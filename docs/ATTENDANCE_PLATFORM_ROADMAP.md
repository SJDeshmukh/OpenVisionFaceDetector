# OpenVisionX Attendance Platform — Implementation Roadmap

## 1. Objective

Evolve the existing face-attendance and payroll product into one reliable attendance platform for corporate employees, factory workers, shift workers, and contractors without interrupting the current attendance flow.

The target processing model is:

```text
Capture source
  -> immutable attendance event
  -> identity/device validation
  -> shift assignment resolution
  -> versioned policy evaluation
  -> daily attendance result
  -> exception/correction workflow
  -> locked payroll input
  -> dashboards, reports, and integrations
```

The current `attendance` table remains operational during migration. New behavior is introduced behind vendor feature flags and compared with existing calculations before becoming authoritative.

## 2. Current-system assessment

OpenVisionX already contains several foundations that should be reused:

- Face/kiosk attendance capture through `/api/person-event`.
- Mobile timestamp support for bounded offline replay.
- Device registration and device activity tracking.
- Shift and activity timetable configuration.
- Multiple punches, payable activities, late detection, and overnight calculations.
- Attendance reports, payroll calculation/export, leave workflows, dashboards, WebSocket updates, and audit logs.
- Multi-tenant vendor scoping and subscription feature flags.

The main structural limitations are:

- `attendance` is simultaneously the captured event and the reporting/payroll source.
- Shift configuration is stored mainly as JSON and employees refer to shifts by text name.
- Calculated daily attendance is recomputed in request/report paths instead of stored as a reproducible versioned result.
- Policy configuration, precedence, effective dates, correction states, and payroll-period locking are not first-class domain objects.
- Attendance inserts occur through live and bulk paths; both must use the same ingestion contract.
- Database access mixes SQLAlchemy, hand-written SQL, runtime schema handling, and Alembic. This makes large schema evolution risky unless one migration path is made authoritative.

## 3. Delivery principles

1. Never rewrite or delete historical punches during ordinary attendance processing.
2. Store event time, receipt time, source, device, timezone, and idempotency identity separately.
3. Version every shift and attendance policy and retain the version used for a calculation.
4. Treat calculated attendance as a projection that can be regenerated from immutable inputs.
5. Corrections create new revisions and audit entries; they never silently overwrite evidence.
6. Payroll reads only approved and locked daily results after the migration is complete.
7. Every table and query is tenant-scoped by `vendor_id` and protected by authorization tests.
8. Release each major capability behind a per-vendor feature flag.
9. PostgreSQL is the production source of truth. SQLite remains suitable for local development/testing or a deliberately specified recovery mode; it must not independently accept production writes that cannot be ordered and reconciled.

## 4. Phase plan

### Phase 0 — Stabilize the foundation

**Estimated duration:** 2–3 weeks

**Goal:** Make subsequent schema and business-rule work safe.

Deliverables:

- Select and document the canonical schema definition and migration workflow.
- Reconcile the active production schema with `database/models.py` and Alembic history.
- Add automated migration tests for both a new database and a copy of the current schema.
- Create a single `AttendanceEventIngestionService`; route live kiosk and bulk attendance through it.
- Define canonical UTC storage and vendor/location timezone conversion rules.
- Introduce structured domain constants for event source, event type, daily status, and workflow status.
- Add correlation IDs and structured logs around event ingestion and calculation.
- Establish baseline test fixtures for day shift, cross-midnight shift, duplicate event, missing punch, and offline replay.

Exit criteria:

- Live and bulk attendance use the same validation and insertion path.
- Existing APIs and dashboard behavior remain backward compatible.
- A clean deployment and an upgrade deployment run migrations successfully.
- PostgreSQL and SQLite test suites produce the same attendance results for the baseline fixtures.

### Phase 1 — Immutable attendance event ledger

**Estimated duration:** 2–3 weeks

**Goal:** Separate captured evidence from calculated attendance.

Add an `attendance_events` table with at least:

```text
id (UUID)
vendor_id
person_id
event_type (IN, OUT, BREAK_START, BREAK_END)
event_time_utc
event_timezone
received_at_utc
source (FACE, RFID, MOBILE, WEB, KIOSK, IMPORT, API)
source_event_id
device_id
location_id (nullable initially)
activity_code
verification_method
verification_score
captured_image_reference
payload_metadata
ingestion_status
created_at
```

Required constraints:

