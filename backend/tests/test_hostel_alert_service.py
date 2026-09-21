from datetime import datetime, timezone
import json
import sqlite3
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.hostel_alert_service import process_due_alerts, save_settings


def _database(tmp_path):
    path = tmp_path / "hostel-alerts.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, status TEXT, vertical TEXT);
        CREATE TABLE subscriptions (vendor_id INTEGER, features TEXT);
        CREATE TABLE vendor_whatsapp_settings (vendor_id INTEGER, status TEXT);
        CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, phone TEXT, custom_data TEXT);
        CREATE TABLE attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER, status TEXT, timestamp DATETIME, attendance_date DATE);
        CREATE TABLE leave_requests (vendor_id INTEGER, student_id INTEGER, start_date DATE, end_date DATE, final_status TEXT);
        CREATE TABLE student_parents (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER, parent_id INTEGER);
        CREATE TABLE parent_users (id INTEGER PRIMARY KEY, contact_phone TEXT);

        INSERT INTO vendors VALUES (1, 'active', 'hostel');
        INSERT INTO subscriptions VALUES (1, '["hostel_attendance_alerts"]');
        INSERT INTO vendor_whatsapp_settings VALUES (1, 'connected');
        INSERT INTO faces VALUES
            (1, 1, 'Late Resident', '9000000001', '{"person_type":"student","parent_phone":"9000000002"}'),
            (2, 1, 'Inside Resident', '9000000003', '{"person_type":"student","parent_phone":"9000000004"}'),
            (3, 1, 'Resident On Leave', '9000000005', '{"person_type":"student","parent_phone":"9000000006"}');
        INSERT INTO attendance VALUES
            (1, 1, 1, 'CHECK_OUT', '2026-09-21 09:00:00', '2026-09-21'),
            (2, 1, 2, 'CHECK_IN', '2026-09-21 12:00:00', '2026-09-21');
        INSERT INTO leave_requests VALUES (1, 3, '2026-09-20', '2026-09-22', 'approved');
    """)
    conn.commit()
    conn.close()

    def factory():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db

    return factory


def test_cutoff_and_parent_escalation_are_idempotent(tmp_path):
    factory = _database(tmp_path)
    save_settings(1, {
        "enabled": True,
        "owner_phone": "9000000099",
        "cutoff_time": "19:00",
        "escalation_minutes": 60,
        "timezone": "Asia/Kolkata",
        "owner_summary_enabled": True,
    }, connection_factory=factory)
    sent = []

    def sender(vendor_id, phone, message):
        sent.append((vendor_id, phone, message))
        return {"success": True}

    now = datetime(2026, 9, 21, 14, 31, tzinfo=timezone.utc)  # 20:01 IST
    first = process_due_alerts(now, connection_factory=factory, sender=sender)
    second = process_due_alerts(now, connection_factory=factory, sender=sender)

    assert first["sent"] == 3  # resident, parent, owner summary
    assert second["sent"] == 0
    assert [phone for _vendor, phone, _message in sent] == ["9000000001", "9000000002", "9000000099"]


def test_entry_after_student_warning_suppresses_parent_alert(tmp_path):
    factory = _database(tmp_path)
    save_settings(1, {
        "enabled": True,
        "cutoff_time": "19:00",
        "escalation_minutes": 60,
        "timezone": "Asia/Kolkata",
        "owner_summary_enabled": False,
    }, connection_factory=factory)
    sent = []
    sender = lambda vendor_id, phone, message: sent.append(phone) or {"success": True}

    process_due_alerts(
        datetime(2026, 9, 21, 13, 31, tzinfo=timezone.utc),
        connection_factory=factory,
        sender=sender,
    )  # 19:01 IST
    conn = factory()
    conn.execute(
        "INSERT INTO attendance VALUES (4, 1, 1, 'CHECK_IN', '2026-09-21 14:00:00', '2026-09-21')"
    )
    conn.commit()
    conn.close()
    process_due_alerts(
        datetime(2026, 9, 21, 14, 31, tzinfo=timezone.utc),
        connection_factory=factory,
        sender=sender,
    )

    assert sent == ["9000000001"]


def test_disabled_superadmin_feature_stops_alert_processing(tmp_path):
    factory = _database(tmp_path)
    save_settings(1, {
        "enabled": True,
        "cutoff_time": "19:00",
        "escalation_minutes": 60,
        "timezone": "Asia/Kolkata",
    }, connection_factory=factory)
    conn = factory()
    conn.execute("UPDATE subscriptions SET features = '[]' WHERE vendor_id = 1")
    conn.commit()
    conn.close()
    sent = []

    result = process_due_alerts(
        datetime(2026, 9, 21, 14, 31, tzinfo=timezone.utc),
        connection_factory=factory,
        sender=lambda vendor_id, phone, message: sent.append(phone) or {"success": True},
    )

    assert result == {"vendors": 0, "sent": 0, "failed": 0, "skipped": 0}
    assert sent == []
