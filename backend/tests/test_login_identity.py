import sys
import sqlite3
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.login_identity_service import (
    LoginIdentityConflictError,
    is_designated_kiosk_account,
    is_valid_login_email,
    is_student_profile,
    login_email_from_profile,
    migrate_legacy_login_identities,
    normalize_login_email,
    sync_person_login_identity,
)


def test_login_identity_requires_and_normalizes_email():
    assert normalize_login_email("  PERSON@Example.COM ") == "person@example.com"
    assert is_valid_login_email("person@example.com") is True
    assert is_valid_login_email("EMP-1001") is False


def test_profile_email_aliases_are_normalized():
    assert login_email_from_profile({"employee_email": " Staff@Example.com "}) == "staff@example.com"
    assert login_email_from_profile('{"student_email":"student@example.com"}') == "student@example.com"
    assert login_email_from_profile({"email": "employee-id"}) == ""


def test_student_profiles_are_not_confused_with_vendor_kiosk_users():
    assert is_student_profile("Student", '{"person_type":"student"}')
    assert is_student_profile("Resident", {})
    assert not is_student_profile("Employee", '{"person_type":"employee"}')

    kiosk = {
        "username": "kiosk@school.example",
        "role": "user",
        "person_id": None,
        "is_kiosk": 1,
    }
    assert is_designated_kiosk_account(kiosk, "Kiosk@School.Example")
    assert not is_designated_kiosk_account(kiosk, "other@school.example")
    assert not is_designated_kiosk_account(
        {**kiosk, "person_id": 25}, "kiosk@school.example"
    )


def test_legacy_employee_id_login_is_migrated_to_profile_email():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, kiosk_username TEXT);
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, custom_data TEXT
        );
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, role TEXT, vendor_id INTEGER, person_id INTEGER
        );
        CREATE TABLE active_sessions (token TEXT, username TEXT);

        INSERT INTO vendors VALUES (1, 'EMP-1001');
        INSERT INTO faces VALUES (
            10, 1, '{"employee_email":"Employee@Example.com"}'
        );
        INSERT INTO system_users VALUES ('EMP-1001', 'user', 1, 10);
        INSERT INTO system_users VALUES ('superadmin', 'super_admin', NULL, NULL);
        INSERT INTO active_sessions VALUES ('old-session', 'EMP-1001');
    """)

    migrated = migrate_legacy_login_identities(conn)
    conn.commit()

    assert migrated == 1
    assert conn.execute(
        "SELECT username FROM system_users WHERE person_id = 10"
    ).fetchone()[0] == "employee@example.com"
    assert conn.execute(
        "SELECT kiosk_username FROM vendors WHERE id = 1"
    ).fetchone()[0] == "employee@example.com"
    assert conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0] == 0
    assert conn.execute(
        "SELECT username FROM system_users WHERE role = 'super_admin'"
    ).fetchone()[0] == "superadmin"
    conn.close()


def test_legacy_login_migration_skips_duplicate_email():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, kiosk_username TEXT);
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, custom_data TEXT
        );
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, role TEXT, vendor_id INTEGER, person_id INTEGER
        );
        CREATE TABLE active_sessions (token TEXT, username TEXT);

        INSERT INTO vendors VALUES (1, NULL);
        INSERT INTO faces VALUES (10, 1, '{"email":"used@example.com"}');
        INSERT INTO system_users VALUES ('EMP-1001', 'user', 1, 10);
        INSERT INTO system_users VALUES ('used@example.com', 'owner', 1, NULL);
    """)

    assert migrate_legacy_login_identities(conn) == 0
    assert conn.execute(
        "SELECT username FROM system_users WHERE person_id = 10"
    ).fetchone()[0] == "EMP-1001"
    conn.close()


