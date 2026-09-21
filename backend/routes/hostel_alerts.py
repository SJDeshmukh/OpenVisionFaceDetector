"""Vendor configuration and observability for hostel attendance alerts."""

import logging

from flask import Blueprint, g, jsonify, request

from services.auth_service import authenticate_vendor_access
from services.hostel_alert_service import get_settings, recent_deliveries, save_settings
from utils import get_db_connection, log_audit, vendor_has_feature


logger = logging.getLogger(__name__)
hostel_alerts_bp = Blueprint("hostel_alerts_bp", __name__)
FEATURE_NAME = "hostel_attendance_alerts"
MANAGER_ROLES = {"super_admin", "vendor_admin", "admin", "owner"}


def _authorize():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return None, error
    if getattr(g, "user_role", None) not in MANAGER_ROLES:
        return None, (jsonify({"error": "Hostel administrator access required"}), 403)
    if not vendor_id:
        return None, (jsonify({"error": "Select a company first"}), 400)

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT vertical FROM vendors WHERE id = ?", (vendor_id,))
        row = c.fetchone()
        vertical = row[0] if row else None
    finally:
        conn.close()
    if str(vertical or "").lower() != "hostel":
        return None, (jsonify({"error": "Hostel Alerts is available only to hostel companies"}), 403)
    if getattr(g, "user_role", None) != "super_admin" and not vendor_has_feature(vendor_id, FEATURE_NAME):
        return None, (jsonify({
            "error": "Hostel Attendance Alerts is not enabled for this company",
            "code": "FEATURE_NOT_ENABLED",
        }), 403)
    return vendor_id, None


@hostel_alerts_bp.route("/hostel-alerts/settings", methods=["GET"])
def hostel_alert_settings_get():
    vendor_id, error = _authorize()
    if error:
        return error
    return jsonify({"success": True, "settings": get_settings(vendor_id)})


@hostel_alerts_bp.route("/hostel-alerts/settings", methods=["PUT"])
def hostel_alert_settings_put():
    vendor_id, error = _authorize()
    if error:
        return error
    try:
        settings = save_settings(vendor_id, request.get_json(silent=True) or {})
        log_audit(
            "hostel_alert_settings_updated",
            {key: settings.get(key) for key in (
                "enabled", "owner_phone", "cutoff_time", "escalation_minutes",
                "timezone", "owner_summary_enabled",
            )},
            target_vendor_id=vendor_id,
        )
        return jsonify({"success": True, "settings": settings})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Unable to update hostel alert settings for vendor %s", vendor_id)
        return jsonify({"error": str(exc)}), 500


@hostel_alerts_bp.route("/hostel-alerts/deliveries", methods=["GET"])
def hostel_alert_deliveries_get():
    vendor_id, error = _authorize()
    if error:
        return error
    return jsonify({
        "success": True,
        "deliveries": recent_deliveries(vendor_id, request.args.get("limit", 100)),
    })
