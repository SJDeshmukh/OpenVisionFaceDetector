"""Complete approved hostel leave when a resident records their return entry."""

from datetime import date, datetime, time


def _date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _time_value(value, fallback):
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()[:8]
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except (TypeError, ValueError):
            continue
    return fallback


def complete_leave_on_hostel_entry(cursor, vendor_id, person_id, event_time, event_status):
    """Mark the latest started approved leave completed after a hostel entry.

    The caller owns the transaction, allowing the attendance event and leave
    transition to commit or roll back together. Future leave is never changed.
    """

    if str(event_status or "").strip().upper() != "CHECK_IN":
        return None
    if not vendor_id or not person_id or not isinstance(event_time, datetime):
        return None

    cursor.execute(
        """SELECT id, start_date, start_time
           FROM leave_requests
           WHERE vendor_id = ? AND student_id = ?
             AND LOWER(TRIM(COALESCE(final_status, ''))) = 'approved'
           ORDER BY start_date DESC, start_time DESC, id DESC""",
        (vendor_id, person_id),
    )
    for row in cursor.fetchall() or []:
        leave_id, start_date, start_time = row[0], row[1], row[2]
        start_day = _date_value(start_date)
        if start_day is None:
            continue
        leave_start = datetime.combine(start_day, _time_value(start_time, time.min))
        if event_time < leave_start:
            continue
        cursor.execute(
            """UPDATE leave_requests
               SET final_status = 'completed'
               WHERE id = ? AND vendor_id = ? AND student_id = ?
                 AND LOWER(TRIM(COALESCE(final_status, ''))) = 'approved'""",
            (leave_id, vendor_id, person_id),
        )
        return leave_id if cursor.rowcount else None
    return None
