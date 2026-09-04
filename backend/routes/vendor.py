from flask import Blueprint, request, jsonify, send_file, send_from_directory, g
import logging
logger = logging.getLogger(__name__)
import sqlite3
import json
import base64
import os
import io
import time
import re
from datetime import datetime, date, timedelta
from services.auth_service import authenticate_vendor_access, extract_token, verify_token
from utils import parse_db_date, parse_db_datetime, cache_get, cache_set, cache_delete_vendor_prefix
from services.person_scope_service import (
    apply_class_mapping,
    class_id_for,
    class_scope_matches,
    is_school_hostel,
    parse_custom_data,
    person_type_for,
    vendor_vertical,
)

# Mock Auth Decorators
def vendor_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        vendor_id, err = authenticate_vendor_access()
        if err: return err
        request.vendor_id = vendor_id
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        _vendor_id, error = authenticate_vendor_access()
        if error:
            return error
        if g.user_role not in ['super_admin', 'vendor_admin', 'admin', 'owner']:
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

def track_metrics(endpoint_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator
    
def rate_limit(*args, **kwargs):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator
    
from utils import require_feature

vendor_bp = Blueprint('vendor_bp', __name__)

from utils import ALL_FEATURES, log_audit

@vendor_bp.route("/logo.png", methods=["GET"])
def get_logo_png():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logo_dir = os.path.join(base_dir, "logo")
    try:
        return send_from_directory(logo_dir, "logo.png")
    except Exception:
        return jsonify({"error": "Logo not found"}), 404


@vendor_bp.route("/mobile/device-slots", methods=["GET"])
def mobile_list_slots():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS vendor_device_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER,
                slot_name TEXT,
                assigned_device_id TEXT,
                assigned_at DATETIME,
                UNIQUE(vendor_id, slot_name)
            )
        """)
        c.execute("SELECT slot_name FROM vendor_device_slots WHERE vendor_id = ? AND (assigned_device_id IS NULL OR assigned_device_id = '') ORDER BY id ASC", (vendor_id,))
        rows = [r[0] if not hasattr(r, 'keys') else r['slot_name'] for r in (c.fetchall() or [])]
        conn.close()
        return jsonify({"slots": rows})
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@vendor_bp.route("/mobile/device-info", methods=["GET"])
def mobile_device_info():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # Resolve current device_id from token
        auth_header = request.headers.get('Authorization')
        token = extract_token(auth_header)
        device_id = None
        if token:
            c.execute("SELECT device_id FROM active_sessions WHERE token = ? LIMIT 1", (token,))
            row = c.fetchone()
            if row:
                try:
                    device_id = row['device_id']
                except Exception:
                    device_id = row[0]
        device_name = None
        if device_id:
            c.execute("SELECT device_name FROM vendor_devices WHERE vendor_id = ? AND device_id = ? LIMIT 1", (vendor_id, device_id))
            r = c.fetchone()
            if r:
                try:
                    device_name = r['device_name']
                except Exception:
                    device_name = r[0]
        conn.close()
        return jsonify({"device_id": device_id, "device_name": device_name})
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@vendor_bp.route("/vendor/device-health", methods=["GET"])
@vendor_required
def vendor_device_health():
    """Return persistent device health for the authenticated vendor.

    Unlike the live-stream endpoint, registered mobile devices remain visible
    after their latest video frame expires or the API process restarts.
    """
    from app import get_db_connection

    vendor_id = request.vendor_id
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT device_id, device_name, registered_at, last_login_at,
                   last_active_at, battery_level
            FROM vendor_devices
            WHERE vendor_id = ?
            ORDER BY last_active_at DESC, registered_at DESC
        """, (vendor_id,))
        devices = []
        for raw in c.fetchall() or []:
            row = dict(raw) if hasattr(raw, "keys") else dict(zip(
                ("device_id", "device_name", "registered_at", "last_login_at", "last_active_at", "battery_level"), raw
            ))
            last_active = parse_db_datetime(row.get("last_active_at") or row.get("last_login_at"))
            comparison_now = datetime.now(last_active.tzinfo) if last_active and last_active.tzinfo else datetime.now()
            age_seconds = (comparison_now - last_active).total_seconds() if last_active else None
            devices.append({
                "device_id": row.get("device_id"),
                "device_name": row.get("device_name") or f"Device {row.get('device_id')}",
                "registered_at": str(row.get("registered_at") or ""),
                "last_seen": last_active.isoformat() if last_active else None,
                "battery_level": row.get("battery_level"),
                "online": bool(age_seconds is not None and 0 <= age_seconds < 300),
            })
        return jsonify({"devices": devices})
    finally:
        conn.close()


