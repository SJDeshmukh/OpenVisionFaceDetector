import json
import sqlite3
import sys
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import xchat_tools
from services.xchat_presenter import build_presentation


def _connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def feature_db(tmp_path, monkeypatch):
    path = tmp_path / "xchat_features.sqlite"
    conn = _connection(path)
    conn.executescript("""
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, department TEXT,
            designation TEXT, shift TEXT, daily_wage REAL, display_id INTEGER
        );
        CREATE TABLE vendor_devices (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, device_id TEXT, device_name TEXT,
            registered_at TEXT, last_login_at TEXT, last_active_at TEXT, battery_level REAL,
            geofence_lat REAL, geofence_lng REAL, geofence_radius REAL, last_lat REAL, last_lng REAL
        );
        CREATE TABLE companies (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, working_hours REAL,
            shifts TEXT, live_timetable TEXT, last_modified_at TEXT, published_at TEXT
        );
        CREATE TABLE leave_requests (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, student_id INTEGER, leave_type TEXT,
            start_date TEXT, end_date TEXT, final_status TEXT, created_at TEXT
        );
        CREATE TABLE classes (id INTEGER PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE lectures (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, subject TEXT, class_year TEXT,
            division TEXT, branch TEXT, lecture_date TEXT, start_time TEXT, teacher TEXT
        );
        CREATE TABLE lecture_attendance (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, lecture_id INTEGER, person_id INTEGER
        );
        CREATE TABLE automated_report_schedules (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, enabled INTEGER, recipient_email TEXT,
            timezone TEXT, send_time TEXT, frequencies TEXT, report_types TEXT, updated_at TEXT
        );
        CREATE TABLE automated_report_deliveries (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, frequency TEXT, period_start TEXT,
            period_end TEXT, status TEXT, recipient_email TEXT, error TEXT, created_at TEXT, sent_at TEXT
        );
        CREATE TABLE parent_users (id INTEGER PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE student_parents (id INTEGER PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE face_reset_requests (id INTEGER PRIMARY KEY, vendor_id INTEGER, status TEXT);
    """)
    conn.executemany("INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 1, "Alpha User", "Ops", "Operator", "Night", 800, 101),
        (2, 2, "Beta User", "Finance", "Manager", "Day", 9000, 201),
    ])
    conn.executemany("INSERT INTO vendor_devices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 1, "alpha-device", "Alpha Camera", "2026-08-01", None, "2026-09-03 08:00", 75, 1, 1, 150, 1, 1),
        (2, 2, "beta-device", "Beta Camera", "2026-08-01", None, "2026-09-03 09:00", 20, 2, 2, 300, 2, 2),
    ])
    conn.executemany("INSERT INTO companies VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 1, "Alpha", 8, json.dumps([{"name": "Night"}]), json.dumps([{"name": "Night Work", "start_time": "22:00", "end_time": "06:00", "type": "Work"}]), None, "2026-09-01"),
        (2, 2, "Beta", 9, json.dumps([{"name": "Day"}]), json.dumps([{"name": "Day Work", "start_time": "09:00", "end_time": "18:00", "type": "Work"}]), None, "2026-09-01"),
    ])
    conn.executemany("INSERT INTO leave_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 1, 1, "Medical", "2026-09-01", "2026-09-02", "pending", "2026-08-31"),
        (2, 2, 2, "Annual", "2026-09-01", "2026-09-03", "approved", "2026-08-30"),
    ])
    conn.executemany("INSERT INTO classes VALUES (?, ?)", [(1, 1), (2, 2)])
    conn.executemany("INSERT INTO lectures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 1, "Physics", "FY", "A", "Science", "2026-09-02", "10:00", "Teacher A"),
        (2, 2, "Finance", "MBA", "B", "Commerce", "2026-09-02", "11:00", "Teacher B"),
    ])
    conn.executemany("INSERT INTO lecture_attendance VALUES (?, ?, ?, ?)", [(1, 1, 1, 1), (2, 2, 2, 2)])
    conn.executemany("INSERT INTO automated_report_schedules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 1, 1, "alpha@example.com", "Asia/Kolkata", "08:00", '["daily"]', '["attendance_summary"]', "2026-09-03"),
        (2, 2, 1, "beta@example.com", "UTC", "09:00", '["weekly"]', '["attendance_detail"]', "2026-09-03"),
    ])
    conn.executemany("INSERT INTO automated_report_deliveries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 1, "daily", "2026-09-02", "2026-09-02", "sent", "alpha@example.com", None, "2026-09-03", "2026-09-03"),
        (2, 2, "weekly", "2026-08-24", "2026-08-30", "failed", "beta@example.com", "secret provider trace", "2026-09-01", None),
    ])
    conn.executemany("INSERT INTO parent_users VALUES (?, ?)", [(1, 1), (2, 2)])
    conn.executemany("INSERT INTO student_parents VALUES (?, ?)", [(1, 1), (2, 2)])
    conn.executemany("INSERT INTO face_reset_requests VALUES (?, ?, ?)", [(1, 1, "pending"), (2, 2, "approved")])
    conn.commit()
    conn.close()
    monkeypatch.setattr(xchat_tools, "_db", lambda: _connection(path))
    return path


def test_people_devices_and_shifts_are_vendor_scoped(feature_db):
    people = xchat_tools.get_people_summary(1)
    devices = xchat_tools.get_device_status(1)
    shifts = xchat_tools.get_shift_configuration(1)

    assert [person["name"] for person in people["people"]] == ["Alpha User"]
    assert [device["name"] for device in devices["devices"]] == ["Alpha Camera"]
    assert shifts["company"] == "Alpha"
    assert shifts["activities"][0]["overnight"] is True


def test_leave_class_report_and_parent_tools_are_vendor_scoped(feature_db):
    leave = xchat_tools.get_leave_summary(1, "2026-09-01", "2026-09-03")
    classes = xchat_tools.get_class_activity_summary(1, "2026-09-01", "2026-09-03")
    reports = xchat_tools.get_automated_report_status(1)
    parents = xchat_tools.get_parent_access_summary(1)

    assert leave["total_requests"] == 1
    assert leave["requests"][0]["name"] == "Alpha User"
    assert classes["configured_classes"] == 1
    assert classes["lectures"][0]["subject"] == "Physics"
    assert reports["recipient_email"] == "alpha@example.com"
    assert reports["deliveries"][0]["frequency"] == "daily"
    assert parents == {"parent_accounts": 1, "student_parent_links": 1, "pending_face_resets": 1, "source_path": "/settings"}


def test_new_feature_results_build_indexed_downloadable_presentations(feature_db):
    result = xchat_tools.get_leave_summary(1, "2026-09-01", "2026-09-03")
    presentation = build_presentation("List leave and show a pie chart by status", [{"name": "get_leave_summary", "result": result}])

    assert presentation["tables"][0]["rows"][0]["index"] == 1
    assert presentation["tables"][0]["download_name"].endswith(".csv")
    assert presentation["charts"][0]["type"] == "pie"
    assert presentation["charts"][0]["download_name"].endswith(".png")
