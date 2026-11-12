"""Session-aware academic enrollment and promotion rules.

Student identity belongs to ``faces``.  Program, year, semester, division and
roll number belong to an effective-dated enrollment so promotions never rewrite
historical academic context.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import re

from services.person_scope_service import parse_custom_data


SESSION_STATUSES = {"PLANNED", "ACTIVE", "CLOSED"}
PROGRAM_STRUCTURES = {"ANNUAL", "SEMESTER"}
ENROLLMENT_STATUSES = {
    "ACTIVE", "COMPLETED", "PROMOTED", "TRANSFERRED", "REPEAT",
    "GRADUATED", "LEFT", "CANCELLED",
}
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,49}$")


class AcademicLifecycleError(ValueError):
    def __init__(self, message, code="ACADEMIC_VALIDATION_ERROR", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _is_pg(conn):
    return bool(getattr(conn, "_is_pg", False)) or "psycopg" in str(type(conn)).lower()


def _row_dict(row, columns=None):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    if columns:
        return dict(zip(columns, row))
    return row


def _parse_date(value, field, required=True):
    if value in (None, ""):
        if required:
            raise AcademicLifecycleError(f"{field} is required")
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise AcademicLifecycleError(f"{field} must use YYYY-MM-DD") from exc


def _code(value, field):
    normalized = str(value or "").strip().upper()
    if not CODE_PATTERN.fullmatch(normalized):
        raise AcademicLifecycleError(
            f"{field} must contain 1-50 letters, numbers, dots, underscores or hyphens"
        )
    return normalized


def _positive_int(value, field, minimum=1, maximum=20):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AcademicLifecycleError(f"{field} must be a whole number") from exc
    if parsed < minimum or parsed > maximum:
        raise AcademicLifecycleError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def ensure_academic_tables(conn):
    """Create the normalized lifecycle tables for tests and rolling deployments."""

    cursor = conn.cursor()
    pg = _is_pg(conn)
    statements = [
        (
            "CREATE TABLE IF NOT EXISTS academic_sessions ("
            + ("id SERIAL PRIMARY KEY" if pg else "id INTEGER PRIMARY KEY AUTOINCREMENT")
            + ", vendor_id INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL, "
              "start_date DATE NOT NULL, end_date DATE NOT NULL, status TEXT NOT NULL DEFAULT 'PLANNED', "
              "created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
              "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(vendor_id, code))"
        ),
        (
            "CREATE TABLE IF NOT EXISTS academic_programs ("
            + ("id SERIAL PRIMARY KEY" if pg else "id INTEGER PRIMARY KEY AUTOINCREMENT")
            + ", vendor_id INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL, "
              "duration_years INTEGER NOT NULL, structure TEXT NOT NULL DEFAULT 'SEMESTER', "
              "semesters_per_year INTEGER NOT NULL DEFAULT 2, is_active INTEGER NOT NULL DEFAULT 1, "
              "created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
              "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(vendor_id, code))"
        ),
        (
            "CREATE TABLE IF NOT EXISTS student_enrollments ("
            + ("id SERIAL PRIMARY KEY" if pg else "id INTEGER PRIMARY KEY AUTOINCREMENT")
            + ", vendor_id INTEGER NOT NULL, person_id INTEGER NOT NULL, "
              "academic_session_id INTEGER NOT NULL, program_id INTEGER NOT NULL, class_id INTEGER, "
              "year_of_study INTEGER NOT NULL, semester INTEGER, division TEXT NOT NULL, roll_number TEXT, "
              "status TEXT NOT NULL DEFAULT 'ACTIVE', effective_from DATE NOT NULL, effective_to DATE, "
              "source TEXT NOT NULL DEFAULT 'MANUAL', change_reason TEXT NOT NULL DEFAULT 'Initial enrollment', "
              "created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
              "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ),
        (
            "CREATE TABLE IF NOT EXISTS student_enrollment_audit ("
            + ("id SERIAL PRIMARY KEY" if pg else "id INTEGER PRIMARY KEY AUTOINCREMENT")
            + ", vendor_id INTEGER NOT NULL, person_id INTEGER NOT NULL, enrollment_id INTEGER, "
              "action TEXT NOT NULL, previous_data TEXT, new_data TEXT, actor_username TEXT, "
              "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ),
        "CREATE INDEX IF NOT EXISTS idx_academic_sessions_vendor_status ON academic_sessions(vendor_id, status, start_date)",
        "CREATE INDEX IF NOT EXISTS idx_academic_programs_vendor_active ON academic_programs(vendor_id, is_active, code)",
        "CREATE INDEX IF NOT EXISTS idx_student_enrollment_resolution ON student_enrollments(vendor_id, person_id, effective_from, effective_to)",
        "CREATE INDEX IF NOT EXISTS idx_student_enrollment_roster ON student_enrollments(vendor_id, academic_session_id, program_id, year_of_study, division, status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_student_enrollment_active_scope "
        "ON student_enrollments(vendor_id, person_id, academic_session_id, program_id, "
        "year_of_study, COALESCE(semester, 0), LOWER(TRIM(division))) WHERE status = 'ACTIVE'",
    ]
    for statement in statements:
        cursor.execute(statement)

    additive_columns = {
        "classes": [
            "academic_session_id INTEGER", "program_id INTEGER", "year_of_study INTEGER",
            "semester INTEGER", "status TEXT DEFAULT 'ACTIVE'",
        ],
        "attendance": [
            "enrollment_id INTEGER", "academic_session_id INTEGER", "program_id INTEGER",
            "year_of_study INTEGER", "semester INTEGER",
        ],
        "lectures": ["class_id INTEGER", "academic_session_id INTEGER", "program_id INTEGER"],
    }
    for table, definitions in additive_columns.items():
        for definition in definitions:
            try:
                if pg:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {definition}")
                else:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            except Exception as exc:
                message = str(exc).lower()
                if "duplicate column" not in message and "already exists" not in message:
                    raise
    conn.commit()


def list_academic_config(conn, vendor_id):
    ensure_academic_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, code, name, start_date, end_date, status, created_at, updated_at "
        "FROM academic_sessions WHERE vendor_id = ? ORDER BY start_date DESC, id DESC",
        (vendor_id,),
    )
    session_columns = ["id", "code", "name", "start_date", "end_date", "status", "created_at", "updated_at"]
    sessions = [_row_dict(row, session_columns) for row in cursor.fetchall()]
    cursor.execute(
        "SELECT id, code, name, duration_years, structure, semesters_per_year, is_active, created_at, updated_at "
        "FROM academic_programs WHERE vendor_id = ? ORDER BY name, code",
        (vendor_id,),
    )
    program_columns = [
        "id", "code", "name", "duration_years", "structure", "semesters_per_year",
        "is_active", "created_at", "updated_at",
    ]
    programs = [_row_dict(row, program_columns) for row in cursor.fetchall()]
    return {"sessions": sessions, "programs": programs}


def create_academic_session(conn, vendor_id, payload, actor):
    code = _code(payload.get("code"), "Session code")
    name = str(payload.get("name") or code).strip()[:100]
    start_date = _parse_date(payload.get("start_date"), "start_date")
    end_date = _parse_date(payload.get("end_date"), "end_date")
    if end_date < start_date:
        raise AcademicLifecycleError("end_date must be on or after start_date")
    status = str(payload.get("status") or "PLANNED").strip().upper()
    if status not in SESSION_STATUSES:
        raise AcademicLifecycleError(f"status must be one of {sorted(SESSION_STATUSES)}")
    ensure_academic_tables(conn)
    cursor = conn.cursor()
    if status == "ACTIVE":
        cursor.execute(
            "UPDATE academic_sessions SET status = 'CLOSED', updated_at = CURRENT_TIMESTAMP "
            "WHERE vendor_id = ? AND status = 'ACTIVE'",
            (vendor_id,),
        )
        cursor.execute(
            "UPDATE classes SET status = 'ARCHIVED' WHERE vendor_id = ? "
            "AND academic_session_id IS NOT NULL",
            (vendor_id,),
        )
    try:
        cursor.execute(
            "INSERT INTO academic_sessions "
            "(vendor_id, code, name, start_date, end_date, status, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vendor_id, code, name, start_date.isoformat(), end_date.isoformat(), status, actor),
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise AcademicLifecycleError("This academic session code already exists", "DUPLICATE_SESSION", 409) from exc
        raise
    session_id = cursor.lastrowid
    if status == "ACTIVE":
        cursor.execute(
            "UPDATE classes SET status = 'ACTIVE' WHERE vendor_id = ? AND academic_session_id = ?",
            (vendor_id, session_id),
        )
    conn.commit()
    return session_id


def create_academic_program(conn, vendor_id, payload, actor):
    code = _code(payload.get("code"), "Program code")
    name = str(payload.get("name") or "").strip()[:120]
    if not name:
        raise AcademicLifecycleError("Program name is required")
    duration_years = _positive_int(payload.get("duration_years"), "duration_years", 1, 12)
    structure = str(payload.get("structure") or "SEMESTER").strip().upper()
    if structure not in PROGRAM_STRUCTURES:
        raise AcademicLifecycleError(f"structure must be one of {sorted(PROGRAM_STRUCTURES)}")
    semesters_per_year = 1 if structure == "ANNUAL" else _positive_int(
        payload.get("semesters_per_year", 2), "semesters_per_year", 1, 4,
    )
    ensure_academic_tables(conn)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO academic_programs "
            "(vendor_id, code, name, duration_years, structure, semesters_per_year, is_active, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (vendor_id, code, name, duration_years, structure, semesters_per_year,
             1 if payload.get("is_active", True) else 0, actor),
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise AcademicLifecycleError("This program code already exists", "DUPLICATE_PROGRAM", 409) from exc
        raise
    program_id = cursor.lastrowid
    conn.commit()
    return program_id


def update_academic_session(conn, vendor_id, session_id, payload):
    ensure_academic_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, code, name, start_date, end_date, status FROM academic_sessions "
        "WHERE id = ? AND vendor_id = ?",
        (session_id, vendor_id),
    )
    row = _row_dict(cursor.fetchone(), ["id", "code", "name", "start_date", "end_date", "status"])
    if not row:
        raise AcademicLifecycleError("Academic session not found", "SESSION_NOT_FOUND", 404)
    code = _code(payload.get("code", row["code"]), "Session code")
    name = str(payload.get("name", row["name"]) or code).strip()[:100]
    start_date = _parse_date(payload.get("start_date", row["start_date"]), "start_date")
    end_date = _parse_date(payload.get("end_date", row["end_date"]), "end_date")
    if end_date < start_date:
        raise AcademicLifecycleError("end_date must be on or after start_date")
    status = str(payload.get("status", row["status"]) or "PLANNED").strip().upper()
    if status not in SESSION_STATUSES:
        raise AcademicLifecycleError(f"status must be one of {sorted(SESSION_STATUSES)}")
    previous_session_status = str(row["status"]).upper()
    allowed_transitions = {
        "PLANNED": {"PLANNED", "ACTIVE", "CLOSED"},
        "ACTIVE": {"ACTIVE", "CLOSED"},
        "CLOSED": {"CLOSED"},
    }
    if status not in allowed_transitions.get(previous_session_status, set()):
        raise AcademicLifecycleError(
            f"Academic session cannot change from {previous_session_status} to {status}",
            "SESSION_HISTORY_LOCKED",
            409,
        )
    cursor.execute(
        "SELECT COUNT(*) FROM student_enrollments WHERE vendor_id = ? AND academic_session_id = ?",
        (vendor_id, session_id),
    )
    if int(cursor.fetchone()[0] or 0) > 0 and (
        code != str(row["code"])
        or start_date != _parse_date(row["start_date"], "start_date")
        or end_date != _parse_date(row["end_date"], "end_date")
    ):
        raise AcademicLifecycleError(
            "Session code and dates cannot change after students are enrolled",
            "SESSION_HISTORY_LOCKED",
            409,
        )
    if status == "ACTIVE":
        cursor.execute(
            "UPDATE academic_sessions SET status = 'CLOSED', updated_at = CURRENT_TIMESTAMP "
            "WHERE vendor_id = ? AND status = 'ACTIVE' AND id <> ?",
            (vendor_id, session_id),
        )
        cursor.execute(
            "UPDATE classes SET status = CASE WHEN academic_session_id = ? THEN 'ACTIVE' ELSE 'ARCHIVED' END "
            "WHERE vendor_id = ? AND academic_session_id IS NOT NULL",
            (session_id, vendor_id),
        )
    elif status == "CLOSED":
        cursor.execute(
            "UPDATE classes SET status = 'ARCHIVED' WHERE vendor_id = ? AND academic_session_id = ?",
            (vendor_id, session_id),
        )
    cursor.execute(
        "UPDATE academic_sessions SET code = ?, name = ?, start_date = ?, end_date = ?, status = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND vendor_id = ?",
        (code, name, start_date.isoformat(), end_date.isoformat(), status, session_id, vendor_id),
    )
    conn.commit()


def update_academic_program(conn, vendor_id, program_id, payload):
    ensure_academic_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, code, name, duration_years, structure, semesters_per_year, is_active "
        "FROM academic_programs WHERE id = ? AND vendor_id = ?",
        (program_id, vendor_id),
    )
    columns = ["id", "code", "name", "duration_years", "structure", "semesters_per_year", "is_active"]
    row = _row_dict(cursor.fetchone(), columns)
    if not row:
        raise AcademicLifecycleError("Academic program not found", "PROGRAM_NOT_FOUND", 404)
    code = _code(payload.get("code", row["code"]), "Program code")
    name = str(payload.get("name", row["name"]) or "").strip()[:120]
    duration = _positive_int(payload.get("duration_years", row["duration_years"]), "duration_years", 1, 12)
    structure = str(payload.get("structure", row["structure"]) or "SEMESTER").strip().upper()
    if structure not in PROGRAM_STRUCTURES:
        raise AcademicLifecycleError(f"structure must be one of {sorted(PROGRAM_STRUCTURES)}")
    semesters = 1 if structure == "ANNUAL" else _positive_int(
        payload.get("semesters_per_year", row["semesters_per_year"]), "semesters_per_year", 1, 4,
    )
    cursor.execute(
        "SELECT COUNT(*), COALESCE(MAX(year_of_study), 0) FROM student_enrollments "
        "WHERE vendor_id = ? AND program_id = ?",
        (vendor_id, program_id),
    )
    usage_count, maximum_enrolled_year = cursor.fetchone()
    if int(usage_count or 0) > 0 and (
        code != str(row["code"])
        or structure != str(row["structure"])
        or semesters != int(row["semesters_per_year"])
    ):
        raise AcademicLifecycleError(
            "Program code and term structure cannot change after students are enrolled",
            "PROGRAM_HISTORY_LOCKED",
            409,
        )
    if duration < int(maximum_enrolled_year or 0):
        raise AcademicLifecycleError(
            f"Program duration cannot be below enrolled year {maximum_enrolled_year}",
            "PROGRAM_DURATION_CONFLICT",
            409,
        )
    cursor.execute(
        "UPDATE academic_programs SET code = ?, name = ?, duration_years = ?, structure = ?, "
        "semesters_per_year = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND vendor_id = ?",
        (code, name, duration, structure, semesters,
         1 if payload.get("is_active", bool(row["is_active"])) else 0, program_id, vendor_id),
    )
    conn.commit()


def _find_session(cursor, vendor_id, *, session_id=None, code=None):
    if session_id not in (None, ""):
        try:
            parsed_id = int(session_id)
        except (TypeError, ValueError) as exc:
            raise AcademicLifecycleError("academic_session_id must be a whole number") from exc
        cursor.execute(
            "SELECT id, code, name, start_date, end_date, status FROM academic_sessions "
            "WHERE vendor_id = ? AND id = ?",
            (vendor_id, parsed_id),
        )
    elif code not in (None, ""):
        cursor.execute(
            "SELECT id, code, name, start_date, end_date, status FROM academic_sessions "
            "WHERE vendor_id = ? AND UPPER(code) = UPPER(?)",
            (vendor_id, str(code).strip()),
        )
    else:
        cursor.execute(
            "SELECT id, code, name, start_date, end_date, status FROM academic_sessions "
            "WHERE vendor_id = ? AND status = 'ACTIVE' ORDER BY start_date DESC LIMIT 1",
            (vendor_id,),
        )
    return _row_dict(cursor.fetchone(), ["id", "code", "name", "start_date", "end_date", "status"])


def _find_program(cursor, vendor_id, *, program_id=None, code=None):
    if program_id in (None, "") and code in (None, ""):
        return None
    if program_id not in (None, ""):
        try:
            parsed_id = int(program_id)
        except (TypeError, ValueError) as exc:
            raise AcademicLifecycleError("program_id must be a whole number") from exc
        cursor.execute(
            "SELECT id, code, name, duration_years, structure, semesters_per_year, is_active "
            "FROM academic_programs WHERE vendor_id = ? AND id = ?",
            (vendor_id, parsed_id),
        )
    else:
        cursor.execute(
            "SELECT id, code, name, duration_years, structure, semesters_per_year, is_active "
            "FROM academic_programs WHERE vendor_id = ? AND UPPER(code) = UPPER(?)",
            (vendor_id, str(code).strip()),
        )
    return _row_dict(
        cursor.fetchone(),
        ["id", "code", "name", "duration_years", "structure", "semesters_per_year", "is_active"],
    )


def validate_enrollment_scope(conn, vendor_id, payload, *, ensure_schema=True):
    if ensure_schema:
        ensure_academic_tables(conn)
    cursor = conn.cursor()
    session = _find_session(
        cursor, vendor_id, session_id=payload.get("academic_session_id"),
        code=payload.get("academic_session"),
    )
    if not session:
        raise AcademicLifecycleError("Academic session was not found", "SESSION_NOT_FOUND", 400)
    if session["status"] != "ACTIVE":
        raise AcademicLifecycleError(
            "Enrollments can only be saved in the active academic session",
            "SESSION_NOT_ACTIVE",
            409,
        )
    program = _find_program(
        cursor, vendor_id, program_id=payload.get("program_id"),
        code=payload.get("program_code") or payload.get("branch"),
    )
    if not program or not program["is_active"]:
        raise AcademicLifecycleError("Active program code was not found", "PROGRAM_NOT_FOUND", 400)
    year = _positive_int(payload.get("year_of_study") or payload.get("class_year"), "year_of_study", 1, int(program["duration_years"]))
    semester = payload.get("semester")
    if program["structure"] == "SEMESTER":
        semester = _positive_int(semester, "semester", 1, int(program["duration_years"]) * int(program["semesters_per_year"]))
        expected_year = ((semester - 1) // int(program["semesters_per_year"])) + 1
        if expected_year != year:
            raise AcademicLifecycleError(
                f"Semester {semester} belongs to year {expected_year}, not year {year}",
                "SEMESTER_YEAR_MISMATCH",
            )
    else:
        semester = None
    division = str(payload.get("division") or "").strip()[:80]
    if not division:
        raise AcademicLifecycleError("division is required")
    effective_from = _parse_date(payload.get("effective_from") or session["start_date"], "effective_from")
    session_start = _parse_date(session["start_date"], "session start date")
    session_end = _parse_date(session["end_date"], "session end date")
    if effective_from < session_start or effective_from > session_end:
        raise AcademicLifecycleError(
            "effective_from must fall within the selected academic session",
            "ENROLLMENT_DATE_OUTSIDE_SESSION",
        )
    return {
        "session": session,
        "program": program,
        "year_of_study": year,
        "semester": semester,
        "division": division,
        "roll_number": str(payload.get("roll_number") or "").strip()[:80] or None,
        "effective_from": effective_from,
    }


def ensure_academic_class(conn, vendor_id, scope):
    cursor = conn.cursor()
    semester = scope["semester"]
    cursor.execute(
        "SELECT id FROM classes WHERE vendor_id = ? AND academic_session_id = ? AND program_id = ? "
        "AND year_of_study = ? AND COALESCE(semester, 0) = ? "
        "AND LOWER(TRIM(COALESCE(division, ''))) = LOWER(TRIM(?)) LIMIT 1",
        (vendor_id, scope["session"]["id"], scope["program"]["id"], scope["year_of_study"],
         semester or 0, scope["division"]),
    )
    row = cursor.fetchone()
    if row:
        return row[0]
    parts = [scope["session"]["code"], scope["program"]["code"], f"Year {scope['year_of_study']}"]
    if semester:
        parts.append(f"Sem {semester}")
    parts.append(scope["division"])
    label = " · ".join(parts)
    cursor.execute(
        "INSERT INTO classes "
        "(vendor_id, class_year, division, branch, label, mapped_subjects, academic_session_id, "
        "program_id, year_of_study, semester, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')",
        (vendor_id, str(scope["year_of_study"]), scope["division"], scope["program"]["code"],
         label, "[]", scope["session"]["id"], scope["program"]["id"],
         scope["year_of_study"], semester),
    )
    return cursor.lastrowid


def _audit(cursor, vendor_id, person_id, enrollment_id, action, previous, new, actor):
    cursor.execute(
        "INSERT INTO student_enrollment_audit "
        "(vendor_id, person_id, enrollment_id, action, previous_data, new_data, actor_username) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (vendor_id, person_id, enrollment_id, action,
         json.dumps(previous, default=str, separators=(",", ":")) if previous else None,
         json.dumps(new, default=str, separators=(",", ":")) if new else None, actor),
    )


def _sync_face_scope(cursor, vendor_id, person_id, enrollment):
    cursor.execute("SELECT custom_data FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
    row = cursor.fetchone()
    if not row:
        raise AcademicLifecycleError("Student was not found", "STUDENT_NOT_FOUND", 404)
    custom = parse_custom_data(row[0])
    custom.update({
        "person_type": "student",
        "class_id": str(enrollment["class_id"]),
        "class_year": str(enrollment["year_of_study"]),
        "year_of_study": enrollment["year_of_study"],
        "semester": enrollment["semester"],
        "division": enrollment["division"],
        "branch": enrollment["program_code"],
        "program_code": enrollment["program_code"],
        "academic_session": enrollment["session_code"],
        "academic_session_id": enrollment["academic_session_id"],
        "enrollment_id": enrollment["id"],
    })
    if enrollment.get("roll_number"):
        custom["roll_number"] = enrollment["roll_number"]
    cursor.execute(
        "UPDATE faces SET custom_data = ? WHERE id = ? AND vendor_id = ?",
        (json.dumps(custom, separators=(",", ":")), person_id, vendor_id),
    )


def enroll_student(
    conn, vendor_id, person_id, payload, actor, source="MANUAL", *,
    ensure_schema=True, commit=True, previous_status=None,
):
    scope = validate_enrollment_scope(conn, vendor_id, payload, ensure_schema=ensure_schema)
    cursor = conn.cursor()
    class_id = ensure_academic_class(conn, vendor_id, scope)
    session_id = scope["session"]["id"]
    cursor.execute(
        "SELECT id, vendor_id, person_id, academic_session_id, program_id, class_id, year_of_study, "
        "semester, division, roll_number, status, effective_from, effective_to, source, change_reason "
        "FROM student_enrollments WHERE vendor_id = ? AND person_id = ? AND academic_session_id = ? "
        "AND program_id = ? AND year_of_study = ? AND COALESCE(semester, 0) = ? "
        "AND LOWER(TRIM(division)) = LOWER(TRIM(?)) AND status = 'ACTIVE' LIMIT 1",
        (vendor_id, person_id, session_id, scope["program"]["id"], scope["year_of_study"],
         scope["semester"] or 0, scope["division"]),
    )
    columns = [
        "id", "vendor_id", "person_id", "academic_session_id", "program_id", "class_id",
        "year_of_study", "semester", "division", "roll_number", "status", "effective_from",
        "effective_to", "source", "change_reason",
    ]
    existing = _row_dict(cursor.fetchone(), columns)
    reason = str(payload.get("change_reason") or "Initial enrollment").strip()[:255]
    if existing:
        changed = existing.get("roll_number") != scope["roll_number"] or existing.get("class_id") != class_id
        if changed:
            cursor.execute(
                "UPDATE student_enrollments SET class_id = ?, roll_number = ?, change_reason = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND vendor_id = ?",
                (class_id, scope["roll_number"], reason, existing["id"], vendor_id),
            )
            _audit(cursor, vendor_id, person_id, existing["id"], "UPDATED", existing,
                   {**existing, "class_id": class_id, "roll_number": scope["roll_number"]}, actor)
        result = {
            **existing, "class_id": class_id, "roll_number": scope["roll_number"],
            "program_code": scope["program"]["code"], "session_code": scope["session"]["code"],
        }
        _sync_face_scope(cursor, vendor_id, person_id, result)
        if commit:
            conn.commit()
        return result, "updated" if changed else "unchanged"

    close_date = scope["effective_from"] - timedelta(days=1)
    cursor.execute(
        "SELECT id, academic_session_id, program_id, year_of_study, semester, division, status, "
        "effective_from, effective_to FROM student_enrollments "
        "WHERE vendor_id = ? AND person_id = ? AND status = 'ACTIVE'",
        (vendor_id, person_id),
    )
    active_rows = cursor.fetchall() or []
    active_columns = [
        "id", "academic_session_id", "program_id", "year_of_study", "semester", "division",
        "status", "effective_from", "effective_to",
    ]
    for active_row in active_rows:
        previous = _row_dict(active_row, active_columns)
        previous_start = _parse_date(previous["effective_from"], "effective_from")
        if close_date < previous_start:
            raise AcademicLifecycleError(
                "The new enrollment starts before the current enrollment. Correct the effective date first.",
                "ENROLLMENT_DATE_CONFLICT", 409,
            )
        close_status = previous_status or (
            "TRANSFERRED" if int(previous["academic_session_id"]) == int(session_id) else "PROMOTED"
        )
        if close_status not in {"PROMOTED", "TRANSFERRED", "REPEAT"}:
            raise AcademicLifecycleError("Invalid prior enrollment status")
        cursor.execute(
            "UPDATE student_enrollments SET status = ?, effective_to = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND vendor_id = ?",
            (close_status, close_date.isoformat(), previous["id"], vendor_id),
        )
        _audit(cursor, vendor_id, person_id, previous["id"], close_status, previous,
               {**previous, "status": close_status, "effective_to": close_date.isoformat()}, actor)

    cursor.execute(
        "INSERT INTO student_enrollments "
        "(vendor_id, person_id, academic_session_id, program_id, class_id, year_of_study, semester, "
        "division, roll_number, status, effective_from, source, change_reason, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)",
        (vendor_id, person_id, session_id, scope["program"]["id"], class_id,
         scope["year_of_study"], scope["semester"], scope["division"], scope["roll_number"],
         scope["effective_from"].isoformat(), str(source or "MANUAL")[:40], reason, actor),
    )
    enrollment_id = cursor.lastrowid
    result = {
        "id": enrollment_id, "vendor_id": vendor_id, "person_id": person_id,
        "academic_session_id": session_id, "program_id": scope["program"]["id"],
        "class_id": class_id, "year_of_study": scope["year_of_study"],
        "semester": scope["semester"], "division": scope["division"],
        "roll_number": scope["roll_number"], "status": "ACTIVE",
        "effective_from": scope["effective_from"].isoformat(), "effective_to": None,
        "program_code": scope["program"]["code"], "session_code": scope["session"]["code"],
    }
    _audit(cursor, vendor_id, person_id, enrollment_id, "CREATED", None, result, actor)
    _sync_face_scope(cursor, vendor_id, person_id, result)
    if commit:
        conn.commit()
    return result, "created"


def resolve_enrollment(conn, vendor_id, person_id, on_date, *, ensure_schema=True):
    if ensure_schema:
        ensure_academic_tables(conn)
    target = _parse_date(on_date, "on_date")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT e.id, e.academic_session_id, e.program_id, e.class_id, e.year_of_study, "
        "e.semester, e.division, e.roll_number, e.status, e.effective_from, e.effective_to, "
        "s.code, p.code, p.name FROM student_enrollments e "
        "JOIN academic_sessions s ON s.id = e.academic_session_id AND s.vendor_id = e.vendor_id "
        "JOIN academic_programs p ON p.id = e.program_id AND p.vendor_id = e.vendor_id "
        "WHERE e.vendor_id = ? AND e.person_id = ? AND e.effective_from <= ? "
        "AND (e.effective_to IS NULL OR e.effective_to >= ?) "
        "ORDER BY e.effective_from DESC, e.id DESC LIMIT 1",
        (vendor_id, person_id, target.isoformat(), target.isoformat()),
    )
    columns = [
        "id", "academic_session_id", "program_id", "class_id", "year_of_study", "semester",
        "division", "roll_number", "status", "effective_from", "effective_to", "session_code",
        "program_code", "program_name",
    ]
    return _row_dict(cursor.fetchone(), columns)


def list_enrollments(conn, vendor_id, person_id=None, session_id=None, active_only=False):
    ensure_academic_tables(conn)
    cursor = conn.cursor()
    query = (
        "SELECT e.id, e.person_id, f.name, e.academic_session_id, s.code, e.program_id, p.code, p.name, "
        "e.class_id, e.year_of_study, e.semester, e.division, e.roll_number, e.status, "
        "e.effective_from, e.effective_to, e.source, e.change_reason, e.created_at "
        "FROM student_enrollments e JOIN faces f ON f.id = e.person_id AND f.vendor_id = e.vendor_id "
        "JOIN academic_sessions s ON s.id = e.academic_session_id AND s.vendor_id = e.vendor_id "
        "JOIN academic_programs p ON p.id = e.program_id AND p.vendor_id = e.vendor_id "
        "WHERE e.vendor_id = ?"
    )
    params = [vendor_id]
    if person_id is not None:
        query += " AND e.person_id = ?"
        params.append(person_id)
    if session_id is not None:
        query += " AND e.academic_session_id = ?"
        params.append(session_id)
    if active_only:
        query += " AND e.status = 'ACTIVE'"
    query += " ORDER BY s.start_date DESC, p.name, e.year_of_study, e.division, f.name"
    cursor.execute(query, tuple(params))
    columns = [
        "id", "person_id", "student_name", "academic_session_id", "session_code", "program_id",
        "program_code", "program_name", "class_id", "year_of_study", "semester", "division",
        "roll_number", "status", "effective_from", "effective_to", "source", "change_reason", "created_at",
    ]
    return [_row_dict(row, columns) for row in cursor.fetchall()]


def promotion_preview(conn, vendor_id, source_session_id, target_session_id):
    config = list_academic_config(conn, vendor_id)
    sessions = {int(item["id"]): item for item in config["sessions"]}
    if int(source_session_id) not in sessions or int(target_session_id) not in sessions:
        raise AcademicLifecycleError("Source or target academic session was not found", "SESSION_NOT_FOUND", 404)
    if int(source_session_id) == int(target_session_id):
        raise AcademicLifecycleError("Source and target sessions must be different")
    source_session = sessions[int(source_session_id)]
    target_session = sessions[int(target_session_id)]
    if _parse_date(target_session["start_date"], "target start date") <= _parse_date(
        source_session["start_date"], "source start date"
    ):
        raise AcademicLifecycleError(
            "Target session must start after the source session",
            "SESSION_ORDER_INVALID",
        )
    rows = list_enrollments(conn, vendor_id, session_id=source_session_id, active_only=True)
    programs = {int(item["id"]): item for item in config["programs"]}
    preview = []
    for row in rows:
        program = programs[int(row["program_id"])]
        next_year = int(row["year_of_study"]) + 1
        if next_year > int(program["duration_years"]):
            action = "graduate"
            next_semester = None
        else:
            action = "promote"
            next_semester = (
                ((next_year - 1) * int(program["semesters_per_year"])) + 1
                if program["structure"] == "SEMESTER" else None
            )
        preview.append({
            **row, "suggested_action": action, "target_session_id": int(target_session_id),
            "target_session_code": target_session["code"],
            "target_year_of_study": None if action == "graduate" else next_year,
            "target_semester": next_semester,
        })
    return preview


def execute_promotions(conn, vendor_id, source_session_id, target_session_id, decisions, actor):
    preview = promotion_preview(conn, vendor_id, source_session_id, target_session_id)
    by_person = {int(item["person_id"]): item for item in preview}
    decision_rows = decisions or []
    supplied = {int(item.get("person_id")): item for item in decision_rows if item.get("person_id") is not None}
    if len(supplied) != len(decision_rows):
        raise AcademicLifecycleError("Each promotion decision must contain one unique person_id")
    missing = sorted(set(by_person) - set(supplied))
    unknown = sorted(set(supplied) - set(by_person))
    if missing or unknown:
        raise AcademicLifecycleError(
            "Promotion decisions must include every student in the preview exactly once",
            "INCOMPLETE_PROMOTION_DECISIONS",
            409,
        )
    results = []
    target_session = next(
        item for item in list_academic_config(conn, vendor_id)["sessions"]
        if int(item["id"]) == int(target_session_id)
    )
    if target_session["status"] != "ACTIVE":
        raise AcademicLifecycleError(
            "Activate the target academic session before applying promotions",
            "SESSION_NOT_ACTIVE",
            409,
        )
    cursor = conn.cursor()
    for person_id, current in by_person.items():
        decision = supplied.get(person_id, {})
        action = str(decision.get("action") or current["suggested_action"]).strip().lower()
        if action in {"graduate", "leave"}:
            final_status = "GRADUATED" if action == "graduate" else "LEFT"
            end_date = _parse_date(target_session["start_date"], "target start date") - timedelta(days=1)
            cursor.execute(
                "UPDATE student_enrollments SET status = ?, effective_to = ?, change_reason = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND vendor_id = ? AND status = 'ACTIVE'",
                (final_status, end_date.isoformat(), decision.get("reason") or final_status.title(),
                 current["id"], vendor_id),
            )
            _audit(cursor, vendor_id, person_id, current["id"], final_status, current,
                   {**current, "status": final_status, "effective_to": end_date.isoformat()}, actor)
            results.append({"person_id": person_id, "action": action, "status": final_status})
            continue
        if action not in {"promote", "repeat", "transfer"}:
            raise AcademicLifecycleError(f"Unsupported promotion action for student {person_id}")
        target_payload = {
            "academic_session_id": target_session_id,
            "program_id": decision.get("program_id") or current["program_id"],
            "year_of_study": decision.get("year_of_study") or (
                current["year_of_study"] if action == "repeat" else current["target_year_of_study"]
            ),
            "semester": decision.get("semester") if "semester" in decision else (
                current["semester"] if action == "repeat" else current["target_semester"]
            ),
            "division": decision.get("division") or current["division"],
            "roll_number": decision.get("roll_number") or current["roll_number"],
            "effective_from": target_session["start_date"],
            "change_reason": decision.get("reason") or action.title(),
        }
        enrollment, result = enroll_student(
            conn, vendor_id, person_id, target_payload, actor, source="PROMOTION",
            ensure_schema=False, commit=False,
            previous_status=("REPEAT" if action == "repeat" else "TRANSFERRED" if action == "transfer" else None),
        )
        results.append({"person_id": person_id, "action": action, "result": result, "enrollment": enrollment})
    conn.commit()
    return results
