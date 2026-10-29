import json
import sqlite3

from services.attendance_shift_service import (
    assign_default_shift_to_unassigned,
    first_active_shift_name,
    synchronize_shift_assignments,
)


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER, shift TEXT)"
    )
    conn.executemany(
        "INSERT INTO faces (id, vendor_id, shift) VALUES (?, ?, ?)",
        [
            (1, 8, None),
            (2, 8, ""),
            (3, 8, "Night"),
            (4, 9, ""),
        ],
    )
    return conn


def test_first_active_shift_is_the_default():
    shifts = [
        {"name": "Disabled", "active": False},
        {"name": "Work", "active": True},
        {"name": "Night", "active": True},
    ]

    assert first_active_shift_name(shifts) == "Work"
    assert first_active_shift_name(json.dumps(shifts)) == "Work"


def test_default_assignment_only_fills_blank_shifts_for_the_vendor():
    conn = _connection()

    changed = assign_default_shift_to_unassigned(
        conn.cursor(),
        8,
        [{"name": "Work"}, {"name": "Night"}],
    )

    assert changed == [1, 2]
    assert conn.execute("SELECT id, shift FROM faces ORDER BY id").fetchall() == [
        (1, "Work"),
        (2, "Work"),
        (3, "Night"),
        (4, ""),
    ]


def test_new_shift_does_not_replace_existing_default_assignments():
    conn = _connection()
    cursor = conn.cursor()
    assign_default_shift_to_unassigned(cursor, 8, [{"id": 1, "name": "Work"}])

    changed = synchronize_shift_assignments(
        cursor,
        8,
        [{"id": 1, "name": "Work"}, {"id": 2, "name": "Night"}],
        previous_shifts=[{"id": 1, "name": "Work"}],
    )

    assert changed == []
    assert conn.execute(
        "SELECT id, shift FROM faces WHERE vendor_id = 8 ORDER BY id"
    ).fetchall() == [(1, "Work"), (2, "Work"), (3, "Night")]


def test_renaming_a_shift_updates_people_assigned_to_that_shift():
    conn = _connection()
    conn.execute("UPDATE faces SET shift = 'Work' WHERE id IN (1, 2)")

    changed = synchronize_shift_assignments(
        conn.cursor(),
        8,
        [{"id": 1, "name": "General"}, {"id": 2, "name": "Night"}],
        previous_shifts=[{"id": 1, "name": "Work"}, {"id": 2, "name": "Night"}],
    )

    assert changed == [1, 2]
    assert conn.execute(
        "SELECT id, shift FROM faces WHERE vendor_id = 8 ORDER BY id"
    ).fetchall() == [(1, "General"), (2, "General"), (3, "Night")]
