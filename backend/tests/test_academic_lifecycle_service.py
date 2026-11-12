import json
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.academic_lifecycle_service import (
    AcademicLifecycleError,
    create_academic_program,
    create_academic_session,
    enroll_student,
    execute_promotions,
    list_academic_config,
    list_enrollments,
    promotion_preview,
    resolve_enrollment,
    update_academic_program,
    update_academic_session,
    validate_enrollment_scope,
)


@pytest.fixture()
def academic_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            custom_data TEXT DEFAULT '{}'
        );
        CREATE TABLE classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            class_year TEXT,
            division TEXT,
            branch TEXT,
            label TEXT,
            mapped_subjects TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE attendance (id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE lectures (id INTEGER PRIMARY KEY AUTOINCREMENT);
        INSERT INTO faces (vendor_id, name, custom_data)
        VALUES (8, 'Student One', '{"student_id":"ADM-001"}');
        """
    )
    yield conn
    conn.close()


def _session(conn, code, start, end, status="ACTIVE"):
    return create_academic_session(
        conn,
        8,
        {
            "code": code,
            "name": code,
            "start_date": start,
            "end_date": end,
            "status": status,
        },
        "admin@example.com",
    )


def _program(conn, code="BSC-CS", years=3, structure="SEMESTER", department="CSE"):
    return create_academic_program(
        conn,
        8,
        {
            "code": code,
            "name": code,
            "department_code": department,
            "duration_years": years,
            "structure": structure,
            "semesters_per_year": 2,
        },
        "admin@example.com",
    )


def test_program_duration_and_semester_rules_are_tenant_configured(academic_db):
    session_id = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    two_year_program = _program(academic_db, "MSC-IT", years=2)

    scope = validate_enrollment_scope(
        academic_db,
        8,
        {
            "academic_session_id": session_id,
            "program_id": two_year_program,
            "year_of_study": 2,
            "semester": 4,
            "division": "A",
        },
    )
    assert scope["year_of_study"] == 2
    assert scope["semester"] == 4

    with pytest.raises(AcademicLifecycleError, match="between 1 and 2"):
        validate_enrollment_scope(
            academic_db,
            8,
            {
                "academic_session_id": session_id,
                "program_id": two_year_program,
                "year_of_study": 3,
                "semester": 5,
                "division": "A",
            },
        )

    with pytest.raises(AcademicLifecycleError, match="belongs to year 2"):
        validate_enrollment_scope(
            academic_db,
            8,
            {
                "academic_session_id": session_id,
                "program_id": two_year_program,
                "year_of_study": 1,
                "semester": 3,
                "division": "A",
            },
        )


def test_reupload_is_idempotent_and_new_session_preserves_history(academic_db):
    first_session = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    program_id = _program(academic_db)
    first_payload = {
        "academic_session_id": first_session,
        "program_id": program_id,
        "year_of_study": 1,
        "semester": 1,
        "division": "A",
        "roll_number": "11",
    }

    first, result = enroll_student(academic_db, 8, 1, first_payload, "admin", source="BULK_IMPORT")
    assert result == "created"
    repeated, result = enroll_student(academic_db, 8, 1, first_payload, "admin", source="BULK_IMPORT")
    assert result == "unchanged"
    assert repeated["id"] == first["id"]

    second_session = _session(academic_db, "2027-28", "2027-06-01", "2028-05-31")
    second, result = enroll_student(
        academic_db,
        8,
        1,
        {
            "academic_session_id": second_session,
            "program_id": program_id,
            "year_of_study": 2,
            "semester": 3,
            "division": "B",
            "roll_number": "21",
        },
        "admin",
        source="BULK_IMPORT",
    )
    assert result == "created"
    assert second["id"] != first["id"]

    history = list_enrollments(academic_db, 8, person_id=1)
    assert len(history) == 2
    assert {row["status"] for row in history} == {"ACTIVE", "PROMOTED"}
    old = resolve_enrollment(academic_db, 8, 1, "2026-10-01")
    current = resolve_enrollment(academic_db, 8, 1, "2027-10-01")
    assert old["year_of_study"] == 1
    assert old["division"] == "A"
    assert current["year_of_study"] == 2
    assert current["division"] == "B"

    custom = json.loads(academic_db.execute("SELECT custom_data FROM faces WHERE id = 1").fetchone()[0])
    assert custom["academic_session"] == "2027-28"
    assert custom["year_of_study"] == 2
    assert custom["student_id"] == "ADM-001"
    assert custom["department"] == "CSE"
    assert academic_db.execute("SELECT department FROM faces WHERE id = 1").fetchone()[0] == "CSE"


def test_promotion_preview_graduates_final_year_and_executes_atomically(academic_db):
    source_session = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    program_id = _program(academic_db, "DIPLOMA", years=2)
    enroll_student(
        academic_db,
        8,
        1,
        {
            "academic_session_id": source_session,
            "program_id": program_id,
            "year_of_study": 2,
            "semester": 4,
            "division": "A",
        },
        "admin",
    )
    target_session = _session(academic_db, "2027-28", "2027-06-01", "2028-05-31")

    preview = promotion_preview(academic_db, 8, source_session, target_session)
    assert len(preview) == 1
    assert preview[0]["suggested_action"] == "graduate"

    results = execute_promotions(
        academic_db, 8, source_session, target_session,
        [{"person_id": 1, "action": "graduate", "reason": "Program completed"}],
        "admin",
    )
    assert results == [{"person_id": 1, "action": "graduate", "status": "GRADUATED"}]
    row = academic_db.execute(
        "SELECT status, effective_to, change_reason FROM student_enrollments WHERE person_id = 1"
    ).fetchone()
    assert row["status"] == "GRADUATED"
    assert row["effective_to"] == "2027-05-31"
    assert row["change_reason"] == "Program completed"


def test_promotion_rejects_a_target_session_that_starts_before_source(academic_db):
    older_session = _session(
        academic_db, "2025-26", "2025-06-01", "2026-05-31", status="PLANNED"
    )
    source_session = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")

    with pytest.raises(AcademicLifecycleError, match="must start after"):
        promotion_preview(academic_db, 8, source_session, older_session)


def test_promotion_starts_the_first_term_of_the_next_year(academic_db):
    source_session = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    program_id = _program(academic_db, "BTECH", years=4)
    enroll_student(
        academic_db,
        8,
        1,
        {
            "academic_session_id": source_session,
            "program_id": program_id,
            "year_of_study": 1,
            "semester": 2,
            "division": "A",
        },
        "admin",
    )
    target_session = _session(academic_db, "2027-28", "2027-06-01", "2028-05-31")

    preview = promotion_preview(academic_db, 8, source_session, target_session)
    assert preview[0]["target_year_of_study"] == 2
    assert preview[0]["target_semester"] == 3


def test_repeat_records_repeat_history_and_requires_complete_decisions(academic_db):
    source_session = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    program_id = _program(academic_db, "BCA", years=3)
    enroll_student(
        academic_db,
        8,
        1,
        {
            "academic_session_id": source_session,
            "program_id": program_id,
            "year_of_study": 1,
            "semester": 1,
            "division": "A",
        },
        "admin",
    )
    target_session = _session(academic_db, "2027-28", "2027-06-01", "2028-05-31")

    with pytest.raises(AcademicLifecycleError, match="include every student"):
        execute_promotions(academic_db, 8, source_session, target_session, [], "admin")

    execute_promotions(
        academic_db,
        8,
        source_session,
        target_session,
        [{"person_id": 1, "action": "repeat", "reason": "Repeat year"}],
        "admin",
    )
    history = list_enrollments(academic_db, 8, person_id=1)
    assert {row["status"] for row in history} == {"ACTIVE", "REPEAT"}
    assert next(row for row in history if row["status"] == "ACTIVE")["year_of_study"] == 1


def test_multiple_same_session_transfers_preserve_every_history_row(academic_db):
    session_id = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    program_id = _program(academic_db, "BSC", years=3)
    common = {
        "academic_session_id": session_id,
        "program_id": program_id,
        "year_of_study": 1,
        "semester": 1,
    }
    for division, effective_from in (
        ("A", "2026-06-01"),
        ("B", "2026-07-01"),
        ("A", "2026-08-01"),
        ("B", "2026-09-01"),
    ):
        enroll_student(
            academic_db,
            8,
            1,
            {**common, "division": division, "effective_from": effective_from},
            "admin",
        )

    history = list_enrollments(academic_db, 8, person_id=1)
    assert len(history) == 4
    assert sum(row["status"] == "TRANSFERRED" for row in history) == 3
    assert sum(row["status"] == "ACTIVE" for row in history) == 1


def test_used_session_and_program_structure_are_history_locked(academic_db):
    session_id = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    program_id = _program(academic_db, "BSC", years=3)
    enroll_student(
        academic_db,
        8,
        1,
        {
            "academic_session_id": session_id,
            "program_id": program_id,
            "year_of_study": 2,
            "semester": 3,
            "division": "A",
        },
        "admin",
    )

    with pytest.raises(AcademicLifecycleError, match="cannot change"):
        update_academic_session(academic_db, 8, session_id, {"code": "RENAMED"})
    with pytest.raises(AcademicLifecycleError, match="cannot change"):
        update_academic_program(academic_db, 8, program_id, {"structure": "ANNUAL"})
    with pytest.raises(AcademicLifecycleError, match="enrolled year 2"):
        update_academic_program(academic_db, 8, program_id, {"duration_years": 1})

    update_academic_program(academic_db, 8, program_id, {"duration_years": 4})
    program = next(
        row for row in list_academic_config(academic_db, 8)["programs"]
        if int(row["id"]) == int(program_id)
    )
    assert program["duration_years"] == 4


def test_planned_session_must_be_activated_before_enrollment(academic_db):
    session_id = _session(
        academic_db, "2027-28", "2027-06-01", "2028-05-31", status="PLANNED",
    )
    program_id = _program(academic_db, "BA", years=3, structure="ANNUAL")
    payload = {
        "academic_session_id": session_id,
        "program_id": program_id,
        "year_of_study": 1,
        "division": "A",
    }

    with pytest.raises(AcademicLifecycleError, match="active academic session"):
        enroll_student(academic_db, 8, 1, payload, "admin")

    update_academic_session(academic_db, 8, session_id, {"status": "ACTIVE"})
    enrollment, result = enroll_student(academic_db, 8, 1, payload, "admin")
    assert result == "created"
    assert enrollment["status"] == "ACTIVE"


def test_closed_session_cannot_be_reactivated(academic_db):
    first = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    _session(academic_db, "2027-28", "2027-06-01", "2028-05-31")

    with pytest.raises(AcademicLifecycleError, match="cannot change from CLOSED to ACTIVE"):
        update_academic_session(academic_db, 8, first, {"status": "ACTIVE"})


def test_enrollment_date_must_fall_inside_session(academic_db):
    session_id = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    program_id = _program(academic_db, "BBA", years=3, structure="ANNUAL")

    with pytest.raises(AcademicLifecycleError, match="within the selected academic session"):
        enroll_student(
            academic_db,
            8,
            1,
            {
                "academic_session_id": session_id,
                "program_id": program_id,
                "year_of_study": 1,
                "division": "A",
                "effective_from": "2027-06-01",
            },
            "admin",
        )


def test_promotions_require_an_active_target_session(academic_db):
    source_session = _session(academic_db, "2026-27", "2026-06-01", "2027-05-31")
    program_id = _program(academic_db, "DIP", years=2)
    enroll_student(
        academic_db,
        8,
        1,
        {
            "academic_session_id": source_session,
            "program_id": program_id,
            "year_of_study": 1,
            "semester": 1,
            "division": "A",
        },
        "admin",
    )
    target_session = _session(
        academic_db, "2027-28", "2027-06-01", "2028-05-31", status="PLANNED",
    )

    with pytest.raises(AcademicLifecycleError, match="Activate the target"):
        execute_promotions(
            academic_db,
            8,
            source_session,
            target_session,
            [{"person_id": 1, "action": "promote"}],
            "admin",
        )