@vendor_bp.route("/mobile/assign-slot", methods=["POST"])
def mobile_assign_slot():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    data = request.json or {}
    device_id = str(data.get("device_id") or "").strip()
    slot_name = str(data.get("slot_name") or "").strip()
    if not device_id or not slot_name:
        return jsonify({"error": "device_id and slot_name required"}), 400
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Ensure slot exists
        c.execute("SELECT id, assigned_device_id FROM vendor_device_slots WHERE vendor_id = ? AND slot_name = ? LIMIT 1", (vendor_id, slot_name))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Slot not found"}), 404
        current_assigned = None
        try:
            current_assigned = row['assigned_device_id']
        except Exception:
            current_assigned = row[1]
        # If assigned to another device, block
        if current_assigned and current_assigned != device_id:
            conn.close()
            return jsonify({"error": "Slot already assigned"}), 409
        # Clear any previous assignment for this device on other slots (reassignment)
        try:
            c.execute("UPDATE vendor_device_slots SET assigned_device_id = NULL, assigned_at = NULL WHERE vendor_id = ? AND assigned_device_id = ? AND slot_name != ?", (vendor_id, device_id, slot_name))
        except Exception:
            pass
        # Assign target slot to this device
        now = datetime.now()
        c.execute("UPDATE vendor_device_slots SET assigned_device_id = ?, assigned_at = ? WHERE vendor_id = ? AND slot_name = ?", (device_id, now, vendor_id, slot_name))
        # Upsert vendor_devices and sync friendly name
        try:
            # Our PostgresCursorWrapper translates INSERT OR IGNORE to ON CONFLICT DO NOTHING
            c.execute("INSERT OR IGNORE INTO vendor_devices (vendor_id, device_id, device_name, registered_at, last_login_at) VALUES (?, ?, ?, ?, ?)", (vendor_id, device_id, slot_name, now, now))
            c.execute("UPDATE vendor_devices SET device_name = ?, last_login_at = ? WHERE vendor_id = ? AND device_id = ?", (slot_name, now, vendor_id, device_id))
        except Exception as e:
            logger.error(f"Error upserting vendor_device in assign_slot: {e}")
        conn.commit()
        try:
            ev = {"vendor_id": vendor_id, "device_id": device_id, "device_name": slot_name}
            socketio.emit("device_name_updated", ev, room=f"vendor_{vendor_id}")
        except Exception:
            pass
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

# --- Company & Timetable Endpoints ---


