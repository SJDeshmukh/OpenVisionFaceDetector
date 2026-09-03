from datetime import datetime
import json
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from services import automated_reports_service as service
from services.automated_reports_service import DEFAULT_SCHEDULE, due_periods, validate_schedule


def schedule(**overrides):
    value = dict(DEFAULT_SCHEDULE)
    value.update({
        "enabled": True,
        "recipient_email": "vendor@example.com",
        "frequencies": ["daily"],
    })
    value.update(overrides)
    return validate_schedule(value)


def test_daily_report_runs_next_morning_for_selected_operational_day():
    config = schedule(daily_days=["Mon"])
    now = datetime(2026, 9, 1, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # Tuesday
    assert due_periods(config, now) == [
        ("daily", datetime(2026, 8, 31).date(), datetime(2026, 8, 31).date())
    ]


def test_night_shift_period_waits_for_cutoff_and_grace():
    with pytest.raises(ValueError, match="after the operational cutoff"):
        schedule(daily_days=["Mon"], send_time="07:15", operational_day_cutoff="07:00", grace_minutes=30)


def test_weekly_period_contains_seven_completed_operational_days():
    config = schedule(frequencies=["weekly"], weekly_days=["Sun"])
    now = datetime(2026, 9, 7, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # Monday
    assert due_periods(config, now) == [
        ("weekly", datetime(2026, 8, 31).date(), datetime(2026, 9, 6).date())
    ]


def test_last_working_day_uses_vendor_timetable_days():
    config = schedule(frequencies=["monthly"], monthly_mode="last_working_day")
    now = datetime(2026, 9, 1, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    result = due_periods(config, now, {"Mon", "Tue", "Wed", "Thu", "Fri"})
    assert result == [("monthly", datetime(2026, 8, 1).date(), datetime(2026, 8, 31).date())]


def test_specific_monthly_day_caps_to_month_end():
    config = schedule(frequencies=["monthly"], monthly_mode="day_of_month", monthly_day=31)
    now = datetime(2026, 5, 1, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert due_periods(config, now) == [
        ("monthly", datetime(2026, 4, 1).date(), datetime(2026, 4, 30).date())
    ]


def test_dispatch_claim_is_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "reports.sqlite"

    def connection():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    conn = connection()
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, company_name TEXT, email TEXT, status TEXT);
        CREATE TABLE subscriptions (vendor_id INTEGER, features TEXT);
        CREATE TABLE companies (vendor_id INTEGER, live_timetable TEXT);
        CREATE TABLE automated_report_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER UNIQUE, enabled INTEGER,
            recipient_email TEXT, timezone TEXT, send_time TEXT, operational_day_cutoff TEXT,
            grace_minutes INTEGER, frequencies TEXT, daily_days TEXT, weekly_days TEXT,
            monthly_mode TEXT, monthly_day INTEGER, report_types TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE automated_report_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id INTEGER, vendor_id INTEGER,
            frequency TEXT, period_start DATE, period_end DATE, status TEXT, recipient_email TEXT,
            UNIQUE(schedule_id, frequency, period_start, period_end)
        );
    """)
    conn.execute("INSERT INTO vendors VALUES (1, 'Night Works', 'vendor@example.com', 'active')")
    conn.execute("INSERT INTO subscriptions VALUES (1, ?)", (json.dumps(["reports", "automated_email_reports"]),))
    conn.execute("INSERT INTO companies VALUES (1, ?)", (json.dumps([{"days": ["Mon"], "enabled": True}]),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(service, "_get_db_connection", connection)

    service.save_schedule(1, schedule(daily_days=["Mon"]))
    now = datetime(2026, 9, 1, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    first = service.dispatch_due_reports(now)
    second = service.dispatch_due_reports(now)
    assert len(first) == 1
    assert second == []
