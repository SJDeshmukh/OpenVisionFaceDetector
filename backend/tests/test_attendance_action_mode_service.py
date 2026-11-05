from datetime import datetime, timezone
import sqlite3

import pytest

from services.attendance_action_mode_service import (
    event_time_to_utc_naive,
    record_action_mode_change,
    resolve_action_mode_at,
)


def mode_history_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE attendance_action_mode_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            effective_from_utc DATETIME NOT NULL,
            changed_by TEXT NOT NULL,
            created_at DATETIME NOT NULL
        )"""
    )
    return conn


def test_mode_history_resolves_multiple_changes_by_original_event_time():
    conn = mode_history_db()
    cursor = conn.cursor()
    record_action_mode_change(
        cursor,
        8,
        "automatic",
        "admin",
        effective_from_utc=datetime(2026, 11, 5, 3, 30),
    )
    record_action_mode_change(
        cursor,
        8,
        "manual",
        "admin",
        effective_from_utc=datetime(2026, 11, 5, 5, 30),
    )
    record_action_mode_change(
        cursor,
        8,
        "automatic",
        "admin",
        effective_from_utc=datetime(2026, 11, 5, 8, 30),
    )

    ten_am = resolve_action_mode_at(
        cursor, 8, datetime(2026, 11, 5, 10, 0), "Asia/Kolkata", "manual"
    )
    noon = resolve_action_mode_at(
        cursor, 8, datetime(2026, 11, 5, 12, 0), "Asia/Kolkata", "automatic"
    )
    three_pm = resolve_action_mode_at(
        cursor, 8, datetime(2026, 11, 5, 15, 0), "Asia/Kolkata", "manual"
    )

    assert ten_am.mode == "automatic"
    assert noon.mode == "manual"
    assert three_pm.mode == "automatic"


def test_repeated_value_does_not_create_a_duplicate_mode_version():
    conn = mode_history_db()
    cursor = conn.cursor()
    assert record_action_mode_change(
        cursor,
        4,
        "manual",
        "admin",
        effective_from_utc=datetime(2026, 11, 5, 5, 30),
    )
    assert not record_action_mode_change(
        cursor,
        4,
        "manual",
        "admin",
        effective_from_utc=datetime(2026, 11, 5, 6, 30),
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM attendance_action_mode_history WHERE vendor_id = 4"
    ).fetchone()[0] == 1


def test_pre_history_event_uses_first_known_baseline():
    conn = mode_history_db()
    cursor = conn.cursor()
    record_action_mode_change(
        cursor,
        3,
        "manual",
        "schema_migration",
        effective_from_utc=datetime(2026, 11, 5, 5, 30),
    )

    result = resolve_action_mode_at(
        cursor, 3, datetime(2026, 11, 4, 12, 0), "Asia/Kolkata", "automatic"
    )

    assert result.mode == "manual"
    assert result.effective_from_utc == datetime(2026, 11, 5, 5, 30)


def test_timezone_conversion_accepts_aware_values_and_rejects_unknown_zones():
    aware = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
    assert event_time_to_utc_naive(aware, "Invalid/Zone") == datetime(2026, 11, 5, 10, 0)

    with pytest.raises(ValueError, match="Unknown attendance event timezone"):
        event_time_to_utc_naive(datetime(2026, 11, 5, 10, 0), "Invalid/Zone")
