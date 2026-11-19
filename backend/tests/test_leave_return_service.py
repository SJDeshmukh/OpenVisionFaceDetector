import sqlite3
from datetime import datetime

from services.leave_return_service import complete_leave_on_hostel_entry


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE leave_requests (
               id INTEGER PRIMARY KEY, vendor_id INTEGER, student_id INTEGER,
               start_date TEXT, start_time TEXT, end_date TEXT, end_time TEXT,
               final_status TEXT
           )"""
    )
    return conn


def test_early_hostel_entry_completes_started_approved_leave():
    conn = _connection()
    conn.execute(
        "INSERT INTO leave_requests VALUES (1, 7, 10, '2026-11-19', '08:00', '2026-11-21', '20:00', 'approved')"
    )

    leave_id = complete_leave_on_hostel_entry(
        conn.cursor(), 7, 10, datetime(2026, 11, 20, 9, 30), "CHECK_IN"
    )

    assert leave_id == 1
    assert conn.execute("SELECT final_status FROM leave_requests WHERE id = 1").fetchone()[0] == "completed"


def test_exit_and_future_leave_do_not_complete_leave():
    conn = _connection()
    conn.execute(
        "INSERT INTO leave_requests VALUES (1, 7, 10, '2026-11-21', '08:00', '2026-11-22', '20:00', 'approved')"
    )

    assert complete_leave_on_hostel_entry(
        conn.cursor(), 7, 10, datetime(2026, 11, 20, 9, 30), "CHECK_IN"
    ) is None
    assert complete_leave_on_hostel_entry(
        conn.cursor(), 7, 10, datetime(2026, 11, 21, 9, 30), "CHECK_OUT"
    ) is None
    assert conn.execute("SELECT final_status FROM leave_requests WHERE id = 1").fetchone()[0] == "approved"


def test_completion_is_tenant_and_person_scoped():
    conn = _connection()
    conn.execute(
        "INSERT INTO leave_requests VALUES (1, 8, 11, '2026-11-19', '08:00', '2026-11-21', '20:00', 'approved')"
    )

    assert complete_leave_on_hostel_entry(
        conn.cursor(), 7, 10, datetime(2026, 11, 20, 9, 30), "CHECK_IN"
    ) is None
    assert conn.execute("SELECT final_status FROM leave_requests WHERE id = 1").fetchone()[0] == "approved"
