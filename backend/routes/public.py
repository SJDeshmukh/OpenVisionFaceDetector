from flask import Blueprint, jsonify, current_app, request
import sqlite3
import os
import logging

# Ensure logging is configured
logger = logging.getLogger(__name__)

public_bp = Blueprint('public_bp', __name__)

# Note: BASE_URL and FRONTEND_URL will be imported from app or handled via current_app
# For now, we can use a helper or placeholder until we fully modularize

@public_bp.route('/config', methods=['GET'])
def get_config():
    return jsonify({
        "backend_url": os.environ.get("BASE_URL", "http://localhost:5000"),
        "frontend_url": os.environ.get("FRONTEND_URL", "http://localhost:3000")
    })

@public_bp.route('/vendors', methods=['GET'])
def public_vendors():
    from utils import get_db_connection
    conn = get_db_connection()
    # Handle both SQLite and PostgreSQL Row factory
    is_pg = getattr(conn, "_is_pg", False)
    if not is_pg:
        conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT id, company_name, vertical, status FROM vendors ORDER BY company_name ASC")
        rows = c.fetchall()
    except Exception as e:
        logger.error(f"Error fetching public vendors: {e}")
        rows = []
    finally:
        conn.close()

    vendors = []
    for r in rows or []:
        try:
            rd = dict(r) if not isinstance(r, dict) else r
            if str(rd.get("status") or "active").lower() != "active":
                continue
            vendors.append({
                "id": rd.get("id"),
                "company_name": rd.get("company_name"),
                "vertical": rd.get("vertical")
            })
        except Exception:
            pass
    return jsonify({"vendors": vendors})

@public_bp.route('/business-types', methods=['GET'])
def public_business_types():
    """
    Returns business types filtered to the requesting app brand.
    X-App-Brand: AttendX  →  only attendx types
    X-App-Brand: TapInX   →  only tapinx types
    No header              →  all types (web dashboard / legacy)
    """
    app_brand = (request.headers.get('X-App-Brand') or '').strip().lower()
    logger.info(f"Public business-types requested, brand='{app_brand}'")

    final_list = [
        # ── AttendX ──────────────────────────────────────────────────────────
        {
            "value": "bulk_attendance_attendx",
            "label": "AttendX",
            "app_type": "attendx",
            "allow_parent_login": True,
            "default_frontend_bundle_id": "attendx_bulk_ui",
            "default_registration_config": [
                {"field": "student_number", "label": "Student/Employee Number", "type": "text", "required": True},
                {"field": "class_section", "label": "Class/Department", "type": "text", "required": True},
                {"field": "daily_wage", "label": "Daily Wage", "type": "text", "required": False},
                {"field": "phone", "label": "Parent/Contact Mobile", "type": "text", "required": True}
            ]
        },
        # ── TapInX — Hostel ──────────────────────────────────────────────────
        {
            "value": "hostel",
            "label": "Hostel",
            "app_type": "tapinx",
            "allow_parent_login": True,
            "default_frontend_bundle_id": "tapinx_ui",
            "default_registration_config": [
                {"field": "student_id", "label": "Student ID", "type": "text", "required": True},
                {"field": "phone", "label": "Student Mobile Number", "type": "text", "required": True},
                {"field": "class_section", "label": "Class/Section", "type": "text", "required": False}
            ]
        },
        # ── TapInX — School / College ─────────────────────────────────────────
        {
            "value": "school",
            "label": "School / College",
            "app_type": "tapinx",
            "allow_parent_login": True,
            "default_frontend_bundle_id": "tapinx_ui",
            "default_registration_config": [
                {"field": "student_id", "label": "Student ID", "type": "text", "required": True},
                {"field": "phone", "label": "Student Mobile Number", "type": "text", "required": True},
                {"field": "class_section", "label": "Class/Section", "type": "text", "required": False}
            ]
        },
        # ── TapInX — Daily Wages (no parent login) ───────────────────────────
        {
            "value": "daily_wages",
            "label": "Daily Wages",
            "app_type": "tapinx",
            "allow_parent_login": False,
            "default_frontend_bundle_id": "tapinx_ui",
            "default_registration_config": [
                {"field": "employee_id", "label": "Employee ID", "type": "text", "required": True},
                {"field": "phone", "label": "Contact Mobile", "type": "text", "required": False},
                {"field": "department", "label": "Department", "type": "text", "required": False}
            ]
        },
        # ── Enterprise ───────────────────────────────────────────────────────
        {
            "value": "enterprise",
            "label": "Enterprise (Custom)",
            "app_type": "other",
            "allow_parent_login": False,
            "default_frontend_bundle_id": "default_attendance",
            "default_registration_config": []
        }
    ]

    # Filter by brand if the mobile app identified itself
    if app_brand == 'attendx':
        final_list = [t for t in final_list if t.get('app_type') == 'attendx']
    elif app_brand == 'tapinx':
        final_list = [t for t in final_list if t.get('app_type') == 'tapinx']

    logger.info(f"Returning {len(final_list)} business types for brand='{app_brand}'.")
    return jsonify({"business_types": final_list})
