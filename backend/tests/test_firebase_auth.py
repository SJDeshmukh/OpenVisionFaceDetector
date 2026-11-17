import sqlite3
import sys
import types

import pytest

from services import firebase_auth_service


def _resolve_account(conn, identity):
    pytest.importorskip("flask")
    from routes.firebase_auth import _resolve_account as resolver

    return resolver(conn, identity)


def _firebase_module(decoded):
    module = types.ModuleType("firebase_admin")
    module.auth = types.SimpleNamespace(
        verify_id_token=lambda token, app=None, check_revoked=False: decoded,
    )
    return module


def test_google_token_requires_verified_google_provider(monkeypatch):
    decoded = {
        "uid": "google-subject-1",
        "email": "Student@Example.com",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"},
    }
    monkeypatch.setitem(sys.modules, "firebase_admin", _firebase_module(decoded))
    monkeypatch.setattr(firebase_auth_service, "_firebase_app", lambda: object())

    identity = firebase_auth_service.verify_google_firebase_token("valid-token")

    assert identity == {
        "subject": "google-subject-1",
        "email": "student@example.com",
        "name": "",
        "picture": "",
    }


@pytest.mark.parametrize(
    "provider,verified",
    [("password", True), ("google.com", False)],
)
def test_google_token_rejects_wrong_provider_or_unverified_email(monkeypatch, provider, verified):
    decoded = {
        "uid": "subject",
        "email": "person@example.com",
        "email_verified": verified,
        "firebase": {"sign_in_provider": provider},
    }
    monkeypatch.setitem(sys.modules, "firebase_admin", _firebase_module(decoded))
    monkeypatch.setattr(firebase_auth_service, "_firebase_app", lambda: object())

    with pytest.raises(firebase_auth_service.FirebaseAuthTokenError):
        firebase_auth_service.verify_google_firebase_token("valid-token")


def _account_database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY,
            password TEXT,
            password_plain TEXT,
            role TEXT,
            vendor_id INTEGER,
            person_id INTEGER,
            has_set_password INTEGER DEFAULT 0,
            force_password_change INTEGER DEFAULT 0
        );
        CREATE TABLE external_auth_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            provider_subject TEXT NOT NULL,
            username TEXT NOT NULL,
            vendor_id INTEGER,
            email TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider, provider_subject),
            UNIQUE(provider, username)
        );
        CREATE TABLE leave_staff (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER,
            name TEXT,
            email TEXT,
            role TEXT,
            department TEXT,
            navbar_items TEXT
        );
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY,
            name TEXT,
            vendor_id INTEGER,
            custom_data TEXT,
            designation TEXT,
            student_status TEXT DEFAULT 'active',
            login_enabled INTEGER DEFAULT 1
        );
        """
    )
    return conn


def test_registered_leave_staff_gets_linked_staff_account():
    conn = _account_database()
    conn.execute(
        "INSERT INTO leave_staff VALUES (4, 8, 'Rector', 'rector@example.com', 'rector', NULL, '[\"leave_management\"]')"
    )

    account = _resolve_account(
        conn,
        {"subject": "google-staff-4", "email": "rector@example.com"},
    )

    assert account["role"] == "staff"
    assert account["vendor_id"] == 8
    link = conn.execute(
        "SELECT provider_subject, username FROM external_auth_identities"
    ).fetchone()
    assert tuple(link) == ("google-staff-4", "rector@example.com")


def test_registered_resident_gets_linked_student_account():
    conn = _account_database()
    conn.execute(
        """INSERT INTO faces
               (id, name, vendor_id, custom_data, designation, student_status, login_enabled)
             VALUES (20, 'Aditi', 8, '{"student_email":"aditi@example.com","person_type":"student"}',
                     'Student', 'active', 1)"""
    )

    account = _resolve_account(
        conn,
        {"subject": "google-student-20", "email": "aditi@example.com"},
    )

    assert account["role"] == "student"
    assert account["person_id"] == 20


def test_unknown_google_email_is_not_auto_registered():
    conn = _account_database()

    with pytest.raises(LookupError, match="not registered"):
        _resolve_account(
            conn,
            {"subject": "unknown-subject", "email": "unknown@example.com"},
        )
