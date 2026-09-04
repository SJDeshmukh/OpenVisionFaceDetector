import os
import time
import sqlite3
import base64
import json
import psycopg2
import traceback
from psycopg2.extras import RealDictCursor
from datetime import date, timedelta, datetime
from threading import Lock
import cachetools
import logging
from functools import wraps
from flask import request, jsonify

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

# --- Path Setup ---
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)

# --- Feature & Template Constants ---
BUNDLE_FEATURES = {
    'attendance_ui': ['reports', 'report_detailed', 'mobile_app', 'live_attendance', 'cameras', 'enable_attendance', 'geofencing'],
    'attendance_payroll_ui': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts'],
    'enterprise_custom_ui': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts', 'api_access', 'white_labeling'],
    'default_attendance': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing'],
    'class_attendance_ui': ['reports', 'report_detailed', 'bulk_image_attendance', 'live_attendance', 'cameras', 'enable_attendance', 'classes'],
    'attendx_bulk_ui': ['reports', 'report_detailed', 'bulk_image_attendance', 'live_attendance', 'cameras', 'enable_attendance', 'classes', 'payroll', 'parent_login', 'lecture_wise_reports'],
    'tapinx_ui': ['reports', 'report_detailed', 'mobile_app', 'live_attendance', 'cameras', 'enable_attendance', 'geofencing', 'parent_alerts', 'checkin_checkout', 'parent_login']
}

