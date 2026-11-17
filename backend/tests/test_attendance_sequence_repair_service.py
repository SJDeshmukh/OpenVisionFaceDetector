import sqlite3

from services.attendance_sequence_repair_service import (
    AttendanceProjectionRow,
    apply_findings,
    find_invalid_transitions,
    load_projection_rows,
)


def _row(attendance_id, timestamp, status, *, day="2026-11-05", person_id=101):
    return AttendanceProjectionRow(
        attendance_id=attendance_id,
        vendor_id=8,
        person_id=person_id,
        name="Anant",
        timestamp=timestamp,
        status=status,
        attendance_date=day,
        source="KIOSK_MANUAL",
    )


def test_audit_keeps_valid_multiple_sessions_and_flags_only_impossible_transitions():
    rows = [
        _row(1, "2026-11-05 08:00:00", "CHECK_IN"),
        _row(2, "2026-11-05 08:00:30", "Check In"),
        _row(3, "2026-11-05 12:00:00", "CHECK_OUT"),
        _row(4, "2026-11-05 13:00:00", "CHECK_OUT"),
        _row(5, "2026-11-05 14:00:00", "CHECK_IN"),
        _row(6, "2026-11-05 18:00:00", "check-out"),
    ]

    findings = find_invalid_transitions(rows)

    assert [(item.row.attendance_id, item.reason) for item in findings] == [
        (2, "duplicate_check_in"),
        (4, "checkout_without_open_checkin"),
    ]


def test_state_is_scoped_by_person_and_operational_date():
    rows = [
        _row(1, "2026-11-05 08:00:00", "CHECK_IN"),
        _row(2, "2026-11-06 08:00:00", "CHECK_IN", day="2026-11-06"),
        _row(3, "2026-11-05 08:00:00", "CHECK_IN", person_id=202),
    ]

    assert find_invalid_transitions(rows) == []


def test_missing_operational_date_is_audit_only_for_night_shift_safety():
    rows = [
        _row(1, "2026-11-06 01:00:00", "CHECK_OUT", day=None),
    ]

    findings = find_invalid_transitions(rows)

    assert len(findings) == 1
    assert findings[0].repair_eligible is False


def test_legacy_sqlite_schema_without_operational_date_or_event_ledger_can_be_audited():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE attendance (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER,
            name TEXT, timestamp TEXT, status TEXT, device_id TEXT, activity TEXT
        );
        INSERT INTO attendance VALUES
            (1, 8, 101, 'Anant', '2026-11-05 08:00:00', 'CHECK_IN', NULL, 'Work'),
            (2, 8, 101, 'Anant', '2026-11-05 08:00:30', 'CHECK_IN', NULL, 'Work');
        """
    )

    rows = load_projection_rows(
        connection.cursor(),
        8,
        "2026-11-05",
        "2026-11-05",
        attendance_columns={
            "id", "vendor_id", "person_id", "name", "timestamp", "status",
            "device_id", "activity",
        },
        event_columns=set(),
    )
    findings = find_invalid_transitions(rows)

    assert len(rows) == 2
    assert [(item.row.attendance_id, item.reason) for item in findings] == [
        (2, "duplicate_check_in")
    ]
    assert findings[0].repair_eligible is False


def test_apply_preserves_audit_and_ledger_while_removing_projection_row():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE attendance (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER,
            name TEXT, timestamp TEXT, status TEXT, attendance_date TEXT,
            device_id TEXT, activity TEXT
        );
        CREATE TABLE attendance_events (
            id TEXT PRIMARY KEY, legacy_attendance_id INTEGER,
            ingestion_status TEXT
        );
        INSERT INTO attendance VALUES
            (1, 8, 101, 'Anant', '2026-11-05 08:00:00', 'CHECK_IN', '2026-11-05', NULL, 'Work'),
            (2, 8, 101, 'Anant', '2026-11-05 08:00:30', 'CHECK_IN', '2026-11-05', NULL, 'Work'),
            (3, 8, 101, 'Anant', '2026-11-05 17:00:00', 'CHECK_OUT', '2026-11-05', NULL, 'Work');
        INSERT INTO attendance_events VALUES
            ('event-1', 1, 'ACCEPTED'), ('event-2', 2, 'ACCEPTED'), ('event-3', 3, 'ACCEPTED');
        """
    )
    rows = [_row(1, "2026-11-05 08:00:00", "CHECK_IN"),
            _row(2, "2026-11-05 08:00:30", "CHECK_IN"),
            _row(3, "2026-11-05 17:00:00", "CHECK_OUT")]
    findings = find_invalid_transitions(rows)

    result = apply_findings(
        connection.cursor(), findings, repaired_by="admin@example.com", run_id="run-1"
    )
    connection.commit()

    assert result == {
        "run_id": "run-1", "repaired": 1, "skipped": 0, "manual_review": 0
    }
    assert connection.execute("SELECT id, status FROM attendance ORDER BY id").fetchall() == [
        (1, "CHECK_IN"), (3, "CHECK_OUT")
    ]
    assert connection.execute(
        "SELECT legacy_attendance_id, ingestion_status FROM attendance_events WHERE id = 'event-2'"
    ).fetchone() == (None, "REJECTED")
    assert connection.execute(
        "SELECT original_attendance_id, reason, repaired_by FROM attendance_repair_audit"
    ).fetchone() == (2, "duplicate_check_in", "admin@example.com")
