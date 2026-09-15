"""Authenticated v2 APIs for normalized workforce and shift configuration."""

from datetime import date, datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, g, jsonify, request

from db_factory import get_db_connection, set_row_factory
from services.auth_service import require_auth
from services.shift_resolution_service import resolve_shift


workforce_config_bp = Blueprint("workforce_config_bp", __name__)
MANAGER_ROLES = {"super_admin", "vendor_admin", "admin", "owner", "hr_admin"}
UNIT_TYPES = {"COMPANY", "OFFICE", "PLANT", "DEPARTMENT", "LINE", "WORK_CENTER", "TEAM"}
LOCATION_TYPES = {"OFFICE", "PLANT", "WAREHOUSE", "REMOTE"}
SCOPE_TYPES = {"EMPLOYEE", "GROUP", "ORG_UNIT", "LOCATION", "VENDOR"}
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _forbidden_if_not_manager():
    if getattr(g, "user_role", None) not in MANAGER_ROLES:
        return jsonify({"error": "Workforce configuration permission required", "code": "FORBIDDEN"}), 403
    return None


def _row_dict(row):
    if hasattr(row, "keys"):
        return dict(row)
    return row


def _parse_date(value, field, *, required=True):
    if value in (None, ""):
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc


def _validate_timezone(value):
    timezone = str(value or "Asia/Kolkata")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return timezone


def _validate_time(value, field):
    normalized = str(value or "")
    if not TIME_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} must use 24-hour HH:MM")
    return normalized


def _json_error(exc, status=400):
    return jsonify({"error": str(exc), "code": "VALIDATION_ERROR"}), status


