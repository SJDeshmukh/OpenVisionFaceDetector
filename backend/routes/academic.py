"""Authenticated academic lifecycle configuration and promotion APIs."""

from flask import Blueprint, g, jsonify, request

from db_factory import get_db_connection
from services.academic_lifecycle_service import (
    AcademicLifecycleError,
    create_academic_program,
    create_academic_session,
    enroll_student,
    execute_promotions,
    list_academic_config,
    list_enrollments,
    promotion_preview,
    update_academic_program,
    update_academic_session,
)
from services.auth_service import require_auth
from utils import log_audit, require_feature


academic_bp = Blueprint("academic_bp", __name__)
MANAGER_ROLES = {"super_admin", "vendor_admin", "admin", "owner"}


def _manager_error():
    if getattr(g, "user_role", None) not in MANAGER_ROLES:
        return jsonify({"error": "Academic configuration permission required", "code": "FORBIDDEN"}), 403
    if not getattr(g, "vendor_id", None):
        return jsonify({"error": "Vendor context is required", "code": "MISSING_VENDOR"}), 400
    return None


def _error(exc):
    if isinstance(exc, AcademicLifecycleError):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status
    raise exc


@academic_bp.route("/academic/config", methods=["GET"])
@require_auth()
@require_feature("academic_management", "classes")
def academic_config():
    role_error = _manager_error()
    if role_error:
        return role_error
    conn = get_db_connection()
    try:
        return jsonify({"success": True, **list_academic_config(conn, g.vendor_id)})
    finally:
        conn.close()

@academic_bp.route("/academic/sessions", methods=["POST"])
@require_auth()
@require_feature("academic_management", "classes")
def academic_session_create():
    role_error = _manager_error()
    if role_error:
        return role_error
    conn = get_db_connection()
    try:
        session_id = create_academic_session(
            conn, g.vendor_id, request.get_json(silent=True) or {}, g.username,
        )
        log_audit("academic_session_created", {"session_id": session_id}, target_vendor_id=g.vendor_id)
        return jsonify({"success": True, "id": session_id}), 201
    except Exception as exc:
        conn.rollback()
        return _error(exc)
    finally:
        conn.close()


@academic_bp.route("/academic/sessions/<int:session_id>", methods=["PATCH"])
@require_auth()
@require_feature("academic_management", "classes")
def academic_session_update(session_id):
    role_error = _manager_error()
    if role_error:
        return role_error
    conn = get_db_connection()
    try:
        update_academic_session(conn, g.vendor_id, session_id, request.get_json(silent=True) or {})
        log_audit("academic_session_updated", {"session_id": session_id}, target_vendor_id=g.vendor_id)
        return jsonify({"success": True})
    except Exception as exc:
        conn.rollback()
        return _error(exc)
    finally:
        conn.close()


@academic_bp.route("/academic/programs", methods=["POST"])
@require_auth()
@require_feature("academic_management", "classes")
def academic_program_create():
    role_error = _manager_error()
    if role_error:
        return role_error
    conn = get_db_connection()
    try:
        program_id = create_academic_program(
            conn, g.vendor_id, request.get_json(silent=True) or {}, g.username,
        )
        log_audit("academic_program_created", {"program_id": program_id}, target_vendor_id=g.vendor_id)
        return jsonify({"success": True, "id": program_id}), 201
    except Exception as exc:
        conn.rollback()
        return _error(exc)
    finally:
        conn.close()


@academic_bp.route("/academic/programs/<int:program_id>", methods=["PATCH"])
@require_auth()
@require_feature("academic_management", "classes")
def academic_program_update(program_id):
    role_error = _manager_error()
    if role_error:
        return role_error
    conn = get_db_connection()
    try:
        update_academic_program(conn, g.vendor_id, program_id, request.get_json(silent=True) or {})
        log_audit("academic_program_updated", {"program_id": program_id}, target_vendor_id=g.vendor_id)
        return jsonify({"success": True})
    except Exception as exc:
        conn.rollback()
        return _error(exc)
    finally:
        conn.close()


@academic_bp.route("/academic/enrollments", methods=["GET", "POST"])
@require_auth()
@require_feature("academic_management", "classes")
def academic_enrollments():
    role_error = _manager_error()
    if role_error:
        return role_error
    conn = get_db_connection()
    try:
        if request.method == "GET":
            person_id = request.args.get("person_id", type=int)
            session_id = request.args.get("session_id", type=int)
            active_only = request.args.get("active_only") in {"1", "true", "yes"}
            return jsonify({
                "success": True,
                "enrollments": list_enrollments(conn, g.vendor_id, person_id, session_id, active_only),
            })
        data = request.get_json(silent=True) or {}
        person_id = data.get("person_id")
        if person_id is None:
            raise AcademicLifecycleError("person_id is required")
        enrollment, result = enroll_student(
            conn, g.vendor_id, int(person_id), data, g.username, source="MANUAL",
        )
        log_audit(
            "student_enrollment_saved",
            {"person_id": int(person_id), "enrollment_id": enrollment["id"], "result": result},
            target_vendor_id=g.vendor_id,
        )
        return jsonify({"success": True, "result": result, "enrollment": enrollment}), 201 if result == "created" else 200
    except Exception as exc:
        conn.rollback()
        return _error(exc)
    finally:
        conn.close()


@academic_bp.route("/academic/promotions/preview", methods=["POST"])
@require_auth()
@require_feature("academic_management", "classes")
def promotions_preview():
    role_error = _manager_error()
    if role_error:
        return role_error
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    try:
        source = int(data.get("source_session_id"))
        target = int(data.get("target_session_id"))
        return jsonify({
            "success": True,
            "students": promotion_preview(conn, g.vendor_id, source, target),
        })
    except (TypeError, ValueError):
        return jsonify({"error": "source_session_id and target_session_id are required", "code": "VALIDATION_ERROR"}), 400
    except Exception as exc:
        return _error(exc)
    finally:
        conn.close()


@academic_bp.route("/academic/promotions/execute", methods=["POST"])
@require_auth()
@require_feature("academic_management", "classes")
def promotions_execute():
    role_error = _manager_error()
    if role_error:
        return role_error
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    try:
        source = int(data.get("source_session_id"))
        target = int(data.get("target_session_id"))
        decisions = data.get("decisions") or []
        if not isinstance(decisions, list):
            raise AcademicLifecycleError("decisions must be a list")
        results = execute_promotions(conn, g.vendor_id, source, target, decisions, g.username)
        log_audit(
            "academic_promotions_executed",
            {"source_session_id": source, "target_session_id": target, "count": len(results)},
            target_vendor_id=g.vendor_id,
        )
        return jsonify({"success": True, "results": results})
    except (TypeError, ValueError) as exc:
        if isinstance(exc, AcademicLifecycleError):
            return _error(exc)
        return jsonify({"error": "source_session_id and target_session_id are required", "code": "VALIDATION_ERROR"}), 400
    except Exception as exc:
        conn.rollback()
        return _error(exc)
    finally:
        conn.close()
