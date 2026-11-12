import json
import sqlite3
import sys
from unittest.mock import MagicMock

from flask import Flask, g

# The staff route imports shared image helpers, but these tests never execute
# image processing. Keep the focused route test independent of local OpenCV.
sys.modules.setdefault("cv2", MagicMock())

from routes import leave_routes


def _connection_factory(db_path):
    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _create_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE leave_staff (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            pin TEXT NOT NULL,
            department TEXT,
            navbar_items TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO leave_staff VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 7, "Old HOD", "hod", "1234", "Science", json.dumps(["dashboard", "settings", "leave_management"])),
            (2, 7, "Commerce HOD", "hod", "5678", "Commerce", json.dumps(["dashboard", "leave_management"])),
        ],
    )
    conn.commit()
    conn.close()


def _workflow():
    return {
        "stages": [
            {"actor_type": "staff", "role_key": "rector", "department_scoped": 0},
            {"actor_type": "staff", "role_key": "hod", "department_scoped": 1},
        ]
    }


def _response(result):
    return result[0] if isinstance(result, tuple) else result


def _status(result):
    return result[1] if isinstance(result, tuple) else result.status_code


def _configure(monkeypatch, db_path, audit_events):
    monkeypatch.setattr(leave_routes, "get_db_connection", _connection_factory(db_path))
    monkeypatch.setattr(leave_routes, "get_active_workflow", lambda conn, vendor_id: _workflow())
    monkeypatch.setattr(leave_routes, "_vendor_subscription_features", lambda cursor, vendor_id: ["leave_management"])
    monkeypatch.setattr(
        leave_routes,
        "log_audit",
        lambda event, details, **kwargs: audit_events.append((event, details)),
    )

    def authenticate():
        g.user_role = "super_admin"
        g.username = "superadmin"
        return 7, None

    monkeypatch.setattr(leave_routes, "authenticate_vendor_access", authenticate)


def test_staff_role_can_change_from_hod_to_rector(tmp_path, monkeypatch):
    db_path = tmp_path / "staff.db"
    _create_db(db_path)
    audit_events = []
    _configure(monkeypatch, db_path, audit_events)
    app = Flask(__name__)

    with app.test_request_context(
        "/admin/staff?vendor_id=7",
        method="PUT",
        json={
            "id": 1,
            "name": "New Rector",
            "role": "rector",
            "pin": "4321",
            "department": "Science",
            "navbar_items": ["dashboard", "settings", "leave_management"],
        },
    ):
        result = leave_routes.manage_staff()

    assert _status(result) == 200
    payload = _response(result).get_json()
    assert payload["staff"] == {
        "id": 1,
        "name": "New Rector",
        "role": "rector",
        "pin": "4321",
        "department": None,
        "navbar_items": ["dashboard", "settings", "leave_management"],
    }

    conn = sqlite3.connect(db_path)
    saved = conn.execute(
        "SELECT name, role, pin, department FROM leave_staff WHERE id = 1"
    ).fetchone()
    conn.close()
    assert saved == ("New Rector", "rector", "4321", None)
    assert audit_events[0][0] == "leave_staff_updated"
    assert "pin" not in audit_events[0][1]


def test_hod_edit_requires_unique_department_assignment(tmp_path, monkeypatch):
    db_path = tmp_path / "staff.db"
    _create_db(db_path)
    audit_events = []
    _configure(monkeypatch, db_path, audit_events)
    app = Flask(__name__)

    with app.test_request_context(
        "/admin/staff?vendor_id=7",
        method="PUT",
        json={
            "id": 1,
            "name": "Old HOD",
            "role": "hod",
            "pin": "1234",
            "department": "Commerce",
            "navbar_items": ["dashboard", "leave_management"],
        },
    ):
        result = leave_routes.manage_staff()

    assert _status(result) == 409
    assert "already assigned to Commerce" in _response(result).get_json()["error"]
    assert audit_events == []


def test_staff_edit_rejects_duplicate_pin(tmp_path, monkeypatch):
    db_path = tmp_path / "staff.db"
    _create_db(db_path)
    audit_events = []
    _configure(monkeypatch, db_path, audit_events)
    app = Flask(__name__)

    with app.test_request_context(
        "/admin/staff?vendor_id=7",
        method="PUT",
        json={
            "id": 1,
            "name": "Old HOD",
            "role": "hod",
            "pin": "5678",
            "department": "Science",
            "navbar_items": ["dashboard", "leave_management"],
        },
    ):
        result = leave_routes.manage_staff()

    assert _status(result) == 409
    assert _response(result).get_json()["error"] == "This PIN is already assigned to someone else"
    assert audit_events == []
