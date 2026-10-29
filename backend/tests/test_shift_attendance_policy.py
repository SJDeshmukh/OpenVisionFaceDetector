import sqlite3
from datetime import date, datetime

from services.attendance_shift_service import (
    ShiftPolicy,
    calculate_shift_wage,
    choose_shift_policy,
    scheduled_payable_hours,
)
from services.attendance_state_service import next_attendance_status, reconcile_person_timeline
from services.attendance_service import calculate_daily_hours


def _work_shift():
    return ShiftPolicy("work", "Work", "06:00", "05:59", assigned=True)


def test_early_morning_punch_belongs_to_previous_shift_day():
    policy = _work_shift()

    assert policy.attendance_date(datetime(2026, 10, 29, 5, 59, 59)) == date(2026, 10, 28)
    assert policy.attendance_date(datetime(2026, 10, 29, 6, 0, 0)) == date(2026, 10, 29)
    assert scheduled_payable_hours(policy, 8) == 8


def test_open_checkin_over_16_hours_checks_out_within_same_shift_day():
    assert next_attendance_status(
        "CHECK_IN",
        hours_since_last=21,
        last_attendance_date=date(2026, 10, 28),
        current_attendance_date=date(2026, 10, 28),
    ) == "CHECK_OUT"
    assert next_attendance_status(
        "CHECK_IN",
        hours_since_last=22,
        last_attendance_date=date(2026, 10, 28),
        current_attendance_date=date(2026, 10, 29),
    ) == "CHECK_IN"


def test_offline_timeline_reconciles_across_assigned_shift_boundary():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE attendance (
            id INTEGER PRIMARY KEY, timestamp TEXT, status TEXT,
            vendor_id INTEGER, person_id INTEGER, attendance_date DATE
        );
        CREATE TABLE attendance_events (
            id TEXT PRIMARY KEY, legacy_attendance_id INTEGER, source TEXT,
            event_type TEXT, vendor_id INTEGER
        );
        """
    )
    rows = [
        (1, "2026-10-28 08:47:41", "CHECK_IN", 8, 101, None),
        (2, "2026-10-29 05:35:49", "CHECK_IN", 8, 101, None),
        (3, "2026-10-29 07:00:41", "CHECK_OUT", 8, 101, None),
    ]
    connection.executemany("INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.executemany(
        "INSERT INTO attendance_events VALUES (?, ?, 'KIOSK', ?, 8)",
        [("a", 1, "CHECK_IN"), ("b", 2, "CHECK_IN"), ("c", 3, "CHECK_OUT")],
    )

    result = reconcile_person_timeline(
        connection.cursor(), 8, 101, target_attendance_id=2, shift_policy=_work_shift()
    )

    assert connection.execute(
        "SELECT status, attendance_date FROM attendance ORDER BY timestamp"
    ).fetchall() == [
        ("CHECK_IN", "2026-10-28"),
        ("CHECK_OUT", "2026-10-28"),
        ("CHECK_IN", "2026-10-29"),
    ]
    assert result.target_status == "CHECK_OUT"
    assert result.latest_status == "CHECK_IN"


def test_assigned_shift_controls_hours_overtime_and_wages():
    policy = choose_shift_policy(
        [{"id": 1, "name": "Day", "start_time": "09:00", "end_time": "17:00"}],
        "Day",
    )
    result = calculate_shift_wage(
        800,
        {date(2026, 10, 28): 10 * 3600},
        policy.scheduled_hours,
        overtime_multiplier=1.5,
    )

    assert policy.scheduled_hours == 8
    assert result == {
        "regular_hours": 8.0,
        "overtime_hours": 2.0,
        "hourly_rate": 100.0,
        "regular_wage": 800.0,
        "overtime_wage": 300.0,
        "gross_wage": 1100.0,
    }


def test_cross_day_session_is_one_attendance_day_with_actual_hours():
    policy = _work_shift()
    stats = calculate_daily_hours(
        [
            {"timestamp": "2026-10-28 08:47:41", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2026-10-29 05:35:49", "status": "CHECK_OUT", "activity": "Work"},
        ],
        shift_policy=policy,
        working_hours=8,
    )

    assert stats["total_hours"] == 20.8
    assert len(stats["sessions"]) == 1
    assert stats["sessions"][0]["attendance_date"] == "2026-10-28"
