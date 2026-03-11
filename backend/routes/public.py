from flask import Blueprint, jsonify, current_app
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
    Returns a list of business types (verticals).
    Now dynamic - fetches unique verticals from the vendors table and merges with defaults.
    """
    logger.info(f"Public business-types requested from {current_app.name}")
    
    # Default list of business types with their configurations
    default_types = {
        "School": {"value": "School", "label": "School", "allow_parent_login": True},
        "College": {"value": "College", "label": "College", "allow_parent_login": True},
        "Office": {"value": "Office", "label": "Office", "allow_parent_login": False},
        "Factory": {"value": "Factory", "label": "Factory", "allow_parent_login": False},
        "Hospital": {"value": "Hospital", "label": "Hospital", "allow_parent_login": False},
        "Gym": {"value": "Gym", "label": "Gym", "allow_parent_login": False},
        "Other": {"value": "Other", "label": "Other", "allow_parent_login": False}
    }

    # Fetch unique verticals from the database
    db_verticals = []
    try:
        from utils import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT DISTINCT vertical FROM vendors WHERE vertical IS NOT NULL AND vertical != ''")
        results = c.fetchall()
        for r in results:
            val = r[0] if not isinstance(r, dict) else r.get('vertical')
            if val:
                db_verticals.append(val)
        conn.close()
    except Exception as e:
        logger.error(f"Error fetching verticals from database for public-business-types: {e}")

    # Merge database values into our map
    for v in db_verticals:
        # Avoid duplicates and preserve case where possible, but use title case for label
        key_norm = v.strip().capitalize()
        if key_norm not in default_types:
            default_types[key_norm] = {
                "value": v,
                "label": v.replace('_', ' ').title(),
                "allow_parent_login": v.lower() in ['school', 'college', 'tuition']
            }

    # Convert mapping to a sorted list
    final_list = sorted(default_types.values(), key=lambda x: x['label'])
    
    logger.info(f"Returning {len(final_list)} business types.")
    return jsonify({
        "business_types": final_list
    })
