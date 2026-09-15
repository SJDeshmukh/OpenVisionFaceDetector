from datetime import datetime

from services.attendance_ingestion_service import (
    AttendanceEventIngestionService,
    LegacyAttendanceEvent,
)
from services.attendance_reconciliation_service import backfill, summarize

from test_attendance_ingestion_service import attendance_db


def test_reconciliation_backfills_missing_ledger_and_is_idempotent():
    conn = attendance_db()
    cursor = conn.cursor()
    first_id = AttendanceEventIngestionService.insert_legacy_event(
        cursor,
        LegacyAttendanceEvent(
            name="Legacy Worker",
            timestamp=datetime(2026, 9, 14, 9, 0),
            status="CHECK_IN",
            vendor_id=5,
            person_id=21,
        ),
    )
    assert first_id == 1
    assert summarize(cursor, 5).missing_ledger == 1

    assert backfill(cursor, 5, source_timezone="Asia/Kolkata") == 1
    assert backfill(cursor, 5, source_timezone="Asia/Kolkata") == 0

    summary = summarize(cursor, 5)
    assert summary.legacy_total == 1
    assert summary.ledger_total == 1
    assert summary.missing_ledger == 0
    assert summary.orphaned_ledger == 0
