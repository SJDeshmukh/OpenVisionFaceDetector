import uuid
import numpy as np
import threading
import requests
import sqlite3
import json
import base64
import os
import io
import time
from collections import defaultdict
from datetime import datetime, date, timedelta
from utils import (
    get_db_connection, _run, log_audit, postgres_available,
    is_testing, vendor_has_feature, BUNDLE_FEATURES, ALL_FEATURES,
    REGISTRATION_TEMPLATES, _ensure_class_batch_tables,
    cache_get, cache_set, create_job, get_job, complete_job, fail_job,
    check_vendor_status, CompatConn,
    _VENDOR_EMB_CACHE
)
from services.face_service import _normalize_vec, _decode_data_uri_to_rgb
from flask import current_app as app, Blueprint, request, jsonify, send_file
# Assuming socketio is initialized elsewhere and accessible
# In a modular setup, you might need a way to access the socketio instance
# For now, let's assume it's available via a global or placeholder
socketio = None # To be updated via init_app or similar
from services.attendance_service import (
    calculate_daily_hours, calculate_arrival_status, calculate_expected_hours
)
from services.auth_service import (
    authenticate_vendor_access, verify_token, extract_token
)

# Mock Auth Decorators
def vendor_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        from services.auth_service import authenticate_vendor_access
        vendor_id, err = authenticate_vendor_access()
        if err: return err
        request.vendor_id = vendor_id
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
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
    
