"""API for visual hostel buildings, beds, allocations, and scoped exports."""

import csv
import io
import json
import logging

from flask import Blueprint, Response, g, jsonify, request

from services.auth_service import authenticate_vendor_access, verify_token
from services.hostel_allocation_service import (
    HostelAllocationError, access_for, allocate, create_building, create_floor,
    create_rooms, delete_building, delete_floor, delete_room, duplicate_floor,
    ensure_tables, get_state, remove_allocation, reorder_rooms, require_permission,
    undo_allocation_change, update_bed, update_building, update_floor, update_room,
)
from utils import get_db_connection, log_audit, vendor_has_feature


logger = logging.getLogger(__name__)
hostel_management_bp = Blueprint("hostel_management_bp", __name__)
FEATURE_NAME = "hostel_allocation"


def _context(permission=None):
    vendor_id, error = authenticate_vendor_access()
    if error:
        return None, None, None, error
    if not vendor_id:
        return None, None, None, (jsonify({"error": "Vendor context is required"}), 400)
    if getattr(g, "user_role", None) != "super_admin" and not vendor_has_feature(vendor_id, FEATURE_NAME):
        return None, None, None, (jsonify({"error": "Hostel management is not enabled for this company", "code": "FEATURE_NOT_ENABLED"}), 403)
    conn = get_db_connection()
    try:
        ensure_tables(conn)
        principal = getattr(g, "username", "")
        system_role = getattr(g, "user_role", "")
        staff_token = request.headers.get("X-Leave-Staff-Token")
        if staff_token:
            claims = verify_token(staff_token)
            if not claims or claims.get("role") != "leave_staff" or str(claims.get("vendor_id")) != str(vendor_id):
                conn.close()
                return None, None, None, (jsonify({"error": "Staff session is invalid or expired"}), 401)
            c = conn.cursor()
            c.execute("SELECT id, role FROM leave_staff WHERE id=? AND vendor_id=?", (claims.get("staff_id"), vendor_id))
            staff = c.fetchone()
            staff_id = staff["id"] if staff and hasattr(staff, "keys") else (staff[0] if staff else None)
            staff_role = staff["role"] if staff and hasattr(staff, "keys") else (staff[1] if staff else None)
            if not staff or str(staff_role) != str(claims.get("staff_role")):
                conn.close()
                return None, None, None, (jsonify({"error": "Staff account is no longer active"}), 401)
            principal = f"staff:{staff_id}"
            system_role = str(staff_role or "staff")
        access = access_for(conn, vendor_id, principal, system_role)
        g.hostel_actor = principal
        if permission:
            require_permission(access, permission)
        return vendor_id, access, conn, None
    except Exception:
        conn.close()
        raise


def _error(exc):
    if isinstance(exc, HostelAllocationError):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status
    logger.exception("Hostel management request failed")
    return jsonify({"error": "Unable to complete hostel management request"}), 500


