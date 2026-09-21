"""Attendance state transitions shared by face-recognition entry points."""


CHECK_IN = "CHECK_IN"
CHECK_OUT = "CHECK_OUT"


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