def test_migration_repairs_valid_but_stale_profile_email_login():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, kiosk_username TEXT);
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, custom_data TEXT
        );
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, role TEXT, vendor_id INTEGER, person_id INTEGER
        );
        CREATE TABLE active_sessions (token TEXT, username TEXT);

        INSERT INTO vendors VALUES (9, NULL);
        INSERT INTO faces VALUES (
            2718, 9, '{"email":"new@example.com","person_type":"student"}'
        );
        INSERT INTO system_users VALUES ('old@example.com', 'student', 9, 2718);
        INSERT INTO active_sessions VALUES ('old-session', 'old@example.com');
    """)

    assert migrate_legacy_login_identities(conn) == 1
    conn.commit()
    assert conn.execute(
        "SELECT username FROM system_users WHERE person_id = 2718"
    ).fetchone()[0] == "new@example.com"
    assert conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0] == 0
    conn.close()


def test_email_only_profile_edit_renames_login_and_revokes_google_link():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, password TEXT, password_plain TEXT,
            role TEXT, vendor_id INTEGER, person_id INTEGER,
            has_set_password INTEGER DEFAULT 0
        );
        CREATE TABLE active_sessions (token TEXT, username TEXT);
        CREATE TABLE external_auth_identities (
            id INTEGER PRIMARY KEY, provider TEXT, provider_subject TEXT,
            username TEXT, vendor_id INTEGER, email TEXT
        );
        INSERT INTO system_users VALUES (
            'old@example.com', 'existing-hash', NULL, 'student', 9, 2718, 1
        );
        INSERT INTO active_sessions VALUES ('old-session', 'old@example.com');
        INSERT INTO external_auth_identities VALUES (
            1, 'google', 'old-google-subject', 'old@example.com', 9, 'old@example.com'
        );
    """)

    result = sync_person_login_identity(
        conn,
        person_id=2718,
        vendor_id=9,
        profile={"email": "New@Example.com"},
        phone="9000000001",
        old_phone="9000000001",
        phone_changed=False,
        student_account=True,
        password_hasher=lambda value: f"hash:{value}",
    )
    conn.commit()

    assert result == "renamed"
    assert conn.execute(
        "SELECT username, password FROM system_users WHERE person_id = 2718"
    ).fetchone() == ("new@example.com", "existing-hash")
    assert conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM external_auth_identities").fetchone()[0] == 0
    conn.close()


def test_login_sync_rejects_email_owned_by_another_person():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, password TEXT, password_plain TEXT,
            role TEXT, vendor_id INTEGER, person_id INTEGER,
            has_set_password INTEGER DEFAULT 0
        );
        CREATE TABLE active_sessions (token TEXT, username TEXT);
        INSERT INTO system_users VALUES
            ('old@example.com', 'hash-1', NULL, 'student', 9, 2718, 1),
            ('used@example.com', 'hash-2', NULL, 'student', 9, 2719, 1);
    """)

    try:
        sync_person_login_identity(
            conn,
            person_id=2718,
            vendor_id=9,
            profile={"email": "used@example.com"},
            phone="9000000001",
            password_hasher=lambda value: f"hash:{value}",
        )
        assert False, "Expected a login identity conflict"
    except LoginIdentityConflictError:
        pass

    assert conn.execute(
        "SELECT username FROM system_users WHERE person_id = 2718"
    ).fetchone()[0] == "old@example.com"
    conn.close()


def test_email_only_edit_renames_existing_login_without_phone():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, password TEXT, password_plain TEXT,
            role TEXT, vendor_id INTEGER, person_id INTEGER,
            has_set_password INTEGER DEFAULT 0
        );
        CREATE TABLE active_sessions (token TEXT, username TEXT);
        INSERT INTO system_users VALUES (
            'old@example.com', 'existing-hash', NULL, 'student', 9, 2718, 1
        );
    """)

    result = sync_person_login_identity(
        conn,
        person_id=2718,
        vendor_id=9,
        profile={"email": "new@example.com"},
        phone="",
        phone_changed=False,
        student_account=True,
        password_hasher=lambda value: f"hash:{value}",
    )

    assert result == "renamed"
    assert conn.execute(
        "SELECT username, password FROM system_users WHERE person_id = 2718"
    ).fetchone() == ("new@example.com", "existing-hash")
    conn.close()