@hostel_management_bp.route("/hostel-management/state", methods=["GET"])
def state_get():
    try:
        vendor_id, access, conn, error = _context()
        if error: return error
        try: return jsonify({"success": True, **get_state(conn, vendor_id, access)})
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/buildings", methods=["POST"])
def building_create():
    try:
        vendor_id, access, conn, error = _context("can_manage_buildings")
        if error: return error
        try:
            building_id = create_building(conn, vendor_id, request.get_json(silent=True) or {})
            log_audit("hostel_building_created", {"building_id": building_id}, target_vendor_id=vendor_id)
            return jsonify({"success": True, "id": building_id}), 201
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/buildings/<int:building_id>", methods=["PUT", "DELETE"])
def building_mutate(building_id):
    try:
        vendor_id, access, conn, error = _context("can_manage_buildings")
        if error: return error
        try:
            if request.method == "DELETE": delete_building(conn, vendor_id, building_id, access)
            else: update_building(conn, vendor_id, building_id, request.get_json(silent=True) or {}, access)
            log_audit("hostel_building_deleted" if request.method == "DELETE" else "hostel_building_updated", {"building_id": building_id}, target_vendor_id=vendor_id)
            return jsonify({"success": True})
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/buildings/<int:building_id>/floors", methods=["POST"])
def floor_create(building_id):
    try:
        vendor_id, access, conn, error = _context("can_edit_layout")
        if error: return error
        try:
            require_permission(access, "can_edit_layout", building_id)
            floor_id = create_floor(conn, vendor_id, building_id, request.get_json(silent=True) or {})
            log_audit("hostel_floor_created", {"building_id": building_id, "floor_id": floor_id}, target_vendor_id=vendor_id)
            return jsonify({"success": True, "id": floor_id}), 201
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/floors/<int:floor_id>/rooms", methods=["POST"])
def rooms_create(floor_id):
    try:
        vendor_id, access, conn, error = _context("can_edit_layout")
        if error: return error
        try:
            ids = create_rooms(conn, vendor_id, floor_id, request.get_json(silent=True) or {}, access)
            log_audit("hostel_rooms_created", {"floor_id": floor_id, "room_ids": ids}, target_vendor_id=vendor_id)
            return jsonify({"success": True, "ids": ids}), 201
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/floors/<int:floor_id>/duplicate", methods=["POST"])
def floor_duplicate(floor_id):
    try:
        vendor_id, access, conn, error = _context("can_edit_layout")
        if error: return error
        try:
            payload = request.get_json(silent=True) or {}
            floor_id_new = duplicate_floor(conn, vendor_id, floor_id, str(payload.get("name") or "").strip(), access)
            log_audit("hostel_floor_duplicated", {"source_floor_id": floor_id, "floor_id": floor_id_new}, target_vendor_id=vendor_id)
            return jsonify({"success": True, "id": floor_id_new}), 201
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/floors/<int:floor_id>", methods=["PUT", "DELETE"])
def floor_mutate(floor_id):
    try:
        vendor_id, access, conn, error = _context("can_edit_layout")
        if error: return error
        try:
            if request.method == "DELETE": delete_floor(conn, vendor_id, floor_id, access)
            else: update_floor(conn, vendor_id, floor_id, request.get_json(silent=True) or {}, access)
            log_audit("hostel_floor_deleted" if request.method == "DELETE" else "hostel_floor_updated", {"floor_id": floor_id}, target_vendor_id=vendor_id)
            return jsonify({"success": True})
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/floors/<int:floor_id>/room-order", methods=["PUT"])
def room_order_update(floor_id):
    try:
        vendor_id, access, conn, error = _context("can_edit_layout")
        if error: return error
        try:
            reorder_rooms(conn, vendor_id, floor_id, (request.get_json(silent=True) or {}).get("room_ids") or [], access)
            return jsonify({"success": True})
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/rooms/<int:room_id>", methods=["PUT", "DELETE"])
def room_mutate(room_id):
    try:
        vendor_id, access, conn, error = _context("can_edit_layout")
        if error: return error
        try:
            if request.method == "DELETE": delete_room(conn, vendor_id, room_id, access)
            else: update_room(conn, vendor_id, room_id, request.get_json(silent=True) or {}, access)
            log_audit("hostel_room_deleted" if request.method == "DELETE" else "hostel_room_updated", {"room_id": room_id}, target_vendor_id=vendor_id)
            return jsonify({"success": True})
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/beds/<int:bed_id>", methods=["PUT"])
def bed_update(bed_id):
    try:
        vendor_id, access, conn, error = _context("can_edit_layout")
        if error: return error
        try:
            update_bed(conn, vendor_id, bed_id, request.get_json(silent=True) or {}, access)
            log_audit("hostel_bed_status_updated", {"bed_id": bed_id, **(request.get_json(silent=True) or {})}, target_vendor_id=vendor_id)
            return jsonify({"success": True})
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/allocations", methods=["POST"])
def allocation_create():
    try:
        vendor_id, access, conn, error = _context("can_allocate")
        if error: return error
        payload = request.get_json(silent=True) or {}
        try:
            result = allocate(conn, vendor_id, int(payload.get("person_id")), int(payload.get("bed_id")), getattr(g, "hostel_actor", getattr(g, "username", "unknown")), access, payload.get("reason"), bool(payload.get("override")), payload.get("override_reason"))
            log_audit("hostel_resident_" + result["action"], {"person_id": payload.get("person_id"), "bed_id": payload.get("bed_id"), "reason": payload.get("reason"), "override": result["eligibility_overridden"]}, target_vendor_id=vendor_id)
            return jsonify({"success": True, **result})
        finally: conn.close()
    except (TypeError, ValueError) as exc:
        if isinstance(exc, HostelAllocationError): return _error(exc)
        return jsonify({"error": "A resident and destination bed are required"}), 400
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/allocations/<int:person_id>", methods=["DELETE"])
def allocation_remove(person_id):
    try:
        vendor_id, access, conn, error = _context("can_allocate")
        if error: return error
        try:
            history_id = remove_allocation(conn, vendor_id, person_id, getattr(g, "hostel_actor", getattr(g, "username", "unknown")), access, (request.get_json(silent=True) or {}).get("reason"))
            log_audit("hostel_resident_removed", {"person_id": person_id}, target_vendor_id=vendor_id)
            return jsonify({"success": True, "history_id": history_id})
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/history/<int:history_id>/undo", methods=["POST"])
def allocation_undo(history_id):
    try:
        vendor_id, access, conn, error = _context("can_allocate")
        if error: return error
        try:
            undo_id = undo_allocation_change(conn, vendor_id, history_id, getattr(g, "hostel_actor", getattr(g, "username", "unknown")), access)
            log_audit("hostel_allocation_undone", {"history_id": history_id, "undo_history_id": undo_id}, target_vendor_id=vendor_id)
            return jsonify({"success": True, "history_id": undo_id})
        finally: conn.close()
    except Exception as exc: return _error(exc)


