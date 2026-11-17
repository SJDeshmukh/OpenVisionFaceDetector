from datetime import datetime, timezone
import json
import sqlite3
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.hostel_alert_service import (
    process_due_alerts,
    process_leave_checkout_alert,
    save_settings,
)


def _database(tmp_path):
    path = tmp_path / "hostel-alerts.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, status TEXT, vertical TEXT);
        CREATE TABLE subscriptions (vendor_id INTEGER, features TEXT);
        CREATE TABLE vendor_whatsapp_settings (vendor_id INTEGER, status TEXT, phone_number TEXT);
        CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, phone TEXT, custom_data TEXT);
        CREATE TABLE attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER, status TEXT, timestamp DATETIME, attendance_date DATE);
        CREATE TABLE leave_requests (id INTEGER PRIMARY KEY, vendor_id INTEGER, student_id INTEGER, leave_type TEXT, reason TEXT, start_date DATE, end_date DATE, start_time TEXT, end_time TEXT, final_status TEXT, rector_status TEXT);
        CREATE TABLE student_parents (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER, parent_id INTEGER);
        CREATE TABLE parent_users (id INTEGER PRIMARY KEY, contact_phone TEXT);

        INSERT INTO vendors VALUES (1, 'active', 'hostel');
        INSERT INTO subscriptions VALUES (1, '["hostel_attendance_alerts"]');
        INSERT INTO vendor_whatsapp_settings VALUES (1, 'connected', '919000000099');
        INSERT INTO faces VALUES
            (1, 1, 'Late Resident', '9000000001', '{"person_type":"student","parent_phone":"9000000002"}'),
            (2, 1, 'Inside Resident', '9000000003', '{"person_type":"student","parent_phone":"9000000004"}'),
            (3, 1, 'Resident On Leave', '9000000005', '{"person_type":"student","parent_phone":"9000000006"}');
        INSERT INTO attendance VALUES
            (1, 1, 1, 'CHECK_OUT', '2026-09-21 09:00:00', '2026-09-21'),
            (2, 1, 2, 'CHECK_IN', '2026-09-21 12:00:00', '2026-09-21');
        INSERT INTO leave_requests VALUES (1, 1, 3, 'home', 'Family visit', '2026-09-20', '2026-09-22', '10:00', '18:00', 'approved', 'approved');
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


def test_qr_connected_number_defaults_hostel_administrator_recipient(tmp_path):
    factory = _database(tmp_path)
    saved = save_settings(1, {
        "enabled": True,
        "cutoff_time": "19:00",
        "escalation_minutes": 60,
        "timezone": "Asia/Kolkata",
        "owner_summary_enabled": True,
    }, connection_factory=factory)
    sent = []

    result = process_due_alerts(
        datetime(2026, 9, 21, 14, 31, tzinfo=timezone.utc),  # 20:01 IST
        connection_factory=factory,
        sender=lambda vendor_id, phone, message: sent.append(phone) or {"success": True},
    )

    assert saved["owner_phone"] == "919000000099"
    assert saved["connected_whatsapp_phone"] == "919000000099"
    assert saved["owner_phone_source"] == "qr_connection"
    assert result["sent"] == 3
    assert sent == ["9000000001", "9000000002", "919000000099"]


def test_explicit_hostel_administrator_number_overrides_qr_number(tmp_path):
    factory = _database(tmp_path)

    saved = save_settings(1, {
        "enabled": False,
        "owner_phone": "919111111111",
        "cutoff_time": "19:00",
        "escalation_minutes": 60,
        "timezone": "Asia/Kolkata",
    }, connection_factory=factory)

    assert saved["owner_phone"] == "919111111111"
    assert saved["connected_whatsapp_phone"] == "919000000099"
    assert saved["owner_phone_source"] == "hostel_settings"


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


def test_feature_flag_allows_alerts_for_non_hostel_vertical(tmp_path):
    """The separately billed feature, not a legacy vertical label, controls access."""
    factory = _database(tmp_path)
    save_settings(1, {
        "enabled": True,
        "owner_phone": "9000000099",
        "cutoff_time": "19:00",
        "escalation_minutes": 60,
        "timezone": "Asia/Kolkata",
        "owner_summary_enabled": False,
    }, connection_factory=factory)
    conn = factory()
    conn.execute("UPDATE vendors SET vertical = 'school' WHERE id = 1")
    conn.commit()
    conn.close()
    sent = []

    result = process_due_alerts(
        datetime(2026, 9, 21, 13, 31, tzinfo=timezone.utc),  # 19:01 IST
        connection_factory=factory,
        sender=lambda vendor_id, phone, message: sent.append(phone) or {"success": True},
    )

    assert result["vendors"] == 1
    assert result["sent"] == 1
    assert sent == ["9000000001"]