@vendor_bp.route("/vendor/subscription", methods=["GET"])
def get_vendor_subscription():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    if not vendor_id:
         return jsonify({"error": "No vendor context"}), 400

    cache_key = f"vendor:{vendor_id}:subscription"
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""
        SELECT s.*, v.company_name, v.status as vendor_status 
        FROM subscriptions s 
        JOIN vendors v ON s.vendor_id = v.id 
        WHERE s.vendor_id = ?
    """, (vendor_id,))
    
    sub = c.fetchone()
    
    if not sub:
        conn.close()
        return jsonify({"error": "No subscription found"}), 404
        
    sub_dict = dict(sub)

    try:
        today = date.today().isoformat()
        c.execute("UPDATE invoices SET status = 'overdue' WHERE vendor_id = ? AND status = 'generated' AND due_date < ?", (vendor_id, today))
        conn.commit()
    except Exception:
        pass

    invoices = []
    try:
        c.execute("SELECT * FROM invoices WHERE vendor_id = ? ORDER BY invoice_date DESC", (vendor_id,))
        invoices = [dict(row) for row in c.fetchall()]
    except Exception:
        invoices = []
        
    conn.close()
    
    # Calculate days left
    days_left = 0
    if sub_dict and sub_dict['end_date']:
            # Robust parsing (handle PG objects vs SQLite strings)
            end_date = parse_db_date(sub_dict['end_date'])
            if end_date:
                # The original code calculated days_left here, let's re-add that logic
                days_left = (end_date - date.today()).days
                # The instruction snippet included these lines, but they don't seem to be used later in the provided context.
                # features = json.loads(sub_dict['features']) if sub_dict['features'] else []
                # is_expired = date.today() > end_date
            else:
                days_left = 0 # If end_date parsing fails, default to 0
    sub_dict['days_left'] = days_left

    try:
        feats = sub_dict.get('features')
        if isinstance(feats, str):
            sub_dict['features'] = json.loads(feats) if feats.strip() else []
        elif feats is None:
            sub_dict['features'] = []
    except Exception:
        sub_dict['features'] = []
    sub_dict['invoices'] = invoices

    try:
        max_web = int(sub_dict.get("max_web_sessions") or 0)
        if max_web < 1:
            sub_dict["max_web_sessions"] = 1
    except Exception:
        sub_dict["max_web_sessions"] = 1
    
    cache_set(cache_key, sub_dict, 3600) # 1 hour cache for subscription
    return jsonify(sub_dict)


@vendor_bp.route("/companies", methods=["GET"])
def get_companies():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if not vendor_id:
        auth_header = request.headers.get('Authorization')
        token = extract_token(auth_header) if auth_header else None
        data = verify_token(token) if token else None
        if data and data.get("role") == "super_admin":
            return jsonify({"error": "Vendor Context Required"}), 400

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT id, name FROM companies"
    params = []
    
    if vendor_id:
        query += " WHERE vendor_id = ?"
        params.append(vendor_id)
        
    c.execute(query, params)
    companies = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify({"companies": companies})


@vendor_bp.route("/companies", methods=["POST"])
def create_company():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if not vendor_id:
        return jsonify({"error": "Vendor Context Required"}), 400
    
    data = request.json
    person_id = data.get("id") or data.get("person_id")
    name = data.get("name")
    if not name:
        return jsonify({"error": "Name is required"}), 400
        
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Check if vendor already has a company
        if vendor_id:
            c.execute("SELECT id FROM companies WHERE vendor_id = ?", (vendor_id,))
            if c.fetchone():
                conn.close()
                return jsonify({"error": "Vendor already has a company"}), 400
        
        c.execute("INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)", 
                  (name, '[]', '[]', '[]', vendor_id))
        conn.commit()
        company_id = c.lastrowid
        conn.close()
        return jsonify({"success": True, "id": company_id, "name": name})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Company already exists"}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@vendor_bp.route("/companies/<int:company_id>", methods=["PUT"])
def update_company_settings(company_id):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if not vendor_id:
        return jsonify({"error": "Vendor Context Required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    
    # Verify Ownership
    if vendor_id:
        c.execute("SELECT vendor_id FROM companies WHERE id = ?", (company_id,))
        row = c.fetchone()
        if not row or (row[0] and row[0] != vendor_id):
             conn.close()
             return jsonify({"error": "Access Denied"}), 403

    data = request.json
    shifts = data.get("shifts") 
    working_hours = data.get("working_hours")

    if shifts is not None:
        # Check Feature 'shifts' if we are updating shifts
        if vendor_id:
            # Re-check feature manually because this endpoint updates multiple things
            conn_check = get_db_connection()
            c_check = conn_check.cursor()
            c_check.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
            sub_row = c_check.fetchone()
            conn_check.close()
            
            has_shifts = False
            if sub_row and sub_row[0]:
                try:
                    features_str = sub_row[0]
                    feats = json.loads(features_str) if features_str else []
                    if "shifts" in feats:
                        has_shifts = True
                except (json.JSONDecodeError, ValueError):
                    pass
            
            if not has_shifts:
                conn.close()
                return jsonify({"error": "Feature 'shifts' is not enabled for your plan."}), 403

        if isinstance(shifts, list):
            shifts = json.dumps(shifts)
        c.execute("UPDATE companies SET shifts = ? WHERE id = ?", (shifts, company_id))
    
    if working_hours is not None:
        c.execute("UPDATE companies SET working_hours = ? WHERE id = ?", (working_hours, company_id))

    conn.commit()
    conn.close()
    return jsonify({"success": True})


@vendor_bp.route("/companies/<int:company_id>", methods=["GET"])
def get_company_details(company_id):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if not vendor_id:
        return jsonify({"error": "Vendor Context Required"}), 400

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"error": "Company not found"}), 404
        
    # Verify Ownership
    if vendor_id and row['vendor_id'] and row['vendor_id'] != vendor_id:
        conn.close()
        return jsonify({"error": "Access Denied"}), 403
        
    conn.close()
    
    data = dict(row)
    for key in ['shifts', 'draft_timetable', 'live_timetable']:
        if data.get(key):
            try:
                data[key] = json.loads(data[key])
            except (json.JSONDecodeError, ValueError):
                data[key] = []
    return jsonify(data)


@vendor_bp.route("/companies/<int:company_id>/draft", methods=["PUT"])
@require_feature("shifts")
def update_draft_timetable(company_id):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if not vendor_id:
        return jsonify({"error": "Vendor Context Required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    
    # Verify Ownership
    if vendor_id:
        c.execute("SELECT vendor_id FROM companies WHERE id = ?", (company_id,))
        row = c.fetchone()
        if not row or (row[0] and row[0] != vendor_id):
             conn.close()
             return jsonify({"error": "Access Denied"}), 403

    data = request.json
    draft_timetable = data.get("draft_timetable") # Expecting JSON string or object
    modified_by = data.get("modified_by", "unknown")
    
    if draft_timetable is None:
        conn.close()
        return jsonify({"error": "draft_timetable is required"}), 400

    if isinstance(draft_timetable, list):
        draft_timetable = json.dumps(draft_timetable)

    c.execute("""UPDATE companies 
                 SET draft_timetable = ?, last_modified_by = ?, last_modified_at = ? 
                 WHERE id = ?""", 
              (draft_timetable, modified_by, datetime.now(), company_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@vendor_bp.route("/companies/<int:company_id>/publish", methods=["POST"])
@require_feature("shifts")
def publish_timetable(company_id):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if not vendor_id:
        return jsonify({"error": "Vendor Context Required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    
    # Verify Ownership
    if vendor_id:
        c.execute("SELECT vendor_id FROM companies WHERE id = ?", (company_id,))
        row = c.fetchone()
        if not row or (row[0] and row[0] != vendor_id):
             conn.close()
             return jsonify({"error": "Access Denied"}), 403

    data = request.json
    published_by = data.get("published_by", "unknown")
    
    # Copy draft to live
    c.execute("""UPDATE companies 
                 SET live_timetable = draft_timetable, published_by = ?, published_at = ? 
                 WHERE id = ?""", 
              (published_by, datetime.now(), company_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@vendor_bp.route("/classes", methods=["GET"])
def list_classes():
    from app import get_db_connection, socketio, is_testing
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    try:
        conn = get_db_connection()
        c = conn.cursor()

        if g.user_role == 'faculty':
            # Filter classes in Python for simplicity with JSON storage
            conn.row_factory = None # Ensure simple indexing if needed, or dict if preferred
            c.execute("SELECT id, class_year, division, branch, label, mapped_subjects FROM classes WHERE vendor_id = ?", (vendor_id,))
            rows = c.fetchall() or []
            items = []
            for r in rows:
                ms_raw = r[5]
                ms = []
                try:
                    ms = json.loads(ms_raw) if ms_raw else []
                except (json.JSONDecodeError, ValueError): pass
                
                # Check if this faculty is assigned to any subject in this class
                if any(m.get('faculty') == g.username for m in ms):
                    items.append({
                        "id": r[0], "class_year": r[1], "division": r[2], "branch": r[3], "label": r[4], 
                        "mapped_subjects": ms
                    })
            conn.close()
            return jsonify({"classes": items})

        if not vendor_id:
            conn.close()
            return jsonify({"error": "Vendor Context Required"}), 400
        c.execute("SELECT id, class_year, division, branch, label, mapped_subjects FROM classes WHERE vendor_id = ? ORDER BY created_at DESC", (vendor_id,))
        rows = c.fetchall() or []
        conn.close()
        items = []
        for r in rows:
            mapped_subjects_list = []
            try:
                mapped_subjects_list = json.loads(r[5]) if r[5] else []
            except (json.JSONDecodeError, ValueError):
                pass

            items.append({
                "id": r[0], "class_year": r[1], "division": r[2], "branch": r[3], "label": r[4], "mapped_subjects": mapped_subjects_list
            })
        return jsonify({"classes": items})
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@vendor_bp.route("/classes", methods=["POST"])
def create_class():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    if g.user_role not in {'super_admin', 'vendor_admin', 'admin', 'owner'}:
        return jsonify({"error": "Access Denied"}), 403
    data = request.get_json(silent=True) or {}
    try:
        conn = get_db_connection()
        c = conn.cursor()

        class_year = str(data.get('class_year') or '').strip()
        division = str(data.get('division') or '').strip()
        branch = str(data.get('branch') or '').strip()
        if is_school_hostel(vendor_vertical(c, vendor_id)) and (not class_year or not division):
            conn.close()
            return jsonify({"error": "Class year and section/division are required"}), 400
        c.execute(
            """SELECT id FROM classes WHERE vendor_id = ?
               AND LOWER(TRIM(COALESCE(class_year, ''))) = LOWER(TRIM(?))
               AND LOWER(TRIM(COALESCE(division, ''))) = LOWER(TRIM(?))
               AND LOWER(TRIM(COALESCE(branch, ''))) = LOWER(TRIM(?)) LIMIT 1""",
            (vendor_id, class_year, division, branch),
        )
        if c.fetchone():
            conn.close()
            return jsonify({"error": "This class/section already exists"}), 409
        mapped_subjects_json = json.dumps(data.get('mapped_subjects') or [])
        
        c.execute("INSERT INTO classes (vendor_id, class_year, division, branch, label, mapped_subjects) VALUES (?, ?, ?, ?, ?, ?)",
                  (vendor_id, class_year, division, branch, str(data.get('label') or ''), mapped_subjects_json))
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({"ok": True, "id": new_id})
    except Exception as e:
        try:
            conn.rollback(); conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@vendor_bp.route("/classes/<int:cid>", methods=["PUT"])
def update_class(cid: int):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    if g.user_role not in {'super_admin', 'vendor_admin', 'admin', 'owner'}:
        return jsonify({"error": "Access Denied"}), 403
    data = request.get_json(silent=True) or {}
    try:
        conn = get_db_connection()
        c = conn.cursor()
            
        c.execute("SELECT vendor_id, class_year, division, branch FROM classes WHERE id = ?", (cid,))
        row = c.fetchone()
        if not row or (vendor_id and int(row[0]) != int(vendor_id)):
            conn.close()
            return jsonify({"error": "not found"}), 404
        old_year, old_division, old_branch = row[1], row[2], row[3]
        new_year = str(data.get('class_year', old_year) or '').strip()
        new_division = str(data.get('division', old_division) or '').strip()
        new_branch = str(data.get('branch', old_branch) or '').strip()
        if is_school_hostel(vendor_vertical(c, vendor_id)) and (not new_year or not new_division):
            conn.close()
            return jsonify({"error": "Class year and section/division are required"}), 400
        c.execute(
            """SELECT id FROM classes WHERE vendor_id = ? AND id <> ?
               AND LOWER(TRIM(COALESCE(class_year, ''))) = LOWER(TRIM(?))
               AND LOWER(TRIM(COALESCE(division, ''))) = LOWER(TRIM(?))
               AND LOWER(TRIM(COALESCE(branch, ''))) = LOWER(TRIM(?)) LIMIT 1""",
            (vendor_id, cid, new_year, new_division, new_branch),
        )
        if c.fetchone():
            conn.close()
            return jsonify({"error": "This class/section already exists"}), 409

        fields = []; params = []
        for k in ["class_year", "division", "branch", "label"]:
            if k in data:
                fields.append(f"{k} = ?"); params.append(str(data.get(k) or ''))
        
        if 'mapped_subjects' in data:
            fields.append("mapped_subjects = ?"); params.append(json.dumps(data.get('mapped_subjects') or []))

        if fields:
            params.append(cid)
            c.execute(f"UPDATE classes SET {', '.join(fields)} WHERE id = ?", params)
            # Class ID is authoritative. Keep every linked student's snapshots
            # and recognition metadata aligned when a class is renamed.
            c.execute("""SELECT f.id, f.custom_data,
                                (SELECT su.role FROM system_users su
                                 WHERE su.person_id = f.id AND su.vendor_id = f.vendor_id
                                 ORDER BY CASE WHEN LOWER(su.role) = 'faculty' THEN 0 ELSE 1 END
                                 LIMIT 1) AS system_role
                         FROM faces f WHERE f.vendor_id = ?""", (vendor_id,))
            face_rows = c.fetchall() or []
            affected_ids = []
            vertical = vendor_vertical(c, vendor_id)
            for face_row in face_rows:
                custom = parse_custom_data(face_row[1])
                if person_type_for(custom, face_row[2], vertical) != 'student':
                    continue
                linked = class_id_for(custom) == str(cid)
                legacy_match = not class_id_for(custom) and class_scope_matches(
                    custom, class_year=old_year, division=old_division, branch=old_branch,
                )
                if not linked and not legacy_match:
                    continue
                updated = apply_class_mapping(custom, cid, new_year, new_division, new_branch)
                updated['person_type'] = 'student'
                c.execute("UPDATE faces SET custom_data = ? WHERE id = ? AND vendor_id = ?",
                          (json.dumps(updated, separators=(',', ':')), face_row[0], vendor_id))
                affected_ids.append(face_row[0])
            for person_id in affected_ids:
                c.execute("""UPDATE person_embeddings SET class_year = ?, division = ?, branch = ?
                             WHERE person_id = ? AND vendor_id = ?""",
                          (new_year, new_division, new_branch, person_id, vendor_id))
            conn.commit()
            cache_delete_vendor_prefix(vendor_id)
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        try:
            conn.rollback(); conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@vendor_bp.route("/classes/<int:cid>", methods=["DELETE"])
def delete_class(cid: int):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    if g.user_role not in {'super_admin', 'vendor_admin', 'admin', 'owner'}:
        return jsonify({"error": "Access Denied"}), 403
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT class_year, division, branch FROM classes WHERE id = ? AND vendor_id = ?", (cid, vendor_id))
        class_row = c.fetchone()
        if not class_row:
            conn.close()
            return jsonify({"error": "not found"}), 404
        c.execute("""SELECT f.id, f.custom_data,
                            (SELECT su.role FROM system_users su
                             WHERE su.person_id = f.id AND su.vendor_id = f.vendor_id
                             ORDER BY CASE WHEN LOWER(su.role) = 'faculty' THEN 0 ELSE 1 END
                             LIMIT 1) AS system_role
                     FROM faces f WHERE f.vendor_id = ?""", (vendor_id,))
        face_rows = c.fetchall() or []
        vertical = vendor_vertical(c, vendor_id)
        assigned = []
        for face_row in face_rows:
            if person_type_for(face_row[1], face_row[2], vertical) != 'student':
                continue
            custom = parse_custom_data(face_row[1])
            if class_id_for(custom) == str(cid) or (
                not class_id_for(custom) and class_scope_matches(
                    custom, class_year=class_row[0], division=class_row[1], branch=class_row[2],
                )
            ):
                assigned.append(face_row[0])
        if assigned:
            conn.close()
            return jsonify({
                "error": "Move all students to another class before deleting this class",
                "assigned_students": len(assigned),
            }), 409
        c.execute("DELETE FROM classes WHERE id = ? AND vendor_id = ?", (cid, vendor_id))
        conn.commit()
        cache_delete_vendor_prefix(vendor_id)
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        try:
            conn.rollback(); conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@vendor_bp.route("/vendor/invoices", methods=["GET"])
def get_my_invoices():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    if not vendor_id:
        return jsonify({"error": "No vendor context"}), 400

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        today = date.today().isoformat()
        c.execute("UPDATE invoices SET status = 'overdue' WHERE vendor_id = ? AND status = 'generated' AND due_date < ?", (vendor_id, today))
        conn.commit()
    except Exception:
        pass
    c.execute("SELECT * FROM invoices WHERE vendor_id = ? ORDER BY invoice_date DESC", (vendor_id,))
    invoices = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify({"invoices": invoices})



@vendor_bp.route("/settings/late-config", methods=["PUT"])
@require_feature("payroll")
def update_global_late_config():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    if not vendor_id:
        return jsonify({"error": "Vendor Context Required"}), 400
    if g.user_role not in {'vendor_admin', 'admin', 'owner'}:
        return jsonify({"error": "Access Denied"}), 403
    
    # Only allow Admin (implicit via authenticate_vendor_access usually, but good to check role if needed)
    # Assuming authenticate_vendor_access checks for valid token.
    
    data = request.json
    allowance = data.get('allowance')
    deduction = data.get('deduction')
    pf_pct = data.get('pf_percentage')
    esi_pct = data.get('esi_percentage')
    grat_pct = data.get('gratuity_percentage')
    grat_years = data.get('gratuity_threshold_years')
    timezone_offset = data.get('timezone_offset')
    
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        if allowance is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      (f'global_late_allowance_vendor_{vendor_id}', str(allowance)))
            
        if deduction is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      (f'global_late_deduction_vendor_{vendor_id}', str(deduction)))

        if pf_pct is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      (f'global_pf_percentage_vendor_{vendor_id}', str(pf_pct)))

        if esi_pct is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      (f'global_esi_percentage_vendor_{vendor_id}', str(esi_pct)))

        if grat_pct is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      (f'global_gratuity_percentage_vendor_{vendor_id}', str(grat_pct)))

        if grat_years is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      (f'global_gratuity_threshold_years_vendor_{vendor_id}', str(grat_years)))

        if timezone_offset is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      (f'global_timezone_offset_vendor_{vendor_id}', str(timezone_offset)))

        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

@vendor_bp.route("/vendor/owners", methods=["GET"])
@vendor_required
def get_vendor_owners():
    from app import get_db_connection
    vendor_id = request.vendor_id
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT username FROM system_users WHERE vendor_id = ? AND role = 'owner'", (vendor_id,))
        owners = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify({"owners": owners})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@vendor_bp.route("/vendor/owners", methods=["PUT"])
@vendor_required
def sync_vendor_owners():
    from app import get_db_connection
    from services.auth_service import hash_password
    vendor_id = request.vendor_id
    data = request.json or {}
    owners = data.get('owners', [])
    
    if not isinstance(owners, list):
        return jsonify({"error": "owners must be a list"}), 400
    if g.user_role not in {'vendor_admin', 'admin', 'owner'}:
        return jsonify({"error": "Admin or owner access required"}), 403

    normalized_owners = []
    seen_usernames = set()
    for owner_data in owners:
        if not isinstance(owner_data, dict):
            return jsonify({"error": "Each owner must be an object"}), 400
        username = str(owner_data.get("username") or "").strip()
        password = str(owner_data.get("password") or "")
        if not username:
            continue
        username_key = username.casefold()
        if username_key in seen_usernames:
            return jsonify({"error": f"Duplicate owner username: {username}"}), 400
        if password and len(password) < 8:
            return jsonify({"error": f"Password must be at least 8 characters for {username}"}), 400
        seen_usernames.add(username_key)
        normalized_owners.append({"username": username, "password": password})

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Fetch current owners
        c.execute("SELECT username FROM system_users WHERE vendor_id = ? AND role = 'owner'", (vendor_id,))
        current_owners = {row[0] for row in c.fetchall()}
        
        new_owner_usernames = set()
        for owner_data in normalized_owners:
            o_username = owner_data.get("username")
            o_password = owner_data.get("password")
            new_owner_usernames.add(o_username)
            
            if o_username in current_owners:
                if o_password:
                    c.execute("UPDATE system_users SET password = ?, password_plain = NULL WHERE username = ? AND vendor_id = ?",
                               (hash_password(o_password), o_username, vendor_id))
            else:
                # Check for global uniqueness across all users
                c.execute("SELECT username FROM system_users WHERE username = ?", (o_username,))
                if c.fetchone():
                    conn.rollback()
                    conn.close()
                    return jsonify({"error": f"Username is already used by another account: {o_username}"}), 409
                
                if not o_password:
                    conn.rollback()
                    conn.close()
                    return jsonify({"error": f"A password of at least 8 characters is required for new owner {o_username}"}), 400
                c.execute("INSERT INTO system_users (username, password, password_plain, role, vendor_id) VALUES (?, ?, NULL, 'owner', ?)",
                           (o_username, hash_password(o_password), vendor_id))
        
        # Remove omitted owners
        to_remove = current_owners - new_owner_usernames
        for r_username in to_remove:
            c.execute("DELETE FROM system_users WHERE username = ? AND vendor_id = ? AND role = 'owner'", (r_username, vendor_id))
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        logger.exception("Unable to update owner accounts for vendor %s", vendor_id)
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": "Unable to update owner accounts"}), 500


@vendor_bp.route("/settings", methods=["GET"])
def get_settings():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    allowed_keys = {'threshold', 'cooldown', 'work_start_time', 'late_threshold', 'late_grace_period', 'auto_checkout', 'voice_greeting', 'admin_alerts'}
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT key, value FROM system_settings")
    rows = c.fetchall()
    conn.close()
    
    all_settings = {row['key']: row['value'] for row in rows}
    if not vendor_id:
        return jsonify({k: all_settings[k] for k in allowed_keys if k in all_settings})

    effective = {}
    for k in allowed_keys:
        vkey = f"{k}_vendor_{vendor_id}"
        if vkey in all_settings and all_settings[vkey] is not None and str(all_settings[vkey]).strip() != "":
            effective[k] = all_settings[vkey]
    return jsonify(effective)


@vendor_bp.route("/settings", methods=["POST"])
def update_settings():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error

    allowed_keys = {'threshold', 'cooldown', 'work_start_time', 'late_threshold', 'late_grace_period', 'auto_checkout', 'voice_greeting', 'admin_alerts'}
    data = request.json or {}
    role = g.user_role
    if role not in {'super_admin', 'vendor_admin', 'admin', 'owner'}:
        return jsonify({"error": "Access Denied"}), 403
    if role != 'super_admin' and not vendor_id:
        return jsonify({"error": "Vendor Context Required"}), 400

    try:
        if 'threshold' in data and not 0.4 <= float(data['threshold']) <= 0.95:
            raise ValueError("threshold must be between 0.40 and 0.95")
        if 'cooldown' in data and not 5 <= int(data['cooldown']) <= 3600:
            raise ValueError("cooldown must be between 5 and 3600 seconds")
        for time_key in ('work_start_time', 'late_threshold'):
            if time_key in data and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', str(data[time_key])):
                raise ValueError(f"{time_key} must use HH:MM format")
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        for key, value in data.items():
            if key not in allowed_keys:
                continue
            store_key = key
            if vendor_id:
                store_key = f"{key}_vendor_{vendor_id}"
            # Ensure value is string
            if isinstance(value, bool):
                val_str = 'true' if value else 'false'
            else:
                val_str = str(value) if value is not None else ""
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (store_key, val_str))
        conn.commit()
        return jsonify({"status": "success", "message": "Settings updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# --- User Management Endpoints ---

@vendor_bp.route("/users", methods=["GET"])
def get_users():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT username, role FROM system_users"
    params = []
    
    if vendor_id:
        query += " WHERE vendor_id = ?"
        params.append(vendor_id)
        
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    users = [{"username": row["username"], "role": row["role"]} for row in rows]
    return jsonify({"users": users})


@vendor_bp.route("/users", methods=["POST"])
@admin_required
def create_user():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    from routes.auth import register_user
    return register_user() # Reuse register logic


@vendor_bp.route("/users/<username>", methods=["PUT"])
@admin_required
def update_user(username):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    data = request.json
    password = data.get("password")
    role = data.get("role")

    if not password and not role:
        return jsonify({"error": "Nothing to update"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Construct Query
        query = "UPDATE system_users SET "
        params = []
        updates = []
        
        if password:
            from services.auth_service import hash_password
            updates.extend(["password = ?", "password_plain = NULL"])
            params.append(hash_password(password))
        if role:
            updates.append("role = ?")
            params.append(role)
            
        query += ", ".join(updates)
        query += " WHERE username = ?"
        params.append(username)
        
        if vendor_id:
            query += " AND vendor_id = ?"
            params.append(vendor_id)
            
        c.execute(query, params)
        conn.commit()
        
        if c.rowcount > 0:
            return jsonify({"status": "success", "message": f"User {username} updated"})
        else:
            return jsonify({"error": "User not found or access denied"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@vendor_bp.route("/users/<username>", methods=["DELETE"])
@admin_required
def delete_user(username):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if username == "admin": # Prevent deleting the main admin
        return jsonify({"error": "Cannot delete default admin"}), 403

    conn = get_db_connection()
    c = conn.cursor()
    try:
        if vendor_id:
            c.execute("DELETE FROM system_users WHERE username = ? AND vendor_id = ?", (username, vendor_id))
        else:
            c.execute("DELETE FROM system_users WHERE username = ?", (username,))
            
        conn.commit()
        if c.rowcount > 0:
            return jsonify({"status": "success", "message": f"User {username} deleted"})
        else:
            return jsonify({"error": "User not found or access denied"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# --- Sync Endpoints ---



@vendor_bp.route("/class-threshold", methods=["GET"])
def get_class_threshold():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    from socket_handlers import latest_frames, client_counts, device_status
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    class_year = request.args.get('class_year') or ''
    division = request.args.get('division') or ''
    branch = request.args.get('branch') or ''
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS class_thresholds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            class_year TEXT,
            division TEXT,
            branch TEXT,
            threshold REAL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vendor_id, class_year, division, branch)
        )""")
        c.execute("""SELECT threshold FROM class_thresholds WHERE vendor_id = ? AND class_year = ? AND division = ? AND branch = ?""",
                  (vendor_id, str(class_year), str(division), str(branch)))
        row = c.fetchone()
        thr = float(row[0]) if row and row[0] is not None else None
        conn.close()
        return jsonify({"threshold": thr})
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

