import sqlite3
import base64
import os
import json
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, Blueprint, request, jsonify, render_template
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, leave_room
try:
    from flask_compress import Compress
except Exception:
    class Compress:
        def __init__(self, *args, **kwargs): pass
try:
    import eventlet
except Exception:
    eventlet = None
from services.llm_service import generate_greeting
import uuid
import time
try:
    import redis
except Exception:
    redis = None
try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
except Exception:
    class _DummyMetric:
        def labels(self, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
    Counter = Histogram = None
    def generate_latest(*args, **kwargs): return b""
    CONTENT_TYPE_LATEST = "text/plain"
from functools import wraps
from storage import upload_base64_image, presigned_url_for_key, OBJECT_STORAGE_ENABLED
from werkzeug.security import generate_password_hash, check_password_hash
def ensure_task_events_table():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        is_pg = isinstance(conn, CompatConn) and getattr(conn, "_is_pg", False)
        if is_pg:
            _run(c, """
                CREATE TABLE IF NOT EXISTS task_events (
                    id SERIAL PRIMARY KEY,
                    task_id TEXT,
                    name TEXT,
                    queue TEXT,
                    worker TEXT,
                    status TEXT,
                    received_at TIMESTAMP,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    runtime REAL,
                    retries INTEGER,
                    eta TIMESTAMP,
                    args TEXT,
                    kwargs TEXT,
                    result TEXT,
                    error TEXT,
                    trace TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            _run(c, """
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    name TEXT,
                    queue TEXT,
                    worker TEXT,
                    status TEXT,
                    received_at DATETIME,
                    started_at DATETIME,
                    finished_at DATETIME,
                    runtime REAL,
                    retries INTEGER,
                    eta DATETIME,
                    args TEXT,
                    kwargs TEXT,
                    result TEXT,
                    error TEXT,
                    trace TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        _run(c, "CREATE INDEX IF NOT EXISTS idx_task_events_status ON task_events(status)")
        _run(c, "CREATE INDEX IF NOT EXISTS idx_task_events_name ON task_events(name)")
        _run(c, "CREATE INDEX IF NOT EXISTS idx_task_events_queue ON task_events(queue)")
        _run(c, "CREATE INDEX IF NOT EXISTS idx_task_events_finished ON task_events(finished_at)")
        conn.commit()
        conn.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
try:
    from celery_app import celery
except Exception:
    celery = None
from datetime import datetime, timedelta
from collections import defaultdict
from datetime import date
from functools import wraps
from itsdangerous import URLSafeTimedSerializer
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None
    class RealDictCursor: pass
# from config import BASE_URL, FRONTEND_URL # Removed config.py per user request

app = Flask(__name__) 
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_change_this_in_prod')
serializer = URLSafeTimedSerializer(app.secret_key)
Compress(app)

load_dotenv()
# Configuration (Simplified for Render)
# Priority: Env Var > Default
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:5001")
BASE_URL = BACKEND_URL # Alias for compatibility
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")


# Allow specific origins for CORS with credentials
allowed_origins = [
    FRONTEND_URL, 
    "http://localhost:5173", 
    "http://127.0.0.1:5173",
    "https://face-detection-frontend-kepx.onrender.com"
]
CORS(
    app,
    resources={r"/*": {"origins": allowed_origins}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Vendor-ID", "x-vendor-id"],
    expose_headers=["Authorization"]
)

# Initialize SocketIO
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25,
    allow_upgrades=False
)

redis_client = None
try:
    REDIS_URL = os.environ.get("REDIS_URL")
    if REDIS_URL:
        redis_client = redis.from_url(REDIS_URL)
except Exception:
    redis_client = None

# Prometheus metrics
if Counter and Histogram:
    REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["endpoint", "method", "status"])
    REQUEST_LATENCY = Histogram("http_request_latency_seconds", "Request latency", ["endpoint", "method"])
else:
    REQUEST_COUNT = _DummyMetric()
    REQUEST_LATENCY = _DummyMetric()

def track_metrics(endpoint):
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            start = time.time()
            resp = fn(*args, **kwargs)
            dur = time.time() - start
            try:
                status = resp[1] if isinstance(resp, tuple) else 200
            except Exception:
                status = 200
            REQUEST_COUNT.labels(endpoint=endpoint, method=request.method, status=status).inc()
            REQUEST_LATENCY.labels(endpoint=endpoint, method=request.method).observe(dur)
            return resp
        return inner
    return wrapper

def rate_limit(key_func=lambda: request.remote_addr, limit=100, window=60):
    def decorator(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if redis_client:
                key = f"rl:{key_func()}"
                try:
                    pipe = redis_client.pipeline()
                    pipe.incr(key, 1)
                    pipe.expire(key, window)
                    count, _ = pipe.execute()
                    if count and int(count) > limit:
                        return jsonify({"error": "Too Many Requests"}), 429
                except Exception:
                    pass
            return fn(*args, **kwargs)
        return inner
    return decorator

@app.after_request
def add_cors_headers(resp):
    try:
        origin = request.headers.get('Origin')
        if origin in allowed_origins or origin == '*':
            resp.headers['Access-Control-Allow-Origin'] = origin
        else:
            resp.headers['Access-Control-Allow-Origin'] = FRONTEND_URL
        resp.headers['Access-Control-Allow-Credentials'] = 'true'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    except Exception:
        pass
    return resp

@app.route('/socket.io/', methods=['OPTIONS'])
def socketio_preflight():
    return ('', 200)

@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
@socketio.on('join_super_admin')
def handle_join_super_admin():
    try:
        join_room('super_admin')
        return {'status': 'joined', 'room': 'super_admin'}
    except Exception as e:
        return {'error': str(e)}, 500

@socketio.on('join_vendor')
def handle_join_vendor(data=None):
    try:
        vendor_id = None
        if data and isinstance(data, dict):
            vendor_id = data.get('vendor_id')
        if not vendor_id:
            # Attempt to infer from auth token
            auth_header = request.headers.get('Authorization')
            if auth_header:
                try:
                    token = auth_header.split(" ")[1]
                    user_data = verify_token(token)
                    if user_data:
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("SELECT vendor_id FROM system_users WHERE username = ?", (user_data['username'],))
                        row = c.fetchone()
                        conn.close()
                        vendor_id = row[0] if row else None
                except Exception:
                    pass
        if not vendor_id:
            return {'error': 'vendor_id required'}, 400
        join_room(f"vendor_{vendor_id}")
        return {'status': 'joined', 'room': f'vendor_{vendor_id}'}
    except Exception as e:
        return {'error': str(e)}, 500

@socketio.on('join_stream')
def handle_join_stream(data=None):
    try:
        vendor_id = None
        if data and isinstance(data, dict):
            vendor_id = data.get('vendor_id')
        if vendor_id is None:
            return {'error': 'vendor_id required'}, 400
        try:
            vendor_id = int(vendor_id)
        except Exception:
            return {'error': 'invalid vendor_id'}, 400
        join_room(f"stream_{vendor_id}")
        return {'status': 'joined', 'room': f"stream_{vendor_id}"}
    except Exception as e:
        return {'error': str(e)}, 500

@socketio.on('leave_stream')
def handle_leave_stream(data=None):
    try:
        vendor_id = None
        if data and isinstance(data, dict):
            vendor_id = data.get('vendor_id')
        if vendor_id is None:
            return {'error': 'vendor_id required'}, 400
        try:
            vendor_id = int(vendor_id)
        except Exception:
            return {'error': 'invalid vendor_id'}, 400
        leave_room(f"stream_{vendor_id}")
        return {'status': 'left', 'room': f"stream_{vendor_id}"}
    except Exception as e:
        return {'error': str(e)}, 500

@socketio.on('stream_frame')
def handle_stream_frame(data=None):
    try:
        if not data or not isinstance(data, dict):
            return {'error': 'invalid payload'}, 400
        image_data = data.get('image')
        if not image_data:
            return {'error': 'image required'}, 400

        vendor_id = data.get('vendor_id')
        device_id = data.get('device_id') or 'default'
        device_name = data.get('device_name') or f"Device {device_id}"

        try:
            vendor_id = int(vendor_id) if vendor_id is not None else 1
        except Exception:
            vendor_id = 1
        if vendor_id <= 0:
            vendor_id = 1

        if vendor_id not in latest_frames:
            latest_frames[vendor_id] = {}

        latest_frames[vendor_id][str(device_id)] = {
            "data": image_data,
            "timestamp": datetime.now(),
            "source_ip": request.headers.get('X-Forwarded-For', request.remote_addr),
            "device_name": device_name
        }

        payload = {
            "vendor_id": vendor_id,
            "device_id": str(device_id),
            "device_name": device_name,
            "image": image_data
        }
        socketio.emit('frame_update', payload, room=f"stream_{vendor_id}")
        socketio.emit('frame_update', payload, room=f"vendor_{vendor_id}")
        socketio.emit('frame_update', payload, room='super_admin')
        return {'status': 'ok'}
    except Exception as e:
        return {'error': str(e)}, 500

@socketio.on('join_parent')
def handle_join_parent(data=None):
    try:
        parent_id = None
        if data and isinstance(data, dict):
            parent_id = data.get('parent_id')
        if not parent_id:
            auth_header = request.headers.get('Authorization')
            if auth_header:
                try:
                    token = auth_header.split(" ")[1]
                    user_data = verify_token(token)
                    if user_data and user_data.get('role') == 'parent':
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("SELECT id FROM parent_users WHERE username = ?", (user_data['username'],))
                        row = c.fetchone()
                        conn.close()
                        parent_id = row[0] if row else None
                except Exception:
                    pass
        if not parent_id:
            return {'error': 'parent_id required'}, 400
        join_room(f"parent_{parent_id}")
        return {'status': 'joined', 'room': f'parent_{parent_id}'}
    except Exception as e:
        return {'error': str(e)}, 500

@socketio.on('join_student_number')
def handle_join_student_number(data=None):
    try:
        student_number = None
        if data and isinstance(data, dict):
            student_number = str(data.get('student_number') or '').strip()
        if not student_number:
            return {'error': 'student_number required'}, 400
        join_room(f"student_{student_number}")
        try:
            fcm_token = None
            vendor_id = None
            if data and isinstance(data, dict):
                fcm_token = str(data.get('fcm_token') or '').strip()
                vendor_id = data.get('vendor_id')
            if fcm_token:
                conn = get_db_connection()
                c = conn.cursor()
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
                c.execute("""CREATE TABLE IF NOT EXISTS parent_tokens
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              vendor_id INTEGER,
                              student_number TEXT,
                              token TEXT UNIQUE,
                              created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
                if vendor_id:
                    try:
                        c.execute("INSERT OR IGNORE INTO parent_tokens (vendor_id, student_number, token) VALUES (?, ?, ?)", (vendor_id, student_number, fcm_token))
                        conn.commit()
                    except Exception:
                        pass
                conn.close()
        except Exception:
            pass
        return {'status': 'joined', 'room': f'student_{student_number}'}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/auth/status', methods=['GET'])
def auth_status():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT name FROM vendors WHERE id = ?", (vendor_id,))
    vendor = c.fetchone()
    conn.close()
    
    return jsonify({
        "status": "active",
        "vendor_id": vendor_id,
        "vendor_name": vendor['name'] if vendor else "Unknown"
    })

# Expose Config to Frontend
@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        "backend_url": BASE_URL,
        "frontend_url": FRONTEND_URL
    })

@app.route('/api/public/vendors', methods=['GET'])
def public_vendors():
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

@app.route('/api/public/business-types', methods=['GET'])
def public_business_types():
    known = [
        {
            "value": "school",
            "label": "School / College / Tuitions",
            "default_frontend_bundle_id": "attendance_ui",
            "default_registration_config": [
                {"field": "student_number", "label": "Student Number", "type": "text", "required": True, "options": []},
                {"field": "department", "label": "Class/Section", "type": "text", "required": False, "options": []}
            ],
            "allow_parent_login": True
        },
        {
            "value": "wages",
            "label": "Daily Wages / Workforce",
            "default_frontend_bundle_id": "attendance_payroll_ui",
            "default_registration_config": [
                {"field": "daily_wage", "label": "Daily Wage", "type": "text", "required": False, "options": []},
                {"field": "department", "label": "Department", "type": "text", "required": False, "options": []}
            ],
            "allow_parent_login": False
        },
        {
            "value": "factory",
            "label": "Industrial / Manufacturing",
            "default_frontend_bundle_id": "attendance_payroll_ui",
            "default_registration_config": [
                {"field": "employee_id", "label": "Employee ID", "type": "text", "required": False, "options": []},
                {"field": "department", "label": "Department", "type": "text", "required": False, "options": []},
                {"field": "shift", "label": "Shift", "type": "text", "required": False, "options": []}
            ],
            "allow_parent_login": False
        },
        {
            "value": "enterprise",
            "label": "Enterprise (Custom)",
            "default_frontend_bundle_id": "default_attendance",
            "default_registration_config": [],
            "allow_parent_login": False
        }
    ]
    return jsonify({"schema_version": 1, "business_types": known})

# Ensure database is always accessed from the same location (backend directory)
DB_PATH = os.environ.get('DB_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'face_db.sqlite')
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_TYPE = os.environ.get("DB_TYPE")

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

class CompatCursor:
    def __init__(self, conn, cur, is_pg):
        self._conn = conn
        self._cur = cur
        self._is_pg = is_pg
    def execute(self, sql, params=None):
        if params is None:
            params = []
        if self._is_pg:
            sql = _adapt_query_for_pg(sql)
        self._cur.execute(sql, params)
    def executemany(self, sql, seq):
        if self._is_pg:
            sql = _adapt_query_for_pg(sql)
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

def get_db_connection(timeout=30):
    if postgres_available():
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return CompatConn(conn, True)
        except Exception:
            pass
    db_path = DB_PATH
    try:
        import db_factory
        if getattr(db_factory, "DB_PATH", None):
            db_path = db_factory.DB_PATH
    except Exception:
        pass
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _pg_cursor(conn):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    return cur

def _adapt_query_for_pg(sql):
    # naive adapter: replace sqlite '?' placeholders with psycopg2 '%s'
    # works for our usage since queries use '?' consistently
    return sql.replace("?", "%s")

def _run(cur, sql, params=None):
    if params is None:
        params = []
    if isinstance(cur, CompatCursor) and getattr(cur, "_is_pg", False):
        sql = _adapt_query_for_pg(sql)
    cur.execute(sql, params)

def ensure_postgres_schema():
    if not postgres_available():
        return
    conn = get_db_connection()
    if not isinstance(conn, CompatConn):
        try:
            conn.close()
        except Exception:
            pass
        return
    c = conn.cursor()
    try:
        _run(c, """
            CREATE TABLE IF NOT EXISTS system_users (
                username TEXT PRIMARY KEY,
                password TEXT,
                role TEXT,
                vendor_id INTEGER
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS vendors (
                id SERIAL PRIMARY KEY,
                company_name TEXT NOT NULL UNIQUE,
                contact_person TEXT,
                phone TEXT,
                email TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                web_login_enabled INTEGER DEFAULT 1,
                frontend_bundle_id TEXT DEFAULT 'default_attendance',
                backend_service_id TEXT DEFAULT 'default_api',
                config TEXT DEFAULT '{}',
                registration_config TEXT,
                vertical TEXT
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                vendor_id INTEGER UNIQUE,
                plan_type TEXT DEFAULT 'basic',
                start_date DATE,
                end_date DATE,
                grace_period_days INTEGER DEFAULT 7,
                max_users INTEGER DEFAULT 10,
                max_employees INTEGER DEFAULT 50,
                max_mobile_devices INTEGER DEFAULT 1,
                max_web_sessions INTEGER DEFAULT 1,
                cost_per_user REAL DEFAULT 199.0,
                cost_per_employee REAL DEFAULT 50.0,
                setup_fee REAL DEFAULT 0.0,
                setup_fee_paid BOOLEAN DEFAULT FALSE,
                features TEXT DEFAULT '[]'
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY,
                vendor_id INTEGER,
                invoice_date DATE,
                due_date DATE,
                amount REAL,
                status TEXT DEFAULT 'generated',
                details TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS active_sessions (
                token TEXT PRIMARY KEY,
                username TEXT,
                vendor_id INTEGER,
                device_id TEXT,
                platform TEXT,
                last_active TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS faces (
                id SERIAL PRIMARY KEY,
                name TEXT,
                templates TEXT,
                face_image TEXT,
                department TEXT,
                designation TEXT,
                phone TEXT,
                shift TEXT,
                daily_wage REAL DEFAULT 0,
                late_allowance_days INTEGER,
                late_deduction_amount REAL DEFAULT 0,
                vendor_id INTEGER,
                custom_data TEXT
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY,
                name TEXT,
                timestamp TIMESTAMP,
                status TEXT,
                captured_image TEXT,
                activity TEXT,
                is_late INTEGER DEFAULT 0,
                vendor_id INTEGER,
                person_id INTEGER
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS companies (
                id SERIAL PRIMARY KEY,
                name TEXT,
                working_hours REAL DEFAULT 8.0,
                shifts TEXT DEFAULT '[]',
                draft_timetable TEXT DEFAULT '[]',
                live_timetable TEXT DEFAULT '[]',
                last_modified_by TEXT,
                last_modified_at TIMESTAMP,
                published_by TEXT,
                published_at TIMESTAMP,
                vendor_id INTEGER
            )
        """)
        _run(c, "CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_vendor_name ON companies(vendor_id, name)")
        _run(c, """
            CREATE TABLE IF NOT EXISTS parent_users (
                id SERIAL PRIMARY KEY,
                vendor_id INTEGER,
                username TEXT UNIQUE,
                password TEXT,
                contact_email TEXT,
                contact_phone TEXT,
                student_number TEXT,
                selected_person_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        _run(c, """
            CREATE TABLE IF NOT EXISTS student_parents (
                id SERIAL PRIMARY KEY,
                vendor_id INTEGER,
                person_id INTEGER,
                parent_id INTEGER,
                UNIQUE(vendor_id, person_id, parent_id)
            )
        """)
        ensure_archive_table()
        ensure_audit_logs_table()
        ensure_task_events_table()
        add_vendor_devices_table()
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

def ensure_postgres_defaults():
    if not postgres_available():
        return
    conn = get_db_connection()
    if not isinstance(conn, CompatConn):
        try:
            conn.close()
        except Exception:
            pass
        return
    c = conn.cursor()
    try:
        default_settings = {
            "threshold": "0.6",
            "cooldown": "30",
            "work_start_time": "09:00",
            "late_threshold": "09:30",
            "late_grace_period": "15",
            "activity_tolerance": "30",
            "auto_checkout": "false",
            "voice_greeting": "true",
            "admin_alerts": "false",
            "global_late_allowance": "7",
            "global_late_deduction": "0.0"
        }
        for key, val in default_settings.items():
            _run(c, "SELECT 1 FROM system_settings WHERE key = ?", (key,))
            if not c.fetchone():
                _run(c, "INSERT INTO system_settings (key, value) VALUES (?, ?)", (key, val))

        _run(c, "SELECT 1 FROM system_users WHERE username = ?", ('admin',))
        if not c.fetchone():
            _run(c, "INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ('admin', hash_password('admin123'), 'admin', None))
        _run(c, "SELECT 1 FROM system_users WHERE username = ?", ('kiosk',))
        if not c.fetchone():
            _run(c, "INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ('kiosk', hash_password('kiosk123'), 'user', None))
        _run(c, "SELECT 1 FROM system_users WHERE username = ?", ('superadmin',))
        if not c.fetchone():
            _run(c, "INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ('superadmin', hash_password('super123'), 'super_admin', None))

        _run(c, "SELECT 1 FROM companies WHERE name = ? AND vendor_id IS NULL", ('Open Vision',))
        if not c.fetchone():
            _run(c, "INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)", ('Open Vision', '[]', '[]', '[]', None))

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

def bootstrap_db():
    if postgres_available():
        ensure_postgres_schema()
        ensure_postgres_defaults()
        add_performance_indexes()
        return
    init_db()
    migrate_faces_pk()
    add_missing_columns()
    add_vendor_devices_table()
    ensure_archive_table()
    ensure_audit_logs_table()
    ensure_task_events_table()
    add_performance_indexes()

def ensure_archive_table():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Generic archive storage to keep full row snapshots per table
        is_pg = isinstance(conn, CompatConn) and getattr(conn, "_is_pg", False)
        if is_pg:
            _run(c, """
                CREATE TABLE IF NOT EXISTS archive_objects (
                    id SERIAL PRIMARY KEY,
                    vendor_id INTEGER,
                    table_name TEXT,
                    row_json TEXT,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    restored_at TIMESTAMP
                )
            """)
        else:
            _run(c, """
                CREATE TABLE IF NOT EXISTS archive_objects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_id INTEGER,
                    table_name TEXT,
                    row_json TEXT,
                    archived_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    restored_at DATETIME
                )
            """)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

def ensure_audit_logs_table():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = isinstance(conn, CompatConn) and getattr(conn, "_is_pg", False)
        if is_pg:
            _run(c, """
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
            _run(c, """
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
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

def log_audit(action, details=None, target_vendor_id=None, status="success"):
    try:
        ensure_audit_logs_table()
        conn = get_db_connection()
        c = conn.cursor()
        actor_username = None
        actor_role = None
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
        ip = request.remote_addr
        payload = {"status": status}
        if isinstance(details, dict):
            payload.update(details)
        elif isinstance(details, str):
            payload["message"] = details
        _run(c, "INSERT INTO audit_logs (actor_username, actor_role, target_vendor_id, action, details, ip) VALUES (?, ?, ?, ?, ?, ?)",
             (actor_username, actor_role, target_vendor_id, action, json.dumps(payload)))
        conn.commit()
        conn.close()
    except Exception:
        pass
def add_vendor_devices_table():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = isinstance(conn, CompatConn) and getattr(conn, "_is_pg", False)
        if is_pg:
            _run(c, """
                CREATE TABLE IF NOT EXISTS vendor_devices (
                    id SERIAL PRIMARY KEY,
                    vendor_id INTEGER,
                    device_id TEXT,
                    device_name TEXT,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TIMESTAMP,
                    UNIQUE(vendor_id, device_id)
                )
            """)
        else:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vendor_devices'")
            if not c.fetchone():
                print("MIGRATION: Creating vendor_devices table...")
                c.execute('''CREATE TABLE vendor_devices
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              vendor_id INTEGER,
                              device_id TEXT,
                              device_name TEXT,
                              registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                              last_login_at DATETIME,
                              UNIQUE(vendor_id, device_id))''')
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    conn.close()

def add_missing_columns():
    try:
        if postgres_available():
            return
        conn = get_db_connection()
        c = conn.cursor()
        
        # 1. Add is_late to attendance if missing
        try:
            c.execute("ALTER TABLE attendance ADD COLUMN is_late INTEGER DEFAULT 0")
            print("Added column 'is_late' to attendance table.")
        except sqlite3.OperationalError:
            pass # Already exists

        # 2. Add Late Deduction Columns to faces table
        c.execute("PRAGMA table_info(faces)")
        cols = [info[1] for info in c.fetchall()]
        
        if 'late_allowance_days' not in cols:
            print("MIGRATION: Adding late_allowance_days to faces table...")
            c.execute("ALTER TABLE faces ADD COLUMN late_allowance_days INTEGER DEFAULT NULL")
            
        if 'late_deduction_amount' not in cols:
            print("MIGRATION: Adding late_deduction_amount to faces table...")
            c.execute("ALTER TABLE faces ADD COLUMN late_deduction_amount REAL DEFAULT NULL")

        # 3. Add Global Defaults to system_settings
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='system_settings'")
        if c.fetchone():
            c.execute("SELECT key FROM system_settings WHERE key IN ('global_late_allowance', 'global_late_deduction')")
            existing_keys = {row[0] for row in c.fetchall()}
            
            if 'global_late_allowance' not in existing_keys:
                c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", ('global_late_allowance', '7'))
                
            if 'global_late_deduction' not in existing_keys:
                c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", ('global_late_deduction', '0.0'))

        # 4. Add max_mobile_devices to subscriptions
        c.execute("PRAGMA table_info(subscriptions)")
        sub_cols = [info[1] for info in c.fetchall()]
        if 'max_mobile_devices' not in sub_cols:
            print("MIGRATION: Adding max_mobile_devices to subscriptions...")
            c.execute("ALTER TABLE subscriptions ADD COLUMN max_mobile_devices INTEGER DEFAULT 1")
        if 'max_web_sessions' not in sub_cols:
            print("MIGRATION: Adding max_web_sessions to subscriptions...")
            c.execute("ALTER TABLE subscriptions ADD COLUMN max_web_sessions INTEGER DEFAULT 1")
        try:
            c.execute("UPDATE subscriptions SET max_web_sessions = 1 WHERE max_web_sessions IS NULL OR max_web_sessions < 1")
        except Exception:
            pass
            
        if 'max_employees' not in sub_cols:
            print("MIGRATION: Adding max_employees to subscriptions...")
            c.execute("ALTER TABLE subscriptions ADD COLUMN max_employees INTEGER DEFAULT 50")

        if 'cost_per_employee' not in sub_cols:
            print("MIGRATION: Adding cost_per_employee to subscriptions...")
            c.execute("ALTER TABLE subscriptions ADD COLUMN cost_per_employee REAL DEFAULT 0")

        # 5. Create active_sessions table
        c.execute('''CREATE TABLE IF NOT EXISTS active_sessions
                     (token TEXT PRIMARY KEY,
                      username TEXT,
                      vendor_id INTEGER,
                      device_id TEXT,
                      platform TEXT, -- 'web' or 'mobile'
                      last_active DATETIME,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        # 6. Create invoices table if not exists
        c.execute('''CREATE TABLE IF NOT EXISTS invoices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      vendor_id INTEGER,
                      amount REAL,
                      status TEXT DEFAULT 'generated', -- generated, paid, overdue, cancelled
                      due_date DATE,
                      generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                      paid_at DATETIME,
                      FOREIGN KEY(vendor_id) REFERENCES vendors(id))''')

        # 7. Create audit_logs table
        c.execute('''CREATE TABLE IF NOT EXISTS audit_logs
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      actor_username TEXT,
                      action TEXT,
                      target_vendor_id INTEGER,
                      details TEXT, -- JSON string
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        # 7b. Create parent_users and student_parents tables
        c.execute('''CREATE TABLE IF NOT EXISTS parent_users
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      vendor_id INTEGER,
                      username TEXT UNIQUE,
                      password TEXT,
                      contact_email TEXT,
                      contact_phone TEXT,
                      student_number TEXT,
                      selected_person_id INTEGER,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS student_parents
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      vendor_id INTEGER,
                      person_id INTEGER,
                      parent_id INTEGER,
                      UNIQUE(vendor_id, person_id, parent_id))''')
        # 8. Add registration_config to vendors
        c.execute("PRAGMA table_info(vendors)")
        vendor_cols = [info[1] for info in c.fetchall()]
        if 'registration_config' not in vendor_cols:
            print("MIGRATION: Adding registration_config to vendors table...")
            c.execute("ALTER TABLE vendors ADD COLUMN registration_config TEXT DEFAULT NULL") # JSON Schema
        if 'vertical' not in vendor_cols:
            print("MIGRATION: Adding vertical to vendors table...")
            c.execute("ALTER TABLE vendors ADD COLUMN vertical TEXT DEFAULT NULL") # Business vertical: school, industry, hospital

        # 9. Add custom_data to faces
        c.execute("PRAGMA table_info(faces)")
        faces_cols = [info[1] for info in c.fetchall()]
        if 'custom_data' not in faces_cols:
            print("MIGRATION: Adding custom_data to faces table...")
            c.execute("ALTER TABLE faces ADD COLUMN custom_data TEXT DEFAULT NULL") # JSON Values

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Schema Update Error: {e}")
import time
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

# Simple in-memory job registry for async responses
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
def add_performance_indexes():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("CREATE INDEX IF NOT EXISTS idx_system_users_vendor ON system_users(vendor_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_vendor ON subscriptions(vendor_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_vendors_status ON vendors(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_invoices_vendor ON invoices(vendor_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_invoices_overdue ON invoices(vendor_id, status, due_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_faces_vendor ON faces(vendor_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_faces_name ON faces(name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_attendance_vendor ON attendance(vendor_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_attendance_timestamp ON attendance(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_vendor_devices_vendor ON vendor_devices(vendor_id)")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Index Setup Error: {e}")
def check_vendor_status(vendor_id):
    """
    Checks if a vendor is allowed to access the system.
    Returns: (is_allowed, reason)
    """
    if not vendor_id:
        return True, "SuperAdmin"
        
    conn = get_db_connection()
    if not isinstance(conn, CompatConn):
        conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Check Vendor Status
    c.execute("SELECT status FROM vendors WHERE id = ?", (vendor_id,))
    vendor = c.fetchone()
    if not vendor:
        conn.close()
        return False, "Vendor not found"
        
    if vendor['status'] != 'active':
        conn.close()
        return False, "Account Suspended"
        
    # Check Subscription Expiry
    c.execute("SELECT end_date, grace_period_days FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
    sub = c.fetchone()
    
    # Check Overdue Invoices
    # Count invoices that are explicitly 'overdue' OR 'generated' but past their due date
    today = date.today().isoformat()
    c.execute("""
        SELECT COUNT(*) FROM invoices 
        WHERE vendor_id = ? 
        AND (status = 'overdue' OR (status = 'generated' AND due_date < ?))
    """, (vendor_id, today))
    overdue_count = c.fetchone()[0]
    
    conn.close()
    
    if overdue_count > 0:
        return False, "Unpaid Invoices"
    
    if sub and sub['end_date']:
        try:
            # Robust parsing (handle optional time)
            end_date_str = sub['end_date'].split(' ')[0]
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            grace = sub['grace_period_days'] or 0
            limit_date = end_date + timedelta(days=grace)
            
            print(f"DEBUG: Vendor {vendor_id} End Date: {end_date}, Limit: {limit_date}, Today: {date.today()}")

            if date.today() > limit_date:
                return False, "Subscription Expired"
        except ValueError as e:
            print(f"DEBUG: Date Parse Error for Vendor {vendor_id}: {e}")
            return False, "Invalid Date Format"
            
    return True, "Active"

def authenticate_vendor_access():
    """
    Helper to authenticate a vendor admin/user and verify subscription status.
    Returns: (vendor_id, error_response)
    If error_response is not None, return it immediately.
    """
    # auth_header = request.headers.get('Authorization')
    # if not auth_header:
    #     return None, (jsonify({"error": "Missing Authorization Header"}), 401)
    
    try:
        auth_header = request.headers.get('Authorization')
        username = None
        role = None
        
        token = None
        if auth_header:
            try:
                token = auth_header.split(" ")[1]
                user_data = verify_token(token)
                if user_data:
                    username = user_data['username']
                    role = user_data['role']
                    try:
                        conn_s = get_db_connection()
                        cs = conn_s.cursor()
                        cs.execute("UPDATE active_sessions SET last_active = ? WHERE token = ?", (datetime.now(), token))
                        conn_s.commit()
                        conn_s.close()
                    except Exception:
                        try:
                            conn_s.close()
                        except Exception:
                            pass
                else:
                    # Token present but invalid/expired -> Explicit Error
                    return None, (jsonify({"error": "Invalid or Expired Token"}), 401)
            except:
                return None, (jsonify({"error": "Invalid Token Format"}), 401)
        
        # Fallback: Check for token in query params (for file downloads/exports)
        if not username and request.args.get('token'):
            try:
                token = request.args.get('token')
                user_data = verify_token(token)
                if user_data:
                    username = user_data['username']
                    role = user_data['role']
                else:
                    return None, (jsonify({"error": "Invalid or Expired Token"}), 401)
            except:
                pass

        if not username:
            # STRICT MODE: No fallback to 'admin'. Require authentication.
            return None, (jsonify({"error": "Authentication Required"}), 401)

        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT vendor_id, role FROM system_users WHERE username = ?", (username,))
        user = c.fetchone()
        
        conn.close()
        
        if not user:
             return None, (jsonify({"error": "User Not Found"}), 401)

        vendor_id = user['vendor_id']
        # if not vendor_id and user['role'] == 'super_admin':
        #      # SuperAdmin default context
        #      vendor_id = 1 
        
        # SuperAdmin Bypass / Impersonation
        if role == 'super_admin':
            # 1. Check for Explicit Impersonation Header
            impersonate_id = request.headers.get('X-Vendor-ID')
            # 2. Check for Query Param (for GET requests)
            if not impersonate_id:
                impersonate_id = request.args.get('vendor_id')
                
            if impersonate_id:
                try:
                    vendor_id = int(impersonate_id)
                except:
                    pass
            
            # If still no vendor_id, return None (Global Context)
            if not vendor_id:
                pass # Allow Global Context
            
        if not vendor_id and role != 'super_admin':
             return None, (jsonify({"error": "Vendor Context Required"}), 400)
        
        if role == 'super_admin':
            return vendor_id, None
             
        # Skip status checks for now
        is_allowed, reason = check_vendor_status(vendor_id)
        if not is_allowed:
           return None, (jsonify({"error": f"Access Denied: {reason}"}), 403)
            
        return vendor_id, None
        
    except Exception as e:
        return None, (jsonify({"error": str(e)}), 500)


# --- Web Dashboard ---
@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "Face Detection Backend API",
        "version": "1.0.0",
        "message": "Please use the Frontend Application to access the dashboard."
    })

# --- Database Setup ---
def migrate_faces_pk():
    """
    Migrates the faces table to use an Integer ID as Primary Key instead of Name.
    This supports multiple users with the same name.
    """
    if postgres_available():
        return
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    
    try:
        # Check if 'id' column exists
        c.execute("PRAGMA table_info(faces)")
        cols = [info[1] for info in c.fetchall()]
        
        if 'id' not in cols:
            print("MIGRATION: Converting faces table to use ID as Primary Key...")
            
            # 1. Rename old table
            c.execute("ALTER TABLE faces RENAME TO faces_old")
            
            # 2. Create new table with ID
            c.execute('''CREATE TABLE faces
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          name TEXT, 
                          templates TEXT, 
                          face_image TEXT,
                          department TEXT,
                          designation TEXT,
                          phone TEXT,
                          shift TEXT,
                          daily_wage REAL DEFAULT 0,
                          late_allowance_days INTEGER DEFAULT NULL,
                          late_deduction_amount REAL DEFAULT 0,
                          vendor_id INTEGER)''')
                          
            # 3. Copy data
            # We rely on AUTOINCREMENT to generate IDs for existing users
            # Note: We must ensure columns exist in faces_old before selecting them. 
            # init_db() runs before this and ensures columns exist.
            c.execute("""INSERT INTO faces (name, templates, face_image, department, designation, phone, shift, daily_wage, late_allowance_days, late_deduction_amount, vendor_id)
                         SELECT name, templates, face_image, department, designation, phone, shift, daily_wage, late_allowance_days, late_deduction_amount, vendor_id 
                         FROM faces_old""")
            
            print(f"Copied {c.rowcount} rows to new faces table.")
            
            # 4. Backfill person_id in attendance table
            print("Backfilling person_id in attendance table...")
            c.execute("""UPDATE attendance 
                         SET person_id = (SELECT id FROM faces WHERE faces.name = attendance.name AND faces.vendor_id = attendance.vendor_id)
                         WHERE person_id IS NULL""")
                         
            # Fallback for records without vendor_id or legacy
            c.execute("""UPDATE attendance 
                         SET person_id = (SELECT id FROM faces WHERE faces.name = attendance.name LIMIT 1)
                         WHERE person_id IS NULL""")
            
            # 5. Drop old table (Optional: Comment out if you want to keep backup)
            # c.execute("DROP TABLE faces_old")
            
            conn.commit()
            print("MIGRATION: Faces table updated successfully.")
            
    except Exception as e:
        print(f"MIGRATION ERROR: {e}")
        conn.rollback()
    finally:
        conn.close()

def init_db():
    if postgres_available():
        return
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute('''CREATE TABLE IF NOT EXISTS faces
                 (name TEXT PRIMARY KEY, 
                  templates TEXT, 
                  face_image TEXT,
                  department TEXT,
                  designation TEXT,
                  phone TEXT,
                  shift TEXT)''')
    
    # New Table for Attendance
    # Check if captured_image column exists, if not, we might need to recreate or alter
    # For dev simplicity, we'll just ensure the table exists with the new schema if it doesn't.
    # If it exists from previous runs without the column, this CREATE IF NOT EXISTS won't add it.
    # So let's handle migration loosely by checking columns.
    
    c.execute('''CREATE TABLE IF NOT EXISTS attendance
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, 
                  timestamp DATETIME, 
                  status TEXT,
                  captured_image TEXT,
                  activity TEXT,
                  is_late INTEGER DEFAULT 0,
                  vendor_id INTEGER)''') 

    # Table for System Users (Admin/Standard)
    c.execute('''CREATE TABLE IF NOT EXISTS system_users
                 (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
    
    # Check for vendor_id in faces table
    c.execute("PRAGMA table_info(faces)")
    faces_cols = [info[1] for info in c.fetchall()]
    if 'vendor_id' not in faces_cols:
        print("Migrating: Adding vendor_id to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN vendor_id INTEGER")

    # Check for vendor_id in attendance table
    c.execute("PRAGMA table_info(attendance)")
    attendance_columns = [info[1] for info in c.fetchall()]
    if 'vendor_id' not in attendance_columns:
        print("Migrating: Adding vendor_id column to attendance table")
        c.execute("ALTER TABLE attendance ADD COLUMN vendor_id INTEGER")
        # Backfill vendor_id from faces table
        print("Migrating: Backfilling vendor_id in attendance table")
        c.execute("UPDATE attendance SET vendor_id = (SELECT vendor_id FROM faces WHERE faces.name = attendance.name)")

    # Check for person_id in attendance table
    if 'person_id' not in attendance_columns:
        print("Migrating: Adding person_id column to attendance table")
        c.execute("ALTER TABLE attendance ADD COLUMN person_id INTEGER")


    # Check for captured_image column in attendance table and add if missing
    c.execute("PRAGMA table_info(attendance)")
    attendance_columns = [info[1] for info in c.fetchall()]
    if 'captured_image' not in attendance_columns:
        print("Migrating: Adding captured_image column to attendance table")
        c.execute("ALTER TABLE attendance ADD COLUMN captured_image TEXT")

    # Check for extra columns in faces table (department, designation, phone)
    c.execute("PRAGMA table_info(faces)")
    faces_columns = [info[1] for info in c.fetchall()]
    
    if 'department' not in faces_columns:
        print("Migrating: Adding department column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN department TEXT")
        
    if 'designation' not in faces_columns:
        print("Migrating: Adding designation column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN designation TEXT")
        
    if 'phone' not in faces_columns:
        print("Migrating: Adding phone column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN phone TEXT")

    if 'shift' not in faces_columns:
        print("Migrating: Adding shift column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN shift TEXT")

    if 'daily_wage' not in faces_columns:
        print("Migrating: Adding daily_wage column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN daily_wage REAL DEFAULT 0")

    if 'late_allowance_days' not in faces_columns:
        print("Migrating: Adding late_allowance_days column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN late_allowance_days INTEGER DEFAULT NULL")

    if 'late_deduction_amount' not in faces_columns:
        print("Migrating: Adding late_deduction_amount column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN late_deduction_amount REAL DEFAULT 0")

    # Check for activity column in attendance table and add if missing
    c.execute("PRAGMA table_info(attendance)")
    attendance_columns = [info[1] for info in c.fetchall()]
    if 'activity' not in attendance_columns:
        print("Migrating: Adding activity column to attendance table")
        c.execute("ALTER TABLE attendance ADD COLUMN activity TEXT")

    if 'is_late' not in attendance_columns:
        print("Migrating: Adding is_late column to attendance table")
        c.execute("ALTER TABLE attendance ADD COLUMN is_late INTEGER DEFAULT 0")

    # --- New Table for Companies & Timetables ---
    c.execute('''CREATE TABLE IF NOT EXISTS companies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT UNIQUE, 
                  shifts TEXT,
                  draft_timetable TEXT, 
                  live_timetable TEXT,
                  last_modified_by TEXT,
                  last_modified_at DATETIME,
                  published_by TEXT,
                  published_at DATETIME)''')

    # Check for working_hours in companies table
    c.execute("PRAGMA table_info(companies)")
    companies_columns = [info[1] for info in c.fetchall()]
    if 'working_hours' not in companies_columns:
        print("Migrating: Adding working_hours column to companies table")
        c.execute("ALTER TABLE companies ADD COLUMN working_hours REAL DEFAULT 8.0")

    # Create default admin if not exists
    c.execute("SELECT * FROM system_users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)", 
                  ('admin', hash_password('admin123'), 'admin'))

    # Create default kiosk user if not exists
    c.execute("SELECT * FROM system_users WHERE username = 'kiosk'")
    if not c.fetchone():
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)", 
                  ('kiosk', hash_password('kiosk123'), 'user'))

    # Create default superadmin if not exists
    c.execute("SELECT * FROM system_users WHERE username = 'superadmin'")
    if not c.fetchone():
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)", 
                  ('superadmin', hash_password('super123'), 'super_admin'))

    # Check for vendor_id in system_users table
    c.execute("PRAGMA table_info(system_users)")
    system_users_columns = [info[1] for info in c.fetchall()]
    if 'vendor_id' not in system_users_columns:
        print("Migrating: Adding vendor_id column to system_users table")
        c.execute("ALTER TABLE system_users ADD COLUMN vendor_id INTEGER")

    # Create default company if not exists
    c.execute("SELECT * FROM companies WHERE name = 'Open Vision'")
    if not c.fetchone():
        # Initialize with empty JSON array for timetables and shifts
        c.execute("INSERT INTO companies (name, shifts, draft_timetable, live_timetable) VALUES (?, ?, ?, ?)", 
                  ('Open Vision', '[]', '[]', '[]'))
    
    # Check for shifts column in companies table and add if missing
    c.execute("PRAGMA table_info(companies)")
    companies_columns = [info[1] for info in c.fetchall()]
    if 'shifts' not in companies_columns:
        print("Migrating: Adding shifts column to companies table")
        c.execute("ALTER TABLE companies ADD COLUMN shifts TEXT DEFAULT '[]'")

    if 'vendor_id' not in companies_columns:
        print("Migrating: Adding vendor_id column to companies table")
        c.execute("ALTER TABLE companies ADD COLUMN vendor_id INTEGER")
        # Link existing company (id=1) to first vendor (id=1) if exists, or just leave null
        # For simplicity, let's assume legacy company is vendor 1 if we are migrating
        # c.execute("UPDATE companies SET vendor_id = 1 WHERE id = 1") 

    # --- New Table for System Settings ---
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
                 
    # Default Settings
    default_settings = {
        "threshold": "0.6",
        "cooldown": "30",
        "work_start_time": "09:00",
        "late_threshold": "09:30",
        "late_grace_period": "15",
        "activity_tolerance": "30",
        "auto_checkout": "false",
        "voice_greeting": "true",
        "admin_alerts": "false"
    }
    
    for key, val in default_settings.items():
        c.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (key, val))

    # --- SaaS Tables ---
    # Vendors Table
    c.execute('''CREATE TABLE IF NOT EXISTS vendors
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  company_name TEXT NOT NULL UNIQUE, 
                  contact_person TEXT, 
                  phone TEXT, 
                  email TEXT,
                  status TEXT DEFAULT 'active', -- active, suspended, expired
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Subscriptions Table
    c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  vendor_id INTEGER, 
                  plan_type TEXT DEFAULT 'basic',
                  start_date DATE, 
                  end_date DATE, 
                  grace_period_days INTEGER DEFAULT 7,
                  max_users INTEGER DEFAULT 10,
                  max_employees INTEGER DEFAULT 50,
                  max_mobile_devices INTEGER DEFAULT 5,
                  cost_per_user REAL DEFAULT 199.0,
                  cost_per_employee REAL DEFAULT 50.0,
                  setup_fee REAL DEFAULT 0.0,
                  setup_fee_paid BOOLEAN DEFAULT 0,
                  features TEXT DEFAULT '[]',
                  FOREIGN KEY(vendor_id) REFERENCES vendors(id))''')

    # Check for features column in subscriptions table (Migration)
    c.execute("PRAGMA table_info(subscriptions)")
    subs_columns = [info[1] for info in c.fetchall()]
    if 'features' not in subs_columns:
        print("Migrating: Adding features column to subscriptions table")
        c.execute("ALTER TABLE subscriptions ADD COLUMN features TEXT DEFAULT '[]'")
    
    # Backfill legacy features (Fix for Access Denied issue)
    # NOTE: This runs on every startup to ensure legacy vendors don't get locked out.
    # In a future version, once all data is migrated, this should be removed or moved to a proper migration script.
    c.execute("UPDATE subscriptions SET features = ? WHERE features IS NULL OR features = '[]' OR features = ''", 
              (json.dumps(['reports', 'mobile_app', 'payroll', 'shifts']),))

    # Check for max_employees and max_mobile_devices (Migration)
    if 'max_employees' not in subs_columns:
        print("Migrating: Adding max_employees column to subscriptions table")
        c.execute("ALTER TABLE subscriptions ADD COLUMN max_employees INTEGER DEFAULT 50")
    if 'max_mobile_devices' not in subs_columns:
        print("Migrating: Adding max_mobile_devices column to subscriptions table")
        c.execute("ALTER TABLE subscriptions ADD COLUMN max_mobile_devices INTEGER DEFAULT 5")
    if 'cost_per_employee' not in subs_columns:
        print("Migrating: Adding cost_per_employee column to subscriptions table")
        c.execute("ALTER TABLE subscriptions ADD COLUMN cost_per_employee REAL DEFAULT 50.0")

    # Invoices Table
    c.execute('''CREATE TABLE IF NOT EXISTS invoices
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  vendor_id INTEGER, 
                  invoice_date DATE, 
                  due_date DATE,
                  amount REAL,
                  status TEXT DEFAULT 'generated', -- generated, paid, overdue
                  details TEXT, -- JSON breakdown
                  FOREIGN KEY(vendor_id) REFERENCES vendors(id))''')

    # --- Migrations for SaaS Tables (Ensure columns exist if table was created previously) ---
    
    # Subscriptions Migration
    c.execute("PRAGMA table_info(subscriptions)")
    sub_cols = [info[1] for info in c.fetchall()]
    
    if 'plan_type' not in sub_cols:
         print("Migrating: Adding plan_type to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN plan_type TEXT DEFAULT 'basic'")
    if 'start_date' not in sub_cols:
         print("Migrating: Adding start_date to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN start_date DATE")
    if 'end_date' not in sub_cols:
         print("Migrating: Adding end_date to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN end_date DATE")
    if 'grace_period_days' not in sub_cols:
         print("Migrating: Adding grace_period_days to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN grace_period_days INTEGER DEFAULT 7")
    if 'max_users' not in sub_cols:
         print("Migrating: Adding max_users to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN max_users INTEGER DEFAULT 10")
    if 'max_employees' not in sub_cols:
         print("Migrating: Adding max_employees to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN max_employees INTEGER DEFAULT 50")
    if 'max_mobile_devices' not in sub_cols:
         print("Migrating: Adding max_mobile_devices to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN max_mobile_devices INTEGER DEFAULT 1")
    if 'cost_per_user' not in sub_cols:
         print("Migrating: Adding cost_per_user to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN cost_per_user REAL DEFAULT 199.0")
    if 'setup_fee' not in sub_cols:
         print("Migrating: Adding setup_fee to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN setup_fee REAL DEFAULT 0.0")
    if 'setup_fee_paid' not in sub_cols:
         print("Migrating: Adding setup_fee_paid to subscriptions")
         c.execute("ALTER TABLE subscriptions ADD COLUMN setup_fee_paid BOOLEAN DEFAULT 0")

    # Vendors Migration
    c.execute("PRAGMA table_info(vendors)")
    vendor_cols = [info[1] for info in c.fetchall()]
    
    if 'name' in vendor_cols and 'company_name' not in vendor_cols:
        print("Migrating: Renaming vendors.name to vendors.company_name")
        try:
            c.execute("ALTER TABLE vendors RENAME COLUMN name TO company_name")
        except Exception as e:
            print(f"Migration Error (Rename): {e}")
            
    if 'contact_person' not in vendor_cols:
        print("Migrating: Adding contact_person to vendors")
        c.execute("ALTER TABLE vendors ADD COLUMN contact_person TEXT")

    if 'web_login_enabled' not in vendor_cols:
        print("Migrating: Adding web_login_enabled to vendors")
        c.execute("ALTER TABLE vendors ADD COLUMN web_login_enabled INTEGER DEFAULT 1")

    if 'frontend_bundle_id' not in vendor_cols:
        print("Migrating: Adding frontend_bundle_id to vendors")
        c.execute("ALTER TABLE vendors ADD COLUMN frontend_bundle_id TEXT DEFAULT 'default_attendance'")

    if 'backend_service_id' not in vendor_cols:
        print("Migrating: Adding backend_service_id to vendors")
        c.execute("ALTER TABLE vendors ADD COLUMN backend_service_id TEXT DEFAULT 'default_api'")

    if 'config' not in vendor_cols:
        print("Migrating: Adding config to vendors")
        c.execute("ALTER TABLE vendors ADD COLUMN config TEXT DEFAULT '{}'")

    # Update system_users for multi-tenancy
    c.execute("PRAGMA table_info(system_users)")
    user_cols = [info[1] for info in c.fetchall()]
    if 'vendor_id' not in user_cols:
        print("Migrating: Adding vendor_id to system_users")
        c.execute("ALTER TABLE system_users ADD COLUMN vendor_id INTEGER")
    
    # Create SuperAdmin User
    c.execute("SELECT * FROM system_users WHERE role = 'super_admin'")
    if not c.fetchone():
        # Default SuperAdmin: admin@trae.com / admin123
        c.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", 
                  ('superadmin', hash_password('admin123'), 'super_admin', None))

    conn.commit()
    conn.close()

# --- Auth Helper & Decorators ---
import uuid

def generate_token(username, role):
    # Add a random nonce to ensure uniqueness even within the same second
    return serializer.dumps({'username': username, 'role': role, 'nonce': str(uuid.uuid4())})

def hash_password(raw_password):
    return generate_password_hash(str(raw_password))

def verify_password(raw_password, stored_password):
    if stored_password is None:
        return False
    raw_password = str(raw_password)
    stored_password = str(stored_password)
    if raw_password == stored_password:
        return True
    try:
        return check_password_hash(stored_password, raw_password)
    except Exception:
        return False

def verify_token(token):
    try:
        data = serializer.loads(token, max_age=86400) # Valid for 1 day
        return data
    except:
        return None

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            return jsonify({}), 200

        # Enable Auth Check
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Missing Authorization Header"}), 401
        
        try:
            token = auth_header.split(" ")[1]
            data = verify_token(token)
            if not data:
                return jsonify({"error": "Invalid or Expired Token"}), 401
            
            # Verify User Exists in DB (Auto-Logout if deleted)
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT role FROM system_users WHERE username = ?", (data['username'],))
            user_row = c.fetchone()
            conn.close()

            if not user_row:
                return jsonify({"error": "User Not Found"}), 401

            if data['role'] != 'super_admin':
                return jsonify({"error": "Super Admin Access Required"}), 403
                
        except IndexError:
             return jsonify({"error": "Invalid Token Format"}), 401
             
        return f(*args, **kwargs)
    return decorated_function

def require_feature(feature_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if request.method == 'OPTIONS':
                return jsonify({}), 200

            # 1. Authenticate & Get Vendor ID
            vendor_id, error = authenticate_vendor_access()
            if error: return error
            
            # 2. Check Feature (Only for Vendor Context)
            if vendor_id:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
                row = c.fetchone()
                conn.close()
                
                has_feature = False
                if row and row[0]:
                    try:
                        import json
                        features = json.loads(row[0])
                        if feature_name in features:
                            has_feature = True
                    except:
                        pass
                
                if not has_feature:
                     return jsonify({"error": f"Feature '{feature_name}' is not enabled for your plan."}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def vendor_has_feature(vendor_id, feature_name):
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
        try:
            conn.close()
        except Exception:
            pass
        return False

greeting_bp = Blueprint("greeting", __name__, url_prefix="/api")

def log_audit(actor_username, action, target_vendor_id=None, details=None):
    """
    Helper to log system events.
    """
    try:
        conn = get_db_connection()
        c = conn.cursor()
        import json
        details_json = json.dumps(details) if details else None
        c.execute("INSERT INTO audit_logs (actor_username, action, target_vendor_id, details) VALUES (?, ?, ?, ?)",
                  (actor_username, action, target_vendor_id, details_json))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Audit Log Error: {e}")

def get_current_actor():
    try:
        auth_header = request.headers.get('Authorization')
        if auth_header:
            token = auth_header.split(" ")[1]
            data = verify_token(token)
            return data['username']
    except:
        pass
    return 'system'

@greeting_bp.route("/admin/audit-logs", methods=["GET"])
@super_admin_required
def get_audit_logs():
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

@greeting_bp.route("/admin/impersonate", methods=["POST"])
@super_admin_required
def impersonate_vendor():
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
        
    log_audit(actor, 'impersonate_vendor', vendor_id, {'impersonated_user': user['username']})
    
    return jsonify({
        "token": token,
        "username": user['username'],
        "role": user['role']
    })

# --- Company & Timetable Endpoints ---

@greeting_bp.route("/vendor/subscription", methods=["GET"])
def get_vendor_subscription():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    if not vendor_id:
         return jsonify({"error": "No vendor context"}), 400

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
    if sub_dict.get('end_date'):
        try:
            end_date_str = str(sub_dict['end_date']).split(' ')[0]
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            days_left = (end_date - date.today()).days
        except Exception:
            days_left = 0
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
    
    return jsonify(sub_dict)

@greeting_bp.route("/companies", methods=["GET"])
def get_companies():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

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

@greeting_bp.route("/companies", methods=["POST"])
def create_company():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
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

@greeting_bp.route("/companies/<int:company_id>", methods=["PUT"])
def update_company_settings(company_id):
    vendor_id, error = authenticate_vendor_access()
    if error: return error

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
                    import json
                    feats = json.loads(sub_row[0])
                    if "shifts" in feats:
                        has_shifts = True
                except:
                    pass
            
            if not has_shifts:
                conn.close()
                return jsonify({"error": "Feature 'shifts' is not enabled for your plan."}), 403

        import json
        if isinstance(shifts, list):
            shifts = json.dumps(shifts)
        c.execute("UPDATE companies SET shifts = ? WHERE id = ?", (shifts, company_id))
    
    if working_hours is not None:
        c.execute("UPDATE companies SET working_hours = ? WHERE id = ?", (working_hours, company_id))

    conn.commit()
    conn.close()
    return jsonify({"success": True})

@greeting_bp.route("/companies/<int:company_id>", methods=["GET"])
def get_company_details(company_id):
    vendor_id, error = authenticate_vendor_access()
    if error: return error

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
    import json
    for key in ['shifts', 'draft_timetable', 'live_timetable']:
        if data.get(key):
            try:
                data[key] = json.loads(data[key])
            except:
                data[key] = []
    return jsonify(data)

@greeting_bp.route("/companies/<int:company_id>/draft", methods=["PUT"])
@require_feature("shifts")
def update_draft_timetable(company_id):
    vendor_id, error = authenticate_vendor_access()
    if error: return error

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

    import json
    if isinstance(draft_timetable, list):
        draft_timetable = json.dumps(draft_timetable)

    c.execute("""UPDATE companies 
                 SET draft_timetable = ?, last_modified_by = ?, last_modified_at = ? 
                 WHERE id = ?""", 
              (draft_timetable, modified_by, datetime.now(), company_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@greeting_bp.route("/companies/<int:company_id>/publish", methods=["POST"])
@require_feature("shifts")
def publish_timetable(company_id):
    vendor_id, error = authenticate_vendor_access()
    if error: return error

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

@greeting_bp.route("/admin/users/password", methods=["PUT"])
@super_admin_required
def reset_user_password():
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

# --- SuperAdmin Endpoints ---

@greeting_bp.route("/admin/stats", methods=["GET"])
@super_admin_required
def get_admin_stats():
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

@greeting_bp.route("/admin/vendors", methods=["GET"])
@super_admin_required
def get_vendors():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get Vendors with Subscription Details
    c.execute("""
        SELECT v.*, 
               s.plan_type, s.start_date, s.end_date, s.max_users, s.max_employees, s.max_mobile_devices, s.max_web_sessions, s.cost_per_user, s.cost_per_employee, s.setup_fee, s.setup_fee_paid, s.features,
               (SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'vendor_admin' LIMIT 1) as admin_username,
               (SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'user' LIMIT 1) as user_username,
               (SELECT COUNT(*) FROM system_users WHERE vendor_id = v.id AND role = 'vendor_admin') as admin_count,
               (SELECT COUNT(*) FROM vendor_devices WHERE vendor_id = v.id) as device_count,
               (SELECT COUNT(*) FROM faces WHERE vendor_id = v.id) as employee_count
        FROM vendors v
        LEFT JOIN subscriptions s ON v.id = s.vendor_id
        ORDER BY v.created_at DESC
    """)
    
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
                print(f"Date Parsing Error for Vendor {v.get('id')}: {e}")
                v['subscription_status'] = 'Error'
        else:
            v['subscription_status'] = 'No Plan'
            
        vendors.append(v)
        
    conn.close()
    return jsonify({"vendors": vendors})

# Feature Mapping based on Frontend Bundles
BUNDLE_FEATURES = {
    'attendance_ui': ['reports', 'report_detailed', 'mobile_app', 'live_attendance', 'cameras', 'enable_attendance', 'geofencing'],
    'attendance_payroll_ui': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts'],
    'enterprise_custom_ui': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts', 'api_access', 'white_labeling'],
    'default_attendance': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing']
}

ALL_FEATURES = ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts', 'api_access', 'white_labeling', 'late_mark']

@greeting_bp.route("/admin/features", methods=["GET"])
@super_admin_required
def get_available_features():
    return jsonify({"features": ALL_FEATURES, "bundles": BUNDLE_FEATURES})

# Registration templates by vertical
REGISTRATION_TEMPLATES = {
    "school": [
        {"field": "student_number", "label": "Student Number", "enabled": True},
        {"field": "class_section", "label": "Class/Section", "enabled": True},
        {"field": "father_name", "label": "Father's Name", "enabled": True}
    ],
    "factory": [
        {"field": "employee_id", "label": "Employee ID", "enabled": True},
        {"field": "department", "label": "Department", "enabled": True},
        {"field": "shift", "label": "Shift", "enabled": True}
    ],
    "retail": [
        {"field": "employee_id", "label": "Employee ID", "enabled": True},
        {"field": "store", "label": "Store", "enabled": True},
        {"field": "designation", "label": "Designation", "enabled": True}
    ]
}

@greeting_bp.route("/admin/registration/templates", methods=["GET"])
@super_admin_required
def get_registration_templates():
    return jsonify({"templates": REGISTRATION_TEMPLATES})

@greeting_bp.route("/admin/vendors/<int:vendor_id>/registration_config", methods=["PUT"])
@super_admin_required
def set_vendor_registration_config(vendor_id):
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

@greeting_bp.route("/admin/vendors/bulk_action", methods=["POST"])
@super_admin_required
def bulk_vendor_action():
    payload = request.json or {}
    vendor_ids = payload.get("vendor_ids") or []
    action = payload.get("action")
    if not vendor_ids or not action:
        return jsonify({"error": "vendor_ids and action required"}), 400
    try:
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
        elif action == "update_web_sessions":
            max_web_sessions = int(payload.get("max_web_sessions") or 1)
            if max_web_sessions < 1:
                max_web_sessions = 1
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

@greeting_bp.route("/admin/vendors/<int:vendor_id>/employees/export", methods=["GET"])
@super_admin_required
def export_employees(vendor_id):
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

@greeting_bp.route("/admin/vendors/<int:vendor_id>/employees/import", methods=["POST"])
@super_admin_required
def import_employees(vendor_id):
    import csv, io
    data = request.json or {}
    csv_data = data.get("csv_data")
    if not csv_data:
        return jsonify({"error": "csv_data required (string)"}), 400
    f = io.StringIO(csv_data)
    reader = csv.DictReader(f)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        count = 0
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
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
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/admin/vendors", methods=["POST"], endpoint="admin_create_vendor")
@super_admin_required
@track_metrics("admin_create_vendor")
@rate_limit(limit=60, window=60)
def create_vendor():
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
                c2.execute("""INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, max_web_sessions, cost_per_user, cost_per_employee, setup_fee, features)
                              VALUES (?, 'custom', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                           (vendor_id, start_date, end_date, max_users, max_employees, max_mobile_devices, max_web_sessions, cost_per_user, cost_per_employee, features_json))
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
                log_audit(get_current_actor(), 'create_vendor', vendor_id, {'company_name': company_name})
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
                eventlet.spawn_n(_process)
        else:
            eventlet.spawn_n(_process)
        return jsonify({
            "success": True, 
            "vendor_id": vendor_id,
            "admin_credentials": {"username": admin_username, "password": admin_password},
            "user_credentials": {"username": user_username, "password": user_password},
            "processing": True
        })
        
    except sqlite3.IntegrityError as e:
        return jsonify({"error": f"Database Error: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/admin/vendors/<int:vendor_id>/suspend", methods=["POST"])
@super_admin_required
def suspend_vendor(vendor_id):
    data = request.json
    action = data.get("action", "suspend") # suspend or activate
    status = 'suspended' if action == 'suspend' else 'active'
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE vendors SET status = ? WHERE id = ?", (status, vendor_id))
    conn.commit()
    conn.close()
    
    log_audit(get_current_actor(), 'suspend_vendor' if action == 'suspend' else 'activate_vendor', vendor_id, {'new_status': status})
    
    # Real-time updates
    socketio.emit('vendor_updated', {'vendor_id': vendor_id, 'status': status}) # For SuperAdmin list
    
    if status == 'suspended':
        socketio.emit('force_logout', {'vendor_id': vendor_id}) # For Vendor Dashboard

    return jsonify({"success": True, "status": status})

@greeting_bp.route("/admin/vendors/<int:vendor_id>/toggle_web_login", methods=["POST"])
@super_admin_required
def toggle_web_login(vendor_id):
    data = request.json
    enabled = data.get("enabled", True) # boolean
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE vendors SET web_login_enabled = ? WHERE id = ?", (1 if enabled else 0, vendor_id))
    conn.commit()
    conn.close()
    
    log_audit(get_current_actor(), 'toggle_web_login', vendor_id, {'enabled': enabled})
    
    socketio.emit('vendor_updated', {'vendor_id': vendor_id, 'web_login_enabled': enabled})
    
    if not enabled:
        socketio.emit('force_logout', {'vendor_id': vendor_id})

    return jsonify({"success": True, "enabled": enabled})


@greeting_bp.route("/admin/vendors/<int:vendor_id>/subscription", methods=["GET"])
@super_admin_required
def get_vendor_subscription_admin(vendor_id):
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

@greeting_bp.route("/admin/vendors/<int:vendor_id>/subscription", methods=["PUT"])
@super_admin_required
def update_vendor_subscription(vendor_id):
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
            c.execute("""INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, max_web_sessions, cost_per_user, cost_per_employee, setup_fee, features)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, max_web_sessions, cost_per_user, cost_per_employee, setup_fee, features_val))
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
             
        if params:
            query = query.rstrip(", ") + " WHERE vendor_id = ?"
            params.append(vendor_id)
            c.execute(query, params)
            conn.commit()
            
            # Log Audit
            log_audit(get_current_actor(), 'update_subscription', vendor_id, data)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/admin/vendors/<int:vendor_id>/registration-config", methods=["GET"])
def get_vendor_registration_config(vendor_id):
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
        c.execute("SELECT registration_config FROM vendors WHERE id = ?", (vendor_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Vendor not found"}), 404
        
        config = row[0]
        if config:
            return jsonify({"config": json.loads(config)})
        else:
            return jsonify({"config": None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/admin/vendors/<int:vendor_id>/registration-config", methods=["PUT"])
@super_admin_required
def update_vendor_registration_config(vendor_id):
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
        log_audit(get_current_actor(), 'update_registration_config', vendor_id, data)
        
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@greeting_bp.route("/admin/vendors/<int:vendor_id>", methods=["PUT"])
@super_admin_required
def update_vendor_details(vendor_id):
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

@greeting_bp.route("/admin/vendors/<int:vendor_id>", methods=["DELETE"])
@super_admin_required
def delete_vendor(vendor_id):
    ensure_archive_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Check vendor
        _run(c, "SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        vendor_row = c.fetchone()
        if not vendor_row:
            log_audit("vendor_delete", {"error": "Not Found"}, target_vendor_id=vendor_id, status="failed")
            return jsonify({"error": "Vendor not found"}), 404
        # Helper to archive rows from table by vendor_id
        def archive_table(table, key="vendor_id"):
            _run(c, f"SELECT * FROM {table} WHERE {key} = ?", (vendor_id,))
            cols = None
            rows = []
            try:
                if hasattr(c, "description") and c.description:
                    cols = [d[0] for d in c.description]
                fetched = c.fetchall()
                for r in fetched:
                    if isinstance(r, dict):
                        rows.append(r)
                    else:
                        rows.append({cols[i]: r[i] for i in range(len(cols))})
            except Exception:
                return
            for row in rows:
                _run(c, "INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES (?, ?, ?)", (vendor_id, table, json.dumps(row)))
        # Archive each related table
        archive_table("subscriptions")
        archive_table("invoices")
        archive_table("system_users")
        archive_table("companies")
        archive_table("faces")
        archive_table("attendance")
        archive_table("active_sessions")
        # Archive vendor itself
        # Convert vendor_row to dict
        vdict = None
        if isinstance(vendor_row, dict):
            vdict = vendor_row
        else:
            cols = [d[0] for d in c.description] if hasattr(c, "description") and c.description else []
            try:
                vdict = {cols[i]: vendor_row[i] for i in range(len(cols))}
            except Exception:
                vdict = {"id": vendor_id}
        _run(c, "INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES (?, ?, ?)", (vendor_id, "vendors", json.dumps(vdict)))
        # Hard delete live rows
        _run(c, "DELETE FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        _run(c, "DELETE FROM invoices WHERE vendor_id = ?", (vendor_id,))
        _run(c, "DELETE FROM system_users WHERE vendor_id = ?", (vendor_id,))
        _run(c, "DELETE FROM companies WHERE vendor_id = ?", (vendor_id,))
        _run(c, "DELETE FROM faces WHERE vendor_id = ?", (vendor_id,))
        _run(c, "DELETE FROM attendance WHERE vendor_id = ?", (vendor_id,))
        _run(c, "DELETE FROM active_sessions WHERE vendor_id = ?", (vendor_id,))
        _run(c, "DELETE FROM vendors WHERE id = ?", (vendor_id,))
        conn.commit()
        log_audit("vendor_delete", {"message": "Archived and deleted"}, target_vendor_id=vendor_id, status="success")
        return jsonify({"success": True, "message": "Vendor archived and deleted from live data"})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        log_audit("vendor_delete", {"error": str(e)}, target_vendor_id=vendor_id, status="failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# --- Billing & Invoices ---
@greeting_bp.route("/admin/vendors/<int:vendor_id>/invoices", methods=["GET"])
@super_admin_required
def get_vendor_invoices(vendor_id):
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

@greeting_bp.route("/admin/archive/vendors", methods=["GET"])
@super_admin_required
def list_archived_vendors():
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

@greeting_bp.route("/admin/audit-logs", methods=["GET"])
@super_admin_required
def list_audit_logs():
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

@greeting_bp.route("/admin/vendors/<int:vendor_id>/invoices/generate", methods=["POST"])
@super_admin_required
def generate_invoice(vendor_id):
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

@greeting_bp.route("/admin/invoices/<int:invoice_id>/status", methods=["PUT"])
@super_admin_required
def update_invoice_status(invoice_id):
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

@greeting_bp.route("/admin/system/health", methods=["GET"])
@super_admin_required
def system_health():
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

@greeting_bp.route("/admin/system/queues", methods=["GET"])
@super_admin_required
def system_queues():
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
@greeting_bp.route("/admin/jobs/events", methods=["GET"])
@super_admin_required
def list_task_events():
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
@greeting_bp.route("/admin/jobs/events/purge", methods=["POST"])
@super_admin_required
def purge_task_events():
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
@greeting_bp.route("/admin/jobs/metrics", methods=["GET"])
@super_admin_required
def jobs_metrics():
    ensure_task_events_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        window_minutes = int(request.args.get("window_minutes") or 60)
        bucket = request.args.get("bucket") or "minute"
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
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
@greeting_bp.route("/admin/vendors/restore", methods=["POST"])
@super_admin_required
def restore_vendor():
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

# --- Vendor Portal Endpoints ---
@greeting_bp.route("/vendor/invoices", methods=["GET"])
def get_my_invoices():
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


@greeting_bp.route("/reports/analytics", methods=["GET"])
@require_feature("reports")
def get_analytics():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    if not vendor_id: return jsonify({"error": "Vendor context required"}), 400

    import json
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
            print(f"Error checking is_late column: {e}")

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
                for act in day_acts:
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

@greeting_bp.route("/reports/export", methods=["GET"])
@require_feature("reports")
def export_report():
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

    STANDARD_PERSON_FIELDS = {"department", "designation", "shift", "phone"}
    enabled_fields = []
    standard_fields = []
    dynamic_fields = []
    if vendor_id:
        c.execute("SELECT registration_config FROM vendors WHERE id = ?", (vendor_id,))
        row = c.fetchone()
        enabled_fields = normalize_registration_config(row['registration_config'] if row else None)
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
        # --- Summary / Payroll Report ---
        
        # 1. Fetch Company Settings (Working Hours & Timetable)
        if vendor_id:
            c.execute("SELECT live_timetable, working_hours FROM companies WHERE vendor_id = ?", (vendor_id,))
            company_row = c.fetchone()
        else:
            # Require Vendor Context for safety
            return jsonify({"error": "Vendor context required for export"}), 400

        timetable = []
        company_working_hours = 8.0 # Default
        if company_row:
            if company_row['live_timetable']:
                try:
                    timetable = json.loads(company_row['live_timetable'])
                except:
                    timetable = []
            if company_row['working_hours']:
                company_working_hours = float(company_row['working_hours'])


        # 2. Fetch Persons (with filters applied if needed, but usually we want all for payroll)
        # Apply filters to faces query
        faces_query = "SELECT name, daily_wage, department, designation, shift, phone, custom_data FROM faces WHERE 1=1"
        faces_params = []
        
        if vendor_id:
            faces_query += " AND vendor_id = ?"
            faces_params.append(vendor_id)

        if department:
            faces_query += " AND department = ?"
            faces_params.append(department)
        if designation:
            faces_query += " AND designation = ?"
            faces_params.append(designation)
        if shift:
            faces_query += " AND shift = ?"
            faces_params.append(shift)
        if phone:
            faces_query += " AND phone = ?"
            faces_params.append(phone)
            
        c.execute(faces_query, faces_params)
        persons_raw = c.fetchall()
        persons = {}
        for row in persons_raw:
            row_dict = dict(row)
            if dynamic_filters:
                match = True
                custom_data = {}
                if row_dict.get('custom_data'):
                    try:
                        import json
                        custom_data = json.loads(row_dict['custom_data'])
                    except Exception:
                        custom_data = {}
                for dk, dv in dynamic_filters.items():
                    val = custom_data.get(dk)
                    if val is None:
                        fallback_key = None
                        for f in dynamic_fields:
                            if f['key'] == dk:
                                fallback_key = f['label']
                                break
                        if fallback_key:
                            val = custom_data.get(fallback_key)
                    if str(val) != str(dv):
                        match = False
                        break
                if not match:
                    continue
            persons[row['name']] = row_dict
        
        # 3. Fetch Attendance for the period (BUFFERED for Overnight Shifts)
        # We fetch Start-1 to End+1 to capture cross-midnight shifts
        start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
        
        buffer_start = (start_dt - timedelta(days=1)).strftime('%Y-%m-%d')
        buffer_end = (end_dt + timedelta(days=1)).strftime('%Y-%m-%d')

        placeholders = ','.join(['?'] * len(persons))
        if not persons:
            rows = []
        else:
            query = f"""
                SELECT * FROM attendance 
                WHERE date(timestamp) BETWEEN ? AND ?
                AND name IN ({placeholders})
                ORDER BY timestamp ASC
            """
            params = [buffer_start, buffer_end] + list(persons.keys())
            c.execute(query, params)
            rows = c.fetchall()
            
        conn.close()
        
        # Group records with Smart Logic (Continuous Stream)
        user_date_records = defaultdict(list)
        user_pending_date = {} # Track "Active Day" for each user {name: date_str}

        # First, organize by name to process streams
        user_streams = defaultdict(list)
        for row in rows:
            user_streams[row['name']].append(dict(row))
            
        for name, records in user_streams.items():
            current_logical_date = None
            
            for row in records:
                status = row['status']
                ts = row['timestamp']
                try:
                    if '.' in ts:
                        dt_obj = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
                    else:
                        dt_obj = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                except:
                    continue

                if status == 'CHECK_IN':
                    # Determine Logical Date for this Shift Start
                    # Heuristic: If < 6 AM, assign to Previous Day (Night Shift continuation?)
                    # OR: Just use the Date. 
                    # Better: Use the date. If I start at 1 AM, it is that day's shift.
                    # EXCEPT if I am late for a 10 PM shift? 
                    # Existing logic used < 6 check. Let's keep it consistent.
                    if dt_obj.hour < 6:
                         logical_date = (dt_obj.date() - timedelta(days=1)).strftime('%Y-%m-%d')
                    else:
                         logical_date = dt_obj.date().strftime('%Y-%m-%d')
                    
                    current_logical_date = logical_date
                    user_date_records[(name, logical_date)].append(row)
                    
                elif status == 'CHECK_OUT':
                    # Assign to current logical date if exists (pair with Check-In)
                    if current_logical_date:
                        user_date_records[(name, current_logical_date)].append(row)
                        current_logical_date = None # Session closed
                    else:
                        # Orphan Check-Out (maybe from before buffer?)
                        # Use same heuristic
                        if dt_obj.hour < 6:
                             logical_date = (dt_obj.date() - timedelta(days=1)).strftime('%Y-%m-%d')
                        else:
                             logical_date = dt_obj.date().strftime('%Y-%m-%d')
                        user_date_records[(name, logical_date)].append(row)

        # Create CSV
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
        
        for name, person_info in persons.items():
            total_hours = 0
            days_present = 0
            
            # Iterate through REQUESTED date range (not buffer)
            current_date = start_dt
            
            while current_date <= end_dt:
                d_str = current_date.strftime('%Y-%m-%d')
                records = user_date_records.get((name, d_str), [])
                if records:
                    stats = calculate_daily_hours(records, timetable, date_str=d_str)
                    total_hours += stats['total_hours']
                    if stats['total_hours'] > 0:
                        days_present += 1
                current_date += timedelta(days=1)
            
            daily_wage = person_info['daily_wage'] or 0
            hourly_rate = daily_wage / company_working_hours if daily_wage and company_working_hours > 0 else 0
            total_wage = round(total_hours * hourly_rate, 2)
            
            # Format Time String
            h = int(total_hours)
            m = int(round((total_hours - h) * 60))
            total_hours_str = f"{h}h {m}m"
            
            row_data = [name]
            for f in standard_fields:
                k = f["key"]
                row_data.append(person_info.get(k) or '')
            row_data += [
                days_present,
                total_hours_str,
                round(total_hours, 2),
                company_working_hours,
                daily_wage,
                round(hourly_rate, 2),
                total_wage
            ]
            
            # Parse Custom Data for Dynamic Fields
            custom_data = {}
            if person_info.get('custom_data'):
                try:
                    import json
                    custom_data = json.loads(person_info['custom_data'])
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
        csv_data = output.getvalue()
        if is_async:
            job_id = create_job(content_type="text/csv", ttl=600)
            def _bg():
                try:
                    complete_job(job_id, csv_data)
                    socketio.emit('job_completed', {'job_id': job_id, 'type': 'report_export', 'vendor_id': vendor_id})
                except Exception as e:
                    fail_job(job_id, e)
            eventlet.spawn_n(_bg)
            return jsonify({"success": True, "job_id": job_id, "processing": True})
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=payroll_summary_{start_date_str}_to_{end_date_str}.csv"}
        )

    # --- Default Detailed Log Report ---
    # (dynamic_fields already fetched above)

    query = """
        SELECT a.name, a.person_id, a.timestamp, a.status, a.is_late, f.department, f.designation, f.shift, f.phone, f.custom_data
        FROM attendance a
        LEFT JOIN faces f ON (a.person_id IS NOT NULL AND a.person_id = f.id) OR (a.person_id IS NULL AND a.name = f.name AND f.vendor_id = a.vendor_id)
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

@greeting_bp.route("/jobs/<job_id>/status", methods=["GET"])
def job_status(job_id):
    j = get_job(job_id)
    if not j:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": j["status"], "error": j["error"]})

@greeting_bp.route("/jobs/<job_id>/result", methods=["GET"])
def job_result(job_id):
    from flask import Response
    j = get_job(job_id)
    if not j:
        return jsonify({"error": "Not found"}), 404
    if j["status"] != "done":
        return jsonify({"status": j["status"]}), 202
    return Response(j["result"], mimetype=j["content_type"])

@greeting_bp.route("/reports/filters", methods=["GET"])
@require_feature("reports")
def get_report_filters():
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
            field_key = field["key"]
            field_label = field["label"]
            if field_key in STANDARD_PERSON_FIELDS:
                continue
            unique_values = set()
            for f in filtered_faces:
                val = None
                if field_key in f["custom"]:
                    val = f["custom"].get(field_key)
                if val is None:
                    val = f["custom"].get(field_label)
                if val is not None and str(val).strip() != "":
                    unique_values.add(str(val))
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

@greeting_bp.route("/attendance/filters", methods=["GET"])
def get_attendance_filters():
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
        enabled_dynamic_keys = {f["key"] for f in enabled_fields if f["key"] not in STANDARD_PERSON_FIELDS}
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

    names = sorted({str(f.get("name")).strip() for f in filtered_faces if str(f.get("name") or "").strip() != ""})
    departments = sorted({str(f.get("department")).strip() for f in filtered_faces if str(f.get("department") or "").strip() != ""}) if visible_standard_filters["department"] else []
    designations = sorted({str(f.get("designation")).strip() for f in filtered_faces if str(f.get("designation") or "").strip() != ""}) if visible_standard_filters["designation"] else []
    shifts = sorted({str(f.get("shift")).strip() for f in filtered_faces if str(f.get("shift") or "").strip() != ""}) if visible_standard_filters["shift"] else []
    phones = sorted({str(f.get("phone")).strip() for f in filtered_faces if str(f.get("phone") or "").strip() != ""}) if visible_standard_filters["phone"] else []

    dynamic_filters = {}
    if enabled_fields:
        for field in enabled_fields:
            field_key = field["key"]
            field_label = field["label"]
            if field_key in STANDARD_PERSON_FIELDS:
                continue
            unique_values = set()
            for f in filtered_faces:
                val = None
                if field_key in f["custom"]:
                    val = f["custom"].get(field_key)
                if val is None:
                    val = f["custom"].get(field_label)
                if val is not None and str(val).strip() != "":
                    unique_values.add(str(val))
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

@greeting_bp.route("/persons", methods=["GET"])
def get_persons():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT id, name, department, designation, shift, daily_wage, face_image, phone, custom_data FROM faces"
    params = []
    
    if vendor_id:
        query += " WHERE vendor_id = ?"
        params.append(vendor_id)
        
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
    
    persons = []
    for row in rows:
        persons.append(dict(row))
    return jsonify({"persons": persons})

@greeting_bp.route("/reports/payroll", methods=["GET"])
@require_feature("payroll")
def get_payroll_report():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    import json
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400
        
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch Timetable and Working Hours
    if vendor_id:
        c.execute("SELECT live_timetable, working_hours FROM companies WHERE vendor_id = ?", (vendor_id,))
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
        if company_row['working_hours']:
            company_working_hours = float(company_row['working_hours'])

    late_enabled = vendor_has_feature(vendor_id, "late_mark")

    # 2. Fetch Persons (to get wages and late config)
    if vendor_id:
        c.execute("SELECT id, name, daily_wage, department, designation, face_image, phone, late_allowance_days, late_deduction_amount FROM faces WHERE vendor_id = ?", (vendor_id,))
    else:
        c.execute("SELECT id, name, daily_wage, department, designation, face_image, phone, late_allowance_days, late_deduction_amount FROM faces")
    
    persons = {row['id']: dict(row) for row in c.fetchall()}
    name_to_ids = defaultdict(list)
    for pid, info in persons.items():
        try:
            name_to_ids[info.get('name')].append(pid)
        except Exception:
            pass

    # 3. Fetch Global Settings
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
        if final_payout < 0: final_payout = 0.0
        
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

@greeting_bp.route("/settings/late-config", methods=["PUT"])
@require_feature("payroll")
def update_global_late_config():
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

@greeting_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "message": "Server is running"})

# --- Auth Endpoints ---
@greeting_bp.route("/auth/login", methods=["POST"], endpoint="auth_login_route")
@track_metrics("auth_login")
@rate_limit(limit=300, window=60)
def login():
    data = request.json or {}
    # Robustness: Handle missing keys and strip whitespace
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    device_id = str(data.get("device_id") or "").strip()
    platform = str(data.get("platform", "web") or "web").strip() # 'web' or 'mobile'

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM system_users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()

    if user and verify_password(password, user.get("password") if hasattr(user, "get") else user["password"]):
        try:
            stored_pw = user.get("password") if hasattr(user, "get") else user["password"]
            if stored_pw == password:
                conn_u = get_db_connection()
                cu = conn_u.cursor()
                cu.execute("UPDATE system_users SET password = ? WHERE username = ?", (hash_password(password), username))
                conn_u.commit()
                conn_u.close()
        except Exception:
            pass
        vendor_vertical = None
        # Check Vendor Subscription Status (if applicable)
        user_keys = user.keys() if hasattr(user, "keys") else []
        user_vendor_id = user['vendor_id'] if ('vendor_id' in user_keys and user['vendor_id']) else None
        if user_vendor_id:
            is_allowed, reason = check_vendor_status(user['vendor_id'])
            
            # Check Web Login Flag and Architecture Config
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT web_login_enabled, frontend_bundle_id, backend_service_id, registration_config FROM vendors WHERE id = ?", (user['vendor_id'],))
            row = c.fetchone()
            web_login_enabled = row[0] if row else 1 # Default to True
            frontend_bundle_id = row[1] if row and len(row) > 1 and row[1] else 'default_attendance'
            backend_service_id = row[2] if row and len(row) > 2 and row[2] else 'default_api'
            # Map registration_config to vendor_config for frontend compatibility
            vendor_config = json.loads(row[3]) if row and len(row) > 3 and row[3] else []
            # Fetch vertical
            vendor_vertical = None
            try:
                c.execute("SELECT vertical FROM vendors WHERE id = ?", (user['vendor_id'],))
                vrow = c.fetchone()
                vendor_vertical = vrow[0] if vrow else None
            except Exception:
                vendor_vertical = None

            # Fetch Features
            c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (user['vendor_id'],))
            sub_row = c.fetchone()
            if sub_row and sub_row[0]:
                try:
                    features = json.loads(sub_row[0])
                except json.JSONDecodeError:
                    features = []
            else:
                features = []
            
            # --- Session Limit Checks ---
            
            if platform == 'web':
                try:
                    c.execute("DELETE FROM active_sessions WHERE platform = 'web' AND last_active < datetime('now','-1 day')")
                    c.execute("DELETE FROM active_sessions WHERE username = ? AND platform = 'web' AND (device_id IS NULL OR device_id = '')", (username,))
                    conn.commit()
                except Exception:
                    pass
                if user['role'] == 'vendor_admin' and not device_id:
                    conn.close()
                    return jsonify({"error": "Device ID required for web login"}), 400
            
            # 1. Mobile: Max Device Enforcement (Persistent Registration)
            elif platform == 'mobile':
                # Get Limit
                c.execute("SELECT max_mobile_devices FROM subscriptions WHERE vendor_id = ?", (user['vendor_id'],))
                sub = c.fetchone()
                max_devs = sub[0] if sub else 1
                
                if device_id:
                    # Check if device is already registered
                    c.execute("SELECT id FROM vendor_devices WHERE vendor_id = ? AND device_id = ?", (user['vendor_id'], device_id))
                    existing_device = c.fetchone()
                    
                    if existing_device:
                        # Already registered -> Update Last Login
                        c.execute("UPDATE vendor_devices SET last_login_at = ? WHERE id = ?", (datetime.now(), existing_device[0]))
                        conn.commit()
                    else:
                        # New Device -> Check Limit
                        c.execute("SELECT COUNT(*) FROM vendor_devices WHERE vendor_id = ?", (user['vendor_id'],))
                        registered_count = c.fetchone()[0]
                        
                        if registered_count >= max_devs:
                            conn.close()
                            return jsonify({"error": f"Mobile device limit reached ({max_devs}). Contact Admin to register new device."}), 403
                        
                        # Register New Device
                        try:
                            c.execute("INSERT INTO vendor_devices (vendor_id, device_id, device_name, last_login_at) VALUES (?, ?, ?, ?)",
                                      (user['vendor_id'], device_id, f"Device {device_id[:8]}", datetime.now()))
                            conn.commit()
                        except sqlite3.IntegrityError:
                            # Race condition or duplicate
                            pass
                else:
                    # No device_id provided for mobile login? 
                    # Strict mode: Require device_id
                    conn.close()
                    return jsonify({"error": "Device ID required for mobile login"}), 400

            conn.close()

            if not is_allowed:
                print(f"Login Blocked: {reason}")
                
                # Special Case: Expired Subscription + Web Login Enabled -> Allow Login with Redirect
                if reason == "Subscription Expired" and web_login_enabled:
                     print("Subscription Expired but Web Login Enabled -> Redirecting to Recharge")
                     token = generate_token(user['username'], user['role'])
                     return jsonify({
                        "status": "success",
                        "role": user["role"],
                        "username": user["username"],
                        "token": token,
                        "redirect_url": "/recharge", # Frontend instruction
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
            
            # Check Web Login Flag for Vendor Admins (Active Account)
            if user['role'] == 'vendor_admin' and not web_login_enabled:
                 return jsonify({"error": "Access Denied: Web Login Disabled"}), 403

        else:
            # SuperAdmin or non-vendor user
            frontend_bundle_id = 'enterprise_custom_ui'
            backend_service_id = 'default_api'
            vendor_config = {}
            features = ALL_FEATURES

        print(f"Login Success: Role={user['role']}") # DEBUG LOG
        token = generate_token(user['username'], user['role'])
        
        # Get Company ID for this vendor (if any)
        company_id = None
        if user_vendor_id:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM companies WHERE vendor_id = ? LIMIT 1", (user_vendor_id,))
            row = c.fetchone()
            if row:
                company_id = row[0]
            
            # --- Web Session Limits ---
            if platform == 'web' and user['role'] == 'vendor_admin':
                try:
                    c.execute("SELECT max_web_sessions FROM subscriptions WHERE vendor_id = ?", (user_vendor_id,))
                    mw = c.fetchone()
                    max_web = mw[0] if mw else 1
                    try:
                        max_web = int(max_web)
                    except Exception:
                        max_web = 1
                    if max_web < 1:
                        max_web = 1
                    c.execute("DELETE FROM active_sessions WHERE username = ? AND platform = 'web' AND (device_id IS NULL OR device_id = '')", (username,))
                    c.execute("SELECT COUNT(DISTINCT device_id) FROM active_sessions WHERE username = ? AND platform = 'web' AND device_id IS NOT NULL AND device_id != ''", (username,))
                    existing_count = c.fetchone()[0] or 0
                    # If device_id provided and exists already, allow replacing; otherwise enforce limit
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
            # --- Record Session ---
            # Remove old session for this specific device/user combo to prevent duplicates
            c.execute("DELETE FROM active_sessions WHERE username = ? AND platform = ? AND device_id = ?", (username, platform, device_id))
            
            # Insert new session
            c.execute("INSERT INTO active_sessions (token, username, vendor_id, device_id, platform, last_active) VALUES (?, ?, ?, ?, ?, ?)",
                      (token, username, user_vendor_id, device_id, platform, datetime.now()))
            conn.commit()
            conn.close()

        return jsonify({
            "status": "success",
            "role": user["role"],
            "username": user["username"],
            "token": token,
            "vendor_id": user_vendor_id,
            "company_id": company_id,
            "frontend_bundle_id": frontend_bundle_id,
            "backend_service_id": backend_service_id,
            "vendor_config": vendor_config,
            "features": features,
            "vertical": vendor_vertical
        })
    else:
        print("Login Failed: Invalid credentials") # DEBUG LOG
        return jsonify({"error": "Invalid credentials"}), 401

@greeting_bp.route("/auth/register", methods=["POST"])
def register_user():
    # Auth Check
    caller_vendor_id, error = authenticate_vendor_access()
    if error: return error

    # Enforce Admin Role (Security Fix)
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1]
    user_data = verify_token(token)
    if user_data['role'] not in ['super_admin', 'vendor_admin']:
        return jsonify({"error": "Access Denied: Admin privileges required"}), 403

    data = request.json
    username = data.get("username")
    password = data.get("password")
    role = data.get("role", "user") # admin or user
    
    # Determine Vendor ID for new user
    target_vendor_id = caller_vendor_id
    if not target_vendor_id: # SuperAdmin
        target_vendor_id = data.get("vendor_id")

    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Check User Limit
        # (Removed strict check on system_users count since we now support Shared Credentials 
        # where one user account can be used on multiple devices, enforced via vendor_devices table)
        
        c.execute(
            "INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), role, target_vendor_id),
        )
        conn.commit()
        return jsonify({"status": "success", "message": "User created"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/parents/register", methods=["POST"])
def register_parent():
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

@greeting_bp.route("/parents/login", methods=["POST"])
def parent_login():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM parent_users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    if not user or not verify_password(password, user.get("password") if hasattr(user, "get") else user["password"]):
        return jsonify({"error": "Invalid credentials"}), 401
    try:
        stored_pw = user.get("password") if hasattr(user, "get") else user["password"]
        if stored_pw == password:
            conn_u = get_db_connection()
            cu = conn_u.cursor()
            cu.execute("UPDATE parent_users SET password = ? WHERE username = ?", (hash_password(password), username))
            conn_u.commit()
            conn_u.close()
    except Exception:
        pass
    token = generate_token(user['username'], 'parent')
    return jsonify({
        "status": "success",
        "role": "parent",
        "username": user["username"],
        "token": token,
        "vendor_id": user["vendor_id"],
        "parent_id": user["id"]
    })

@greeting_bp.route("/admin/students/assign-parent", methods=["POST"])
def assign_parent():
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

@greeting_bp.route("/parents/attendance", methods=["GET"])
def get_parent_attendance():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401
    try:
        token = auth_header.split(" ")[1]
        data = verify_token(token)
        if not data or data.get('role') != 'parent':
            return jsonify({"error": "Invalid or Expired Token"}), 401
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, vendor_id FROM parent_users WHERE username = ?", (data['username'],))
        pu = c.fetchone()
        if not pu:
            conn.close()
            return jsonify({"error": "Parent not found"}), 404
        parent_id = pu['id']
        vendor_id = pu['vendor_id']
        limit = int(request.args.get('limit', 50))
        c.execute("""
            SELECT a.id, a.name, a.timestamp, a.status, a.activity, a.is_late, a.person_id 
            FROM attendance a
            JOIN student_parents sp ON sp.person_id = a.person_id
            WHERE sp.parent_id = ? AND a.vendor_id = ?
            ORDER BY a.timestamp DESC
            LIMIT ?
        """, (parent_id, vendor_id, limit))
        rows = c.fetchall()
        conn.close()
        return jsonify({"attendance": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@greeting_bp.route("/public/attendance-by-student", methods=["GET"])
def public_attendance_by_student():
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
@greeting_bp.route("/parents/select-student", methods=["POST"])
def parent_select_student():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401
    try:
        token = auth_header.split(" ")[1]
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
        c.execute("SELECT id, vendor_id FROM parent_users WHERE username = ?", (data['username'],))
        pu = c.fetchone()
        if not pu:
            conn.close()
            return jsonify({"error": "Parent not found"}), 404
        parent_id = pu['id']
        vendor_id = pu['vendor_id']
        # Find student by custom_data->student_number under this vendor
        c.execute("SELECT id, name, custom_data FROM faces WHERE vendor_id = ? AND custom_data IS NOT NULL", (vendor_id,))
        rows = c.fetchall()
        selected = None
        import json
        for r in rows:
            try:
                cd = json.loads(r['custom_data'])
                if str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or '').strip() == str(student_number).strip():
                    selected = r
                    break
            except Exception:
                pass
        if not selected:
            conn.close()
            return jsonify({"error": "Student not found"}), 404
        person_id = selected['id']
        # Update parent preferred student and mapping
        c.execute("UPDATE parent_users SET student_number = ?, selected_person_id = ? WHERE id = ?", (student_number, person_id, parent_id))
        # Remove old mappings for this parent in vendor and insert new
        c.execute("DELETE FROM student_parents WHERE parent_id = ? AND vendor_id = ?", (parent_id, vendor_id))
        c.execute("INSERT OR IGNORE INTO student_parents (vendor_id, person_id, parent_id) VALUES (?, ?, ?)", (vendor_id, person_id, parent_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "person_id": person_id, "name": selected['name'], "student_number": student_number})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- System Settings Endpoints ---

@greeting_bp.route("/settings", methods=["GET"])
def get_settings():
    allowed_keys = {'threshold', 'cooldown', 'work_start_time', 'late_threshold', 'auto_checkout', 'voice_greeting', 'admin_alerts'}
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

@greeting_bp.route("/settings", methods=["POST"])
def update_settings():
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

    allowed_keys = {'threshold', 'cooldown', 'work_start_time', 'late_threshold', 'auto_checkout', 'voice_greeting', 'admin_alerts'}
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
@greeting_bp.route("/users", methods=["GET"])
def get_users():
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

@greeting_bp.route("/users", methods=["POST"])
def create_user():
    return register_user() # Reuse register logic

@greeting_bp.route("/users/<username>", methods=["PUT"])
def update_user(username):
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

@greeting_bp.route("/users/<username>", methods=["DELETE"])
def delete_user(username):
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

@greeting_bp.route("/sync/upload", methods=["POST"])
@require_feature("mobile_app")
def upload_face():
    # Auth Check
    caller_vendor_id, error = authenticate_vendor_access()
    if error: return error

    data = request.json
    person_id = data.get("person_id")
    name = data.get("name")
    templates = data.get("templates")
    templates_list = data.get("templates_list")
    face_image = data.get("face_image")
    phone = data.get("phone")
    department = data.get("department")
    designation = data.get("designation")
    shift = data.get("shift")
    
    # Extract Custom Data (Dynamic Fields)
    standard_fields = {'person_id', 'name', 'templates', 'face_image', 'phone', 'department', 'designation', 'shift', 'vendor_id'}
    custom_dict = {k: v for k, v in data.items() if k not in standard_fields}
    custom_data = json.dumps(custom_dict) if custom_dict else None

    # Use caller's vendor_id. If SuperAdmin, allow overriding via payload.
    vendor_id = caller_vendor_id
    if not vendor_id:
        vendor_id = data.get("vendor_id")

    if not name:
        return jsonify({"error": "Missing name"}), 400

    try:
        c = get_db_connection().cursor()
    except Exception:
        pass

    try:
        conn_check = get_db_connection()
        cc = conn_check.cursor()
        vertical = None
        if vendor_id:
            cc.execute("SELECT vertical FROM vendors WHERE id = ?", (vendor_id,))
            r = cc.fetchone()
            vertical = r[0] if r else None
        student_number = None
        try:
            student_number = str(custom_dict.get('student_number') or custom_dict.get('roll_number') or custom_dict.get('admission_number') or '').strip()
        except Exception:
            student_number = None
        if vertical == 'school' and student_number:
            if person_id:
                cc.execute("SELECT id, custom_data FROM faces WHERE vendor_id = ? AND id != ?", (vendor_id, person_id))
            else:
                cc.execute("SELECT id, custom_data FROM faces WHERE vendor_id = ?", (vendor_id,))
            rows = cc.fetchall()
            for r in rows:
                try:
                    cd = json.loads(r[1]) if r[1] else {}
                    sn = str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or '').strip()
                    if sn and sn == student_number:
                        conn_check.close()
                        return jsonify({"error": "Duplicate student_number for this vendor"}), 409
                except Exception:
                    continue
        # Generic duplicate guard for new registrations:
        # If creating a new person (no person_id), block if name or templates already exist for this vendor
        if not person_id:
            try:
                if vendor_id:
                    if templates_list and isinstance(templates_list, list) and len(templates_list) > 0:
                        cc.execute("SELECT templates FROM faces WHERE vendor_id = ?", (vendor_id,))
                        rows_all = cc.fetchall()
                        for rtpl in rows_all:
                            try:
                                et = rtpl[0] if not isinstance(rtpl, dict) else rtpl.get("templates")
                                if not et:
                                    continue
                                if et.startswith('['):
                                    arr = json.loads(et)
                                    for t in templates_list:
                                        if t in arr:
                                            conn_check.close()
                                            return jsonify({"error": "Face already registered for this vendor (templates_list)"}), 409
                                else:
                                    for t in templates_list:
                                        if t == et:
                                            conn_check.close()
                                            return jsonify({"error": "Face already registered for this vendor (templates)"}), 409
                            except Exception:
                                continue
                    elif vendor_id and templates and str(templates).strip() != "":
                        cc.execute("SELECT id FROM faces WHERE vendor_id = ? AND templates = ? LIMIT 1", (vendor_id, templates))
                        row_tpl = cc.fetchone()
                        if row_tpl:
                            conn_check.close()
                            return jsonify({"error": "Face already registered for this vendor (templates)"}), 409
            except Exception:
                pass
        conn_check.close()
    except Exception:
        pass

    # 1. Vendor Status Check
    if vendor_id:
        allowed, reason = check_vendor_status(vendor_id)
        if not allowed:
            return jsonify({"error": f"Access Denied: {reason}"}), 403

    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # 2. Employee Limit Check & Operation
        if not person_id and vendor_id:
            # Check limit (only for new users)
            c.execute("SELECT max_employees FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
            sub = c.fetchone()
            max_employees = sub[0] if sub else 50 # Default limit
            
            c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (vendor_id,))
            current_count = c.fetchone()[0]
            
            if current_count >= max_employees:
                conn.close()
                return jsonify({"error": f"Employee Limit Reached ({max_employees}). Upgrade your plan."}), 403

        image_url = None
        if face_image and OBJECT_STORAGE_ENABLED:
            try:
                s3_url = upload_base64_image(name or f"face_{datetime.now().timestamp()}", face_image)
                if s3_url:
                    image_url = presigned_url_for_key(s3_url, expires_seconds=3600)
                    face_image = image_url
            except Exception:
                pass
        if person_id:
            if caller_vendor_id:
                c.execute(
                    "SELECT name, templates, face_image, phone, department, designation, shift, vendor_id, custom_data FROM faces WHERE id=? AND vendor_id=?",
                    (person_id, caller_vendor_id),
                )
            else:
                c.execute(
                    "SELECT name, templates, face_image, phone, department, designation, shift, vendor_id, custom_data FROM faces WHERE id=?",
                    (person_id,),
                )
            row = c.fetchone()
            if not row:
                return jsonify({"error": "Person not found"}), 404
            existing = {
                "name": row[0],
                "templates": row[1],
                "face_image": row[2],
                "phone": row[3],
                "department": row[4],
                "designation": row[5],
                "shift": row[6],
                "vendor_id": row[7],
                "custom_data": row[8]
            }
            if custom_data is None and existing["custom_data"]:
                try:
                    old = json.loads(existing["custom_data"])
                    for k, v in custom_dict.items():
                        old[k] = v
                    custom_data = json.dumps(old)
                except Exception:
                    custom_data = existing["custom_data"]
            fields = []
            params = []
            if name is not None:
                fields.append("name=?"); params.append(name)
            if templates_list and isinstance(templates_list, list) and len(templates_list) > 0:
                fields.append("templates=?"); params.append(json.dumps(templates_list))
            elif templates is not None and templates != "":
                fields.append("templates=?"); params.append(templates)
            if face_image is not None and face_image != "":
                fields.append("face_image=?"); params.append(face_image)
            if phone is not None and phone != "":
                fields.append("phone=?"); params.append(phone)
            if department is not None and department != "":
                fields.append("department=?"); params.append(department)
            if designation is not None and designation != "":
                fields.append("designation=?"); params.append(designation)
            if shift is not None and shift != "":
                fields.append("shift=?"); params.append(shift)
            if caller_vendor_id is None and vendor_id is not None:
                fields.append("vendor_id=?"); params.append(vendor_id)
            if custom_data is not None:
                fields.append("custom_data=?"); params.append(custom_data)
            if not fields:
                new_id = person_id
            else:
                q = "UPDATE faces SET " + ", ".join(fields) + " WHERE id=?"
                params.append(person_id)
                c.execute(q, params)
                new_id = person_id
        else:
            # Insert New
            to_store_templates = None
            if templates_list and isinstance(templates_list, list) and len(templates_list) > 0:
                to_store_templates = json.dumps(templates_list)
            else:
                to_store_templates = templates or ""
            c.execute("INSERT INTO faces (name, templates, face_image, phone, department, designation, shift, vendor_id, custom_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (name, to_store_templates, face_image, phone or "", department or "", designation or "", shift or "", vendor_id, custom_data))
            new_id = c.lastrowid

        conn.commit()
        
        # Real-time update for Vendor Dashboard (People List) and SuperAdmin (Limits)
        socketio.emit('persons_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
        socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
        
        return jsonify({"status": "success", "message": f"Face for {name} saved.", "person_id": new_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/sync/download", methods=["GET"], endpoint="sync_download_route")
@require_feature("mobile_app")
@track_metrics("sync_download")
@rate_limit(limit=120, window=60)
def download_faces():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT * FROM faces"
    params = []
    
    if vendor_id:
        query += " WHERE vendor_id = ?"
        params.append(vendor_id)
        
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

    faces = []
    for row in rows:
        face_item = {
            "id": row["id"],
            "name": row["name"],
            "templates": row["templates"] if row["templates"] else None,
            "face_image": row["face_image"] if row["face_image"] else None,
            "phone": row["phone"] if "phone" in row.keys() else "",
            "department": row["department"] if "department" in row.keys() else "",
            "designation": row["designation"] if "designation" in row.keys() else "",
            "shift": row["shift"] if "shift" in row.keys() else "",
            "custom_data": json.loads(row["custom_data"]) if "custom_data" in row.keys() and row["custom_data"] else {}
        }
        try:
            if face_item["face_image"] and isinstance(face_item["face_image"], str) and face_item["face_image"].startswith("s3://"):
                url = presigned_url_for_key(face_item["face_image"])
                if url:
                    face_item["image_url"] = url
            elif face_item["face_image"] and isinstance(face_item["face_image"], str) and face_item["face_image"].startswith("http"):
                face_item["image_url"] = face_item["face_image"]
        except Exception:
            pass
        faces.append(face_item)
    
    return jsonify({"faces": faces})

@greeting_bp.route("/sync/delete/<name>", methods=["DELETE"])
@require_feature("mobile_app")
def delete_face(name):
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if not name:
        return jsonify({"error": "Missing name"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        if vendor_id:
            c.execute("DELETE FROM faces WHERE name = ? AND vendor_id = ?", (name, vendor_id))
        else:
            c.execute("DELETE FROM faces WHERE name = ?", (name,))
            
        conn.commit()
        if c.rowcount > 0:
            # Real-time update
            if vendor_id:
                socketio.emit('persons_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
                socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
            
            return jsonify({"status": "success", "message": f"Face for {name} deleted."})
        else:
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/sync/delete/id/<int:person_id>", methods=["DELETE"])
@require_feature("mobile_app")
def delete_face_by_id(person_id):
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Get name for message and scoping
        if vendor_id:
            c.execute("SELECT name FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        else:
            c.execute("SELECT name, vendor_id FROM faces WHERE id = ?", (person_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        name = row[0]
        # Delete
        if vendor_id:
            c.execute("DELETE FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        else:
            c.execute("DELETE FROM faces WHERE id = ?", (person_id,))
        conn.commit()
        if c.rowcount > 0:
            if vendor_id:
                socketio.emit('persons_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
                socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
            return jsonify({"status": "success", "message": f"Face for {name} deleted.", "person_id": person_id})
        else:
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/persons/wages", methods=["PUT"])
@require_feature("payroll")
def update_wages():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    data = request.json
    updates = data.get("updates", []) # List of {person_id|name, daily_wage, late_allowance_days, late_deduction_amount}

    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        for u in updates:
            pid = u.get('person_id')
            name = u.get('name')
            wage = u.get('daily_wage')
            allowance = u.get('late_allowance_days')
            deduction = u.get('late_deduction_amount')
            
            if pid or name:
                query_parts = []
                params = []
                
                if 'daily_wage' in u:
                    query_parts.append("daily_wage = ?")
                    params.append(u['daily_wage'])
                if 'late_allowance_days' in u:
                    query_parts.append("late_allowance_days = ?")
                    params.append(u['late_allowance_days'])
                if 'late_deduction_amount' in u:
                    query_parts.append("late_deduction_amount = ?")
                    params.append(u['late_deduction_amount'])
                
                if query_parts:
                    if pid:
                        query_str = f"UPDATE faces SET {', '.join(query_parts)} WHERE id = ?"
                        params.append(pid)
                    else:
                        query_str = f"UPDATE faces SET {', '.join(query_parts)} WHERE name = ?"
                        params.append(name)
                    
                    if vendor_id:
                        query_str += " AND vendor_id = ?"
                        params.append(vendor_id)
                        
                    c.execute(query_str, params)
                 
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/person-event", methods=["POST"])
def person_event():
    data = request.json
    
    # Debug Log
    print(f"Received person-event: detected={data.get('detected')}, recognized={data.get('recognized')}, name={data.get('name')}")

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
                print(f"Invalid timestamp format: {timestamp_str}. Using server time.")
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
        print(f"WARNING: No timestamp received from client. Falling back to Server Time (UTC): {current_time_obj}")

    print(f"DEBUG TIME: Server saw {current_time_obj} (Original TS: {timestamp_str})")

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
        print(f"Admin Identification Check: {name}")
        return jsonify({
            "speak": True,
            "text": f"Identified: {name} (Admin Mode)"
        })
    if recognized and not person_id:
        return jsonify({
            "speak": True,
            "text": "Please register vendor-wise from your organization. Missing person_id."
        })

    # --- Check-in / Check-out Logic ---
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Determine Expected Status EARLY (for better activity matching)
    if person_id:
        if vendor_id_to_check:
            c.execute("SELECT * FROM attendance WHERE person_id = ? AND vendor_id = ? ORDER BY timestamp DESC LIMIT 1", (person_id, vendor_id_to_check))
        else:
            c.execute("SELECT * FROM attendance WHERE person_id = ? ORDER BY timestamp DESC LIMIT 1", (person_id,))
    else:
        if vendor_id_to_check:
            c.execute("SELECT * FROM attendance WHERE name = ? AND vendor_id = ? ORDER BY timestamp DESC LIMIT 1", (name, vendor_id_to_check))
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
                print(f"Stale Check-In detected for {name} ({duration_hours:.1f}h ago). Resetting to CHECK_IN.")
                expected_status = 'CHECK_IN'
        except Exception as e:
            print(f"Error checking stale status: {e}")

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
                print(f"User Shift Name: {user_shift_name}")
                for s in shifts_data:
                    # Loose matching for robustness (case-insensitive, trim)
                    if s.get('name', '').strip().lower() == user_shift_name.strip().lower():
                        user_shift_id = s.get('id')
                        print(f"Resolved User Shift ID: {user_shift_id}")
                        break
        
        # --- STRICT SHIFT FILTERING (User Request) ---
        # If the user has an assigned shift, we MUST filter the timetable to ONLY include:
        # 1. Activities explicitly assigned to this shift (shift_id match)
        # 2. Global activities (shift_id is None/Empty) - BUT only if they don't conflict with specific ones.
        
        filtered_timetable = []
        if company_row and company_row['live_timetable']:
            full_timetable = json.loads(company_row['live_timetable'])
            
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
                    
                print(f"Shift Filter Applied: {len(full_timetable)} -> {len(filtered_timetable)} activities.")
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
            
            # Fetch Settings
            c.execute("SELECT key, value FROM system_settings WHERE key IN ('activity_tolerance', 'late_grace_period')")
            settings = {row['key']: row['value'] for row in c.fetchall()}
            tolerance = int(settings.get('activity_tolerance', 30))
            grace_period = int(settings.get('late_grace_period', 15))

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
                        print(f"Matched Yesterday's Standard Shift: {act.get('name')} (Grace Period)")

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
                        print(f"Matched Yesterday's Shift: {act.get('name')}")
            
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
                     
                     print(f"Fallback Activity Match: {best_fallback.get('name')} (Strict window missed)")
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
                    print(f"Check-In Priority: Picked {best_match.get('name')} (Yesterday={best_match.get('_is_yesterday', False)})")
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
        print(f"Activity Detection Error: {e}")

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
            print(f"Activity {activity_name} already completed for {name}. Skipping.")
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
            print(f"Cooldown Check: Name={name}, Last={last_ts}, Now={datetime.now()}, Delta={delta_seconds}s, Limit={cooldown_seconds}s")
            
            if 0 <= delta_seconds < cooldown_seconds:
                print(f"Cooldown active for {name}. Skipping.")
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
                     print(f"Cooldown active (future skew) for {name}. Skipping.")
                     conn.close()
                     return jsonify({"speak": False})
                 else:
                     print(f"Ignoring future timestamp (timezone mismatch?) for {name}. Allowing entry.")

    except Exception as e:
        print(f"Cooldown Error: {e}" )

    new_status = expected_status
    # if last_record and last_record['status'] == 'CHECK_IN':
    #     new_status = 'CHECK_OUT'
    
    # Calculate Late Status
    is_late = 0
    if new_status == 'CHECK_IN' and best_match:
        try:
            # Ensure grace_period is available
            if 'grace_period' not in locals(): grace_period = 15
            
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
            except:
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
                print("Strict Logic: Activity is from Yesterday. Adding 1440 to check_mins.")
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
            print(f"LATE CHECK: Act={activity_name}, Start={effective_start_mins}, Check={check_mins}, Grace={act_grace}")

            # Calculate Threshold
            late_threshold = effective_start_mins + act_grace
            
            if check_mins > late_threshold:
                is_late = 1
                print(f"Late Detected (Strict): {name} [ID={person_id}] (Time: {check_mins}, Start: {effective_start_mins}, Grace: {act_grace}, Diff: {check_mins - effective_start_mins})")
            else:
                # Debugging info
                print(f"On Time Detected: {name} [ID={person_id}] (Time: {check_mins}, Start: {effective_start_mins}, Grace: {act_grace}, Threshold: {late_threshold})")
                
                # Also check if check_mins is BEFORE start_mins (Early Arrival is On Time)
                if check_mins < effective_start_mins:
                    print(f"Early Arrival: {effective_start_mins - check_mins} mins early.")

        except Exception as e:
            print(f"Late Calculation Error: {e}")

    if vendor_id_to_check and not vendor_has_feature(vendor_id_to_check, "late_mark"):
        is_late = 0

    # Insert new record with image
    # Use UTC for storage to ensure consistency
    current_time_utc = datetime.utcnow()
    # But for now, since we use naive datetimes everywhere, let's stick to naive local server time
    # to avoid breaking existing logic that expects naive objects.
    # Ideally, we should migrate to UTC everywhere.
    # Given the user's issue "past attendance", let's make sure we return ISO 8601 strings in API.
    
    current_time = current_time_obj
    try:
        c.execute("INSERT INTO attendance (name, timestamp, status, captured_image, activity, is_late, vendor_id, person_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                  (name, current_time, new_status, captured_image, activity_name, is_late, vendor_id_to_check, person_id))
        conn.commit()
        print(f"Attendance Recorded: {name} - {new_status} ({activity_name}) Late={is_late} at {current_time}")
        try:
            ev = {
                "name": name,
                "timestamp": current_time.strftime('%Y-%m-%d %H:%M:%S'),
                "status": new_status,
                "is_late": is_late,
                "activity": activity_name,
                "vendor_id": vendor_id_to_check
            }
            if vendor_id_to_check:
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
                            socketio.emit('parent_attendance', ev, room=f"parent_{pr[0]}")
                        except Exception:
                            pass
                    try:
                        c.execute("SELECT custom_data FROM faces WHERE id = ?", (pid_lookup,))
                        row_cd = c.fetchone()
                        if row_cd and row_cd[0]:
                            cd = json.loads(row_cd[0])
                            sn = str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or '').strip()
                            if sn:
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
                                            try:
                                                requests.post("https://fcm.googleapis.com/fcm/send", headers=headers, data=json.dumps(payload), timeout=5)
                                            except Exception:
                                                pass
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
        print(f"Attendance insert error: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"speak": False}), 500

@greeting_bp.route("/public/register-token", methods=["POST"])
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

@greeting_bp.route("/attendance", methods=["GET"], endpoint="attendance_list_route")
@track_metrics("attendance_list")
@rate_limit(limit=300, window=60)
def get_attendance():
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

    query = """
        SELECT a.*, f.department, f.designation, f.shift, f.phone, f.custom_data AS face_custom_data
        FROM attendance a
        LEFT JOIN faces f ON (a.person_id IS NOT NULL AND a.person_id = f.id) OR (a.person_id IS NULL AND a.name = f.name AND f.vendor_id = a.vendor_id)
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
            "department": row["department"] if "department" in row.keys() else "",
            "designation": row["designation"] if "designation" in row.keys() else "",
            "shift": row["shift"] if "shift" in row.keys() else "",
            "phone": row["phone"] if "phone" in row.keys() else "",
            "custom_data": face_custom
        })
    
    return jsonify({"attendance": attendance})

def calculate_daily_hours(records, timetable=None, date_str=None):
    """
    Calculate work hours from a list of attendance records for a single user.
    Records must be sorted by timestamp ASC.
    timetable: List of activity objects (from company live_timetable) to determine payability of gaps.
    date_str: Optional date string to enable real-time calculation for active sessions.
    """
    total_seconds = 0
    current_checkin = None
    current_checkin_activity = None # Track activity started at Check-In
    last_checkout_activity = None # Track activity of last checkout to determine gap payability
    sessions = []
    
    # Sort just in case
    sorted_records = sorted(records, key=lambda x: x['timestamp'])

    for record in sorted_records:
        status = record['status']
        activity_name = record.get('activity', 'Work')
        
        try:
            ts = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            # Fallback for timestamps without microseconds
            try:
                ts = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S')
            except:
                continue # Skip invalid

        if status == 'CHECK_IN':
            if current_checkin is None:
                current_checkin = ts
                current_checkin_activity = activity_name # Store activity from Check-In
                
                # Check if the GAP before this Check-In is payable
                # Logic: If we had a previous session that ended (last_checkout_activity), 
                # we check if THAT activity was payable.
                # Usually, Gaps are Breaks. If Break is Payable, we add the gap time.
                # However, calculate_daily_hours iterates linearly.
                # We need to look at the gap between `sessions[-1]['end_ts']` and `current_checkin`.
                
                if sessions:
                    last_session = sessions[-1]
                    gap_seconds = (ts - last_session['end_ts']).total_seconds()
                    
                    if gap_seconds > 0 and timetable:
                        # Find the activity definition for the gap
                        # We use the activity name from the PREVIOUS CHECK_OUT record (stored in last_checkout_activity)
                        # If last_checkout_activity is None, we can't determine.
                        
                        is_gap_payable = False
                        if last_checkout_activity:
                             # Find activity in timetable (Case Insensitive)
                             last_act_lower = last_checkout_activity.lower().strip()
                             for act in timetable:
                                if act.get('name', '').lower().strip() == last_act_lower:
                                    # Default is_payable to True for Work, False for others if not specified?
                                    # User said: "if it is off, then the activity is not payable".
                                    # In our JSON, we defaulted is_payable to True in UI, but existing data might miss it.
                                    # Let's assume default True for 'Work' type, False for others if missing.
                                    act_type = act.get('type', 'Work')
                                    
                                    # STRICT PAYROLL RULE: 
                                    # Gaps are NEVER payable automatically. 
                                    # User Instruction: "only those tiem when the emplyee had check in and check out that time needs to be saved"
                                    # Users must Check-In to a "Paid Break" activity to get paid for it.
                                    # Checking Out stops the wage counter immediately.
                                    is_gap_payable = False 
                                    
                                    # Legacy Logic Disabled:
                                    # is_gap_payable = act.get('is_payable', False)
                                    
                                    # if is_gap_payable:
                                    #    ... (Logic removed)
                                    pass
                                    break
                        
                        if is_gap_payable:
                             # This block is now effectively unreachable or always False
                             pass


        elif status == 'CHECK_OUT':
            if current_checkin:
                duration = (ts - current_checkin).total_seconds()
                
                # STRICT FIX: Prevent Negative Duration
                # If Check-Out is before Check-In (e.g. Timezone mismatch or bad data), clamp to 0.
                if duration < 0:
                    duration = 0

                # Determine Session Activity: Use the one from Check-In, fallback to current record if missing
                session_activity = current_checkin_activity if current_checkin_activity else activity_name
                
                # Check if this session's activity is PAYABLE
                # User Requirement: "payable hours calculated only when we register an activity with shift"
                # Strict Logic: Rely entirely on the timetable configuration.
                is_session_payable = False
                
                # Normalize for matching
                session_activity_lower = session_activity.lower().strip() if session_activity else ""
                
                if timetable:
                    found_act = None
                    for act in timetable:
                        act_name = act.get('name', '').lower().strip()
                        if act_name == session_activity_lower:
                            found_act = act
                            break
                    
                    if found_act:
                        # STRICT: Use the is_payable flag from the DB. 
                        # If missing, default to False (safe).
                        is_session_payable = found_act.get('is_payable', False)
                    else:
                        # Activity not found in timetable
                        # Strict Fallback: If not defined by admin, it is NOT payable.
                        is_session_payable = False
                else:
                    # No timetable -> No payable hours (Strict)
                    is_session_payable = False

                if is_session_payable:
                    total_seconds += duration
                else:
                    pass
                    
                sessions.append({
                    "type": "Work", # Standard session
                    "activity": session_activity,
                    "is_payable": is_session_payable,
                    "start_ts": current_checkin, # Correct start
                    "end_ts": ts,
                    "start": current_checkin.strftime('%H:%M'),
                    "end": ts.strftime('%H:%M'),
                    "duration_mins": round(duration / 60)
                })
                current_checkin = None
                current_checkin_activity = None
                last_checkout_activity = activity_name # Use Check-Out reason for gap logic (e.g. Lunch/TeaBreak)
    
    # --- Deduct Unpaid Overlaps (REMOVED based on user request for strict Check-In/Out calculation) ---
    # User instruction: "wage counting is very important based on payble check in and check out times gap only"
    # This implies no auto-deductions for scheduled breaks if the user didn't actually check out.
    # if timetable and records and total_seconds > 0:
    #     try:
    #         # ... (Logic removed to prevent auto-deduction)
    #         pass
    #     except Exception as e:
    #         print(f"Error in unpaid deduction logic: {e}")

    # Clean up sessions for output
    final_sessions = []
    for s in sessions:
        # Keep timestamps as ISO strings for reporting
        if "start_ts" in s and isinstance(s["start_ts"], datetime):
             s["start_ts"] = s["start_ts"].isoformat()
        if "end_ts" in s and isinstance(s["end_ts"], datetime):
             s["end_ts"] = s["end_ts"].isoformat()
        final_sessions.append(s)

    is_active = current_checkin is not None
    
    # Real-time Calculation: If active and today, add duration from last checkin to NOW
    if is_active and date_str:
        try:
            today_str = datetime.now().strftime('%Y-%m-%d')
            # Allow active calculation if it's today OR if we are processing a continuous stream
            if True: # Always check active if date_str is present (it implies "Live" context)
                now_dt = datetime.now()
                duration = (now_dt - current_checkin).total_seconds()
                if duration < 0:
                    duration = 0
                
                # Check payability of current active session
                # We need the activity name for the current session.
                # Assuming the LAST Check-In established the activity.
                # Find the last Check-In record
                last_in_record = None
                for r in reversed(sorted_records):
                    if r['status'] == 'CHECK_IN':
                        last_in_record = r
                        break
                
                active_activity_name = last_in_record.get('activity', 'Work') if last_in_record else "Unknown"
                
                is_active_payable = False
                found_act = None
                if timetable:
                     for act in timetable:
                         if act.get('name') == active_activity_name:
                             found_act = act
                             break
                     if found_act:
                         act_type = found_act.get('type', 'Work')
                         is_active_payable = found_act.get('is_payable', act_type == 'Work')
                
                if is_active_payable:
                    total_seconds += duration
                
                # Add Active Session to FINAL sessions directly
                final_sessions.append({
                    "type": "Work (Active)",
                    "activity": active_activity_name,
                    "is_payable": is_active_payable,
                    "start_ts": current_checkin.isoformat(),
                    "end_ts": now_dt.isoformat(),
                    "start": current_checkin.strftime('%H:%M'),
                    "end": now_dt.strftime('%H:%M'),
                    "duration_mins": round(duration / 60)
                })
        except Exception as e:
            print(f"Real-time calc error: {e}")

    # Calculate string format (e.g. "2h 30m")
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    total_hours_str = f"{h}h {m}m"

    return {
        "total_hours": round(total_seconds / 3600, 2),
        "total_hours_str": total_hours_str,
        "sessions": final_sessions,
        "is_active": is_active,
        "last_checkin": current_checkin.strftime('%H:%M') if current_checkin else None
    }

# --- Live Camera Stream Endpoints ---

# In-memory storage for the latest frames
# Structure: { vendor_id: { device_id: { "data": ..., "timestamp": ..., "source_ip": ... } } }
latest_frames = {}

def cleanup_inactive_streams():
    """Background task to remove stale streams and update stats."""
    last_active_count = -1
    while True:
        socketio.sleep(5) # Sleep 5 seconds
        
        try:
            current_time = datetime.now()
            stale_threshold = timedelta(seconds=30)
            
            # 1. Cleanup Stale Devices
            # We need to modify dictionary while iterating, so use list of keys
            vendors_to_remove = []
            
            active_count = 0
            
            for v_id in list(latest_frames.keys()):
                devices = latest_frames[v_id]
                devices_to_remove = []
                
                for d_id, data in devices.items():
                    if current_time - data['timestamp'] > stale_threshold:
                        devices_to_remove.append(d_id)
                    else:
                        active_count += 1
                
                for d_id in devices_to_remove:
                    del devices[d_id]
                    
                if not devices:
                    vendors_to_remove.append(v_id)
            
            for v_id in vendors_to_remove:
                del latest_frames[v_id]
                
            # 2. Emit Stats Update if changed
            if active_count != last_active_count:
                last_active_count = active_count
                socketio.emit('active_devices_update', {'count': active_count}, room='super_admin')
                
        except Exception as e:
            print(f"Error in cleanup task: {e}")

# Start the background task
try:
    socketio.start_background_task(cleanup_inactive_streams)
except Exception as e:
    print(f"Failed to start background task: {e}")


@greeting_bp.route("/stream/upload", methods=["POST"])
def upload_stream_frame():
    try:
        # 1. Identify Vendor from Auth Token
        vendor_id = 1 # Default to Vendor 1 (Legacy/Unauth)
        
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
                    if u_row and u_row[0]:
                        vendor_id = u_row[0]
            except:
                pass

        data = request.json
        image_data = data.get("image") # Base64 string
        device_id = data.get("device_id", "default")
        
        # 2. Check for explicit vendor_id in body (Override)
        if data.get("vendor_id"):
            try:
                vendor_id = int(data.get("vendor_id"))
            except:
                pass
        
        if not image_data:
            return jsonify({"error": "No image data"}), 400
            
        if vendor_id not in latest_frames:
            latest_frames[vendor_id] = {}
            
        latest_frames[vendor_id][device_id] = {
            "data": image_data,
            "timestamp": datetime.now(),
            "source_ip": request.headers.get('X-Forwarded-For', request.remote_addr),
            "device_name": data.get("device_name", f"Device {device_id}")
        }
        payload = {
            "vendor_id": vendor_id,
            "device_id": str(device_id),
            "device_name": data.get("device_name", f"Device {device_id}"),
            "image": image_data
        }
        socketio.emit('frame_update', payload, room=f"stream_{vendor_id}")
        socketio.emit('frame_update', payload, room=f"vendor_{vendor_id}")
        socketio.emit('frame_update', payload, room='super_admin')
        
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"Stream Upload Error: {e}")
        return jsonify({"error": str(e)}), 500

@greeting_bp.route("/stream/view", methods=["GET"])
def view_stream_frame():
    auth_vendor_id, error = authenticate_vendor_access()
    if error: return error

    # Determine which vendor stream to view
    target_vendor_id = auth_vendor_id
    
    # If SuperAdmin, allow selecting vendor (default to 1)
    if not target_vendor_id:
        try:
            target_vendor_id = int(request.args.get('vendor_id', 1))
        except:
            target_vendor_id = 1
            
    target_device_id = request.args.get('device_id', 'default')

    vendor_frames = latest_frames.get(target_vendor_id, {})
    frame_data = vendor_frames.get(target_device_id)

    # Legacy Fallback: If no device_id specified and 'default' missing, return first available
    if not request.args.get('device_id') and not frame_data and vendor_frames:
        frame_data = next(iter(vendor_frames.values()))

    # Check if frame is stale (older than 10 seconds)
    if frame_data and frame_data.get("timestamp"):
        delta = datetime.now() - frame_data["timestamp"]
        if delta.total_seconds() > 10:
            return jsonify({"status": "offline", "image": None})
            
    if frame_data and frame_data.get("data"):
        return jsonify({
            "status": "online", 
            "image": frame_data["data"],
            "source_ip": frame_data.get("source_ip", "Unknown"),
            "timestamp": frame_data.get("timestamp").isoformat()
        })
    else:
        return jsonify({"status": "offline", "image": None})

@greeting_bp.route("/stream/active-devices", methods=["GET"])
def list_active_devices():
    """
    Returns a list of active devices (streams) for the authenticated vendor 
    or all vendors if SuperAdmin.
    """
    auth_vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    active_list = []
    
    # If SuperAdmin (auth_vendor_id is None), return all
    # If Vendor Admin, return only theirs
    
    target_vendors = [auth_vendor_id] if auth_vendor_id else latest_frames.keys()
    
    for vid in target_vendors:
        if vid in latest_frames:
            devices = latest_frames[vid]
            for did, data in devices.items():
                # Filter out stale devices (> 30 seconds)
                if (datetime.now() - data['timestamp']).total_seconds() < 30:
                    active_list.append({
                        "vendor_id": vid,
                        "device_id": did,
                        "device_name": data.get("device_name", f"Device {did}"),
                        "last_seen": data['timestamp'].isoformat(),
                        "source_ip": data.get("source_ip")
                    })
                    
    return jsonify({"devices": active_list})


def calculate_expected_hours(day_activities):
    """
    Helper to calculate total expected work hours from a list of activities.
    Handles overnight shifts correctly.
    """
    expected_hours = 0
    for act in day_activities:
        # Check is_payable, default to True if Work, False otherwise
        is_payable = act.get('is_payable', act.get('type') == 'Work')
        
        if is_payable:
            try:
                s = datetime.strptime(act['start_time'], '%H:%M')
                e = datetime.strptime(act['end_time'], '%H:%M')
                
                # Handle overnight shifts (end < start)
                if e < s:
                    e += timedelta(days=1)
                    
                duration = (e - s).total_seconds() / 3600
                expected_hours += duration
            except Exception as e:
                print(f"Error calculating expected hours for activity {act}: {e}")
                pass
    return expected_hours

def calculate_arrival_status(expected_start, sessions, day_activities=None):
    """
    Determines if the user arrived late based on their first 'Work' session.
    """
    arrival_status = "On Time"
    if not expected_start or not sessions:
        return arrival_status

    # Find the first 'Work' or relevant session
    first_checkin = None
    for s in sessions:
        s_type = s.get('type', '')
        if s_type == 'Work' or 'Active' in s_type:
             # Prefer 'Work' but 'Active' works if it's the first one
             first_checkin = s['start']
             break
    
    if not first_checkin:
        # Fallback to first session if no Work session found yet
        first_checkin = sessions[0]['start']

    if first_checkin:
        # Get tolerance from the first scheduled activity
        tolerance_mins = 0 # Default Strict
        if day_activities:
             # Check rules for grace_period ONLY (Strict User Request)
             first_act = day_activities[0]
             rules = first_act.get('rules', {}) or {}
             
             # Handle grace_period
             gp = rules.get('grace_period')
             if gp is not None:
                 try:
                     # Robust parsing for grace period (handle "15 min", "15", etc.)
                     if isinstance(gp, str):
                         import re
                         digits = re.findall(r'\d+', gp)
                         if digits:
                             tolerance_mins = int(digits[0])
                         else:
                             tolerance_mins = 0
                     else:
                         tolerance_mins = int(gp)
                 except:
                     tolerance_mins = 0
             else:
                 # No grace period defined -> 0 tolerance
                 tolerance_mins = 0

        try:
            exp_dt = datetime.strptime(expected_start, '%H:%M')
            act_dt = datetime.strptime(first_checkin, '%H:%M')
            
            # Handle midnight crossing (e.g. Expected 23:00, Actual 00:10 next day)
            if act_dt < exp_dt and (exp_dt.hour - act_dt.hour) > 12:
                act_dt += timedelta(days=1)
            
            # Handle reverse midnight crossing (Expected 00:10, Actual 23:50 prev day)
            # Only apply if Expected Start is early morning (e.g. < 06:00) to avoid false positives for very late Day Shifts
            if exp_dt < act_dt and (act_dt.hour - exp_dt.hour) > 12:
                 if exp_dt.hour < 6:
                     exp_dt += timedelta(days=1)

            diff_seconds = (act_dt - exp_dt).total_seconds()
            if diff_seconds > (tolerance_mins * 60):
                arrival_status = "Late"
        except Exception as e:
            print(f"Error calc arrival status: {e}")
            # Fallback: simple comparison if complex logic fails
            try:
                 # Simple string compare if format allows? No, safer to leave as On Time or retry simple
                 pass
            except:
                 pass

    return arrival_status

@greeting_bp.route("/attendance/summary", methods=["GET"])
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

@greeting_bp.route("/superadmin/subscription", methods=["POST", "PUT"])
@super_admin_required
def update_subscription():
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

@greeting_bp.route("/superadmin/employees", methods=["GET"])
@super_admin_required
def get_all_employees():
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

@greeting_bp.route("/auth/logout", methods=["POST"])
def logout():
    # Attempt to get token
    auth_header = request.headers.get('Authorization')
    token = None
    if auth_header:
        try:
            token = auth_header.split(" ")[1]
        except:
            pass
            
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
        return jsonify({"status": "success", "message": "Logged out"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
# Bootstrap DB in WSGI environments (Render/Gunicorn) to ensure base tables exist
try:
    bootstrap_db()
except Exception as _e:
    try:
        print(f"Bootstrap Error: {_e}")
    except Exception:
        pass

app.register_blueprint(greeting_bp)

if __name__ == "__main__":
    bootstrap_db()
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)
