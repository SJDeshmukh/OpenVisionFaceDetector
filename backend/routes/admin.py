from flask import Blueprint, request, jsonify, send_file, g
import logging
logger = logging.getLogger(__name__)
import sqlite3
from datetime import datetime, date, timedelta
import json
import base64
import re
import os
import math
import secrets
import qrcode
from io import BytesIO
from utils import (
    _run, log_audit, ALL_FEATURES, BUNDLE_FEATURES, REGISTRATION_TEMPLATES,
    cache_get, cache_set, cache_delete, reset_sequence, create_job, complete_job, fail_job, get_db_connection
)
from db_factory import get_table_columns
try:
    from celery_app import celery
except Exception:
    celery = None

# Import from services
from services.auth_service import (
    authenticate_vendor_access,
    verify_token,
    extract_token,
    hash_password,
    verify_password,
    generate_token,
)
from services.restoration_service import run_restore
from services.person_scope_service import (
    is_school_hostel,
    person_type_for,
    requested_person_type,
    vendor_vertical,
)

def trigger_model_download_if_needed(features):
    """Background task to ensure heavy AI models are downloaded if bulk_image_attendance is selected."""
    if not features:
        return
    if 'bulk_image_attendance' in features:
        try:
            # We use a thread or separate process to not block the API response
            import threading
            from download_models import run_full_download
            print(f"[ADMIN] Feature 'bulk_image_attendance' detected. Triggering AI model pre-download...", flush=True)
            threading.Thread(target=run_full_download, daemon=True).start()
        except Exception as e:
            print(f"[ADMIN] Error triggering model download: {e}", flush=True)

