"""Authenticated salary history, confirmation, and finalized payroll records."""

import json
import logging
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, g, jsonify, request

from middleware.handlers import rate_limit
from services.attendance_service import calculate_daily_hours
from services.attendance_shift_service import (
    choose_shift_policy,
    parse_shift_list,
    scheduled_payable_hours,
)
from services.auth_service import require_auth
from services.salary_version_service import (
    MANAGER_ROLES,
    ReauthenticationError,
    SalaryValidationError,
    calculate_versioned_shift_wage,
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


def _period_wage_totals(cursor, vendor_id, employee, versions, start_day, end_day):
    """Price every payable attendance day in the period with its effective salary version."""
    cursor.execute(
        "SELECT live_timetable, working_hours, shifts FROM companies WHERE vendor_id = ?",
        (vendor_id,),
    )
    company = dict(cursor.fetchone() or {})
    try:
        timetable = json.loads(company.get("live_timetable") or "[]")
    except (TypeError, ValueError):
        timetable = []
    try:
        working_hours = float(company.get("working_hours") or 8.0)
    except (TypeError, ValueError):
        working_hours = 8.0
    shift_policy = choose_shift_policy(
        parse_shift_list(company.get("shifts")), employee.get("shift")
    )
    scheduled_hours = scheduled_payable_hours(shift_policy, working_hours)

    cursor.execute(
        "SELECT value FROM system_settings WHERE key = ?",
        (f"missing_checkout_deduction_percent_vendor_{vendor_id}",),
    )
    setting = cursor.fetchone()
    try:
        missing_deduction_pct = float(dict(setting).get("value")) if setting else 50.0
    except (TypeError, ValueError):
        missing_deduction_pct = 50.0

    cursor.execute(
        """SELECT person_id, status, activity, timestamp, is_late
             FROM attendance
            WHERE vendor_id = ? AND person_id = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC""",
        (
            vendor_id,
            employee["id"],
            start_day.strftime("%Y-%m-%d 00:00:00"),
            (end_day + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"),
        ),
    )
    records = [dict(row) for row in cursor.fetchall() or []]

    stats = calculate_daily_hours(
        records,
        timetable,
        missing_checkout_deduction_percent=missing_deduction_pct,
        working_hours=scheduled_hours,
        shift_policy=shift_policy,
    )
    per_day_seconds = defaultdict(float)
    for session in stats.get("sessions", []):
        if not session.get("is_payable", False):
            continue
        try:
            attendance_day = date.fromisoformat(session["attendance_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if start_day <= attendance_day <= end_day:
            per_day_seconds[attendance_day] += float(session.get("duration_seconds") or 0)

    wage_result = calculate_versioned_shift_wage(
        versions, employee, per_day_seconds, scheduled_hours
    )
    totals = {}
    for group in wage_result.get("groups", []):
        version_id = group.get("salary_version_id")
        if version_id is None:
            continue
        wage = group.get("wage") or {}
        totals[int(version_id)] = {
            "days": len(group.get("dates") or []),
            "hours": round(
                float(wage.get("regular_hours") or 0) + float(wage.get("overtime_hours") or 0),
                2,
            ),
            "amount": round(float(wage.get("gross_wage") or 0), 2),
        }
    return totals


@compensation_bp.route("/persons/<int:person_id>/salary-versions", methods=["GET"])
@require_auth(roles=_MANAGER_ROLES)
@require_feature("payroll")
def get_employee_salary_versions(person_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, name, display_id, daily_wage, shift FROM faces WHERE id = ? AND vendor_id = ?",
            (person_id, g.vendor_id),
        )
        employee = cursor.fetchone()
        if not employee:
            return jsonify({"error": "Employee not found"}), 404
        employee = dict(employee)
        versions = load_salary_versions(cursor, g.vendor_id, [person_id]).get(person_id, [])

        period = {"start": None, "end": None}
        period_totals = {}
        start_raw = str(request.args.get("start") or "").strip()
        end_raw = str(request.args.get("end") or "").strip()
        if start_raw and end_raw:
            try:
                start_day = date.fromisoformat(start_raw)
                end_day = date.fromisoformat(end_raw)
            except ValueError:
                return jsonify({"error": "Invalid date format"}), 400
            if start_day > end_day:
                return jsonify({"error": "start must be on or before end"}), 400
            period_totals = _period_wage_totals(
                cursor, g.vendor_id, employee, versions, start_day, end_day
            )
            period = {"start": start_raw, "end": end_raw}

        payload = []
        for version in reversed(versions):
            item = serialize_salary_version(version)
            totals = period_totals.get(int(version["id"])) or {}
            item["period_days"] = int(totals.get("days", 0))
            item["period_hours"] = float(totals.get("hours", 0.0))
            item["period_amount"] = float(totals.get("amount", 0.0))
            payload.append(item)
        return jsonify({
            "person_id": person_id,
            "name": employee["name"],
            "display_id": employee["display_id"],
            "period": period,
            "versions": payload,
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