def require_feature(feature_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator
    
attendance_bp = Blueprint('attendance_bp', __name__)

@attendance_bp.route("/class-batch/start", methods=["POST"])
def class_batch_start():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    bid = str(uuid.uuid4())[:12]
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("INSERT INTO class_batches (id, vendor_id, class_year, division, branch, status) VALUES (?, ?, ?, ?, ?, ?)",
              (bid, vendor_id, str(data.get('class_year') or ''), str(data.get('division') or ''), str(data.get('branch') or ''), 'active'))
    conn.commit(); conn.close()
    return jsonify({"batch_id": bid})


@attendance_bp.route("/class-batch/add", methods=["POST"])
def class_batch_add():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    bid = request.form.get('batch_id') or request.args.get('batch_id')
    if not bid:
        return jsonify({"error": "batch_id required"}), 400
    params = {
        "class_year": request.form.get('class_year') or request.args.get('class_year') or '',
        "division": request.form.get('division') or request.args.get('division') or '',
        "branch": request.form.get('branch') or request.args.get('branch') or ''
    }
    try:
        fast_raw = request.form.get('fast') or request.args.get('fast')
        if fast_raw is not None:
            params["fast"] = str(fast_raw).strip().lower() in ("1", "true", "yes", "y")
    except Exception:
        pass
    try:
        dms_raw = request.form.get('det_max_side') or request.args.get('det_max_side')
        if dms_raw is not None and str(dms_raw).strip() != "":
            params["det_max_side"] = int(dms_raw)
    except Exception:
        pass
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("SELECT id FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    if not c.fetchone():
        conn.close()
        return jsonify({"error": "batch not found"}), 404
    files = request.files.getlist('images')
    if not files and 'image' in request.files:
        files = [request.files['image']]
    if not files:
        conn.close()
        return jsonify({"error": "no images"}), 400
    created = []
    seq_base = int(time.time())
    for idx, f in enumerate(files):
        raw = f.read()
        img_b64 = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')
        item_id = uuid.uuid4().hex[:12]
        c.execute("INSERT INTO class_batch_items (id, batch_id, seq, image_b64, annotated_b64, faces_json, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (item_id, bid, seq_base + idx, img_b64, '', '[]', 'pending'))
        created.append(item_id)
    conn.commit()
    conn.close()
    
    from celery_app import celery
    if celery:
        from tasks import process_class_batch_items
        process_class_batch_items.delay(bid, vendor_id, params)
    else:
        # Fallback to internal threading if celery is not configured
        def _worker():
            from tasks import process_class_batch_items
            try:
                process_class_batch_items(bid, vendor_id, params)
            except Exception:
                pass
        import threading
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        
    return jsonify({"ok": True, "created": created})


@attendance_bp.route("/class-batch/commit", methods=["POST"])
def class_batch_commit():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    bid = payload.get('batch_id')
    assigns = payload.get('assignments') or []
    class_year = payload.get('class_year') or ''
    division = payload.get('division') or ''
    branch = payload.get('branch') or ''
    threshold = payload.get('threshold')
    if not bid or not isinstance(assigns, list):
        return jsonify({"error": "batch_id and assignments required"}), 400
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS person_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            person_id INTEGER,
            class_year TEXT,
            division TEXT,
            branch TEXT,
            vec BLOB,
            dim INTEGER,
            struct_vec BLOB,
            landmarks_3d TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
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
    except Exception:
        pass
    if threshold is not None:
        try:
            thr = float(threshold)
            c.execute("""INSERT INTO class_thresholds (vendor_id, class_year, division, branch, threshold)
                         VALUES (?, ?, ?, ?, ?)
                         ON CONFLICT(vendor_id, class_year, division, branch)
                         DO UPDATE SET threshold=excluded.threshold, updated_at=CURRENT_TIMESTAMP
                      """, (vendor_id, str(class_year), str(division), str(branch), thr))
            conn.commit()
        except Exception:
            pass
    try:
        from multiple_face_detection import app as mfd_app
    except Exception:
        return jsonify({"error": "embedder unavailable"}), 500
    saved = 0
    for a in assigns:
        try:
            item_id = a.get('item_id'); face_index = a.get('face_index'); person_id = a.get('person_id')
            if not item_id or person_id in (None, '', 0) or face_index is None:
                continue
            c.execute("SELECT faces_json FROM class_batch_items WHERE id = ? AND batch_id = ?", (item_id, bid))
            row = c.fetchone()
            if not row:
                continue
            faces = json.loads(row['faces_json'] if isinstance(row, sqlite3.Row) else row[0] or '[]')
            face = None
            for f in faces:
                if int(f.get('index', -1)) == int(face_index):
                    face = f; break
            if not face:
                continue
            uri = None
            if isinstance(face.get('thumbs'), dict):
                uri = face['thumbs'].get('face') or face.get('thumb')
            else:
                uri = face.get('thumb')
            if not uri:
                continue
            # Prefer the pre-computed embedding vector from detection (avoids JPEG re-encoding mismatch)
            emb_vec_b64 = face.get('emb_vec') or ''
            if emb_vec_b64:
                try:
                    raw_bytes = base64.b64decode(emb_vec_b64)
                    emb = np.frombuffer(raw_bytes, dtype=np.float32).copy()
                    emb = _normalize_vec(emb)
                except Exception:
                    emb = None
            else:
                emb = None
            if emb is None or emb.size == 0:
                # Fallback: re-embed from thumbnail (less accurate)
                img_rgb = _decode_data_uri_to_rgb(uri)
                if img_rgb is None:
                    continue
                emb = mfd_app.get_embedder().embed(img_rgb)
                emb = _normalize_vec(emb)
            if emb is None or emb.size == 0:
                continue
            vec_blob = emb.astype(np.float32).tobytes()
            dim = int(emb.size)

            struct_vec_b64 = face.get('struct_vec') or ''
            landmarks_3d = face.get('landmarks_3d') or []
            
            struct_blob = None
            if struct_vec_b64:
                try:
                    s_bytes = base64.b64decode(struct_vec_b64)
                    s_emb = np.frombuffer(s_bytes, dtype=np.float32).copy()
                    if s_emb.size > 0:
                        struct_blob = s_emb.astype(np.float32).tobytes()
                except Exception:
                    pass
            lmks_json = json.dumps(landmarks_3d) if landmarks_3d else None

            c.execute("""INSERT INTO person_embeddings (vendor_id, person_id, class_year, division, branch, vec, dim, struct_vec, landmarks_3d)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                      """, (vendor_id, int(person_id), str(class_year), str(division), str(branch), vec_blob, dim, struct_blob, lmks_json))
            saved += 1
        except Exception:
            continue
    conn.commit()
    # Invalidate ALL embedding caches for this vendor
    try:
        prefix = f"{int(vendor_id or 0)}_"
        keys_to_delete = [k for k in _VENDOR_EMB_CACHE.keys() if str(k).startswith(prefix)]
        for k in keys_to_delete:
            del _VENDOR_EMB_CACHE[k]
    except Exception:
        pass
    conn.close()
    return jsonify({"ok": True, "saved": saved})


@attendance_bp.route("/class-batch/status", methods=["GET"])
def class_batch_status():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    bid = request.args.get('batch_id')
    if not bid:
        return jsonify({"error": "batch_id required"}), 400
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("SELECT id, class_year, division, branch, status FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    b = c.fetchone()
    if not b:
        conn.close()
        return jsonify({"error": "batch not found"}), 404
    c.execute("SELECT id, seq, image_b64, annotated_b64, faces_json, status FROM class_batch_items WHERE batch_id = ? ORDER BY seq ASC", (bid,))
    rows = c.fetchall() or []
    conn.close()
    items = []
    for r in rows:
        items.append({"id": r[0], "seq": r[1], "image": r[2], "annotated": r[3], "faces": json.loads(r[4] or "[]"), "status": r[5]})
    return jsonify({"batch": {"id": b[0], "class_year": b[1], "division": b[2], "branch": b[3], "status": b[4]}, "items": items})


@attendance_bp.route("/class-batch/clear", methods=["POST"])
def class_batch_clear():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    bid = data.get('batch_id')
    if not bid:
        return jsonify({"error": "batch_id required"}), 400
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("DELETE FROM class_batch_items WHERE batch_id = ?", (bid,))
    c.execute("DELETE FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@attendance_bp.route("/class-batch/refresh", methods=["POST"])
def class_batch_refresh():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    bid = data.get('batch_id')
    if not bid:
        return jsonify({"error": "batch_id required"}), 400
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("SELECT id, vendor_id, class_year, division, branch FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "batch not found"}), 404
    params = {
        "class_year": str(row[2] or ""),
        "division": str(row[3] or ""),
        "branch": str(row[4] or "")
    }
    try:
        if 'fast' in data:
            params["fast"] = bool(data.get('fast'))
    except Exception:
        pass
    try:
        if 'det_max_side' in data and data.get('det_max_side') is not None:
            params["det_max_side"] = int(data.get('det_max_side'))
    except Exception:
        pass
    conn.close()
    from tasks import refresh_class_batch_items
    refresh_class_batch_items.delay(bid, vendor_id, params)
    return jsonify({"ok": True})


@attendance_bp.route("/reports/analytics", methods=["GET"])
@require_feature("reports")
def get_analytics():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    if not vendor_id: return jsonify({"error": "Vendor context required"}), 400

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Fetch Timetable (Multi-tenant)
    c.execute("SELECT live_timetable FROM companies WHERE vendor_id = ?", (vendor_id,))
    company_row = c.fetchone()
    
    # Fallback to legacy company if not found (e.g. for initial migration)
    if not company_row:
         # Force Vendor ID check if we are in multi-tenant mode
         if vendor_id:
             c.execute("SELECT live_timetable FROM companies WHERE vendor_id = ?", (vendor_id,))
             company_row = c.fetchone()
         else:
             # If no vendor_id (SuperAdmin without context), we do NOT fallback to Company 1.
             # Strict multi-tenancy: No data shown without explicit vendor context.
             pass

    timetable = []
    if company_row and company_row['live_timetable']:
        try:
            timetable = json.loads(company_row['live_timetable'])
        except:
            timetable = []

    late_enabled = vendor_has_feature(vendor_id, "late_mark")
    # Fetch Late Grace Period
    c.execute("SELECT value FROM system_settings WHERE key='late_grace_period'")
    row = c.fetchone()
    grace_period = int(row['value']) if row else 15

    def get_late_users(target_date_str):
        if not late_enabled:
            return []
        # 1. Try to use is_late column (New Logic)
        try:
            # Join with faces to filter by vendor
            c.execute("""
                SELECT COUNT(DISTINCT COALESCE(a.person_id, f.id)) as count 
                FROM attendance a
                JOIN faces f ON (a.person_id IS NOT NULL AND a.person_id = f.id) OR (a.person_id IS NULL AND a.name = f.name AND a.vendor_id = f.vendor_id)
                WHERE date(a.timestamp) = ? AND a.is_late = 1 AND a.vendor_id = ?
            """, (target_date_str, vendor_id))
            db_late_count = c.fetchone()['count']
            
            if db_late_count > 0:
                c.execute("""
                    SELECT DISTINCT COALESCE(a.person_id, f.id) AS person_id
                    FROM attendance a
                    JOIN faces f ON (a.person_id IS NOT NULL AND a.person_id = f.id) OR (a.person_id IS NULL AND a.name = f.name AND a.vendor_id = f.vendor_id)
                    WHERE date(a.timestamp) = ? AND a.is_late = 1 AND a.vendor_id = ?
                """, (target_date_str, vendor_id))
                ids = []
                for r in c.fetchall():
                    try:
                        pid = r['person_id']
                        if pid is not None:
                            ids.append(pid)
                    except Exception:
                        pass
                return ids
        except Exception as e:
            pass # print(f"Error checking is_late column: {e}")

        # 2. Fallback to calculation
        day_name = datetime.strptime(target_date_str, '%Y-%m-%d').strftime('%a')
        
        # Fetch all Check-Ins for the date with User Shift (First Check-in per user)
        # Filter by vendor_id
        c.execute("""
            SELECT COALESCE(a.person_id, f.id) AS person_id, MIN(a.timestamp) as timestamp, f.shift
            FROM attendance a
            JOIN faces f ON (a.person_id IS NOT NULL AND a.person_id = f.id) OR (a.person_id IS NULL AND a.name = f.name AND a.vendor_id = f.vendor_id)
            WHERE date(a.timestamp) = ? AND a.status = 'CHECK_IN' AND a.vendor_id = ?
            GROUP BY COALESCE(a.person_id, f.id)
        """, (target_date_str, vendor_id))
        
        records = c.fetchall()
        late_users = []
        
        for row in records:
            pid = row['person_id']
            ts_str = row['timestamp']
            shift_name = row['shift'] if 'shift' in row.keys() else None
            
            # Filter timetable for this day
            day_acts = [t for t in timetable if day_name in t.get('days', []) and t.get('type', '').lower() == 'work']
            
            # Match shift
            matched_act = None
            if shift_name:
                # 1. Match by Shift ID if the activity is explicitly linked to a shift object
                # First, find the shift object in the company's 'shifts' array that matches this name
                c.execute("SELECT shifts FROM companies WHERE vendor_id = ?", (vendor_id,))
                s_row = c.fetchone()
                shifts_list = json.loads(s_row['shifts']) if s_row and s_row['shifts'] else []
                
                target_shift_id = None
                for s_obj in shifts_list:
                    if s_obj.get('name') == shift_name:
                        target_shift_id = s_obj.get('id')
                        break
                
                # 2. Match activity by shift_id OR name
                for act in day_acts:
                    # If we found a shift ID, try matching that first
                    if target_shift_id and act.get('shift_id') == target_shift_id:
                        matched_act = act
                        break
                    # Fallback to matching by name
                    if act.get('name') == shift_name:
                        matched_act = act
                        break
            
            # If no shift matched or no shift assigned, pick first work act (Fallback)
            if not matched_act and day_acts:
                matched_act = day_acts[0]
            
            if matched_act:
                work_start = matched_act.get('start_time', "09:00")
                try:
                    h, m = map(int, work_start.split(':'))
                    threshold_mins = h * 60 + m + grace_period
                    
                    # Parse timestamp
                    if '.' in ts_str:
                         ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f')
                    else:
                         ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    
                    checkin_mins = ts.hour * 60 + ts.minute
                    
                    if checkin_mins > threshold_mins:
                        late_users.append(pid)
                except:
                    pass
        return late_users

    # 1. Overall Stats (Today)
    today_date = datetime.now()
    today_str = today_date.strftime('%Y-%m-%d')
    
    late_users_today = get_late_users(today_str)
    late_today = len(late_users_today)

    c.execute("""
        SELECT COUNT(DISTINCT COALESCE(a.person_id, f.id)) as count 
        FROM attendance a
        JOIN faces f ON (a.person_id IS NOT NULL AND a.person_id = f.id) OR (a.person_id IS NULL AND a.name = f.name AND a.vendor_id = f.vendor_id)
        WHERE date(a.timestamp) = ? AND a.vendor_id = ?
    """, (today_str, vendor_id))
    present_today = c.fetchone()['count']
    
    c.execute("SELECT COUNT(*) as count FROM faces WHERE vendor_id = ?", (vendor_id,))
    total_users = c.fetchone()['count']
    
    absent_today = max(0, total_users - present_today)
    on_time_today = max(0, present_today - late_today)

    # 2. Daily Attendance Trend (Last 7 Days)
    dates = [(today_date - timedelta(days=i)) for i in range(6, -1, -1)]
    attendance_trend = []
    
    for d_obj in dates:
        d_str = d_obj.strftime('%Y-%m-%d')
        
        c.execute("""
            SELECT COUNT(DISTINCT COALESCE(a.person_id, f.id)) as count 
            FROM attendance a
            JOIN faces f ON (a.person_id IS NOT NULL AND a.person_id = f.id) OR (a.person_id IS NULL AND a.name = f.name AND a.vendor_id = f.vendor_id)
            WHERE date(a.timestamp) = ? AND a.vendor_id = ?
        """, (d_str, vendor_id))
        present = c.fetchone()['count']
        absent = max(0, total_users - present)
        
        late = len(get_late_users(d_str))

        attendance_trend.append({
            "name": d_obj.strftime('%a'),
            "date": d_str,
            "present": present,
            "absent": absent,
            "late": late,
            "total": total_users
        })

    # 3. Department Stats (Late Arrivals Today)
    dept_data = []
    if late_users_today:
        placeholders = ','.join(['?'] * len(late_users_today))
        # Also ensure we only select from our vendor (redundant but safe)
        c.execute(f"""
            SELECT department, COUNT(*) as count
            FROM faces 
            WHERE id IN ({placeholders})
            AND department IS NOT NULL AND department != ''
            AND vendor_id = ?
            GROUP BY department
        """, late_users_today + [vendor_id])
        dept_rows = c.fetchall()
        dept_data = [{"name": row['department'], "late": row['count']} for row in dept_rows]

    conn.close()

    return jsonify({
        "pie_data": [
            {"name": "On Time", "value": on_time_today},
            {"name": "Late", "value": late_today},
            {"name": "Absent", "value": absent_today}
        ],
        "bar_data": attendance_trend,
        "dept_data": dept_data,
        "summary": {
            "total_users": total_users,
            "present_today": present_today,
            "late_today": late_today,
            "absent_today": absent_today
        }
    })


@attendance_bp.route("/reports/export", methods=["GET"])
@require_feature("reports")
def export_report():
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    import csv
    import io
    from flask import Response
    from collections import defaultdict
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    def normalize_registration_config(raw):
        out = []
        if not raw:
            return out
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return out
        if not isinstance(raw, list):
            return out
        for f in raw:
            if not isinstance(f, dict):
                continue
            if f.get("enabled", True) is False:
                continue
            key = f.get("field") or f.get("key")
            if not key:
                continue
            label = f.get("label") or key
            options = f.get("options") if isinstance(f.get("options"), list) else None
            out.append({"key": str(key), "label": str(label), "options": options})
        return out

    STANDARD_PERSON_FIELDS = set()
    enabled_fields = []
    standard_fields = []
    dynamic_fields = []
    if vendor_id:
        try:
            c.execute("PRAGMA table_info(vendors)")
            vcols = [info[1] for info in c.fetchall()]
        except Exception:
            vcols = []
        reg_select = "registration_config" if "registration_config" in vcols else "NULL AS registration_config"
        c.execute(f"SELECT {reg_select} FROM vendors WHERE id = ?", (vendor_id,))
        row = c.fetchone()
        val = None
        if row is not None:
            try:
                val = row['registration_config'] if hasattr(row, 'keys') and 'registration_config' in row.keys() else row[0]
            except Exception:
                val = None
        enabled_fields = normalize_registration_config(val)
        standard_fields = [f for f in enabled_fields if f["key"] in STANDARD_PERSON_FIELDS]
        dynamic_fields = [f for f in enabled_fields if f["key"] not in STANDARD_PERSON_FIELDS]
    
    # Filters
    start_date_str = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date_str = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    department = request.args.get('department')
    designation = request.args.get('designation')
    shift = request.args.get('shift')
    phone = request.args.get('phone')
    report_type = request.args.get('type', 'detailed') # detailed or summary
    is_async = request.args.get('async') == 'true'
    dynamic_filters = {}
    try:
        for k, v in request.args.items():
            if k.startswith('dynamic_') and v:
                dynamic_key = k[len('dynamic_'):]
                dynamic_filters[dynamic_key] = v
    except Exception:
        dynamic_filters = {}
    
    if report_type == 'summary':
        resp = get_payroll_report()
        if isinstance(resp, tuple):
            return resp
        data = {}
        try:
            data = resp.get_json()
        except Exception:
            pass
        payroll = data.get('payroll', [])
        output = io.StringIO()
        writer = csv.writer(output)
        headers = ['Employee Name']
        for f in standard_fields:
            headers.append(f["label"])
        headers += [
            'Days Present', 'Total Hours (Formatted)', 'Total Payable Hours',
            'Standard Daily Hours', 'Daily Wage', 'Hourly Rate', 'Total Estimated Wage'
        ]
        for field in dynamic_fields:
            headers.append(field["label"])
        writer.writerow(headers)
        for p in payroll:
            row_data = [
                p.get('name'),
            ]
            for f in standard_fields:
                row_data.append(p.get(f["key"]) or '')
            row_data += [
                p.get('days_present', 0),
                p.get('total_hours_str', ''),
                p.get('total_hours', 0),
                p.get('standard_daily_hours', 8.0),
                p.get('daily_wage', 0),
                p.get('hourly_rate', 0),
                p.get('total_cost', 0),
            ]
            for field in dynamic_fields:
                row_data.append(p.get(field["key"]) or '-')
            writer.writerow(row_data)
        output.seek(0)
        csv_data = output.getvalue()
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=payroll_summary_{start_date_str}_to_{end_date_str}.csv"}
        )

    # --- Default Detailed Log Report ---
    # (dynamic_fields already fetched above)

    try:
        c.execute("PRAGMA table_info(attendance)")
        acols = [info[1] for info in c.fetchall()]
    except Exception:
        acols = []
    person_sel = "a.person_id" if "person_id" in acols else "NULL AS person_id"
    join_cond = "a.person_id IS NOT NULL AND a.person_id = f.id" if "person_id" in acols else "a.name = f.name AND f.vendor_id = a.vendor_id"
    query = f"""
        SELECT a.name, {person_sel}, a.timestamp, a.status, a.is_late, f.department, f.designation, f.shift, f.phone, f.custom_data
        FROM attendance a
        LEFT JOIN faces f ON ({join_cond}) 
        WHERE date(a.timestamp) BETWEEN ? AND ?
    """
    params = [start_date_str, end_date_str]
    
    if vendor_id:
        query += " AND a.vendor_id = ?"
        params.append(vendor_id)

    if department:
        query += " AND f.department = ?"
        params.append(department)
        
    if designation:
        query += " AND f.designation = ?"
        params.append(designation)
    if shift:
        query += " AND f.shift = ?"
        params.append(shift)
    if phone:
        query += " AND f.phone = ?"
        params.append(phone)
        
    query += " ORDER BY a.timestamp DESC"
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = ['Name', 'Date', 'Time', 'Status']
    for f in standard_fields:
        headers.append(f["label"])
    for field in dynamic_fields:
        headers.append(field["label"])
    
    writer.writerow(headers)
    
    for row in rows:
        if dynamic_filters:
            try:
                import json
                cd = json.loads(row['custom_data']) if row['custom_data'] else {}
            except Exception:
                cd = {}
            should_skip = False
            for dk, dv in dynamic_filters.items():
                val = cd.get(dk)
                if val is None:
                    fallback_key = None
                    for f in dynamic_fields:
                        if f['key'] == dk:
                            fallback_key = f['label']
                            break
                    if fallback_key:
                        val = cd.get(fallback_key)
                if str(val) != str(dv):
                    should_skip = True
                    break
            if should_skip:
                continue
        try:
            ts = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            ts = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
            
        date_str = ts.strftime('%Y-%m-%d')
        time_str = ts.strftime('%I:%M %p')
        
        status_str = row['status']
        if row['status'] == 'CHECK_IN' and 'is_late' in row.keys() and row['is_late'] == 1:
            status_str = 'Late'
            
        row_data = [
            row['name'], 
            date_str, 
            time_str, 
            status_str
        ]
        for f in standard_fields:
            k = f["key"]
            row_data.append(row[k] or 'N/A')
        
        # Parse Custom Data for Dynamic Fields
        custom_data = {}
        if row['custom_data']:
            try:
                import json
                custom_data = json.loads(row['custom_data'])
            except:
                pass
        
        for field in dynamic_fields:
            val = custom_data.get(field["key"])
            if val is None:
                val = custom_data.get(field["label"])
            if val is None:
                val = '-'
            row_data.append(val)
            
        writer.writerow(row_data)
    
    output.seek(0)
    csv_data2 = output.getvalue()
    if is_async:
        job_id = create_job(content_type="text/csv", ttl=600)
        def _bg2():
            try:
                complete_job(job_id, csv_data2)
                socketio.emit('job_completed', {'job_id': job_id, 'type': 'report_export', 'vendor_id': vendor_id})
            except Exception as e:
                fail_job(job_id, e)
        eventlet.spawn_n(_bg2)
        return jsonify({"success": True, "job_id": job_id, "processing": True})
    return Response(
        csv_data2,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=attendance_log_{start_date_str}_to_{end_date_str}.csv"}
    )


@attendance_bp.route("/jobs/<job_id>/status", methods=["GET"])
def job_status(job_id):
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    j = get_job(job_id)
    if not j:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": j["status"], "error": j["error"]})


@attendance_bp.route("/jobs/<job_id>/result", methods=["GET"])
def job_result(job_id):
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    from flask import Response
    j = get_job(job_id)
    if not j:
        return jsonify({"error": "Not found"}), 404
    if j["status"] != "done":
        return jsonify({"status": j["status"]}), 202
    return Response(j["result"], mimetype=j["content_type"])


@attendance_bp.route("/reports/filters", methods=["GET"])
@require_feature("reports")
def get_report_filters():
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    try:
        import hashlib
        qs_hash = hashlib.md5((request.query_string or b"").decode("utf-8", "ignore").encode("utf-8")).hexdigest()
    except Exception:
        qs_hash = "nohash"
    cache_key = f"report_filters_{vendor_id or 'global'}_{qs_hash}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    def normalize_registration_config(raw):
        out = []
        if not raw:
            return out
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return out
        if not isinstance(raw, list):
            return out
        for f in raw:
            if not isinstance(f, dict):
                continue
            if f.get("enabled", True) is False:
                continue
            key = f.get("field") or f.get("key")
            if not key:
                continue
            label = f.get("label") or key
            options = f.get("options") if isinstance(f.get("options"), list) else None
            out.append({"key": str(key), "label": str(label), "options": options})
        return out

    STANDARD_PERSON_FIELDS = set()
    enabled_fields = []
    if vendor_id:
        try:
            c.execute("PRAGMA table_info(vendors)")
            vcols = [info[1] for info in c.fetchall()]
        except Exception:
            vcols = []
        reg_select = "registration_config" if "registration_config" in vcols else "NULL AS registration_config"
        c.execute(f"SELECT {reg_select} FROM vendors WHERE id = ?", (vendor_id,))
        row = c.fetchone()
        val = None
        if row is not None:
            try:
                # row could be tuple or Row; handle both
                val = row['registration_config'] if hasattr(row, 'keys') and 'registration_config' in row.keys() else row[0]
            except Exception:
                val = None
        enabled_fields = normalize_registration_config(val)
    enabled_standard = {f["key"] for f in enabled_fields if f["key"] in STANDARD_PERSON_FIELDS}
    visible_standard_filters = {
        "department": False,
        "designation": False,
        "shift": False,
        "phone": False
    }

    selected_standard = {
        "department": request.args.get("department"),
        "designation": request.args.get("designation"),
        "shift": request.args.get("shift"),
        "phone": request.args.get("phone")
    }
    selected_standard = {k: v for k, v in selected_standard.items() if v is not None and str(v).strip() != ""}
    selected_dynamic = {}
    try:
        for k, v in request.args.items():
            if v is None or str(v).strip() == "":
                continue
            if k.startswith("dynamic_"):
                selected_dynamic[k[len("dynamic_"):]] = str(v).strip()
    except Exception:
        selected_dynamic = {}

    faces = []
    params = []
    query = "SELECT name, department, designation, shift, phone, custom_data FROM faces"
    try:
        c.execute("PRAGMA table_info(faces)")
        fcols = [info[1] for info in c.fetchall()]
        if 'custom_data' not in fcols:
            c.execute("ALTER TABLE faces ADD COLUMN custom_data TEXT DEFAULT NULL")
            conn.commit()
    except Exception:
        pass
    if vendor_id:
        query += " WHERE vendor_id = ?"
        params.append(vendor_id)
    c.execute(query, params)
    for r in c.fetchall():
        face_custom = {}
        try:
            if r["custom_data"]:
                face_custom = json.loads(r["custom_data"])
        except Exception:
            face_custom = {}
        faces.append({
            "name": r["name"],
            "department": r["department"],
            "designation": r["designation"],
            "shift": r["shift"],
            "phone": r["phone"],
            "custom": face_custom
        })

    def face_matches(face):
        for k, v in selected_standard.items():
            if str(face.get(k) or "").strip() != str(v).strip():
                return False
        for k, v in selected_dynamic.items():
            rv = None
            if k in face["custom"]:
                rv = face["custom"].get(k)
            else:
                for ef in enabled_fields:
                    if ef.get("key") == k:
                        rv = face["custom"].get(ef.get("label"))
                        break
            if rv is None or str(rv).strip() != str(v).strip():
                return False
        return True

    filtered_faces = [f for f in faces if face_matches(f)]

    departments = sorted({str(f.get("department")).strip() for f in filtered_faces if str(f.get("department") or "").strip() != ""}) if visible_standard_filters["department"] else []
    designations = sorted({str(f.get("designation")).strip() for f in filtered_faces if str(f.get("designation") or "").strip() != ""}) if visible_standard_filters["designation"] else []
    shifts = sorted({str(f.get("shift")).strip() for f in filtered_faces if str(f.get("shift") or "").strip() != ""}) if visible_standard_filters["shift"] else []
    phones = sorted({str(f.get("phone")).strip() for f in filtered_faces if str(f.get("phone") or "").strip() != ""}) if visible_standard_filters["phone"] else []

    dynamic_filters = {}
    if enabled_fields:
        for field in enabled_fields:
            field_key = str(field.get("key") or "").strip()
            field_label = str(field.get("label") or field_key).strip()
            if not field_key:
                continue
            base_keys = {"name", "department", "designation", "shift", "phone"}
            fk_lower = field_key.lower()
            fl_lower = field_label.lower()
            unique_values = set()
            for f in filtered_faces:
                # Prefer base column if present (e.g., name, department)
                val = f.get(field_key)
                if val is None and fk_lower in base_keys:
                    for bk in base_keys:
                        if fk_lower == bk:
                            val = f.get(bk)
                            break
                if val is None and fl_lower in base_keys:
                    for bk in base_keys:
                        if fl_lower == bk:
                            val = f.get(bk)
                            break
                if val is None:
                    if field_key in f["custom"]:
                        val = f["custom"].get(field_key)
                    if val is None:
                        val = f["custom"].get(field_label)
                if val is not None and str(val).strip() != "":
                    unique_values.add(str(val).strip())
            if field.get("options"):
                allowed = [str(x) for x in (field.get("options") or [])]
                if unique_values:
                    allowed = [x for x in allowed if x in unique_values]
                dynamic_filters[field_key] = {"label": field_label, "options": allowed}
            else:
                dynamic_filters[field_key] = {"label": field_label, "options": sorted(list(unique_values))[:200]}

    conn.close()
    
    result = {
        "departments": departments,
        "designations": designations,
        "shifts": shifts,
        "phones": phones,
        "visible_standard_filters": visible_standard_filters,
        "dynamic_filters": dynamic_filters
    }
    cache_set(cache_key, result, 15)
    return jsonify(result)


@attendance_bp.route("/attendance/filters", methods=["GET"])
def get_attendance_filters():
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    try:
        import hashlib
        qs_hash = hashlib.md5((request.query_string or b"").decode("utf-8", "ignore").encode("utf-8")).hexdigest()
    except Exception:
        qs_hash = "nohash"
    cache_key = f"attendance_filters_{vendor_id or 'global'}_{qs_hash}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    def normalize_registration_config(raw):
        out = []
        if not raw:
            return out
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return out
        if not isinstance(raw, list):
            return out
        for f in raw:
            if not isinstance(f, dict):
                continue
            if f.get("enabled", True) is False:
                continue
            key = f.get("field") or f.get("key")
            if not key:
                continue
            label = f.get("label") or key
            options = f.get("options") if isinstance(f.get("options"), list) else None
            out.append({"key": str(key), "label": str(label), "options": options})
        return out

    STANDARD_PERSON_FIELDS = {"department", "designation", "shift", "phone"}
    enabled_fields = []
    if vendor_id:
        c.execute("SELECT registration_config FROM vendors WHERE id = ?", (vendor_id,))
        row = c.fetchone()
        enabled_fields = normalize_registration_config(row['registration_config'] if row else None)
    enabled_standard = {f["key"] for f in enabled_fields if f["key"] in STANDARD_PERSON_FIELDS}
    visible_standard_filters = {
        "department": "department" in enabled_standard,
        "designation": "designation" in enabled_standard,
        "shift": "shift" in enabled_standard,
        "phone": "phone" in enabled_standard
    }

    selected_standard = {
        "name": request.args.get("name"),
        "department": request.args.get("department"),
        "designation": request.args.get("designation"),
        "shift": request.args.get("shift"),
        "phone": request.args.get("phone")
    }
    selected_standard = {k: v for k, v in selected_standard.items() if v is not None and str(v).strip() != ""}

    selected_dynamic = {}
    if enabled_fields:
        enabled_dynamic_keys = {f["key"] for f in enabled_fields}
        for k, v in request.args.items():
            if k in enabled_dynamic_keys and v is not None and str(v).strip() != "":
                selected_dynamic[k] = str(v).strip()

    faces = []
    params = []
    query = "SELECT name, department, designation, shift, phone, custom_data FROM faces"
    if vendor_id:
        query += " WHERE vendor_id = ?"
        params.append(vendor_id)
    c.execute(query, params)
    for r in c.fetchall():
        face_custom = {}
        try:
            if r["custom_data"]:
                face_custom = json.loads(r["custom_data"])
        except Exception:
            face_custom = {}
        faces.append({
            "name": r["name"],
            "department": r["department"],
            "designation": r["designation"],
            "shift": r["shift"],
            "phone": r["phone"],
            "custom": face_custom
        })

    def face_matches(face):
        base_keys = {"name", "department", "designation", "shift", "phone"}
        for k, v in selected_standard.items():
            if str(face.get(k) or "").strip() != str(v).strip():
                return False
        for k, v in selected_dynamic.items():
            rv = None
            # Prefer base column if present
            kl = str(k).strip().lower()
            if k in face:
                rv = face.get(k)
            if rv is None and kl in base_keys:
                # Case-insensitive map to base column
                for bk in base_keys:
                    if kl == bk and bk in face:
                        rv = face.get(bk)
                        break
            if rv is None:
                if k in face["custom"]:
                    rv = face["custom"].get(k)
            if rv is None:
                for ef in enabled_fields:
                    if ef.get("key") == k:
                        rv = face["custom"].get(ef.get("label"))
                        break
            if rv is None or str(rv).strip() != str(v).strip():
                return False
        return True

    filtered_faces = [f for f in faces if face_matches(f)]

    names = sorted({str(f.get("name")).strip() for f in filtered_faces if str(f.get("name") or "").strip() != ""})
    departments = sorted({str(f.get("department")).strip() for f in filtered_faces if str(f.get("department") or "").strip() != ""}) if visible_standard_filters["department"] else []
    designations = sorted({str(f.get("designation")).strip() for f in filtered_faces if str(f.get("designation") or "").strip() != ""}) if visible_standard_filters["designation"] else []
    shifts = sorted({str(f.get("shift")).strip() for f in filtered_faces if str(f.get("shift") or "").strip() != ""}) if visible_standard_filters["shift"] else []
    phones = sorted({str(f.get("phone")).strip() for f in filtered_faces if str(f.get("phone") or "").strip() != ""}) if visible_standard_filters["phone"] else []

    dynamic_filters = {}
    if enabled_fields:
        base_keys = {"name", "department", "designation", "shift", "phone"}
        for field in enabled_fields:
            field_key = str(field.get("key") or "").strip()
            field_label = str(field.get("label") or field_key).strip()
            if not field_key:
                continue
            unique_values = set()
            for f in filtered_faces:
                val = f.get(field_key)
                if val is None:
                    # case-insensitive base column mapping
                    fk_lower = field_key.lower()
                    fl_lower = field_label.lower()
                    if fk_lower in base_keys:
                        for bk in base_keys:
                            if fk_lower == bk:
                                val = f.get(bk)
                                break
                    if val is None and fl_lower in base_keys:
                        for bk in base_keys:
                            if fl_lower == bk:
                                val = f.get(bk)
                                break
                if val is None and field_key in f["custom"]:
                    val = f["custom"].get(field_key)
                if val is None:
                    val = f["custom"].get(field_label)
                if val is not None and str(val).strip() != "":
                    unique_values.add(str(val).strip())
            if field.get("options"):
                allowed = [str(x) for x in (field.get("options") or [])]
                if unique_values:
                    allowed = [x for x in allowed if x in unique_values]
                dynamic_filters[field_key] = {"label": field_label, "options": allowed}
            else:
                dynamic_filters[field_key] = {"label": field_label, "options": sorted(list(unique_values))[:200]}

    conn.close()
    result = {
        "names": names,
        "departments": departments,
        "designations": designations,
        "shifts": shifts,
        "phones": phones,
        "visible_standard_filters": visible_standard_filters,
        "dynamic_filters": dynamic_filters
    }
    cache_set(cache_key, result, 15)
    return jsonify(result)


@attendance_bp.route("/attendance/filters/debug", methods=["GET"])
def get_attendance_filters_debug():
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT registration_config FROM vendors WHERE id = ?", (vendor_id,))
    row = c.fetchone()
    raw = row['registration_config'] if row else None
    def normalize_registration_config(raw):
        out = []
        if not raw:
            return out
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return out
        if not isinstance(raw, list):
            return out
        for f in raw:
            if not isinstance(f, dict):
                continue
            if f.get("enabled", True) is False:
                continue
            key = f.get("field") or f.get("key")
            if not key:
                continue
            label = f.get("label") or key
            options = f.get("options") if isinstance(f.get("options"), list) else None
            out.append({"key": str(key), "label": str(label), "options": options})
        return out
    enabled_fields = normalize_registration_config(raw)
    # Compose current dynamic filters using existing logic
    request_args = request.args.to_dict()
    for k in list(request_args.keys()):
        if request_args[k] is None or str(request_args[k]).strip() == "":
            del request_args[k]
    # Reuse get_attendance_filters result
    res = get_attendance_filters()
    try:
        data = res.get_json()
    except Exception:
        data = {}
    return jsonify({
        "vendor_id": vendor_id,
        "registration_fields": enabled_fields,
        "dynamic_filters": data.get("dynamic_filters", {}),
        "visible_standard_filters": data.get("visible_standard_filters", {})
    })

@attendance_bp.route("/reports/payroll", methods=["GET"])
def get_payroll_report():
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400
        
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch Timetable and Working Hours
    if vendor_id:
        try:
            c.execute("PRAGMA table_info(companies)")
            ccols = [info[1] for info in c.fetchall()]
        except Exception:
            ccols = []
        wh_select = "working_hours" if "working_hours" in ccols else "NULL AS working_hours"
        c.execute(f"SELECT live_timetable, {wh_select} FROM companies WHERE vendor_id = ?", (vendor_id,))
        company_row = c.fetchone()
    else:
        return jsonify({"error": "Vendor context required"}), 400

    timetable = []
    company_working_hours = 8.0 # Default

    if company_row:
        if company_row['live_timetable']:
            try:
                timetable = json.loads(company_row['live_timetable'])
            except:
                timetable = []
        try:
            if company_row['working_hours']:
                company_working_hours = float(company_row['working_hours'])
        except Exception:
            pass

    late_enabled = vendor_has_feature(vendor_id, "late_mark")

    # 2. Fetch Persons (to get wages and late config)
    if vendor_id:
        try:
            c.execute("PRAGMA table_info(faces)")
            fcols = [info[1] for info in c.fetchall()]
        except Exception:
            fcols = []
        extra = []
        if "late_allowance_days" in fcols:
            extra.append("late_allowance_days")
        if "late_deduction_amount" in fcols:
            extra.append("late_deduction_amount")
        extra_select = ", " + ", ".join(extra) if extra else ""
        c.execute(f"SELECT id, name, daily_wage, department, designation, face_image, phone{extra_select} FROM faces WHERE vendor_id = ?", (vendor_id,))
    else:
        c.execute("SELECT id, name, daily_wage, department, designation, face_image, phone FROM faces")
    
    persons = {row['id']: dict(row) for row in c.fetchall()}
    name_to_ids = defaultdict(list)
    for pid, info in persons.items():
        try:
            name_to_ids[info.get('name')].append(pid)
        except Exception:
            pass

    # 3. Fetch Global Settings
    try:
        c.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
    except Exception:
        pass
    c.execute("SELECT key, value FROM system_settings WHERE key IN ('global_late_allowance', 'global_late_deduction')")
    settings = {row['key']: row['value'] for row in c.fetchall()}
    global_allowance = int(settings.get('global_late_allowance', 7))
    global_deduction = float(settings.get('global_late_deduction', 0.0))
    
    # 4. Fetch Attendance (With Buffer for Cross-Day Shifts)
    try:
        s_dt = datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=1)
        e_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
    except ValueError:
        conn.close()
        return jsonify({"error": "Invalid date format"}), 400

    query = """
        SELECT * FROM attendance 
        WHERE date(timestamp) BETWEEN ? AND ? 
    """
    params = [s_dt.strftime('%Y-%m-%d'), e_dt.strftime('%Y-%m-%d')]
    
    if vendor_id:
        query += " AND vendor_id = ?"
        params.append(vendor_id)
        
    query += " ORDER BY timestamp ASC"
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    # Group by person_id ONLY (Continuous Stream)
    user_records = defaultdict(list)
    for row in rows:
        pid = None
        try:
            if 'person_id' in row.keys():
                pid = row['person_id']
        except Exception:
            pid = None
        if not pid:
            nm = None
            try:
                nm = row['name']
            except Exception:
                nm = None
            ids = name_to_ids.get(nm, [])
            if len(ids) == 1:
                pid = ids[0]
        if not pid:
            continue
        user_records[pid].append(dict(row))
        
    # Calculate Totals
    payroll_data = []
    
    # Iterate over all known persons
    for pid, person_info in persons.items():
        total_hours = 0
        present_dates = set()
        late_marks_count = 0
        
        records = user_records.get(pid, [])
        
        # Calculate continuous sessions
        # Pass today_str to capture real-time active session
        today_str = datetime.now().strftime('%Y-%m-%d')
        stats = calculate_daily_hours(records, timetable, date_str=today_str)
        
        start_dt_req = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt_req = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        # Calculate Late Marks Count for the requested period
        # We need to iterate over sessions or unique days?
        # Late mark is per day (usually on first check-in).
        # We can count distinct days where is_late=1
        
        late_dates = set()
        
        # Scan raw records for is_late=1 in the requested range
        for r in records:
            if r.get('is_late') == 1:
                try:
                    r_ts = r['timestamp']
                    if '.' in r_ts:
                         r_dt = datetime.strptime(r_ts, '%Y-%m-%d %H:%M:%S.%f').date()
                    else:
                         r_dt = datetime.strptime(r_ts, '%Y-%m-%d %H:%M:%S').date()
                    
                    if start_dt_req <= r_dt <= end_dt_req:
                        late_dates.add(r_dt)
                except:
                    pass
        
        late_marks_count = len(late_dates)
        if not late_enabled:
            late_marks_count = 0

        for session in stats.get('sessions', []):
            if session.get('start_ts'):
                try:
                    # Parse ISO format
                    sess_start = datetime.fromisoformat(session['start_ts'])
                    sess_date = sess_start.date()
                    
                    # Filter by requested date range
                    # Logic: Shift belongs to the date it STARTED
                    if start_dt_req <= sess_date <= end_dt_req:
                        # Only sum PAYABLE sessions
                        if session.get('is_payable', False):
                            mins = session.get('duration_mins', 0)
                            total_hours += (mins / 60.0)
                            present_dates.add(sess_date)
                except ValueError:
                    continue

        days_present = len(present_dates)
            
        daily_wage = person_info['daily_wage'] or 0
        
        # Cost Calculation: (Total Hours / Working Hours) * Daily Wage
        hourly_rate = daily_wage / company_working_hours if daily_wage and company_working_hours > 0 else 0
        base_cost = round(total_hours * hourly_rate, 2)
        
        # Late Deduction Logic
        p_allowance = person_info.get('late_allowance_days')
        p_deduction_amt = person_info.get('late_deduction_amount')
        
        # Use Individual if set (not None), else Global
        allowance = p_allowance if p_allowance is not None else global_allowance
        deduction_amt = p_deduction_amt if p_deduction_amt is not None else global_deduction
        
        deductable_lates = max(0, late_marks_count - allowance)
        total_deduction = round(deductable_lates * deduction_amt, 2)
        
        final_payout = round(base_cost - total_deduction, 2)
        
        # Format Total Hours String
        h = int(total_hours)
        m = int(round((total_hours - h) * 60))
        total_hours_str = f"{h}h {m}m"
        
        payroll_data.append({
            "person_id": pid,
            "name": person_info.get('name'),
            "department": person_info['department'],
            "designation": person_info['designation'],
            "face_image": person_info['face_image'],
            "phone": person_info['phone'],
            "late_allowance_days": person_info.get('late_allowance_days'),
            "late_deduction_amount": person_info.get('late_deduction_amount'),
            "daily_wage": daily_wage,
            "total_hours": round(total_hours, 2),
            "total_hours_str": total_hours_str,
            "days_present": days_present,
            "base_cost": base_cost,
            "late_marks_count": late_marks_count,
            "late_deduction": total_deduction,
            "final_payout": final_payout,
            "total_cost": final_payout, # Keep for backward compatibility, but UI should likely show breakdown
            "company_working_hours": company_working_hours
        })
    
    return jsonify({
        "payroll": payroll_data,
        "global_settings": {
            "allowance": global_allowance,
            "deduction": global_deduction
        }
    })


@attendance_bp.route("/reports/payroll/export-daily", methods=["GET"])
def export_payroll_daily():
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date required"}), 400
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        _run(c, "SELECT * FROM attendance WHERE vendor_id = ?", (vendor_id,))
        rows = c.fetchall()
        from collections import defaultdict
        user_records = defaultdict(list)
        for row in rows:
            d = dict(row)
            pid = d.get('person_id')
            if pid:
                user_records[pid].append(d)
        # Fetch person info
        persons = {}
        _run(c, "SELECT id as person_id, name, department, designation, phone, shift, custom_data, daily_wage FROM faces WHERE vendor_id = ?", (vendor_id,))
        for r in c.fetchall():
            persons[r['person_id']] = dict(r)
        # Global/individual late config
        _run(c, "SELECT value FROM system_settings WHERE key='global_late_allowance'")
        gr = c.fetchone()
        global_allowance = int(gr['value']) if gr and gr['value'] else 0
        _run(c, "SELECT value FROM system_settings WHERE key='global_late_deduction'")
        dr = c.fetchone()
        global_deduction = float(dr['value']) if dr and dr['value'] else 0.0
        start_dt_req = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt_req = datetime.strptime(end_date, '%Y-%m-%d').date()
        import csv, io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["person_id","name","date","hours_payable","late_mark","deduction_applied"])
        for pid, records in user_records.items():
            info = persons.get(pid, {})
            timetable = []
            try:
                tjson = info.get('shift') or ""
                if tjson:
                    timetable = json.loads(tjson) if isinstance(tjson, str) else (tjson or [])
            except Exception:
                timetable = []
            stats = calculate_daily_hours(records, timetable, date_str=datetime.now().strftime('%Y-%m-%d'))
            per_day = {}
            for s in stats.get('sessions', []):
                try:
                    sd = datetime.fromisoformat(s['start_ts']).date()
                    if start_dt_req <= sd <= end_dt_req and s.get('is_payable', False):
                        per_day[sd] = per_day.get(sd, 0) + (s.get('duration_mins', 0) or 0)
                except Exception:
                    continue
            # Late dates within range
            late_dates = []
            for r in records:
                if r.get('is_late') == 1:
                    try:
                        r_ts = r['timestamp']
                        if '.' in r_ts:
                            r_dt = datetime.strptime(r_ts, '%Y-%m-%d %H:%M:%S.%f').date()
                        else:
                            r_dt = datetime.strptime(r_ts, '%Y-%m-%d %H:%M:%S').date()
                        if start_dt_req <= r_dt <= end_dt_req:
                            late_dates.append(r_dt)
                    except Exception:
                        pass
            late_dates = sorted(set(late_dates))
            allowance = info.get('late_allowance_days')
            deduction_amt = info.get('late_deduction_amount')
            if allowance is None: allowance = global_allowance
            if deduction_amt is None: deduction_amt = global_deduction
            for d, mins in sorted(per_day.items()):
                lm = 1 if d in late_dates else 0
                idx = late_dates.index(d) + 1 if d in late_dates else 0
                deduct = deduction_amt if (lm == 1 and idx > allowance) else 0.0
                writer.writerow([pid, info.get('name'), d.isoformat(), round(mins/60.0,2), lm, deduct])
        return output.getvalue(), 200, {"Content-Type": "text/csv"}
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@attendance_bp.route("/reports/payroll/import", methods=["POST"])
def import_payroll_adjustments():
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    if 'file' not in request.files:
        return jsonify({"error":"CSV file required"}), 400
    f = request.files['file']
    try:
        content = f.read().decode('utf-8')
        import csv, io
        reader = csv.DictReader(io.StringIO(content))
        conn = get_db_connection()
        c = conn.cursor()
        updated = 0
        for row in reader:
            pid = row.get('person_id')
            allow = row.get('late_allowance_days')
            deduct = row.get('late_deduction_amount')
            if not pid: continue
            vals = {}
            if allow is not None and str(allow).strip() != "":
                try: vals['late_allowance_days'] = int(allow)
                except: pass
            if deduct is not None and str(deduct).strip() != "":
                try: vals['late_deduction_amount'] = float(deduct)
                except: pass
            if vals:
                _run(c, "UPDATE faces SET late_allowance_days = ?, late_deduction_amount = ? WHERE vendor_id = ? AND id = ?", (vals.get('late_allowance_days'), vals.get('late_deduction_amount'), vendor_id, pid))
                updated += 1
        conn.commit()
        conn.close()
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@attendance_bp.route("/public/attendance-by-student", methods=["GET"])
def public_attendance_by_student():
    from utils import get_db_connection
    # socketio, is_testing, ALL_FEATURES - these might need careful handling if from app
    from services.auth_service import extract_token, verify_token
    student_number = request.args.get("student_number", "").strip()
    if not student_number:
        return jsonify({"error": "student_number required"}), 400
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT id, vendor_id, name, custom_data FROM faces WHERE custom_data IS NOT NULL")
        rows = c.fetchall()
        import json
        person_id = None
        vendor_id = None
        for r in rows:
            try:
                cd = json.loads(r['custom_data'])
                sn = str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or '').strip()
                if sn == student_number:
                    person_id = r['id']
                    vendor_id = r['vendor_id']
                    break
            except Exception:
                pass
        if not person_id:
            conn.close()
            return jsonify({"attendance": []})
        limit = int(request.args.get('limit', 50))
        date_filter = request.args.get('date')
        date_from = request.args.get('from')
        date_to = request.args.get('to')
        if date_filter:
            c.execute("""
                SELECT id, name, timestamp, status, activity, is_late, person_id 
                FROM attendance
                WHERE person_id = ? AND date(timestamp) = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (person_id, date_filter, limit))
        elif date_from and date_to:
            c.execute("""
                SELECT id, name, timestamp, status, activity, is_late, person_id 
                FROM attendance
                WHERE person_id = ? AND date(timestamp) BETWEEN ? AND ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (person_id, date_from, date_to, limit))
        else:
            c.execute("""
                SELECT id, name, timestamp, status, activity, is_late, person_id 
                FROM attendance
                WHERE person_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (person_id, limit))
        out_rows = [dict(x) for x in c.fetchall()]
        conn.close()
        return jsonify({"attendance": out_rows, "student_number": student_number})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

@attendance_bp.route("/public/register-token", methods=["POST"])
def public_register_token():
    data = request.json or {}
    student_number = str(data.get("student_number") or "").strip()
    token = str(data.get("token") or "").strip()
    vendor_id = data.get("vendor_id")
    if not student_number or not token:
        return jsonify({"error": "student_number and token required"}), 400
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS parent_tokens
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      vendor_id INTEGER,
                      student_number TEXT,
                      token TEXT UNIQUE,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        if not vendor_id:
            c.execute("SELECT vendor_id, custom_data FROM faces WHERE custom_data IS NOT NULL")
            rows = c.fetchall()
            import json
            for r in rows:
                try:
                    cd = json.loads(r[1])
                    sn = str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or '').strip()
                    if sn == student_number:
                        vendor_id = r[0]
                        break
                except Exception:
                    pass
        if not vendor_id:
            conn.close()
            return jsonify({"error": "vendor not found"}), 404
        c.execute("INSERT OR IGNORE INTO parent_tokens (vendor_id, student_number, token) VALUES (?, ?, ?)", (vendor_id, student_number, token))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@attendance_bp.route("/attendance/summary", methods=["GET"])
def get_attendance_summary():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    # company_id = request.args.get('company_id', 1) # Legacy default

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch Timetable
    timetable = []
    
    if vendor_id:
        c.execute("SELECT live_timetable FROM companies WHERE vendor_id = ?", (vendor_id,))
    else:
        return jsonify({"error": "Vendor context required"}), 400
        
    company_row = c.fetchone()
    
    if company_row and company_row['live_timetable']:
        import json
        try:
            timetable = json.loads(company_row['live_timetable'])
        except:
            pass
            
    # 2. Parse Timetable for the target day
    target_date = datetime.strptime(date_str, '%Y-%m-%d')
    day_name = target_date.strftime('%a') # Mon, Tue...
    
    expected_work_hours = 0
    expected_start = None
    expected_end = None
    
    # Filter activities for this day
    day_activities = [a for a in timetable if day_name in a.get('days', [])]
    # Sort by start time
    day_activities.sort(key=lambda x: x.get('start_time', '00:00'))
    
    if day_activities:
        # Calculate expected hours (Payable activities only)
        expected_work_hours = calculate_expected_hours(day_activities)
        
        expected_start = day_activities[0]['start_time']
        expected_end = day_activities[-1]['end_time']

    # 3. Get all records for the day
    query = "SELECT * FROM attendance WHERE date(timestamp) = ?"
    params = [date_str]
    
    if vendor_id:
        query += " AND vendor_id = ?"
        params.append(vendor_id)
        
    query += " ORDER BY timestamp ASC"
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    # Group by user
    user_records = defaultdict(list)
    for row in rows:
        user_records[row['name']].append(dict(row))

    summary = []
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    for user, records in user_records.items():
        stats = calculate_daily_hours(records, timetable, date_str=date_str)
        
        # 4. Compare with Schedule
        status = "Present"
        if stats['total_hours'] == 0:
            status = "Absent"
        elif expected_work_hours > 0:
            if stats['total_hours'] < (expected_work_hours - 0.5): # 30 min buffer
                status = "Undertime"
            elif stats['total_hours'] > (expected_work_hours + 1):
                status = "Overtime"
            else:
                status = "On Track"
        
        # Check Late Arrival
        arrival_status = calculate_arrival_status(expected_start, stats['sessions'], day_activities)

        summary.append({
            "name": user,
            "date": date_str,
            "schedule": {
                "expected_hours": round(expected_work_hours, 2),
                "expected_start": expected_start,
                "expected_end": expected_end,
            },
            "status": status,
            "arrival_status": arrival_status,
            **stats
        })

    return jsonify({"summary": summary})

# --- SuperAdmin Subscription Management ---



@attendance_bp.route("/person-event", methods=["POST"])
def person_event():
    from app import latest_frames, client_counts, device_status
    data = request.json
    
    # Debug Log
    pass # print(f"Received person-event: detected={data.get('detected')}, recognized={data.get('recognized')}, name={data.get('name')}")

    detected = data.get("detected", False)
    recognized = data.get("recognized", False)
    name = data.get("name")
    person_id = data.get("person_id")
    
    # --- SaaS Subscription Enforcement & Multi-tenancy ---
    # Check if the associated vendor is active/paid AND if person belongs to the kiosk's vendor
    
    kiosk_vendor_id = None
    person_vendor_id = None
    
    # 1. Identify Kiosk Vendor from Auth Token
    auth_header = request.headers.get('Authorization')
    if auth_header:
        try:
            token = auth_header.split(" ")[1]
            user_data = verify_token(token)
            if user_data:
                conn_auth = get_db_connection()
                c_auth = conn_auth.cursor()
                c_auth.execute("SELECT vendor_id FROM system_users WHERE username = ?", (user_data['username'],))
                u_row = c_auth.fetchone()
                conn_auth.close()
                if u_row:
                    kiosk_vendor_id = u_row[0]
        except:
            pass

    # 2. Identify Person Vendor
    if recognized:
         conn_check = get_db_connection()
         c_check = conn_check.cursor()
         f_row = None
         
         if person_id:
             c_check.execute("SELECT vendor_id FROM faces WHERE id = ?", (person_id,))
             f_row = c_check.fetchone()
         
         if not f_row and name and kiosk_vendor_id:
             c_check.execute("SELECT vendor_id FROM faces WHERE name = ? AND vendor_id = ? LIMIT 1", (name, kiosk_vendor_id))
             f_row = c_check.fetchone()

         conn_check.close()
         if f_row:
             person_vendor_id = f_row[0]

    # 3. Cross Check: Prevent Kiosk (Vendor A) from recording Person (Vendor B)
    if kiosk_vendor_id and person_vendor_id:
        if kiosk_vendor_id != person_vendor_id:
             return jsonify({
                "speak": True,
                "text": "Access Denied: Person belongs to another organization."
            })

    # 4. Determine which vendor to check for subscription
    # Prefer Kiosk Vendor, fallback to Person Vendor (for unauth kiosks)
    vendor_id_to_check = kiosk_vendor_id if kiosk_vendor_id else person_vendor_id

    if recognized and not person_id and not vendor_id_to_check and name:
        return jsonify({
            "speak": True,
            "text": "Registration must be vendor-wise. Missing person_id; please re-register from your organization."
        })

    # 5. Enforce Status
    if vendor_id_to_check:
        is_allowed, reason = check_vendor_status(vendor_id_to_check)
        if not is_allowed:
            return jsonify({
                "speak": True,
                "text": f"Service Suspended: {reason}. Attendance not recorded."
            })
    # -------------------------------------

    # person_id extracted earlier
    # ... rest of function ...
    confidence = data.get("confidence", 0)
    captured_image = data.get("image") # Base64 string of the frame
    is_attendance = data.get("is_attendance", True) # Default to True for backward compatibility
    
    # Determine current time from mobile timestamp if available
    timestamp_str = data.get("timestamp")
    current_time_obj = datetime.now()
    
    if timestamp_str:
        try:
            # Parse ISO 8601 string (e.g. 2023-10-27T10:00:00.123)
            current_time_obj = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.%f")
        except ValueError:
            try:
                # Fallback for format without milliseconds
                current_time_obj = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass # print(f"Invalid timestamp format: {timestamp_str}. Using server time.")
                current_time_obj = datetime.now()
    else:
        # User requested no assumptions about Timezone.
        # We use strict Server Time (which is UTC on Render).
        # If user wants local time, they MUST send timestamp from client or configure server TZ.
        current_time_obj = datetime.now()
        
        # NOTE: Previous versions applied a hardcoded or configured offset here.
        # Per user request: "why to give any value when the time itself is coming from the mobile phone?"
        # We now rely STRICTLY on the mobile timestamp.
        # If timestamp_str is missing, we use Server Time (UTC) as a raw fallback.
        # If this causes negative durations, the root cause is the Client not sending the timestamp.
        pass # print(f"WARNING: No timestamp received from client. Falling back to Server Time (UTC): {current_time_obj}")

    pass # print(f"DEBUG TIME: Server saw {current_time_obj} (Original TS: {timestamp_str})")

    # Case 1: No person detected
    if not detected:
        return jsonify({"speak": False})

    # Case 2: Person detected but NOT recognized
    if detected and not recognized:
        message = "Hello! You are not recognized. Please register with the admin first."
        return jsonify({
            "speak": True,
            "text": message
        })

    # Case 3: Person detected and recognized
    try:
        if person_id:
            conn_name = get_db_connection()
            c_name = conn_name.cursor()
            c_name.execute("SELECT name FROM faces WHERE id = ? LIMIT 1", (person_id,))
            r_name = c_name.fetchone()
            conn_name.close()
            if r_name and r_name[0]:
                name = r_name[0]
    except Exception:
        pass
    name = name or ""
    
    # If this is just an identification check (e.g. from Admin panel), do not record attendance
    if not is_attendance:
        pass # print(f"Admin Identification Check: {name}")
        return jsonify({
            "speak": True,
            "text": f"Identified: {name} (Admin Mode)"
        })
    # Enforce: person_id required for recognized attendance
    if recognized and not person_id:
        return jsonify({
            "error": "person_id required for attendance. Re-register or sync device.",
            "speak": True,
            "text": "Please re-register vendor-wise. Missing person_id."
        }), 400

    # --- Check-in / Check-out Logic ---
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Ensure attendance has device_id column (SQLite safe migration)
    try:
        c.execute("PRAGMA table_info(attendance)")
        cols = [row[1] if isinstance(row, (list, tuple)) else row['name'] for row in c.fetchall() or []]
        if 'device_id' not in cols:
            try:
                c.execute("ALTER TABLE attendance ADD COLUMN device_id TEXT")
                conn.commit()
            except Exception:
                pass
    except Exception:
        pass

    # Resolve current device_id from session token (preferred) or payload fallback
    current_device_id = None
    try:
        auth_header2 = request.headers.get('Authorization')
        token2 = extract_token(auth_header2)
        if token2:
            try:
                c.execute("SELECT device_id FROM active_sessions WHERE token = ? LIMIT 1", (token2,))
                row_d = c.fetchone()
                if row_d:
                    # RealDictCursor or sqlite row
                    try:
                        current_device_id = row_d['device_id']
                    except Exception:
                        current_device_id = row_d[0]
            except Exception:
                current_device_id = None
    except Exception:
        current_device_id = None
    # Fallback to body field if provided by client (future-proof)
    if not current_device_id:
        try:
            current_device_id = str(data.get('device_id') or '').strip() or None
        except Exception:
            current_device_id = None

    # Determine Expected Status EARLY (for better activity matching)
    if person_id:
        if vendor_id_to_check:
            if current_device_id:
                c.execute("SELECT * FROM attendance WHERE person_id = ? AND vendor_id = ? AND device_id = ? ORDER BY timestamp DESC LIMIT 1", (person_id, vendor_id_to_check, current_device_id))
            else:
                c.execute("SELECT * FROM attendance WHERE person_id = ? AND vendor_id = ? ORDER BY timestamp DESC LIMIT 1", (person_id, vendor_id_to_check))
        else:
            if current_device_id:
                c.execute("SELECT * FROM attendance WHERE person_id = ? AND device_id = ? ORDER BY timestamp DESC LIMIT 1", (person_id, current_device_id))
            else:
                c.execute("SELECT * FROM attendance WHERE person_id = ? ORDER BY timestamp DESC LIMIT 1", (person_id,))
    else:
        if vendor_id_to_check:
            if current_device_id:
                c.execute("SELECT * FROM attendance WHERE name = ? AND vendor_id = ? AND device_id = ? ORDER BY timestamp DESC LIMIT 1", (name, vendor_id_to_check, current_device_id))
            else:
                c.execute("SELECT * FROM attendance WHERE name = ? AND vendor_id = ? ORDER BY timestamp DESC LIMIT 1", (name, vendor_id_to_check))
        else:
            if current_device_id:
                c.execute("SELECT * FROM attendance WHERE name = ? AND device_id = ? ORDER BY timestamp DESC LIMIT 1", (name, current_device_id))
            else:
                c.execute("SELECT * FROM attendance WHERE name = ? ORDER BY timestamp DESC LIMIT 1", (name,))
    last_record = c.fetchone()
    
    expected_status = 'CHECK_IN'
    if last_record and last_record['status'] == 'CHECK_IN':
        expected_status = 'CHECK_OUT'
        
        # Check for Stale Check-In (e.g. forgot to check out yesterday)
        try:
            ts_str = last_record['timestamp']
            last_ts = None
            if '.' in ts_str:
                last_ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f')
            else:
                last_ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                
            # Calculate duration since last check-in
            # If > 16 hours, assume stale and reset to CHECK_IN
            duration_hours = (current_time_obj - last_ts).total_seconds() / 3600
            
            if duration_hours > 16:
                pass # print(f"Stale Check-In detected for {name} ({duration_hours:.1f}h ago). Resetting to CHECK_IN.")
                expected_status = 'CHECK_IN'
        except Exception as e:
            pass # print(f"Error checking stale status: {e}")

    # Helper function for time conversion
    # Define to_mins ONLY ONCE if not already in scope, but here it is local.
    def to_mins(hm):
        try:
            hm_str = str(hm).strip().lower()
            # Robust AM/PM handling
            is_pm = 'pm' in hm_str or 'p.m.' in hm_str
            is_am = 'am' in hm_str or 'a.m.' in hm_str
            
            # Remove am/pm for parsing
            clean_str = hm_str.replace(' am', '').replace(' pm', '').replace('am', '').replace('pm', '')
            clean_str = clean_str.replace(' a.m.', '').replace(' p.m.', '').replace('a.m.', '').replace('p.m.', '').strip()
            
            if ':' in clean_str:
                parts = clean_str.split(':')
            elif '.' in clean_str:
                parts = clean_str.split('.')
            else:
                # Handle plain integer hours
                if clean_str.isdigit():
                    return int(clean_str) * 60
                return 0
            
            h = int(parts[0])
            m = int(parts[1])
            
            # 12-hour to 24-hour conversion
            if is_pm and h != 12:
                h += 12
            elif is_am and h == 12:
                h = 0
                
            return h * 60 + m
        except:
            return 0

    # Identify Activity Context FIRST to determine duplication rules
    activity_name = "Work" # Default
    activity_type = "Work"
    best_match = None
    has_timetable_entries = False
    
    try:
        # Fetch Timetable and Shifts
        if vendor_id_to_check:
            c.execute("SELECT live_timetable, shifts FROM companies WHERE vendor_id = ?", (vendor_id_to_check,))
            company_row = c.fetchone()
        else:
            # No vendor context identified (Legacy data issue or Unrecognized Person + Unauth Kiosk)
            # Cannot determine timetable. Proceed with defaults.
            company_row = None
        
        # Fetch User Shift
        if person_id:
            c.execute("SELECT shift FROM faces WHERE id = ?", (person_id,))
        else:
            if vendor_id_to_check:
                c.execute("SELECT shift FROM faces WHERE name = ? AND vendor_id = ? LIMIT 1", (name, vendor_id_to_check))
            else:
                c.execute("SELECT shift FROM faces WHERE name = ? LIMIT 1", (name,))
        face_row = c.fetchone()
        user_shift_name = face_row['shift'] if face_row and 'shift' in face_row.keys() else None

        # Initialize shifts_data and user_shift_id
        shifts_data = []
        user_shift_id = None
        
        if company_row:
             shifts_data = json.loads(company_row['shifts']) if company_row['shifts'] else []
             # Resolve User Shift ID
             if user_shift_name:
                pass # print(f"User Shift Name: {user_shift_name}")
                for s in shifts_data:
                    # Loose matching for robustness (case-insensitive, trim)
                    if s.get('name', '').strip().lower() == user_shift_name.strip().lower():
                        user_shift_id = s.get('id')
                        pass # print(f"Resolved User Shift ID: {user_shift_id}")
                        break
        
        # --- STRICT SHIFT FILTERING (User Request) ---
        # If the user has an assigned shift, we MUST filter the timetable to ONLY include:
        # 1. Activities explicitly assigned to this shift (shift_id match)
        # 2. Global activities (shift_id is None/Empty) - BUT only if they don't conflict with specific ones.
        
        filtered_timetable = []
        if company_row and company_row['live_timetable']:
            full_timetable = json.loads(company_row['live_timetable'])
            try:
                has_timetable_entries = isinstance(full_timetable, list) and len(full_timetable) > 0
            except Exception:
                has_timetable_entries = False
            
            if user_shift_id:
                # 1. Collect Specific Matches
                specific_acts = [a for a in full_timetable if str(a.get('shift_id', '')) == str(user_shift_id)]
                
                # 2. Collect Global Matches (No shift_id)
                # But be careful: If we have a specific "Work" activity, ignore global "Work".
                global_acts = [a for a in full_timetable if not a.get('shift_id')]
                
                # Filter Globals: Exclude if a specific activity of same type exists?
                # Actually, simpler rule: If user has a shift, ONLY trust that shift's structure.
                # But "Lunch" might be global.
                # Strategy: Add all specific acts. Add global acts ONLY if their 'type' is NOT in specific acts?
                # No, that's risky.
                # Better Strategy: Just add both, but when selecting "Work", specific overrides global.
                # Actually, if I am assigned "Night Shift", I should NOT match "Day Shift" (Global 9-5).
                # So if I have a specific "Work", I should definitely ignore global "Work".
                
                specific_types = {a.get('type', 'Work').lower() for a in specific_acts}
                
                filtered_timetable.extend(specific_acts)
                
                for ga in global_acts:
                    # If we already have a specific activity of this type (e.g. Work), skip the global one.
                    # This prevents "Global 9-5" from polluting "Night Shift 21-05".
                    if ga.get('type', 'Work').lower() in specific_types:
                        continue
                    filtered_timetable.append(ga)
                    
                pass # print(f"Shift Filter Applied: {len(full_timetable)} -> {len(filtered_timetable)} activities.")
            else:
                # No shift assigned to user? Use everything (Open Mode)
                filtered_timetable = full_timetable

            timetable = filtered_timetable
            
            now = current_time_obj
            current_hm = now.strftime('%H:%M')
            day_name = now.strftime('%a')
            
            curr_mins = to_mins(current_hm)
            today_acts = [a for a in timetable if day_name in a.get('days', [])]
            
            matching_acts = []
            
            # Fetch Settings (support vendor overrides)
            base_keys = ['activity_tolerance', 'late_grace_period']
            keys = list(base_keys)
            if vendor_id_to_check:
                keys.extend([f"{k}_vendor_{vendor_id_to_check}" for k in base_keys])
            placeholders = ",".join(["?"] * len(keys))
            c.execute(f"SELECT key, value FROM system_settings WHERE key IN ({placeholders})", keys)
            settings = {row['key']: row['value'] for row in c.fetchall()}
            vendor_suffix = f"_vendor_{vendor_id_to_check}" if vendor_id_to_check else ""
            tolerance = int(settings.get(f"activity_tolerance{vendor_suffix}", settings.get('activity_tolerance', 30)))
            grace_period = int(settings.get(f"late_grace_period{vendor_suffix}", settings.get('late_grace_period', 15)))

            # --- Check Yesterday's Night Shifts (Spillover) ---
            # If current time is early morning, it might belong to a shift that started yesterday
            yesterday_obj = now - timedelta(days=1)
            yesterday_name = yesterday_obj.strftime('%a')
            yesterday_acts = [a for a in timetable if yesterday_name in a.get('days', [])]

            for act in yesterday_acts:
                s = to_mins(act.get('start_time', '00:00'))
                e = to_mins(act.get('end_time', '00:00'))
                
                act_rules = act.get('rules', {})
                act_grace = int(act_rules.get('grace_period', tolerance))
                
                is_yesterday_match = False
                
                if s > e: # Night Shift from Yesterday (e.g. 9 PM - 2 AM)
                    # Check if current time is within the end window (morning of today)
                    # e.g. End 01:00. Curr 00:15. Matches.
                    if curr_mins <= (e + act_grace):
                        is_yesterday_match = True
                else:
                    # Standard Shift from Yesterday (e.g. 4 PM - 11 PM)
                    # Check if current time (Today) is within the grace period of yesterday's end.
                    # Logic: (Current Time + 24h) <= (End Time + Grace)
                    if (curr_mins + 1440) <= (e + act_grace): 
                        is_yesterday_match = True
                        pass # print(f"Matched Yesterday's Standard Shift: {act.get('name')} (Grace Period)")

                if is_yesterday_match:
                    # Verify Shift ID Match
                    act_shift_id = act.get('shift_id')
                    is_match = False
                    if act_shift_id:
                        if user_shift_id and int(act_shift_id) == int(user_shift_id):
                            is_match = True
                    else:
                        is_match = True
                        
                    if is_match:
                        # CRITICAL FIX: Tag this activity as belonging to YESTERDAY.
                        # This allows downstream logic to know we need to apply overnight calculations.
                        act['_is_yesterday'] = True
                        matching_acts.append(act)
                        pass # print(f"Matched Yesterday's Shift: {act.get('name')}")
            
            for act in today_acts:
                start_mins = to_mins(act.get('start_time', '00:00'))
                end_mins = to_mins(act.get('end_time', '00:00'))
                
                # Check if current time is within this activity (with buffer)
                # Use activity-specific grace_period (from rules) if available, else global tolerance
                # User requested to use grace_period from rules for this logic
                act_rules = act.get('rules', {})
                act_grace = int(act_rules.get('grace_period', tolerance))
                
                is_match = False
                start_window = start_mins - act_grace
                end_window = end_mins + act_grace
                
                if start_mins > end_mins:
                    # Night shift (spans midnight)
                    # For TODAY'S night shift, we only match the START (evening) part.
                    # The END (morning) part belongs to TOMORROW (which will be caught by 'Yesterday Check' tomorrow).
                    # If we match 'end_window' here, we incorrectly match Day X's 00:15 to Day X's 5pm shift (instead of Day X-1's).
                    if curr_mins >= start_window:
                        is_match = True
                else:
                    # Standard shift
                    if start_window <= curr_mins <= end_window:
                        is_match = True
                        
                if is_match:
                    # Filter by Shift ID if activity has one
                    act_shift_id = act.get('shift_id')
                    is_shift_match = False
                    
                    if not act_shift_id:
                        is_shift_match = True
                    else:
                        if not user_shift_id:
                             is_shift_match = True
                        else:
                             try:
                                 if int(act_shift_id) == int(user_shift_id):
                                     is_shift_match = True
                             except:
                                 pass
                             
                             if not is_shift_match and 'shifts_data' in locals() and shifts_data:
                                 for s in shifts_data:
                                     if str(s.get('id')) == str(act_shift_id):
                                         if s.get('name') == user_shift_id:
                                             is_shift_match = True
                                         break
                    
                    if is_shift_match:
                        matching_acts.append(act)
            
            # --- Fallback Logic for Very Late/Early Arrivals ---
            # If no activity matches the strict time window (e.g. user arrives at 6pm for a 9-5 shift),
            # matching_acts will be empty. We should try to find the intended "Work" activity 
            # so we can correctly mark them as Late (instead of "On Time" for generic Work).
            if not matching_acts:
                 # Find potential Work activities for this user (Shift-specific or Global)
                 potential_acts = []
                 for act in today_acts:
                     # Only consider WORK activities
                     if act.get('type', 'Work') != 'Work':
                         continue

                     # Check Shift Match
                     act_shift_id = act.get('shift_id')
                     is_shift_match = False
                     
                     if not act_shift_id:
                         is_shift_match = True # Global activity
                     else:
                         # Activity has shift
                         if not user_shift_id:
                              # User has NO shift -> Allow match (Open Shift mode) to ensure detection
                              is_shift_match = True
                         else:
                              # Try to match IDs or Names
                              try:
                                  if int(act_shift_id) == int(user_shift_id):
                                      is_shift_match = True
                              except:
                                  pass
                              
                              # If ID match failed (or error), try Name match
                              if not is_shift_match and 'shifts_data' in locals() and shifts_data:
                                  for s in shifts_data:
                                      if str(s.get('id')) == str(act_shift_id):
                                          if s.get('name') == user_shift_id:
                                              is_shift_match = True
                                          break
                     
                     if is_shift_match:
                         potential_acts.append(act)
                 
                 if potential_acts:
                     # If multiple work activities, which one to pick?
                     # 1. Sort by PROXIMITY to current time (Loophole Fix for Multi-Shift / Late Night)
                     # If curr_mins is 22:00 (1320), we prefer Shift B (22:00) over Shift A (09:00).
                     # Calculate circular distance (24h clock) to handle midnight wrapping.
                     def circular_dist(act_start, now_mins):
                         diff = abs(act_start - now_mins)
                         return min(diff, 1440 - diff)
                         
                     potential_acts.sort(key=lambda x: circular_dist(to_mins(x.get('start_time', '00:00')), curr_mins))
                     
                     best_fallback = potential_acts[0]
                     
                     pass # print(f"Fallback Activity Match: {best_fallback.get('name')} (Strict window missed)")
                     matching_acts.append(best_fallback)

            # Prioritize:
            # New Logic (User Request):
            # If CHECK_IN (Starting something): Prioritize Longest Duration Activity (Work) over sub-activities (Break)
            # If CHECK_OUT (Ending something): Prioritize Breaks (Lunch) over Work? Or maybe consistent?
            # User specifically said: "he will be marked for the first activity which is work... all activies marked missed except longest"
            
            best_match = None
            
            if matching_acts:
                # Helper to calculate duration
                def get_duration(act):
                    s = to_mins(act.get('start_time', '00:00'))
                    e = to_mins(act.get('end_time', '00:00'))
                    d = e - s
                    if d < 0: d += 24*60 # Handle overnight
                    return d
                
                # Sort Priority:
                # 1. Matches from Yesterday (Continuing Shift) - HIGHEST PRIORITY
                # 2. Longest Duration (Work)
                # 3. Others
                
                matching_acts.sort(key=lambda x: (
                    1 if x.get('_is_yesterday') else 0, # Priority 1: Yesterday's Shift
                    get_duration(x) # Priority 2: Duration
                ), reverse=True)

                if expected_status == 'CHECK_IN':
                    # Prioritize Longest Duration (Work) but respect Yesterday First
                    best_match = matching_acts[0]
                    pass # print(f"Check-In Priority: Picked {best_match.get('name')} (Yesterday={best_match.get('_is_yesterday', False)})")
                else:
                    # Check-Out Logic: Prioritize Breaks?
                    # Original logic prioritized Breaks over Work. Let's keep that for Check-Out to allow "Going to Lunch"
                    breaks = [a for a in matching_acts if a.get('type', '').lower() != 'work']
                    if breaks:
                        best_match = breaks[0]
                    else:
                        best_match = matching_acts[0]

            if best_match:
                activity_name = best_match.get('name', 'Work')
                activity_type = best_match.get('type', 'Work')
                # Update grace_period from activity rules for Late calculation
                act_rules = best_match.get('rules', {})
                if 'grace_period' in act_rules:
                    grace_period = int(act_rules['grace_period'])

    except Exception as e:
        pass # print(f"Activity Detection Error: {e}")

    # --- Duplication Check ---
    # User Requirement: "if the employee has completed the activity... it should not duplicate again"
    # Logic: For non-Work activities (Breaks), if we have a complete pair (OUT and IN), block further scans.
    
    if activity_type.lower() != 'work':
        today_str = current_time_obj.strftime('%Y-%m-%d')
        c.execute("""
            SELECT count(*) as count 
            FROM attendance 
            WHERE name = ? 
            AND date(timestamp) = ? 
            AND activity = ?
        """, (name, today_str, activity_name))
        count = c.fetchone()['count']
        
        # Assuming a complete activity cycle is 2 records (OUT for Lunch, IN from Lunch)
        # Or maybe just check if they are already "IN" from Lunch?
        # If count >= 2, it implies they left and came back.
        if count >= 2:
            pass # print(f"Activity {activity_name} already completed for {name}. Skipping.")
            conn.close()
            return jsonify({
                "speak": True,
                "text": f"You have already completed {activity_name}."
            })

    # Get last status and timestamp (Already fetched above as last_record)
    # c.execute("SELECT * FROM attendance WHERE name = ? ORDER BY timestamp DESC LIMIT 1", (name,))
    # last_record = c.fetchone()
    
    
    # --- Cooldown Check ---
    try:
        if last_record:
            last_ts_str = last_record['timestamp']
            # Parse timestamp (handle both with and without microseconds)
            if '.' in last_ts_str:
                last_ts = datetime.strptime(last_ts_str, '%Y-%m-%d %H:%M:%S.%f')
            else:
                last_ts = datetime.strptime(last_ts_str, '%Y-%m-%d %H:%M:%S')
            
            # Get cooldown setting
            c.execute("SELECT value FROM system_settings WHERE key='cooldown'")
            row = c.fetchone()
            cooldown_seconds = int(row['value']) if row else 30
            
            # Calculate time difference
            # Use abs() to handle cases where DB has "future" timestamps due to timezone mixups
            # (e.g. if DB has IST but server checks against UTC)
            delta_seconds = (datetime.now() - last_ts).total_seconds()
            pass # print(f"Cooldown Check: Name={name}, Last={last_ts}, Now={datetime.now()}, Delta={delta_seconds}s, Limit={cooldown_seconds}s")
            
            if 0 <= delta_seconds < cooldown_seconds:
                pass # print(f"Cooldown active for {name}. Skipping.")
                conn.close()
                return jsonify({"speak": False})
            elif delta_seconds < 0:
                 # Last record is in the future.
                 # If it's just a few seconds (clock skew), treat as cooldown.
                 # If it's large (timezone mismatch), we should probably allow it to correct the drift, 
                 # OR block it if we want to enforce strictness. 
                 # Given the issues, let's allow it if it's > 60 seconds in future (assume data error/timezone),
                 # but block if it's within 0 to -60 seconds (likely just double scan with clock skew).
                 if abs(delta_seconds) < 60:
                     pass # print(f"Cooldown active (future skew) for {name}. Skipping.")
                     conn.close()
                     return jsonify({"speak": False})
                 else:
                     pass # print(f"Ignoring future timestamp (timezone mismatch?) for {name}. Allowing entry.")

    except Exception as e:
        pass # print(f"Cooldown Error: {e}" )

    new_status = expected_status
    # if last_record and last_record['status'] == 'CHECK_IN':
    #     new_status = 'CHECK_OUT'
    
    # Calculate Late Status
    is_late = 0
    if new_status == 'CHECK_IN':
        if best_match:
            try:
                # Ensure grace_period is available
                if 'grace_period' not in locals():
                    grace_period = 15

                # Recalculate curr_mins if needed
                if 'curr_mins' not in locals():
                    now_check = current_time_obj
                    curr_mins = now_check.hour * 60 + now_check.minute

                start_hm = best_match.get('start_time', '09:00')
                start_mins = to_mins(start_hm)

                # Use activity-specific grace period
                act_rules = best_match.get('rules', {})
                try:
                    # Robust parsing for grace period (handle "15 min", "15", etc.)
                    raw_grace = act_rules.get('grace_period', grace_period)
                    if isinstance(raw_grace, str):
                        # Extract digits
                        import re
                        digits = re.findall(r'\d+', raw_grace)
                        if digits:
                            act_grace = int(digits[0])
                        else:
                            act_grace = 15
                    else:
                        act_grace = int(raw_grace)
                except Exception:
                    act_grace = 15

                # --- STRICT LATE CHECK ---
                # User requirement: If check-in is not in [start, start + grace], mark as Late.
                # Even if it is within the activity duration.

                # Handle Overnight Shifts for comparison
                # If start > end, and we are in the "next day" part (early morning), we add 1440 to check_mins
                # But we must compare against start_mins (which is previous day).
                # So if check_mins is early morning (e.g. 01:00 = 60), and start is 22:00 (1320),
                # check_mins becomes 1500. 1500 > 1320 + grace.

                check_mins = curr_mins
                effective_start_mins = start_mins

                # Detect if we are in the "next day" part of an overnight shift
                end_hm = best_match.get('end_time', '17:00')
                end_mins = to_mins(end_hm)

                # STRICT LOGIC: If matched activity is from Yesterday, we MUST treat current time as Next Day (+1440)
                if best_match.get('_is_yesterday'):
                    pass # print("Strict Logic: Activity is from Yesterday. Adding 1440 to check_mins.")
                    check_mins += 1440
                elif start_mins > end_mins:
                    # Night shift (Today)
                    # If current time is early morning (less than end time + buffer), assume next day
                    if curr_mins <= (end_mins + 360) and start_mins > 360:
                        check_mins += 1440

                # --- Smart Rollover Safety Net ---
                # REMOVED: User requested no assumptions.
                # We strictly rely on Shift Matching to pick the correct shift (Yesterday vs Today).

                # Debug Log
                pass # print(f"LATE CHECK: Act={activity_name}, Start={effective_start_mins}, Check={check_mins}, Grace={act_grace}")

                # Calculate Threshold
                late_threshold = effective_start_mins + act_grace

                if check_mins > late_threshold:
                    is_late = 1
                    pass # print(f"Late Detected (Strict): {name} [ID={person_id}] (Time: {check_mins}, Start: {effective_start_mins}, Grace: {act_grace}, Diff: {check_mins - effective_start_mins})")
                else:
                    # Debugging info
                    pass # print(f"On Time Detected: {name} [ID={person_id}] (Time: {check_mins}, Start: {effective_start_mins}, Grace: {act_grace}, Threshold: {late_threshold})")

                    # Also check if check_mins is BEFORE start_mins (Early Arrival is On Time)
                    if check_mins < effective_start_mins:
                        pass # print(f"Early Arrival: {effective_start_mins - check_mins} mins early.")

            except Exception as e:
                pass # print(f"Late Calculation Error: {e}")
        else:
            try:
                if 'curr_mins' not in locals():
                    now_check = current_time_obj
                    curr_mins = now_check.hour * 60 + now_check.minute
                # If there is no timetable configured at all (no shifts/activities),
                # do NOT apply generic fallback thresholds. Treat as On Time.
                if has_timetable_entries:
                    base_keys = ['work_start_time', 'late_threshold', 'late_grace_period']
                    keys = list(base_keys)
                    if vendor_id_to_check:
                        keys.extend([f"{k}_vendor_{vendor_id_to_check}" for k in base_keys])
                    placeholders = ",".join(["?"] * len(keys))
                    c.execute(f"SELECT key, value FROM system_settings WHERE key IN ({placeholders})", keys)
                    settings_rows = c.fetchall() or []
                    settings_map = {r['key']: r['value'] for r in settings_rows}
                    vendor_suffix = f"_vendor_{vendor_id_to_check}" if vendor_id_to_check else ""

                    raw_late_threshold = (settings_map.get(f"late_threshold{vendor_suffix}") or settings_map.get('late_threshold') or '').strip()
                    raw_work_start = (settings_map.get(f"work_start_time{vendor_suffix}") or settings_map.get('work_start_time') or '').strip()
                    raw_grace = (settings_map.get(f"late_grace_period{vendor_suffix}") or settings_map.get('late_grace_period') or '').strip()

                    grace_mins = 15
                    try:
                        grace_mins = int(raw_grace) if raw_grace != "" else 15
                    except Exception:
                        grace_mins = 15

                    threshold_mins = 0
                    if raw_late_threshold:
                        threshold_mins = to_mins(raw_late_threshold)
                    if threshold_mins <= 0 and raw_work_start:
                        threshold_mins = to_mins(raw_work_start) + grace_mins
                    if threshold_mins <= 0:
                        threshold_mins = to_mins('09:00') + grace_mins

                    if curr_mins > threshold_mins:
                        is_late = 1
                        pass # print(f"Late Detected (Fallback): {name} [ID={person_id}] (Time: {curr_mins}, Threshold: {threshold_mins}, Grace: {grace_mins})")
                else:
                    # No timetable/activities configured: never mark late by fallback.
                    is_late = 0
            except Exception as e:
                pass # print(f"Late Fallback Error: {e}")

    if vendor_id_to_check and not vendor_has_feature(vendor_id_to_check, "late_mark"):
        try:
            if is_testing():
                pass
            else:
                is_late = 0
        except Exception:
            is_late = 0

    # Insert new record with image
    # Use UTC for storage to ensure consistency
    current_time_utc = datetime.now()
    # But for now, since we use naive datetimes everywhere, let's stick to naive local server time
    # to avoid breaking existing logic that expects naive objects.
    # Ideally, we should migrate to UTC everywhere.
    # Given the user's issue "past attendance", let's make sure we return ISO 8601 strings in API.
    
    current_time = current_time_obj
    try:
        # Insert with device_id if column exists, else fallback
        try:
            if current_device_id is not None:
                c.execute("INSERT INTO attendance (name, timestamp, status, captured_image, activity, is_late, vendor_id, person_id, device_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                          (name, current_time, new_status, captured_image, activity_name, is_late, vendor_id_to_check, person_id, current_device_id))
            else:
                c.execute("INSERT INTO attendance (name, timestamp, status, captured_image, activity, is_late, vendor_id, person_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                          (name, current_time, new_status, captured_image, activity_name, is_late, vendor_id_to_check, person_id))
        except Exception:
            # Fallback if device_id column not present
            c.execute("INSERT INTO attendance (name, timestamp, status, captured_image, activity, is_late, vendor_id, person_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                      (name, current_time, new_status, captured_image, activity_name, is_late, vendor_id_to_check, person_id))
        conn.commit()
        pass # print(f"Attendance Recorded: {name} - {new_status} ({activity_name}) Late={is_late} at {current_time}")
        try:
            ev = {
                "name": name,
                "timestamp": current_time.strftime('%Y-%m-%d %H:%M:%S'),
                "status": new_status,
                "is_late": is_late,
                "activity": activity_name,
                "vendor_id": vendor_id_to_check,
                "device_id": current_device_id
            }
            try:
                if vendor_id_to_check and current_device_id:
                    c.execute("SELECT device_name FROM vendor_devices WHERE vendor_id = ? AND device_id = ? LIMIT 1", (vendor_id_to_check, current_device_id))
                    rdn = c.fetchone()
                    if rdn:
                        try:
                            ev["device_name"] = rdn['device_name']
                        except Exception:
                            ev["device_name"] = rdn[0]
            except Exception:
                pass
            if vendor_id_to_check and socketio:
                socketio.emit('attendance_updated', ev, room=f"vendor_{vendor_id_to_check}")
                pid_lookup = person_id
                if not pid_lookup and name:
                    try:
                        c.execute("SELECT id FROM faces WHERE name = ? AND vendor_id = ? LIMIT 1", (name, vendor_id_to_check))
                        r = c.fetchone()
                        pid_lookup = r[0] if r else None
                    except Exception:
                        pid_lookup = None
                if pid_lookup:
                    c.execute("SELECT parent_id FROM student_parents WHERE vendor_id = ? AND person_id = ?", (vendor_id_to_check, pid_lookup))
                    parent_rows = c.fetchall()
                    for pr in parent_rows or []:
                        try:
                            if socketio:
                                socketio.emit('parent_attendance', ev, room=f"parent_{pr[0]}")
                        except Exception:
                            pass
                    try:
                        c.execute("SELECT custom_data FROM faces WHERE id = ?", (pid_lookup,))
                        row_cd = c.fetchone()
                        if row_cd and row_cd[0]:
                            cd = json.loads(row_cd[0])
                            sn = str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or '').strip()
                            if sn and socketio:
                                socketio.emit('student_attendance', ev, room=f"student_{sn}")
                            try:
                                conn2 = get_db_connection()
                                c2 = conn2.cursor()
                                c2.execute("SELECT token FROM parent_tokens WHERE student_number = ? AND vendor_id = ?", (sn, vendor_id_to_check))
                                token_rows = c2.fetchall()
                                conn2.close()
                                if token_rows:
                                    tokens = [t[0] for t in token_rows]
                                    try:
                                        from celery_app import celery
                                        if celery:
                                            from tasks import send_alert_task
                                            send_alert_task.delay(tokens, ev)
                                        else:
                                            import requests, os, json
                                            server_key = os.getenv("FCM_SERVER_KEY", "")
                                            if server_key:
                                                payload = {
                                                    "registration_ids": tokens,
                                                    "notification": {
                                                        "title": f"{ev.get('name', '')} {ev.get('status', '')}",
                                                        "body": f"{ev.get('timestamp', '')} {ev.get('activity', '')}"
                                                    },
                                                    "data": ev
                                                }
                                                headers = {"Content-Type": "application/json", "Authorization": "key=" + server_key}
                                                requests.post("https://fcm.googleapis.com/fcm/send", headers=headers, data=json.dumps(payload), timeout=5)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception as _e:
            pass
        try:
            conn.close()
        except Exception:
            pass
        msg = f"{name}: {new_status.replace('_', ' ').title()}"
        if is_late == 1 and new_status == 'CHECK_IN':
            msg = f"{name}: Late"
        return jsonify({
            "speak": True,
            "text": msg,
            "status": new_status,
            "is_late": is_late,
            "activity": activity_name,
            "person_id": person_id
        })
    except Exception as e:
        pass # print(f"Attendance insert error: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"speak": False}), 500



@attendance_bp.route("/attendance", methods=["GET"], endpoint="attendance_list_route")
@track_metrics("attendance_list")
@rate_limit(limit=300, window=60)
def get_attendance():
    from app import latest_frames, client_counts, device_status
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Filters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    department = request.args.get('department')
    designation = request.args.get('designation')
    shift = request.args.get('shift')
    phone = request.args.get('phone')
    name = request.args.get('name')
    person_id = request.args.get('person_id')
    status = request.args.get('status')
    device_id_filter = request.args.get('device_id')
    device_name_filter = request.args.get('device_name')

    query = """
        SELECT a.*, 
               f.department, f.designation, f.shift, f.phone, f.custom_data AS face_custom_data,
               a.device_id AS device_id,
               vd.device_name AS device_name
        FROM attendance a
        JOIN faces f 
             ON (a.person_id IS NOT NULL AND a.person_id = f.id) 
             OR (a.person_id IS NULL AND a.name = f.name AND f.vendor_id = a.vendor_id)
        LEFT JOIN vendor_devices vd
             ON vd.vendor_id = a.vendor_id AND vd.device_id = a.device_id
        WHERE 1=1
    """
    params = []

    if vendor_id:
        query += " AND a.vendor_id = ?"
        params.append(vendor_id)

    if start_date:
        query += " AND date(a.timestamp) >= ?"
        params.append(start_date)
    
    if end_date:
        query += " AND date(a.timestamp) <= ?"
        params.append(end_date)

    if department:
        query += " AND f.department = ?"
        params.append(department)

    if designation:
        query += " AND f.designation = ?"
        params.append(designation)

    if shift:
        query += " AND f.shift = ?"
        params.append(shift)

    if phone:
        query += " AND f.phone = ?"
        params.append(phone)

    if name:
        query += " AND a.name LIKE ?"
        params.append(f"%{name}%")

    if person_id:
        try:
            pid = int(person_id)
            query += " AND a.person_id = ?"
            params.append(pid)
        except Exception:
            return jsonify({"error": "Invalid person_id"}), 400

    # Device filters
    if device_id_filter and str(device_id_filter).strip() != "":
        query += " AND a.device_id = ?"
        params.append(str(device_id_filter).strip())
    if device_name_filter and str(device_name_filter).strip() != "":
        query += " AND COALESCE(vd.device_name, '') = ?"
        params.append(str(device_name_filter).strip())

    if status and status != "All Statuses":
        # Map UI status to DB status if needed, or just use DB status
        # The UI sends 'On Time', 'Late', 'Absent' which are derived statuses, 
        # but the DB stores 'CHECK_IN', 'CHECK_OUT'. 
        # Filtering by 'Late' or 'On Time' is complex in SQL without pre-calculation.
        # For now, let's support basic CHECK_IN/CHECK_OUT if passed, 
        # or if the user meant the derived status, we might need to filter in Python 
        # or do complex SQL. 
        # Given the "filters like report page" request, simpler is better.
        # Let's stick to DB status if it matches, otherwise ignore for now 
        # or implement simple mapping if easy.
        # The UI currently has "On Time", "Late", "Absent". 
        # "Absent" implies no record, so it won't be in logs.
        # "Late" implies CHECK_IN after a time.
        # Let's just filter by name/dept/date for now as primary requirement.
        pass

    query += " ORDER BY a.timestamp DESC"

    # Optional pagination
    try:
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))
        if limit > 0:
            query += " LIMIT ? OFFSET ?"
            params += [limit, offset]
    except:
        pass
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    attendance = []
    # Dynamic filters from registration fields: any query params not in the standard list
    standard_keys = {'start_date','end_date','department','designation','shift','phone','name','person_id','status','limit','offset'}
    extra_filters = {k: v for k, v in request.args.items() if k not in standard_keys and v is not None and str(v).strip() != ''}
    for row in rows:
        # Check if captured_image column exists in the row (for backward compatibility)
        img = None
        if 'captured_image' in row.keys():
            img = row['captured_image']
        # Decode face custom_data for dynamic filtering
        face_custom = {}
        try:
            if 'face_custom_data' in row.keys() and row['face_custom_data']:
                face_custom = json.loads(row['face_custom_data'])
        except Exception:
            face_custom = {}
        # Apply extra filters: must match all provided keys
        match = True
        for k, v in extra_filters.items():
            rv = None
            # Try from custom_data; fallback to row fields if present
            if k in face_custom:
                rv = str(face_custom.get(k))
            elif k in row.keys():
                rv = str(row[k])
            if rv is None or str(rv).strip() != str(v).strip():
                match = False
                break
        if not match:
            continue
        attendance.append({
            "id": row["id"],
            "person_id": row["person_id"] if "person_id" in row.keys() else None,
            "name": row["name"],
            "timestamp": row["timestamp"],
            "status": row["status"],
            "is_late": row["is_late"] if "is_late" in row.keys() else 0,
            "activity": row["activity"] if "activity" in row.keys() else "",
            "captured_image": img,
            "vendor_id": row["vendor_id"] if "vendor_id" in row.keys() else None,
            "device_id": row["device_id"] if "device_id" in row.keys() else None,
            "device_name": row["device_name"] if "device_name" in row.keys() else None,
            "department": row["department"] if "department" in row.keys() else "",
            "designation": row["designation"] if "designation" in row.keys() else "",
            "shift": row["shift"] if "shift" in row.keys() else "",
            "phone": row["phone"] if "phone" in row.keys() else "",
            "custom_data": face_custom
        })
    
    return jsonify({"attendance": attendance})