import math

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # Radius of earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

@vendor_bp.route("/mobile/heartbeat", methods=["POST"])
def mobile_heartbeat():
    from app import get_db_connection, socketio
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json or {}
    device_id = data.get("device_id")
    battery_level = data.get("battery_level")
    lat = data.get("latitude")
    lng = data.get("longitude")
    
    if not device_id:
        # Fallback: resolve from session if possible
        auth_header = request.headers.get('Authorization')
        token = extract_token(auth_header)
        if token:
            try:
                conn_s = get_db_connection()
                c_s = conn_s.cursor()
                c_s.execute("SELECT device_id FROM active_sessions WHERE token = ? LIMIT 1", (token,))
                row = c_s.fetchone()
                if row:
                    device_id = row[0] if not hasattr(row, 'keys') else row['device_id']
                conn_s.close()
            except Exception:
                pass

    if not device_id:
        return jsonify({"error": "device_id required"}), 400
        
    try:
        conn = get_db_connection()
        try:
            if not getattr(conn, "_is_pg", False):
                conn.row_factory = sqlite3.Row
        except Exception:
            pass
            
        c = conn.cursor()
        now = datetime.now()
        
        # Get existing device to check geofence anchor
        try:
            c.execute("SELECT geofence_lat, geofence_lng, geofence_radius FROM vendor_devices WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
            device_row = c.fetchone()
        except Exception as e:
            logger.error(f"Error fetching device info in heartbeat: {e}")
            device_row = None
        
        geofence_status = "inside"
        if device_row:
            row_dict = dict(device_row) if hasattr(device_row, 'keys') or isinstance(device_row, dict) else {'geofence_lat': device_row[0], 'geofence_lng': device_row[1], 'geofence_radius': device_row[2]}
            anchor_lat = row_dict.get('geofence_lat')
            anchor_lng = row_dict.get('geofence_lng')
            radius = row_dict.get('geofence_radius')
            
            if lat is not None and lng is not None:
                lat = float(lat)
                lng = float(lng)
                # If no anchor yet, this becomes the anchor
                if anchor_lat is None or anchor_lng is None:
                    c.execute("""
                        UPDATE vendor_devices 
                        SET last_active_at = ?, battery_level = ?, last_lat = ?, last_lng = ?, geofence_lat = ?, geofence_lng = ? 
                        WHERE vendor_id = ? AND device_id = ?
                    """, (now, battery_level, lat, lng, lat, lng, vendor_id, device_id))
                else:
                    # Anchor exists, check distance
                    if radius is not None and radius > 0:
                        dist = haversine_distance(anchor_lat, anchor_lng, lat, lng)
                        if dist > radius:
                            geofence_status = "outside"
                    
                    c.execute("""
                        UPDATE vendor_devices 
                        SET last_active_at = ?, battery_level = ?, last_lat = ?, last_lng = ? 
                        WHERE vendor_id = ? AND device_id = ?
                    """, (now, battery_level, lat, lng, vendor_id, device_id))
            else:
                # No GPS provided
                c.execute("""
                    UPDATE vendor_devices 
                    SET last_active_at = ?, battery_level = ? 
                    WHERE vendor_id = ? AND device_id = ?
                """, (now, battery_level, vendor_id, device_id))
        else:
             # Device not found (e.g., student device or missing record), insert it
             try:
                 # INSERT OR IGNORE is translated by our PostgresCursorWrapper
                 c.execute("""
                    INSERT OR IGNORE INTO vendor_devices 
                    (vendor_id, device_id, device_name, registered_at, last_active_at, battery_level, last_lat, last_lng, geofence_lat, geofence_lng) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                 """, (vendor_id, device_id, f"Mobile {device_id[:6]}", now, now, battery_level, lat, lng, lat, lng))
                 
                 # Immediately update in case it was IGNORED above but needs fields updated
                 c.execute("""
                     UPDATE vendor_devices 
                     SET last_active_at = ?, battery_level = ?, last_lat = ?, last_lng = ?
                     WHERE vendor_id = ? AND device_id = ?
                 """, (now, battery_level, lat, lng, vendor_id, device_id))
             except Exception as e:
                 logger.error(f"Error upserting vendor_device in heartbeat: {e}")
            
        conn.commit()
        
        # Emit real-time update
        payload = {
            "vendor_id": vendor_id,
            "device_id": device_id,
            "last_active_at": now.isoformat(),
            "battery_level": battery_level,
            "online": True
        }
        socketio.emit("device_health_update", payload, room=f"vendor_{vendor_id}")
        socketio.emit("device_health_update", payload, room="super_admin")
        
        conn.close()
        return jsonify({"status": "success", "geofence_status": geofence_status})
    except Exception as e:
        logger.error(f"Global error in mobile_heartbeat: {e}")
        return jsonify({"error": str(e)}), 500

@vendor_bp.route("/subject-master", methods=["GET"])
@vendor_required
def get_subject_master():
    from app import get_db_connection
    vendor_id = request.vendor_id
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, class_year, branch, subject_name FROM subject_master WHERE vendor_id = ? ORDER BY class_year, branch, subject_name", (vendor_id,))
        rows = c.fetchall() or []
        conn.close()
        items = []
        for r in rows:
             items.append({"id": r[0], "class_year": r[1], "branch": r[2], "subject_name": r[3]})
        return jsonify({"subjects": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@vendor_bp.route("/subject-master", methods=["POST"])
@vendor_required
def add_master_subject():
    from app import get_db_connection
    vendor_id = request.vendor_id
    data = request.json or {}
    class_year = str(data.get("class_year", "")).strip()
    branch = str(data.get("branch", "")).strip()
    subject_name = str(data.get("subject_name", "")).strip()
    if not subject_name:
        return jsonify({"error": "Subject name is required"}), 400
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Native UPSERT syntax works in both supported databases. Using an
        # explicit conflict target also keeps duplicate submissions idempotent.
        c.execute(
            """INSERT INTO subject_master (vendor_id, class_year, branch, subject_name)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(vendor_id, class_year, branch, subject_name) DO NOTHING""",
            (vendor_id, class_year, branch, subject_name),
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@vendor_bp.route("/subject-master/<int:sid>", methods=["DELETE"])
@vendor_required
def delete_master_subject(sid):
    from app import get_db_connection
    vendor_id = request.vendor_id
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM subject_master WHERE id = ? AND vendor_id = ?", (sid, vendor_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