ALL_FEATURES = ['reports', 'report_detailed', 'report_payroll', 'automated_email_reports', 'xchat_ai', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts', 'api_access', 'white_labeling', 'late_mark', 'bulk_image_attendance', 'classes', 'leave_management', 'parent_login', 'lecture_wise_reports', 'parent_alerts', 'checkin_checkout']

REGISTRATION_TEMPLATES = {
    "school": [
        {"field": "student_id", "label": "Student ID", "enabled": True},
        {"field": "phone", "label": "Student Mobile Number", "enabled": True},
        {"field": "class_section", "label": "Class/Section", "enabled": False}
    ],
    "hostel": [
        {"field": "student_id", "label": "Student ID", "enabled": True},
        {"field": "phone", "label": "Student Mobile Number", "enabled": True},
        {"field": "class_section", "label": "Class/Section", "enabled": False}
    ],
    "daily_wages": [
        {"field": "employee_id", "label": "Employee ID", "enabled": True},
        {"field": "phone", "label": "Contact Mobile", "enabled": False},
        {"field": "department", "label": "Department", "enabled": False}
    ],
    "class_attendance": [
        {"field": "student_number", "label": "Student Number", "enabled": True},
        {"field": "class_section", "label": "Class/Section", "enabled": True},
        {"field": "phone", "label": "Parent Mobile Number", "enabled": False}
    ],
    "factory": [
        {"field": "employee_id", "label": "Employee ID", "enabled": True},
        {"field": "department", "label": "Department", "enabled": True}
    ],
    "bulk_attendance_attendx": [
        {"field": "student_number", "label": "Student/Employee Number", "enabled": True},
        {"field": "class_section", "label": "Class/Department", "enabled": True},
        {"field": "daily_wage", "label": "Daily Wage", "enabled": True},
        {"field": "phone", "label": "Parent/Contact Mobile", "enabled": True}
    ],
    "checkin_checkout_tapinx": [
        {"field": "student_id", "label": "Student ID", "enabled": True},
        {"field": "phone", "label": "Parent Mobile Number", "enabled": True},
        {"field": "class_section", "label": "Class/Section", "enabled": True}
    ]
}

# --- Configuration & Globals ---
DATABASE_URL = os.environ.get("DATABASE_URL")
LOW_RAM_MODE = str(os.environ.get("LOW_RAM_MODE", "0")).strip().lower() in ("1", "true", "yes", "y")

try:
    DET_MAX_SIDE_DEFAULT = int(os.environ.get("DET_MAX_SIDE", "640" if LOW_RAM_MODE else "1280"))
except Exception:
    DET_MAX_SIDE_DEFAULT = 640 if LOW_RAM_MODE else 1280

try:
    import faiss as _faiss
except ImportError:
    _faiss = None

USE_FAISS = str(os.environ.get("USE_FAISS", "0")).strip().lower() in ("1", "true", "yes", "y") and (_faiss is not None) and (not LOW_RAM_MODE)
_FAISS_LOCK = Lock() if USE_FAISS else None

import uuid
import redis
import sqlite3
import numpy as np
import io
try:
    from PIL import Image, ImageOps
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    Image = None
    ImageOps = None

import cv2

# --- Image Decoding Utilities ---
def decode_image_to_rgb(body: bytes) -> np.ndarray | None:
    """Decodes image bytes (JPEG, PNG, HEIC, etc.) to an RGB NumPy array."""
    if not body:
        return None
    
    # Try Pillow first (handles HEIC, WebP, etc.)
    if Image:
        try:
            with Image.open(io.BytesIO(body)) as img:
                img = ImageOps.exif_transpose(img)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                return np.array(img)
        except Exception as e:
            # logger.warning(f"Pillow decode failed: {e}")
            pass
            
    # Fallback to OpenCV
    try:
        arr = np.frombuffer(body, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is not None:
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        pass
        
    return None

def decode_image_to_bgr(body: bytes) -> np.ndarray | None:
    """Decodes image bytes (JPEG, PNG, HEIC, etc.) to a BGR NumPy array (OpenCV format)."""
    rgb = decode_image_to_rgb(body)
    if rgb is not None:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return None

def extract_student_number_from_custom_data(c_data_raw, search_term=None):
    """
    Extracts a student enrollment number from the custom_data JSON field.
    Priority: student_number, student number, id_number, id number, student_id.
    """
    if not c_data_raw:
        return ""
    try:
        cd = json.loads(c_data_raw) if isinstance(c_data_raw, str) else c_data_raw
    except Exception:
        cd = None
        
    if not isinstance(cd, dict):
        if search_term and str(search_term).lower() in str(c_data_raw).lower():
            return str(search_term).strip()
        return ""

    # Priority keys for student/employee ID
    priority_keys = [
        "student_number", "student number",
        "id_number",      "id number",
        "employee_id",    "employee id",
        "student_id",     "student id"
    ]
    
    # 1. Try to find an exact match for one of the priority keys
    for k in priority_keys:
        val = str(cd.get(k) or "").strip()
        if val:
            return val
            
    # 2. Try case-insensitive matching for keys
    cd_lower = {str(k).lower(): v for k, v in cd.items()}
    for k in priority_keys:
        val = str(cd_lower.get(k) or "").strip()
        if val:
            return val
            
    # 3. Fallback: if search_term is provided and exists in any value, return search_term
    if search_term:
        st_lower = str(search_term).lower()
        if any(st_lower in str(v).lower() for v in cd.values()):
            return str(search_term).strip()

    return ""

def get_face_augmentations(img_rgb: np.ndarray) -> list[np.ndarray]:
    """
    Generates augmented views to maximise recognition coverage across real-world conditions.
    Covers: lighting variation, head tilt, mild perspective (seat rows), distance blur,
    and combined transforms.  Returns ~14 views from a single crop.
    """
    if img_rgb is None or img_rgb.size == 0:
        return []

    h, w = img_rgb.shape[:2]
    center = (w // 2, h // 2)
    augs = [img_rgb]

    # ── 1. Horizontal flip ────────────────────────────────────────────────────
    try:
        augs.append(cv2.flip(img_rgb, 1))
    except Exception: pass

    # ── 2. Lighting (classroom has uneven / artificial lighting) ─────────────
    try:
        augs.append(cv2.convertScaleAbs(img_rgb, alpha=1.25, beta=15))   # brighter
        augs.append(cv2.convertScaleAbs(img_rgb, alpha=0.75, beta=-15))  # darker
        augs.append(cv2.convertScaleAbs(img_rgb, alpha=1.10, beta=5))    # mild warm
    except Exception: pass

    # ── 3. Head-tilt rotation (seats cause 5-15° natural tilt) ──────────────
    try:
        for angle in [8, -8, 15, -15]:
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            augs.append(cv2.warpAffine(img_rgb, M, (w, h), borderMode=cv2.BORDER_REFLECT_101))
    except Exception: pass

    # ── 4. Horizontal perspective warp (simulate seated-row 3D turn ~15-20°) ─
    try:
        pts_src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        shift = int(w * 0.10)   # ~10% width shift
        for pts_dst in [
            np.float32([[shift, 0], [w, 0], [w - shift, h], [0, h]]),   # slight left turn
            np.float32([[0, 0], [w - shift, 0], [w, h], [shift, h]]),   # slight right turn
        ]:
            M_p = cv2.getPerspectiveTransform(pts_src, pts_dst)
            warped = cv2.warpPerspective(img_rgb, M_p, (w, h), borderMode=cv2.BORDER_REFLECT_101)
            augs.append(warped)
    except Exception: pass

    # ── 5. Distance blur (back-row faces are softer / lower-res) ────────────
    try:
        augs.append(cv2.GaussianBlur(img_rgb, (3, 3), 0.8))
    except Exception: pass

    # ── 6. Combined: flip + darker (common real-world pairing) ───────────────
    try:
        flipped_dark = cv2.convertScaleAbs(cv2.flip(img_rgb, 1), alpha=0.80, beta=-10)
        augs.append(flipped_dark)
    except Exception: pass

    return augs


def prepare_augmented_embeddings(img_rgb: np.ndarray, mfd_app) -> list:
    """
    Given a full image, finds the primary face, crops it,
    generates ~14 augmented versions of the CROP, and returns their embeddings.

    Augmenting the CROP (not the raw photo) is critical: the embedder aligns
    the face geometrically before extracting features, so augmentations applied
    to the uncropped image are mostly normalised away.  Applying them to the
    already-cropped face ensures the model sees genuinely diverse views.
    Returns: List of 512-d embeddings (numpy arrays).
    """
    try:
        # 1. Detect faces in the original image
        # We use fast=True to get raw crops quickly
        det_ann, det_crops, det_df, _ = mfd_app.detect_faces(
            image_input=img_rgb,
            compute_embeddings=False,
            crop_mode="Face",
            portrait_scale=1.5,
            enhancer="None", # Skip enhancement during registration to keep it raw/consistent
            det_max_side=1280
        )
        
        if not det_crops or len(det_crops) == 0:
            print("[UTILS] No face detected during augmentation prep.")
            return []
            
        # 2. Take the primary face crop
        primary_crop = det_crops[0]
        
        # 3. Generate 6 augmented versions of the CROP
        augmented_crops = get_face_augmentations(primary_crop)
        
        # 4. Extract embeddings for each augmented crop
        embedder = mfd_app.get_embedder()
        embeddings = []
        for crop in augmented_crops:
            # FacePlugin/ONNX embedder handles resizing internally
            emb = embedder.embed(crop)
            if emb is not None and emb.size > 0:
                embeddings.append(emb)
                
        return embeddings
    except Exception as e:
        print(f"[UTILS] prepare_augmented_embeddings failed: {e}")
        import traceback
        traceback.print_exc()
        return []

# --- Database Utilities ---
def get_table_columns(conn, table_name):
    """Returns a list of column names for a given table."""
    c = conn.cursor()
    is_pg = getattr(conn, "_is_pg", False)
    try:
        if is_pg:
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table_name,))
            return [str(r[0]) for r in c.fetchall()]
        else:
            c.execute(f"PRAGMA table_info({table_name})")
            return [str(r[1]) for r in c.fetchall()]
    except Exception:
        if is_pg and hasattr(conn, "rollback"): conn.rollback()
        return []
    finally:
        c.close()

def get_db_connection(timeout=30):
    """Proxy to db_factory.get_db_connection to avoid circular imports."""
    from db_factory import get_db_connection as _get_conn
    return _get_conn(timeout)

def _run(conn, sql, params=None):
    """Helper to run a SQL command and commit, handling cross-DB compatibility."""
    is_pg = getattr(conn, "_is_pg", False)
    if is_pg:
        # Convert ? placeholders to %s for PostgreSQL
        if params and "?" in sql:
            sql = sql.replace("?", "%s")
        # Handle 'INSERT OR IGNORE' -> 'INSERT ... ON CONFLICT DO NOTHING'
        if "INSERT OR IGNORE" in sql.upper():
            sql = sql.upper().replace("INSERT OR IGNORE", "INSERT") + " ON CONFLICT DO NOTHING"
            # Note: This is a simplistic replacement; assumes the target table has a UNIQUE constraint/PK
            # and that 'INSERT' was the first word. In practice, our queries follow this pattern.

    c = conn.cursor()
    try:
        c.execute(sql, params or ())
        conn.commit()
    except Exception as e:
        if is_pg: conn.rollback()
        raise e
    finally:
        c.close()

def ensure_audit_logs_table(conn):
    """Ensures that the audit_logs table exists."""
    is_pg = getattr(conn, "_is_pg", False)
    if is_pg:
        sql = """CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY,
                    actor_username TEXT,
                    actor_role TEXT,
                    target_vendor_id INTEGER,
                    action TEXT,
                    details TEXT,
                    ip TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
    else:
        sql = """CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_username TEXT,
                    actor_role TEXT,
                    target_vendor_id INTEGER,
                    action TEXT,
                    details TEXT,
                    ip TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )"""
    _run(conn, sql)

# Bounded cache for embeddings: max 20 vendors, 10 min TTL
_VENDOR_EMB_CACHE = cachetools.TTLCache(maxsize=20, ttl=600)

def _now_ts():
    try:
        import time as _t
        return _t.time()
    except Exception:
        return 0.0

def parse_db_date(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        val = val.strip().replace('T', ' ')
        fmts = [
            '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d',
            '%a, %d %b %Y %H:%M:%S %Z',
            '%a, %d %b %Y %H:%M:%S',
            '%d %b %Y', '%b %d, %Y',
            '%a, %d %b %Y'
        ]
        for fmt in fmts:
            try:
                return datetime.strptime(val, fmt).date()
            except Exception:
                pass
            if ' ' in val:
                try:
                    return datetime.strptime(val.split(' ')[0], fmt).date()
                except Exception:
                    pass
        
        # Final fallback for HTTP/RFC formats
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(val).date()
        except Exception:
            pass
    return None

def parse_db_datetime(val):
    if not val: return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, str):
        val_clean = val.strip().replace('T', ' ')
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%a, %d %b %Y %H:%M:%S %Z'):
            try:
                return datetime.strptime(val_clean, fmt)
            except Exception:
                continue
        
        # Final fallback for HTTP/RFC formats
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(val_clean)
        except Exception:
            pass
    return None


# --- Observability & Security Decorators ---
def error_logger(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {f.__name__}: {e}\n{traceback.format_exc()}")
            raise e
    return wrapped

def rate_limit(limit=60, window=60):
    """Placeholder for rate limiting logic. Can be integrated with Redis."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # In a real implementation, you'd check Redis or a memory store here.
            return f(*args, **kwargs)
        return wrapped
    return decorator

