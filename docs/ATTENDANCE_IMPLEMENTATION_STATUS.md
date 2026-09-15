# Attendance Platform Implementation Status

Last updated: 2026-09-15

This file tracks implementation against `ATTENDANCE_PLATFORM_ROADMAP.md`.

| Phase | Status | Implemented | Remaining |
|---|---|---|---|
| 0 — Foundation | In progress | Canonical ingestion service, shared domain constants, centralized bounded time resolution, architecture decision, focused tests | Production schema inventory, upgrade-migration fixture, structured metrics/correlation IDs, redirect any remaining non-route attendance writers |
| 1 — Event ledger | In progress | Additive schema/model/migration, transactional legacy+ledger writes, source idempotency, UTC conversion with source timezone, Android idempotency payload, backfill and reconciliation command | Production shadow reconciliation, concurrent duplicate race handling, operations UI, per-vendor rollout flag |
| 2 — Structure and shifts | In progress | Locations, organization hierarchy, person memberships, versioned shifts/segments, effective assignments, holidays/weekly offs, deterministic tenant-scoped resolver, authenticated v2 configuration/preview APIs | Legacy JSON migration command, update/version endpoints, dashboard UI, integration tests |
| 3 — Policy engine | Not started | — | Full phase |
| 4 — Corrections/approvals | Not started | — | Full phase |
| 5 — Payroll close | Not started | — | Full phase |
| 6 — Manufacturing | Not started | — | Full phase |
| 7 — Corporate/enterprise | Not started | — | Full phase |
| 8 — Analytics | Not started | — | Full phase |

## Verification log

- Backend focused unit tests: 13 passing.
- Python compile checks: passing for new and changed backend modules.
- `git diff --check`: passing.
- Android compile: blocked by missing Android SDK configuration on this host. Gradle 8.13 and Java 17 are otherwise selected correctly.

## Compatibility state

- Existing `/api/person-event` response and legacy `attendance` writes remain available.
- Reports and payroll still read the legacy `attendance` table.
- New ledger writes occur in the same caller-owned transaction as legacy writes.
- Normalized shift APIs are additive under `/api/v2`; current timetable APIs remain unchanged.
