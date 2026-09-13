import logging
from flask import Blueprint, jsonify, request, g
from utils import get_db_connection, vendor_has_feature
from services.auth_service import authenticate_vendor_access
from services.evolution_whatsapp_service import (
    get_or_create_settings,
    update_settings,
    fetch_qr_code,
    sync_connection_state,
    disconnect_instance,
    send_whatsapp_text,
    clean_phone_number
)

logger = logging.getLogger("whatsapp_routes")

whatsapp_bp = Blueprint("whatsapp_bp", __name__)


def _authenticate_whatsapp_access():
    """Validates user access via standard authenticate_vendor_access() and enforces whatsapp_alerts feature."""
    vendor_id, err = authenticate_vendor_access()
    if err:
        return None, None, err
    role = getattr(g, "user_role", None)

    # Enforce feature check unless super_admin
    if role != "super_admin" and not vendor_has_feature(vendor_id, "whatsapp_alerts"):
        return None, None, (jsonify({
            "error": "WhatsApp Alerts feature is not enabled for your company. Please contact support/administrator to activate it.",
            "code": "FEATURE_NOT_ENABLED"
        }), 403)

    return vendor_id, role, None


@whatsapp_bp.route("/api/whatsapp/settings", methods=["GET"])
def get_whatsapp_settings():
    vendor_id, role, err = _authenticate_whatsapp_access()
    if err:
        return err

    if role not in ("super_admin", "vendor_admin", "admin", "owner"):
        return jsonify({"error": "Access denied"}), 403

    settings = get_or_create_settings(vendor_id)
    return jsonify({"success": True, "settings": settings})


@whatsapp_bp.route("/api/whatsapp/settings", methods=["POST"])
def update_whatsapp_settings():
    vendor_id, role, err = _authenticate_whatsapp_access()
    if err:
        return err

    if role not in ("super_admin", "vendor_admin", "admin", "owner"):
        return jsonify({"error": "Access denied"}), 403

    data = request.json or {}
    success = update_settings(vendor_id, data)
    settings = get_or_create_settings(vendor_id)
    return jsonify({"success": success, "settings": settings})


@whatsapp_bp.route("/api/whatsapp/qr", methods=["GET"])
def get_whatsapp_qr():
    vendor_id, role, err = _authenticate_whatsapp_access()
    if err:
        return err

    if role not in ("super_admin", "vendor_admin", "admin", "owner"):
        return jsonify({"error": "Access denied"}), 403

    result = fetch_qr_code(vendor_id)
    return jsonify(result)


@whatsapp_bp.route("/api/whatsapp/sync", methods=["POST"])
def sync_whatsapp_status():
    vendor_id, role, err = _authenticate_whatsapp_access()
    if err:
        return err

    if role not in ("super_admin", "vendor_admin", "admin", "owner"):
        return jsonify({"error": "Access denied"}), 403

    result = sync_connection_state(vendor_id)
    return jsonify(result)


@whatsapp_bp.route("/api/whatsapp/disconnect", methods=["POST"])
def disconnect_whatsapp():
    vendor_id, role, err = _authenticate_whatsapp_access()
    if err:
        return err

    if role not in ("super_admin", "vendor_admin", "admin", "owner"):
        return jsonify({"error": "Access denied"}), 403

    result = disconnect_instance(vendor_id)
    settings = get_or_create_settings(vendor_id)
    return jsonify({"success": True, "settings": settings})


@whatsapp_bp.route("/api/whatsapp/send-test", methods=["POST"])
def send_test_message():
    vendor_id, role, err = _authenticate_whatsapp_access()
    if err:
        return err

    if role not in ("super_admin", "vendor_admin", "admin", "owner"):
        return jsonify({"error": "Access denied"}), 403

    data = request.json or {}
    settings = get_or_create_settings(vendor_id)
    
    target_phone = data.get("phone") or (settings.get("phone_number") if settings else None)
    if not target_phone:
        return jsonify({"success": False, "error": "No phone number provided or registered"}), 400

    msg = (
        "🧪 *TapInX WhatsApp Gateway — Test Message*\n\n"
        "Congratulations! Your WhatsApp instance is successfully connected and verified.\n"
        "Automated operational alerts (attendance punches, leave signoffs, advance approvals) will be delivered seamlessly.\n\n"
        "_Sent from TapInX WhatsApp Gateway._"
    )
    result = send_whatsapp_text(vendor_id, target_phone, msg)
    return jsonify({"success": True, "result": result})


@whatsapp_bp.route("/api/admin/whatsapp/overview", methods=["GET"])
def get_superadmin_whatsapp_overview():
    """SuperAdmin overview of all companies and their WhatsApp connection status."""
    vendor_id, err = authenticate_vendor_access()
    if err:
        return err
    if getattr(g, "user_role", None) != "super_admin":
        return jsonify({"error": "Super Admin access required"}), 403

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT v.id AS vendor_id, v.company_name, v.contact_person, v.phone AS company_phone,
                   ws.status AS whatsapp_status, ws.phone_number AS registered_whatsapp_phone,
                   ws.auto_punch_alerts, ws.auto_leave_alerts, ws.auto_advance_alerts, ws.auto_late_alerts,
                   ws.last_connected_at
            FROM vendors v
            LEFT JOIN vendor_whatsapp_settings ws ON ws.vendor_id = v.id
            ORDER BY v.id DESC
        """)
        rows = c.fetchall()
        vendors = []
        for r in rows:
            if hasattr(r, 'keys'):
                vendors.append(dict(r))
            else:
                vendors.append({
                    "vendor_id": r[0],
                    "company_name": r[1],
                    "contact_person": r[2],
                    "company_phone": r[3],
                    "whatsapp_status": r[4] or "disconnected",
                    "registered_whatsapp_phone": r[5],
                    "auto_punch_alerts": bool(r[6]) if r[6] is not None else False,
                    "auto_leave_alerts": bool(r[7]) if r[7] is not None else False,
                    "auto_advance_alerts": bool(r[8]) if r[8] is not None else False,
                    "auto_late_alerts": bool(r[9]) if r[9] is not None else False,
                    "last_connected_at": r[10]
                })
        return jsonify({"success": True, "vendors": vendors})
    except Exception as e:
        logger.error(f"Error fetching superadmin whatsapp overview: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