def test_time_change_starts_new_same_day_alert_cycle(tmp_path):
    factory = _database(tmp_path)
    config = {
        "enabled": True,
        "cutoff_time": "19:00",
        "escalation_minutes": 60,
        "timezone": "Asia/Kolkata",
        "owner_summary_enabled": False,
    }
    initial = save_settings(1, config, connection_factory=factory)
    sent = []
    sender = lambda vendor_id, phone, message: sent.append(phone) or {"success": True}
    now = datetime(2026, 9, 21, 13, 31, tzinfo=timezone.utc)  # 19:01 IST

    first = process_due_alerts(now, connection_factory=factory, sender=sender)
    duplicate = process_due_alerts(now, connection_factory=factory, sender=sender)
    unchanged = save_settings(1, config, connection_factory=factory)
    still_duplicate = process_due_alerts(now, connection_factory=factory, sender=sender)

    changed = save_settings(
        1,
        {**config, "cutoff_time": "18:30"},
        connection_factory=factory,
    )
    after_time_change = process_due_alerts(now, connection_factory=factory, sender=sender)
    new_duplicate = process_due_alerts(now, connection_factory=factory, sender=sender)

    assert first["sent"] == 1
    assert duplicate["sent"] == 0
    assert still_duplicate["sent"] == 0
    assert unchanged["schedule_revision"] == initial["schedule_revision"]
    assert changed["schedule_revision"] == initial["schedule_revision"] + 1
    assert after_time_change["sent"] == 1
    assert new_duplicate["sent"] == 0
    assert sent == ["9000000001", "9000000001"]


def test_approved_leave_with_datetime_string_suppresses_alerts(tmp_path):
    factory = _database(tmp_path)
    conn = factory()
    conn.execute("INSERT INTO faces VALUES (4, 1, 'Leave Resident', '9000000010', '{\"person_type\":\"student\",\"parent_phone\":\"9000000011\"}')")
    conn.execute("INSERT INTO leave_requests VALUES (2, 1, 4, 'home', 'Family visit', '2026-09-21 10:00:00', '2026-09-22 18:00:00', '10:00', '18:00', 'approved', 'approved')")
    conn.commit()
    conn.close()

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
        datetime(2026, 9, 21, 14, 31, tzinfo=timezone.utc),  # 20:01 IST
        connection_factory=factory,
        sender=sender,
    )
    # Resident 4 must NOT receive alerts because they are on approved leave
    assert "9000000010" not in sent
    assert "9000000011" not in sent


def test_leave_checkout_alert_dispatches_to_parent_for_all_residents(tmp_path):
    factory = _database(tmp_path)
    conn = factory()
    conn.execute("INSERT INTO faces VALUES (5, 1, 'Priya Patel', '9000000020', '{\"person_type\":\"student\",\"gender\":\"female\",\"parent_phone\":\"9000000021\"}')")
    conn.execute("INSERT INTO faces VALUES (6, 1, 'Rahul Verma', '9000000022', '{\"person_type\":\"student\",\"gender\":\"male\",\"parent_phone\":\"9000000023\"}')")
    conn.execute("INSERT INTO leave_requests VALUES (101, 1, 5, 'night_out', 'Family function', '2026-09-21', '2026-09-22', '18:00', '20:00', 'approved', 'approved')")
    conn.execute("INSERT INTO leave_requests VALUES (102, 1, 6, 'night_out', 'Friends meetup', '2026-09-21', '2026-09-22', '18:00', '20:00', 'approved', 'approved')")
    conn.commit()
    conn.close()

    save_settings(1, {
        "enabled": True,
        "leave_checkout_alert_enabled": True,
        "timezone": "Asia/Kolkata",
    }, connection_factory=factory)

    sent = []
    def sender(vendor_id, phone, message):
        sent.append((vendor_id, phone, message))
        return {"success": True}

    checkout_time = datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc)  # 18:00 IST

    # 1. Resident 5 (female) on night out checks out -> sends WhatsApp to parent
    res_female = process_leave_checkout_alert(1, 5, checkout_time, connection_factory=factory, sender=sender)
    assert res_female["status"] == "sent"
    assert len(sent) == 1
    assert sent[0][1] == "9000000021"
    assert "Priya Patel" in sent[0][2]
    assert "Night Out" in sent[0][2]

    # 2. Duplicate checkout on same day -> skipped
    res_dup = process_leave_checkout_alert(1, 5, checkout_time, connection_factory=factory, sender=sender)
    assert res_dup["status"] == "skipped"
    assert len(sent) == 1

    # 3. Resident 6 (male) on night out checks out -> ALSO sends WhatsApp to parent (same rules for all residents)
    res_male = process_leave_checkout_alert(1, 6, checkout_time, connection_factory=factory, sender=sender)
    assert res_male["status"] == "sent"
    assert len(sent) == 2
    assert sent[1][1] == "9000000023"
    assert "Rahul Verma" in sent[1][2]
