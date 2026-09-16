import sqlite3
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.vendor_delete_service import (
    purge_vendor_archive_database,
    purge_vendor_database,
)


def test_vendor_purge_removes_new_and_legacy_tenant_data_and_releases_identity():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, company_name TEXT);
        CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER, face_image TEXT);
        CREATE TABLE attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE attendance_events (id TEXT PRIMARY KEY, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE shifts (id INTEGER PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE shift_versions (id INTEGER PRIMARY KEY, vendor_id INTEGER, shift_id INTEGER);
        CREATE TABLE shift_segments (id INTEGER PRIMARY KEY, vendor_id INTEGER, shift_version_id INTEGER);
        CREATE TABLE vendor_whatsapp_settings (id INTEGER PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE system_users (username TEXT PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE active_sessions (token TEXT PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE archive_objects (id INTEGER PRIMARY KEY, vendor_id INTEGER);

        INSERT INTO vendors VALUES (1, 'Delete Me'), (2, 'Keep Me');
        INSERT INTO faces VALUES (10, 1, 'old-face'), (20, 2, 'keep-face');
        INSERT INTO attendance VALUES (10, 1, 10), (20, 2, 20);
        INSERT INTO attendance_events VALUES ('old-event', 1, 10), ('keep-event', 2, 20);
        INSERT INTO shifts VALUES (10, 1), (20, 2);
        INSERT INTO shift_versions VALUES (10, 1, 10), (20, 2, 20);
        INSERT INTO shift_segments VALUES (10, 1, 10), (20, 2, 20);
        INSERT INTO vendor_whatsapp_settings VALUES (10, 1), (20, 2);
        INSERT INTO system_users VALUES ('vendor@example.com', 1), ('keep@example.com', 2);
        INSERT INTO active_sessions VALUES ('old-token', 1), ('keep-token', 2);
        INSERT INTO system_settings VALUES ('threshold_vendor_1', '0.6');
        INSERT INTO system_settings VALUES ('threshold_vendor_2', '0.7');
        INSERT INTO archive_objects VALUES (10, 1), (20, 2);
    """)

    deleted = purge_vendor_database(conn, 1)
    conn.commit()

    assert deleted["vendors"] == 1
    for table in (
        "vendors", "faces", "attendance", "attendance_events", "shifts",
        "shift_versions", "shift_segments", "vendor_whatsapp_settings",
        "system_users", "active_sessions", "archive_objects",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE " + (
            "id = 1" if table == "vendors" else "vendor_id = 1"
        )).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM system_settings WHERE key = 'threshold_vendor_1'"
    ).fetchone()[0] == 0

    # The deleted email is immediately reusable by a newly registered company.
    conn.execute("INSERT INTO system_users VALUES ('vendor@example.com', 2)")
    conn.commit()
    assert conn.execute(
        "SELECT vendor_id FROM system_users WHERE username = 'vendor@example.com'"
    ).fetchone()[0] == 2
    conn.close()


def test_vendor_archive_purge_removes_all_vendor_owned_archive_rows():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE backup_metadata (id INTEGER PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE unrelated_metadata (id INTEGER PRIMARY KEY, value TEXT);

        INSERT INTO attendance VALUES (10, 1), (20, 2);
        INSERT INTO backup_metadata VALUES (10, 1), (20, 2);
        INSERT INTO unrelated_metadata VALUES (1, 'keep');
    """)

    deleted = purge_vendor_archive_database(conn, 1)
    conn.commit()

    assert deleted == {"attendance": 1, "backup_metadata": 1}
    assert conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE vendor_id = 1"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM backup_metadata WHERE vendor_id = 1"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE vendor_id = 2"
    ).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM unrelated_metadata").fetchone()[0] == 1
    conn.close()
