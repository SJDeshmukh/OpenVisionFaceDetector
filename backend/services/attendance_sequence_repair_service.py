"""Audit and repair invalid legacy work-attendance state transitions.

The ``attendance`` table is the mutable reporting/payroll projection. Raw
capture evidence remains in ``attendance_events`` where available, while every
projection row removed by this service is copied to
``attendance_repair_audit`` first.

This service deliberately does not fabricate a missing check-in or checkout.
It accepts valid IN/OUT pairs, including multiple pairs on one operational day,
and flags only transitions that cannot be valid in manual work-attendance mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
from typing import Iterable, Optional
import uuid

from services.manual_attendance_action_service import normalize_manual_action


@dataclass(frozen=True)
class AttendanceProjectionRow:
    attendance_id: int
    vendor_id: int
    person_id: int
    name: str
    timestamp: object
    status: str
    attendance_date: object
    device_id: Optional[str] = None
    activity: Optional[str] = None
    source: Optional[str] = None

    @property
    def operational_date(self) -> str:
        stored = self.attendance_date
        if isinstance(stored, (date, datetime)):
            return stored.date().isoformat() if isinstance(stored, datetime) else stored.isoformat()
        if stored not in (None, ""):
            return str(stored)[:10]

        stamp = self.timestamp
        if isinstance(stamp, datetime):
            return stamp.date().isoformat()
        try:
            return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).date().isoformat()
        except (TypeError, ValueError):
            return ""


@dataclass(frozen=True)
class AttendanceSequenceFinding:
    row: AttendanceProjectionRow
    reason: str
    expected_status: str

    @property
    def repair_eligible(self) -> bool:
        # Without the persisted operational date, a post-midnight checkout may
        # legitimately close the previous night shift. Report it, but require a
        # human to resolve it with the employee's historical shift assignment.
        return self.row.attendance_date not in (None, "")

    def as_dict(self) -> dict:
        payload = asdict(self.row)
        payload["timestamp"] = str(self.row.timestamp)
        payload["attendance_date"] = (
            str(self.row.attendance_date) if self.row.attendance_date is not None else None
        )
        payload.update({"reason": self.reason, "expected_status": self.expected_status})
        payload["repair_eligible"] = self.repair_eligible
        return payload


def find_invalid_transitions(
    rows: Iterable[AttendanceProjectionRow],
) -> list[AttendanceSequenceFinding]:
    """Return impossible transitions without modifying the supplied rows.

    State is isolated by tenant, person and operational date. The expected
    sequence is CHECK_IN, CHECK_OUT, CHECK_IN, CHECK_OUT, ... . Unknown legacy
    status labels are left untouched for manual review.
    """

    findings: list[AttendanceSequenceFinding] = []
    expected_by_scope: dict[tuple[int, int, str], str] = {}

    sorted_rows = sorted(
        rows,
        key=lambda item: (
            item.vendor_id,
            item.person_id,
            item.operational_date,
            str(item.timestamp),
            item.attendance_id,
        ),
    )
    for row in sorted_rows:
        normalized = normalize_manual_action(row.status)
        if normalized not in {"CHECK_IN", "CHECK_OUT"}:
            continue

        scope = (row.vendor_id, row.person_id, row.operational_date)
        expected = expected_by_scope.get(scope, "CHECK_IN")
        if normalized != expected:
            reason = (
                "duplicate_check_in"
                if normalized == "CHECK_IN"
                else "checkout_without_open_checkin"
            )
            findings.append(
                AttendanceSequenceFinding(
                    row=row,
                    reason=reason,
                    expected_status=expected,
                )
            )
            continue

        expected_by_scope[scope] = "CHECK_OUT" if expected == "CHECK_IN" else "CHECK_IN"

    return findings


def load_projection_rows(cursor, vendor_id: int, start_date: str, end_date: str):
    """Load one tenant/date range with parameterized filtering."""

    cursor.execute(
        """SELECT a.id, a.vendor_id, a.person_id, a.name, a.timestamp,
                  a.status, a.attendance_date, a.device_id, a.activity,
                  (SELECT MIN(e.source)
                     FROM attendance_events e
                    WHERE e.legacy_attendance_id = a.id) AS source
             FROM attendance a
            WHERE a.vendor_id = ?
              AND a.person_id IS NOT NULL
              AND COALESCE(a.attendance_date, DATE(a.timestamp)) >= ?
              AND COALESCE(a.attendance_date, DATE(a.timestamp)) <= ?
            ORDER BY a.person_id,
                     COALESCE(a.attendance_date, DATE(a.timestamp)),
                     a.timestamp, a.id""",
        (vendor_id, start_date, end_date),
    )
    return [
        AttendanceProjectionRow(
            attendance_id=row[0],
            vendor_id=row[1],
            person_id=row[2],
            name=row[3] or "",
            timestamp=row[4],
            status=row[5] or "",
            attendance_date=row[6],
            device_id=row[7],
            activity=row[8],
            source=row[9],
        )
        for row in (cursor.fetchall() or [])
    ]


def ensure_repair_audit_schema(cursor):
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS attendance_repair_audit (
               id TEXT PRIMARY KEY,
               run_id TEXT NOT NULL,
               vendor_id INTEGER NOT NULL,
               person_id INTEGER NOT NULL,
               original_attendance_id INTEGER NOT NULL,
               attendance_date DATE,
               original_timestamp TIMESTAMP NOT NULL,
               original_status TEXT NOT NULL,
               source TEXT,
               reason TEXT NOT NULL,
               action TEXT NOT NULL,
               ledger_event_ids TEXT NOT NULL DEFAULT '[]',
               row_snapshot TEXT NOT NULL,
               repaired_by TEXT NOT NULL,
               created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
               UNIQUE(vendor_id, original_attendance_id)
           )"""
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS idx_attendance_repair_audit_scope
           ON attendance_repair_audit(vendor_id, person_id, attendance_date)"""
    )


def apply_findings(
    cursor,
    findings: Iterable[AttendanceSequenceFinding],
    *,
    repaired_by: str,
    run_id: Optional[str] = None,
) -> dict:
    """Remove invalid rows from the mutable projection with an audit copy.

    The caller owns the transaction and must commit or roll back. Ledger event
    types and timestamps are not changed. Their projection link is cleared and
    ingestion status is marked rejected so raw evidence remains queryable.
    """

    actor = str(repaired_by or "").strip()
    if not actor:
        raise ValueError("repaired_by is required")

    ensure_repair_audit_schema(cursor)
    resolved_run_id = str(run_id or uuid.uuid4())
    repaired = 0
    skipped = 0
    manual_review = 0

    for finding in findings:
        if not finding.repair_eligible:
            manual_review += 1
            continue
        row = finding.row
        cursor.execute(
            "SELECT * FROM attendance WHERE id = ? AND vendor_id = ? AND person_id = ?",
            (row.attendance_id, row.vendor_id, row.person_id),
        )
        original_row = cursor.fetchone()
        if not original_row:
            skipped += 1
            continue

        column_names = [str(item[0]) for item in (cursor.description or [])]
        complete_snapshot = {}
        for index, column_name in enumerate(column_names):
            try:
                value = original_row[column_name]
            except (KeyError, TypeError, IndexError):
                value = original_row[index]
            complete_snapshot[column_name] = value

        cursor.execute(
            "SELECT id FROM attendance_events WHERE legacy_attendance_id = ? ORDER BY id",
            (row.attendance_id,),
        )
        ledger_event_ids = [str(item[0]) for item in (cursor.fetchall() or [])]
        snapshot = {
            "attendance_row": complete_snapshot,
            "finding": finding.as_dict(),
        }

        cursor.execute(
            """INSERT INTO attendance_repair_audit
               (id, run_id, vendor_id, person_id, original_attendance_id,
                attendance_date, original_timestamp, original_status, source,
                reason, action, ledger_event_ids, row_snapshot, repaired_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), resolved_run_id, row.vendor_id, row.person_id,
                row.attendance_id, row.operational_date or None, str(row.timestamp),
                row.status, row.source, finding.reason,
                "REMOVED_FROM_PROJECTION", json.dumps(ledger_event_ids),
                json.dumps(snapshot, sort_keys=True, default=str), actor,
            ),
        )
        cursor.execute(
            """UPDATE attendance_events
                  SET legacy_attendance_id = NULL, ingestion_status = 'REJECTED'
                WHERE legacy_attendance_id = ?""",
            (row.attendance_id,),
        )
        cursor.execute(
            "DELETE FROM attendance WHERE id = ? AND vendor_id = ? AND person_id = ?",
            (row.attendance_id, row.vendor_id, row.person_id),
        )
        repaired += 1

    return {
        "run_id": resolved_run_id,
        "repaired": repaired,
        "skipped": skipped,
        "manual_review": manual_review,
    }
