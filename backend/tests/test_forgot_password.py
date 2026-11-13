import re
import sqlite3
import sys
from types import SimpleNamespace

from flask import Flask, g

from routes import auth
from services import email_service
from services.auth_service import verify_password


def _connection_factory(path):
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    return connect


def _undecorated(handler):
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__
    return handler


def test_forgot_password_emails_hashed_temporary_password_and_forces_change(tmp_path, monkeypatch):
    db_path = tmp_path / "password-reset.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, email TEXT);
        CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER, custom_data TEXT);
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, password TEXT, password_plain TEXT, role TEXT,
            vendor_id INTEGER, person_id INTEGER, has_set_password INTEGER,
            force_password_change INTEGER
        );
        CREATE TABLE active_sessions (token TEXT, username TEXT);
        """
    )
    conn.execute("INSERT INTO vendors VALUES (1, 'office@example.com')")
    conn.execute("INSERT INTO faces VALUES (10, 1, '{\"student_email\":\"student@example.com\"}')")
    conn.execute(
        "INSERT INTO system_users VALUES (?, ?, NULL, 'user', 1, 10, 1, 0)",
        ("STUDENT-1", auth.hash_password("old-password")),
    )
    conn.execute("INSERT INTO active_sessions VALUES ('old-token', 'STUDENT-1')")
    conn.commit()
    conn.close()

    connect = _connection_factory(db_path)
    monkeypatch.setitem(sys.modules, "app", SimpleNamespace(get_db_connection=connect))
    delivered = {}

    def send_email(subject, body, recipient, attachments=None):
        delivered.update(subject=subject, body=body, recipient=recipient)
        return "message-id"

    monkeypatch.setattr(email_service, "send_email", send_email)
    app = Flask(__name__)
    with app.test_request_context(
        "/auth/forgot-password",
        method="POST",
        json={"email": " Student@Example.com "},
    ):
        result = _undecorated(auth.forgot_password)()
        assert result.get_json()["status"] == "success"

    temporary_password = re.search(r"Temporary password: ([A-Z0-9]{5})", delivered["body"]).group(1)
    assert any(character.isalpha() for character in temporary_password)
    assert any(character.isdigit() for character in temporary_password)
    assert delivered["recipient"] == "student@example.com"

    conn = sqlite3.connect(db_path)
    username, password_hash, password_plain, has_set, force_change = conn.execute(
        "SELECT username, password, password_plain, has_set_password, force_password_change FROM system_users WHERE username = 'student@example.com'"
    ).fetchone()
    sessions = conn.execute("SELECT COUNT(*) FROM active_sessions WHERE username = 'STUDENT-1'").fetchone()[0]
    conn.close()
    assert username == "student@example.com"
    assert verify_password(temporary_password, password_hash)
    assert password_plain is None
    assert (has_set, force_change, sessions) == (0, 1, 0)


def test_forgot_password_does_not_change_password_when_delivery_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "password-reset-failure.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, email TEXT);
        CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER, custom_data TEXT);
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, password TEXT, password_plain TEXT, role TEXT,
            vendor_id INTEGER, person_id INTEGER, has_set_password INTEGER,
            force_password_change INTEGER
        );
        CREATE TABLE active_sessions (token TEXT, username TEXT);
        """
    )
    original_hash = auth.hash_password("old-password")
    conn.execute("INSERT INTO system_users VALUES ('person@example.com', ?, NULL, 'faculty', 1, NULL, 1, 0)", (original_hash,))
    conn.commit()
    conn.close()

    monkeypatch.setitem(
        sys.modules,
        "app",
        SimpleNamespace(get_db_connection=_connection_factory(db_path)),
    )
    monkeypatch.setattr(email_service, "send_email", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("SMTP down")))
    app = Flask(__name__)
    with app.test_request_context(
        "/auth/forgot-password",
        method="POST",
        json={"email": "person@example.com"},
    ):
        result, status = _undecorated(auth.forgot_password)()
        assert status == 503
        assert "could not be delivered" in result.get_json()["error"]

    conn = sqlite3.connect(db_path)
    password_hash, force_change = conn.execute(
        "SELECT password, force_password_change FROM system_users WHERE username = 'person@example.com'"
    ).fetchone()
    conn.close()
    assert password_hash == original_hash
    assert force_change == 0


def test_first_login_student_can_set_password_without_current_password(tmp_path, monkeypatch):
    db_path = tmp_path / "student-first-login.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, password TEXT, password_plain TEXT, role TEXT,
            has_set_password INTEGER, force_password_change INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO system_users VALUES (?, ?, NULL, 'student', 0, 0)",
        ("student@example.com", auth.hash_password("9876543210")),
    )
    conn.commit()
    conn.close()

    monkeypatch.setitem(
        sys.modules,
        "app",
        SimpleNamespace(get_db_connection=_connection_factory(db_path)),
    )
    monkeypatch.setattr(auth, "verify_token", lambda token: {"username": "student@example.com"})
    app = Flask(__name__)
    with app.test_request_context(
        "/auth/change-password",
        method="POST",
        json={"password": "new-password"},
        headers={"Authorization": "Bearer web-token"},
    ):
        response = _undecorated(auth.change_password)()

    assert response.get_json()["status"] == "success"
    conn = sqlite3.connect(db_path)
    password_hash, password_plain, has_set, force_change = conn.execute(
        "SELECT password, password_plain, has_set_password, force_password_change FROM system_users"
    ).fetchone()
    conn.close()
    assert verify_password("new-password", password_hash)
    assert password_plain is None
    assert (has_set, force_change) == (1, 0)


def test_student_role_can_reset_password_with_cookie_authenticated_session(tmp_path, monkeypatch):
    db_path = tmp_path / "student-default-password.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, phone TEXT, custom_data TEXT
        );
        CREATE TABLE system_users (
            username TEXT, password TEXT, password_plain TEXT, role TEXT,
            vendor_id INTEGER, person_id INTEGER, has_set_password INTEGER
        );
        CREATE TABLE active_sessions (
            token TEXT, username TEXT, vendor_id INTEGER
        );
        """
    )
    conn.execute("INSERT INTO faces VALUES (10, 1, '9876543210', '{}')")
    conn.execute(
        "INSERT INTO system_users VALUES (?, ?, NULL, 'student', 1, 10, 1)",
        ("student@example.com", auth.hash_password("custom-password")),
    )
    conn.execute("INSERT INTO active_sessions VALUES ('web-token', 'student@example.com', 1)")
    conn.commit()
    conn.close()

    monkeypatch.setitem(
        sys.modules,
        "app",
        SimpleNamespace(get_db_connection=_connection_factory(db_path)),
    )

    def authenticate():
        g.user_role = "student"
        g.username = "student@example.com"
        return 1, None

    monkeypatch.setattr(auth, "authenticate_vendor_access", authenticate)
    app = Flask(__name__)
    with app.test_request_context("/auth/student/reset-to-default", method="POST"):
        response = auth.reset_student_password_to_default()

    assert response.get_json()["status"] == "success"
    assert "token=;" in response.headers.get("Set-Cookie", "")

    conn = sqlite3.connect(db_path)
    password_hash, password_plain, has_set = conn.execute(
        "SELECT password, password_plain, has_set_password FROM system_users WHERE username = 'student@example.com'"
    ).fetchone()
    sessions = conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0]
    conn.close()
    assert verify_password("9876543210", password_hash)
    assert password_plain is None
    assert has_set == 0
    assert sessions == 0
