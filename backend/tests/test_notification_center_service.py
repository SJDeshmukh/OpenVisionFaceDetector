import sqlite3

from services.notification_center_service import build_notification_center, mark_notifications_read


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE notification_read_receipts (
            scope_vendor_id INTEGER NOT NULL,
            principal_key TEXT NOT NULL,
            notification_key TEXT NOT NULL,
            read_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(scope_vendor_id, principal_key, notification_key)
        );
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT,
            department TEXT, custom_data TEXT
        );
        CREATE TABLE advances (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER,
            amount REAL, status TEXT, created_at DATETIME
        );
        CREATE TABLE leave_requests (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, student_id INTEGER,
            leave_type TEXT, start_date DATE, end_date DATE,
            final_status TEXT, cancellation_status TEXT, created_at DATETIME
        );
        CREATE TABLE leave_request_stages (
            id INTEGER PRIMARY KEY, request_id INTEGER, vendor_id INTEGER,
            stage_key TEXT, display_name TEXT, role_key TEXT, sequence INTEGER,
            department_scoped INTEGER, status TEXT, created_at DATETIME, decided_at DATETIME
        );
        CREATE TABLE face_reset_requests (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, parent_id INTEGER,
            reason TEXT, status TEXT, created_at DATETIME
        );
        CREATE TABLE parent_users (id INTEGER PRIMARY KEY, vendor_id INTEGER, username TEXT);
        CREATE TABLE hostel_alert_deliveries (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER,
            alert_type TEXT, status TEXT, attempts INTEGER, error TEXT, created_at DATETIME
        );
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY, actor_username TEXT, action TEXT,
            target_vendor_id INTEGER, timestamp DATETIME
        );
        """
    )
    return conn


def test_owner_only_receives_pending_advances_for_own_vendor():
    conn = _connection()
    conn.executemany(
        "INSERT INTO faces VALUES (?, ?, ?, ?, ?)",
        [(1, 7, "Asha", None, None), (2, 8, "Other tenant", None, None)],
    )
    conn.executemany(
        "INSERT INTO advances VALUES (?, ?, ?, ?, ?, ?)",
        [
            (10, 7, 1, 1250, "pending", "2026-11-18 09:00:00"),
            (11, 7, 1, 500, "approved", "2026-11-18 10:00:00"),
            (12, 8, 2, 9999, "pending", "2026-11-18 11:00:00"),
        ],
    )
    principal = {
        "vendor_id": 7,
        "scope_vendor_id": 7,
        "principal_key": "owner:owner@example.com",
        "role": "owner",
        "features": set(),
    }

    items = build_notification_center(conn, principal)

    assert [item["key"] for item in items] == ["advance:10:pending"]
    assert "Asha" in items[0]["message"]


def test_student_leave_feed_is_person_scoped_and_read_receipts_are_isolated():
    conn = _connection()
    conn.executemany(
        "INSERT INTO faces VALUES (?, ?, ?, ?, ?)",
        [(1, 7, "Asha", "CSE", None), (2, 7, "Mina", "CSE", None)],
    )
    conn.executemany(
        "INSERT INTO leave_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (20, 7, 1, "home_visit", "2026-11-20", "2026-11-21", "approved", None, "2026-11-18 08:00:00"),
            (21, 7, 2, "medical", "2026-11-20", "2026-11-20", "rejected", None, "2026-11-18 09:00:00"),
        ],
    )
    principal = {
        "vendor_id": 7,
        "scope_vendor_id": 7,
        "principal_key": "student:asha@example.com",
        "role": "student",
        "person_id": 1,
        "features": {"leave_management"},
    }

    items = build_notification_center(conn, principal)
    assert len(items) == 1
    assert items[0]["key"].startswith("leave:20:approved")
    assert items[0]["read"] is False

    assert mark_notifications_read(conn, principal, [items[0]["key"], "../../invalid"]) == 1
    assert build_notification_center(conn, principal)[0]["read"] is True

    other_principal = {**principal, "principal_key": "student:other@example.com"}
    assert build_notification_center(conn, other_principal)[0]["read"] is False


def test_hod_only_receives_current_stage_for_matching_department():
    conn = _connection()
    conn.executemany(
        "INSERT INTO faces VALUES (?, ?, ?, ?, ?)",
        [(1, 7, "CSE Student", "CSE", None), (2, 7, "Civil Student", "Civil", None)],
    )
    conn.executemany(
        "INSERT INTO leave_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (30, 7, 1, "home_visit", "2026-11-20", "2026-11-21", "pending", None, "2026-11-18 08:00:00"),
            (31, 7, 2, "home_visit", "2026-11-20", "2026-11-21", "pending", None, "2026-11-18 09:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO leave_request_stages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 30, 7, "hod", "HOD Approval", "hod", 1, 1, "pending", "2026-11-18 08:00:00", None),
            (2, 31, 7, "hod", "HOD Approval", "hod", 1, 1, "pending", "2026-11-18 09:00:00", None),
        ],
    )
    principal = {
        "vendor_id": 7,
        "scope_vendor_id": 7,
        "principal_key": "leave_staff:4",
        "role": "hod",
        "department": "Computer Science and Engineering",
        "features": {"leave_management"},
    }

    items = build_notification_center(conn, principal)

    assert [item["key"] for item in items] == ["leave-action:30:hod"]
    assert "CSE Student" in items[0]["message"]