@hostel_management_bp.route("/hostel-management/permissions", methods=["GET", "PUT"])
def permissions_manage():
    try:
        vendor_id, access, conn, error = _context("can_manage_permissions")
        if error: return error
        c = conn.cursor()
        try:
            if request.method == "GET":
                c.execute("SELECT id, username, building_id, access_role, can_export, can_override_eligibility, can_view_resident_details FROM hostel_staff_permissions WHERE vendor_id=? ORDER BY username, building_id", (vendor_id,))
                columns = ("id", "username", "building_id", "access_role", "can_export", "can_override_eligibility", "can_view_resident_details")
                rows = [dict(zip(columns, row)) if not hasattr(row, "keys") else dict(row) for row in (c.fetchall() or [])]
                c.execute("SELECT id, name, role, department FROM leave_staff WHERE vendor_id=? ORDER BY name", (vendor_id,))
                staff_columns = ("id", "name", "role", "department")
                staff = [dict(zip(staff_columns, row)) if not hasattr(row, "keys") else dict(row) for row in (c.fetchall() or [])]
                return jsonify({"permissions": rows, "staff": staff})
            payload = request.get_json(silent=True) or {}; username = str(payload.get("username") or "").strip().lower(); building_id = payload.get("building_id")
            if not username or not building_id: raise HostelAllocationError("Username and building are required")
            role = str(payload.get("access_role") or "viewer").lower()
            if role not in {"warden", "viewer"}: raise HostelAllocationError("Access role must be warden or viewer")
            c.execute("""INSERT INTO hostel_staff_permissions (vendor_id,username,building_id,access_role,can_export,can_override_eligibility,can_view_resident_details,updated_at)
                         VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                         ON CONFLICT (vendor_id,username,building_id) DO UPDATE SET access_role=EXCLUDED.access_role,can_export=EXCLUDED.can_export,can_override_eligibility=EXCLUDED.can_override_eligibility,can_view_resident_details=EXCLUDED.can_view_resident_details,updated_at=CURRENT_TIMESTAMP""",
                      (vendor_id, username, int(building_id), role, 1 if payload.get("can_export") else 0, 1 if payload.get("can_override_eligibility") else 0, 1 if payload.get("can_view_resident_details") else 0))
            conn.commit(); log_audit("hostel_staff_permission_updated", {"username": username, "building_id": building_id, "role": role}, target_vendor_id=vendor_id)
            return jsonify({"success": True})
        finally: conn.close()
    except Exception as exc: return _error(exc)