- Unique `(vendor_id, source, source_event_id)` for idempotency.
- Indexed `(vendor_id, person_id, event_time_utc)`.
- Valid foreign keys where migration compatibility permits.
- Events cannot be updated/deleted through normal product APIs.

Implementation and rollout:

- Add an idempotency key to the Android and web capture requests.
- Initially dual-write to `attendance` and `attendance_events` in one transaction.
- Backfill historical `attendance` rows with deterministic legacy source IDs.
- Provide a reconciliation job showing missing, duplicated, or mismatched events.
- Keep the existing reports reading `attendance` during this phase.

Exit criteria:

- Retrying the same offline event produces exactly one stored event.
- Out-of-order events retain their true event time and receipt time.
- Every new legacy attendance row has a corresponding ledger event.
- Reconciliation reaches an agreed accuracy threshold on production-like data (target 99.9%+, with every discrepancy categorized).

### Phase 2 — Organization, locations, shifts, and assignments

**Estimated duration:** 3–4 weeks

**Goal:** Replace shift-name and organization JSON dependencies with effective-dated records.

Add normalized entities:

- `organization_units`: company, office, plant, department, line, work center, and team using a parent-child hierarchy.
- `locations`: address, timezone, geofence, and active status.
- `shifts` and `shift_versions`: start/end, paid duration, grace, cross-midnight behavior, and effective dates.
- `shift_segments`: work and paid/unpaid break windows.
- `shift_assignments`: person/group, shift version, start date, end date, priority, and assignment source.
- `holiday_calendars`, `holidays`, and weekly-off patterns.

Resolution order must be deterministic:

```text
explicit employee assignment
  > roster/group assignment
  > department assignment
  > location default
  > vendor default
```

Implementation and rollout:

- Migrate current company shift JSON into normalized shift versions.
- Map `faces.shift` text to assignments, retaining it temporarily as a compatibility field.
- Build shift CRUD and assignment APIs before changing the timetable UI.
- Add a shift-resolution preview: employee + operational date -> resolved shift and explanation.

Exit criteria:

- Existing shifts migrate without changing attendance calculations.
- A 10 PM–6 AM shift belongs to the configured operational date.
- Changing tomorrow's shift does not change historical attendance.
- Overlapping assignments are rejected or resolved through documented priority.

### Phase 3 — Versioned policy and daily calculation engine

**Estimated duration:** 4–6 weeks

**Goal:** Produce deterministic daily attendance results from events, assignments, leave, and holidays.

Start with typed policy fields, not a general expression-language or no-code rule builder:

- Required/minimum minutes.
- Late and early-out thresholds and grace minutes.
- Half-day and absence thresholds.
- Paid/unpaid break rules.
- Missing-punch behavior.
- First/last versus paired-punch calculation mode.
- Overtime eligibility, threshold, cap, and rounding.
- Holiday and weekly-off work behavior.

Add:

- `attendance_policies` and immutable `attendance_policy_versions`.
- `policy_assignments` using the same explicit precedence model as shifts.
- `daily_attendance` with operational date, resolved shift/policy versions, first-in, last-out, payable minutes, break minutes, late/early/overtime minutes, status, exception codes, calculation version, and revision number.
- `daily_attendance_segments` linking calculated work/break segments to source event IDs.
- `calculation_runs` to track cause, engine version, scope, status, and errors.

Engine requirements:

- Pure calculation core: identical inputs produce identical outputs.
- Explicit exception codes such as `MISSING_OUT`, `UNPAIRED_OUT`, `DUPLICATE_EVENT`, `OUTSIDE_SHIFT`, and `NO_SHIFT`.
- Targeted recalculation when an event, shift, policy, holiday, leave, or approved correction changes.
- Full-period recalculation tool for administrators, with preview and audit trail.

Rollout:

- Run the new engine in shadow mode beside current calculations.
- Provide an internal comparison report by vendor/day/person.
- Categorize differences as intended rule improvement, legacy defect, configuration issue, or new-engine defect.
- Turn on new daily results vendor-by-vendor only after sign-off.

Exit criteria:

- Golden tests cover at least 30 agreed scenarios, including multiple punches, midnight, leave overlap, breaks, grace, overtime, missing punches, and device drift.
- Recalculation is idempotent and historical results retain their shift/policy versions.
- Shadow differences are reviewed and within the agreed threshold.

### Phase 4 — Exceptions, corrections, approvals, and audit

**Estimated duration:** 3–4 weeks

