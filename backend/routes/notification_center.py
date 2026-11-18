import json

from flask import Blueprint, g, jsonify, request

from db_factory import get_db_connection
from services.auth_service import require_auth
from services.notification_center_service import build_notification_center, mark_notifications_read


notification_center_bp = Blueprint("notification_center_bp", __name__)


def _parse_features(raw):
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    try:
        parsed = json.loads(raw or "[]")
        return {str(item).strip() for item in parsed if str(item).strip()} if isinstance(parsed, list) else set()
    except (TypeError, ValueError):
        return set()


def _resolve_principal(conn):
    vendor_id = getattr(g, "vendor_id", None)
    role = str(getattr(g, "user_role", "") or "").strip().lower()
    username = str(getattr(g, "username", "") or "").strip()
    features = set()

    if vendor_id:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
            row = cursor.fetchone()
            if row:
                raw = row["features"] if hasattr(row, "keys") else row[0]
                features = _parse_features(raw)
        finally:
            cursor.close()

    # A signed staff session is narrower than the underlying admin account and
    # must take precedence when it is present.
    if request.headers.get("X-Leave-Staff-Token"):
        from routes.leave_routes import _authenticated_leave_staff

        staff = _authenticated_leave_staff(vendor_id)
        if not staff:
            return None, (jsonify({"error": "Staff session is invalid or no longer active", "code": "STAFF_SESSION_INVALID"}), 403)
        return {
            "vendor_id": vendor_id,
            "scope_vendor_id": int(vendor_id or 0),
            "principal_key": f"leave_staff:{staff['id']}",
            "role": str(staff.get("role") or "staff").strip().lower(),
            "department": staff.get("department"),
            "navbar_items": staff.get("navbar_items") or [],
            "features": features,
            "person_id": None,
        }, None

    principal = {
        "vendor_id": vendor_id,
        "scope_vendor_id": int(vendor_id or 0),
        "principal_key": f"{role}:{username.lower()}",
        "role": role,
        "department": None,
        "navbar_items": [],
        "features": features,
        "person_id": None,
    }

    cursor = conn.cursor()
    try:
        if role == "parent":
            cursor.execute(
                "SELECT selected_person_id FROM parent_users WHERE vendor_id = ? AND username = ?",
                (vendor_id, username),
            )
            row = cursor.fetchone()
            if row:
                principal["person_id"] = row["selected_person_id"] if hasattr(row, "keys") else row[0]
        elif role != "super_admin":
            cursor.execute(
                "SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ?",
                (vendor_id, username),
            )
            row = cursor.fetchone()
            if row:
                principal["person_id"] = row["person_id"] if hasattr(row, "keys") else row[0]
    finally:
        cursor.close()
    return principal, None


@notification_center_bp.route("/notifications", methods=["GET"])
@require_auth()
def get_notifications():
    conn = get_db_connection()
    try:
        principal, error = _resolve_principal(conn)
        if error:
            return error
        try:
            limit = max(1, min(int(request.args.get("limit", 40)), 100))
        except (TypeError, ValueError):
            limit = 40
        items = build_notification_center(conn, principal, limit)
        return jsonify({
            "status": "success",
            "items": items,
            "unread_count": sum(1 for item in items if not item.get("read")),
        })
    finally:
        conn.close()


@notification_center_bp.route("/notifications/read", methods=["POST"])
@require_auth()
def read_notifications():
    payload = request.get_json(silent=True) or {}
    keys = payload.get("keys")
    if not isinstance(keys, list):
        return jsonify({"error": "keys must be an array", "code": "INVALID_REQUEST"}), 400

    conn = get_db_connection()
    try:
        principal, error = _resolve_principal(conn)
        if error:
            return error
        marked = mark_notifications_read(conn, principal, keys)
        return jsonify({"status": "success", "marked": marked})
    finally:
        conn.close()
