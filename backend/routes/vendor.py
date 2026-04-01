from flask import Blueprint, request, jsonify, send_file, send_from_directory
import sqlite3
import json
import base64
import os
import io
import time
from datetime import datetime, date, timedelta
from services.auth_service import authenticate_vendor_access, extract_token, verify_token
from utils import parse_db_date, cache_get, cache_set

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
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Missing Authorization Header"}), 401
        token = extract_token(auth_header)
        data = verify_token(token)
        if not data or data.get('role') not in ['super_admin', 'vendor_admin']:
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
            c.execute("""
                CREATE TABLE IF NOT EXISTS vendor_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_id INTEGER,
                    device_id TEXT,
                    device_name TEXT,
                    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_login_at DATETIME
                )
            """)
        except Exception:
            pass
        try:
            c.execute("UPDATE vendor_devices SET device_name = ?, last_login_at = ? WHERE vendor_id = ? AND device_id = ?", (slot_name, now, vendor_id, device_id))
            if c.rowcount == 0:
                c.execute("INSERT INTO vendor_devices (vendor_id, device_id, device_name, registered_at, last_login_at) VALUES (?, ?, ?, ?, ?)", (vendor_id, device_id, slot_name, now, now))
        except Exception:
            try:
                c.execute("INSERT INTO vendor_devices (vendor_id, device_id, device_name, registered_at, last_login_at) VALUES (?, ?, ?, ?, ?)", (vendor_id, device_id, slot_name, now, now))
            except Exception:
                pass
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
                except:
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
            except:
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
        # Ensure table
        c.execute("""CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            class_year TEXT,
            division TEXT,
            branch TEXT,
            label TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        if vendor_id:
            c.execute("SELECT id, class_year, division, branch, label FROM classes WHERE vendor_id = ? ORDER BY created_at DESC", (vendor_id,))
        else:
            c.execute("SELECT id, class_year, division, branch, label FROM classes ORDER BY created_at DESC")
        rows = c.fetchall() or []
        conn.close()
        items = []
        for r in rows:
            items.append({
                "id": r[0], "class_year": r[1], "division": r[2], "branch": r[3], "label": r[4]
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
    data = request.get_json(silent=True) or {}
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            class_year TEXT,
            division TEXT,
            branch TEXT,
            label TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("INSERT INTO classes (vendor_id, class_year, division, branch, label) VALUES (?, ?, ?, ?, ?)",
                  (vendor_id, str(data.get('class_year') or ''), str(data.get('division') or ''), str(data.get('branch') or ''), str(data.get('label') or '')))
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
    data = request.get_json(silent=True) or {}
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT vendor_id FROM classes WHERE id = ?", (cid,))
        row = c.fetchone()
        if not row or (vendor_id and int(row[0]) != int(vendor_id)):
            conn.close()
            return jsonify({"error": "not found"}), 404
        fields = []; params = []
        for k in ["class_year", "division", "branch", "label"]:
            if k in data:
                fields.append(f"{k} = ?"); params.append(str(data.get(k) or ''))
        if fields:
            params.append(cid)
            c.execute(f"UPDATE classes SET {', '.join(fields)} WHERE id = ?", params)
            conn.commit()
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
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM classes WHERE id = ? AND vendor_id = ?", (cid, vendor_id))
        conn.commit()
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
    
    # Only allow Admin (implicit via authenticate_vendor_access usually, but good to check role if needed)
    # Assuming authenticate_vendor_access checks for valid token.
    
    data = request.json
    allowance = data.get('allowance')
    deduction = data.get('deduction')
    
    if allowance is None and deduction is None:
        return jsonify({"error": "No settings provided"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        if allowance is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      ('global_late_allowance', str(allowance)))
            
        if deduction is not None:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", 
                      ('global_late_deduction', str(deduction)))
                      
        conn.commit()
        return jsonify({"status": "success", "message": "Global late settings updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@vendor_bp.route("/settings", methods=["GET"])
def get_settings():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    allowed_keys = {'threshold', 'cooldown', 'work_start_time', 'late_threshold', 'late_grace_period', 'auto_checkout', 'voice_greeting', 'admin_alerts'}
    auth_header = request.headers.get('Authorization')
    token_data = None
    if auth_header:
        try:
            token = auth_header.split(" ")[1]
            token_data = verify_token(token)
        except Exception:
            token_data = None
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT key, value FROM system_settings")
    rows = c.fetchall()
    conn.close()
    
    all_settings = {row['key']: row['value'] for row in rows}
    public_settings = {k: v for k, v in all_settings.items() if k in allowed_keys}
    if not token_data:
        return jsonify(public_settings)

    username = token_data.get('username')
    role = token_data.get('role')
    if role == 'super_admin':
        return jsonify(public_settings)
    if role != 'vendor_admin':
        return jsonify(public_settings)

    vendor_id = None
    try:
        conn_u = get_db_connection()
        conn_u.row_factory = sqlite3.Row
        cu = conn_u.cursor()
        cu.execute("SELECT vendor_id FROM system_users WHERE username = ?", (username,))
        ur = cu.fetchone()
        vendor_id = ur['vendor_id'] if ur else None
        conn_u.close()
    except Exception:
        try:
            conn_u.close()
        except Exception:
            pass
        vendor_id = None

    if not vendor_id:
        return jsonify(public_settings)

    effective = dict(public_settings)
    for k in allowed_keys:
        vkey = f"{k}_vendor_{vendor_id}"
        if vkey in all_settings and all_settings[vkey] is not None and str(all_settings[vkey]).strip() != "":
            effective[k] = all_settings[vkey]
    return jsonify(effective)


@vendor_bp.route("/settings", methods=["POST"])
def update_settings():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401
    try:
        token = auth_header.split(" ")[1]
        token_data = verify_token(token)
    except Exception:
        token_data = None
    if not token_data:
        return jsonify({"error": "Invalid or Expired Token"}), 401

    allowed_keys = {'threshold', 'cooldown', 'work_start_time', 'late_threshold', 'late_grace_period', 'auto_checkout', 'voice_greeting', 'admin_alerts'}
    data = request.json or {}
    role = token_data.get('role')
    username = token_data.get('username')
    vendor_id = None
    if role == 'vendor_admin':
        try:
            conn_u = get_db_connection()
            conn_u.row_factory = sqlite3.Row
            cu = conn_u.cursor()
            cu.execute("SELECT vendor_id FROM system_users WHERE username = ?", (username,))
            ur = cu.fetchone()
            vendor_id = ur['vendor_id'] if ur else None
            conn_u.close()
        except Exception:
            try:
                conn_u.close()
            except Exception:
                pass
            vendor_id = None
        if not vendor_id:
            return jsonify({"error": "Vendor Context Required"}), 400
    elif role != 'super_admin':
        return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    c = conn.cursor()
    try:
        for key, value in data.items():
            if key not in allowed_keys:
                continue
            store_key = key
            if role == 'vendor_admin' and vendor_id:
                store_key = f"{key}_vendor_{vendor_id}"
            # Ensure value is string
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
def create_user():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    return register_user() # Reuse register logic


@vendor_bp.route("/users/<username>", methods=["PUT"])
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
            updates.append("password = ?")
            params.append(password)
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
    from app import latest_frames, client_counts, device_status
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

@vendor_bp.route("/mobile/heartbeat", methods=["POST"])
def mobile_heartbeat():
    from app import get_db_connection, socketio
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json or {}
    device_id = data.get("device_id")
    battery_level = data.get("battery_level")
    
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
        c = conn.cursor()
        now = datetime.now()
        
        # Update device health
        c.execute("""
            UPDATE vendor_devices 
            SET last_active_at = ?, battery_level = ? 
            WHERE vendor_id = ? AND device_id = ?
        """, (now, battery_level, vendor_id, device_id))
        
        conn.commit()
        
        # Emit real-time update
        payload = {
            "vendor_id": vendor_id,
            "device_id": device_id,
            "last_active_at": now.isoformat(),
            "battery_level": battery_level,
            "status": "online"
        }
        socketio.emit("device_health_update", payload, room=f"vendor_{vendor_id}")
        socketio.emit("device_health_update", payload, room="super_admin")
        
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