**Goal:** Make attendance disputes and manual actions controlled and traceable.

Add:

- `attendance_correction_requests` containing requested punch/status change, reason, evidence, requester, and state.
- `approval_workflows`, `approval_steps`, and effective-dated workflow assignments.
- `approval_instances` and `approval_actions` for actual requests.
- `attendance_adjustments` as immutable approved overrides applied on top of calculated results.
- Dedicated attendance audit records containing before/after snapshots and reason.

Initial state machine:

```text
DRAFT -> SUBMITTED -> APPROVED | REJECTED | CANCELLED
                       |
                       -> daily attendance recalculation
```

Keep the first release to one configurable manager/HR chain. Do not begin with a visual workflow builder.

UI deliverables:

- Employee correction submission.
- Manager exception inbox.
- HR daily record detail showing source events, calculated segments, policy explanation, corrections, and audit timeline.

Exit criteria:

- No approved edit removes or changes a raw event.
- Unauthorized supervisors cannot see or approve employees outside their scope.
- Concurrent approvals cannot approve the same step twice.
- Every changed payroll-relevant value has actor, timestamp, reason, and before/after evidence.

### Phase 5 — Payroll close and trustworthy exports

**Estimated duration:** 3–4 weeks

**Goal:** Prevent payroll from changing unexpectedly after review.

Add:

- `payroll_periods` with OPEN, REVIEW, LOCKED, EXPORTED, and REOPENED states.
- `payroll_attendance_inputs` as a snapshot of approved daily results.
- Overtime approval records and separate earning codes.
- Export mappings for payable days, paid/unpaid leave, LOP, OT, holiday work, weekly-off work, late deductions, comp-off, and shift allowance.
- Reopen permission requiring reason and audit entry.

Migration:

- Compare existing payroll reports with new attendance-input snapshots for at least two complete pay periods.
- Keep salary/statutory calculation in the existing payroll service initially; replace only its attendance inputs.

Exit criteria:

- Locking a period creates a reproducible snapshot.
- New punches or policy changes cannot silently alter a locked period.
- Reopening and relocking produces a new audited revision.
- CSV/XLSX totals reconcile with dashboard totals and approved daily records.

### Phase 6 — Manufacturing operations

**Estimated duration:** 4–6 weeks

**Goal:** Add factory-specific value after the attendance core is trustworthy.

Deliverables:

- Plant, gate, production line, work center, supervisor, skill, and certification assignments.
- Contractor companies, contract validity, worker assignments, and gate-pass status.
- Device adapters for face, RFID, and supported biometric/access-control systems using the Phase 1 ingestion contract.
- Device heartbeat, clock offset, last-sync time, queue depth, firmware/app version, and health alerts.
- Offline queue with signed device identity, monotonically ordered local sequence, retry, and reconciliation.
- Real-time required-versus-present manpower by plant/line/shift and qualified-worker coverage.
- Contractor attendance and approved billable-hours export.

Important boundary: gate presence, attendance, line deployment, and payroll eligibility are distinct facts even when they derive from the same event.

Exit criteria:

- A device can remain offline, replay events, and create no duplicates after reconnection.
- Dashboard counts are traceable to employees and source events.
- Expired contractor or gate-pass conditions are visibly flagged without silently changing historical attendance.

### Phase 7 — Corporate, mobile, and enterprise integrations

**Estimated duration:** 4–6 weeks

**Goal:** Support hybrid/corporate attendance and external ecosystems.

Deliverables:

- Flexible hours, core hours, WFH, hybrid schedules, mobile/web attendance, and office IP/geofence policies.
- Device binding, selfie/face verification, liveness result, and controlled manual fallback.
- SSO and directory provisioning.
- Versioned public APIs and signed webhooks with replay protection.
- HRMS/payroll connectors based on the locked payroll input contract.
- Multi-country timezone, holiday, retention, and localization configuration.

Exit criteria:

- Location and identity failures return explicit reason codes.
- Webhooks are idempotent, signed, retryable, and observable.
- Biometric and location retention/deletion settings are enforceable per tenant.

### Phase 8 — Advanced analytics and configurable automation

**Estimated duration:** ongoing

Only after sufficient stable production data:

- Absence, overtime, late, correction, and device-failure trends.
- Staffing forecasts and skill-gap alerts.
- Anomaly indicators for HR review, never automatic disciplinary decisions.
- Visual workflow builder if real customer workflows justify it.
- Advanced policy composition after typed rules prove insufficient.