def _csv_response(filename, headers, rows):
    stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(headers); writer.writerows(rows)
    return Response(stream.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@hostel_management_bp.route("/hostel-management/export/<kind>.csv", methods=["GET"])
def export_csv(kind):
    try:
        vendor_id, access, conn, error = _context("can_export")
        if error: return error
        try:
            state = get_state(conn, vendor_id, access)
            building_filter = request.args.get("building_id", type=int)
            buildings = [item for item in state["buildings"] if not building_filter or int(item["id"]) == building_filter]
            if building_filter and not buildings:
                raise HostelAllocationError("Building is outside your permitted scope", 403, "BUILDING_SCOPE_DENIED")
            if kind == "current":
                status_filter = str(request.args.get("room_filter") or "all").lower()
                search = str(request.args.get("search") or "").strip().lower()
                rows = []
                for building in buildings:
                    for floor in building["floors"]:
                        for room in floor["rooms"]:
                            haystack = f"{building['name']} {floor['name']} {room['room_number']} " + " ".join(f"{(bed.get('resident') or {}).get('name', '')} {(bed.get('resident') or {}).get('resident_id', '')}" for bed in room["beds"])
                            if search and search not in haystack.lower(): continue
                            summary = room.get("summary") or {}
                            matches_status = (
                                status_filter == "all" or
                                (status_filter == "available" and int(summary.get("available", 0)) > 0) or
                                (status_filter == "partial" and int(summary.get("occupied", 0)) > 0 and int(summary.get("available", 0)) > 0) or
                                (status_filter == "full" and int(summary.get("total", 0)) > 0 and int(summary.get("occupied", 0)) == int(summary.get("total", 0))) or
                                (status_filter == "unavailable" and int(summary.get("unavailable", 0)) > 0)
                            )
                            if not matches_status: continue
                            for bed in room["beds"]:
                                resident = bed.get("resident") or {}
                                rows.append((building["name"], floor["name"], room["room_number"], bed["bed_label"], bed["status"], resident.get("name", ""), resident.get("resident_id", ""), bed.get("allocated_at", ""), bed.get("unavailable_reason", ""), bed.get("unavailable_note", ""), bed.get("reservation_expires_at", "")))
                return _csv_response("hostel-current-occupancy.csv", ("Building", "Floor", "Room", "Bed", "Status", "Resident", "Resident ID", "Allocated At", "Unavailability Reason", "Note", "Reservation Expiry"), rows)
            if kind == "history":
                allowed_beds = {int(bed["id"]) for building in buildings for floor in building["floors"] for room in floor["rooms"] for bed in room["beds"]}
                history = state["history"] if not building_filter else [item for item in state["history"] if any(value is not None and int(value) in allowed_beds for value in (item.get("previous_bed_id"), item.get("new_bed_id")))]
                rows = [(item.get("created_at"), item.get("resident_name"), item.get("person_id"), item.get("action"), item.get("previous_bed_id"), item.get("new_bed_id"), item.get("actor_username"), item.get("reason"), item.get("override_reason")) for item in history]
                return _csv_response("hostel-allocation-history.csv", ("Timestamp", "Resident", "Resident ID", "Action", "Previous Bed", "New Bed", "Actor", "Reason", "Override Reason"), rows)
            raise HostelAllocationError("Export type must be current or history", 404)
        finally: conn.close()
    except Exception as exc: return _error(exc)
