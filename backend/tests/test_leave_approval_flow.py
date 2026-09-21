import json
import sqlite3

from flask import Flask, g

from routes import leave_routes


def _connection_factory(db_path):
    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    return connect


def _create_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            name TEXT,
            department TEXT,
            custom_data TEXT
        );
        CREATE TABLE parent_users (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            student_number TEXT NOT NULL,
            selected_person_id INTEGER,
            face_template TEXT,
            device_id TEXT,
            face_image TEXT,
            face_server_template TEXT
        );
        CREATE TABLE leave_staff (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            department TEXT
        );
        CREATE TABLE leave_requests (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            leave_type TEXT,
            reason TEXT,
            start_date TEXT,
            end_date TEXT,
            start_time TEXT,
            end_time TEXT,
            parent_status TEXT DEFAULT 'pending',
            rector_status TEXT DEFAULT 'pending',
            hod_status TEXT DEFAULT 'pending',
            final_status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE leave_workflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER NOT NULL,
            name TEXT NOT NULL, version INTEGER NOT NULL, is_active INTEGER NOT NULL,
            created_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vendor_id, version)
        );
        CREATE TABLE leave_workflow_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id INTEGER NOT NULL,
            stage_key TEXT NOT NULL, display_name TEXT NOT NULL, actor_type TEXT NOT NULL,
            role_key TEXT, sequence INTEGER NOT NULL, department_scoped INTEGER NOT NULL,
            auth_method TEXT NOT NULL, UNIQUE(workflow_id, sequence), UNIQUE(workflow_id, stage_key)
        );
        CREATE TABLE leave_request_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
            vendor_id INTEGER NOT NULL, workflow_id INTEGER, workflow_version INTEGER NOT NULL,
            stage_key TEXT NOT NULL, display_name TEXT NOT NULL, actor_type TEXT NOT NULL,
            role_key TEXT, sequence INTEGER NOT NULL, department_scoped INTEGER NOT NULL,
            auth_method TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', actor_id TEXT,
            actor_name TEXT, decided_at TEXT, decision_metadata TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(request_id, sequence)
        );
        """
    )
    conn.execute(
        "INSERT INTO faces VALUES (?, ?, ?, ?, ?)",
        (10, 1, "Student One", "Science", json.dumps({"student_id": "STU-1", "department": "Science"})),
    )
    conn.execute(
        "INSERT INTO parent_users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (20, 1, "parent_1_STU-1", "STU-1", 10, "registered-template", "device-1", "audit-image", "server-template"),
    )
    conn.executemany(
        "INSERT INTO leave_staff VALUES (?, ?, ?, ?)",
        [(30, 1, "rector", None), (31, 1, "hod", "Science")],
    )
    conn.execute(
        """INSERT INTO leave_requests
           (id, vendor_id, student_id, leave_type, reason, start_date, end_date)
           VALUES (100, 1, 10, 'home', 'Family', '2026-09-12', '2026-09-13')"""
    )
    conn.commit()
    conn.close()


def _json(result):
    response = result[0] if isinstance(result, tuple) else result
    return response.get_json()


def test_student_rector_hod_parent_is_the_only_valid_order(tmp_path, monkeypatch):
    db_path = tmp_path / "leave-flow.db"
    _create_db(db_path)
    monkeypatch.setattr(leave_routes, "get_db_connection", _connection_factory(db_path))

    principal = {"role": "vendor_admin", "username": "vendor-admin"}

    def authenticate():
        g.user_role = principal["role"]
        g.username = principal["username"]
        return 1, None

    monkeypatch.setattr(leave_routes, "authenticate_vendor_access", authenticate)
    monkeypatch.setattr(
        leave_routes,
        "_authenticated_leave_staff",
        lambda vendor_id, required_role=None: {
            "id": 30 if required_role == "rector" else 31,
            "role": required_role,
            "department": None if required_role == "rector" else "Science",
        },
    )
    import tasks
    import services.task_payload_service as task_payload_service

    class _Result:
        def get(self, timeout=None):
            return {"faces": [{"emb_vec": "verified-live-template"}]}

    class _Task:
        def apply_async(self, *args, **kwargs):
            return _Result()

    monkeypatch.setattr(tasks, "detect_faces_task", _Task())
    monkeypatch.setattr(task_payload_service, "store_image_payload", lambda payload: payload)
    monkeypatch.setattr(
        leave_routes,
        "_decode_face_template",
        lambda template: (__import__("numpy").array([1.0]), "test-model"),
    )

    app = Flask(__name__)

    principal.update(role="parent", username="parent_1_STU-1")
    with app.test_request_context("/parent/pending?student_number=STU-1"):
        assert _json(leave_routes.get_parent_pending_requests())["requests"] == []

    principal.update(role="vendor_admin", username="vendor-admin")
    with app.test_request_context("/admin/pending?role=rector"):
        assert [r["id"] for r in _json(leave_routes.get_admin_pending_requests.__wrapped__())["requests"]] == [100]
    with app.test_request_context(
        "/admin/approve",
        method="POST",
        json={"request_id": 100, "role": "rector", "action": "approved"},
    ):
        assert _json(leave_routes.admin_approve_request.__wrapped__())["status"] == "success"

    principal.update(role="parent", username="parent_1_STU-1")
    with app.test_request_context("/parent/pending?student_number=STU-1"):
        assert _json(leave_routes.get_parent_pending_requests())["requests"] == []

    principal.update(role="vendor_admin", username="vendor-admin")
    with app.test_request_context("/admin/pending?role=hod"):
        assert [r["id"] for r in _json(leave_routes.get_admin_pending_requests.__wrapped__())["requests"]] == [100]
    with app.test_request_context(
        "/admin/approve",
        method="POST",
        json={"request_id": 100, "role": "hod", "action": "approved"},
    ):
        assert _json(leave_routes.admin_approve_request.__wrapped__())["status"] == "success"

    principal.update(role="parent", username="parent_1_STU-1")
    with app.test_request_context("/parent/pending?student_number=STU-1"):
        assert [r["id"] for r in _json(leave_routes.get_parent_pending_requests())["requests"]] == [100]
    with app.test_request_context(
        "/parent/approve",
        method="POST",
        json={
            "request_id": 100,
            "student_number": "STU-1",
            "action": "approved",
            "captured_face": "data:image/jpeg;base64,audit-image",
        },
    ):
        assert _json(leave_routes.parent_approve_request())["status"] == "success"

    conn = sqlite3.connect(db_path)
    statuses = conn.execute(
        "SELECT rector_status, hod_status, parent_status, final_status FROM leave_requests WHERE id = 100"
    ).fetchone()
    conn.close()
    assert statuses == ("approved", "approved", "approved", "approved")


def test_rector_rejection_stops_the_flow(tmp_path, monkeypatch):
    db_path = tmp_path / "leave-rejection.db"
    _create_db(db_path)
    monkeypatch.setattr(leave_routes, "get_db_connection", _connection_factory(db_path))

    def authenticate():
        g.user_role = "vendor_admin"
        g.username = "vendor-admin"
        return 1, None

    monkeypatch.setattr(leave_routes, "authenticate_vendor_access", authenticate)
    monkeypatch.setattr(
        leave_routes,
        "_authenticated_leave_staff",
        lambda vendor_id, required_role=None: {"id": 30, "role": "rector", "department": None},
    )
    app = Flask(__name__)

    with app.test_request_context(
        "/admin/approve",
        method="POST",
        json={"request_id": 100, "role": "rector", "action": "rejected"},
    ):
        assert _json(leave_routes.admin_approve_request.__wrapped__())["status"] == "success"

    conn = sqlite3.connect(db_path)
    statuses = conn.execute(
        "SELECT rector_status, hod_status, parent_status, final_status FROM leave_requests WHERE id = 100"
    ).fetchone()
    conn.close()
    assert statuses == ("rejected", "pending", "pending", "rejected")