def track_metrics(name):
    """Decorator to track function execution metrics."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            start_time = time.time()
            try:
                result = f(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                # logger.info(f"METRIC: {name} took {duration:.4f}s")
        return wrapped
    return decorator

# --- Redis Client ---
REDIS_URL = os.environ.get("REDIS_URL")
try:
    if REDIS_URL:
        redis_client = redis.from_url(REDIS_URL)
        # Ping to check if actually available
        redis_client.ping()
    else:
        redis_client = None
except Exception:
    redis_client = None

# --- Testing Mode ---
def is_testing():
    return os.environ.get("FLASK_ENV") == "testing" or os.environ.get("PYTEST_CURRENT_TEST") is not None

# --- Internal Bounded Cache ---
# max 2000 items, 5 min TTL
CACHE = cachetools.TTLCache(maxsize=2000, ttl=300)
def cache_get(key):
    try:
        if redis_client:
            val = redis_client.get(f"cache:{key}")
            if val is not None:
                return json.loads(val)
    except Exception:
        pass
    try:
        return CACHE.get(key)
    except Exception:
        return None

def cache_set(key, value, ttl=300):
    try:
        if redis_client:
            redis_client.setex(f"cache:{key}", ttl, json.dumps(value))
            return
    except Exception:
        pass
    try:
        CACHE[key] = value
    except Exception:
        pass

def cache_delete(key):
    try:
        if redis_client:
            redis_client.delete(f"cache:{key}")
    except Exception:
        pass
    if key in CACHE:
        del CACHE[key]

def cache_delete_vendor_prefix(vendor_id):
    """Delete all cache keys starting with vendor:{vendor_id}:"""
    prefix = f"vendor:{vendor_id}:"
    try:
        if redis_client:
            # Note: redis.keys is O(N), for large datasets scan is better. 
            # But for a typical app, this is fine.
            keys = redis_client.keys(f"cache:{prefix}*")
            if keys:
                redis_client.delete(*keys)
    except Exception:
        pass
    
    # Clean in-memory cache
    to_del = [k for k in CACHE.keys() if k.startswith(prefix)]
    for k in to_del:
        del CACHE[k]

    # Recognition caches use a compact numeric prefix instead of the API cache
    # prefix. Clear them in the same operation so a class reassignment or a
    # student/faculty type correction is visible to the very next scan.
    embedding_prefix = f"{int(vendor_id or 0)}_"
    embedding_keys = [
        key for key in list(_VENDOR_EMB_CACHE.keys())
        if str(key).startswith(embedding_prefix)
    ]
    for key in embedding_keys:
        del _VENDOR_EMB_CACHE[key]

# --- Job Registry ---
JOBS = {}
def create_job(content_type="application/json", ttl=600):
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "result": None, "error": None, "content_type": content_type, "expires": time.time() + ttl}
    return job_id

def complete_job(job_id, result):
    if job_id in JOBS:
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["result"] = result

def fail_job(job_id, err):
    if job_id in JOBS:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(err)

def get_job(job_id):
    j = JOBS.get(job_id)
    if not j:
        return None
    if j["expires"] < time.time():
        return None
    return j

# --- Vendor & Feature Checks ---
def check_vendor_status(vendor_id):
    """
    Checks if a vendor is allowed to access the system.
    Returns: (is_allowed, reason)
    """
    if not vendor_id:
        return True, "SuperAdmin"
    
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Check Vendor Status
        c.execute("SELECT status FROM vendors WHERE id = ?", (vendor_id,))
        vendor = c.fetchone()
        if not vendor:
            return False, "Vendor not found"
        if vendor['status'] != 'active':
            return False, "Account Suspended"
            
        c.execute("SELECT end_date, grace_period_days FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        sub = c.fetchone()
        if sub:
            ed = sub['end_date'] if isinstance(sub, dict) else sub[0]
            grace = (sub['grace_period_days'] if isinstance(sub, dict) else sub[1]) or 0
            ed_date = parse_db_date(ed)
            if ed_date:
                if date.today() > (ed_date + timedelta(days=grace)):
                    return False, "Subscription Expired"
            
        # Check Overdue Invoices
        today = date.today().isoformat()
        c.execute("""
            SELECT COUNT(*) FROM invoices 
            WHERE vendor_id = ? 
            AND (status = 'overdue' OR (status = 'generated' AND due_date < ?))
        """, (vendor_id, today))
        overdue_count = c.fetchone()[0]
        
        if overdue_count > 0:
            return False, "Unpaid Invoices"
            
        return True, "Active"
    finally:
        conn.close()

def get_db_connection(timeout=30):
    try:
        from db_factory import get_db_connection as _get
        return _get(timeout=timeout)
    except ImportError:
        # Fallback to simple sqlite if db_factory is not available or in path
        db_path = os.environ.get("DB_PATH", "face_db.sqlite")
        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        return conn

def reset_sequence(table_name):
    """
    Resets the auto-increment sequence for a given table to MAX(id) + 1.
    Compatible with SQLite and PostgreSQL.
    """
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Check if Postgres using the _is_pg flag from db_factory wrappers
        is_pg = getattr(conn, "_is_pg", False)
            
        if is_pg:
            # Postgres: setval(seq, val, is_called)
            # If table is empty, set val=1, is_called=false so nextval returns 1
            # If table has max(id)=N, set val=N, is_called=true so nextval returns N+1
            sql = f"""
                SELECT setval(
                    pg_get_serial_sequence('{table_name}', 'id'), 
                    COALESCE((SELECT MAX(id) FROM {table_name}), 1), 
                    EXISTS (SELECT 1 FROM {table_name})
                )
            """
            c.execute(sql)
        else:
            # SQLite: UPDATE sqlite_sequence
            sql = f"UPDATE sqlite_sequence SET seq = COALESCE((SELECT MAX(id) FROM {table_name}), 0) WHERE name = '{table_name}'"
            c.execute(sql)
            
        conn.commit()
        conn.close()
    except Exception:
        pass

def require_feature(*feature_names):
    from functools import wraps
    from flask import request, jsonify
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if request.method == 'OPTIONS':
                return jsonify({}), 200

            # Authenticate & Get Vendor ID
            from services.auth_service import authenticate_vendor_access
            vendor_id, error = authenticate_vendor_access()
            if error: return error
            
            # Check Feature (Only for Vendor Context)
            if vendor_id:
                # Bypass for mobile_app (legacy/special case) if it's one of the requested features
                if "mobile_app" in feature_names:
                    return f(*args, **kwargs)
                
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
                row = c.fetchone()
                conn.close()
                
                has_feature = False
                features = []
                if row and row[0]:
                    try:
                        features = json.loads(row[0])
                        # Check if ANY of the requested features are present
                        if any(fn in features for fn in feature_names):
                            has_feature = True
                    except Exception:
                        pass
                
                if not has_feature:
                    return jsonify({"error": f"Feature(s) {feature_names} not enabled for this vendor"}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def _run(cur, sql, params=None):
    if params is None:
        params = []
    # If the cursor belongs to a Postgres connection, adapt query
    is_pg = False
    try:
        # Check if it's our PostgresCursorWrapper or similar
        if hasattr(cur, "cursor") and hasattr(cur.cursor, "mogrify"): # Raw psycopg2
             is_pg = True
        elif hasattr(cur, "_is_pg"): # Our wrapper
             is_pg = cur._is_pg
    except Exception:
        pass

    if is_pg:
        sql = sql.replace("?", "%s")
    cur.execute(sql, params)

def _ensure_class_batch_tables(conn):
    try:
        c = conn.cursor()
        is_pg = getattr(conn, "_is_pg", False)
        
        if is_pg:
            c.execute("""
                CREATE TABLE IF NOT EXISTS class_batches (
                    id TEXT PRIMARY KEY,
                    vendor_id INTEGER,
                    class_year TEXT,
                    division TEXT,
                    branch TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS class_batch_items (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT,
                    seq INTEGER,
                    image_b64 TEXT,
                    annotated_b64 TEXT,
                    faces_json TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            c.execute("""
                CREATE TABLE IF NOT EXISTS class_batches (
                    id TEXT PRIMARY KEY,
                    vendor_id INTEGER,
                    class_year TEXT,
                    division TEXT,
                    branch TEXT,
                    status TEXT DEFAULT 'active',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS class_batch_items (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT,
                    seq INTEGER,
                    image_b64 TEXT,
                    annotated_b64 TEXT,
                    faces_json TEXT,
                    status TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
    except Exception:
        pass

def postgres_available():
    if not (DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://"))):
        return False
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False

def ensure_audit_logs_table():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            c.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    actor_username TEXT,
                    actor_role TEXT,
                    target_vendor_id INTEGER,
                    action TEXT,
                    details TEXT,
                    ip TEXT
                )
            """)
        else:
            c.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    actor_username TEXT,
                    actor_role TEXT,
                    target_vendor_id INTEGER,
                    action TEXT,
                    details TEXT,
                    ip TEXT
                )
            """)
            
            # Migration: Add missing columns if table existed from old version
            try:
                c.execute("PRAGMA table_info(audit_logs)")
                cols = [info[1] for info in c.fetchall()]
                if 'actor_role' not in cols:
                    c.execute("ALTER TABLE audit_logs ADD COLUMN actor_role TEXT")
                if 'ip' not in cols:
                    c.execute("ALTER TABLE audit_logs ADD COLUMN ip TEXT")
            except Exception:
                pass
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

def log_audit(action, details=None, target_vendor_id=None, status="success", actor=None):
    try:
        from flask import request
        from services.auth_service import verify_token
        
        conn = get_db_connection()
        ensure_audit_logs_table(conn)
        c = conn.cursor()
        actor_username = actor
        actor_role = None
        
        if not actor_username:
            try:
                auth_header = request.headers.get('Authorization')
                if auth_header:
                    token = auth_header.split(" ")[1]
                    user_data = verify_token(token)
                    if user_data:
                        actor_username = user_data.get('username')
                        actor_role = user_data.get('role')
            except Exception:
                pass
        
        if not actor_username:
            actor_username = 'system'

        try:
            ip = request.remote_addr
        except:
            ip = '0.0.0.0'

        payload = {"status": status}
        if isinstance(details, dict):
            payload.update(details)
        elif isinstance(details, str):
            payload["message"] = details
            
        c.execute("INSERT INTO audit_logs (actor_username, actor_role, target_vendor_id, action, details, ip) VALUES (?, ?, ?, ?, ?, ?)",
             (actor_username, actor_role, target_vendor_id, action, json.dumps(payload), ip))
        conn.commit()
        conn.close()
    except Exception:
        try:
            conn.close()
        except:
            pass

def vendor_has_feature(vendor_id, feature_name):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT features FROM subscriptions WHERE vendor_id = ? LIMIT 1", (vendor_id,))
        row = c.fetchone()
        conn.close()
        if row:
            raw = row['features'] if isinstance(row, dict) else row[0]
            if not raw:
                return False
            try:
                features = json.loads(raw) if isinstance(raw, str) else list(raw)
            except Exception:
                features = []
            return feature_name in features
        return False
    except Exception:
        return False

def _align_landmarks_3d(lmks):
    """
    Remove head pose (yaw/pitch/roll) by rotating the 3D mesh into a
    canonical frontal frame defined by the eye line (X) and the
    orthogonalized nose-bridge→chin vector (Y).
    Handles both 2D (68,2) and 3D (68,3) landmarks by padding 2D→3D.
    Falls back to the original landmarks on degenerate input.
    """
    import numpy as np
    lmks = np.array(lmks, dtype=np.float32)
    # Pad 2D landmarks to 3D with z=0
    if lmks.ndim == 2 and lmks.shape[1] == 2:
        lmks = np.column_stack([lmks, np.zeros(len(lmks), dtype=np.float32)])
    if lmks.ndim != 2 or lmks.shape[1] != 3:
        return lmks
    le = np.mean(lmks[36:42], axis=0)
    re = np.mean(lmks[42:48], axis=0)

    x_axis = re - le
    x_norm = np.linalg.norm(x_axis)
    if x_norm < 1e-5:
        return lmks
    x_axis /= x_norm

    y_raw = lmks[27] - lmks[8]  # nose bridge → chin
    y_axis = y_raw - np.dot(y_raw, x_axis) * x_axis  # orthogonalize against X
    y_norm = np.linalg.norm(y_axis)
    if y_norm < 1e-5:
        return lmks
    y_axis /= y_norm

    z_axis = np.cross(x_axis, y_axis)
    z_norm = np.linalg.norm(z_axis)
    if z_norm < 1e-5:
        return lmks
    z_axis /= z_norm

    # R columns are face axes in world space; R^T maps face frame → canonical
    R = np.column_stack([x_axis, y_axis, z_axis])
    center = (le + re) / 2.0
    return ((R.T @ (lmks - center).T).T + center).astype(np.float32)


def _extract_structural_vector(lmks):
    """
    204-dim pose-aligned full-mesh: align to canonical frontal frame first,
    then 68pts × 3 coords anchored to nose bridge, scaled by IOD, L2-normalized.
    """
    import numpy as np
    if lmks is None or len(lmks) != 68: return np.array([], dtype=np.float32)
    lmks = np.array(lmks, dtype=np.float32)
    lmks = _align_landmarks_3d(lmks)
    anchor = lmks[27]  # nose bridge (after alignment)
    le = np.mean(lmks[36:42], axis=0)
    re = np.mean(lmks[42:48], axis=0)
    iod = float(np.linalg.norm(le - re))
    if iod < 1e-5: iod = 1.0
    mesh_norm = (lmks - anchor) / iod
    v = mesh_norm.flatten().astype(np.float32)
    n = np.linalg.norm(v)
    return (v / n) if n > 1e-6 else v
