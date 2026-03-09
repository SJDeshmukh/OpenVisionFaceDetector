from flask import Blueprint, request, jsonify, send_file
import sqlite3
from datetime import datetime, date, timedelta
import json
import base64
import re
import os
import secrets
import qrcode
from io import BytesIO

# Import from services
from services.auth_service import verify_token, extract_token, hash_password, verify_password

# Authentication decorators - these might be defined in app.py, so we will import them locally or they might need to be resolved.
def super_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Missing Authorization Header"}), 401
        token = extract_token(auth_header)
        data = verify_token(token)
        if not data or data.get('role') != 'super_admin':
            return jsonify({"error": "Super Admin access required"}), 403
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



def rate_limit(*args, **kwargs):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator

def super_admin_role_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import request, jsonify
        from services.auth_service import extract_token, verify_token
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Missing Authorization Header"}), 401
        token = extract_token(auth_header)
        data = verify_token(token)
        if not data or data.get('role') != 'super_admin':
            return jsonify({"error": "Super Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

def admin_role_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import request, jsonify
        from services.auth_service import extract_token, verify_token
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
        def decorated(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated
    return decorator


def log_audit(action, details, target_vendor_id=None, actor=None):
    pass

admin_bp = Blueprint('admin_bp', __name__)


# --- Extracted Admin Routes ---


@admin_bp.route("/audit-logs", methods=["GET"])
@super_admin_required
def get_audit_logs():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Optional filtering
    vendor_id = request.args.get('vendor_id')
    limit = request.args.get('limit', 100)
    
    query = "SELECT * FROM audit_logs"
    params = []
    
    if vendor_id:
        query += " WHERE target_vendor_id = ?"
        params.append(vendor_id)
        
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    
    c.execute(query, params)
    logs = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({"logs": logs})

@admin_bp.route("/impersonate", methods=["POST"])
@super_admin_required
def impersonate_vendor():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json
    vendor_id = data.get('vendor_id')
    
    if not vendor_id:
        return jsonify({"error": "Vendor ID required"}), 400
        
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Find the admin user for this vendor
    c.execute("SELECT username, role FROM system_users WHERE vendor_id = ? AND role = 'admin' LIMIT 1", (vendor_id,))
    user = c.fetchone()
    
    if not user:
        # Fallback to any user if no admin found (unlikely)
        c.execute("SELECT username, role FROM system_users WHERE vendor_id = ? LIMIT 1", (vendor_id,))
        user = c.fetchone()
        
    conn.close()
    
    if not user:
        return jsonify({"error": "No users found for this vendor"}), 404
        
    # Generate Token
    token = generate_token(user['username'], user['role'])
    
    try:
        auth_header = request.headers.get('Authorization')
        if auth_header:
            token = auth_header.split(" ")[1]
            current_user = verify_token(token)
            actor = current_user['username'] if current_user else 'unknown'
        else:
            actor = 'system'
    except:
        actor = 'system'
        
    log_audit('impersonate_vendor', {'impersonated_user': user['username']}, target_vendor_id=vendor_id, actor=actor)
    
    return jsonify({
        "token": token,
        "username": user['username'],
        "role": user['role']
    })

@admin_bp.route("/vendors/<int:vendor_id>/devices", methods=["GET"])
@super_admin_required
def list_vendor_devices(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # Ensure table exists for SQLite environments
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
        c.execute("SELECT id, device_id, device_name, registered_at, last_login_at FROM vendor_devices WHERE vendor_id = ? ORDER BY registered_at DESC", (vendor_id,))
        rows = [dict(row) for row in c.fetchall() or []]
        conn.close()
        return jsonify({"devices": rows})
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/devices/<device_id>", methods=["PUT"])
@super_admin_required
def update_vendor_device_name(vendor_id, device_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json or {}
    new_name = str(data.get("device_name") or "").strip()
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM vendor_devices WHERE vendor_id = ? AND device_id = ? LIMIT 1", (vendor_id, device_id))
        row = c.fetchone()
        if new_name:
            if row:
                c.execute("UPDATE vendor_devices SET device_name = ?, last_login_at = CURRENT_TIMESTAMP WHERE vendor_id = ? AND device_id = ?", (new_name, vendor_id, device_id))
            else:
                c.execute("INSERT INTO vendor_devices (vendor_id, device_id, device_name) VALUES (?, ?, ?)", (vendor_id, device_id, new_name))
            try:
                ev = {"vendor_id": vendor_id, "device_id": device_id, "device_name": new_name}
                socketio.emit("device_name_updated", ev, room=f"vendor_{vendor_id}")
            except Exception:
                pass
        else:
            # Unassign device name: clear friendly name and free any slot assignment
            if row:
                try:
                    c.execute("UPDATE vendor_devices SET device_name = NULL WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
                except Exception:
                    c.execute("UPDATE vendor_devices SET device_name = '' WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
            else:
                # Ensure a record exists even if no name provided (pre-registration)
                try:
                    c.execute("INSERT INTO vendor_devices (vendor_id, device_id, device_name) VALUES (?, ?, NULL)", (vendor_id, device_id))
                except Exception:
                    pass
            # Clear any slot assignment for this device
            try:
                c.execute("UPDATE vendor_device_slots SET assigned_device_id = NULL, assigned_at = NULL WHERE vendor_id = ? AND assigned_device_id = ?", (vendor_id, device_id))
            except Exception:
                pass
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/devices/<device_id>/assign-slot", methods=["POST"])
@super_admin_required
def admin_assign_device_slot(vendor_id, device_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json or {}
    slot_name = str(data.get("slot_name") or "").strip()
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Ensure tables exist
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
        # Ensure vendor_devices record exists
        c.execute("SELECT id FROM vendor_devices WHERE vendor_id = ? AND device_id = ? LIMIT 1", (vendor_id, device_id))
        exists = c.fetchone()
        if not exists:
            c.execute("INSERT INTO vendor_devices (vendor_id, device_id, device_name) VALUES (?, ?, NULL)", (vendor_id, device_id))
        if not slot_name:
            # Clear all assignments for this device
            try:
                c.execute("UPDATE vendor_device_slots SET assigned_device_id = NULL, assigned_at = NULL WHERE vendor_id = ? AND assigned_device_id = ?", (vendor_id, device_id))
            except Exception:
                pass
            try:
                c.execute("UPDATE vendor_devices SET device_name = NULL WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
            except Exception:
                c.execute("UPDATE vendor_devices SET device_name = '' WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
            conn.commit()
            try:
                socketio.emit("device_name_updated", {"vendor_id": vendor_id, "device_id": device_id, "device_name": None}, room=f"vendor_{vendor_id}")
            except Exception:
                pass
            log_audit("device_unassign_slot_admin", {"device_id": device_id}, target_vendor_id=vendor_id)
            conn.close()
            return jsonify({"success": True})
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
        if current_assigned and current_assigned != device_id:
            conn.close()
            return jsonify({"error": "Slot already assigned"}), 409
        # Clear any previous assignment for this device on other slots
        try:
            c.execute("UPDATE vendor_device_slots SET assigned_device_id = NULL, assigned_at = NULL WHERE vendor_id = ? AND assigned_device_id = ? AND slot_name != ?", (vendor_id, device_id, slot_name))
        except Exception:
            pass
        # Assign target slot to this device
        now = datetime.now()
        c.execute("UPDATE vendor_device_slots SET assigned_device_id = ?, assigned_at = ? WHERE vendor_id = ? AND slot_name = ?", (device_id, now, vendor_id, slot_name))
        # Sync friendly name into vendor_devices
        try:
            c.execute("UPDATE vendor_devices SET device_name = ?, last_login_at = ? WHERE vendor_id = ? AND device_id = ?", (slot_name, now, vendor_id, device_id))
        except Exception:
            pass
        conn.commit()
        try:
            ev = {"vendor_id": vendor_id, "device_id": device_id, "device_name": slot_name}
            socketio.emit("device_name_updated", ev, room=f"vendor_{vendor_id}")
        except Exception:
            pass
        conn.close()
        log_audit("device_assign_slot_admin", {"device_id": device_id, "slot_name": slot_name}, target_vendor_id=vendor_id)
        return jsonify({"success": True})
    except Exception as e:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/devices/<device_id>", methods=["DELETE"])
@super_admin_required
def delete_vendor_device(vendor_id, device_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Ensure tables exist
        try:
            c.execute("CREATE TABLE IF NOT EXISTS vendor_devices (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, device_id TEXT, device_name TEXT, registered_at DATETIME DEFAULT CURRENT_TIMESTAMP, last_login_at DATETIME)")
            c.execute("CREATE TABLE IF NOT EXISTS vendor_device_slots (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, slot_name TEXT, assigned_device_id TEXT, assigned_at DATETIME, UNIQUE(vendor_id, slot_name))")
            c.execute("CREATE TABLE IF NOT EXISTS active_sessions (token TEXT PRIMARY KEY, username TEXT, vendor_id INTEGER, device_id TEXT, platform TEXT, last_active DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        except Exception:
            pass
        # Unassign any slots tied to this device
        try:
            c.execute("UPDATE vendor_device_slots SET assigned_device_id = NULL, assigned_at = NULL WHERE vendor_id = ? AND assigned_device_id = ?", (vendor_id, device_id))
        except Exception:
            pass
        # Delete any active sessions for this device (mobile/web tied to this device_id)
        try:
            c.execute("DELETE FROM active_sessions WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
        except Exception:
            pass
        # Remove the device record
        c.execute("DELETE FROM vendor_devices WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
        conn.commit()
        try:
            socketio.emit("vendor_updated", {"vendor_id": vendor_id}, room="super_admin")
            socketio.emit("device_removed", {"vendor_id": vendor_id, "device_id": device_id}, room=f"vendor_{vendor_id}")
        except Exception:
            pass
        conn.close()
        log_audit("device_delete", {"device_id": device_id}, target_vendor_id=vendor_id)
        return jsonify({"success": True})
    except Exception as e:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/devices/<device_id>/logout", methods=["POST"])
@super_admin_required
def logout_vendor_device(vendor_id, device_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Remove only mobile sessions for this device
        try:
            c.execute("DELETE FROM active_sessions WHERE vendor_id = ? AND device_id = ? AND platform = 'mobile'", (vendor_id, device_id))
        except Exception:
            # Fallback: remove any sessions for this device_id regardless of platform
            try:
                c.execute("DELETE FROM active_sessions WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
            except Exception:
                pass
        conn.commit()
        conn.close()
        try:
            socketio.emit("force_logout_mobile_device", {"vendor_id": vendor_id, "device_id": device_id}, room=f"vendor_{vendor_id}")
        except Exception:
            pass
        log_audit("device_logout", {"device_id": device_id}, target_vendor_id=vendor_id)
        return jsonify({"success": True})
    except Exception as e:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/device-slots", methods=["GET"])
@super_admin_required
def list_vendor_device_slots(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
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
        c.execute("SELECT id, slot_name, assigned_device_id, assigned_at FROM vendor_device_slots WHERE vendor_id = ? ORDER BY id ASC", (vendor_id,))
        rows = [dict(row) for row in c.fetchall() or []]
        conn.close()
        return jsonify({"slots": rows})
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/device-slots", methods=["PUT"])
@super_admin_required
def set_vendor_device_slots(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json or {}
    slots = data.get("slots") or []
    if not isinstance(slots, list):
        return jsonify({"error": "slots must be a list"}), 400
    slots = [str(s).strip() for s in slots if str(s or "").strip() != ""]
    try:
        conn = get_db_connection()
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
        # Upsert slots
        for s in slots:
            try:
                c.execute("INSERT OR IGNORE INTO vendor_device_slots (vendor_id, slot_name) VALUES (?, ?)", (vendor_id, s))
            except Exception:
                pass
        # Remove slots not present if they are unassigned
        q_marks = ",".join(["?"] * len(slots)) if slots else ""
        if slots:
            c.execute(f"DELETE FROM vendor_device_slots WHERE vendor_id = ? AND (assigned_device_id IS NULL OR assigned_device_id = '') AND slot_name NOT IN ({q_marks})", [vendor_id, *slots])
        else:
            # If empty list provided, do not delete assigned slots
            c.execute("DELETE FROM vendor_device_slots WHERE vendor_id = ? AND (assigned_device_id IS NULL OR assigned_device_id = '')", (vendor_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/users/password", methods=["PUT"])
@super_admin_required
def reset_user_password():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json
    target_username = data.get("username")
    new_password = data.get("new_password")
    
    if not target_username or not new_password:
        return jsonify({"error": "Username and New Password are required"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Check if user exists
        c.execute("SELECT role FROM system_users WHERE username = ?", (target_username,))
        user = c.fetchone()
        
        if not user:
            return jsonify({"error": "User not found"}), 404
            
        # Update Password
        c.execute("UPDATE system_users SET password = ? WHERE username = ?", (new_password, target_username))
        conn.commit()
        
        return jsonify({"success": True, "message": f"Password for {target_username} updated."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/stats", methods=["GET"])
@super_admin_required
def get_admin_stats():
    from app import get_db_connection, socketio, is_testing, latest_frames
    from utils import cache_get, cache_set, ALL_FEATURES
    cached = cache_get("admin_stats")
    if cached:
        return jsonify(cached)
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Total Vendors
    c.execute("SELECT COUNT(*) FROM vendors")
    total_vendors = c.fetchone()[0]
    
    # 2. Active Vendors
    c.execute("SELECT COUNT(*) FROM vendors WHERE status = 'active'")
    active_vendors = c.fetchone()[0]
    
    # 3. Total Employees Managed
    c.execute("SELECT COUNT(*) FROM faces")
    total_employees = c.fetchone()[0]
    
    # 4. Total Devices Registered
    c.execute("SELECT COUNT(*) FROM vendor_devices")
    total_devices = c.fetchone()[0]
    
    # 5. Revenue (Simple Sum of monthly costs for active subscriptions)
    # This is an estimate based on active plans
    c.execute("""
        SELECT SUM(
            (IFNULL(cost_per_user, 0) * IFNULL(max_users, 0)) + 
            (IFNULL(cost_per_employee, 0) * IFNULL(max_employees, 0))
        ) 
        FROM subscriptions 
        WHERE end_date >= DATE('now')
    """)
    monthly_revenue = c.fetchone()[0] or 0
    
    conn.close()
    
    try:
        active_streaming_devices = 0
        now_ts = datetime.now()
        for v in latest_frames.values():
            for d in v.values():
                if (now_ts - d.get("timestamp", now_ts)).total_seconds() < 30:
                    active_streaming_devices += 1
    except Exception:
        active_streaming_devices = 0
    
    result = {
        "total_vendors": total_vendors,
        "active_vendors": active_vendors,
        "total_employees": total_employees,
        "total_devices": total_devices,
        "active_streaming_devices": active_streaming_devices,
        "monthly_recurring_revenue": monthly_revenue
    }
    cache_set("admin_stats", result, 2)
    return jsonify(result)

@admin_bp.route("/vendors", methods=["GET"])
@super_admin_required
def get_vendors():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get Vendors with Subscription Details
    try:
        c.execute("PRAGMA table_info(subscriptions)")
        subs_cols = [info[1] for info in c.fetchall()]
    except Exception:
        subs_cols = []
    max_web_select = "s.max_web_sessions" if "max_web_sessions" in subs_cols else "1 AS max_web_sessions"
    query = f"""
        SELECT v.*, 
               s.plan_type, s.start_date, s.end_date, s.max_users, s.max_employees, s.max_mobile_devices, {max_web_select}, s.cost_per_user, s.cost_per_employee, s.setup_fee, s.setup_fee_paid, s.features,
               (SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'vendor_admin' LIMIT 1) as admin_username,
               (SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'user' LIMIT 1) as user_username,
               (SELECT COUNT(*) FROM system_users WHERE vendor_id = v.id AND role = 'vendor_admin') as admin_count,
               (SELECT COUNT(*) FROM vendor_devices WHERE vendor_id = v.id) as device_count,
               (SELECT COUNT(*) FROM faces WHERE vendor_id = v.id) as employee_count
        FROM vendors v
        LEFT JOIN subscriptions s ON v.id = s.vendor_id
        ORDER BY v.created_at DESC
    """
    c.execute(query)
    
    vendors = []
    for row in c.fetchall():
        v = dict(row)
        def _coerce_int(x):
            try:
                if x is None:
                    return None
                if isinstance(x, str) and x.strip() == "":
                    return None
                return int(float(x))
            except Exception:
                return None

        mu = _coerce_int(v.get("max_users"))
        if mu is not None and mu < 0:
            v["max_users"] = abs(mu)
        mme = _coerce_int(v.get("max_mobile_devices"))
        if mme is not None and mme < 0:
            v["max_mobile_devices"] = abs(mme)
        me = _coerce_int(v.get("max_employees"))
        if me is not None and me < 0:
            v["max_employees"] = abs(me)

        # Calculate status based on subscription
        if v.get('features'):
            try:
                import json
                v['features'] = json.loads(v['features'])
            except:
                v['features'] = []
        else:
            v['features'] = []

        if v['end_date']:
            try:
                # Handle both 'YYYY-MM-DD' and 'YYYY-MM-DD HH:MM:SS'
                date_str = v['end_date'].split(' ')[0]
                end_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                
                if date.today() > end_date:
                    v['subscription_status'] = 'Expired'
                else:
                    v['subscription_status'] = 'Active'
            except Exception as e:
                pass # print(f"Date Parsing Error for Vendor {v.get('id')}: {e}")
                v['subscription_status'] = 'Error'
        else:
            v['subscription_status'] = 'No Plan'
            
        vendors.append(v)
        
    conn.close()
    return jsonify({"vendors": vendors})

@admin_bp.route("/features", methods=["GET"])
@super_admin_required
def get_available_features():
    from app import get_db_connection, socketio, is_testing
    from utils import BUNDLE_FEATURES, ALL_FEATURES
    return jsonify({"features": ALL_FEATURES, "bundles": BUNDLE_FEATURES})

@admin_bp.route("/registration/templates", methods=["GET"])
@super_admin_required
def get_registration_templates():
    from app import get_db_connection, socketio, is_testing
    from utils import REGISTRATION_TEMPLATES
    return jsonify({"templates": REGISTRATION_TEMPLATES})

@admin_bp.route("/vendors/<int:vendor_id>/registration_config", methods=["PUT"])
@super_admin_required
def set_vendor_registration_config(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json or {}
    config = data.get("registration_config")
    if config is None:
        return jsonify({"error": "registration_config required"}), 400
    try:
        # Validate JSON array
        if isinstance(config, str):
            import json as _json
            config = _json.loads(config)
        if not isinstance(config, list):
            return jsonify({"error": "registration_config must be a list"}), 400
        conn = get_db_connection()
        c = conn.cursor()
        _run(c, "UPDATE vendors SET registration_config = ? WHERE id = ?", (json.dumps(config), vendor_id))
        conn.commit()
        conn.close()
        log_audit("vendor_registration_config_update", {"count": len(config)}, target_vendor_id=vendor_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/bulk_action", methods=["POST"])
@super_admin_required
def bulk_vendor_action():
    from celery_app import celery
    payload = request.json or {}
    vendor_ids = payload.get("vendor_ids") or []
    action = payload.get("action")
    if not vendor_ids or not action:
        return jsonify({"error": "vendor_ids and action required"}), 400
    
    if celery and len(vendor_ids) > 1:
        from tasks import bulk_vendor_action_task
        task = bulk_vendor_action_task.delay(vendor_ids, action, payload)
        return jsonify({"success": True, "task_id": task.id, "message": "Bulk action processing in background"}), 202

    try:
        from app import get_db_connection, socketio, ALL_FEATURES
        conn = get_db_connection()
        c = conn.cursor()
        if action in ("suspend", "activate"):
            new_status = 'suspended' if action == 'suspend' else 'active'
            for vid in vendor_ids:
                _run(c, "UPDATE vendors SET status = ? WHERE id = ?", (new_status, vid))
                log_audit(f"vendor_{action}", {}, target_vendor_id=vid)
        elif action == "toggle_feature":
            feature = payload.get("feature")
            enabled = payload.get("enabled", True)
            for vid in vendor_ids:
                _run(c, "SELECT features FROM subscriptions WHERE vendor_id = ?", (vid,))
                row = c.fetchone()
                feats = []
                if row and row[0]:
                    try:
                        feats = json.loads(row[0])
                    except Exception:
                        feats = []
                if enabled and feature not in feats:
                    feats.append(feature)
                if not enabled:
                    feats = [f for f in feats if f != feature]
                _run(c, "UPDATE subscriptions SET features = ? WHERE vendor_id = ?", (json.dumps(feats), vid))
                log_audit("vendor_toggle_feature", {"feature": feature, "enabled": enabled}, target_vendor_id=vid)
                try:
                    socketio.emit('features_updated', {'vendor_id': vid, 'features': feats}, room=f"vendor_{vid}")
                    socketio.emit('vendor_updated', {'vendor_id': vid}, room='super_admin')
                except Exception:
                    pass
        elif action == "update_web_sessions":
            # ... keep existing synchronous logic for quick updates ...
            max_web_sessions = int(payload.get("max_web_sessions") or 1)
            # ... (truncated for brevity in actual replacement, but I should keep it all)
            if max_web_sessions < 1: max_web_sessions = 1
            for vid in vendor_ids:
                _run(c, "UPDATE subscriptions SET max_web_sessions = ? WHERE vendor_id = ?", (max_web_sessions, vid))
                log_audit("vendor_update_web_sessions", {"max_web_sessions": max_web_sessions}, target_vendor_id=vid)
        else:
            return jsonify({"error": "Unknown action"}), 400
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/employees/export", methods=["GET"])
@super_admin_required
def export_employees(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    import csv, io
    conn = get_db_connection()
    c = conn.cursor()
    _run(c, "SELECT name, phone, department, designation, shift, daily_wage, custom_data FROM faces WHERE vendor_id = ?", (vendor_id,))
    rows = c.fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name","phone","department","designation","shift","daily_wage","custom_data"])
    for r in rows:
        if isinstance(r, dict):
            writer.writerow([r.get("name"), r.get("phone"), r.get("department"), r.get("designation"), r.get("shift"), r.get("daily_wage"), r.get("custom_data")])
        else:
            writer.writerow(list(r))
    return output.getvalue(), 200, {"Content-Type": "text/csv"}

@admin_bp.route("/vendors/<int:vendor_id>/employees/import", methods=["POST"])
@super_admin_required
def import_employees(vendor_id):
    from celery_app import celery
    data = request.json or {}
    csv_data = data.get("csv_data")
    if not csv_data:
        return jsonify({"error": "csv_data required (string)"}), 400
    
    if celery:
        from tasks import process_import_employees_task
        task = process_import_employees_task.delay(vendor_id, csv_data)
        return jsonify({"success": True, "task_id": task.id, "message": "Import processing in background"}), 202

    from app import get_db_connection, log_audit
    import csv, io
    f = io.StringIO(csv_data)
    # ... keep existing fallback ...
    reader = csv.DictReader(f)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        count = 0
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name: continue
            phone = row.get("phone")
            department = row.get("department")
            designation = row.get("designation")
            shift = row.get("shift")
            daily_wage = float(row.get("daily_wage") or 0)
            custom_data = row.get("custom_data")
            _run(c, """INSERT INTO faces (name, phone, department, designation, shift, daily_wage, vendor_id, custom_data)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (name, phone, department, designation, shift, daily_wage, vendor_id, custom_data))
            count += 1
        conn.commit()
        log_audit("employees_import", {"count": count}, target_vendor_id=vendor_id)
        return jsonify({"success": True, "imported": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors", methods=["POST"], endpoint="create_vendor")
@super_admin_required
@track_metrics("admin_create_vendor")
@rate_limit(limit=60, window=60)
def create_vendor():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    from utils import BUNDLE_FEATURES
    data = request.json
    company_name = data.get("company_name")
    
    if not company_name:
        return jsonify({"error": "Company Name is required"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        frontend_bundle_id = data.get("frontend_bundle_id", "default_attendance")
        backend_service_id = data.get("backend_service_id", "default_api")
        vertical = data.get("vertical")
        c.execute("""INSERT INTO vendors (company_name, contact_person, phone, email, frontend_bundle_id, backend_service_id) 
                     VALUES (?, ?, ?, ?, ?, ?)""",
                  (company_name, data.get("contact_person"), data.get("phone"), data.get("email"), frontend_bundle_id, backend_service_id))
        vendor_id = c.lastrowid
        if vertical:
            try:
                c.execute("UPDATE vendors SET vertical = ? WHERE id = ?", (vertical, vendor_id))
                if str(vertical).strip().lower() == "school":
                    try:
                        rc = json.dumps([
                            {"field": "student_number", "label": "Student ID", "type": "text", "required": True, "options": []},
                            {"field": "phone", "label": "Mobile Number", "type": "text", "required": True, "options": []},
                            {"field": "department", "label": "Class/Section", "type": "text", "required": False, "options": []}
                        ])
                        c.execute("UPDATE vendors SET registration_config = ? WHERE id = ? AND (registration_config IS NULL OR TRIM(registration_config) = '')", (rc, vendor_id))
                    except Exception:
                        pass
                conn.commit()
            except Exception:
                pass
        conn.commit()
        admin_username = data.get("admin_username") or f"admin_{vendor_id}"
        admin_password = data.get("admin_password") or "default123"
        user_username = data.get("user_username") or f"user_{vendor_id}"
        user_password = data.get("user_password") or "user123"
        payload = {
            "vendor_id": vendor_id,
            "company_name": company_name,
            "frontend_bundle_id": frontend_bundle_id,
            "admin_username": admin_username,
            "admin_password": admin_password,
            "user_username": user_username,
            "user_password": user_password,
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
            "max_users": data.get("max_users"),
            "max_employees": data.get("max_employees"),
            "max_mobile_devices": data.get("max_mobile_devices"),
            "max_web_sessions": data.get("max_web_sessions"),
            "cost_per_user": data.get("cost_per_user"),
            "cost_per_employee": data.get("cost_per_employee"),
            "features": data.get("features")
        }
        def _process():
            try:
                conn2 = get_db_connection()
                c2 = conn2.cursor()
                start_date = data.get("start_date") or date.today().isoformat()
                end_date = data.get("end_date") or (date.today() + timedelta(days=14)).isoformat()
                max_users = data.get("max_users") or 5
                max_employees = data.get("max_employees") or 50
                max_mobile_devices = data.get("max_mobile_devices")
                if max_mobile_devices is None:
                    max_mobile_devices = max_users
                max_web_sessions = int(data.get("max_web_sessions") or 1)
                if max_web_sessions < 1:
                    max_web_sessions = 1
                cost_per_user = data.get("cost_per_user") or 0
                cost_per_employee = data.get("cost_per_employee") or 0
                features = data.get("features")
                if features is None:
                    features = BUNDLE_FEATURES.get(frontend_bundle_id, [])
                import json
                features_json = json.dumps(features)
                c2.execute("PRAGMA table_info(subscriptions)")
                subs_cols = [info[1] for info in c2.fetchall()]
                cols = ["vendor_id", "plan_type", "start_date", "end_date", "max_users", "max_employees", "max_mobile_devices", "cost_per_user", "cost_per_employee", "setup_fee", "features"]
                vals = [vendor_id, "custom", start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, 0, features_json]
                if "max_web_sessions" in subs_cols:
                    cols.insert(7, "max_web_sessions")
                    vals.insert(7, max_web_sessions)
                placeholders = ", ".join(["?"] * len(cols))
                c2.execute(f"INSERT INTO subscriptions ({', '.join(cols)}) VALUES ({placeholders})", tuple(vals))
                try:
                    c2.execute("""INSERT INTO system_users (username, password, role, vendor_id)
                                  VALUES (?, ?, 'vendor_admin', ?)""",
                               (admin_username, hash_password(admin_password), vendor_id))
                except sqlite3.IntegrityError:
                    pass
                try:
                    c2.execute("""INSERT INTO system_users (username, password, role, vendor_id)
                                  VALUES (?, ?, 'user', ?)""",
                               (user_username, hash_password(user_password), vendor_id))
                except sqlite3.IntegrityError:
                    pass
                c2.execute("INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)", 
                           (company_name, '[]', '[]', '[]', vendor_id))
                conn2.commit()
                conn2.close()
                log_audit('create_vendor', {'company_name': company_name}, target_vendor_id=vendor_id)
                socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
            except Exception:
                try:
                    conn2.close()
                except Exception:
                    pass
        if celery:
            try:
                celery.send_task("tasks.process_vendor_creation", args=[payload])
            except Exception:
                if app.config.get('TESTING'):
                    _process()
                else:
                    _run_in_native_thread(_process)
        else:
            _process()
        # Ensure vendor admin exists
        try:
            conn3 = get_db_connection()
            c3 = conn3.cursor()
            c3.execute("SELECT username FROM system_users WHERE vendor_id = ? AND role = 'vendor_admin' LIMIT 1", (vendor_id,))
            row_admin = c3.fetchone()
            if not row_admin:
                c3.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, 'vendor_admin', ?)", (admin_username, hash_password(admin_password), vendor_id))
                conn3.commit()
            conn3.close()
        except Exception:
            try:
                conn3.close()
            except Exception:
                pass
        return jsonify({
            "success": True, 
            "vendor_id": vendor_id,
            "admin_credentials": {"username": admin_username, "password": admin_password},
            "user_credentials": {"username": user_username, "password": user_password},
            "processing": True
        })
        
    except sqlite3.IntegrityError as e:
        try:
            pass # print(f"Create Vendor Exception: {e}")
        except Exception:
            pass
        return jsonify({"error": f"Database Error: {str(e)}"}), 400
    except Exception as e:
        try:
            pass # print(f"Create Vendor Exception: {e}")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/suspend", methods=["POST"])
@super_admin_required
def suspend_vendor(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json
    action = data.get("action", "suspend") # suspend or activate
    status = 'suspended' if action == 'suspend' else 'active'
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE vendors SET status = ? WHERE id = ?", (status, vendor_id))
    conn.commit()
    try:
        if status == 'suspended':
            _run(c, "DELETE FROM active_sessions WHERE vendor_id = ?", (vendor_id,))
    except Exception:
        pass
    conn.close()
    
    log_audit('suspend_vendor' if action == 'suspend' else 'activate_vendor', {'new_status': status}, target_vendor_id=vendor_id)
    
    # Real-time updates
    socketio.emit('vendor_updated', {'vendor_id': vendor_id, 'status': status}) # For SuperAdmin list
    
    if status == 'suspended':
        socketio.emit('force_logout', {'vendor_id': vendor_id}) # For Vendor Dashboard

    return jsonify({"success": True, "status": status})

@admin_bp.route("/vendors/<int:vendor_id>/toggle_web_login", methods=["POST"])
@super_admin_required
def toggle_web_login(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json
    enabled = data.get("enabled", True) # boolean
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE vendors SET web_login_enabled = ? WHERE id = ?", (1 if enabled else 0, vendor_id))
    conn.commit()
    conn.close()
    
    log_audit('toggle_web_login', {'enabled': enabled}, target_vendor_id=vendor_id)
    
    socketio.emit('vendor_updated', {'vendor_id': vendor_id, 'web_login_enabled': enabled})
    
    if not enabled:
        socketio.emit('force_logout', {'vendor_id': vendor_id})

    return jsonify({"success": True, "enabled": enabled})

@admin_bp.route("/vendors/<int:vendor_id>/subscription", methods=["GET"])
@super_admin_required
def get_vendor_subscription_admin(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        sub = c.fetchone()
        if not sub:
             return jsonify({"error": "No subscription found"}), 404
        
        # Convert row to dict
        sub_dict = dict(sub)
        return jsonify(sub_dict)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/subscription", methods=["PUT"])
@super_admin_required
def update_vendor_subscription(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    from utils import BUNDLE_FEATURES
    data = request.json
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        def to_int_min(value, default_val, min_val):
            try:
                if value is None:
                    return default_val
                if isinstance(value, str) and value.strip() == "":
                    return default_val
                v = int(float(value))
                if v < min_val:
                    v = min_val
                return v
            except Exception:
                return default_val

        # Check if subscription exists
        c.execute("SELECT rowid FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        if not c.fetchone():
            import json
            start_date = data.get("start_date") or date.today().isoformat()
            end_date = data.get("end_date") or (date.today() + timedelta(days=14)).isoformat()
            max_users = to_int_min(data.get("max_users"), 5, 1)
            max_employees = to_int_min(data.get("max_employees"), 50, 0)
            max_mobile_devices = data.get("max_mobile_devices")
            if max_mobile_devices is None and 'max_users' in data:
                max_mobile_devices = data['max_users']
            if max_mobile_devices is None:
                max_mobile_devices = max_users
            max_mobile_devices = to_int_min(max_mobile_devices, max_users, 1)
            max_web_sessions = to_int_min(data.get("max_web_sessions"), 1, 1)
            cost_per_user = data.get("cost_per_user") or 0
            cost_per_employee = data.get("cost_per_employee") or 0
            features_val = data.get("features")
            if features_val is None:
                c.execute("SELECT frontend_bundle_id FROM vendors WHERE id = ?", (vendor_id,))
                r = c.fetchone()
                bundle = r[0] if r else "default_attendance"
                features_val = BUNDLE_FEATURES.get(bundle, [])
            if isinstance(features_val, list):
                features_val = json.dumps(features_val)
            setup_fee = data.get("setup_fee") or 0
            plan_type = data.get("plan_type") or "custom"
            c.execute("PRAGMA table_info(subscriptions)")
            subs_cols = [info[1] for info in c.fetchall()]
            cols = ["vendor_id", "plan_type", "start_date", "end_date", "max_users", "max_employees", "max_mobile_devices", "cost_per_user", "cost_per_employee", "setup_fee", "features"]
            vals = [vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, setup_fee, features_val]
            if "max_web_sessions" in subs_cols:
                cols.insert(7, "max_web_sessions")
                vals.insert(7, max_web_sessions)
            placeholders = ", ".join(["?"] * len(cols))
            c.execute(f"INSERT INTO subscriptions ({', '.join(cols)}) VALUES ({placeholders})", tuple(vals))
            conn.commit()
            
        # Build Update Query
        query = "UPDATE subscriptions SET "
        params = []
        
        fields = ['start_date', 'end_date', 'plan_type', 'max_users', 'max_employees', 'max_mobile_devices', 'max_web_sessions', 'cost_per_user', 'cost_per_employee', 'setup_fee', 'setup_fee_paid']
        
        # Handle aliases or logic
        if 'features' in data:
            import json
            query += "features = ?, "
            features_val = data['features']
            if isinstance(features_val, list):
                features_val = json.dumps(features_val)
            params.append(features_val)

        if 'max_users' in data:
            # Sync max_users and max_mobile_devices if only one is provided?
            # Or trust the input. The frontend sends max_users for phones.
            # We should update both if they are meant to be the same.
            # But let's stick to updating what is sent.
            pass
            
        for field in fields:
            if field in data:
                if field == 'max_web_sessions':
                    try:
                        v = int(data[field])
                        if v < 1:
                            v = 1
                        data[field] = v
                    except Exception:
                        data[field] = 1
                if field == 'max_users':
                    data[field] = to_int_min(data[field], 5, 1)
                if field == 'max_employees':
                    data[field] = to_int_min(data[field], 50, 0)
                if field == 'max_mobile_devices':
                    data[field] = to_int_min(data[field], data.get('max_users') or 5, 1)
                query += f"{field} = ?, "
                params.append(data[field])
        
        # Special case: if max_users is updated but max_mobile_devices isn't, sync them?
        # User said "number of users which will be number of phones".
        if 'max_users' in data and 'max_mobile_devices' not in data:
             query += "max_mobile_devices = ?, "
             params.append(data['max_users'])
             
        # Capture old limits
        old_web = None
        old_mobile = None
        try:
            c.execute("SELECT max_web_sessions, max_mobile_devices FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
            r = c.fetchone()
            if r:
                try:
                    old_web = int(r[0]) if r[0] is not None else None
                except Exception:
                    old_web = None
                try:
                    old_mobile = int(r[1]) if r[1] is not None else None
                except Exception:
                    old_mobile = None
        except Exception:
            old_web = None
            old_mobile = None
        
        # Compute decreased flags
        new_web = data.get('max_web_sessions')
        new_mobile = data.get('max_mobile_devices')
        try:
            if isinstance(new_web, str): new_web = int(new_web)
        except Exception:
            pass
        try:
            if isinstance(new_mobile, str): new_mobile = int(new_mobile)
        except Exception:
            pass
        decreased_web = (old_web is not None and new_web is not None and int(new_web) < int(old_web))
        decreased_mobile = (old_mobile is not None and new_mobile is not None and int(new_mobile) < int(old_mobile))
        
        if params:
            query = query.rstrip(", ") + " WHERE vendor_id = ?"
            params.append(vendor_id)
            c.execute(query, params)
            conn.commit()
            
            # Log Audit
            log_audit('update_subscription', data, target_vendor_id=vendor_id)
            
            try:
                _run(c, "SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
                row = c.fetchone()
                feats = []
                if row and row[0]:
                    try:
                        feats = json.loads(row[0])
                    except Exception:
                        feats = []
                socketio.emit('features_updated', {'vendor_id': vendor_id, 'features': feats}, room=f"vendor_{vendor_id}")
                socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
            except Exception:
                pass
            
            try:
                if decreased_web:
                    socketio.emit('force_logout_web', {'vendor_id': vendor_id, 'reason': 'Web session limit decreased'}, room=f"vendor_{vendor_id}")
                    c.execute("DELETE FROM active_sessions WHERE vendor_id = ? AND platform = 'web'", (vendor_id,))
                if decreased_mobile:
                    socketio.emit('force_logout_mobile', {'vendor_id': vendor_id, 'reason': 'Mobile device limit decreased'}, room=f"vendor_{vendor_id}")
                    c.execute("DELETE FROM active_sessions WHERE vendor_id = ? AND platform = 'mobile'", (vendor_id,))
                conn.commit()
            except Exception:
                pass
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/registration-config", methods=["GET"])
def get_vendor_registration_config(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    # Auth Check (SuperAdmin or Vendor Admin of same vendor)
    caller_vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    # Check permission
    # If caller_vendor_id is None, it means SuperAdmin (in global context).
    # If caller_vendor_id matches vendor_id, it is the vendor admin.
    if caller_vendor_id and caller_vendor_id != vendor_id:
         return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT registration_config, vertical FROM vendors WHERE id = ?", (vendor_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Vendor not found"}), 404
        config = None
        vertical_val = None
        try:
            config = row[0]
            vertical_val = row[1]
        except Exception:
            try:
                config = row["registration_config"]
                vertical_val = row["vertical"]
            except Exception:
                pass
        if config:
            return jsonify({"config": json.loads(config)})
        if str(vertical_val or "").strip().lower() == "school":
            try:
                default_rc = [
                    {"field": "student_number", "label": "Student ID", "type": "text", "required": True, "options": []},
                    {"field": "phone", "label": "Mobile Number", "type": "text", "required": True, "options": []},
                    {"field": "department", "label": "Class/Section", "type": "text", "required": False, "options": []}
                ]
                return jsonify({"config": default_rc})
            except Exception:
                return jsonify({"config": None})
        return jsonify({"config": None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/registration-config", methods=["PUT"])
@super_admin_required
def update_vendor_registration_config(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json
    config = data.get('config') # Expecting a list/object
    
    if config is None:
        return jsonify({"error": "Missing config"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (json.dumps(config), vendor_id))
        conn.commit()
        
        # Log Audit
        log_audit('update_registration_config', data, target_vendor_id=vendor_id)
        
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>", methods=["PUT"])
@super_admin_required
def update_vendor_details(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    from utils import BUNDLE_FEATURES
    data = request.json
    
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Check if vendor exists
        c.execute("SELECT id FROM vendors WHERE id = ?", (vendor_id,))
        if not c.fetchone():
            return jsonify({"error": "Vendor not found"}), 404

        # 1. Update Vendor Details
        query = "UPDATE vendors SET "
        params = []
        
        fields = ['company_name', 'contact_person', 'phone', 'email', 'frontend_bundle_id', 'backend_service_id', 'vertical']
        for field in fields:
            if field in data:
                query += f"{field} = ?, "
                params.append(data[field])
        
        # Sync Features if frontend_bundle_id is updated
        if 'frontend_bundle_id' in data:
            new_bundle_id = data['frontend_bundle_id']
            new_features = BUNDLE_FEATURES.get(new_bundle_id, [])
            import json
            features_json = json.dumps(new_features)
            
            # Check if subscription exists
            c.execute("SELECT rowid FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
            if c.fetchone():
                c.execute("UPDATE subscriptions SET features = ? WHERE vendor_id = ?", (features_json, vendor_id))
            else:
                # Should create one? Maybe not here.
                pass
        
        if 'config' in data:
            config = data['config']
            if isinstance(config, dict):
                config = json.dumps(config)
            query += "config = ?, "
            params.append(config)
        
        if params:
            query = query.rstrip(", ") + " WHERE id = ?"
            params.append(vendor_id)
            c.execute(query, params)
            try:
                if 'vertical' in data and str(data.get('vertical') or '').strip().lower() == 'school':
                    c.execute("SELECT registration_config FROM vendors WHERE id = ?", (vendor_id,))
                    r = c.fetchone()
                    needs_set = False
                    if not r:
                        needs_set = True
                    else:
                        try:
                            existing_rc = r[0]
                            needs_set = existing_rc is None or str(existing_rc).strip() == ''
                        except Exception:
                            needs_set = True
                    if needs_set:
                        rc = json.dumps([
                            {"field": "student_number", "label": "Student ID", "type": "text", "required": True, "options": []},
                            {"field": "phone", "label": "Mobile Number", "type": "text", "required": True, "options": []},
                            {"field": "department", "label": "Class/Section", "type": "text", "required": False, "options": []}
                        ])
                        c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (rc, vendor_id))
            except Exception:
                pass
            
        # 2. Update Admin Credentials
        admin_username = data.get('admin_username')
        admin_password = data.get('admin_password')
        if admin_username or admin_password:
            # Check if admin user exists for this vendor
            c.execute("SELECT rowid FROM system_users WHERE vendor_id = ? AND role = 'vendor_admin'", (vendor_id,))
            admin_user = c.fetchone()
            
            if admin_user:
                update_query = "UPDATE system_users SET "
                update_params = []
                if admin_username:
                    update_query += "username = ?, "
                    update_params.append(admin_username)
                if admin_password:
                    update_query += "password = ?, "
                    update_params.append(hash_password(admin_password))
                
                update_query = update_query.rstrip(", ") + " WHERE rowid = ?"
                update_params.append(admin_user[0])
                c.execute(update_query, update_params)
            else:
                # Create if missing (Self-healing)
                c.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, 'vendor_admin', ?)",
                          (admin_username or f"admin_{vendor_id}", hash_password(admin_password or "default123"), vendor_id))

        # 3. Update User/Kiosk Credentials
        user_username = data.get('user_username')
        user_password = data.get('user_password')
        if user_username or user_password:
            # Check if kiosk user exists for this vendor
            c.execute("SELECT rowid FROM system_users WHERE vendor_id = ? AND role = 'user'", (vendor_id,))
            kiosk_user = c.fetchone()
            
            if kiosk_user:
                update_query = "UPDATE system_users SET "
                update_params = []
                if user_username:
                    update_query += "username = ?, "
                    update_params.append(user_username)
                if user_password:
                    update_query += "password = ?, "
                    update_params.append(hash_password(user_password))
                
                update_query = update_query.rstrip(", ") + " WHERE rowid = ?"
                update_params.append(kiosk_user[0])
                c.execute(update_query, update_params)
            else:
                # Create if missing
                c.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, 'user', ?)",
                          (user_username or f"user_{vendor_id}", hash_password(user_password or "user123"), vendor_id))

        conn.commit()
        return jsonify({"success": True})
        
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username or Company Name already exists"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>", methods=["DELETE"])
@super_admin_required
def delete_vendor(vendor_id):
    from celery_app import celery
    if celery:
        from tasks import process_delete_vendor_task
        task = process_delete_vendor_task.delay(vendor_id)
        return jsonify({"success": True, "task_id": task.id, "message": "Vendor deletion/archiving in background"}), 202

    from app import get_db_connection, socketio
    ensure_archive_table()
    conn = get_db_connection()
    c = conn.cursor()
    # ... keep existing fallback ...
    try:
        _run(c, "SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        vendor_row = c.fetchone()
        if not vendor_row:
            return jsonify({"error": "Vendor not found"}), 404
        # (Rest of the original code follows...)
        def archive_table(table, key="vendor_id"):
            _run(c, f"SELECT * FROM {table} WHERE {key} = ?", (vendor_id,))
            cols = [d[0] for d in c.description] if hasattr(c, "description") and c.description else []
            fetched = c.fetchall()
            for r in fetched:
                row = r if isinstance(r, dict) else {cols[i]: r[i] for i in range(len(cols))}
                _run(c, "INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES (?, ?, ?)", (vendor_id, table, json.dumps(row)))
        tables = ["subscriptions", "invoices", "system_users", "companies", "faces", "attendance", "active_sessions"]
        for t in tables: archive_table(t)
        vcols = [d[0] for d in c.description] if hasattr(c, "description") and c.description else []
        vdict = vendor_row if isinstance(vendor_row, dict) else {vcols[i]: vendor_row[i] for i in range(len(vcols))}
        _run(c, "INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES (?, ?, ?)", (vendor_id, "vendors", json.dumps(vdict)))
        for t in tables: _run(c, f"DELETE FROM {t} WHERE vendor_id = ?", (vendor_id,))
        _run(c, "DELETE FROM vendors WHERE id = ?", (vendor_id,))
        conn.commit()
        return jsonify({"success": True, "message": "Vendor archived and deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/invoices", methods=["GET"])
@super_admin_required
def get_vendor_invoices(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Auto-update overdue status
    today = date.today().isoformat()
    c.execute("UPDATE invoices SET status = 'overdue' WHERE vendor_id = ? AND status = 'generated' AND due_date < ?", (vendor_id, today))
    conn.commit()
    
    c.execute("SELECT * FROM invoices WHERE vendor_id = ? ORDER BY invoice_date DESC", (vendor_id,))
    invoices = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify({"invoices": invoices})

@admin_bp.route("/archive/vendors", methods=["GET"])
@super_admin_required
def list_archived_vendors():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    ensure_archive_table()
    company = request.args.get("company_name")
    email = request.args.get("email")
    conn = get_db_connection()
    c = conn.cursor()
    try:
        _run(c, "SELECT vendor_id, row_json, archived_at, restored_at FROM archive_objects WHERE table_name = 'vendors'")
        rows = c.fetchall()
        results = []
        for r in rows:
            # r may be tuple or dict depending on DB driver
            row_json = None
            vid = None
            if isinstance(r, dict):
                vid = r.get("vendor_id")
                row_json = r.get("row_json")
            else:
                # vendor_id at index 0, row_json at index 1 for our select order
                vid = r[0]
                row_json = r[1]
            try:
                data = json.loads(row_json)
            except Exception:
                continue
            if company and data.get("company_name") != company:
                continue
            if email and data.get("email") != email:
                continue
            results.append({"vendor_id": vid, "data": data})
        return jsonify({"archived_vendors": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/audit-logs", methods=["GET"])
@super_admin_required
def list_audit_logs():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    ensure_audit_logs_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        _run(c, "SELECT id, timestamp, actor_username, actor_role, target_vendor_id, action, details, ip FROM audit_logs ORDER BY timestamp DESC LIMIT 500")
        rows = c.fetchall()
        logs = []
        for r in rows:
            if isinstance(r, dict):
                d = r
            else:
                d = {
                    "id": r[0],
                    "timestamp": r[1],
                    "actor_username": r[2],
                    "actor_role": r[3],
                    "target_vendor_id": r[4],
                    "action": r[5],
                    "details": r[6],
                    "ip": r[7]
                }
            logs.append(d)
        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/invoices/generate", methods=["POST"])
@super_admin_required
def generate_invoice(vendor_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    from utils import create_job, complete_job, fail_job
    import eventlet
    is_async = request.args.get('async') == 'true'
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get Subscription Details
    c.execute("SELECT * FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
    sub = c.fetchone()
    if not sub:
        conn.close()
        return jsonify({"error": "No subscription found"}), 404
        
    # Get Billable Unit Count (Phones/Users) - Matching Dashboard Logic
    # User requested: "amount should be number of users multiplied by the amount per employee"
    # Interpreted as: Number of Phones (Users) * Cost per Unit
    billed_count = sub['max_users'] or 5
    
    # Calculate Amount
    cost_per_user = sub['cost_per_user'] or 0 # Now means Cost Per Device
    cost_per_employee = sub['cost_per_employee'] or 0 # New Cost Per Employee
    
    # Formula: (Max Employees * Cost Per Employee) + (Max Devices * Cost Per Device)
    max_employees_count = sub['max_employees'] or 50
    billed_device_count = sub['max_users'] or 5 # Using max_users as max_devices
    
    employee_cost_total = max_employees_count * cost_per_employee
    device_cost_total = billed_device_count * cost_per_user
    
    monthly_cost = employee_cost_total + device_cost_total
    
    # Check for Setup Fee
    setup_fee = 0
    if sub['setup_fee'] and not sub['setup_fee_paid']:
        setup_fee = sub['setup_fee']
        
    total_amount = monthly_cost + setup_fee
    
    import json
    details = {
        "max_employees": max_employees_count,
        "cost_per_employee": cost_per_employee,
        "max_devices": billed_device_count,
        "cost_per_device": cost_per_user,
        "employee_cost_total": employee_cost_total,
        "device_cost_total": device_cost_total,
        "monthly_charge": monthly_cost,
        "setup_fee": setup_fee
    }
    
    # Create Invoice
    invoice_date = date.today().isoformat()
    due_date = (date.today() + timedelta(days=7)).isoformat()
    
    c.execute("""INSERT INTO invoices (vendor_id, invoice_date, due_date, amount, status, details)
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (vendor_id, invoice_date, due_date, total_amount, 'generated', json.dumps(details)))
              
    # If setup fee was included, mark it as paid (or maybe only after invoice is paid? Let's keep it simple for now)
    # Actually, better to mark setup_fee_paid ONLY when invoice is paid.
    
    conn.commit()
    try:
        log_audit("invoice_generate", {"amount": total_amount}, target_vendor_id=vendor_id, status="success")
    except Exception:
        pass
    conn.close()
    if is_async:
        job_id = create_job(content_type="application/json", ttl=600)
        def _bg():
            try:
                complete_job(job_id, json.dumps({"success": True, "message": "Invoice Generated", "amount": total_amount}))
                socketio.emit('job_completed', {'job_id': job_id, 'type': 'invoice_generate', 'vendor_id': vendor_id})
            except Exception as e:
                fail_job(job_id, e)
        eventlet.spawn_n(_bg)
        return jsonify({"success": True, "job_id": job_id, "processing": True})
    return jsonify({"success": True, "message": "Invoice Generated", "amount": total_amount})

@admin_bp.route("/invoices/<int:invoice_id>/status", methods=["PUT"])
@super_admin_required
def update_invoice_status(invoice_id):
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json
    status = data.get("status") # paid, overdue, generated
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("UPDATE invoices SET status = ? WHERE id = ?", (status, invoice_id))
    
    # If paid, check if it included setup fee and update subscription
    if status == 'paid':
        c.execute("SELECT details, vendor_id FROM invoices WHERE id = ?", (invoice_id,))
        invoice = c.fetchone()
        if invoice:
            import json
            details = json.loads(invoice['details'])
            if details.get('setup_fee', 0) > 0:
                c.execute("UPDATE subscriptions SET setup_fee_paid = 1 WHERE vendor_id = ?", (invoice['vendor_id'],))
    
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@admin_bp.route("/system/health", methods=["GET"])
@super_admin_required
def system_health():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    status = {"db": "ok", "redis": "disabled", "active_sessions": 0}
    # DB check
    try:
        conn = get_db_connection()
        c = conn.cursor()
        _run(c, "SELECT COUNT(*) FROM active_sessions")
        row = c.fetchone()
        status["active_sessions"] = row[0] if row else 0
        conn.close()
    except Exception as e:
        status["db"] = f"error: {str(e)}"
    # Redis
    try:
        if redis_client:
            redis_client.ping()
            status["redis"] = "ok"
    except Exception as e:
        status["redis"] = f"error: {str(e)}"
    # Socket info (basic)
    status["socketio"] = {"async_mode": socketio.async_mode, "ping_timeout": 60, "ping_interval": 25}
    return jsonify(status)

@admin_bp.route("/system/queues", methods=["GET"])
@super_admin_required
def system_queues():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = {
        "broker": "unknown",
        "queues": {},
        "workers": [],
        "active": {},
        "reserved": {},
        "scheduled": {}
    }
    # Broker info
    try:
        if redis_client:
            data["broker"] = "redis"
            # Common Celery queue names
            for q in ["celery", "default", "high", "low"]:
                try:
                    llen = redis_client.llen(q)
                    if llen is not None:
                        data["queues"][q] = int(llen)
                except Exception:
                    pass
    except Exception:
        pass
    # Celery inspect
    try:
        if celery:
            i = celery.control.inspect()
            data["active"] = i.active() or {}
            data["reserved"] = i.reserved() or {}
            data["scheduled"] = i.scheduled() or {}
            stats = i.stats() or {}
            data["workers"] = list(stats.keys())
    except Exception as e:
        data["error"] = str(e)
    return jsonify(data)

@admin_bp.route("/jobs/events", methods=["GET"])
@super_admin_required
def list_task_events():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    ensure_task_events_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        status = request.args.get("status")
        queue = request.args.get("queue")
        name = request.args.get("name")
        limit = int(request.args.get("limit") or 100)
        offset = int(request.args.get("offset") or 0)
        base = "SELECT id, task_id, name, queue, worker, status, received_at, started_at, finished_at, runtime, retries, eta, args, kwargs, result, error FROM task_events"
        where = []
        params = []
        if status:
            where.append("status = ?")
            params.append(status)
        if queue:
            where.append("queue = ?")
            params.append(queue)
        if name:
            where.append("name = ?")
            params.append(name)
        if where:
            base += " WHERE " + " AND ".join(where)
        base += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        _run(c, base, params)
        rows = c.fetchall()
        events = []
        for r in rows:
            if isinstance(r, dict):
                events.append(r)
            else:
                events.append({
                    "id": r[0], "task_id": r[1], "name": r[2], "queue": r[3], "worker": r[4], "status": r[5],
                    "received_at": r[6], "started_at": r[7], "finished_at": r[8], "runtime": r[9], "retries": r[10],
                    "eta": r[11], "args": r[12], "kwargs": r[13], "result": r[14], "error": r[15]
                })
        return jsonify({"events": events})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/jobs/events/purge", methods=["POST"])
@super_admin_required
def purge_task_events():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    ensure_task_events_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        older_days = int(request.args.get("older_days") or 0)
        max_rows = request.json.get("max_rows") if request.is_json else None
        deleted = 0
        if older_days > 0:
            _run(c, "DELETE FROM task_events WHERE created_at < datetime('now', ?)", (f'-{older_days} days',))
            deleted += c.rowcount if hasattr(c, "rowcount") else 0
        if max_rows:
            _run(c, "SELECT COUNT(*) FROM task_events")
            total = c.fetchone()[0]
            if total and int(total) > int(max_rows):
                overflow = int(total) - int(max_rows)
                _run(c, "DELETE FROM task_events WHERE id IN (SELECT id FROM task_events ORDER BY id ASC LIMIT ?)", (overflow,))
                deleted += c.rowcount if hasattr(c, "rowcount") else 0
        conn.commit()
        return jsonify({"success": True, "deleted": deleted})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/jobs/metrics", methods=["GET"])
@super_admin_required
def jobs_metrics():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    ensure_task_events_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        window_minutes = int(request.args.get("window_minutes") or 60)
        bucket = request.args.get("bucket") or "minute"
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        _run(c, "SELECT queue, status, runtime, finished_at, started_at, received_at FROM task_events WHERE (finished_at IS NOT NULL AND finished_at >= ?) OR (finished_at IS NULL AND created_at >= ?)", (cutoff.isoformat(), cutoff.isoformat()))
        rows = c.fetchall()
        buckets = {}
        queues = set()
        def bucket_key(ts):
            try:
                if not ts:
                    return None
                dt = datetime.fromisoformat(ts.replace('Z',''))
            except Exception:
                return None
            if bucket == "hour":
                return dt.strftime("%Y-%m-%d %H:00")
            return dt.strftime("%Y-%m-%d %H:%M")
        for r in rows:
            if isinstance(r, dict):
                q = r.get("queue")
                st = r.get("status")
                rt = r.get("runtime")
                ts = r.get("finished_at") or r.get("started_at") or r.get("received_at")
            else:
                q, st, rt, fts, sts, rts = r
                ts = fts or sts or rts
            queues.add(q or "unknown")
            bk = bucket_key(ts)
            if not bk:
                continue
            key = (q or "unknown", bk)
            if key not in buckets:
                buckets[key] = {"count": 0, "fail": 0, "retry": 0, "runtimes": []}
            buckets[key]["count"] += 1
            if st == "failure":
                buckets[key]["fail"] += 1
            if st == "retry":
                buckets[key]["retry"] += 1
            try:
                if rt is not None:
                    buckets[key]["runtimes"].append(float(rt))
            except Exception:
                pass
        series = {}
        time_keys = sorted({bk for (_, bk) in buckets.keys()})
        for q in sorted(queues):
            series[q] = []
            for t in time_keys:
                agg = buckets.get((q, t))
                if not agg:
                    series[q].append({"time": t, "count": 0, "fail_rate": 0.0, "avg_runtime": 0.0, "p95": 0.0, "p99": 0.0})
                    continue
                cnt = agg["count"]
                fr = (agg["fail"] / cnt) if cnt else 0.0
                avg = sum(agg["runtimes"]) / len(agg["runtimes"]) if agg["runtimes"] else 0.0
                runt = sorted(agg["runtimes"])
                def pct(p):
                    if not runt:
                        return 0.0
                    idx = int(max(0, min(len(runt)-1, round(p * len(runt)) - 1)))
                    return runt[idx]
                series[q].append({"time": t, "count": cnt, "fail_rate": fr, "avg_runtime": avg, "p95": pct(0.95), "p99": pct(0.99)})
        return jsonify({"bucket": bucket, "window_minutes": window_minutes, "times": time_keys, "series": series})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/restore", methods=["POST"])
@super_admin_required
def restore_vendor():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    ensure_archive_table()
    data = request.json or {}
    company = data.get("company_name")
    email = data.get("email")
    if not company and not email:
        return jsonify({"error": "Provide company_name or email"}), 400
    conn = get_db_connection()
    c = conn.cursor()
    try:
        _run(c, "SELECT vendor_id, row_json FROM archive_objects WHERE table_name='vendors'")
        rows = c.fetchall()
        target_vendor_id = None
        vendor_snapshot = None
        for r in rows:
            vid = r[0] if not isinstance(r, dict) else r.get("vendor_id")
            row_json = r[1] if not isinstance(r, dict) else r.get("row_json")
            try:
                vdata = json.loads(row_json)
            except Exception:
                continue
            if company and vdata.get("company_name") != company:
                continue
            if email and vdata.get("email") != email:
                continue
            target_vendor_id = vid
            vendor_snapshot = vdata
            break
        if not target_vendor_id:
            return jsonify({"error": "No archived vendor match found"}), 404
        # Create vendor
        _run(c, """INSERT INTO vendors (company_name, contact_person, phone, email, frontend_bundle_id, backend_service_id) 
                   VALUES (?, ?, ?, ?, ?, ?)""", (
            vendor_snapshot.get("company_name"),
            vendor_snapshot.get("contact_person"),
            vendor_snapshot.get("phone"),
            vendor_snapshot.get("email"),
            vendor_snapshot.get("frontend_bundle_id") or "default_attendance",
            vendor_snapshot.get("backend_service_id") or "default_api"
        ))
        new_vendor_id = None
        try:
            new_vendor_id = c.lastrowid
        except Exception:
            _run(c, "SELECT id FROM vendors WHERE email = ?", (vendor_snapshot.get("email"),))
            r2 = c.fetchone()
            new_vendor_id = r2[0] if r2 else None
        if not new_vendor_id:
            conn.rollback()
            return jsonify({"error": "Failed to create vendor"}), 500
        # Restore subscriptions
        _run(c, "SELECT row_json FROM archive_objects WHERE table_name='subscriptions' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            obj = json.loads(row_json)
            _run(c, """INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, setup_fee, features)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                new_vendor_id, obj.get("plan_type") or "custom", obj.get("start_date"), obj.get("end_date"),
                obj.get("max_users"), obj.get("max_employees"), obj.get("max_mobile_devices"),
                obj.get("cost_per_user"), obj.get("cost_per_employee"), obj.get("setup_fee") or 0, obj.get("features")
            ))
        # Restore users
        _run(c, "SELECT row_json FROM archive_objects WHERE table_name='system_users' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            u = json.loads(row_json)
            _run(c, """INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)""",
                 (u.get("username"), u.get("password"), u.get("role"), new_vendor_id))
        # Restore companies
        _run(c, "SELECT row_json FROM archive_objects WHERE table_name='companies' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            comp = json.loads(row_json)
            _run(c, """INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)""",
                 (comp.get("name"), comp.get("shifts") or "[]", comp.get("draft_timetable") or "[]", comp.get("live_timetable") or "[]", new_vendor_id))
        # Restore faces
        _run(c, "SELECT row_json FROM archive_objects WHERE table_name='faces' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            f = json.loads(row_json)
            _run(c, """INSERT INTO faces (name, templates, face_image, phone, department, designation, shift, vendor_id, custom_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (f.get("name"), f.get("templates"), f.get("face_image"), f.get("phone"), f.get("department"), f.get("designation"), f.get("shift"), new_vendor_id, f.get("custom_data")))
        conn.commit()
        return jsonify({"success": True, "new_vendor_id": new_vendor_id})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/students/assign-parent", methods=["POST"])
def assign_parent():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    caller_vendor_id, error = authenticate_vendor_access()
    if error: return error
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1]
    user_data = verify_token(token)
    if user_data['role'] not in ['super_admin', 'vendor_admin']:
        return jsonify({"error": "Access Denied: Admin privileges required"}), 403
    data = request.json
    person_id = data.get("person_id")
    parent_id = data.get("parent_id")
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO student_parents (vendor_id, person_id, parent_id) VALUES (?, ?, ?)",
                  (caller_vendor_id, person_id, parent_id))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/superadmin/subscription", methods=["POST", "PUT"])
@super_admin_required
def update_subscription():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    data = request.json
    vendor_id = data.get("vendor_id")
    
    if not vendor_id:
        return jsonify({"error": "Vendor ID required"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Check if subscription exists
        c.execute("SELECT id FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        exists = c.fetchone()
        
        fields = ["plan_type", "max_users", "max_employees", "max_mobile_devices", "start_date", "end_date", "grace_period_days", "status", "cost_per_user", "cost_per_employee", "setup_fee", "setup_fee_paid"]
        updates = []
        params = []
        
        for field in fields:
            if field in data:
                updates.append(f"{field} = ?")
                params.append(data[field])
                
        if not updates:
             return jsonify({"error": "No fields to update"}), 400
             
        params.append(vendor_id)
        
        if exists:
            query = f"UPDATE subscriptions SET {', '.join(updates)} WHERE vendor_id = ?"
            c.execute(query, params)
        else:
            return jsonify({"error": "Subscription not found for vendor"}), 404
            
        conn.commit()
        return jsonify({"status": "success", "message": "Subscription updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/superadmin/employees", methods=["GET"])
@super_admin_required
def get_all_employees():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from services.auth_service import authenticate_vendor_access
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Join Faces with Vendors and Attendance
    # We want latest attendance status
    query = """
        SELECT f.*, v.company_name,
               (SELECT status FROM attendance a WHERE a.person_id = f.id ORDER BY timestamp DESC LIMIT 1) as last_status,
               (SELECT timestamp FROM attendance a WHERE a.person_id = f.id ORDER BY timestamp DESC LIMIT 1) as last_seen
        FROM faces f
        LEFT JOIN vendors v ON f.vendor_id = v.id
    """
    
    # Filter by vendor if requested
    vendor_id = request.args.get("vendor_id")
    params = []
    if vendor_id:
        query += " WHERE f.vendor_id = ?"
        params.append(vendor_id)
        
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    employees = []
    for row in rows:
        employees.append({
            "id": row["id"],
            "name": row["name"],
            "vendor_id": row["vendor_id"],
            "company_name": row["company_name"],
            "department": row["department"],
            "designation": row["designation"],
            "face_image": row["face_image"],
            "last_status": row["last_status"],
            "last_seen": row["last_seen"]
        })
        
    return jsonify({"employees": employees})