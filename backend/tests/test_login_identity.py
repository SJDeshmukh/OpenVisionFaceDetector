import sys
import sqlite3
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.login_identity_service import (
    is_valid_login_email,
    login_email_from_profile,
    migrate_legacy_login_identities,
    normalize_login_email,
)


def test_login_identity_requires_and_normalizes_email():
    assert normalize_login_email("  PERSON@Example.COM ") == "person@example.com"
    assert is_valid_login_email("person@example.com") is True
    assert is_valid_login_email("EMP-1001") is False


def test_profile_email_aliases_are_normalized():
    assert login_email_from_profile({"employee_email": " Staff@Example.com "}) == "staff@example.com"
    assert login_email_from_profile('{"student_email":"student@example.com"}') == "student@example.com"
    assert login_email_from_profile({"email": "employee-id"}) == ""


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
