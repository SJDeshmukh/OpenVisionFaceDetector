import sqlite3

from services.attendance_state_service import reconcile_person_timeline


def _database():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE attendance (
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            vendor_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            device_id TEXT
        );
        CREATE TABLE attendance_events (
            id TEXT PRIMARY KEY,
            legacy_attendance_id INTEGER,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL
        );
        """
    )
    return connection


def test_backdated_offline_punch_reclassifies_later_kiosk_projection():
    connection = _database()
    cursor = connection.cursor()

    # Device A was online first, so this was originally classified CHECK_IN.
    cursor.execute(
        "INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?)",
        (1, "2026-10-28 09:00:00", "CHECK_IN", 8, 101, "device-a"),
    )
    cursor.execute(
        "INSERT INTO attendance_events VALUES (?, ?, ?, ?)",
        ("event-a", 1, "KIOSK", "CHECK_IN"),
    )

    # Device B later reconnects with an older 08:00 punch. Both devices had
    # locally predicted CHECK_IN, but the shared chronological result is
    # 08:00 CHECK_IN followed by 09:00 CHECK_OUT.
    cursor.execute(
        "INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?)",
        (2, "2026-10-28 08:00:00", "CHECK_IN", 8, 101, "device-b"),
    )
    cursor.execute(
        "INSERT INTO attendance_events VALUES (?, ?, ?, ?)",
        ("event-b", 2, "KIOSK", "CHECK_IN"),
    )

    result = reconcile_person_timeline(
        cursor,
        8,
        101,
        target_attendance_id=2,
    )

    rows = cursor.execute(
        "SELECT timestamp, status, device_id FROM attendance ORDER BY timestamp, id"
    ).fetchall()
    ledger = cursor.execute(
        "SELECT id, event_type FROM attendance_events ORDER BY id"
    ).fetchall()

    assert rows == [
        ("2026-10-28 08:00:00", "CHECK_IN", "device-b"),
        ("2026-10-28 09:00:00", "CHECK_OUT", "device-a"),
    ]
    assert result.target_status == "CHECK_IN"
    assert result.latest_status == "CHECK_OUT"
    assert result.changed_count == 1
    # The capture ledger remains immutable; only the attendance projection is
    # recalculated for reports, payroll, and the current kiosk state.
    assert ledger == [("event-a", "CHECK_IN"), ("event-b", "CHECK_IN")]


def test_manual_status_remains_an_authoritative_anchor():
    connection = _database()
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?)",
        (1, "2026-10-28 08:00:00", "CHECK_OUT", 8, 101, "web"),
    )
    cursor.execute(
        "INSERT INTO attendance_events VALUES (?, ?, ?, ?)",
        ("manual", 1, "WEB", "CHECK_OUT"),
    )
    cursor.execute(
        "INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?)",
        (2, "2026-10-28 09:00:00", "CHECK_OUT", 8, 101, "kiosk"),
    )
    cursor.execute(
        "INSERT INTO attendance_events VALUES (?, ?, ?, ?)",
        ("kiosk", 2, "KIOSK", "CHECK_OUT"),
    )

    result = reconcile_person_timeline(cursor, 8, 101, target_attendance_id=2)

    assert cursor.execute(
        "SELECT status FROM attendance ORDER BY timestamp, id"
    ).fetchall() == [("CHECK_OUT",), ("CHECK_IN",)]
    assert result.target_status == "CHECK_IN"
    assert result.latest_status == "CHECK_IN"