## 5. API evolution

Recommended resource families:

```text
/api/v2/attendance-events
/api/v2/daily-attendance
/api/v2/attendance-corrections
/api/v2/attendance-exceptions
/api/v2/shifts
/api/v2/shift-assignments
/api/v2/attendance-policies
/api/v2/approval-workflows
/api/v2/payroll-periods
/api/v2/devices
/api/v2/organization-units
```

Keep `/api/person-event` available as a compatibility adapter that calls the new ingestion service. Avoid making devices understand policy or payroll rules.

## 6. Cross-cutting work required in every phase

### Security and privacy

- Tenant isolation tests for every read/write endpoint.
- Granular permissions and scoped supervisor access.
- Encrypt sensitive biometric references and credentials; never return templates in ordinary APIs.
- Configurable image/template retention and audited deletion.
- Record consent/legal-basis metadata as required by the deployment jurisdiction.
- Use short-lived signed URLs for evidence images rather than embedding large base64 data in routine records.

### Reliability and observability

- Metrics: ingestion success/failure, duplicate rate, sync lag, device clock offset, calculation latency/failure, exception rate, correction rate, and payroll reconciliation differences.
- Dead-letter/retry handling for asynchronous calculations and integrations.
- Health dashboard with per-device and per-worker/job state.
- Restore drills and point-in-time database recovery for production.

### Testing

- Unit tests for pure calculation rules.
- Golden scenario tests supplied and signed off by HR/payroll users.
- Database contract tests on PostgreSQL and supported SQLite development mode.
- API authorization and tenant-boundary tests.
- Migration/backfill/reconciliation tests.
- Android offline/retry and duplicate-delivery tests.
- End-to-end tests from punch to daily result to approved payroll export.
- Load tests for shift-change peaks and bulk offline synchronization.

## 7. Recommended release cadence

Use two-week sprints and release a production-safe increment at the end of each phase. Suggested milestones:

| Milestone | Approximate target | Usable result |
|---|---:|---|
| M0 | Week 3 | Stable schema and unified ingestion |
| M1 | Week 6 | Immutable, deduplicated event ledger |
| M2 | Week 10 | Normalized shifts and assignments |
| M3 | Week 16 | Shadow-tested daily policy engine |
| M4 | Week 20 | Corrections and approval workflow |
| M5 | Week 24 | Locked, reproducible payroll inputs |
| M6 | Week 30 | Factory, contractor, device health, manpower |
| M7 | Week 36 | Corporate/hybrid and enterprise integration |

These are sequencing estimates, not commitments. Actual dates depend on team size, production data quality, and how many current APIs must remain compatible.

## 8. Team order of work per phase

For each phase, use this order:

1. Agree on scenarios and acceptance criteria with an HR/payroll domain owner.
2. Write an architecture decision record and schema/API contract.
3. Add migrations and backfill/reconciliation tooling.
4. Implement domain service and unit/golden tests.
5. Add authenticated APIs and authorization tests.
6. Update web/Android clients.
7. Run shadow or dual-write mode and measure differences.
8. Pilot with one internal/demo vendor, then one real vendor.
9. Enable vendor-by-vendor with rollback flags.
10. Remove the legacy path only after telemetry shows that it is unused and migration reconciliation is complete.

## 9. What not to build first

Defer these until the core engine and payroll close are proven:

- A generic drag-and-drop rule language.
- A visual approval-workflow designer.
- Many proprietary biometric integrations at once.
- Predictive AI for absenteeism or workforce discipline.
- PLC/machine integration without a specific validated customer use case.
- Fully generic multi-country payroll calculation.

## 10. First implementation backlog

The first three sprints should produce:

### Sprint 1

- Architecture decisions for event identity, UTC/timezone rules, canonical migrations, and production database responsibility.
- Current-schema inventory and migration test harness.
- Attendance scenario fixture pack and current-result baseline.
- Interface for `AttendanceEventIngestionService`.

### Sprint 2

- `attendance_events` migration and repository/service.
- `/api/person-event` dual-write through the ingestion service.
- Idempotency support in capture payload validation and Android client.
- Metrics and structured logs.

### Sprint 3

- Bulk attendance migrated to the same service.
- Historical event backfill and reconciliation command.
- Operations view/report for discrepancies and rejected events.
- Pilot feature flag and rollback procedure.

Do not start the general policy engine until these three sprints are accepted. They provide the evidence layer on which every later attendance, approval, and payroll feature depends.