# Authentication decorators - these might be defined in app.py, so we will import them locally or they might need to be resolved.
def super_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        _, error = authenticate_vendor_access()
        if error:
            return error
        if g.user_role != 'super_admin':
            return jsonify({"error": "Super Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        _, error = authenticate_vendor_access()
        if error:
            return error
        if g.user_role not in ['super_admin', 'vendor_admin']:
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
        _, error = authenticate_vendor_access()
        if error:
            return error
        if g.user_role != 'super_admin':
            return jsonify({"error": "Super Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

def admin_role_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        _, error = authenticate_vendor_access()
        if error:
            return error
        if g.user_role not in ['super_admin', 'vendor_admin']:
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



admin_bp = Blueprint('admin_bp', __name__)


# --- Extracted Admin Routes ---


@admin_bp.route("/audit-logs", methods=["GET"])
@super_admin_required
def get_audit_logs():
    from app import socketio, is_testing
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    data = request.get_json(silent=True) or {}
    vendor_id = data.get('vendor_id')
    
    if not vendor_id:
        return jsonify({"error": "Vendor ID required"}), 400
        
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Find the admin user for this vendor
    c.execute("SELECT username, role FROM system_users WHERE vendor_id = ? AND role = 'vendor_admin' LIMIT 1", (vendor_id,))
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
            current_token = auth_header.split(" ")[1]
            current_user = verify_token(current_token)
            actor = current_user['username'] if current_user else 'unknown'
        else:
            actor = 'system'
    except Exception:
        logger.debug("Actor token lookup failed", exc_info=True)
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT id, device_id, device_name, registered_at, last_login_at, 
                   last_active_at, battery_level, geofence_lat, geofence_lng, geofence_radius, last_lat, last_lng 
            FROM vendor_devices 
            WHERE vendor_id = ? 
            ORDER BY registered_at DESC
        """, (vendor_id,))
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
    from app import socketio, is_testing
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

@admin_bp.route("/vendors/<int:vendor_id>/devices/<device_id>/geofence", methods=["PUT"])
@super_admin_required
def update_device_geofence(vendor_id, device_id):
    data = request.json or {}
    radius = data.get("radius_meters")
    lat = data.get("latitude")
    lng = data.get("longitude")
    reset_anchor = bool(data.get("reset_anchor", False))
    
    # Validation for radius
    if radius is not None and str(radius).strip() != "":
        try:
            radius = float(radius)
            if radius <= 0: radius = None
        except ValueError:
            return jsonify({"error": "Invalid radius"}), 400
    else:
        radius = None

    # Validation for coordinates if provided
    latitude = None
    longitude = None
    if lat is not None and str(lat).strip() != "":
        try:
            latitude = float(lat)
            if not (-90.0 <= latitude <= 90.0):
                return jsonify({"error": "Latitude must be between -90 and 90"}), 400
        except ValueError:
            return jsonify({"error": "Invalid latitude"}), 400

    if lng is not None and str(lng).strip() != "":
        try:
            longitude = float(lng)
            if not (-180.0 <= longitude <= 180.0):
                return jsonify({"error": "Longitude must be between -180 and 180"}), 400
        except ValueError:
            return jsonify({"error": "Invalid longitude"}), 400

    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Check if device exists
        c.execute("SELECT id FROM vendor_devices WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
        if not c.fetchone():
            conn.close()
            return jsonify({"error": "Device not found"}), 404
            
        if radius is None:
            # Completely disable geofencing
            c.execute("""
                UPDATE vendor_devices 
                SET geofence_radius = NULL, geofence_lat = NULL, geofence_lng = NULL 
                WHERE vendor_id = ? AND device_id = ?
            """, (vendor_id, device_id))
        elif latitude is not None and longitude is not None:
            # Set explicit coordinates and radius
            c.execute("""
                UPDATE vendor_devices 
                SET geofence_radius = ?, geofence_lat = ?, geofence_lng = ? 
                WHERE vendor_id = ? AND device_id = ?
            """, (radius, latitude, longitude, vendor_id, device_id))
        elif reset_anchor:
            # Clear anchor coordinates (to be recaptured on next mobile heartbeat)
            c.execute("""
                UPDATE vendor_devices 
                SET geofence_radius = ?, geofence_lat = NULL, geofence_lng = NULL 
                WHERE vendor_id = ? AND device_id = ?
            """, (radius, vendor_id, device_id))
        else:
            # Update radius only, retaining existing anchor
            c.execute("""
                UPDATE vendor_devices 
                SET geofence_radius = ? 
                WHERE vendor_id = ? AND device_id = ?
            """, (radius, vendor_id, device_id))
            
        conn.commit()
        conn.close()
        return jsonify({"success": True, "geofence_radius": radius, "geofence_lat": latitude, "geofence_lng": longitude})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/fleet/telemetry", methods=["GET"])
@super_admin_required
def get_fleet_telemetry():
    try:
        conn = get_db_connection()
        try:
            if not getattr(conn, "_is_pg", False):
                conn.row_factory = sqlite3.Row
        except Exception:
            pass
        c = conn.cursor()
        
        query = """
            SELECT d.id, d.vendor_id, v.company_name, v.vertical,
                   d.device_id, d.device_name, d.registered_at, 
                   d.last_active_at, d.last_login_at, d.battery_level,
                   d.geofence_lat, d.geofence_lng, d.geofence_radius,
                   d.last_lat, d.last_lng
            FROM vendor_devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
            ORDER BY d.last_active_at DESC
        """
        c.execute(query)
        rows = [dict(r) if hasattr(r, 'keys') or isinstance(r, dict) else {
            'id': r[0], 'vendor_id': r[1], 'company_name': r[2], 'vertical': r[3],
            'device_id': r[4], 'device_name': r[5], 'registered_at': r[6],
            'last_active_at': r[7], 'last_login_at': r[8], 'battery_level': r[9],
            'geofence_lat': r[10], 'geofence_lng': r[11], 'geofence_radius': r[12],
            'last_lat': r[13], 'last_lng': r[14]
        } for r in c.fetchall() or []]
        conn.close()
        
        now = datetime.now()
        devices = []
        from routes.vendor import haversine_distance

        for r in rows:
            last_active = r.get("last_active_at")
            is_online = False
            if last_active:
                try:
                    if isinstance(last_active, str):
                        clean_str = last_active.replace('Z', '').split('.')[0]
                        dt = datetime.fromisoformat(clean_str)
                    else:
                        dt = last_active
                    is_online = (now - dt).total_seconds() < 300
                except Exception:
                    pass

            anchor_lat = r.get("geofence_lat")
            anchor_lng = r.get("geofence_lng")
            radius = r.get("geofence_radius")
            last_lat = r.get("last_lat")
            last_lng = r.get("last_lng")
            
            distance = None
            geofence_status = "disabled"
            if radius and float(radius) > 0:
                if last_lat is not None and last_lng is not None and anchor_lat is not None and anchor_lng is not None:
                    dist = haversine_distance(float(anchor_lat), float(anchor_lng), float(last_lat), float(last_lng))
                    distance = round(dist, 1)
                    geofence_status = "outside" if dist > float(radius) else "inside"
                elif last_lat is None or last_lng is None:
                    geofence_status = "no_gps"
                else:
                    geofence_status = "inside"

            r["is_online"] = is_online
            r["distance_meters"] = distance
            r["geofence_status"] = geofence_status

            # Standardize coordinates and vendor fields for map components
            lat_f = None
            lng_f = None
            if last_lat is not None and str(last_lat).strip() != "":
                try: lat_f = float(last_lat)
                except Exception: lat_f = None

            if last_lng is not None and str(last_lng).strip() != "":
                try: lng_f = float(last_lng)
                except Exception: lng_f = None

            g_lat_f = None
            g_lng_f = None
            if anchor_lat is not None and str(anchor_lat).strip() != "":
                try: g_lat_f = float(anchor_lat)
                except Exception: g_lat_f = None

            if anchor_lng is not None and str(anchor_lng).strip() != "":
                try: g_lng_f = float(anchor_lng)
                except Exception: g_lng_f = None

            r["latitude"] = lat_f
            r["longitude"] = lng_f
            r["last_lat"] = lat_f
            r["last_lng"] = lng_f
            r["geofence_latitude"] = g_lat_f
            r["geofence_longitude"] = g_lng_f
            r["geofence_lat"] = g_lat_f
            r["geofence_lng"] = g_lng_f
            r["vendor_name"] = r.get("company_name") or f"Vendor {r.get('vendor_id')}"

            devices.append(r)

        return jsonify({"status": "success", "devices": devices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/vendors/<int:vendor_id>/devices/<device_id>/assign-slot", methods=["POST"])
@super_admin_required
def admin_assign_device_slot(vendor_id, device_id):
    from app import socketio, is_testing
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    try:
        logger.info(f"DELETE request for vendor_id={vendor_id}, device_id={device_id}")
        
        conn = get_db_connection()
        c = conn.cursor()
        
        # Defensive check for optional tables to avoid PostgreSQL transaction aborts
        def safe_execute(query, params, table=None, cols=None):
            is_pg = getattr(conn, "_is_pg", False)
            if is_pg:
                # Use SAVEPOINT to protect the main transaction from optional query failures
                try:
                    c.execute("SAVEPOINT cleanup_step")
                except Exception:
                    pass

            try:
                if table and cols:
                    # Check if all required columns exist in the table
                    existing_cols = get_table_columns(conn, table)
                    if not existing_cols:
                        logger.warning(f"Table '{table}' does not exist, skipping query.")
                        if is_pg:
                            try: c.execute("RELEASE SAVEPOINT cleanup_step")
                            except Exception: pass
                        return 0
                    missing_cols = [col for col in cols if col not in existing_cols]
                    if missing_cols:
                        logger.warning(f"Columns {missing_cols} missing in table '{table}', skipping query.")
                        if is_pg:
                            try: c.execute("RELEASE SAVEPOINT cleanup_step")
                            except Exception: pass
                        return 0
                
                c.execute(query, params)
                if is_pg:
                    try: c.execute("RELEASE SAVEPOINT cleanup_step")
                    except Exception: pass
                return c.rowcount
            except Exception as e:
                logger.error(f"Execution failed for optional cleanup on table '{table}': {e}. Skipping this step to protect deletion.")
                if is_pg:
                    try:
                        c.execute("ROLLBACK TO SAVEPOINT cleanup_step")
                    except Exception as rollback_err:
                        logger.error(f"Critical: Failed to rollback savepoint: {rollback_err}")
                return 0

        # Optional Cleanups
        # 1. Unassign slots
        rows = safe_execute(
            "UPDATE vendor_device_slots SET assigned_device_id = NULL, assigned_at = NULL WHERE vendor_id = ? AND assigned_device_id = ?",
            (vendor_id, device_id),
            table="vendor_device_slots",
            cols=["vendor_id", "assigned_device_id"]
        )
        logger.info(f"Unassigned slots: {rows}")

        # 2. Delete active sessions
        rows = safe_execute(
            "DELETE FROM active_sessions WHERE vendor_id = ? AND device_id = ?",
            (vendor_id, device_id),
            table="active_sessions",
            cols=["vendor_id", "device_id"]
        )
        logger.info(f"Deleted sessions: {rows}")

        # 3. Update parent users
        rows = safe_execute(
            "UPDATE parent_users SET device_id = NULL, fcm_token = NULL, session_version = COALESCE(session_version, 1) + 1 WHERE vendor_id = ? AND device_id = ?",
            (vendor_id, device_id),
            table="parent_users",
            cols=["vendor_id", "device_id", "fcm_token", "session_version"]
        )
        logger.info(f"Updated parent users: {rows}")

        # 4. Delete parent tokens
        rows = safe_execute(
            "DELETE FROM parent_tokens WHERE vendor_id = ? AND device_id = ?",
            (vendor_id, device_id),
            table="parent_tokens",
            cols=["vendor_id", "device_id"]
        )
        logger.info(f"Deleted parent tokens: {rows}")

        # Core Deletion (Critical)
        # We perform this last and without the 'safe_execute' helper to ensure it bubbles up errors if the main table is broken.
        c.execute("DELETE FROM vendor_devices WHERE vendor_id = ? AND device_id = ?", (vendor_id, device_id))
        rows_deleted = c.rowcount
        logger.info(f"Deleted device record from vendor_devices: {rows_deleted}")
        
        conn.commit()
        
        try:
            socketio.emit("vendor_updated", {"vendor_id": vendor_id}, room="super_admin")
            socketio.emit("device_removed", {"vendor_id": vendor_id, "device_id": device_id}, room=f"vendor_{vendor_id}")
            socketio.emit("force_logout_mobile", {"vendor_id": vendor_id, "device_id": device_id, "reason": "Device deleted by admin"}, room=f"vendor_{vendor_id}")
            logger.info("Socket events emitted")
        except Exception as e:
            logger.warning(f"Socket emit error: {e}")
            pass

        conn.close()

        # Invalidate stats cache so summary cards update
        cache_delete("admin_stats")

        log_audit("device_delete", {"device_id": device_id}, target_vendor_id=vendor_id)
        return jsonify({"success": True, "rows_deleted": rows_deleted})
    except Exception as e:
        logger.error(f"Error in delete_vendor_device: {e}", exc_info=True)
        try:
            if 'conn' in locals() and conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/devices/<device_id>/logout", methods=["POST"])
@super_admin_required
def logout_vendor_device(vendor_id, device_id):
    from app import socketio, is_testing
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
            socketio.emit("force_logout_mobile", {"vendor_id": vendor_id, "device_id": device_id, "reason": "Remote logout by admin"}, room=f"vendor_{vendor_id}")
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
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
    from app import socketio, is_testing
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
    from app import socketio, is_testing
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
        c.execute("UPDATE system_users SET password = ?, password_plain = NULL WHERE username = ?", (hash_password(new_password), target_username))
        conn.commit()
        
        return jsonify({"success": True, "message": f"Password for {target_username} updated."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/stats", methods=["GET"])
@super_admin_required
def get_admin_stats():
    from app import socketio, is_testing, latest_frames
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
    
    # 5. Device Health Stats
    # Offline: last_active_at < 5 minutes ago or null
    is_pg = getattr(conn, "_is_pg", False)
    five_mins_ago = (datetime.now() - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    placeholder = '%s' if is_pg else '?'
    c.execute(f"SELECT COUNT(*) FROM vendor_devices WHERE last_active_at < {placeholder} OR last_active_at IS NULL", (five_mins_ago,))
    offline_devices = c.fetchone()[0]
    
    # Low Battery: battery_level < 20
    c.execute("SELECT COUNT(*) FROM vendor_devices WHERE battery_level < 20")
    low_battery_devices = c.fetchone()[0]
    
    # 6. Revenue (Simple Sum of monthly costs for active subscriptions)
    # This is an estimate based on active plans
    if is_pg:
        c.execute("""
            SELECT SUM(
                (COALESCE(cost_per_user, 0) * COALESCE(max_users, 0)) + 
                (COALESCE(cost_per_employee, 0) * COALESCE(max_employees, 0))
            ) 
            FROM subscriptions 
            WHERE end_date >= CURRENT_DATE
        """)
    else:
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
        "offline_devices": offline_devices,
        "low_battery_devices": low_battery_devices,
        "active_streaming_devices": active_streaming_devices,
        "monthly_recurring_revenue": monthly_revenue
    }
    cache_set("admin_stats", result, 300) # 5 min cache
    return jsonify(result)

@admin_bp.route("/vendors", methods=["GET"])
@super_admin_required
def get_vendors():
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get Vendors with Subscription Details
    try:
        subs_cols = get_table_columns(conn, "subscriptions")
    except Exception:
        subs_cols = []
    max_web_select = "s.max_web_sessions" if "max_web_sessions" in subs_cols else "1 AS max_web_sessions"
    xchat_select = ", ".join([
        "s.xchat_billing_mode" if "xchat_billing_mode" in subs_cols else "'payg' AS xchat_billing_mode",
        "s.xchat_token_limit" if "xchat_token_limit" in subs_cols else "0 AS xchat_token_limit",
        "s.xchat_tokens_used" if "xchat_tokens_used" in subs_cols else "0 AS xchat_tokens_used",
        "s.xchat_input_tokens" if "xchat_input_tokens" in subs_cols else "0 AS xchat_input_tokens",
        "s.xchat_output_tokens" if "xchat_output_tokens" in subs_cols else "0 AS xchat_output_tokens",
        "s.xchat_tokens_billed" if "xchat_tokens_billed" in subs_cols else "0 AS xchat_tokens_billed",
        "s.xchat_price_per_1k_tokens" if "xchat_price_per_1k_tokens" in subs_cols else "0 AS xchat_price_per_1k_tokens",
    ])

    vendor_cols = get_table_columns(conn, "vendors")
    sys_user_cols = get_table_columns(conn, "system_users")
    has_kiosk_username_col = "kiosk_username" in vendor_cols
    has_is_kiosk_col = "is_kiosk" in sys_user_cols

    kiosk_filter = "(is_kiosk = 1 OR person_id IS NULL)" if has_is_kiosk_col else "(person_id IS NULL)"
    kiosk_order = "CASE WHEN is_kiosk = 1 THEN 0 WHEN person_id IS NULL THEN 1 ELSE 2 END, " if has_is_kiosk_col else ""

    if has_kiosk_username_col:
        user_user_select = f"""COALESCE(
            NULLIF(v.kiosk_username, ''),
            (SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'user' AND {kiosk_filter} ORDER BY {kiosk_order}username ASC LIMIT 1)
        ) as user_username"""
    else:
        user_user_select = f"""(SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'user' AND {kiosk_filter} ORDER BY {kiosk_order}username ASC LIMIT 1) as user_username"""

    query = f"""
        SELECT v.*, 
               s.plan_type, s.start_date, s.end_date, s.max_users, s.max_employees, s.max_mobile_devices, {max_web_select}, s.cost_per_user, s.cost_per_employee, s.setup_fee, s.setup_fee_paid, s.features, {xchat_select},
               ws.status AS whatsapp_status, ws.phone_number AS whatsapp_phone,
               (SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'vendor_admin' LIMIT 1) as admin_username,
               NULL as admin_password,
               {user_user_select},
               NULL as user_password,
               (SELECT COUNT(*) FROM system_users WHERE vendor_id = v.id AND role = 'vendor_admin') as admin_count,
               (SELECT COUNT(*) FROM vendor_devices WHERE vendor_id = v.id) as device_count,
               (SELECT COUNT(*) FROM faces WHERE vendor_id = v.id) as employee_count
        FROM vendors v
        LEFT JOIN subscriptions s ON v.id = s.vendor_id
        LEFT JOIN vendor_whatsapp_settings ws ON v.id = ws.vendor_id
        ORDER BY v.created_at DESC
    """
    c.execute(query)
    
    rows = c.fetchall()
    
    # Pre-fetch system_settings for threshold and cooldown in a single query to eliminate N+1 queries
    settings_cache = {}
    need_settings = any(r.get("threshold") is None or r.get("cooldown") is None for r in rows)
    if need_settings:
        try:
            c.execute("SELECT key, value FROM system_settings WHERE key LIKE 'threshold_vendor_%' OR key LIKE 'cooldown_vendor_%'")
            for s_row in (c.fetchall() or []):
                try:
                    sk = s_row['key'] if hasattr(s_row, 'keys') else s_row[0]
                    sv = s_row['value'] if hasattr(s_row, 'keys') else s_row[1]
                    settings_cache[sk] = sv
                except Exception:
                    pass
        except Exception:
            pass

    vendors = []
    for row in rows:
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

        # Ensure threshold and cooldown are populated for SuperAdmin without N+1 queries
        if v.get("threshold") is None:
            raw_t = settings_cache.get(f"threshold_vendor_{v['id']}")
            try: v["threshold"] = float(raw_t) if raw_t else 0.60
            except: v["threshold"] = 0.60
        else:
            try: v["threshold"] = float(v["threshold"])
            except: v["threshold"] = 0.60

        if v.get("cooldown") is None:
            raw_c = settings_cache.get(f"cooldown_vendor_{v['id']}")
            try: v["cooldown"] = int(raw_c) if raw_c else 30
            except: v["cooldown"] = 30
        else:
            try: v["cooldown"] = int(v["cooldown"])
            except: v["cooldown"] = 30

        # Calculate status based on subscription
        if v.get('features'):
            try:
                v['features'] = json.loads(v['features'])
            except (json.JSONDecodeError, ValueError):
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
        
    # Fetch all owners for these vendors to avoid N+1 query problem
    if vendors:
        vendor_ids = [v['id'] for v in vendors]
        placeholders = ", ".join(["?"] * len(vendor_ids))
        c.execute(f"SELECT username, vendor_id FROM system_users WHERE role = 'owner' AND vendor_id IN ({placeholders})", vendor_ids)
        owner_rows = c.fetchall()
        
        # Map owners to vendors
        owners_map = {}
        for row in owner_rows:
            vid = row['vendor_id'] if not hasattr(row, "keys") else row["vendor_id"]
            uname = row['username'] if not hasattr(row, "keys") else row["username"]
            if vid not in owners_map:
                owners_map[vid] = []
            owners_map[vid].append({"username": uname})
            
        for v in vendors:
            v['owners'] = owners_map.get(v['id'], [])

    conn.close()
    return jsonify({"vendors": vendors})

@admin_bp.route("/features", methods=["GET"])
@super_admin_required
def get_available_features():
    from app import socketio, is_testing
    return jsonify({"features": ALL_FEATURES, "bundles": BUNDLE_FEATURES})


@admin_bp.route("/vendors/<int:vendor_id>/automated-report-schedule", methods=["GET"])
@super_admin_required
def get_automated_report_schedule(vendor_id):
    from services.automated_reports_service import get_schedule
    from services.email_service import smtp_is_configured
    try:
        return jsonify({"schedule": get_schedule(vendor_id), "smtp_configured": smtp_is_configured()})
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404


@admin_bp.route("/vendors/<int:vendor_id>/automated-report-schedule", methods=["PUT"])
@super_admin_required
def update_automated_report_schedule(vendor_id):
    from services.automated_reports_service import save_schedule
    payload = request.json or {}
    if payload.get("enabled"):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        row = c.fetchone()
        conn.close()
        try:
            features = json.loads(row[0] or "[]") if row else []
        except Exception:
            features = []
        if "automated_email_reports" not in features:
            return jsonify({"error": "Enable the Automated Email Reports feature before activating its schedule"}), 400
    try:
        schedule = save_schedule(vendor_id, payload)
        log_audit("automated_report_schedule_update", {
            "enabled": schedule["enabled"], "frequencies": schedule["frequencies"],
            "send_time": schedule["send_time"], "timezone": schedule["timezone"],
        }, target_vendor_id=vendor_id)
        return jsonify({"success": True, "schedule": schedule})
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@admin_bp.route("/vendors/<int:vendor_id>/automated-report-deliveries", methods=["GET"])
@super_admin_required
def get_automated_report_deliveries(vendor_id):
    try:
        limit = max(1, min(int(request.args.get("limit", 20)), 100))
    except ValueError:
        limit = 20
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT id, frequency, period_start, period_end, status, attempts,
                   recipient_email, message_id, error, created_at, sent_at
            FROM automated_report_deliveries WHERE vendor_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (vendor_id, limit))
        return jsonify({"deliveries": [dict(row) for row in (c.fetchall() or [])]})
    finally:
        conn.close()


@admin_bp.route("/vendors/<int:vendor_id>/edit-details", methods=["GET"])
@super_admin_required
def get_vendor_edit_details(vendor_id):
    from services.automated_reports_service import serialize_schedule
    from services.email_service import smtp_is_configured
    from services.config_utils import hydrate_registration_config

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        # 1. Fetch vendor email, vertical, registration_config
        c.execute("SELECT email, vertical, registration_config FROM vendors WHERE id = ?", (vendor_id,))
        v_row = c.fetchone()
        if not v_row:
            return jsonify({"error": "Vendor not found"}), 404

        v_dict = dict(v_row)
        vendor_email = v_dict.get("email") or ""
        config_raw = v_dict.get("registration_config")
        config_data = []
        if config_raw:
            try:
                config_data = json.loads(config_raw) if isinstance(config_raw, str) else config_raw
            except Exception:
                config_data = []

        if not config_data:
            try:
                c.execute("SELECT fields FROM bulk_attendance_config WHERE vendor_id = ?", (vendor_id,))
                b_row = c.fetchone()
                if b_row and b_row[0]:
                    b_fields = json.loads(b_row[0])
                    for f in b_fields:
                        fname = f.get('name') or f.get('field')
                        if fname:
                            config_data.append({
                                "field": fname,
                                "name": fname,
                                "label": f.get('label', fname),
                                "type": f.get('type', 'text'),
                                "required": bool(f.get('required', False)),
                                "options": f.get('options', []),
                                "enabled": True
                            })
            except Exception as ex:
                logger.warning(f"Error reading bulk_attendance_config fallback: {ex}")

        for item in config_data:
            if isinstance(item, dict):
                f_val = item.get('field') or item.get('name')
                if f_val:
                    item['field'] = f_val
                    item['name'] = f_val

        hydrated_config = hydrate_registration_config(vendor_id, config_data, conn=conn) if config_data else []

        # 2. Fetch automated report schedule
        c.execute("SELECT * FROM automated_report_schedules WHERE vendor_id = ?", (vendor_id,))
        sched_row = c.fetchone()
        schedule = serialize_schedule(sched_row, vendor_email)
        smtp_conf = smtp_is_configured()

        # 3. Fetch automated report deliveries (limit 10)
        c.execute("""
            SELECT id, frequency, period_start, period_end, status, attempts,
                   recipient_email, message_id, error, created_at, sent_at
            FROM automated_report_deliveries WHERE vendor_id = ?
            ORDER BY created_at DESC LIMIT 10
        """, (vendor_id,))
        deliveries = [dict(row) for row in (c.fetchall() or [])]

        # 4. Fetch subscription (for latest echo)
        c.execute("SELECT * FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        sub_row = c.fetchone()
        sub_dict = dict(sub_row) if sub_row else None

        return jsonify({
            "registration_config": hydrated_config,
            "report_schedule": schedule,
            "smtp_configured": smtp_conf,
            "report_deliveries": deliveries,
            "subscription": sub_dict
        })
    except Exception as e:
        logger.error(f"Error in get_vendor_edit_details: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@admin_bp.route("/vendors/<int:vendor_id>/automated-report-test", methods=["POST"])
@super_admin_required
def send_automated_report_test(vendor_id):
    if not celery:
        return jsonify({"error": "Background worker is not configured"}), 503
    from services.automated_reports_service import get_schedule
    try:
        schedule = get_schedule(vendor_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    if not schedule.get("id"):
        return jsonify({"error": "Save the report schedule before sending a test"}), 400
    recipient = str((request.json or {}).get("recipient_email") or schedule.get("recipient_email") or "").strip()
    if not recipient:
        return jsonify({"error": "Recipient email is required"}), 400
    report_day = date.today() - timedelta(days=1)
    unique_frequency = f"test-{secrets.token_hex(6)}"
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO automated_report_deliveries
                (schedule_id, vendor_id, frequency, period_start, period_end, status, recipient_email)
            VALUES (?, ?, ?, ?, ?, 'queued', ?)
        """, (schedule["id"], vendor_id, unique_frequency, report_day.isoformat(), report_day.isoformat(), recipient))
        delivery_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    from tasks import send_automated_report_task
    task = send_automated_report_task.apply_async(args=[delivery_id], queue="normal_priority")
    return jsonify({"success": True, "delivery_id": delivery_id, "task_id": task.id}), 202

@admin_bp.route("/registration/templates", methods=["GET"])
@super_admin_required
def get_registration_templates():
    from app import socketio, is_testing
    return jsonify({"templates": REGISTRATION_TEMPLATES})

@admin_bp.route("/vendors/<int:vendor_id>/registration_config", methods=["PUT"])
@super_admin_required
def set_vendor_registration_config(vendor_id):
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    data = request.json or {}
    config = data.get("registration_config")
    if config is None:
        return jsonify({"error": "registration_config required"}), 400
    try:
        # Validate JSON array
        if isinstance(config, str):
            config = json.loads(config)
        if not isinstance(config, list):
            return jsonify({"error": "registration_config must be a list"}), 400
        from services.config_utils import normalize_registration_config
        config = normalize_registration_config(config)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (json.dumps(config), vendor_id))
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
        from app import socketio, ALL_FEATURES
        conn = get_db_connection()
        c = conn.cursor()
        if action in ("suspend", "activate"):
            new_status = 'suspended' if action == 'suspend' else 'active'
            for vid in vendor_ids:
                c.execute("UPDATE vendors SET status = ? WHERE id = ?", (new_status, vid))
                log_audit(f"vendor_{action}", {}, target_vendor_id=vid)
        elif action == "toggle_feature":
            feature = payload.get("feature")
            enabled = payload.get("enabled", True)
            for vid in vendor_ids:
                c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vid,))
                row = c.fetchone()
                feats = []
                if row and row[0]:
                    try:
                        feats = json.loads(row[0])
                    except Exception:
                        feats = []
                if enabled and feature not in feats:
                    feats.append(feature)
                if enabled and feature == "automated_email_reports":
                    for dependency in ("reports", "report_detailed"):
                        if dependency not in feats:
                            feats.append(dependency)
                if enabled and feature == "employee_reports":
                    if "reports" not in feats:
                        feats.append("reports")
                if not enabled:
                    feats = [f for f in feats if f != feature]
                c.execute("UPDATE subscriptions SET features = ? WHERE vendor_id = ?", (json.dumps(feats), vid))
                if feature == "automated_email_reports" and not enabled:
                    c.execute("UPDATE automated_report_schedules SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE vendor_id = ?", (vid,))
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
                c.execute("UPDATE subscriptions SET max_web_sessions = ? WHERE vendor_id = ?", (max_web_sessions, vid))
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    import csv, io
    conn = get_db_connection()
    c = conn.cursor()
    vertical = vendor_vertical(c, vendor_id)
    try:
        wanted_type = requested_person_type(request.args.get("person_type"), vertical)
    except ValueError as exc:
        conn.close()
        return jsonify({"error": str(exc)}), 400
    c.execute("""SELECT f.name, f.phone, f.department, f.designation, f.shift,
                        f.daily_wage, f.custom_data,
                        (SELECT su.role FROM system_users su
                         WHERE su.person_id = f.id AND su.vendor_id = f.vendor_id
                         ORDER BY CASE LOWER(su.role) WHEN 'faculty' THEN 0 WHEN 'student' THEN 1 ELSE 2 END
                         LIMIT 1) AS system_role
                 FROM faces f WHERE f.vendor_id = ?""", (vendor_id,))
    rows = [row for row in c.fetchall() if not wanted_type or person_type_for(row[6], row[7], vertical) == wanted_type]
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name","phone","department","designation","shift","daily_wage","custom_data"])
    for r in rows:
        if hasattr(r, "keys"):
            writer.writerow([r["name"], r["phone"], r["department"], r["designation"], r["shift"], r["daily_wage"], r["custom_data"]])
        else:
            writer.writerow(list(r[:7]))
    return output.getvalue(), 200, {"Content-Type": "text/csv"}

