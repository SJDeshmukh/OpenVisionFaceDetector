import sqlite3
from datetime import date, datetime

from services.attendance_query_service import (
    build_operational_date_filter,
    resolve_operational_date,
)
from services.attendance_shift_service import ShiftPolicy


def test_history_filter_uses_persisted_operational_date_and_legacy_fallback():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """CREATE TABLE attendance (
               id INTEGER PRIMARY KEY,
               vendor_id INTEGER,
               timestamp DATETIME,
               attendance_date DATE
           )"""
    )
    connection.executemany(
        "INSERT INTO attendance VALUES (?, 8, ?, ?)",
        [
            # Its stored shift day must win even if its current shift changed.
            (1, "2026-11-02 05:30:00", "2026-11-01"),
            # Pre-migration rows still use their timestamp as a fallback.
            (2, "2026-11-01 12:00:00", None),
            (3, "2026-11-02 12:00:00", "2026-11-02"),
        ],
    )

    clause, params = build_operational_date_filter(
        "2026-11-01", "2026-11-01"
    )
    rows = connection.execute(
        f"SELECT a.id FROM attendance a WHERE a.vendor_id = ?{clause} ORDER BY a.id",
        [8, *params],
    ).fetchall()

    assert rows == [(1,), (2,)]


def test_response_keeps_captured_operational_date_after_shift_change():
    current_day_shift = ShiftPolicy(None, "Day", "09:00", "17:00")
    timestamp = datetime(2026, 11, 2, 5, 30)

    assert current_day_shift.attendance_date(timestamp) == date(2026, 11, 2)
    assert resolve_operational_date(
        "2026-11-01", timestamp, current_day_shift
    ) == date(2026, 11, 1)
