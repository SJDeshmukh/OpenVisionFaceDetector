"""Reconcile and backfill the immutable event ledger against legacy punches."""

from dataclasses import dataclass
import os

from domain.attendance import AttendanceEventSource
from services.attendance_ingestion_service import (
    AttendanceEventIngestionService,
    LegacyAttendanceEvent,
)


@dataclass(frozen=True)
class ReconciliationSummary:
    legacy_total: int
    ledger_total: int
    missing_ledger: int
    orphaned_ledger: int
    backfilled: int = 0


def summarize(cursor, vendor_id=None) -> ReconciliationSummary:
    vendor_clause = " WHERE vendor_id = ?" if vendor_id is not None else ""
    params = (vendor_id,) if vendor_id is not None else ()

    cursor.execute(f"SELECT COUNT(*) FROM attendance{vendor_clause}", params)
    legacy_total = int(cursor.fetchone()[0])
    cursor.execute(f"SELECT COUNT(*) FROM attendance_events{vendor_clause}", params)
    ledger_total = int(cursor.fetchone()[0])

    missing_sql = """SELECT COUNT(*) FROM attendance a
        LEFT JOIN attendance_events e ON e.legacy_attendance_id = a.id
        WHERE e.id IS NULL"""
    orphan_sql = """SELECT COUNT(*) FROM attendance_events e
        LEFT JOIN attendance a ON a.id = e.legacy_attendance_id
        WHERE e.legacy_attendance_id IS NOT NULL AND a.id IS NULL"""
    scoped_params = ()
    if vendor_id is not None:
        missing_sql += " AND a.vendor_id = ?"
        orphan_sql += " AND e.vendor_id = ?"
        scoped_params = (vendor_id,)
    cursor.execute(missing_sql, scoped_params)
    missing = int(cursor.fetchone()[0])
    cursor.execute(orphan_sql, scoped_params)
    orphaned = int(cursor.fetchone()[0])

    return ReconciliationSummary(legacy_total, ledger_total, missing, orphaned)


def backfill(cursor, vendor_id=None, *, source_timezone=None) -> int:
    """Backfill ledger projections for valid legacy person attendance rows."""

    sql = """SELECT a.id, a.name, a.timestamp, a.status, a.vendor_id,
                    a.person_id, a.captured_image, a.activity, a.is_late,
                    a.device_id
             FROM attendance a
             LEFT JOIN attendance_events e ON e.legacy_attendance_id = a.id
             WHERE e.id IS NULL AND a.vendor_id IS NOT NULL AND a.person_id IS NOT NULL"""
    params = ()
    if vendor_id is not None:
        sql += " AND a.vendor_id = ?"
        params = (vendor_id,)
    sql += " ORDER BY a.id"
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    timezone_name = source_timezone or os.environ.get("DEFAULT_TIMEZONE", "Asia/Kolkata")
    count = 0
    for row in rows:
        event = LegacyAttendanceEvent(
            name=row[1],
            timestamp=row[2],
            status=row[3],
            vendor_id=row[4],
            person_id=row[5],
            captured_image=row[6],
            activity=row[7] or "Work",
            is_late=int(row[8] or 0),
            device_id=row[9],
            source=AttendanceEventSource.LEGACY.value,
            source_event_id=f"legacy:attendance:{row[0]}",
            source_timezone=timezone_name,
            payload_metadata={"backfilled": True},
        )
        result = AttendanceEventIngestionService.insert_ledger_projection(
            cursor, event, row[0], event.source_event_id
        )
        if not result.duplicate:
            count += 1
    return count