@admin_bp.route("/vendors/<int:vendor_id>/employees/import", methods=["POST"])
@super_admin_required
def import_employees(vendor_id):
    from celery_app import celery
    data = request.json or {}
    csv_data = data.get("csv_data")
    if not csv_data:
        return jsonify({"error": "csv_data required (string)"}), 400

    scope_conn = get_db_connection()
    scope_cursor = scope_conn.cursor()
    school_student_flow = is_school_hostel(vendor_vertical(scope_cursor, vendor_id))
    scope_conn.close()
    if school_student_flow:
        return jsonify({
            "error": "Use Student Bulk Import for School/Hostel records so every student has a class/section"
        }), 400
    
    if celery:
        from tasks import process_import_employees_task
        task = process_import_employees_task.delay(vendor_id, csv_data)
        return jsonify({"success": True, "task_id": task.id, "message": "Import processing in background"}), 202

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
            # Get next display_id for this vendor
            c.execute("SELECT COALESCE(MAX(display_id), 0) + 1 FROM faces WHERE vendor_id = ?", (vendor_id,))
            next_display_id = c.fetchone()[0]

            c.execute("""INSERT INTO faces (name, phone, department, designation, shift, daily_wage, vendor_id, custom_data, display_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (name, phone, department, designation, shift, daily_wage, vendor_id, custom_data, next_display_id))
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
    from app import socketio, is_testing
    from db_factory import get_db_connection
    from services.auth_service import authenticate_vendor_access
    data = request.get_json(silent=True) or {}
    company_name = data.get("company_name")
    from services.xchat_billing_service import normalize_billing_mode
    try:
        data['xchat_billing_mode'] = normalize_billing_mode(data.get('xchat_billing_mode', 'payg'))
        data['xchat_token_limit'] = max(0, int(data.get('xchat_token_limit') or 0))
        rate = float(data.get('xchat_price_per_1k_tokens') or 0)
        if not math.isfinite(rate) or rate < 0:
            raise ValueError("XChat token price must be a non-negative number")
        data['xchat_price_per_1k_tokens'] = rate
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc) or "Invalid XChat token limit"}), 400
    
    if not company_name:
        return jsonify({"error": "Company Name is required"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        frontend_bundle_id = data.get("frontend_bundle_id", "default_attendance")
        backend_service_id = data.get("backend_service_id", "default_api")
        vertical = data.get("vertical")
        registration_config = data.get("registration_config")
        
        # 1. Create Vendor
        c.execute("""INSERT INTO vendors (company_name, contact_person, phone, email, frontend_bundle_id, backend_service_id, attendance_type, retention_days, registration_config) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (company_name, data.get("contact_person"), data.get("phone"), data.get("email"), frontend_bundle_id, backend_service_id, data.get("attendance_type", "total_time"), data.get("retention_days", 90), json.dumps(registration_config) if registration_config else None))
        vendor_id = c.lastrowid
        
        # 2. Setup Subscription (Synchronous now to avoid "Infinity" on first load)
        from datetime import date, timedelta
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
            from utils import BUNDLE_FEATURES
            features = BUNDLE_FEATURES.get(frontend_bundle_id, [])
        if "automated_email_reports" in features:
            for dependency in ("reports", "report_detailed"):
                if dependency not in features:
                    features.append(dependency)
        if "employee_reports" in features and "reports" not in features:
            features.append("reports")
        
        features_json = json.dumps(features)
        
        # Get columns to handle schema variations
        from db_factory import get_table_columns
        subs_cols = get_table_columns(conn, "subscriptions")
        
        s_cols = ["vendor_id", "plan_type", "start_date", "end_date", "max_users", "max_employees", "max_mobile_devices", "cost_per_user", "cost_per_employee", "setup_fee", "features"]
        s_vals = [vendor_id, "custom", start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, 0, features_json]
        
        if "max_web_sessions" in subs_cols:
            s_cols.append("max_web_sessions")
            s_vals.append(max_web_sessions)
        if "grace_period_days" in subs_cols:
            s_cols.append("grace_period_days")
            s_vals.append(0)
        for field, default in (
            ('xchat_billing_mode', 'payg'), ('xchat_token_limit', 0),
            ('xchat_tokens_used', 0), ('xchat_tokens_billed', 0),
            ('xchat_price_per_1k_tokens', 0),
        ):
            if field in subs_cols:
                s_cols.append(field)
                s_vals.append(default if field == 'xchat_tokens_billed' else data.get(field, default))
            
        placeholders = ", ".join(["?"] * len(s_cols))
        c.execute(f"INSERT INTO subscriptions ({', '.join(s_cols)}) VALUES ({placeholders})", tuple(s_vals))
        
        # 3. Create Admin & User Accounts
        admin_username = data.get("admin_username") or f"admin_{vendor_id}"
        admin_password = str(data.get("admin_password") or "")
        user_username = data.get("user_username") or f"user_{vendor_id}"
        user_password = str(data.get("user_password") or "")
        if len(admin_password) < 8 or len(user_password) < 8:
            conn.rollback()
            return jsonify({"error": "Admin and kiosk passwords must contain at least 8 characters"}), 400
        
        from services.auth_service import hash_password
        kiosk_pin = str(data.get("kiosk_pin") or "8888").strip()
        if not kiosk_pin: kiosk_pin = "8888"

        sys_user_cols = get_table_columns(conn, "system_users")
        is_kiosk_field = ", is_kiosk" if "is_kiosk" in sys_user_cols else ""
        is_kiosk_val = ", 1" if "is_kiosk" in sys_user_cols else ""

        c.execute("""INSERT INTO system_users (username, password, password_plain, role, vendor_id, kiosk_pin)
                      VALUES (?, ?, NULL, 'vendor_admin', ?, ?)""",
                   (admin_username, hash_password(admin_password), vendor_id, kiosk_pin))
        c.execute(f"""INSERT INTO system_users (username, password, password_plain, role, vendor_id, kiosk_pin{is_kiosk_field})
                      VALUES (?, ?, NULL, 'user', ?, ?{is_kiosk_val})""",
                   (user_username, hash_password(user_password), vendor_id, kiosk_pin))

        vendor_cols = get_table_columns(conn, "vendors")
        threshold_val = float(data.get("threshold") or 0.60)
        cooldown_val = int(data.get("cooldown") or 30)
        update_v_fields = ["kiosk_pin = ?"]
        update_v_params = [kiosk_pin]
        if "kiosk_username" in vendor_cols:
            update_v_fields.append("kiosk_username = ?")
            update_v_params.append(user_username)
        if "threshold" in vendor_cols:
            update_v_fields.append("threshold = ?")
            update_v_params.append(threshold_val)
        if "cooldown" in vendor_cols:
            update_v_fields.append("cooldown = ?")
            update_v_params.append(cooldown_val)
        update_v_params.append(vendor_id)
        c.execute(f"UPDATE vendors SET {', '.join(update_v_fields)} WHERE id = ?", tuple(update_v_params))
        c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (f"threshold_vendor_{vendor_id}", str(threshold_val)))
        c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (f"cooldown_vendor_{vendor_id}", str(cooldown_val)))
        
        # 3b. Create Owner Accounts
        owners = data.get("owners", [])
        if isinstance(owners, list):
            for owner_data in owners:
                o_username = owner_data.get("username")
                o_password = owner_data.get("password")
                if o_username and o_password:
                    # Check if already exists (username global uniqueness)
                    c.execute("SELECT username FROM system_users WHERE username = ?", (o_username,))
                    if not c.fetchone():
                        c.execute("""INSERT INTO system_users (username, password, password_plain, role, vendor_id)
                                      VALUES (?, ?, NULL, 'owner', ?)""",
                                   (o_username, hash_password(o_password), vendor_id))
        
        # 4. Create Default Company
        c.execute("INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)", 
                   (company_name, '[]', '[]', '[]', vendor_id))
        
        # 5. Handle Vertical Spcifics
        if vertical:
            c.execute("UPDATE vendors SET vertical = ? WHERE id = ?", (vertical, vendor_id))
            if str(vertical).strip().lower() in {"school", "hostel"}:
                hostel_flow = str(vertical).strip().lower() == "hostel"
                rc = json.dumps([
                    {"field": "student_id", "label": "Resident ID" if hostel_flow else "Student ID", "type": "text", "required": True, "options": []},
                    {"field": "phone", "label": "Resident Mobile Number" if hostel_flow else "Student Mobile Number", "type": "text", "required": True, "options": []},
                    {"field": "class_id", "label": "Room/Block" if hostel_flow else "Class/Section", "type": "class_select", "required": True, "options": []}
                ])
                c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (rc, vendor_id))
        
        # 6. Finalize Transaction
        conn.commit()
        
        # 7. Non-critical background tasks
        try:
            from utils import log_audit
            log_audit('create_vendor', {'company_name': company_name}, target_vendor_id=vendor_id)
        except Exception: pass
        
        try:
            trigger_model_download_if_needed(features)
        except Exception: pass
        
        socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
        
        # Invalidate stats cache so summary cards update
        cache_delete("admin_stats")
        
        return jsonify({
            "success": True,
            "vendor_id": vendor_id,
            "admin_credentials": {"username": admin_username, "password": admin_password},
            "user_credentials": {"username": user_username, "password": user_password}
        })
    except Exception as e:
        conn.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/suspend", methods=["POST"])
