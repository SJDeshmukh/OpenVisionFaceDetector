from flask import Blueprint, jsonify
import sqlite3
import os

public_bp = Blueprint('public_bp', __name__)

# Note: BASE_URL and FRONTEND_URL will be imported from app or handled via current_app
# For now, we can use a helper or placeholder until we fully modularize

@public_bp.route('/config', methods=['GET'])
def get_config():
    from flask import current_app
    return jsonify({
        "backend_url": os.environ.get("BASE_URL", "http://localhost:5000"),
        "frontend_url": os.environ.get("FRONTEND_URL", "http://localhost:3000")
    })

@public_bp.route('/vendors', methods=['GET'])
def public_vendors():
    from app import get_db_connection
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT id, company_name, vertical, status FROM vendors ORDER BY company_name ASC")
        rows = c.fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()

    vendors = []
    for r in rows or []:
        try:
            rd = dict(r)
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
    return jsonify({
        "business_types": [
            {"value": "School", "label": "School"},
            {"value": "College", "label": "College"},
            {"value": "Office", "label": "Office"},
            {"value": "Factory", "label": "Factory"},
            {"value": "Hospital", "label": "Hospital"},
            {"value": "Gym", "label": "Gym"},
            {"value": "Other", "label": "Other"}
        ]
    })
