# ADR 0001: Attendance data ownership and time handling

- Status: Accepted for Phase 0
- Date: 2026-09-15

## Context

The product currently supports PostgreSQL and SQLite through a compatibility
wrapper and also contains SQLAlchemy models, runtime schema creation, and
Alembic migrations. Attendance writes originate in live and bulk routes.
Changing attendance rules before establishing one write contract would cause
different capture paths to produce different data.

## Decision

1. PostgreSQL is the production system of record.
2. Alembic will become the canonical production schema migration mechanism.
   Runtime schema creation remains temporarily for compatibility and will be
   reduced only after upgrade tests cover deployed schemas.
3. All attendance capture paths write through
   `AttendanceEventIngestionService` inside a caller-owned transaction.
4. Phase 0 retains existing naive timestamps to avoid a breaking data change.
5. Phase 1 ledger events will store UTC event and receipt timestamps plus the
   IANA timezone used to interpret the event.
6. A client timestamp is accepted only for bounded offline replay. Live events
   use server time; implausible timestamps fall back to server time and are
   observable.
7. SQLite is supported for development, automated tests, and explicitly
   designed recovery. It is not an independent multi-writer production source
   of truth.

## Consequences

- Routes keep their current transaction boundaries and response contracts.
- Phase 1 can dual-write without duplicating changes across live and bulk paths.
- Existing production data needs an inventory and tested Alembic baseline before
  runtime migrations can be removed.
- Timezone-aware storage is postponed to the immutable ledger rather than
  silently reinterpreting historical naive timestamps.