@super_admin_required
def suspend_vendor(vendor_id):
    from app import socketio, is_testing
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
            c.execute("DELETE FROM active_sessions WHERE vendor_id = ?", (vendor_id,))
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
    from app import socketio, is_testing
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
    from app import socketio, is_testing
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    data = request.get_json(silent=True) or {}
    from services.xchat_billing_service import normalize_billing_mode
    if 'xchat_billing_mode' in data:
        try:
            data['xchat_billing_mode'] = normalize_billing_mode(data['xchat_billing_mode'])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    for token_field in ('xchat_token_limit', 'xchat_tokens_used'):
        if token_field in data:
            try:
                data[token_field] = max(0, int(data[token_field] or 0))
            except (TypeError, ValueError):
                return jsonify({"error": f"{token_field} must be a non-negative integer"}), 400
    if 'xchat_price_per_1k_tokens' in data:
        try:
            rate = float(data['xchat_price_per_1k_tokens'] or 0)
            if not math.isfinite(rate) or rate < 0:
                raise ValueError
            data['xchat_price_per_1k_tokens'] = rate
        except (TypeError, ValueError):
            return jsonify({"error": "xchat_price_per_1k_tokens must be a non-negative number"}), 400
    
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

        # Check if subscription exists (use primary key 'id' for PG/SQLite compatibility)
        c.execute("SELECT id FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        if not c.fetchone():
            from utils import parse_db_date
            sd_raw = data.get("start_date")
            ed_raw = data.get("end_date")
            parsed_sd = parse_db_date(sd_raw)
            parsed_ed = parse_db_date(ed_raw)
            
            start_date = parsed_sd.isoformat() if parsed_sd else (date.today().isoformat())
            end_date = parsed_ed.isoformat() if parsed_ed else (date.today() + timedelta(days=14)).isoformat()
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
            subs_cols = get_table_columns(conn, "subscriptions")
            cols = ["vendor_id", "plan_type", "start_date", "end_date", "max_users", "max_employees", "max_mobile_devices", "cost_per_user", "cost_per_employee", "setup_fee", "features"]
            vals = [vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, setup_fee, features_val]
            if "max_web_sessions" in subs_cols:
                cols.insert(7, "max_web_sessions")
                vals.insert(7, max_web_sessions)
            for field, default in (
                ('xchat_billing_mode', 'payg'), ('xchat_token_limit', 0),
                ('xchat_tokens_used', 0), ('xchat_tokens_billed', 0),
                ('xchat_price_per_1k_tokens', 0),
            ):
                if field in subs_cols:
                    cols.append(field)
                    vals.append(default if field == 'xchat_tokens_billed' else data.get(field, default))
            placeholders = ", ".join(["?"] * len(cols))
            c.execute(f"INSERT INTO subscriptions ({', '.join(cols)}) VALUES ({placeholders})", tuple(vals))
            conn.commit()
            
        # Build Update Query
        query = "UPDATE subscriptions SET "
        params = []
        
        fields = ['start_date', 'end_date', 'plan_type', 'max_users', 'max_employees', 'max_mobile_devices', 'max_web_sessions', 'cost_per_user', 'cost_per_employee', 'setup_fee', 'setup_fee_paid', 'xchat_billing_mode', 'xchat_token_limit', 'xchat_tokens_used', 'xchat_price_per_1k_tokens']
        
        # Handle aliases or logic
        if 'features' in data:
            query += "features = ?, "
            features_val = data['features']
            if isinstance(features_val, list) and 'automated_email_reports' in features_val:
                for dependency in ('reports', 'report_detailed'):
                    if dependency not in features_val:
                        features_val.append(dependency)
                data['features'] = features_val
            if isinstance(features_val, list) and 'employee_reports' in features_val:
                if 'reports' not in features_val:
                    features_val.append('reports')
                data['features'] = features_val
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
                
                if field in ('start_date', 'end_date'):
                    from utils import parse_db_date
                    parsed = parse_db_date(data[field])
                    if parsed:
                        data[field] = parsed.isoformat()

                query += f"{field} = ?, "
                params.append(data[field])
        
        # Special case: if max_users is updated but max_mobile_devices isn't, sync them?
        # User said "number of users which will be number of phones".
        if 'max_users' in data and 'max_mobile_devices' not in data:
             query += "max_mobile_devices = ?, "
             params.append(data['max_users'])

        if data.get('xchat_tokens_used') == 0:
            query += "xchat_input_tokens = 0, xchat_output_tokens = 0, xchat_tokens_billed = 0, "
             
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
            if 'features' in data:
                current_features = data.get('features') or []
                if isinstance(current_features, str):
                    try:
                        current_features = json.loads(current_features)
                    except Exception:
                        current_features = []
                if 'automated_email_reports' not in current_features:
                    c.execute("UPDATE automated_report_schedules SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE vendor_id = ?", (vendor_id,))
            conn.commit()
            
            # Log Audit
            log_audit('update_subscription', data, target_vendor_id=vendor_id)
            
            try:
                c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    from services.config_utils import hydrate_registration_config
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
        config_data = []
        if config:
            try:
                config_data = json.loads(config)
            except Exception:
                config_data = []

        # If vendors.registration_config is empty, fallback to bulk_attendance_config!
        if not config_data:
            try:
                c.execute("SELECT fields FROM bulk_attendance_config WHERE vendor_id = ?", (vendor_id,))
                b_row = c.fetchone()
                if b_row and b_row[0]:
                    b_fields = json.loads(b_row[0])
                    for f in b_fields:
                        fname = f.get('name') or f.get('field')
                        if fname:
                            config_data.append({
                                "field": fname,
                                "name": fname,
                                "label": f.get('label', fname),
                                "type": f.get('type', 'text'),
                                "required": bool(f.get('required', False)),
                                "options": f.get('options', []),
                                "enabled": True
                            })
            except Exception as ex:
                logger.warning(f"Error reading bulk_attendance_config fallback: {ex}")

        # Ensure all fields have both field and name populated
        for item in config_data:
            if isinstance(item, dict):
                f_val = item.get('field') or item.get('name')
                if f_val:
                    item['field'] = f_val
                    item['name'] = f_val

        if config_data:
            # Hydrate dynamic fields (e.g. Leave Departments)
            hydrated = hydrate_registration_config(vendor_id, config_data, conn=conn)
            return jsonify({"config": hydrated})
        return jsonify({"config": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/registration-config", methods=["PUT"])
@super_admin_required
def update_vendor_registration_config(vendor_id):
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    data = request.json
    config = data.get('config') # Expecting a list/object
    
    if config is None:
        return jsonify({"error": "Missing config"}), 400
    try:
        from services.config_utils import normalize_registration_config
        config = normalize_registration_config(config)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (json.dumps(config), vendor_id))
        
        # Also synchronize bulk_attendance_config
        try:
            bulk_fields = []
            for f in config:
                fname = f.get('field') or f.get('name')
                if fname:
                    bulk_fields.append({
                        "name": fname,
                        "label": f.get('label', fname),
                        "type": f.get('type', 'text'),
                        "required": bool(f.get('required', False)),
                        "options": f.get('options', [])
                    })
            now_iso = datetime.utcnow().isoformat()
            c.execute("SELECT id FROM bulk_attendance_config WHERE vendor_id = ?", (vendor_id,))
            if c.fetchone():
                c.execute(
                    "UPDATE bulk_attendance_config SET fields = ?, updated_at = ? WHERE vendor_id = ?",
                    (json.dumps(bulk_fields), now_iso, vendor_id)
                )
            else:
                c.execute(
                    "INSERT INTO bulk_attendance_config (vendor_id, fields, updated_at) VALUES (?, ?, ?)",
                    (vendor_id, json.dumps(bulk_fields), now_iso)
                )
        except Exception as e_bulk:
            logger.warning(f"Could not sync bulk_attendance_config: {e_bulk}")

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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
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
        
        fields = ['company_name', 'contact_person', 'phone', 'email', 'frontend_bundle_id', 'backend_service_id', 'vertical', 'attendance_type', 'retention_days']
        for field in fields:
            if field in data:
                query += f"{field} = ?, "
                params.append(data[field])
        
        # Sync Features: Prioritize granular features if provided, otherwise fallback to bundle defaults
        features_json = None
        if 'features' in data:
            features_val = data['features']
            if isinstance(features_val, list):
                # Trigger model download if new feature set includes bulk attendance
                trigger_model_download_if_needed(features_val)
                features_json = json.dumps(features_val)
        elif 'frontend_bundle_id' in data:
            new_bundle_id = data['frontend_bundle_id']
            new_features = BUNDLE_FEATURES.get(new_bundle_id, [])
            trigger_model_download_if_needed(new_features)
            features_json = json.dumps(new_features)

        if features_json:
            # Check if subscription exists
            c.execute("SELECT id FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
            if c.fetchone():
                c.execute("UPDATE subscriptions SET features = ? WHERE vendor_id = ?", (features_json, vendor_id))
            else:
                # Create if missing (Self-healing)
                c.execute("INSERT INTO subscriptions (vendor_id, features) VALUES (?, ?)", (vendor_id, features_json))
        
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
                if 'vertical' in data and str(data.get('vertical') or '').strip().lower() in {'school', 'hostel'}:
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
                        hostel_flow = str(data.get('vertical') or '').strip().lower() == 'hostel'
                        rc = json.dumps([
                            {"field": "student_id", "label": "Resident ID" if hostel_flow else "Student ID", "type": "text", "required": True, "options": []},
                            {"field": "phone", "label": "Resident Mobile Number" if hostel_flow else "Student Mobile Number", "type": "text", "required": True, "options": []},
                            {"field": "class_id", "label": "Room/Block" if hostel_flow else "Class/Section", "type": "class_select", "required": True, "options": []}
                        ])
                        c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (rc, vendor_id))
            except Exception:
                pass
            
        # 2. Update Admin Credentials
        admin_username = data.get('admin_username')
        admin_password = data.get('admin_password')
        if admin_username or admin_password:
            # Check if admin user exists for this vendor
            c.execute("SELECT username FROM system_users WHERE vendor_id = ? AND role = 'vendor_admin' LIMIT 1", (vendor_id,))
            admin_user = c.fetchone()
            
            if admin_user:
                update_query = "UPDATE system_users SET "
                update_params = []
                if admin_username:
                    update_query += "username = ?, "
                    update_params.append(admin_username)
                if admin_password:
                    update_query += "password = ?, password_plain = NULL, "
                    update_params.append(hash_password(admin_password))
                
                update_query = update_query.rstrip(", ") + " WHERE username = ?"
                update_params.append(admin_user[0] if not hasattr(admin_user, "keys") else admin_user["username"])
                c.execute(update_query, update_params)
            else:
                # Create if missing (Self-healing)
                if not admin_password or len(str(admin_password)) < 8:
                    return jsonify({"error": "A password of at least 8 characters is required for a new admin"}), 400
                c.execute("INSERT INTO system_users (username, password, password_plain, role, vendor_id) VALUES (?, ?, NULL, 'vendor_admin', ?)",
                          (admin_username or f"admin_{vendor_id}", hash_password(admin_password), vendor_id))

        # 3. Update User/Kiosk Credentials
        user_username = (data.get('user_username') or '').strip()
        user_password = data.get('user_password')

        vendor_cols = get_table_columns(conn, "vendors")
        has_kiosk_username_col = "kiosk_username" in vendor_cols
        sys_user_cols = get_table_columns(conn, "system_users")
        has_is_kiosk_col = "is_kiosk" in sys_user_cols

        # 1. First check if vendor has an assigned kiosk_username
        existing_kiosk_username = None
        if has_kiosk_username_col:
            c.execute("SELECT kiosk_username FROM vendors WHERE id = ?", (vendor_id,))
            v_row = c.fetchone()
            if v_row:
                raw_ku = v_row[0] if not hasattr(v_row, "keys") else v_row.get("kiosk_username")
                if raw_ku and str(raw_ku).strip():
                    existing_kiosk_username = str(raw_ku).strip()

        # 2. Look up the designated kiosk user in system_users
        kiosk_user = None
        if existing_kiosk_username:
            c.execute("SELECT username FROM system_users WHERE vendor_id = ? AND username = ?", (vendor_id, existing_kiosk_username))
            kiosk_user = c.fetchone()

        if not kiosk_user:
            kiosk_filter = "(is_kiosk = 1 OR person_id IS NULL)" if has_is_kiosk_col else "(person_id IS NULL)"
            kiosk_order = "ORDER BY CASE WHEN is_kiosk = 1 THEN 0 WHEN person_id IS NULL THEN 1 ELSE 2 END, username ASC" if has_is_kiosk_col else "ORDER BY username ASC"
            c.execute(f"SELECT username FROM system_users WHERE vendor_id = ? AND role = 'user' AND {kiosk_filter} {kiosk_order} LIMIT 1", (vendor_id,))
            kiosk_user = c.fetchone()

        current_kiosk_username = (kiosk_user[0] if not hasattr(kiosk_user, "keys") else kiosk_user.get("username")) if kiosk_user else None

        if user_username or user_password:
            target_username = user_username or current_kiosk_username or f"user_{vendor_id}"

            if kiosk_user:
                update_query = "UPDATE system_users SET "
                update_params = []
                if has_is_kiosk_col:
                    update_query += "is_kiosk = 1, "
                update_query += "person_id = NULL, "
                if user_username and user_username != current_kiosk_username:
                    update_query += "username = ?, "
                    update_params.append(user_username)
                if user_password:
                    update_query += "password = ?, password_plain = NULL, "
                    update_params.append(hash_password(user_password))

                update_query = update_query.rstrip(", ") + " WHERE username = ? AND vendor_id = ?"
                update_params.extend([current_kiosk_username, vendor_id])
                c.execute(update_query, update_params)
            else:
                # Create if missing (Self-healing)
                if not user_password or len(str(user_password)) < 8:
                    return jsonify({"error": "A password of at least 8 characters is required for a new kiosk user"}), 400

                is_kiosk_field = ", is_kiosk" if has_is_kiosk_col else ""
                is_kiosk_val = ", 1" if has_is_kiosk_col else ""
                kiosk_pin_init = str(data.get('kiosk_pin') or '8888').strip()
                c.execute(f"""
                    INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id, kiosk_pin{is_kiosk_field})
                    VALUES (?, ?, NULL, 'user', ?, NULL, ?{is_kiosk_val})
                """, (target_username, hash_password(user_password), vendor_id, kiosk_pin_init))

            if has_kiosk_username_col:
                c.execute("UPDATE vendors SET kiosk_username = ? WHERE id = ?", (target_username, vendor_id))

        if 'kiosk_pin' in data and data.get('kiosk_pin') is not None:
            kiosk_pin = str(data.get('kiosk_pin')).strip()
            if kiosk_pin:
                c.execute("UPDATE vendors SET kiosk_pin = ? WHERE id = ?", (kiosk_pin, vendor_id))
                target_user = user_username or current_kiosk_username
                if target_user:
                    c.execute("UPDATE system_users SET kiosk_pin = ? WHERE vendor_id = ? AND username = ?", (kiosk_pin, vendor_id, target_user))
                else:
                    kiosk_filter = "(is_kiosk = 1 OR person_id IS NULL)" if has_is_kiosk_col else "(person_id IS NULL)"
                    c.execute(f"UPDATE system_users SET kiosk_pin = ? WHERE vendor_id = ? AND role = 'user' AND {kiosk_filter}", (kiosk_pin, vendor_id))

        if 'threshold' in data and data.get('threshold') is not None:
            try:
                thresh_val = round(float(data['threshold']), 2)
                if 0.40 <= thresh_val <= 0.95:
                    if "threshold" in vendor_cols:
                        c.execute("UPDATE vendors SET threshold = ? WHERE id = ?", (thresh_val, vendor_id))
                    c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (f"threshold_vendor_{vendor_id}", str(thresh_val)))
            except Exception as ex:
                logger.warning(f"Error updating threshold for vendor {vendor_id}: {ex}")

        if 'cooldown' in data and data.get('cooldown') is not None:
            try:
                cool_val = int(data['cooldown'])
                if 5 <= cool_val <= 3600:
                    if "cooldown" in vendor_cols:
                        c.execute("UPDATE vendors SET cooldown = ? WHERE id = ?", (cool_val, vendor_id))
                    c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (f"cooldown_vendor_{vendor_id}", str(cool_val)))
            except Exception as ex:
                logger.warning(f"Error updating cooldown for vendor {vendor_id}: {ex}")

        # 4. Update Owner Accounts (Sync Logic)
        owners = data.get('owners', [])
        if isinstance(owners, list):
            # Fetch current owners
            c.execute("SELECT username FROM system_users WHERE vendor_id = ? AND role = 'owner'", (vendor_id,))
            current_owners = {row[0] if not hasattr(row, "keys") else row["username"] for row in c.fetchall()}
            
            new_owner_usernames = set()
            for owner_data in owners:
                o_username = owner_data.get("username")
                o_password = owner_data.get("password")
                if not o_username: continue
                new_owner_usernames.add(o_username)
                
                if o_username in current_owners:
                    # Update password if provided
                    if o_password:
                        c.execute("UPDATE system_users SET password = ?, password_plain = NULL WHERE username = ? AND vendor_id = ?",
                                   (hash_password(o_password), o_username, vendor_id))
                else:
                    # Create new owner (ensure unique username)
                    c.execute("SELECT username FROM system_users WHERE username = ?", (o_username,))
                    if not c.fetchone():
                        if not o_password or len(str(o_password)) < 8:
                            return jsonify({"error": f"A password of at least 8 characters is required for owner {o_username}"}), 400
                        c.execute("INSERT INTO system_users (username, password, password_plain, role, vendor_id) VALUES (?, ?, NULL, 'owner', ?)",
                                   (o_username, hash_password(o_password), vendor_id))
            
            # Remove omitted owners
            to_remove = current_owners - new_owner_usernames
            for r_username in to_remove:
                c.execute("DELETE FROM system_users WHERE username = ? AND vendor_id = ? AND role = 'owner'", (r_username, vendor_id))

        conn.commit()
        
        # Real-time UI updates
        try:
            c.execute("""
                SELECT s.features 
                FROM subscriptions s 
                WHERE s.vendor_id = ?
            """, (vendor_id,))
            row = c.fetchone()
            feats = []
            if row and row[0]:
                feats = json.loads(row[0])
            socketio.emit('features_updated', {'vendor_id': vendor_id, 'features': feats}, room=f"vendor_{vendor_id}")
            socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
        except Exception:
            pass

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
    from app import socketio
    from db_factory import ensure_archive_table
    ensure_archive_table()
    conn = get_db_connection()
    c = conn.cursor()
    # ... keep existing fallback ...
    try:
        is_pg = getattr(conn, "_is_pg", False)
        placeholder = "%s" if is_pg else "?"
        sql_vendor = f"SELECT * FROM vendors WHERE id = {placeholder}"
        c.execute(sql_vendor, (vendor_id,))
        vendor_row = c.fetchone()
        if not vendor_row:
            return jsonify({"error": "Vendor not found"}), 404
            
        vcols = [d[0] for d in c.description] if hasattr(c, "description") and c.description else []
        vdict = vendor_row if isinstance(vendor_row, dict) else {vcols[i]: vendor_row[i] for i in range(len(vcols))}

        def _json_default(obj):
            if isinstance(obj, (bytes, bytearray, memoryview)):
                import base64
                return base64.b64encode(obj).decode('utf-8')
            from datetime import date, datetime
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            return str(obj)

        def archive_table(table, key="vendor_id"):
            sp_name = f"sp_arch_{table}"
            if is_pg:
                c.execute(f"SAVEPOINT {sp_name}")
            try:
                # Check if table exists first to avoid error
                if is_pg:
                    # PostgreSQL SELECT EXISTS always returns (True,) or (False,)
                    c.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)", (table,))
                    row = c.fetchone()
                    if not row or not row[0]:
                        if is_pg: c.execute(f"RELEASE SAVEPOINT {sp_name}")
                        return
                else:
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                    if not c.fetchone():
                        return

                c_read = conn.cursor()
                sql_target = f"SELECT * FROM {table} WHERE {key} = {placeholder}"
                c_read.execute(sql_target, (vendor_id,))
                cols = [d[0] for d in c_read.description] if hasattr(c_read, "description") and c_read.description else []
                rows = c_read.fetchall()
                c_read.close()

                if rows:
                    c_write = conn.cursor()
                    sql_insert = f"INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES ({placeholder}, {placeholder}, {placeholder})"
                    for r in rows:
                        row = r if isinstance(r, dict) else {cols[i]: r[i] for i in range(len(cols))}
                        c_write.execute(sql_insert, (vendor_id, table, json.dumps(row, default=_json_default)))
                    c_write.close()

                if is_pg:
                    c.execute(f"RELEASE SAVEPOINT {sp_name}")
            except Exception as arch_err:
                logger.warning(f"Could not archive {table} for vendor {vendor_id}: {arch_err}")
                if is_pg:
                    try:
                        c.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                    except Exception:
                        pass

        tables = [
            # Child tables first (they reference faces/parent_users/lectures/schedules which reference vendors)
            "lecture_attendance", "face_reset_requests", "student_parents",
            "advance_revisions", "advances", "leave_requests", "person_embeddings",
            "automated_report_deliveries", "automated_report_schedules",
            "xchat_messages", "xchat_token_usage", "xchat_conversations", "class_thresholds",
            # Tables that reference vendors directly
            "class_batches", "attendance", "lectures",
            "system_users", "parent_tokens", "parent_users",
            "faces", "leave_staff", "vendor_device_slots", "vendor_devices",
            "active_sessions", "invoices", "subscriptions", "companies",
            "bulk_attendance_config", "registration_batches",
            "subject_master", "classes",
            "audit_logs",
        ]
        for t in tables:
            key = "target_vendor_id" if t == "audit_logs" else "vendor_id"
            archive_table(t, key=key)

        # Archive class_batch_items
        sp_cbi = "sp_arch_class_batch_items"
        if is_pg: c.execute(f"SAVEPOINT {sp_cbi}")
        try:
            c_read = conn.cursor()
            sql_items = f"SELECT * FROM class_batch_items WHERE batch_id IN (SELECT id FROM class_batches WHERE vendor_id = {placeholder})"
            c_read.execute(sql_items, (vendor_id,))
            cols = [d[0] for d in c_read.description] if hasattr(c_read, "description") and c_read.description else []
            rows = c_read.fetchall()
            c_read.close()
            if rows:
                c_write = conn.cursor()
                sql_insert_items = f"INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES ({placeholder}, {placeholder}, {placeholder})"
                for r in rows:
                    row = r if isinstance(r, dict) else {cols[i]: r[i] for i in range(len(cols))}
                    c_write.execute(sql_insert_items, (vendor_id, "class_batch_items", json.dumps(row, default=_json_default)))
                c_write.close()
            if is_pg: c.execute(f"RELEASE SAVEPOINT {sp_cbi}")
        except Exception as e:
            logger.warning(f"Could not archive class_batch_items for vendor {vendor_id}: {e}")
            if is_pg:
                try: c.execute(f"ROLLBACK TO SAVEPOINT {sp_cbi}")
                except Exception: pass

        # Archive registration_batch_items
        sp_rbi = "sp_arch_reg_batch_items"
        if is_pg: c.execute(f"SAVEPOINT {sp_rbi}")
        try:
            c_read = conn.cursor()
            sql_items = f"SELECT * FROM registration_batch_items WHERE batch_id IN (SELECT id FROM registration_batches WHERE vendor_id = {placeholder})"
            c_read.execute(sql_items, (vendor_id,))
            cols = [d[0] for d in c_read.description] if hasattr(c_read, "description") and c_read.description else []
            rows = c_read.fetchall()
            c_read.close()
            if rows:
                c_write = conn.cursor()
                sql_insert_items = f"INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES ({placeholder}, {placeholder}, {placeholder})"
                for r in rows:
                    row = r if isinstance(r, dict) else {cols[i]: r[i] for i in range(len(cols))}
                    c_write.execute(sql_insert_items, (vendor_id, "registration_batch_items", json.dumps(row, default=_json_default)))
                c_write.close()
            if is_pg: c.execute(f"RELEASE SAVEPOINT {sp_rbi}")
        except Exception as e:
            logger.warning(f"Could not archive registration_batch_items for vendor {vendor_id}: {e}")
            if is_pg:
                try: c.execute(f"ROLLBACK TO SAVEPOINT {sp_rbi}")
                except Exception: pass

        sql_insert_vendor = f"INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES ({placeholder}, {placeholder}, {placeholder})"
        c.execute(sql_insert_vendor, (vendor_id, "vendors", json.dumps(vdict, default=_json_default)))

        # Explicit reverse-dependency deletions to guarantee clean foreign key cascades
        delete_steps = [
            # 1. Sub-child items
            ("class_batch_items", f"DELETE FROM class_batch_items WHERE batch_id IN (SELECT id FROM class_batches WHERE vendor_id = {placeholder})", (vendor_id,)),
            ("registration_batch_items", f"DELETE FROM registration_batch_items WHERE batch_id IN (SELECT id FROM registration_batches WHERE vendor_id = {placeholder})", (vendor_id,)),
            ("lecture_attendance", f"DELETE FROM lecture_attendance WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("automated_report_deliveries", f"DELETE FROM automated_report_deliveries WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("xchat_messages", f"DELETE FROM xchat_messages WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("xchat_token_usage", f"DELETE FROM xchat_token_usage WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("advance_revisions", f"DELETE FROM advance_revisions WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 2. Tables referencing faces or parent_users
            ("advances", f"DELETE FROM advances WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("leave_requests", f"DELETE FROM leave_requests WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("person_embeddings", f"DELETE FROM person_embeddings WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("attendance", f"DELETE FROM attendance WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("student_parents", f"DELETE FROM student_parents WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("face_reset_requests", f"DELETE FROM face_reset_requests WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 3. Parent user tokens & users
            ("parent_tokens", f"DELETE FROM parent_tokens WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("parent_users", f"DELETE FROM parent_users WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 4. System users
            ("system_users", f"DELETE FROM system_users WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 5. Faces (all tables referencing faces are deleted!)
            ("faces", f"DELETE FROM faces WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 6. Intermediate parent tables
            ("class_batches", f"DELETE FROM class_batches WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("registration_batches", f"DELETE FROM registration_batches WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("lectures", f"DELETE FROM lectures WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("automated_report_schedules", f"DELETE FROM automated_report_schedules WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("xchat_conversations", f"DELETE FROM xchat_conversations WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 7. Remaining vendor-direct tables
            ("classes", f"DELETE FROM classes WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("subject_master", f"DELETE FROM subject_master WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("class_thresholds", f"DELETE FROM class_thresholds WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("bulk_attendance_config", f"DELETE FROM bulk_attendance_config WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("leave_staff", f"DELETE FROM leave_staff WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("vendor_device_slots", f"DELETE FROM vendor_device_slots WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("vendor_devices", f"DELETE FROM vendor_devices WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("active_sessions", f"DELETE FROM active_sessions WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("invoices", f"DELETE FROM invoices WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("subscriptions", f"DELETE FROM subscriptions WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("companies", f"DELETE FROM companies WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("audit_logs", f"DELETE FROM audit_logs WHERE target_vendor_id = {placeholder}", (vendor_id,)),
            ("archive_objects", f"DELETE FROM archive_objects WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 8. Finally, the vendor itself
            ("vendors", f"DELETE FROM vendors WHERE id = {placeholder}", (vendor_id,)),
        ]

        for table_name, sql, params in delete_steps:
            sp = f"sp_del_{table_name}"
            try:
                # Check if table exists
                if is_pg:
                    c.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)", (table_name,))
                    row = c.fetchone()
                    if not row or not row[0]:
                        continue
                else:
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                    if not c.fetchone():
                        continue

                if is_pg:
                    c.execute(f"SAVEPOINT {sp}")
                c.execute(sql, params)
                if is_pg:
                    c.execute(f"RELEASE SAVEPOINT {sp}")
            except Exception as del_err:
                if is_pg:
                    try:
                        c.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                    except Exception:
                        pass
                logger.warning(f"Could not delete {table_name} for vendor {vendor_id}: {del_err}")
                if table_name == "vendors":
                    raise del_err
        
        # 1. Commit the deletion FIRST so it's permanent and doesn't roll back if sequence reset fails
        conn.commit()
        
        # 2. Invalidate admin stats cache so the numbers update immediately
        cache_delete("admin_stats")
        
        # 3. Reset sequences for all relevant tables (Nice to have, not critical)
        # We do this in a separate try-except block to prevent it from affecting the deletion result
        try:
            is_pg = getattr(conn, "_is_pg", False)
            reset_tables = [s[0] for s in delete_steps]
            for t in reset_tables:
                try:
                    if is_pg:
                        # Postgres: We need to be careful with column names and sequences
                        # Only try if 'id' column exists
                        c.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{t}' AND column_name='id'")
                        if c.fetchone():
                            c.execute(f"SELECT pg_get_serial_sequence('{t}', 'id')")
                            seq_row = c.fetchone()
                            if seq_row and seq_row[0]:
                                seq_name = seq_row[0]
                                c.execute(f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM {t}), 1), EXISTS (SELECT 1 FROM {t}))")
                                conn.commit() # Commit each reset separately
                    else:
                        # SQLite
                        c.execute(f"UPDATE sqlite_sequence SET seq = COALESCE((SELECT MAX(id) FROM {t}), 0) WHERE name = '{t}'")
                        conn.commit()
                except Exception:
                    if conn: conn.rollback() # Rollback only this specific sequence reset if it fails
                    pass
        except Exception:
            pass
        
        try:
            from app import socketio
            socketio.emit('force_logout', {'vendor_id': vendor_id, 'reason': 'Vendor account deleted'}, room=f"vendor_{vendor_id}")
            # Notify super admin dashboard to refresh stats
            socketio.emit('admin_stats_updated', room='super_admin')
            socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
        except Exception:
            pass
        return jsonify({"success": True, "message": "Vendor archived and deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/<int:vendor_id>/invoices", methods=["GET"])
@super_admin_required
def get_vendor_invoices(vendor_id):
    from app import socketio, is_testing
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    from db_factory import ensure_archive_table as _ensure_archive_table
    _ensure_archive_table()
    company = request.args.get("company_name")
    email = request.args.get("email")
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT vendor_id, row_json, archived_at, restored_at FROM archive_objects WHERE table_name = 'vendors'")
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



@admin_bp.route("/vendors/<int:vendor_id>/invoices/generate", methods=["POST"])
@super_admin_required
def generate_invoice(vendor_id):
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    import threading
    is_async = request.args.get('async') == 'true'
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Serialize invoice generation per vendor so two simultaneous clicks cannot
    # charge the same unbilled token watermark twice.
    is_pg = getattr(conn, "_is_pg", False)
    if not is_pg:
        c.execute("BEGIN IMMEDIATE")

    # Get Subscription Details
    select_subscription = "SELECT * FROM subscriptions WHERE vendor_id = ?"
    if is_pg:
        select_subscription += " FOR UPDATE"
    c.execute(select_subscription, (vendor_id,))
    sub = c.fetchone()
    if not sub:
        conn.close()
        return jsonify({"error": "No subscription found"}), 404
        
    sub = dict(sub)

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

    # Bill only AI tokens consumed since the previous generated invoice. The
    # watermark prevents the same cumulative usage from being charged twice.
    from services.xchat_billing_service import calculate_token_charge
    xchat_calculation = calculate_token_charge(
        sub.get('xchat_tokens_used', 0),
        sub.get('xchat_tokens_billed', 0),
        sub.get('xchat_price_per_1k_tokens', 0),
    )
    xchat_charge = xchat_calculation['unbilled_charge']
    
    # Check for Setup Fee
    setup_fee = 0
    if sub['setup_fee'] and not sub['setup_fee_paid']:
        setup_fee = sub['setup_fee']
        
    total_amount = round(monthly_cost + setup_fee + xchat_charge, 2)
    
    details = {
        "max_employees": max_employees_count,
        "cost_per_employee": cost_per_employee,
        "max_devices": billed_device_count,
        "cost_per_device": cost_per_user,
        "employee_cost_total": employee_cost_total,
        "device_cost_total": device_cost_total,
        "monthly_charge": monthly_cost,
        "setup_fee": setup_fee,
        "xchat": {
            **xchat_calculation,
            "input_tokens_total": int(sub.get('xchat_input_tokens') or 0),
            "output_tokens_total": int(sub.get('xchat_output_tokens') or 0),
            "billing_unit": "1000_tokens",
            "charge": xchat_charge,
        },
    }
    
    # Create Invoice
    invoice_date = date.today().isoformat()
    due_date = (date.today() + timedelta(days=7)).isoformat()
    
    c.execute("""INSERT INTO invoices (vendor_id, invoice_date, due_date, amount, status, details)
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (vendor_id, invoice_date, due_date, total_amount, 'generated', json.dumps(details)))

    if xchat_calculation['unbilled_tokens'] > 0:
        c.execute(
            "UPDATE subscriptions SET xchat_tokens_billed = ? WHERE vendor_id = ?",
            (xchat_calculation['tokens_used'], vendor_id),
        )
              
    # If setup fee was included, mark it as paid (or maybe only after invoice is paid? Let's keep it simple for now)
    # Actually, better to mark setup_fee_paid ONLY when invoice is paid.
    
    conn.commit()
    # The vendor subscription response embeds its invoice list and is cached for
    # an hour. Invalidate it immediately so Vendor Settings sees this invoice.
    cache_delete(f"vendor:{vendor_id}:subscription")
    try:
        log_audit("invoice_generate", {"amount": total_amount}, target_vendor_id=vendor_id, status="success")
    except Exception:
        pass
    conn.close()
    try:
        socketio.emit(
            'invoice_updated',
            {'vendor_id': vendor_id, 'action': 'generated'},
            room=f"vendor_{vendor_id}",
        )
    except Exception:
        pass
    if is_async:
        job_id = create_job(content_type="application/json", ttl=600)
        def _bg():
            try:
                complete_job(job_id, json.dumps({"success": True, "message": "Invoice Generated", "amount": total_amount}))
                socketio.emit('job_completed', {'job_id': job_id, 'type': 'invoice_generate', 'vendor_id': vendor_id})
            except Exception as e:
                fail_job(job_id, e)
        threading.Thread(target=_bg, daemon=True).start()
        return jsonify({"success": True, "job_id": job_id, "processing": True})
    return jsonify({"success": True, "message": "Invoice Generated", "amount": total_amount})

@admin_bp.route("/invoices/<int:invoice_id>/status", methods=["PUT"])
@super_admin_required
def update_invoice_status(invoice_id):
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").strip().lower()
    if status not in {'paid', 'overdue', 'generated'}:
        return jsonify({"error": "status must be paid, overdue, or generated"}), 400
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT details, vendor_id FROM invoices WHERE id = ?", (invoice_id,))
    invoice = c.fetchone()
    if not invoice:
        conn.close()
        return jsonify({"error": "Invoice not found"}), 404

    vendor_id = invoice['vendor_id']
    c.execute("UPDATE invoices SET status = ? WHERE id = ?", (status, invoice_id))
    
    # If paid, check if it included setup fee and update subscription
    if status == 'paid':
        try:
            raw_details = invoice['details']
            details = json.loads(raw_details) if isinstance(raw_details, str) else (raw_details or {})
        except Exception:
            details = {}
        if details.get('setup_fee', 0) > 0:
            c.execute("UPDATE subscriptions SET setup_fee_paid = 1 WHERE vendor_id = ?", (vendor_id,))
    
    conn.commit()
    conn.close()
    cache_delete(f"vendor:{vendor_id}:subscription")
    try:
        socketio.emit(
            'invoice_updated',
            {'vendor_id': vendor_id, 'invoice_id': invoice_id, 'status': status, 'action': 'status'},
            room=f"vendor_{vendor_id}",
        )
    except Exception:
        pass
    return jsonify({"success": True})

@admin_bp.route("/system/health", methods=["GET"])
@super_admin_required
def system_health():
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    from utils import redis_client
    status = {"db": "ok", "redis": "disabled", "active_sessions": 0}
    # DB check
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM active_sessions")
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    from utils import redis_client
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    from tasks import ensure_task_events_table
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
        c.execute(base, params)
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    from tasks import ensure_task_events_table
    ensure_task_events_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        older_days = int(request.args.get("older_days") or 0)
        max_rows = request.json.get("max_rows") if request.is_json else None
        deleted = 0
        if older_days > 0:
            c.execute("DELETE FROM task_events WHERE created_at < datetime('now', ?)", (f'-{older_days} days',))
            deleted += c.rowcount if hasattr(c, "rowcount") else 0
        if max_rows:
            c.execute("SELECT COUNT(*) FROM task_events")
            total = c.fetchone()[0]
            if total and int(total) > int(max_rows):
                overflow = int(total) - int(max_rows)
                c.execute("DELETE FROM task_events WHERE id IN (SELECT id FROM task_events ORDER BY id ASC LIMIT ?)", (overflow,))
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    from tasks import ensure_task_events_table
    ensure_task_events_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        window_minutes = int(request.args.get("window_minutes") or 60)
        bucket = request.args.get("bucket") or "minute"
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        c.execute("SELECT queue, status, runtime, finished_at, started_at, received_at FROM task_events WHERE (finished_at IS NOT NULL AND finished_at >= ?) OR (finished_at IS NULL AND created_at >= ?)", (cutoff.isoformat(), cutoff.isoformat()))
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    from db_factory import ensure_archive_table
    ensure_archive_table()
    data = request.json or {}
    company = data.get("company_name")
    email = data.get("email")
    if not company and not email:
        return jsonify({"error": "Provide company_name or email"}), 400
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT vendor_id, row_json FROM archive_objects WHERE table_name='vendors'")
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
        
        is_pg = getattr(conn, "_is_pg", False)
        
        # 1. Restore Vendor
        sql_insert_vendor = """INSERT INTO vendors (company_name, contact_person, phone, email, frontend_bundle_id, backend_service_id, registration_config, vertical, attendance_type, retention_days, status, created_at) 
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                            """INSERT INTO vendors (company_name, contact_person, phone, email, frontend_bundle_id, backend_service_id, registration_config, vertical, attendance_type, retention_days, status, created_at) 
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        
        c.execute(sql_insert_vendor, (
            vendor_snapshot.get("company_name"),
            vendor_snapshot.get("contact_person"),
            vendor_snapshot.get("phone"),
            vendor_snapshot.get("email"),
            vendor_snapshot.get("frontend_bundle_id") or "default_attendance",
            vendor_snapshot.get("backend_service_id") or "default_api",
            vendor_snapshot.get("registration_config"),
            vendor_snapshot.get("vertical"),
            vendor_snapshot.get("attendance_type") or "total_time",
            vendor_snapshot.get("retention_days") or 90,
            vendor_snapshot.get("status") or "active",
            vendor_snapshot.get("created_at") or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))
        
        new_vendor_id = None
        if is_pg:
            c.execute("SELECT id FROM vendors WHERE email = %s ORDER BY id DESC LIMIT 1", (vendor_snapshot.get("email"),))
            new_vendor_id = c.fetchone()[0]
        else:
            new_vendor_id = c.lastrowid

        if not new_vendor_id:
            conn.rollback()
            return jsonify({"error": "Failed to create vendor"}), 500

        # Mappings for dependent tables
        person_id_map = {}
        parent_id_map = {}
        
        # 2. Restore Subscriptions
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='subscriptions' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            obj = json.loads(row_json)
            sql = """INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, setup_fee, features, max_web_sessions, xchat_billing_mode, xchat_token_limit, xchat_tokens_used, xchat_input_tokens, xchat_output_tokens, xchat_tokens_billed, xchat_price_per_1k_tokens)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, setup_fee, features, max_web_sessions, xchat_billing_mode, xchat_token_limit, xchat_tokens_used, xchat_input_tokens, xchat_output_tokens, xchat_tokens_billed, xchat_price_per_1k_tokens)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (
                new_vendor_id, obj.get("plan_type") or "custom", obj.get("start_date"), obj.get("end_date"),
                obj.get("max_users"), obj.get("max_employees"), obj.get("max_mobile_devices"),
                obj.get("cost_per_user"), obj.get("cost_per_employee"), obj.get("setup_fee") or 0, 
                obj.get("features"), obj.get("max_web_sessions") or 1,
                obj.get("xchat_billing_mode") or "payg", obj.get("xchat_token_limit") or 0,
                obj.get("xchat_tokens_used") or 0, obj.get("xchat_input_tokens") or 0,
                obj.get("xchat_output_tokens") or 0, obj.get("xchat_tokens_billed") or 0,
                obj.get("xchat_price_per_1k_tokens") or 0,
            ))

        # 3. Restore Companies
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='companies' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            comp = json.loads(row_json)
            sql = """INSERT INTO companies (name, shifts, draft_timetable, live_timetable, working_hours, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO companies (name, shifts, draft_timetable, live_timetable, working_hours, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (comp.get("name"), comp.get("shifts") or "[]", comp.get("draft_timetable") or "[]", comp.get("live_timetable") or "[]", comp.get("working_hours"), new_vendor_id))

        # 4. Restore Faces (and populate person_id_map)
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='faces' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            f = json.loads(row_json)
            old_id = f.get("id")
            
            c.execute("SELECT COALESCE(MAX(display_id), 0) + 1 FROM faces WHERE vendor_id = %s" if is_pg else "SELECT COALESCE(MAX(display_id), 0) + 1 FROM faces WHERE vendor_id = ?", (new_vendor_id,))
            next_display_id = c.fetchone()[0]

            sql = """INSERT INTO faces (name, templates, face_image, phone, department, designation, shift, daily_wage, late_allowance_days, late_deduction_amount, custom_data, display_id, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO faces (name, templates, face_image, phone, department, designation, shift, daily_wage, late_allowance_days, late_deduction_amount, custom_data, display_id, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (
                f.get("name"), f.get("templates"), f.get("face_image"), f.get("phone"), 
                f.get("department"), f.get("designation"), f.get("shift"), f.get("daily_wage"),
                f.get("late_allowance_days"), f.get("late_deduction_amount"), f.get("custom_data"), 
                next_display_id, new_vendor_id
            ))
            
            new_id = None
            if is_pg:
                c.execute("SELECT id FROM faces WHERE vendor_id = %s AND name = %s ORDER BY id DESC LIMIT 1", (new_vendor_id, f.get("name")))
                new_id = c.fetchone()[0]
            else:
                new_id = c.lastrowid
            
            if old_id: person_id_map[old_id] = new_id

        # 5. Restore Parent Users
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='parent_users' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            p = json.loads(row_json)
            old_id = p.get("id")
            sql = """INSERT INTO parent_users (username, password, contact_email, contact_phone, student_number, device_id, fcm_token, face_image, face_template, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO parent_users (username, password, contact_email, contact_phone, student_number, device_id, fcm_token, face_image, face_template, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (
                p.get("username"), p.get("password"), p.get("contact_email"), p.get("contact_phone"),
                p.get("student_number"), p.get("device_id"), p.get("fcm_token"), p.get("face_image"),
                p.get("face_template"), new_vendor_id
            ))
            
            new_id = None
            if is_pg:
                c.execute("SELECT id FROM parent_users WHERE vendor_id = %s AND username = %s ORDER BY id DESC LIMIT 1", (new_vendor_id, p.get("username")))
                new_id = c.fetchone()[0]
            else:
                new_id = c.lastrowid
            if old_id: parent_id_map[old_id] = new_id

        # 6. Restore System Users
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='system_users' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            u = json.loads(row_json)
            old_person_id = u.get("person_id")
            new_person_id = person_id_map.get(old_person_id) if old_person_id else None
            
            sql = """INSERT INTO system_users (username, password, password_plain, role, has_set_password, last_active_at, person_id, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO system_users (username, password, password_plain, role, has_set_password, last_active_at, person_id, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (
                u.get("username"), u.get("password"), None, u.get("role"),
                u.get("has_set_password"), u.get("last_active_at"), new_person_id, new_vendor_id
            ))

        # 7. Restore Attendance
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='attendance' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            a = json.loads(row_json)
            old_person_id = a.get("person_id")
            new_person_id = person_id_map.get(old_person_id) if old_person_id else None
            
            sql = """INSERT INTO attendance (name, timestamp, status, captured_image, activity, is_late, device_id, person_id, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO attendance (name, timestamp, status, captured_image, activity, is_late, device_id, person_id, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (
                a.get("name"), a.get("timestamp"), a.get("status"), a.get("captured_image"),
                a.get("activity"), a.get("is_late"), a.get("device_id"), new_person_id, new_vendor_id
            ))

        # 8. Restore Leave Requests
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='leave_requests' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            l = json.loads(row_json)
            old_student_id = l.get("student_id")
            new_student_id = person_id_map.get(old_student_id) if old_student_id else None
            
            sql = """INSERT INTO leave_requests (student_id, leave_type, reason, start_date, end_date, start_time, end_time, parent_status, rector_status, hod_status, final_status, created_at, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO leave_requests (student_id, leave_type, reason, start_date, end_date, start_time, end_time, parent_status, rector_status, hod_status, final_status, created_at, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (
                new_student_id, l.get("leave_type"), l.get("reason"), l.get("start_date"),
                l.get("end_date"), l.get("start_time"), l.get("end_time"), l.get("parent_status"),
                l.get("rector_status"), l.get("hod_status"), l.get("final_status"), l.get("created_at"), new_vendor_id
            ))

        # 9. Restore Person Embeddings
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='person_embeddings' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            e = json.loads(row_json)
            old_person_id = e.get("person_id")
            new_person_id = person_id_map.get(old_person_id) if old_person_id else None
            
            # Convert base64 back to bytes for LargeBinary columns
            import base64
            vec = base64.b64decode(e.get("vec")) if e.get("vec") else None
            struct_vec = base64.b64decode(e.get("struct_vec")) if e.get("struct_vec") else None
            
            sql = """INSERT INTO person_embeddings (person_id, class_year, division, branch, vec, dim, struct_vec, landmarks_3d, created_at, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO person_embeddings (person_id, class_year, division, branch, vec, dim, struct_vec, landmarks_3d, created_at, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (
                new_person_id, e.get("class_year"), e.get("division"), e.get("branch"),
                vec, e.get("dim"), struct_vec, e.get("landmarks_3d"), e.get("created_at"), new_vendor_id
            ))

        # 10. Restore Student Parents (Mapping)
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='student_parents' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            sp = json.loads(row_json)
            old_p_id = sp.get("person_id")
            old_pa_id = sp.get("parent_id")
            new_p_id = person_id_map.get(old_p_id)
            new_pa_id = parent_id_map.get(old_pa_id)
            
            if new_p_id and new_pa_id:
                sql = "INSERT INTO student_parents (person_id, parent_id, created_at, vendor_id) VALUES (%s, %s, %s, %s)" if is_pg else \
                      "INSERT INTO student_parents (person_id, parent_id, created_at, vendor_id) VALUES (?, ?, ?, ?)"
                c.execute(sql, (new_p_id, new_pa_id, sp.get("created_at"), new_vendor_id))

        # 11. Restore Class Batches and Items
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='class_batches' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            cb = json.loads(row_json)
            batch_id = cb.get("id")
            sql = """INSERT INTO class_batches (id, class_year, division, branch, status, created_at, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO class_batches (id, class_year, division, branch, status, created_at, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (batch_id, cb.get("class_year"), cb.get("division"), cb.get("branch"), cb.get("status"), cb.get("created_at"), new_vendor_id))
            
            # Items for this batch
            c.execute("SELECT row_json FROM archive_objects WHERE table_name='class_batch_items' AND vendor_id = ?", (target_vendor_id,))
            for (item_json,) in c.fetchall():
                item = json.loads(item_json)
                if item.get("batch_id") == batch_id:
                    sql_i = """INSERT INTO class_batch_items (id, batch_id, seq, image_b64, annotated_b64, faces_json, status, created_at) 
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                            """INSERT INTO class_batch_items (id, batch_id, seq, image_b64, annotated_b64, faces_json, status, created_at) 
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
                    c.execute(sql_i, (item.get("id"), batch_id, item.get("seq"), item.get("image_b64"), item.get("annotated_b64"), item.get("faces_json"), item.get("status"), item.get("created_at")))

        # 12. Restore Devices and Slots
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='vendor_devices' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            d = json.loads(row_json)
            sql = """INSERT INTO vendor_devices (device_id, device_name, registered_at, last_login_at, last_active_at, battery_level, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO vendor_devices (device_id, device_name, registered_at, last_login_at, last_active_at, battery_level, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (d.get("device_id"), d.get("device_name"), d.get("registered_at"), d.get("last_login_at"), d.get("last_active_at"), d.get("battery_level"), new_vendor_id))

        c.execute("SELECT row_json FROM archive_objects WHERE table_name='vendor_device_slots' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            s = json.loads(row_json)
            sql = """INSERT INTO vendor_device_slots (slot_name, assigned_device_id, assigned_at, vendor_id) 
                     VALUES (%s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO vendor_device_slots (slot_name, assigned_device_id, assigned_at, vendor_id) 
                     VALUES (?, ?, ?, ?)"""
            c.execute(sql, (s.get("slot_name"), s.get("assigned_device_id"), s.get("assigned_at"), new_vendor_id))

        # 13. Restore Invoices and Audit Logs
        c.execute("SELECT row_json FROM archive_objects WHERE table_name='invoices' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            inv = json.loads(row_json)
            sql = """INSERT INTO invoices (amount, status, due_date, generated_at, paid_at, invoice_date, details, vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO invoices (amount, status, due_date, generated_at, paid_at, invoice_date, details, vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (inv.get("amount"), inv.get("status"), inv.get("due_date"), inv.get("generated_at"), inv.get("paid_at"), inv.get("invoice_date"), inv.get("details"), new_vendor_id))

        c.execute("SELECT row_json FROM archive_objects WHERE table_name='leave_staff' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            s = json.loads(row_json)
            sql = """INSERT INTO leave_staff (staff_id, role, vendor_id) 
                     VALUES (%s, %s, %s)""" if is_pg else \
                  """INSERT INTO leave_staff (staff_id, role, vendor_id) 
                     VALUES (?, ?, ?)"""
            # Note: staff_id here refers to person_id (Face ID)
            new_staff_id = person_id_map.get(s.get("staff_id"))
            if new_staff_id:
                c.execute(sql, (new_staff_id, s.get("role"), new_vendor_id))

        c.execute("SELECT row_json FROM archive_objects WHERE table_name='audit_logs' AND vendor_id = ?", (target_vendor_id,))
        for (row_json,) in c.fetchall():
            log = json.loads(row_json)
            sql = """INSERT INTO audit_logs (actor_username, actor_role, action, details, ip, timestamp, target_vendor_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s)""" if is_pg else \
                  """INSERT INTO audit_logs (actor_username, actor_role, action, details, ip, timestamp, target_vendor_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)"""
            c.execute(sql, (log.get("actor_username"), log.get("actor_role"), log.get("action"), log.get("details"), log.get("ip"), log.get("timestamp"), new_vendor_id))

        # Mark archived objects as restored
        now = datetime.now()
        c.execute("UPDATE archive_objects SET restored_at = %s WHERE vendor_id = %s" if is_pg else "UPDATE archive_objects SET restored_at = ? WHERE vendor_id = ?", (now, target_vendor_id))
        
        conn.commit()
        
        # Invalidate cache
        cache_delete("admin_stats")
        
        try:
            socketio.emit('admin_stats_updated', room='super_admin')
        except Exception:
            pass
        
        return jsonify({"success": True, "new_vendor_id": new_vendor_id, "message": "Vendor and all related data restored successfully"})
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
    from app import socketio, is_testing
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
    from app import socketio, is_testing
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
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    conn = get_db_connection()
    if not getattr(conn, "_is_pg", False):
        conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Join Faces with Vendors and Attendance
    # We want latest attendance status
    query = """
        SELECT f.*, v.company_name,
               (SELECT status FROM attendance a WHERE a.person_id = f.id ORDER BY timestamp DESC LIMIT 1) as last_status,
               (SELECT timestamp FROM attendance a WHERE a.person_id = f.id ORDER BY timestamp DESC LIMIT 1) as last_seen,
               (SELECT p.face_image FROM student_parents sp JOIN parent_users p ON sp.parent_id = p.id WHERE sp.person_id = f.id LIMIT 1) as parent_face,
               (SELECT p.username FROM student_parents sp JOIN parent_users p ON sp.parent_id = p.id WHERE sp.person_id = f.id LIMIT 1) as parent_name,
               (SELECT p.contact_phone FROM student_parents sp JOIN parent_users p ON sp.parent_id = p.id WHERE sp.person_id = f.id LIMIT 1) as parent_phone
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
            "last_seen": row["last_seen"],
            "parent_face": row["parent_face"],
            "parent_name": row["parent_name"],
            "parent_phone": row["parent_phone"]
        })
        
    return jsonify({"employees": employees})
    
@admin_bp.route("/vendors/<int:vendor_id>/employees", methods=["GET"])
@super_admin_required
def get_vendor_employees(vendor_id):
    from app import socketio, is_testing
    from services.auth_service import authenticate_vendor_access
    conn = get_db_connection()
    if not getattr(conn, "_is_pg", False):
        conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Same logic as get_all_employees but for a specific vendor
    query = """
        SELECT f.*, v.company_name, su.username as student_username,
               (SELECT status FROM attendance a WHERE a.person_id = f.id ORDER BY timestamp DESC LIMIT 1) as last_status,
               (SELECT timestamp FROM attendance a WHERE a.person_id = f.id ORDER BY timestamp DESC LIMIT 1) as last_seen,
               (SELECT p.face_image FROM student_parents sp JOIN parent_users p ON sp.parent_id = p.id WHERE sp.person_id = f.id LIMIT 1) as parent_face,
               (SELECT p.username FROM student_parents sp JOIN parent_users p ON sp.parent_id = p.id WHERE sp.person_id = f.id LIMIT 1) as parent_name,
               (SELECT p.contact_phone FROM student_parents sp JOIN parent_users p ON sp.parent_id = p.id WHERE sp.person_id = f.id LIMIT 1) as parent_phone
        FROM faces f
        LEFT JOIN vendors v ON f.vendor_id = v.id
        LEFT JOIN system_users su ON f.id = su.person_id AND su.role = 'user'
        WHERE f.vendor_id = ?
    """
    
    c.execute(query, (vendor_id,))
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
            "last_seen": row["last_seen"],
            "phone": row["phone"],
            "student_username": row["student_username"],
            "parent_face": row["parent_face"],
            "parent_name": row["parent_name"],
            "parent_phone": row["parent_phone"]
        })
        
    return jsonify({"employees": employees})


@admin_bp.route("/archival/run", methods=["POST"])
@super_admin_required
def trigger_archival():
    from services.archival_service import run_archival
    count = run_archival()
    return jsonify({"success": True, "archived_count": count})


@admin_bp.route("/archival/download", methods=["GET"])
@super_admin_required
def download_archival_database():
    from db_factory import DB_BACKUP_PATH
    if not os.path.exists(DB_BACKUP_PATH):
        return jsonify({"error": "No backup database found"}), 404
    return send_file(DB_BACKUP_PATH, as_attachment=True, download_name="backup_faces.db")


@admin_bp.route("/archival/vendors/<int:vendor_id>", methods=["DELETE"])
@super_admin_required
def delete_vendor_archive(vendor_id):
    from db_factory import get_backup_db_connection
    try:
        conn = get_backup_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM attendance WHERE vendor_id = ?", (vendor_id,))
        c.execute("DELETE FROM backup_metadata WHERE vendor_id = ?", (vendor_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Archived data for vendor {vendor_id} deleted permanently."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/database/restore", methods=["POST"])
@super_admin_required
def restore_database():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if not file.filename.endswith('.db') and not file.filename.endswith('.sqlite'):
        return jsonify({"error": "Invalid file type. Please upload a .db or .sqlite file"}), 400
    
    temp_path = os.path.join("/tmp", f"restore_{secrets.token_hex(8)}.sqlite")
    try:
        file.save(temp_path)
        stats = run_restore(temp_path)
        log_audit("RESTORE_DATABASE", f"Merged data from {file.filename}")
        return jsonify({"success": True, "message": "Database restored/merged successfully", "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@admin_bp.route("/database/backup", methods=["GET"])
@super_admin_required
def backup_database():
    from services.restoration_service import run_backup
    import secrets
    import os
    
    temp_path = os.path.join("/tmp", f"full_backup_{secrets.token_hex(4)}.db")
    try:
        stats = run_backup(temp_path)
        log_audit("BACKUP_DATABASE", "Generated full system backup")
        return send_file(temp_path, as_attachment=True, download_name="full_system_backup.db")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # Note: We should ideally delete the temp file after sending, 
    # but send_file doesn't make that easy without a wrapper.
    # Flask's after_this_request can do it or just let /tmp clean up.
@admin_bp.route("/vendors/<int:vendor_id>/portable-export", methods=["GET"])
@super_admin_required
def portable_export_vendor(vendor_id):
    import json
    import gzip
    from io import BytesIO
    
    conn = get_db_connection()
    if not getattr(conn, "_is_pg", False):
        conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        # 1. Get Vendor
        c.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        vendor = dict(c.fetchone())
        if not vendor:
            return jsonify({"error": "Vendor not found"}), 404
            
        # 2. Get Subscription
        c.execute("SELECT * FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        sub_row = c.fetchone()
        subscription = dict(sub_row) if sub_row else None
        
        # 3. Get Company
        c.execute("SELECT * FROM companies WHERE vendor_id = ?", (vendor_id,))
        comp_row = c.fetchone()
        company = dict(comp_row) if comp_row else None
        
        # 4. Get Faces
        c.execute("SELECT * FROM faces WHERE vendor_id = ?", (vendor_id,))
        faces = [dict(row) for row in c.fetchall()]
        
        # 5. Get Embeddings
        c.execute("SELECT * FROM person_embeddings WHERE vendor_id = ?", (vendor_id,))
        embeddings = [dict(row) for row in c.fetchall()]
        
        # 6. Get Users
        c.execute("SELECT * FROM system_users WHERE vendor_id = ?", (vendor_id,))
        users = [dict(row) for row in c.fetchall()]
        
        package = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "vendor": vendor,
            "subscription": subscription,
            "company": company,
            "faces": faces,
            "embeddings": embeddings,
            "users": users
        }
        
        # Custom JSON encoder
        def _json_default(obj):
            if isinstance(obj, (bytes, bytearray, memoryview)):
                import base64
                return base64.b64encode(obj).decode('utf-8')
            from datetime import date, datetime
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            return str(obj)
            
        # Compress the JSON
        json_data = json.dumps(package, default=_json_default).encode('utf-8')
        compressed = gzip.compress(json_data)
        
        filename = f"vendor_{vendor_id}_{vendor['company_name'].replace(' ', '_')}_portable.gz"
        return send_file(
            BytesIO(compressed),
            mimetype='application/gzip',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/vendors/portable-import", methods=["POST"])
@super_admin_required
def portable_import_vendor():
    import json
    import gzip
    
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    try:
        raw_content = file.read()
        try:
            content = gzip.decompress(raw_content)
        except Exception:
            # Fallback to plain JSON
            content = raw_content
            
        package = json.loads(content)
        if package.get("version") != "1.0":
            return jsonify({"error": "Unsupported package version"}), 400
            
        v_data = package.get("vendor")
        s_data = package.get("subscription")
        c_data = package.get("company")
        f_list = package.get("faces", [])
        e_list = package.get("embeddings", [])
        u_list = package.get("users", [])
        
        conn = get_db_connection()
        c = conn.cursor()
        
        try:
            # 1. Create Vendor (Generate new ID)
            # Check if email exists
            c.execute("SELECT id FROM vendors WHERE email = ?", (v_data.get("email"),))
            if c.fetchone():
                return jsonify({"error": f"Vendor with email {v_data.get('email')} already exists"}), 409
                
            c.execute("""INSERT INTO vendors (company_name, contact_person, phone, email, status, frontend_bundle_id, backend_service_id, registration_config, retention_days)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (v_data.get("company_name"), v_data.get("contact_person"), v_data.get("phone"), v_data.get("email"), 
                       v_data.get("status", "active"), v_data.get("frontend_bundle_id"), v_data.get("backend_service_id"),
                       v_data.get("registration_config"), v_data.get("retention_days", 90)))
            
            new_vendor_id = None
            try:
                new_vendor_id = c.lastrowid
            except Exception: pass
            
            if not new_vendor_id:
               c.execute("SELECT id FROM vendors WHERE email = ?", (v_data.get("email"),))
               rv = c.fetchone()
               new_vendor_id = rv[0] if rv else None
               
            if not new_vendor_id:
                raise Exception("Failed to retrieve new vendor ID")
            
            # 2. Restore Subscription
            if s_data:
                c.execute("""INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, status, max_users, max_employees, cost_per_user, setup_fee, setup_fee_paid, max_mobile_devices, cost_per_employee, grace_period_days, max_web_sessions, features, xchat_billing_mode, xchat_token_limit, xchat_tokens_used, xchat_input_tokens, xchat_output_tokens, xchat_tokens_billed, xchat_price_per_1k_tokens)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (new_vendor_id, s_data.get("plan_type"), s_data.get("start_date"), s_data.get("end_date"), s_data.get("status"),
                           s_data.get("max_users"), s_data.get("max_employees"), s_data.get("cost_per_user"), s_data.get("setup_fee"), s_data.get("setup_fee_paid"),
                           s_data.get("max_mobile_devices"), s_data.get("cost_per_employee"), s_data.get("grace_period_days"), s_data.get("max_web_sessions"), s_data.get("features"),
                           s_data.get("xchat_billing_mode") or "payg", s_data.get("xchat_token_limit") or 0,
                           s_data.get("xchat_tokens_used") or 0, s_data.get("xchat_input_tokens") or 0,
                           s_data.get("xchat_output_tokens") or 0, s_data.get("xchat_tokens_billed") or 0,
                           s_data.get("xchat_price_per_1k_tokens") or 0))
            
            # 3. Restore Company
            if c_data:
                c.execute("""INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id)
                             VALUES (?, ?, ?, ?, ?)""",
                          (c_data.get("name"), c_data.get("shifts"), c_data.get("draft_timetable"), c_data.get("live_timetable"), new_vendor_id))
            
            # 4. Restore Users
            for u in u_list:
                # Check if username exists
                c.execute("SELECT username FROM system_users WHERE username = ?", (u.get("username"),))
                if c.fetchone():
                    # Handle collision by appending vendor ID
                    u["username"] = f"{u['username']}_{new_vendor_id}"
                
                c.execute("""INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)""",
                          (u.get("username"), u.get("password"), u.get("role"), new_vendor_id))
            
            # 5. Restore Faces & Map IDs
            face_id_map = {}
            for f in f_list:
                old_id = f.get("id")
                c.execute("""INSERT INTO faces (name, templates, face_image, department, designation, phone, shift, vendor_id, custom_data, display_id)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (f.get("name"), f.get("templates"), f.get("face_image"), f.get("department"), f.get("designation"), 
                           f.get("phone"), f.get("shift"), new_vendor_id, f.get("custom_data"), f.get("display_id")))
                
                new_face_id = None
                try: new_face_id = c.lastrowid
                except Exception: pass
                
                if not new_face_id:
                     # Fallback to phone + name for identification in the same transaction
                     c.execute("SELECT id FROM faces WHERE vendor_id = ? AND phone = ? AND name = ?", (new_vendor_id, f.get("phone"), f.get("name")))
                     rf = c.fetchone()
                     new_face_id = rf[0] if rf else None
                
                if new_face_id:
                    face_id_map[old_id] = new_face_id
                
            # 6. Restore Embeddings with mapped person_id
            for e in e_list:
                old_person_id = e.get("person_id")
                new_person_id = face_id_map.get(old_person_id)
                if not new_person_id: continue
                
                def _decode_blob(val):
                    if isinstance(val, str):
                        try:
                            import base64
                            return base64.b64decode(val)
                        except Exception:
                            pass
                    return val
                
                vec = _decode_blob(e.get("vec"))
                struct_vec = _decode_blob(e.get("struct_vec"))
                lms = _decode_blob(e.get("landmarks_3d")) if e.get("landmarks_3d") else None
                
                c.execute("""INSERT INTO person_embeddings (vendor_id, person_id, class_year, division, branch, vec, dim, struct_vec, landmarks_3d)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (new_vendor_id, new_person_id, e.get("class_year"), e.get("division"), e.get("branch"), vec, e.get("dim"), struct_vec, lms))
            
            conn.commit()
            log_audit("portable_import", {"company": v_data.get("company_name"), "faces_count": len(f_list)}, target_vendor_id=new_vendor_id)
            
            # Trigger FAISS cache refresh for the new vendor
            try:
                from services.face_service import _ensure_vendor_emb_cache
                _ensure_vendor_emb_cache(new_vendor_id, force_refresh=True)
            except Exception: pass
            
            return jsonify({"success": True, "vendor_id": new_vendor_id, "faces_imported": len(f_list)})
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            conn.close()
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/vendors/<int:vendor_id>/leave/students", methods=["GET"])
@super_admin_required
def get_vendor_leave_students(vendor_id):
    conn = get_db_connection()
    try:
        if not getattr(conn, "_is_pg", False):
            conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Link system_users with faces to get names
        c.execute("""
            SELECT 
                su.username,
                su.has_set_password,
                su.role,
                f.name,
                f.phone as face_phone
            FROM system_users su
            LEFT JOIN faces f ON su.person_id = f.id
            WHERE su.vendor_id = ? AND su.role = 'user'
        """, (vendor_id,))
        
        students = []
        for row in c.fetchall():
            r = dict(row)
            # Determine status
            # If password_plain matches face_phone, it's probably the default
            is_default = not bool(r.get('has_set_password'))
            students.append({
                "name": r['name'] or "Unknown Student",
                "student_id": r['username'],
                "phone": r['face_phone'],
                "status": "Default" if is_default else "Changed"
            })
            
        return jsonify({"students": students})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# OVER-THE-AIR (OTA) APK RELEASE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/app-releases", methods=["GET"], strict_slashes=False)
@super_admin_required
def get_admin_app_releases():
    from utils import get_db_connection
    from services.apk_service import list_all_releases, get_latest_release
    conn = get_db_connection()
    try:
        releases = list_all_releases(conn, limit=50)
        latest = get_latest_release(conn)
        return jsonify({
            "releases": releases,
            "latest_release": latest
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@admin_bp.route("/app-releases", methods=["POST"], strict_slashes=False)
@super_admin_required
def upload_admin_app_release():
    from utils import get_db_connection, log_audit
    from services.apk_service import save_apk_release
    
    if "apk_file" not in request.files:
        return jsonify({"error": "No apk_file provided in request"}), 400
    
    apk_file = request.files["apk_file"]
    if not apk_file.filename or not apk_file.filename.lower().endswith(".apk"):
        return jsonify({"error": "Invalid file. Please upload an .apk file"}), 400

    version_code_raw = request.form.get("version_code")
    version_name_raw = request.form.get("version_name")

    version_code = None
    if version_code_raw and version_code_raw.strip():
        try:
            version_code = int(version_code_raw.strip())
        except ValueError:
            return jsonify({"error": "version_code must be an integer"}), 400

    version_name = version_name_raw.strip() if version_name_raw and version_name_raw.strip() else None

    release_notes = request.form.get("release_notes", "")
    force_update = str(request.form.get("force_update", "false")).lower() in ["true", "1", "yes"]
    package_name = request.form.get("package_name", "com.faceplugin.facerecognitionsdk")

    conn = get_db_connection()
    try:
        result = save_apk_release(
            conn=conn,
            file_storage=apk_file,
            version_code=version_code,
            version_name=version_name,
            package_name=package_name,
            release_notes=release_notes,
            force_update=force_update
        )
        actual_code = result.get("version_code", version_code)
        actual_name = result.get("version_name", version_name)
        log_audit("UPLOAD_APP_RELEASE", f"Uploaded APK v{actual_name} (code: {actual_code})")
        return jsonify({
            "message": f"APK release v{actual_name} (code {actual_code}) uploaded and activated successfully",
            "release": result
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@admin_bp.route("/app-releases/<int:release_id>/activate", methods=["POST"], strict_slashes=False)
@super_admin_required
def activate_admin_app_release(release_id):
    from utils import get_db_connection, log_audit
    from services.apk_service import activate_release
    conn = get_db_connection()
    try:
        ok = activate_release(conn, release_id)
        if ok:
            log_audit("ACTIVATE_APP_RELEASE", f"Activated APK release id {release_id}")
            return jsonify({"message": f"Release {release_id} is now active"}), 200
        else:
            return jsonify({"error": "Failed to activate release"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@admin_bp.route("/app-releases/<int:release_id>", methods=["DELETE"], strict_slashes=False)
@super_admin_required
def delete_admin_app_release(release_id):
    from utils import get_db_connection, log_audit
    from services.apk_service import delete_release
    conn = get_db_connection()
    try:
        ok, msg = delete_release(conn, release_id)
        if ok:
            log_audit("DELETE_APP_RELEASE", f"Deleted APK release id {release_id}")
            return jsonify({"message": msg}), 200
        else:
            status_code = 404 if msg == "Release not found" else 400
            return jsonify({"error": msg}), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@admin_bp.route("/app-releases/broadcast", methods=["POST"], strict_slashes=False)
@super_admin_required
def broadcast_app_update_to_kiosks():
    """
    Emits a Socket.IO event to all connected kiosks notifying them that an update is ready.
    """
    from utils import get_db_connection, log_audit
    from services.apk_service import get_latest_release
    from app import socketio
    conn = get_db_connection()
    try:
        latest = get_latest_release(conn)
        if not latest:
            return jsonify({"error": "No active release to broadcast"}), 404

        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/api/public/app/download/latest"

        payload = {
            "version_code": latest["version_code"],
            "version_name": latest["version_name"],
            "package_name": latest.get("package_name"),
            "file_size": latest["file_size"],
            "release_notes": latest.get("release_notes") or "",
            "force_update": bool(latest.get("force_update")),
            "download_url": download_url
        }

        # Broadcast to all connected sockets
        socketio.emit("app_update_available", payload)
        log_audit("BROADCAST_APP_UPDATE", f"Broadcasted v{latest['version_name']} (code {latest['version_code']}) to kiosks")

        return jsonify({
            "message": f"Update notification for v{latest['version_name']} broadcasted successfully to all kiosks",
            "payload": payload
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@admin_bp.route("/app-releases/device-status", methods=["GET"], strict_slashes=False)
@super_admin_required
def get_app_release_device_status():
    from utils import get_db_connection
    from services.apk_service import list_device_update_statuses
    target = request.args.get("version_code")
    conn = get_db_connection()
    try:
        statuses = list_device_update_statuses(conn, target)
        summary = {}
        for item in statuses:
            key = str(item.get("status") or "UNKNOWN")
            summary[key] = summary.get(key, 0) + 1
            if isinstance(item.get("updated_at"), datetime):
                item["updated_at"] = item["updated_at"].isoformat()
        return jsonify({"devices": statuses, "summary": summary})
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        conn.close()
