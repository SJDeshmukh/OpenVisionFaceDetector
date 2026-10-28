"""Attendance state transitions shared by face-recognition entry points."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


CHECK_IN = "CHECK_IN"
CHECK_OUT = "CHECK_OUT"


@dataclass(frozen=True)
class TimelineReconciliation:
    target_status: Optional[str]
    target_timestamp: Optional[str]
    latest_status: Optional[str]
    latest_timestamp: Optional[str]
    changed_count: int = 0


def next_attendance_status(last_status=None, hours_since_last=None, hostel_mode=False):
    """Return the next punch status without coupling it to a device or database.

    Normal attendance starts with CHECK_IN and treats an open session older than
    16 hours as a fresh CHECK_IN. Hostel movement starts with CHECK_OUT because
    a resident is assumed to be inside before their first exit scan. Hostel
    movement always alternates globally and deliberately ignores the 16-hour
    work-session reset.
    """
    normalized = str(last_status or "").strip().upper()

    if hostel_mode:
        if not normalized:
            return CHECK_OUT
        return CHECK_OUT if normalized == CHECK_IN else CHECK_IN

    if normalized != CHECK_IN:
        return CHECK_IN
    try:
        if hours_since_last is not None and float(hours_since_last) > 16:
            return CHECK_IN
    except (TypeError, ValueError):
        pass
    return CHECK_OUT


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _as_timestamp(value):
    parsed = _as_datetime(value)
    if parsed is not None:
        return parsed.isoformat(timespec="milliseconds")
    return str(value) if value not in (None, "") else None


def reconcile_person_timeline(
    cursor,
    vendor_id,
    person_id,
    *,
    target_attendance_id=None,
    hostel_mode=False,
):
    """Rebuild the mutable attendance projection in chronological order.

    ``attendance_events`` remains the immutable capture ledger. Only kiosk
    punches are derived automatically; imported/manual/legacy statuses act as
    anchors. This lets a late upload from one offline kiosk correct later kiosk
    projections that were recorded before the missing event was known.
    """

    cursor.execute(
        """SELECT a.id, a.timestamp, a.status, COALESCE(e.source, '')
           FROM attendance a
           LEFT JOIN attendance_events e ON e.legacy_attendance_id = a.id
           WHERE a.vendor_id = ? AND a.person_id = ?
           ORDER BY a.timestamp ASC, a.id ASC""",
        (vendor_id, person_id),
    )
    rows = cursor.fetchall() or []

    last_status = None
    last_time = None
    target_status = None
    target_timestamp = None
    latest_status = None
    latest_timestamp = None
    changed_count = 0

    for row in rows:
        attendance_id, timestamp, stored_status, source = row[0], row[1], row[2], row[3]
        parsed_time = _as_datetime(timestamp)
        normalized_stored = str(stored_status or "").strip().upper()
        source = str(source or "").strip().upper()

        # Kiosk punches are automatic face events. Other sources may contain a
        # deliberate status and therefore remain authoritative timeline anchors.
        if source == "KIOSK" or normalized_stored not in (CHECK_IN, CHECK_OUT):
            hours_since_last = None
            if parsed_time is not None and last_time is not None:
                try:
                    hours_since_last = (parsed_time - last_time).total_seconds() / 3600.0
                except (TypeError, ValueError):
                    hours_since_last = None
            resolved_status = next_attendance_status(
                last_status,
                hours_since_last=hours_since_last,
                hostel_mode=hostel_mode,
            )
        else:
            resolved_status = normalized_stored

        if resolved_status != normalized_stored:
            cursor.execute(
                "UPDATE attendance SET status = ? WHERE id = ? AND vendor_id = ? AND person_id = ?",
                (resolved_status, attendance_id, vendor_id, person_id),
            )
            changed_count += 1

        rendered_timestamp = _as_timestamp(timestamp)
        if target_attendance_id is not None and str(attendance_id) == str(target_attendance_id):
            target_status = resolved_status
            target_timestamp = rendered_timestamp

        last_status = resolved_status
        if parsed_time is not None:
            last_time = parsed_time
        latest_status = resolved_status
        latest_timestamp = rendered_timestamp

    return TimelineReconciliation(
        target_status=target_status,
        target_timestamp=target_timestamp,
        latest_status=latest_status,
        latest_timestamp=latest_timestamp,
        changed_count=changed_count,
    )


def latest_person_state(cursor, vendor_id, person_id):
    cursor.execute(
        """SELECT status, timestamp
           FROM attendance
           WHERE vendor_id = ? AND person_id = ?
           ORDER BY timestamp DESC, id DESC
           LIMIT 1""",
        (vendor_id, person_id),
    )
    row = cursor.fetchone()
    if not row:
        return None, None
    return str(row[0] or "").strip().upper() or None, _as_timestamp(row[1])
