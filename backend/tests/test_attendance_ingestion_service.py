from datetime import datetime, timedelta
import sqlite3

import pytest

from services.attendance_ingestion_service import (
    AttendanceEventIngestionService,
    LegacyAttendanceEvent,
    resolve_client_event_time,
)


def attendance_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            timestamp DATETIME,
            status TEXT,
            vendor_id INTEGER,
            person_id INTEGER,
            captured_image TEXT,
            activity TEXT,
            is_late INTEGER,
            device_id TEXT,
            attendance_date DATE,
            class_year TEXT,
            division TEXT,
            branch TEXT,
            subject TEXT,
            lecture_id INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE attendance_events (
            id TEXT PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            legacy_attendance_id INTEGER,
            event_type TEXT NOT NULL,
            event_time_utc DATETIME NOT NULL,
            event_timezone TEXT NOT NULL,
            received_at_utc DATETIME NOT NULL,
            source TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            device_id TEXT,
            activity_code TEXT,
            verification_method TEXT,
            verification_score REAL,
            captured_image_reference TEXT,
            payload_metadata TEXT,
            ingestion_status TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            UNIQUE(vendor_id, source, source_event_id)
        )"""
    )
    return conn


def test_insert_legacy_event_uses_caller_transaction():
    conn = attendance_db()
    cursor = conn.cursor()
    event_time = datetime(2026, 9, 15, 9, 0)

    event_id = AttendanceEventIngestionService.insert_legacy_event(
        cursor,
        LegacyAttendanceEvent(
            name="Asha",
            timestamp=event_time,
            status="CHECK_IN",
            vendor_id=7,
            person_id=42,
            activity="Day Shift",
            device_id="kiosk-1",
            is_late=1,
        ),
    )

    row = conn.execute("SELECT * FROM attendance WHERE id = ?", (event_id,)).fetchone()
    assert dict(row) | {}  # Ensure the row remains dict-compatible for existing routes.
    assert row["name"] == "Asha"
    assert row["status"] == "CHECK_IN"
    assert row["vendor_id"] == 7
    assert row["person_id"] == 42
    assert row["activity"] == "Day Shift"
    assert row["device_id"] == "kiosk-1"
    assert row["is_late"] == 1

    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 0


def test_insert_supports_lecture_metadata():
    conn = attendance_db()
    cursor = conn.cursor()
    AttendanceEventIngestionService.insert_legacy_event(
        cursor,
        LegacyAttendanceEvent(
            name="Student One",
            timestamp="2026-09-15T10:00:00",
            status="CHECK_IN",
            vendor_id=3,
            person_id=8,
            activity="Lecture",
            class_year="FY",
            division="A",
            branch="CS",
            subject="Mathematics",
            lecture_id=99,
        ),
    )
    row = conn.execute("SELECT * FROM attendance").fetchone()
    assert (row["class_year"], row["division"], row["branch"]) == ("FY", "A", "CS")
    assert (row["subject"], row["lecture_id"]) == ("Mathematics", 99)


@pytest.mark.parametrize("field", ["name", "timestamp", "vendor_id", "person_id"])
def test_required_event_fields_are_validated(field):
    values = {
        "name": "Worker",
        "timestamp": datetime(2026, 9, 15, 9, 0),
        "status": "CHECK_IN",
        "vendor_id": 1,
        "person_id": 2,
    }
    values[field] = None
    with pytest.raises(ValueError):
        LegacyAttendanceEvent(**values)


def test_unknown_event_type_is_rejected():
    with pytest.raises(ValueError, match="Unsupported attendance event type"):
        LegacyAttendanceEvent(
            name="Worker",
            timestamp=datetime(2026, 9, 15, 9, 0),
            status="PRESENT",
            vendor_id=1,
            person_id=2,
        )


def test_time_resolution_is_deterministic_with_injected_server_time():
    server_now = datetime(2026, 9, 15, 12, 0)
    recent = "2026-09-15T11:45:00"
    stale = "2026-09-13T12:00:00"

    assert resolve_client_event_time(recent, server_now=server_now) == datetime(2026, 9, 15, 11, 45)
    assert resolve_client_event_time(stale, server_now=server_now) == server_now
    assert resolve_client_event_time(None, server_now=server_now) == server_now


def test_ingest_dual_writes_and_deduplicates_source_event():
    conn = attendance_db()
    cursor = conn.cursor()
    event = LegacyAttendanceEvent(
        name="Offline Worker",
        timestamp="2026-09-15T09:00:00",
        status="CHECK_IN",
        vendor_id=4,
        person_id=12,
        device_id="android-1",
        source="KIOSK",
        source_event_id="android-1:queue-501",
        source_timezone="Asia/Kolkata",
        verification_method="FACE",
        verification_score=0.91,
    )

    first = AttendanceEventIngestionService.ingest(cursor, event)
    second = AttendanceEventIngestionService.ingest(cursor, event)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.event_id == first.event_id
    assert second.legacy_attendance_id == first.legacy_attendance_id
    assert conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 1
    ledger = conn.execute("SELECT * FROM attendance_events").fetchone()
    assert ledger["event_time_utc"] == "2026-09-15 03:30:00"
    assert ledger["event_timezone"] == "Asia/Kolkata"
    assert ledger["verification_method"] == "FACE"
    assert ledger["verification_score"] == pytest.approx(0.91)
