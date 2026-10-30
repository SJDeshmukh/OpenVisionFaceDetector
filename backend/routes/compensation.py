"""Authenticated salary history, confirmation, and finalized payroll records."""

import json
import logging

from flask import Blueprint, g, jsonify, request

from middleware.handlers import rate_limit
from services.auth_service import require_auth
from services.salary_version_service import (
    MANAGER_ROLES,
    ReauthenticationError,
    SalaryValidationError,
    issue_reauth_token,
    load_salary_versions,
    serialize_salary_version,
)
from utils import get_db_connection, require_feature


logger = logging.getLogger(__name__)
compensation_bp = Blueprint("compensation_bp", __name__)
_MANAGER_ROLES = sorted(MANAGER_ROLES)


@compensation_bp.route("/persons/wages/reauth", methods=["POST"])
@require_auth(roles=_MANAGER_ROLES)
@require_feature("payroll")
@rate_limit(
    key_func=lambda: f"payroll-reauth:{g.vendor_id}:{g.username}",
    limit=5,
    window=300,
)
def reauthenticate_payroll_change():
    data = request.get_json(silent=True) or {}
    purpose = str(data.get("purpose") or "salary_change").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        token, expires_at = issue_reauth_token(
            cursor,
            g.vendor_id,
            g.username,
            g.user_role,
            data.get("password"),
            purpose,
        )
        conn.commit()
        return jsonify({
            "success": True,
            "reauth_token": token,
            "expires_at": expires_at.isoformat() + "Z",
        })
    except SalaryValidationError as exc:
        conn.rollback()
        return jsonify({"error": str(exc), "code": "INVALID_REQUEST"}), 400
    except ReauthenticationError as exc:
        conn.rollback()
        return jsonify({"error": str(exc), "code": "REAUTHENTICATION_FAILED"}), 403
    except Exception:
        conn.rollback()
        logger.exception("Payroll reauthentication failed for user %s", g.username)
        return jsonify({"error": "Could not confirm the password"}), 500
    finally:
        conn.close()


@compensation_bp.route("/persons/<int:person_id>/salary-versions", methods=["GET"])
@require_auth(roles=_MANAGER_ROLES)
@require_feature("payroll")
def get_employee_salary_versions(person_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, name, display_id FROM faces WHERE id = ? AND vendor_id = ?",
            (person_id, g.vendor_id),
        )
        employee = cursor.fetchone()
        if not employee:
            return jsonify({"error": "Employee not found"}), 404
        versions = load_salary_versions(cursor, g.vendor_id, [person_id]).get(person_id, [])
        return jsonify({
            "person_id": person_id,
            "name": employee["name"],
            "display_id": employee["display_id"],
            "versions": [serialize_salary_version(version) for version in reversed(versions)],
        })
    except Exception:
        logger.exception("Could not load salary history for employee %s", person_id)
        return jsonify({"error": "Could not load salary history"}), 500
    finally:
        conn.close()


@compensation_bp.route("/reports/payroll/runs", methods=["GET"])
@require_auth(roles=_MANAGER_ROLES)
@require_feature("payroll", "report_payroll")
def list_finalized_payroll_runs():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT id, period_start, period_end, status, finalized_by,
                      finalized_at, created_at
                 FROM payroll_runs WHERE vendor_id = ?
                 ORDER BY finalized_at DESC LIMIT 100""",
            (g.vendor_id,),
        )
        return jsonify({"runs": [dict(row) for row in cursor.fetchall() or []]})
    finally:
        conn.close()


@compensation_bp.route("/reports/payroll/runs/<int:run_id>", methods=["GET"])
@require_auth(roles=_MANAGER_ROLES)
@require_feature("payroll", "report_payroll")
def get_finalized_payroll_run(run_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT * FROM payroll_runs WHERE id = ? AND vendor_id = ?",
            (run_id, g.vendor_id),
        )
        run = cursor.fetchone()
        if not run:
            return jsonify({"error": "Finalized payroll was not found"}), 404
        cursor.execute(
            """SELECT pli.*, f.name, f.display_id
                 FROM payroll_line_items pli
                 LEFT JOIN faces f ON f.id = pli.person_id AND f.vendor_id = pli.vendor_id
                WHERE pli.payroll_run_id = ? AND pli.vendor_id = ?
                ORDER BY f.display_id, f.name""",
            (run_id, g.vendor_id),
        )
        run_data = dict(run)
        for field in ("settings_json",):
            try:
                run_data[field.removesuffix("_json")] = json.loads(run_data.pop(field) or "{}")
            except (TypeError, ValueError):
                run_data[field.removesuffix("_json")] = {}
        lines = []
        for row in cursor.fetchall() or []:
            item = dict(row)
            for field, fallback in (("salary_version_ids", []), ("calculation_json", {})):
                try:
                    item[field.removesuffix("_json")] = json.loads(item.pop(field) or json.dumps(fallback))
                except (TypeError, ValueError):
                    item[field.removesuffix("_json")] = fallback
            calculation = item.get("calculation") or {}
            if not item.get("name"):
                item["name"] = calculation.get("name")
            if item.get("display_id") is None:
                item["display_id"] = calculation.get("display_id")
            lines.append(item)
        return jsonify({"run": run_data, "line_items": lines})
    finally:
        conn.close()
