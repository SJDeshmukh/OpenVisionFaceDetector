import sqlite3

import pytest

from services.apk_service import (
    list_device_update_statuses,
    record_device_update_status,
)


def update_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, company_name TEXT);
        CREATE TABLE vendor_devices (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, device_id TEXT, device_name TEXT
        );
        INSERT INTO vendors VALUES (1, 'Factory One');
        INSERT INTO vendor_devices VALUES (1, 1, 'device-a', 'Gate A');
    """)
    return conn


def test_device_status_upserts_one_row_per_target_release():
    conn = update_db()
    record_device_update_status(
        conn, vendor_id=1, device_id="device-a", release_id=8,
        target_version_code=12, installed_version_code=11,
        installed_version_name="3.1", status="DOWNLOADING", progress=25,
    )
    record_device_update_status(
        conn, vendor_id=1, device_id="device-a", release_id=8,
        target_version_code=12, installed_version_code=11,
        installed_version_name="3.1", status="DOWNLOADED", progress=100,
    )
    rows = list_device_update_statuses(conn, 12)
    assert len(rows) == 1
    assert rows[0]["status"] == "DOWNLOADED"
    assert rows[0]["progress"] == 100
    assert rows[0]["company_name"] == "Factory One"
    assert rows[0]["device_name"] == "Gate A"


def test_device_status_validates_state_and_clamps_progress():
    conn = update_db()
    with pytest.raises(ValueError, match="Unsupported"):
        record_device_update_status(
            conn, vendor_id=1, device_id="device-a",
            target_version_code=12, status="MADE_UP",
        )
    record_device_update_status(
        conn, vendor_id=1, device_id="device-a",
        target_version_code=12, status="DOWNLOADING", progress=250,
    )
    assert list_device_update_statuses(conn)[0]["progress"] == 100
