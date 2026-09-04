"""Canonical person-type and class-allocation rules.

School and hostel tenants store flexible registration fields in ``faces.custom_data``.
This module gives those records a stable contract without breaking legacy rows:

* a linked ``system_users.role`` is authoritative for faculty/student accounts;
* new records persist ``person_type`` explicitly in custom data;
* legacy non-faculty records in school/hostel tenants are treated as students;
* class IDs are authoritative, while class/year snapshots remain readable for
  older records and reporting.
"""

import json


SCHOOL_HOSTEL_VERTICALS = frozenset({"school", "hostel"})
PERSON_TYPES = frozenset({"student", "faculty", "employee"})
_PERSON_TYPE_ALIASES = {
    "pupil": "student",
    "learner": "student",
    "teacher": "faculty",
    "staff": "faculty",
}


def normalize_person_type(value, default=None):
    normalized = str(value or "").strip().lower()
    normalized = _PERSON_TYPE_ALIASES.get(normalized, normalized)
    return normalized if normalized in PERSON_TYPES else default


def is_school_hostel(vertical):
    return str(vertical or "").strip().lower() in SCHOOL_HOSTEL_VERTICALS


def parse_custom_data(value):
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def person_type_for(custom_data=None, system_role=None, vertical=None):
    """Resolve one canonical type, preferring the authenticated account role."""

    role_type = normalize_person_type(system_role)
    if role_type:
        return role_type
    if str(system_role or "").strip().lower() == "user" and is_school_hostel(vertical):
        return "student"

    custom = parse_custom_data(custom_data)
    explicit = normalize_person_type(
        custom.get("person_type") or custom.get("enrolment_type") or custom.get("enrollment_type")
    )
    if explicit:
        return explicit
    return "student" if is_school_hostel(vertical) else "employee"


def requested_person_type(value, vertical=None):
    """Validate an API filter and default School/Hostel views to students."""

    if value not in (None, ""):
        normalized = normalize_person_type(value)
        if not normalized:
            raise ValueError("person_type must be student, faculty, or employee")
        return normalized
    return "student" if is_school_hostel(vertical) else None


def class_id_for(custom_data):
    custom = parse_custom_data(custom_data)
    value = custom.get("class_id")
    return str(value).strip() if value not in (None, "") else ""


def class_scope_for(custom_data):
    custom = parse_custom_data(custom_data)
    return {
        "class_id": class_id_for(custom),
        "class_year": str(
            custom.get("class_year") or custom.get("year") or custom.get("Year") or ""
        ).strip(),
        "division": str(
            custom.get("division") or custom.get("Division") or custom.get("section")
            or custom.get("Section") or ""
        ).strip(),
        "branch": str(
            custom.get("branch") or custom.get("Branch") or custom.get("department")
            or custom.get("Department") or ""
        ).strip(),
    }


def has_class_allocation(custom_data):
    return bool(class_id_for(custom_data))


def class_scope_matches(custom_data, class_id=None, class_year=None, division=None, branch=None):
    """Match a student to a class using exact, case-insensitive values.

    ``class_id`` wins whenever the record has one. Snapshot matching is retained
    only so existing students can be displayed and moved into the normalized
    class-ID flow.
    """

    scope = class_scope_for(custom_data)
    wanted_id = str(class_id or "").strip()
    if wanted_id and scope["class_id"]:
        return scope["class_id"] == wanted_id

    # A class ID cannot safely be compared with a legacy record unless the
    # caller also supplied the class snapshots represented by that ID. Without
    # those snapshots, accepting the row would put every unallocated legacy
    # student into whichever class happened to be requested.
    snapshot_requested = any(
        str(value or "").strip() for value in (class_year, division, branch)
    )
    if wanted_id and not scope["class_id"] and not snapshot_requested:
        return False

    comparisons = (
        (class_year, scope["class_year"]),
        (division, scope["division"]),
        (branch, scope["branch"]),
    )
    for expected, actual in comparisons:
        expected_norm = str(expected or "").strip().casefold()
        if expected_norm and expected_norm != str(actual or "").strip().casefold():
            return False
    return bool(wanted_id or snapshot_requested)


def apply_class_mapping(custom_data, class_id, class_year="", division="", branch=""):
    custom = parse_custom_data(custom_data)
    custom.update({
        "class_id": str(class_id),
        "class_year": str(class_year or ""),
        "division": str(division or ""),
        "branch": str(branch or ""),
    })
    return custom


def faculty_person_ids(cursor, vendor_id):
    cursor.execute(
        "SELECT person_id FROM system_users "
        "WHERE vendor_id = ? AND LOWER(role) = 'faculty' AND person_id IS NOT NULL",
        (vendor_id,),
    )
    return {int(row[0]) for row in (cursor.fetchall() or []) if row[0] is not None}


def vendor_vertical(cursor, vendor_id):
    cursor.execute("SELECT vertical FROM vendors WHERE id = ?", (vendor_id,))
    row = cursor.fetchone()
    if not row:
        return ""
    try:
        return str(row["vertical"] or "")
    except (KeyError, TypeError):
        return str(row[0] or "")
