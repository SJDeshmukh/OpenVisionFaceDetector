import os
import time
import sqlite3
import base64
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import date, timedelta, datetime
from threading import Lock

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

_VENDOR_EMB_CACHE = {}

def _now_ts():
    try:
        import time as _t
        return _t.time()
    except Exception:
        return 0.0


# --- Redis Client ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
try:
    redis_client = redis.from_url(REDIS_URL)
    # Ping to check if actually available
    redis_client.ping()
except Exception:
    redis_client = None

# --- Testing Mode ---
def is_testing():
    return os.environ.get("FLASK_ENV") == "testing" or os.environ.get("PYTEST_CURRENT_TEST") is not None

# --- Internal Cache ---
CACHE = {}
def cache_get(key):
    try:
        if redis_client:
            val = redis_client.get(f"cache:{key}")
            if val is not None:
                return json.loads(val)
    except Exception:
        pass
    v = CACHE.get(key)
    if not v:
        return None
    if v["e"] < time.time():
        return None
    return v["v"]

def cache_set(key, value, ttl):
    try:
        if redis_client:
            redis_client.setex(f"cache:{key}", ttl, json.dumps(value))
            return
    except Exception:
        pass
    CACHE[key] = {"v": value, "e": time.time() + ttl}

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
            
        # Check Subscription Expiry
        c.execute("SELECT end_date, grace_period_days FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        sub = c.fetchone()
        if not sub:
            return False, "No active subscription"
            
        expiry = datetime.strptime(sub['end_date'], '%Y-%m-%d').date()
        grace = sub['grace_period_days'] or 0
        if date.today() > (expiry + timedelta(days=grace)):
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

def reset_sequence(table_name):
    """
    Resets the auto-increment sequence for a given table to MAX(id) + 1.
    Compatible with SQLite and PostgreSQL.
    """
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Check if Postgres
        is_pg = False
        try:
            is_pg = isinstance(conn, CompatConn) and getattr(conn, "_is_pg", False)
        except Exception:
            pass
            
        if is_pg:
            # Postgres: setval
            sql = f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE((SELECT MAX(id) FROM {table_name}), 0))"
            _run(c, sql)
        else:
            # SQLite: UPDATE sqlite_sequence
            sql = f"UPDATE sqlite_sequence SET seq = COALESCE((SELECT MAX(id) FROM {table_name}), 0) WHERE name = '{table_name}'"
            _run(c, sql)
            
        conn.commit()
        conn.close()
    except Exception:
        pass

def vendor_has_feature(vendor_id, feature_name):
    try:
        if is_testing() and feature_name == "late_mark":
            return True
    except Exception:
        pass
    if not vendor_id:
        return True
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            try:
                features = json.loads(row[0])
                return feature_name in features
            except Exception:
                return False
        return False
    except Exception:
        return False

# --- Schema Helpers ---
def _ensure_class_batch_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS class_batches(
        id TEXT PRIMARY KEY,
        vendor_id INTEGER,
        class_year TEXT,
        division TEXT,
        branch TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS class_batch_items(
        id TEXT PRIMARY KEY,
        batch_id TEXT,
        seq INTEGER,
        image_b64 TEXT,
        annotated_b64 TEXT,
        faces_json TEXT,
        status TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

_POSTGRES_AVAILABLE = None
def postgres_available():
    global _POSTGRES_AVAILABLE
    if _POSTGRES_AVAILABLE is False:
        return False
    if not (DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://"))):
        _POSTGRES_AVAILABLE = False
        return False
    if psycopg2 is None:
        _POSTGRES_AVAILABLE = False
        return False
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        _POSTGRES_AVAILABLE = True
        return True
    except Exception:
        _POSTGRES_AVAILABLE = False
        return False

def get_db_connection(timeout=30):
    if postgres_available():
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return CompatConn(conn, True)
        except Exception:
            pass
    try:
        from db_factory import get_db_connection as _get
        return _get(timeout=timeout)
    except ImportError:
        # Fallback to simple sqlite if db_factory is not available or in path
        db_path = os.environ.get("DATABASE_URL", "face_db.sqlite")
        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        return conn

class CompatCursor:
    def __init__(self, conn, cur, is_pg):
        self._conn = conn
        self._cur = cur
        self._is_pg = is_pg
    def execute(self, sql, params=None):
        if params is None:
            params = []
        # PostgreSQL doesn't like ? placeholder if we use regular psycopg2 without wrapper
        # but db_factory already handles this. This is for direct usage if needed.
        self._cur.execute(sql, params)
    def executemany(self, sql, seq):
        self._cur.executemany(sql, seq)
    def fetchall(self):
        return self._cur.fetchall()
    def fetchone(self):
        return self._cur.fetchone()
    @property
    def rowcount(self):
        try:
            return self._cur.rowcount
        except Exception:
            return None
    def __getattr__(self, name):
        return getattr(self._cur, name)

class CompatConn:
    def __init__(self, raw_conn, is_pg):
        self._raw = raw_conn
        self._is_pg = is_pg
    def cursor(self):
        if self._is_pg:
            return CompatCursor(self, self._raw.cursor(cursor_factory=RealDictCursor), True)
        return self._raw.cursor()
    def commit(self):
        return self._raw.commit()
    def rollback(self):
        return self._raw.rollback()
    def close(self):
        return self._raw.close()
    def __getattr__(self, name):
        return getattr(self._raw, name)

def log_audit(action, details=None, target_vendor_id=None, actor="system"):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO audit_logs (actor_username, action, target_vendor_id, details) VALUES (?, ?, ?, ?)",
                  (actor, action, target_vendor_id, json.dumps(details or {})))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

def _pg_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)

def _adapt_query_for_pg(sql):
    return sql.replace("?", "%s")

def _run(cur, sql, params=None):
    if params is None:
        params = []
    if isinstance(cur, CompatCursor) and getattr(cur, "_is_pg", False):
        sql = _adapt_query_for_pg(sql)
    cur.execute(sql, params)

# --- Feature & Template Constants ---
BUNDLE_FEATURES = {
    'attendance_ui': ['reports', 'report_detailed', 'mobile_app', 'live_attendance', 'cameras', 'enable_attendance', 'geofencing'],
    'attendance_payroll_ui': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts'],
    'enterprise_custom_ui': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts', 'api_access', 'white_labeling'],
    'default_attendance': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing'],
    'class_attendance_ui': ['reports', 'report_detailed', 'bulk_image_attendance', 'live_attendance', 'cameras', 'enable_attendance', 'classes']
}

ALL_FEATURES = ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts', 'api_access', 'white_labeling', 'late_mark', 'bulk_image_attendance', 'classes']

REGISTRATION_TEMPLATES = {
    "school": [
        {"field": "student_number", "label": "Student Number", "enabled": True},
        {"field": "class_section", "label": "Class/Section", "enabled": True},
        {"field": "father_name", "label": "Father's Name", "enabled": True}
    ],
    "class_attendance": [
        {"field": "student_number", "label": "Student Number", "enabled": True},
        {"field": "class_section", "label": "Class/Section", "enabled": True},
        {"field": "phone", "label": "Parent Mobile Number", "enabled": False}
    ],
    "factory": [
        {"field": "employee_id", "label": "Employee ID", "enabled": True},
        {"field": "department", "label": "Department", "enabled": True}
    ]
}
