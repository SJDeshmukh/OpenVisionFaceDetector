import logging
from flask import Blueprint, jsonify, request, g
from utils import _require_role, get_db_connection
from services.auth_service import extract_token, verify_token
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
    """Validates user token and extracts vendor_id and role."""
    auth_header = request.headers.get("Authorization")
    token = extract_token(auth_header)
    user_data = verify_token(token)
    if not user_data:
        return None, None, (jsonify({"error": "Unauthorized"}), 401)
    
    role = user_data.get("role")
    vendor_id = user_data.get("vendor_id")

    # If super_admin, allow target vendor_id from query parameter
    if role == "super_admin":
        target = request.args.get("vendor_id") or (request.json or {}).get("vendor_id")
        if target:
            vendor_id = int(target)

    if not vendor_id and role != "super_admin":
        return None, None, (jsonify({"error": "Vendor context required"}), 400)

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
        "_Sent from TapInX Evolution API Gateway._"
    )
    result = send_whatsapp_text(vendor_id, target_phone, msg)
    return jsonify({"success": True, "result": result})


@whatsapp_bp.route("/api/admin/whatsapp/overview", methods=["GET"])
def get_superadmin_whatsapp_overview():
    """SuperAdmin overview of all companies and their WhatsApp connection status."""
    auth_header = request.headers.get("Authorization")
    token = extract_token(auth_header)
    user_data = verify_token(token)
    if not user_data or user_data.get("role") != "super_admin":
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