@workforce_config_bp.route("/v2/locations", methods=["GET", "POST"])
@require_auth()
def locations():
    role_error = _forbidden_if_not_manager()
    if role_error:
        return role_error
    vendor_id = g.vendor_id
    conn = get_db_connection()
    set_row_factory(conn)
    cursor = conn.cursor()
    try:
        if request.method == "GET":
            cursor.execute("SELECT * FROM locations WHERE vendor_id = ? ORDER BY name", (vendor_id,))
            return jsonify({"locations": [_row_dict(row) for row in cursor.fetchall()]})
        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or "").strip().upper()
        name = str(data.get("name") or "").strip()
        location_type = str(data.get("location_type") or "OFFICE").upper()
        if not code or not name:
            raise ValueError("code and name are required")
        if location_type not in LOCATION_TYPES:
            raise ValueError(f"location_type must be one of {sorted(LOCATION_TYPES)}")
        timezone = _validate_timezone(data.get("timezone"))
        cursor.execute(
            """INSERT INTO locations
               (vendor_id, code, name, location_type, timezone, address,
                geofence_lat, geofence_lng, geofence_radius_m)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vendor_id, code, name, location_type, timezone, data.get("address"),
             data.get("geofence_lat"), data.get("geofence_lng"), data.get("geofence_radius_m")),
        )
        location_id = cursor.lastrowid
        conn.commit()
        return jsonify({"id": location_id}), 201
    except ValueError as exc:
        conn.rollback()
        return _json_error(exc)
    except Exception as exc:
        conn.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return _json_error(ValueError("location code already exists"), 409)
        raise
    finally:
        conn.close()


@workforce_config_bp.route("/v2/organization-units", methods=["GET", "POST"])
@require_auth()
def organization_units():
    role_error = _forbidden_if_not_manager()
    if role_error:
        return role_error
    vendor_id = g.vendor_id
    conn = get_db_connection()
    set_row_factory(conn)
    cursor = conn.cursor()
    try:
        if request.method == "GET":
            cursor.execute("SELECT * FROM organization_units WHERE vendor_id = ? ORDER BY name", (vendor_id,))
            return jsonify({"organization_units": [_row_dict(row) for row in cursor.fetchall()]})
        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or "").strip().upper()
        name = str(data.get("name") or "").strip()
        unit_type = str(data.get("unit_type") or "").upper()
        if not code or not name or unit_type not in UNIT_TYPES:
            raise ValueError(f"code, name, and unit_type in {sorted(UNIT_TYPES)} are required")
        parent_id, location_id = data.get("parent_id"), data.get("location_id")
        if parent_id is not None:
            cursor.execute("SELECT id FROM organization_units WHERE id = ? AND vendor_id = ?", (parent_id, vendor_id))
            if not cursor.fetchone():
                raise ValueError("parent organization unit not found")
        if location_id is not None:
            cursor.execute("SELECT id FROM locations WHERE id = ? AND vendor_id = ?", (location_id, vendor_id))
            if not cursor.fetchone():
                raise ValueError("location not found")
        cursor.execute(
            """INSERT INTO organization_units
               (vendor_id, parent_id, location_id, code, name, unit_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (vendor_id, parent_id, location_id, code, name, unit_type),
        )
        unit_id = cursor.lastrowid
        conn.commit()
        return jsonify({"id": unit_id}), 201
    except ValueError as exc:
        conn.rollback()
        return _json_error(exc)
    finally:
        conn.close()


@workforce_config_bp.route("/v2/shifts", methods=["GET", "POST"])
@require_auth()
def shifts():
    role_error = _forbidden_if_not_manager()
    if role_error:
        return role_error
    vendor_id = g.vendor_id
    conn = get_db_connection()
    set_row_factory(conn)
    cursor = conn.cursor()
    try:
        if request.method == "GET":
            cursor.execute(
                """SELECT s.id, s.code, s.name, s.is_active,
                          sv.id AS version_id, sv.version_number, sv.effective_from,
                          sv.effective_to, sv.start_time, sv.end_time, sv.timezone,
                          sv.grace_minutes, sv.is_cross_midnight
                   FROM shifts s LEFT JOIN shift_versions sv ON sv.id = (
                       SELECT sv2.id FROM shift_versions sv2
                       WHERE sv2.shift_id = s.id AND sv2.vendor_id = s.vendor_id
                       ORDER BY sv2.version_number DESC LIMIT 1)
                   WHERE s.vendor_id = ? ORDER BY s.name""",
                (vendor_id,),
            )
            return jsonify({"shifts": [_row_dict(row) for row in cursor.fetchall()]})
        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or "").strip().upper()
        name = str(data.get("name") or "").strip()
        start_time = _validate_time(data.get("start_time"), "start_time")
        end_time = _validate_time(data.get("end_time"), "end_time")
        effective_from = _parse_date(data.get("effective_from"), "effective_from")
        effective_to = _parse_date(data.get("effective_to"), "effective_to", required=False)
        if not code or not name:
            raise ValueError("code and name are required")
        if effective_to and effective_to < effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        timezone = _validate_timezone(data.get("timezone"))
        cursor.execute("INSERT INTO shifts (vendor_id, code, name) VALUES (?, ?, ?)", (vendor_id, code, name))
        shift_id = cursor.lastrowid
        cross_midnight = int(end_time <= start_time)
        cursor.execute(
            """INSERT INTO shift_versions
               (vendor_id, shift_id, version_number, effective_from, effective_to,
                start_time, end_time, timezone, operational_day_offset,
                grace_minutes, is_cross_midnight)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vendor_id, shift_id, effective_from.isoformat(),
             effective_to.isoformat() if effective_to else None, start_time, end_time,
             timezone, int(data.get("operational_day_offset") or 0),
             max(0, int(data.get("grace_minutes") or 0)), cross_midnight),
        )
        version_id = cursor.lastrowid
        for sequence, segment in enumerate(data.get("segments") or []):
            segment_type = str(segment.get("segment_type") or "BREAK").upper()
            if segment_type not in {"WORK", "BREAK"}:
                raise ValueError("segment_type must be WORK or BREAK")
            cursor.execute(
                """INSERT INTO shift_segments
                   (vendor_id, shift_version_id, segment_type, start_time, end_time, is_paid, sequence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (vendor_id, version_id, segment_type,
                 _validate_time(segment.get("start_time"), "segment.start_time"),
                 _validate_time(segment.get("end_time"), "segment.end_time"),
                 int(bool(segment.get("is_paid", segment_type == "WORK"))), sequence),
            )
        conn.commit()
        return jsonify({"id": shift_id, "version_id": version_id}), 201
    except ValueError as exc:
        conn.rollback()
        return _json_error(exc)
    finally:
        conn.close()


@workforce_config_bp.route("/v2/shift-assignments", methods=["POST"])
@require_auth()
def create_shift_assignment():
    role_error = _forbidden_if_not_manager()
    if role_error:
        return role_error
    vendor_id = g.vendor_id
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        shift_id = int(data.get("shift_id"))
        scope = str(data.get("scope_type") or "").upper()
        if scope not in SCOPE_TYPES:
            raise ValueError(f"scope_type must be one of {sorted(SCOPE_TYPES)}")
        effective_from = _parse_date(data.get("effective_from"), "effective_from")
        effective_to = _parse_date(data.get("effective_to"), "effective_to", required=False)
        cursor.execute("SELECT id FROM shifts WHERE id = ? AND vendor_id = ?", (shift_id, vendor_id))
        if not cursor.fetchone():
            raise ValueError("shift not found")
        targets = {
            "EMPLOYEE": data.get("person_id"), "ORG_UNIT": data.get("organization_unit_id"),
            "LOCATION": data.get("location_id"), "GROUP": data.get("group_key"), "VENDOR": vendor_id,
        }
        if targets[scope] in (None, ""):
            raise ValueError(f"target is required for {scope} scope")
        target_checks = {
            "EMPLOYEE": ("faces", "person_id"),
            "ORG_UNIT": ("organization_units", "organization_unit_id"),
            "LOCATION": ("locations", "location_id"),
        }
        if scope in target_checks:
            table, field = target_checks[scope]
            cursor.execute(
                f"SELECT id FROM {table} WHERE id = ? AND vendor_id = ?",
                (data.get(field), vendor_id),
            )
            if not cursor.fetchone():
                raise ValueError(f"{field} not found")
        cursor.execute(
            """INSERT INTO shift_assignments
               (vendor_id, shift_id, scope_type, person_id, organization_unit_id,
                location_id, group_key, effective_from, effective_to, priority, assignment_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vendor_id, shift_id, scope, data.get("person_id"),
             data.get("organization_unit_id"), data.get("location_id"), data.get("group_key"),
             effective_from.isoformat(), effective_to.isoformat() if effective_to else None,
             int(data.get("priority") or 0), "MANUAL"),
        )
        assignment_id = cursor.lastrowid
        conn.commit()
        return jsonify({"id": assignment_id}), 201
    except (TypeError, ValueError) as exc:
        conn.rollback()
        return _json_error(exc)
    finally:
        conn.close()


@workforce_config_bp.route("/v2/person-organization-assignments", methods=["POST"])
@require_auth()
def create_person_organization_assignment():
    role_error = _forbidden_if_not_manager()
    if role_error:
        return role_error
    vendor_id = g.vendor_id
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        person_id = int(data.get("person_id"))
        organization_unit_id = int(data.get("organization_unit_id"))
        effective_from = _parse_date(data.get("effective_from"), "effective_from")
        effective_to = _parse_date(data.get("effective_to"), "effective_to", required=False)
        if effective_to and effective_to < effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        cursor.execute("SELECT id FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        if not cursor.fetchone():
            raise ValueError("person_id not found")
        cursor.execute(
            "SELECT id FROM organization_units WHERE id = ? AND vendor_id = ?",
            (organization_unit_id, vendor_id),
        )
        if not cursor.fetchone():
            raise ValueError("organization_unit_id not found")
        cursor.execute(
            """INSERT INTO person_organization_assignments
               (vendor_id, person_id, organization_unit_id, effective_from,
                effective_to, is_primary)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (vendor_id, person_id, organization_unit_id, effective_from.isoformat(),
             effective_to.isoformat() if effective_to else None,
             int(bool(data.get("is_primary", True)))),
        )
        assignment_id = cursor.lastrowid
        conn.commit()
        return jsonify({"id": assignment_id}), 201
    except (TypeError, ValueError) as exc:
        conn.rollback()
        return _json_error(exc)
    finally:
        conn.close()


@workforce_config_bp.route("/v2/shift-resolution", methods=["GET"])
@require_auth()
def shift_resolution_preview():
    role_error = _forbidden_if_not_manager()
    if role_error:
        return role_error
    vendor_id = g.vendor_id
    conn = get_db_connection()
    set_row_factory(conn)
    cursor = conn.cursor()
    try:
        person_id = int(request.args.get("person_id"))
        operational_date = _parse_date(request.args.get("date") or date.today().isoformat(), "date")
        cursor.execute("SELECT id FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        if not cursor.fetchone():
            return jsonify({"error": "person not found"}), 404
        cursor.execute(
            """SELECT poa.organization_unit_id, ou.location_id
               FROM person_organization_assignments poa
               JOIN organization_units ou ON ou.id = poa.organization_unit_id AND ou.vendor_id = poa.vendor_id
               WHERE poa.vendor_id = ? AND poa.person_id = ? AND poa.effective_from <= ?
                 AND (poa.effective_to IS NULL OR poa.effective_to >= ?)""",
            (vendor_id, person_id, operational_date.isoformat(), operational_date.isoformat()),
        )
        memberships = cursor.fetchall() or []
        org_ids = [row[0] for row in memberships]
        location_id = next((row[1] for row in memberships if row[1] is not None), None)
        resolved = resolve_shift(
            cursor, vendor_id, person_id, operational_date,
            organization_unit_ids=org_ids, location_id=location_id,
        )
        if not resolved:
            return jsonify({"resolved": False, "reason": "NO_SHIFT_ASSIGNMENT"})
        return jsonify({"resolved": True, "shift": resolved.__dict__})
    except (TypeError, ValueError) as exc:
        return _json_error(exc)
    finally:
        conn.close()
