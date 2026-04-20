import os
from flask import Blueprint, request, jsonify, make_response
from datetime import datetime, date, timedelta
from services.auth_service import authenticate_vendor_access, verify_password, generate_token, check_vendor_status, verify_token, hash_password, generate_token_with_claims, extract_token
from middleware.handlers import rate_limit
import json
import sqlite3
import logging
from db_factory import get_table_columns
from utils import error_logger

logger = logging.getLogger(__name__)

# We will need the app's db connection temporarily until we refactor database access
# We also need check_vendor_status, so we will import it locally inside functions or at the top


auth_bp = Blueprint('auth_bp', __name__)
@auth_bp.route("/auth/me", methods=["GET"])
def get_current_user():
    from app import get_db_connection
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    auth_header = request.headers.get('Authorization')
    token = extract_token(auth_header)
    data = verify_token(token)
    if not data:
        return jsonify({"error": "Invalid token"}), 401
    
    username = data['username']
    conn = get_db_connection()
    try:
        if not getattr(conn, "_is_pg", False):
            conn.row_factory = sqlite3.Row
    except Exception:
        pass
    c = conn.cursor()
    c.execute("SELECT * FROM system_users WHERE username = ?", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    
    user_dict = dict(user)
    # Remove password
    if 'password' in user_dict: del user_dict['password']
    # Get Vendor Details
    vendor_id = user_dict.get('vendor_id')
    features = []
    frontend_bundle_id = 'default_attendance'
    backend_service_id = 'default_api'
    vendor_config = []
    vendor_vertical = None
    web_login_enabled = 1
    
    if vendor_id:
        c.execute("SELECT web_login_enabled, frontend_bundle_id, backend_service_id, registration_config, vertical FROM vendors WHERE id = ?", (vendor_id,))
        v_row = c.fetchone()
        if v_row:
            web_login_enabled = v_row[0]
            frontend_bundle_id = v_row[1] or 'default_attendance'
            backend_service_id = v_row[2] or 'default_api'
            config_raw = json.loads(v_row[3]) if v_row[3] else []
            from services.config_utils import hydrate_registration_config
            vendor_config = hydrate_registration_config(vendor_id, config_raw, conn=conn)
            vendor_vertical = v_row[4]
            
        c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        s_row = c.fetchone()
        if s_row and s_row[0]:
            try:
                features = json.loads(s_row[0])
            except:
                features = []
                
    conn.close()
    
    return jsonify({
        "username": username,
        "role": user_dict['role'],
        "vendor_id": vendor_id,
        "person_id": user_dict.get('person_id'),
        "frontend_bundle_id": frontend_bundle_id,
        "backend_service_id": backend_service_id,
        "vendor_config": vendor_config,
        "features": features,
        "vertical": vendor_vertical,
        "web_login_enabled": web_login_enabled
    })


@auth_bp.route("/auth/login", methods=["POST"])
@rate_limit(limit=10, window=60)  # 10 attempts per minute per IP
@error_logger
def login():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    data = request.json or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    device_id = str(data.get("device_id") or "").strip()
    platform = str(data.get("platform", "web") or "web").strip()
    features = []

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    conn = get_db_connection()
    # If it's our PostgresConnectionWrapper, it won't have row_factory attribute like sqlite3.Connection
    # But it will return PostgresCursorWrapper which handles DictCursor
    try:
        if not getattr(conn, "_is_pg", False):
            conn.row_factory = sqlite3.Row
    except Exception:
        pass
        
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM system_users WHERE username = ?", (username,))
        user = c.fetchone()
    except Exception as e:
        # Fallback for uninitialized DB or other errors
        logger.error(f"Initial login query failed: {e}")
        try:
            from app import init_db
            init_db()
        except Exception:
            pass
        try:
            # Re-fetch cursor after potential init_db
            c = conn.cursor()
            c.execute("SELECT * FROM system_users WHERE username = ?", (username,))
            user = c.fetchone()
        except Exception:
            user = None
    
    # Handle demo admin fallback
    if not user and username in ("admin", "vendor_admin"):
        try:
            # Check for demo vendor
            c.execute("SELECT id FROM vendors WHERE company_name = ?", ("Demo Company",))
            vrow = c.fetchone()
            if not vrow:
                c.execute("INSERT INTO vendors (company_name, contact_person, phone, email, status) VALUES (?, ?, ?, ?, ?)",
                           ("Demo Company", "Demo Admin", "0000000000", "demo@example.com", "active"))
                conn.commit()
                c.execute("SELECT id FROM vendors WHERE company_name = ?", ("Demo Company",))
                vrow = c.fetchone()
            
            vendor_id = vrow[0] if vrow and not hasattr(vrow, 'keys') else (vrow['id'] if vrow else None)
            
            if vendor_id:
                # Ensure subscription exists
                c.execute("SELECT id FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
                srow = c.fetchone()
                if not srow:
                    start_date = date.today()
                    end_date = start_date + timedelta(days=365)
                    c.execute("""INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, grace_period_days, features)
                                  VALUES (?, ?, ?, ?, ?, ?)""",
                               (vendor_id, "basic", start_date.isoformat(), end_date.isoformat(), 30, json.dumps(['reports','mobile_app','payroll','shifts'])))
                    conn.commit()
                
                c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)",
                           (username, hash_password(password or "admin123"), "vendor_admin", vendor_id))
                conn.commit()
                c.execute("SELECT * FROM system_users WHERE username = ?", (username,))
                user = c.fetchone()
        except Exception as e:
            logger.error(f"Failed to auto-create demo admin: {e}")
                
    if not user and is_testing() and username.startswith("admin_"):
        try:
            parts = username.split("_")
            vid = int(parts[1]) if len(parts) > 1 else None
            default_pw = password or "default123"
            c.execute("""INSERT OR IGNORE INTO system_users (username, password, role, vendor_id)
                          VALUES (?, ?, 'vendor_admin', ?)""", (username, hash_password(default_pw), vid))
            conn.commit()
            c.execute("SELECT * FROM system_users WHERE username = ?", (username,))
            user = c.fetchone()
        except Exception:
            pass
    # Handle Student Login Auto-Creation
    if not user and username:
        try:
            is_pg = getattr(conn, "_is_pg", False)
            if is_pg:
                c.execute("SELECT id, name, phone, vendor_id, custom_data FROM faces WHERE custom_data::jsonb->>'student_id' = %s OR custom_data::jsonb->>'id_number' = %s", (username, username))
            else:
                c.execute("SELECT id, name, phone, vendor_id, custom_data FROM faces WHERE json_extract(custom_data, '$.student_id') = ? OR json_extract(custom_data, '$.id_number') = ?", (username, username))
            
            face = c.fetchone()
            if face:
                face_row = face if hasattr(face, 'keys') else dict(zip(['id', 'name', 'phone', 'vendor_id', 'custom_data'], face))
                student_phone = face_row.get('phone')
                
                # FALLBACK: If phone column is empty, check custom_data for student_phone or phone
                if not student_phone and face_row.get('custom_data'):
                    try:
                        custom = face_row['custom_data']
                        if isinstance(custom, str):
                            custom = json.loads(custom)
                        student_phone = custom.get('student_phone') or custom.get('phone') or custom.get('contact_phone')
                    except: pass

                if student_phone and str(password) == str(student_phone):
                    # SECURE HASHING: Hash the password being stored
                    if is_pg:
                        c.execute(
                            "INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (%s, %s, %s, 'user', %s, %s)",
                            (username, hash_password(password), password, face_row['vendor_id'], face_row['id'])
                        )
                    else:
                        c.execute(
                            "INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (?, ?, ?, 'user', ?, ?)",
                            (username, hash_password(password), password, face_row['vendor_id'], face_row['id'])
                        )
                    conn.commit()
                    c.execute("SELECT * FROM system_users WHERE username = ?", (username,))
                    user = c.fetchone()
                    if user:
                        # Ensure user is a dict for the next steps
                        user = dict(user) if not isinstance(user, dict) else user
                        user['force_password_change'] = True
        except Exception as e:
            logger.error(f"Failed student auto-login check: {e}")

    conn.close()

    if not user:
        return jsonify({"error": "Invalid username or password"}), 401

    # Convert to dict for easier access
    if hasattr(user, 'keys'):
        user = dict(user)
    elif not isinstance(user, dict):
        # Fallback if it's a tuple/list from a different cursor type
        return jsonify({"error": "Internal database error"}), 500

    if username == "superadmin" and is_testing():
        pass_condition = True
        is_student = False
        has_set_password = False
    else:
        stored_pw = user.get("password")
        stored_plain = user.get("password_plain")
        
        # Check if student is using their "base" mobile number but has a custom password set
        is_student = user.get('role') == 'user'
        stored_pw = user.get("password")
        stored_plain = user.get("password_plain")
        
        # PROACTIVE FIX: If stored_plain is missing for student, try to resolve it from faces
        if is_student and not stored_plain:
            try:
                person_id = user.get('person_id')
                if person_id:
                    conn_f = get_db_connection()
                    cf = conn_f.cursor()
                    cf.execute("SELECT phone FROM faces WHERE id = ?", (person_id,))
                    frow = cf.fetchone()
                    if frow:
                        stored_plain = frow[0]
                        # Update the user record so we don't do this every time
                        cf.execute("UPDATE system_users SET password_plain = ? WHERE username = ?", (stored_plain, username))
                        conn_f.commit()
                        logger.info(f"Restored missing password_plain for student {username}")
                    conn_f.close()
            except Exception as e:
                logger.error(f"Error restoring student plain password: {e}")

        # Normalize comparison: remove leading 0 or +91 if necessary
        def normalize_phone(p):
            if not p: return ""
            p = str(p).strip().replace("+91", "").replace(" ", "").replace("-", "")
            if p.startswith("0") and len(p) > 10: p = p[1:]
            return p
        
        normalized_input = normalize_phone(password)
        normalized_stored = normalize_phone(stored_plain)
        
        # Identity verification logic:
        # If they enter their custom password (matching the hash), let them in directly.
        # If they enter their mobile number (matching stored_plain) AND have a custom password, trigger modal.
        
        is_entering_mobile = stored_plain and (password == stored_plain or normalized_input == normalized_stored)
        has_set_password = user.get('has_set_password') == 1
        
        logger.info(f"Login trace for {username}: is_student={is_student}, has_set_password={has_set_password}, stored_plain_exists={bool(stored_plain)}")
        
        # 1. Try verifiable password (Hash) FIRST
        if verify_password(password, stored_pw):
            pass_condition = True
        # 2. If it didn't match hash, check if it's the mobile number and they HAVE a custom password set
        elif is_student and is_entering_mobile and has_set_password:
            # They entered ID + Mobile, but they have a custom password.
            # Check if they also provided the secondary password
            secondary_password = request.json.get('secondary_password')
            if not secondary_password:
                logger.info(f"Triggering student password modal for {username}")
                return jsonify({
                    "status": "success",
                    "needs_student_password": True,
                    "username": username,
                    "role": "user",
                    "vendor_id": user.get('vendor_id')
                })
            
            # Verify secondary password (modal input)
            if verify_password(secondary_password, stored_pw):
                pass_condition = True
            else:
                return jsonify({"error": "Invalid custom password"}), 401
        
        # 3. Fallback for non-modal cases (e.g. first login with mobile number)
        elif password == stored_pw or (stored_plain and password == stored_plain):
            pass_condition = True
        else:
            pass_condition = verify_password(password, stored_pw)
        
    if pass_condition:
        try:
            if user.get("password") == password:
                # Password was plain text, migrate to hash
                conn_u = get_db_connection()
                cu = conn_u.cursor()
                cu.execute("UPDATE system_users SET password = ?, password_plain = NULL WHERE username = ?", 
                           (hash_password(password), username))
                conn_u.commit()
                conn_u.close()
        except Exception as e:
            logger.error(f"Migration error: {e}")
            
        # If it's a student and they haven't set a custom password yet, force them to set one
        if is_student and not has_set_password:
            user['force_password_change'] = True
            logger.info(f"Forcing student password set for {username} (first login or reset)")

        vendor_vertical = None
        user_vendor_id = user.get('vendor_id')
        
        if user_vendor_id:
            is_allowed, reason = check_vendor_status(user_vendor_id)
            if not is_allowed and reason != "Subscription Expired":
                return jsonify({"error": f"Access Denied: {reason}"}), 403
            
            # Use separate variable for is_pg to avoid re-calculating or using outdated ones
            is_pg = getattr(conn, "_is_pg", False)
            
            conn = get_db_connection()
            c = conn.cursor()
            vcols = get_table_columns(conn, "vendors")
            reg_select = "registration_config" if "registration_config" in vcols else "NULL AS registration_config"
            c.execute(f"SELECT web_login_enabled, frontend_bundle_id, backend_service_id, {reg_select} FROM vendors WHERE id = ?", (user_vendor_id,))
            row = c.fetchone()
            web_login_enabled = row[0] if row else 1
            frontend_bundle_id = row[1] if row and len(row) > 1 and row[1] else 'default_attendance'
            backend_service_id = row[2] if row and len(row) > 2 and row[2] else 'default_api'
            config_raw = json.loads(row[3]) if row and len(row) > 3 and row[3] else []
            from services.config_utils import hydrate_registration_config
            vendor_config = hydrate_registration_config(user_vendor_id, config_raw, conn=conn)
            
            try:
                c.execute("SELECT vertical FROM vendors WHERE id = ?", (user['vendor_id'],))
                vrow = c.fetchone()
                vendor_vertical = vrow[0] if vrow else None
            except Exception:
                vendor_vertical = None
                
            try:
                c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (user['vendor_id'],))
                sub_row = c.fetchone()
                if sub_row:
                    try:
                        raw = sub_row[0] if not hasattr(sub_row, "keys") else dict(sub_row).get("features")
                    except Exception:
                        raw = sub_row[0]
                    if raw:
                        try:
                            features = json.loads(raw) if isinstance(raw, str) else list(raw)
                        except Exception:
                            features = []
            except Exception:
                pass
            
            if platform == 'web':
                try:
                    is_pg = getattr(conn, "_is_pg", False)
                    if is_pg:
                        c.execute("DELETE FROM active_sessions WHERE platform = 'web' AND last_active < (NOW() - INTERVAL '1 day')")
                    else:
                        c.execute("DELETE FROM active_sessions WHERE platform = 'web' AND last_active < datetime('now','-1 day')")
                    c.execute("DELETE FROM active_sessions WHERE username = ? AND platform = 'web' AND (device_id IS NULL OR device_id = '')", (username,))
                    conn.commit()
                except Exception:
                    pass
            elif platform == 'mobile':
                if user['role'] in ['vendor_admin', 'user', 'owner']:
                    c.execute("SELECT max_mobile_devices FROM subscriptions WHERE vendor_id = ?", (user['vendor_id'],))
                    sub = c.fetchone()
                    # if limit is None or missing, default to 1
                    max_devs = sub[0] if sub and sub[0] is not None else 1
                    
                    if device_id:
                        c.execute("SELECT id FROM vendor_devices WHERE vendor_id = ? AND device_id = ?", (user['vendor_id'], device_id))
                        existing_device = c.fetchone()
                        
                        if existing_device:
                            c.execute("UPDATE vendor_devices SET last_login_at = ? WHERE id = ?", (datetime.now(), existing_device[0]))
                            conn.commit()
                        else:
                            c.execute("SELECT COUNT(*) FROM vendor_devices WHERE vendor_id = ?", (user['vendor_id'],))
                            registered_count = c.fetchone()[0]
                            
                            if registered_count >= max_devs:
                                conn.close()
                                return jsonify({"error": f"Mobile device limit reached ({max_devs}). Contact Admin to register new device."}), 403
                            
                            try:
                                c.execute("INSERT INTO vendor_devices (vendor_id, device_id, device_name, last_login_at) VALUES (?, ?, ?, ?)",
                                          (user['vendor_id'], device_id, f"Device {device_id[:8]}", datetime.now()))
                                conn.commit()
                            except sqlite3.IntegrityError:
                                pass
                    else:
                        conn.close()
                        return jsonify({"error": "Device ID required for mobile login"}), 400
                else:
                    # Allow parent and other roles on mobile without consuming vendor device slots
                    pass

            conn.close()

            if not is_allowed:
                if reason == "Subscription Expired" and web_login_enabled:
                     token = generate_token(user['username'], user['role'], user.get('vendor_id'), platform=platform)
                     return jsonify({
                        "status": "success",
                        "role": user["role"],
                        "username": user["username"],
                        "token": token,
                        "redirect_url": "/recharge",
                        "warning": "Subscription Expired",
                        "frontend_bundle_id": frontend_bundle_id,
                        "backend_service_id": backend_service_id,
                        "vendor_config": vendor_config,
                        "features": features
                    })

                error_msg = f"Access Denied: {reason}"
                if reason == "Subscription Expired":
                    error_msg = "Access Denied: Recharge the plan"
                return jsonify({"error": error_msg}), 403
            
            if user['role'] == 'vendor_admin' and not web_login_enabled:
                 return jsonify({"error": "Access Denied: Web Login Disabled"}), 403
        else:
            frontend_bundle_id = 'enterprise_custom_ui'
            backend_service_id = 'default_api'
            vendor_config = {}
            features = ALL_FEATURES

        token = generate_token(user['username'], user['role'], user.get('vendor_id'), platform=platform)

        company_id = None
        if user_vendor_id:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM companies WHERE vendor_id = ? LIMIT 1", (user_vendor_id,))
            row = c.fetchone()
            if row:
                company_id = row[0]
            
            device_slot_required = False
            available_slots = []
            try:
                if platform == 'mobile':
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
                    if device_id:
                        c.execute("SELECT slot_name FROM vendor_device_slots WHERE vendor_id = ? AND assigned_device_id = ? LIMIT 1", (user_vendor_id, device_id))
                        assigned_row = c.fetchone()
                        if not assigned_row:
                            c.execute("SELECT slot_name FROM vendor_device_slots WHERE vendor_id = ? AND (assigned_device_id IS NULL OR assigned_device_id = '') ORDER BY id ASC", (user_vendor_id,))
                            available_rows = c.fetchall() or []
                            available_slots = [r[0] if not hasattr(r, 'keys') else (r['slot_name']) for r in available_rows]
                            if len(available_slots) > 0:
                                device_slot_required = True
            except Exception as _e:
                device_slot_required = False
                available_slots = []
            
            if platform == 'web' and user['role'] == 'vendor_admin':
                max_web = 1
                try:
                    c.execute("SELECT max_web_sessions FROM subscriptions WHERE vendor_id = ?", (user_vendor_id,))
                    mw = c.fetchone()
                    max_web = mw[0] if mw else 1
                except Exception:
                    max_web = 1
                try:
                    max_web = int(max_web)
                except Exception:
                    max_web = 1
                if max_web < 1:
                    max_web = 1
                try:
                    c.execute("DELETE FROM active_sessions WHERE username = ? AND platform = 'web' AND (device_id IS NULL OR device_id = '')", (username,))
                    c.execute("SELECT COUNT(DISTINCT device_id) FROM active_sessions WHERE username = ? AND platform = 'web' AND device_id IS NOT NULL AND device_id != ''", (username,))
                    existing_count = c.fetchone()[0] or 0
                    if existing_count >= max_web:
                        if device_id:
                            c.execute("SELECT COUNT(*) FROM active_sessions WHERE username = ? AND platform = 'web' AND device_id = ?", (username, device_id))
                            same = c.fetchone()[0]
                            if same == 0:
                                conn.close()
                                return jsonify({"error": f"Web session limit reached ({max_web})."}), 403
                        else:
                            conn.close()
                            return jsonify({"error": f"Web session limit reached ({max_web})."}), 403
                except Exception:
                    pass

            # Device-Centric Restriction: 
            # Ensure this specific device only has ONE active session at a time in the database,
            # regardless of which user is logging in now vs who was there before.
            try:
                c.execute("DELETE FROM active_sessions WHERE platform = ? AND device_id = ?", (platform, device_id))
            except Exception:
                pass

            # Cleanup stale sessions (older than 12h instead of 24h for better rotation)
            try:
                is_pg = getattr(conn, "_is_pg", False)
                # Only purge web sessions automatically; mobile sessions persist
                # until explicit logout or admin force-logout.
                if is_pg:
                    c.execute("DELETE FROM active_sessions WHERE platform = 'web' AND last_active < (NOW() - INTERVAL '12 hours')")
                else:
                    c.execute("DELETE FROM active_sessions WHERE platform = 'web' AND last_active < datetime('now','-12 hours')")
            except Exception as e:
                logger.error(f"Error cleaning stale sessions: {e}")

            try:
                c.execute("CREATE TABLE IF NOT EXISTS active_sessions (token TEXT PRIMARY KEY, username TEXT, vendor_id INTEGER, device_id TEXT, platform TEXT, last_active DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            except Exception:
                pass
            
            # Create NEW session for this login
            c.execute("INSERT INTO active_sessions (token, username, vendor_id, device_id, platform, last_active) VALUES (?, ?, ?, ?, ?, ?)",
                      (token, username, user_vendor_id, device_id, platform, datetime.now()))
            conn.commit()
            conn.close()

        resp = make_response(jsonify({
            "status": "success",
            "role": user["role"],
            "username": user["username"],
            "token": token,  # kept for mobile / backward compat
            "vendor_id": user_vendor_id,
            "person_id": user.get("person_id"),
            "company_id": company_id,
            "frontend_bundle_id": frontend_bundle_id,
            "backend_service_id": backend_service_id,
            "vendor_config": vendor_config,
            "features": features,
            "vertical": vendor_vertical,
            "device_slot_required": bool(locals().get('device_slot_required', False)),
            "available_slots": locals().get('available_slots', []),
            "force_password_change": user.get('force_password_change', False)
        }))

        # For web logins: set an httpOnly cookie so the token is not accessible
        # to JavaScript (XSS protection). Mobile clients use the Bearer token above.
        if platform == 'web':
            is_secure = os.environ.get('PROTOCOL', 'http').lower() == 'https'
            resp.set_cookie(
                'token', token,
                httponly=True,
                secure=is_secure,
                samesite='Lax',
                max_age=86400,  # matches WEB_TOKEN_TTL (24 h)
                path='/'
            )

        return resp
    else:
        return jsonify({"error": "Invalid credentials"}), 401

@auth_bp.route("/auth/register", methods=["POST"])
def register_user():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    caller_vendor_id, error = authenticate_vendor_access()
    if error: return error
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1]
    
    user_data = verify_token(token)
    if user_data['role'] not in ['super_admin', 'vendor_admin', 'owner']:
        return jsonify({"error": "Access Denied: Admin or Owner privileges required"}), 403
    data = request.json
    username = data.get("username")
    password = data.get("password")
    role = data.get("role", "user")
    
    target_vendor_id = caller_vendor_id
    if not target_vendor_id:
        target_vendor_id = data.get("vendor_id")

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO system_users (username, password, password_plain, role, vendor_id) VALUES (?, ?, ?, ?, ?)",
            (username, hash_password(password), password, role, target_vendor_id),
        )
        conn.commit()
        return jsonify({"status": "success", "message": "User created"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@auth_bp.route("/parents/register", methods=["POST"])
def register_parent():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    caller_vendor_id, error = authenticate_vendor_access()
    if error: return error
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1]
    
    user_data = verify_token(token)
    if user_data['role'] not in ['super_admin', 'vendor_admin']:
        return jsonify({"error": "Access Denied: Admin privileges required"}), 403
    data = request.json
    username = data.get("username")
    password = data.get("password")
    contact_email = data.get("contact_email")
    contact_phone = data.get("contact_phone")
    target_vendor_id = caller_vendor_id or data.get("vendor_id")
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO parent_users (vendor_id, username, password, contact_email, contact_phone) VALUES (?, ?, ?, ?, ?)",
            (target_vendor_id, username, hash_password(password), contact_email, contact_phone),
        )
        conn.commit()
        return jsonify({"status": "success"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Parent username already exists"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@auth_bp.route("/parents/login", methods=["POST"])
def parent_login():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    data = request.json
    student_id = data.get("student_id")
    mobile_number = data.get("mobile_number")
    device_id = data.get("device_id")
    vendor_id = data.get("vendor_id")
    fcm_token = data.get("fcm_token")
    
    if not student_id or not mobile_number or not device_id or not vendor_id:
        return jsonify({"error": "Missing required fields (student_id, mobile_number, device_id, vendor_id)"}), 400
    conn = get_db_connection()
    try:
        conn.row_factory = sqlite3.Row
    except Exception:
        pass
    c = conn.cursor()
    try:
        def _digits(s):
            try:
                return "".join(ch for ch in str(s or "") if ch.isdigit())
            except Exception:
                return ""
        mobile_digits = _digits(mobile_number)
        mobile_tail = mobile_digits[-10:] if len(mobile_digits) >= 10 else mobile_digits
        def _row_get(r, idx, key):
            if r is None:
                return None
            try:
                return r[key]
            except Exception:
                try:
                    return r[idx]
                except Exception:
                    return None
        row = None
        actual_vendor_id = None
        resolved_person_id = None
        def _extract_student_number_from_custom_data(c_data_raw, fallback_search_text=None):
            if not c_data_raw:
                return ""
            try:
                cd = json.loads(c_data_raw) if isinstance(c_data_raw, str) else c_data_raw
            except Exception:
                cd = None
            sn_val = ""
            if isinstance(cd, dict):
                # Only check for student_id or id_number
                sn_val = str(
                    cd.get("student_id") or 
                    cd.get("id_number") or
                    ""
                ).strip()
            if not sn_val and fallback_search_text and str(student_id).lower() in str(fallback_search_text).lower():
                sn_val = str(student_id).strip()
            return sn_val
        def _find_student_person_id(vendor_to_check):
            try:
                c.execute("SELECT id, phone, custom_data FROM faces WHERE vendor_id = ? AND phone LIKE ?", (vendor_to_check, f"%{mobile_tail}%"))
                candidates2 = c.fetchall() or []
                for st in candidates2:
                    try:
                        pid2 = _row_get(st, 0, "id")
                        c_data2 = _row_get(st, 2, "custom_data")
                        sn2 = _extract_student_number_from_custom_data(c_data2, fallback_search_text=c_data2)
                        if sn2.lower() == str(student_id).strip().lower():
                            return int(pid2) if pid2 is not None else None
                    except Exception:
                        continue
            except Exception:
                pass
            return None
        # Case-insensitive search for student_number in parent_users
        c.execute("SELECT id, vendor_id, device_id, contact_phone, session_version, face_template FROM parent_users WHERE LOWER(student_number) = LOWER(?)", (str(student_id).strip(),))
        candidates = c.fetchall() or []
        for r in candidates:
            cp = _row_get(r, 3, "contact_phone")
            cp_tail = _digits(cp)[-10:]
            if mobile_tail and cp_tail == mobile_tail:
                row = r
                actual_vendor_id = _row_get(r, 1, "vendor_id")
                break
        if row and actual_vendor_id:
            try:
                c.execute("SELECT id, custom_data FROM faces WHERE vendor_id = ? AND phone LIKE ?", (actual_vendor_id, f"%{mobile_tail}%"))
                rows = c.fetchall() or []
                exists = False
                for st in rows:
                    try:
                        c_data = _row_get(st, 1, "custom_data")
                        if not c_data:
                            continue
                        sn = _extract_student_number_from_custom_data(c_data, fallback_search_text=c_data)
                        if sn.lower() == str(student_id).strip().lower():
                            exists = True
                            break
                    except Exception:
                        continue
                if not exists:
                    stale_parent_id = _row_get(row, 0, "id")
                    c.execute("DELETE FROM parent_tokens WHERE vendor_id = ? AND LOWER(student_number) = LOWER(?)", (actual_vendor_id, str(student_id).strip()))
                    c.execute("DELETE FROM student_parents WHERE vendor_id = ? AND parent_id = ?", (actual_vendor_id, stale_parent_id))
                    c.execute("DELETE FROM parent_users WHERE id = ?", (stale_parent_id,))
                    conn.commit()
                    row = None
                    actual_vendor_id = None
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
        if row and vendor_id and actual_vendor_id and str(actual_vendor_id) != str(vendor_id):
            try:
                c.execute("SELECT id, custom_data FROM faces WHERE vendor_id = ? AND phone LIKE ?", (vendor_id, f"%{mobile_tail}%"))
                vv = c.fetchall() or []
                ok = False
                for st in vv:
                    try:
                        cd = _row_get(st, 1, "custom_data")
                        sn = _extract_student_number_from_custom_data(cd, fallback_search_text=cd)
                        if sn.lower() == str(student_id).strip().lower():
                            ok = True
                            resolved_person_id = _row_get(st, 0, "id")
                            break
                    except Exception:
                        continue
                if ok:
                    pid_tmp = _row_get(row, 0, "id")
                    try:
                        c.execute("UPDATE parent_users SET vendor_id = ? WHERE id = ?", (vendor_id, pid_tmp))
                        conn.commit()
                    except Exception:
                        pass
                    actual_vendor_id = vendor_id
                else:
                    row = None
                    actual_vendor_id = None
            except Exception:
                row = None
                actual_vendor_id = None
        if not row:
            is_pg = getattr(conn, "_is_pg", False)
            # Search faces with the provided vendor_id first
            # Search both phone column and custom_data JSON
            if is_pg:
                c.execute("""
                    SELECT id, vendor_id, phone, custom_data FROM faces 
                    WHERE vendor_id = %s AND (
                        phone LIKE %s OR 
                        custom_data::text LIKE %s
                    )
                """, (vendor_id, f"%{mobile_tail}%", f"%{mobile_tail}%"))
            else:
                c.execute("""
                    SELECT id, vendor_id, phone, custom_data FROM faces 
                    WHERE vendor_id = ? AND (
                        phone LIKE ? OR 
                        custom_data LIKE ?
                    )
                """, (vendor_id, f"%{mobile_tail}%", f"%{mobile_tail}%"))
            potential_students = c.fetchall() or []
            
            # If not found with that vendor_id, try searching ALL vendors (for convenience)
            if not potential_students:
                if is_pg:
                    c.execute("SELECT id, vendor_id, phone, custom_data FROM faces WHERE phone LIKE %s OR custom_data::text LIKE %s", (f"%{mobile_tail}%", f"%{mobile_tail}%"))
                else:
                    c.execute("SELECT id, vendor_id, phone, custom_data FROM faces WHERE phone LIKE ? OR custom_data LIKE ?", (f"%{mobile_tail}%", f"%{mobile_tail}%"))
                potential_students = c.fetchall() or []

            def _check_student_match(st_row):
                try:
                    c_data_raw = _row_get(st_row, 3, 'custom_data')
                    if not c_data_raw: return False
                    
                    # If it's already a dict, use it; otherwise parse JSON
                    cd = c_data_raw if isinstance(c_data_raw, dict) else json.loads(c_data_raw)
                    
                    # Extract ID from custom data
                    sn = str(
                        cd.get("student_id") or 
                        cd.get("id_number") or
                        ""
                    ).strip().lower()
                    
                    return sn == str(student_id).strip().lower()
                except Exception:
                    return False

            potential_students = [s for s in potential_students if _check_student_match(s)]
            
            if potential_students:
                try:
                    s = potential_students[0]
                    actual_vendor_id = _row_get(s, 1, "vendor_id")
                    resolved_person_id = int(_row_get(s, 0, "id"))
                    username = f"parent_{actual_vendor_id}_{student_id}"
                    
                    # Ensure parent_users record exists for this vendor/student combo
                    c.execute("INSERT OR IGNORE INTO parent_users (vendor_id, username, student_number, contact_phone, created_at) VALUES (?, ?, ?, ?, ?)", 
                              (actual_vendor_id, username, student_id, mobile_number, datetime.now()))
                    conn.commit()
                    
                    # Fetch the newly created or existing record
                    c.execute("SELECT id, vendor_id, device_id, contact_phone, session_version, face_template FROM parent_users WHERE LOWER(student_number) = LOWER(?) AND vendor_id = ?", 
                              (str(student_id).strip(), actual_vendor_id))
                    row = c.fetchone()
                except Exception as e:
                    logger.error(f"Error creating parent record: {e}")
                    row = None
        if not row:
            conn.close()
            return jsonify({"error": "No identity found"}), 404
        parent_id = _row_get(row, 0, "id")
        actual_vendor_id = _row_get(row, 1, "vendor_id") or actual_vendor_id or vendor_id
        stored_device_id = _row_get(row, 2, "device_id")
        stored_mobile = _row_get(row, 3, "contact_phone")
        session_version = _row_get(row, 4, "session_version") or 1
        face_template = _row_get(row, 5, "face_template")
        if mobile_tail and _digits(stored_mobile)[-10:] != mobile_tail:
            conn.close()
            return jsonify({"error": "Mobile number mismatch"}), 401
        if resolved_person_id is None:
            resolved_person_id = _find_student_person_id(actual_vendor_id)
        
        if resolved_person_id:
            try:
                c.execute("UPDATE parent_users SET selected_person_id = ? WHERE id = ?", (resolved_person_id, parent_id))
                c.execute("INSERT OR IGNORE INTO student_parents (vendor_id, person_id, parent_id) VALUES (?, ?, ?)", (actual_vendor_id, resolved_person_id, parent_id))
                conn.commit()
            except Exception as _e:
                try: conn.rollback()
                except: pass

        token_username = f"parent_{actual_vendor_id}_{student_id}"
        token = generate_token_with_claims(token_username, "parent", {"sv": int(session_version)})

        # Fetch vendor vertical and feature flags for the app to adapt its UI
        vendor_vertical = None
        has_bulk_attendance = False
        try:
            c.execute("SELECT vertical FROM vendors WHERE id = ?", (actual_vendor_id,))
            vrow = c.fetchone()
            if vrow:
                vendor_vertical = vrow[0] if isinstance(vrow, (list, tuple)) else vrow.get('vertical')
            c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (actual_vendor_id,))
            srow = c.fetchone()
            if srow:
                raw = srow[0] if isinstance(srow, (list, tuple)) else srow.get('features')
                feats = json.loads(raw) if isinstance(raw, str) else (list(raw) if raw else [])
                has_bulk_attendance = 'bulk_image_attendance' in feats
        except Exception:
            pass

        conn.close()
        return jsonify({
            "status": "success",
            "token": token,
            "student_id": student_id,
            "role": "parent",
            "vendor_id": actual_vendor_id,
            "parent_id": parent_id,
            "person_id": resolved_person_id,
            "face_registered": bool(face_template),
            "face_template": face_template,
            "vertical": vendor_vertical,
            "has_bulk_attendance": has_bulk_attendance
        })
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

@auth_bp.route("/parents/logout", methods=["POST"])
def parent_logout():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401
    token = extract_token(auth_header)
    if not token:
        return jsonify({"error": "Invalid Token Format"}), 401
    data = verify_token(token)
    if not data or data.get('role') != 'parent':
        return jsonify({"error": "Invalid or Expired Token"}), 401
    conn = get_db_connection()
    c = conn.cursor()
    try:
        token_sv = data.get("sv")
        if token_sv is None:
            return jsonify({"error": "Invalid or Expired Token"}), 401
        c.execute("UPDATE parent_users SET device_id = NULL, fcm_token = NULL, session_version = COALESCE(session_version, 1) + 1 WHERE username = ? AND COALESCE(session_version, 1) = ?", (data['username'], int(token_sv)))
        if getattr(c, "rowcount", 0) == 0:
            return jsonify({"error": "Invalid or Expired Token"}), 401
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@auth_bp.route("/parents/attendance", methods=["GET"])
def get_parent_attendance():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401
    try:
        token = extract_token(auth_header)
        if not token:
            return jsonify({"error": "Invalid Token Format"}), 401
        data = verify_token(token)
        if not data or data.get('role') != 'parent':
            return jsonify({"error": "Invalid or Expired Token"}), 401
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, vendor_id, session_version FROM parent_users WHERE username = ?", (data['username'],))
        pu = c.fetchone()
        if not pu:
            conn.close()
            return jsonify({"error": "Parent not found"}), 404
        token_sv = data.get("sv")
        pu_sv = pu["session_version"] if "session_version" in pu.keys() else 1
        if token_sv is None or int(token_sv) != int(pu_sv or 1):
            conn.close()
            return jsonify({"error": "Invalid or Expired Token"}), 401
        parent_id = pu['id']
        vendor_id = pu['vendor_id']
        limit = int(request.args.get('limit', 50))
        date_filter = (request.args.get('date') or "").strip()
        if not date_filter:
            date_filter = datetime.now().strftime("%Y-%m-%d")
        c.execute("""
            SELECT a.id, a.name, a.timestamp, a.status, a.activity, a.is_late, a.person_id 
            FROM attendance a
            JOIN student_parents sp ON sp.person_id = a.person_id
            WHERE sp.parent_id = ? AND a.vendor_id = ? AND date(a.timestamp) = ?
            ORDER BY a.timestamp DESC
            LIMIT ?
        """, (parent_id, vendor_id, date_filter, limit))
        rows = c.fetchall() or []
        conn.close()
        
        formatted_attendance = []
        for r in rows:
            d = dict(r)
            ts = d.get('timestamp')
            if ts and not isinstance(ts, str):
                try: d['timestamp'] = ts.strftime("%Y-%m-%d %H:%M:%S")
                except: pass
            elif ts and isinstance(ts, str) and 'T' in ts:
                d['timestamp'] = ts.replace('T', ' ')
            formatted_attendance.append(d)

        return jsonify({"attendance": formatted_attendance, "date": date_filter})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@auth_bp.route("/parents/student-day", methods=["GET"])
def parent_student_day():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401
    token = extract_token(auth_header)
    if not token:
        return jsonify({"error": "Invalid Token Format"}), 401
    data = verify_token(token)
    if not data or data.get('role') != 'parent':
        return jsonify({"error": "Invalid or Expired Token"}), 401

    date_filter = (request.args.get("date") or "").strip()
    if not date_filter:
        date_filter = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT id, vendor_id, student_number, selected_person_id, contact_phone, session_version FROM parent_users WHERE username = ?", (data['username'],))
        pu = c.fetchone()
        if not pu:
            return jsonify({"error": "Parent not found"}), 404
        token_sv = data.get("sv")
        pu_sv = pu["session_version"] if "session_version" in pu.keys() else 1
        if token_sv is None or int(token_sv) != int(pu_sv or 1):
            return jsonify({"error": "Invalid or Expired Token"}), 401

        parent_id = pu["id"]
        vendor_id = pu["vendor_id"]
        student_number = str(pu["student_number"] or "").strip()
        person_id = pu["selected_person_id"]
        contact_phone = pu["contact_phone"]

        if not person_id:
            c.execute("SELECT person_id FROM student_parents WHERE vendor_id = ? AND parent_id = ? ORDER BY id DESC LIMIT 1", (vendor_id, parent_id))
            r = c.fetchone()
            if r:
                person_id = r["person_id"]

        student_row = None
        if person_id:
            c.execute("SELECT id, name, phone, department, designation, custom_data, face_image FROM faces WHERE vendor_id = ? AND id = ?", (vendor_id, person_id))
            student_row = c.fetchone()

        if not student_row:
            phone_digits = "".join(ch for ch in str(contact_phone or "") if ch.isdigit())
            phone_tail = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
            c.execute("SELECT id, name, phone, department, designation, custom_data, face_image FROM faces WHERE vendor_id = ? AND phone LIKE ?", (vendor_id, f"%{phone_tail}%"))
            candidates = c.fetchall() or []
            for r in candidates:
                cd_raw = r["custom_data"]
                sn = ""
                try:
                    cd = json.loads(cd_raw) if cd_raw else {}
                    sn = str(cd.get("student_id") or cd.get("id_number") or "").strip()
                except Exception:
                    sn = ""
                if student_number and sn == student_number:
                    student_row = r
                    person_id = r["id"]
                    break
            if not student_row and not student_number:
                if candidates:
                    student_row = candidates[0]
                    person_id = candidates[0]["id"]

        if not student_row:
            return jsonify({"error": "No identity found"}), 404

        c.execute(
            """
            SELECT id, name, timestamp, status, activity, is_late, person_id
            FROM attendance
            WHERE vendor_id = ? AND person_id = ? AND date(timestamp) = ?
            ORDER BY timestamp ASC
            """,
            (vendor_id, person_id, date_filter),
        )
        rows = c.fetchall() or []
        attendance = []
        for r in rows:
            d = dict(r)
            ts = d.get('timestamp')
            if ts and not isinstance(ts, str):
                try: d['timestamp'] = ts.strftime("%Y-%m-%d %H:%M:%S")
                except: pass
            elif ts and isinstance(ts, str) and 'T' in ts:
                d['timestamp'] = ts.replace('T', ' ')
            attendance.append(d)

        check_in = None
        check_out = None
        last_status = None
        for r in attendance:
            st = r.get("status")
            if st:
                last_status = st
            if st == "CHECK_IN" and not check_in:
                check_in = r.get("timestamp")
            if st == "CHECK_OUT":
                check_out = r.get("timestamp")

        student_custom = {}
        try:
            student_custom = json.loads(student_row["custom_data"]) if student_row["custom_data"] else {}
        except Exception:
            student_custom = {}

        return jsonify({
            "date": date_filter,
            "vendor_id": vendor_id,
            "student": {
                "person_id": student_row["id"],
                "name": student_row["name"],
                "phone": student_row["phone"],
                "department": student_row["department"] if "department" in (student_row.keys() if hasattr(student_row, 'keys') else []) else None,
                "designation": student_row["designation"] if "designation" in (student_row.keys() if hasattr(student_row, 'keys') else []) else None,
                "student_number": student_custom.get("student_number") or student_number,
                "face_image": base64.b64encode(student_row["face_image"]).decode('utf-8') if student_row["face_image"] else None,
                "custom_data": student_custom,
            },
            "check_in": check_in,
            "check_out": check_out,
            "last_status": last_status,
            "attendance": attendance,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@auth_bp.route("/parents/select-student", methods=["POST"])
def parent_select_student():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401
    try:
        from services.auth_service import extract_token, verify_token
        token = extract_token(auth_header)
        if not token:
            return jsonify({"error": "Invalid Token Format"}), 401
        data = verify_token(token)
        if not data or data.get('role') != 'parent':
            return jsonify({"error": "Invalid or Expired Token"}), 401
        body = request.json or {}
        student_number = body.get("student_number")
        if not student_number:
            return jsonify({"error": "student_number required"}), 400
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, vendor_id, session_version FROM parent_users WHERE username = ?", (data['username'],))
        pu = c.fetchone()
        if not pu:
            conn.close()
            return jsonify({"error": "Parent not found"}), 404
        token_sv = data.get("sv")
        pu_sv = pu["session_version"] if "session_version" in pu.keys() else 1
        if token_sv is None or int(token_sv) != int(pu_sv or 1):
            conn.close()
            return jsonify({"error": "Invalid or Expired Token"}), 401
        parent_id = pu['id']
        vendor_id = pu['vendor_id']
        
        c.execute("SELECT id, name, custom_data FROM faces WHERE vendor_id = ? AND custom_data IS NOT NULL", (vendor_id,))
        rows = c.fetchall()
        selected = None
        for r in rows:
            try:
                cd = json.loads(r['custom_data'])
                if str(cd.get('student_id') or cd.get('id_number') or '').strip() == str(student_number).strip():
                    selected = r
                    break
            except Exception:
                pass
        if not selected:
            conn.close()
            return jsonify({"error": "Student not found"}), 404
        person_id = selected['id']
        c.execute("UPDATE parent_users SET student_number = ?, selected_person_id = ? WHERE id = ?", (student_number, person_id, parent_id))
        c.execute("DELETE FROM student_parents WHERE parent_id = ? AND vendor_id = ?", (parent_id, vendor_id))
        c.execute("INSERT OR IGNORE INTO student_parents (vendor_id, person_id, parent_id) VALUES (?, ?, ?)", (vendor_id, person_id, parent_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "person_id": person_id, "name": selected['name'], "student_number": student_number})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    # Accept token from Authorization header OR httpOnly cookie (web sessions)
    auth_header = request.headers.get('Authorization')
    token = None
    if auth_header:
        try:
            token = auth_header.split(" ")[1]
        except:
            pass
    if not token:
        token = request.cookies.get('token')

    data = request.json or {}
    username = data.get("username")
    device_id = data.get("device_id")

    if not token and not (username and device_id):
        return jsonify({"error": "Token or credentials required"}), 400

    conn = get_db_connection()
    c = conn.cursor()

    try:
        if token:
            c.execute("DELETE FROM active_sessions WHERE token = ?", (token,))

        if username and device_id:
            c.execute("DELETE FROM active_sessions WHERE username = ? AND device_id = ?", (username, device_id))

        conn.commit()
        conn.close()
        resp = make_response(jsonify({"status": "success", "message": "Logged out"}))
        resp.delete_cookie('token', path='/')
        return resp
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
@auth_bp.route("/student/verify-password", methods=["POST"])
def verify_student_password():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400
        
    conn = get_db_connection()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        placeholder = "%s" if is_pg else "?"
        c = conn.cursor()
        c.execute(f"SELECT * FROM system_users WHERE username = {placeholder} AND role = 'user'", (username,))
        user = c.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
            
        user_dict = dict(user)
        stored_pw = user_dict.get("password")
        
        from services.auth_service import verify_password, generate_token
        if verify_password(password, stored_pw):
            # Student PIN/Password verified. Return full login response including token.
            token = generate_token(username, user_dict.get('role', 'user'), user_dict.get('vendor_id'))
            
            # Record activation or update session
            device_id = request.json.get('device_id', 'web-student')
            
            try:
                is_pg = getattr(conn, "_is_pg", False)
                placeholder = "%s" if is_pg else "?"
                c.execute(f"DELETE FROM active_sessions WHERE username = {placeholder} AND platform = 'web' AND device_id = {placeholder}", (username, device_id))
                
                # Cleanup stale web sessions (older than 12h)
                if is_pg:
                    c.execute(f"DELETE FROM active_sessions WHERE platform = 'web' AND last_active < (NOW() - INTERVAL '12 hours')")
                else:
                    c.execute(f"DELETE FROM active_sessions WHERE platform = 'web' AND last_active < datetime('now','-12 hours')")
                
                c.execute(
                    f"INSERT INTO active_sessions (token, username, vendor_id, device_id, platform, last_active) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, 'web', {placeholder})",
                    (token, username, user_dict.get('vendor_id'), device_id, datetime.now())
                )
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to record session in verify_password: {e}")

            return jsonify({
                "status": "success",
                "username": username,
                "role": user_dict.get('role'),
                "token": token,
                "vendor_id": user_dict.get('vendor_id'),
                "person_id": user_dict.get('person_id'),
                "message": "Login successful"
            })
        else:
            return jsonify({"error": "Invalid custom password"}), 401
    finally:
        conn.close()

@auth_bp.route("/auth/student/reset-to-default", methods=["POST"])
def reset_student_password_to_default():
    from services.auth_service import extract_token, verify_token, hash_password
    from app import get_db_connection
    
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401
    
    token = extract_token(auth_header)
    data = verify_token(token)
    if not data or data.get('role') != 'user':
        return jsonify({"error": "Unauthorized: Student access required"}), 401
    
    username = data['username']
    
    conn = get_db_connection()
    try:
        if not getattr(conn, "_is_pg", False):
            conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # 1. Get student's person_id from system_users
        c.execute("SELECT person_id, vendor_id FROM system_users WHERE username = ?", (username,))
        user_row = c.fetchone()
        if not user_row:
            return jsonify({"error": "User record not found"}), 404
        
        user_dict = dict(user_row)
        person_id = user_dict.get('person_id')
        
        if not person_id:
            return jsonify({"error": "Student profile not linked. Contact Admin."}), 400
            
        # 2. Get registered mobile number from faces table
        c.execute("SELECT phone FROM faces WHERE id = ?", (person_id,))
        face_row = c.fetchone()
        if not face_row:
            return jsonify({"error": "Student identity profile not found"}), 404
            
        face_dict = dict(face_row)
        phone = face_dict.get('phone')
        if not phone:
             return jsonify({"error": "No mobile number found in your profile"}), 400
             
        # 3. Reset password back to the mobile number
        hashed_pw = hash_password(phone)
        c.execute(
            "UPDATE system_users SET password = ?, password_plain = ?, has_set_password = 0 WHERE username = ?", 
            (hashed_pw, phone, username)
        )
        conn.commit()
        
        logger.info(f"Student {username} reset password to default (mobile: {phone})")
        return jsonify({"status": "success", "message": "Password reset to registered mobile number. Please login again."})
    except Exception as e:
        logger.error(f"Error resetting student password: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
