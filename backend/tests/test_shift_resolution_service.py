from datetime import date
import sqlite3

from services.shift_resolution_service import choose_assignment, resolve_shift


def test_assignment_precedence_beats_numeric_priority_across_scopes():
    assignments = [
        {"id": 1, "shift_id": 1, "scope_type": "VENDOR", "priority": 999, "effective_from": "2026-01-01"},
        {"id": 2, "shift_id": 2, "scope_type": "EMPLOYEE", "priority": 0, "effective_from": "2026-01-01"},
    ]
    assert choose_assignment(assignments, date(2026, 9, 15))["id"] == 2


def test_future_and_expired_assignments_are_ignored():
    assignments = [
        {"id": 1, "shift_id": 1, "scope_type": "EMPLOYEE", "effective_from": "2026-10-01"},
        {"id": 2, "shift_id": 2, "scope_type": "EMPLOYEE", "effective_from": "2026-01-01", "effective_to": "2026-08-31"},
        {"id": 3, "shift_id": 3, "scope_type": "LOCATION", "effective_from": "2026-01-01"},
    ]
    assert choose_assignment(assignments, date(2026, 9, 15))["id"] == 3


def test_resolve_shift_is_vendor_scoped_and_effective_dated():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE shifts (id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT);
        CREATE TABLE shift_versions (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, shift_id INTEGER,
            version_number INTEGER, effective_from DATE, effective_to DATE,
            start_time TEXT, end_time TEXT, timezone TEXT, is_cross_midnight INTEGER
        );
        CREATE TABLE shift_assignments (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, shift_id INTEGER,
            scope_type TEXT, person_id INTEGER, organization_unit_id INTEGER,
            location_id INTEGER, group_key TEXT, effective_from DATE,
            effective_to DATE, priority INTEGER
        );
    """)
    conn.execute("INSERT INTO shifts VALUES (10, 1, 'Night')")
    conn.execute("INSERT INTO shifts VALUES (20, 2, 'Other Tenant')")
    conn.execute("INSERT INTO shift_versions VALUES (101, 1, 10, 1, '2026-01-01', NULL, '22:00', '06:00', 'Asia/Kolkata', 1)")
    conn.execute("INSERT INTO shift_versions VALUES (201, 2, 20, 1, '2026-01-01', NULL, '09:00', '17:00', 'UTC', 0)")
    conn.execute("INSERT INTO shift_assignments VALUES (1, 1, 10, 'VENDOR', NULL, NULL, NULL, NULL, '2026-01-01', NULL, 0)")
    conn.execute("INSERT INTO shift_assignments VALUES (2, 1, 10, 'EMPLOYEE', 42, NULL, NULL, NULL, '2026-09-01', NULL, 0)")
    conn.execute("INSERT INTO shift_assignments VALUES (3, 2, 20, 'EMPLOYEE', 42, NULL, NULL, NULL, '2026-01-01', NULL, 0)")

    resolved = resolve_shift(conn.cursor(), 1, 42, date(2026, 9, 15))
    assert resolved.shift_id == 10
    assert resolved.shift_version_id == 101
    assert resolved.scope_type == "EMPLOYEE"
    assert resolved.is_cross_midnight is True
    assert "precedence 500" in resolved.explanation
