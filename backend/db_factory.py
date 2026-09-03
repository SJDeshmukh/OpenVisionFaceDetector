import os
import sqlite3
try:
    import psycopg2
    import psycopg2.pool
    from psycopg2.extras import DictCursor
    from psycopg2 import extensions as ext
except ImportError:
    psycopg2 = None
    ext = None
import re
import logging
from datetime import datetime
import time
from database.models import db

def set_row_factory(conn):
    """Sets the appropriate row factory for SQLite or uses DictCursor for PG."""
    if getattr(conn, "_is_pg", False):
        # psycopg2 connections with DictCursor don't need row_factory
        # But we ensure it's using DictCursor if initialized via get_db_connection
        return conn
    else:
        # SQLite native connection
        try:
            conn.row_factory = sqlite3.Row
        except Exception:
            pass
    return conn

def get_table_columns(conn, table_name):
    """Returns a list of column names for a given table."""
    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()
    try:
        if is_pg:
            # Use SAVEPOINT to protect any active transaction from being aborted if this check fails
            c.execute("SAVEPOINT get_cols_sp")
            try:
                # PostgreSQL uses %s for parameters
                c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table_name,))
                cols = [str(r[0]) for r in c.fetchall()]
                c.execute("RELEASE SAVEPOINT get_cols_sp")
                return cols
            except Exception:
                # Rollback only the column check, keeping the main transaction alive
                try:
                    c.execute("ROLLBACK TO SAVEPOINT get_cols_sp")
                except Exception:
                    pass
                return []
        else:
            # SQLite PRAGMA doesn't support ? for table names
            # table_name is trusted here since it's used internally
            c.execute(f"PRAGMA table_info({table_name})")
            return [str(r[1]) for r in c.fetchall()]
    except Exception:
        return []
    finally:
        c.close()

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.environ.get("DATABASE_URL", "")
# Default to face_db.sqlite in the same directory as this file
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "face_db.sqlite")
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB_PATH)

# Global state to track if we are in fallback mode
DB_TYPE = 'postgres' if DATABASE_URL else 'sqlite'
_IS_FALLBACK_MODE = False
_LAST_PG_RETRY_TIME = 0
_PG_COOLDOWN_SECONDS = 30 # Don't flood logs if PG is down

# Backup Database Configuration
DB_BACKUP_PATH = os.environ.get("DB_BACKUP_PATH", os.path.join(os.path.dirname(__file__), "backup_faces.db"))

_PG_POOL = None

def get_pg_pool():
    global _PG_POOL
    if _PG_POOL is None and DATABASE_URL:
        try:
            # ThreadedConnectionPool for eventlet/threading compatibility
            minconn = int(os.environ.get("DB_MIN_CONN", "1"))
            maxconn = int(os.environ.get("DB_MAX_CONN", "50"))
            if psycopg2:
                _PG_POOL = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, DATABASE_URL)
                logger.info(f"PostgreSQL connection pool initialized (min={minconn}, max={maxconn})")
            else:
                logger.error("PostgreSQL requested but psycopg2 is not installed.")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {e}")
    return _PG_POOL

def init_db_sqlalchemy(app):
    """Initializes SQLAlchemy with the Flask app."""
    if DATABASE_URL:
        # Use PostgreSQL
        app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
        # Connection pool settings for SQLAlchemy
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            "pool_size": int(os.environ.get("DB_MIN_CONN", "5")),
            "max_overflow": int(os.environ.get("DB_MAX_CONN", "50")) - int(os.environ.get("DB_MIN_CONN", "5")),
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        }
    else:
        # Fallback to SQLite
        # Ensure the path is absolute for SQLAlchemy
        abs_db_path = os.path.abspath(DB_PATH)
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{abs_db_path}"
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            "connect_args": {"check_same_thread": False},
        }
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    logger.info(f"SQLAlchemy initialized with {DB_TYPE} backend.")

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self._lastrowid = None
        self._rowcount = -1

    def execute(self, sql, params=None):
        if params is None: params = []
        # 1. Handle SQLite PRAGMA (Ignore)
        if sql.strip().upper().startswith("PRAGMA"):
            return self

        # 2. Convert SQLite syntax/functions to Postgres
        sql_pg = sql.replace('?', '%s')
        
        # Clean up multi-line SQL for easier regex matching
        sql_up = sql_pg.upper().strip()
        
        # Handle "INSERT OR IGNORE" -> "INSERT ... ON CONFLICT DO NOTHING"
        if "INSERT OR IGNORE" in sql_up:
            sql_pg = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', sql_pg, flags=re.IGNORECASE)
            # Find the core part to determine where to append ON CONFLICT
            target_table = None
            for table in [
                'system_users', 'parent_users', 'active_sessions', 'subscriptions', 
                'vendors', 'student_parents', 'vendor_devices', 'vendor_device_slots',
                'audit_logs', 'parent_tokens', 'system_settings', 'face_reset_requests'
            ]:
                if table in sql_pg.lower():
                    target_table = table
                    break
            
            if target_table:
                # Remove trailing semicolon if present to append ON CONFLICT safely
                sql_pg = sql_pg.rstrip().rstrip(';')
                if target_table == "system_users":
                    sql_pg += " ON CONFLICT (username) DO NOTHING"
                elif target_table == "parent_users":
                    sql_pg += " ON CONFLICT (username) DO NOTHING"
                elif target_table == "active_sessions":
                    sql_pg += " ON CONFLICT (token) DO NOTHING"
                elif target_table == "subscriptions":
                    sql_pg += " ON CONFLICT (vendor_id) DO NOTHING"
                elif target_table == "vendors" and "id" in sql_pg.lower():
                    sql_pg += " ON CONFLICT (id) DO NOTHING"
                elif target_table == "student_parents":
                    sql_pg += " ON CONFLICT (person_id, parent_id) DO NOTHING"
                elif target_table == "vendor_devices":
                    sql_pg += " ON CONFLICT (vendor_id, device_id) DO NOTHING"
                elif target_table == "vendor_device_slots":
                    sql_pg += " ON CONFLICT (vendor_id, slot_name) DO NOTHING"
                elif target_table == "system_settings":
                    sql_pg += " ON CONFLICT (key) DO NOTHING"

        # Handle "INSERT OR REPLACE" -> "INSERT ... ON CONFLICT (...) DO UPDATE SET ..."
        if "INSERT OR REPLACE" in sql_up:
            sql_pg = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO', 'INSERT INTO', sql_pg, flags=re.IGNORECASE)
            sql_pg = sql_pg.rstrip().rstrip(';')
            if "system_settings" in sql_pg.lower():
                sql_pg += " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"

        # Function translation
        sql_pg = re.sub(r'\bIFNULL\s*\(', 'COALESCE(', sql_pg, flags=re.IGNORECASE)
        sql_pg = re.sub(r"DATE\s*\(\s*'now'\s*\)", 'CURRENT_DATE', sql_pg, flags=re.IGNORECASE)
        sql_pg = re.sub(r"DATETIME\s*\(\s*'now'\s*\)", 'CURRENT_TIMESTAMP', sql_pg, flags=re.IGNORECASE)
        sql_pg = re.sub(r"DEFAULT\s+CURRENT_TIMESTAMP", "DEFAULT CURRENT_TIMESTAMP", sql_pg, flags=re.IGNORECASE)
        
        # SQLite to Postgres Type/Constraint translation
        if "CREATE TABLE" in sql_pg.upper():
            sql_pg = re.sub(r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b', 'SERIAL PRIMARY KEY', sql_pg, flags=re.IGNORECASE)
            sql_pg = re.sub(r'\bDATETIME\b', 'TIMESTAMP', sql_pg, flags=re.IGNORECASE)
            sql_pg = re.sub(r'\bBLOB\b', 'BYTEA', sql_pg, flags=re.IGNORECASE)
        
        # 3. Handle lastrowid for INSERTs
        is_insert = sql_pg.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in sql_pg.upper() and "ON CONFLICT" not in sql_pg.upper():
             match = re.search(r"INSERT\s+INTO\s+([a-zA-Z0-9_]+)", sql_pg, re.IGNORECASE)
             if match:
                 table_name = match.group(1)
                 if table_name not in ['system_users', 'active_sessions', 'system_settings', 'audit_logs', 'parent_tokens']: 
                     sql_pg += " RETURNING id"
        
        try:
            self.cursor.execute(sql_pg, params)
            self._rowcount = self.cursor.rowcount
            
            if is_insert and "RETURNING id" in sql_pg:
                row = self.cursor.fetchone()
                if row:
                    self._lastrowid = row['id'] if isinstance(row, dict) else row[0]
            else:
                self._lastrowid = None
                
            return self
        except Exception as e:
            logger.error(f"SQL Error: {e} | Query: {sql_pg} | Params: {params}")
            raise e

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def description(self):
        """Expose DB-API column metadata from the wrapped psycopg2 cursor.

        Several shared query paths use ``cursor.description`` to map tuple rows
        into dictionaries.  The wrapper previously hid that standard cursor
        attribute, causing PostgreSQL-only 500 responses after a successful
        attendance insert.
        """
        return self.cursor.description
        
    def close(self):
        self.cursor.close()
        
    @property
    def rowcount(self):
        return self._rowcount
        
    @property
    def lastrowid(self):
        return self._lastrowid

    def __iter__(self):
        return self.cursor.__iter__()

class SQLiteConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn
        self._is_pg = False
        self._row_factory = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            try: self.conn.rollback()
            except: pass
        else:
            try: self.conn.commit()
            except: pass
        self.conn.close()

    @property
    def row_factory(self):
        return self.conn.row_factory

    @row_factory.setter
    def row_factory(self, val):
        self.conn.row_factory = val

    def cursor(self):
        return self.conn.cursor()

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def rollback(self):
        self.conn.rollback()

    def execute(self, sql, params=None):
        if params is None: params = []
        return self.conn.execute(sql, params)

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn
        self._row_factory = None
        self._is_pg = True
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            try: self.rollback()
            except: pass
        self.close()

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, val):
        self._row_factory = val

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor(cursor_factory=DictCursor))

    def commit(self):
        self.conn.commit()

    def close(self):
        if self._closed:
            return
        self._closed = True
        # Always rollback any uncommitted/aborted transaction before returning to pool
        # to prevent poisoned connections from cascading to other requests.
        try:
            if ext:
                status = self.conn.get_transaction_status()
                if status != ext.TRANSACTION_STATUS_IDLE:
                    self.conn.rollback()
        except Exception:
            pass
        pool = get_pg_pool()
        if pool:
            try:
                pool.putconn(self.conn)
            except Exception as e:
                logger.error(f"Error returning connection to pool: {e}")
                try: self.conn.close()
                except: pass
        else:
            try: self.conn.close()
            except: pass

    def __del__(self):
        try:
            self.close()
        except:
            pass

    def rollback(self):
        self.conn.rollback()

    def execute(self, sql, params=None):
        c = self.cursor()
        c.execute(sql, params)
        return c

def get_db_connection(timeout=30):
    global _IS_FALLBACK_MODE, _LAST_PG_RETRY_TIME
    
    current_time = time.time()
    
    # 1. Try PostgreSQL (Primary) if DATABASE_URL is set and we're not in cooldown
    # We still try if not in fallback mode, but if we are in fallback, we wait for cooldown
    should_try_pg = DATABASE_URL and (not _IS_FALLBACK_MODE or (current_time - _LAST_PG_RETRY_TIME) > _PG_COOLDOWN_SECONDS)
    
    if should_try_pg:
        try:
            pool = get_pg_pool()
            if pool:
                conn = pool.getconn()
                # Ensure the connection is in a clean state.
                # If a previous request aborted a transaction but didn't rollback, we must fix it here.
                try:
                    if ext:
                        status = conn.get_transaction_status()
                        if status == ext.TRANSACTION_STATUS_INERROR:
                            logger.warning("Retrieved 'aborted' connection from pool. Performing recovery rollback.")
                            conn.rollback()
                        elif status != ext.TRANSACTION_STATUS_IDLE:
                            # Also rollback if it's IN_TRANS (unfinished transaction) to prevent cross-request leakage
                            conn.rollback()
                except Exception as ex:
                    logger.debug(f"Failed to check/reset connection status: {ex}")
            else:
                if psycopg2:
                    conn = psycopg2.connect(DATABASE_URL, connect_timeout=timeout)
                else:
                    raise Exception("PostgreSQL requested but psycopg2 is not installed.")
            
            try:
                # If it's a new connection or we want to ensure settings
                conn.autocommit = False
                cur = conn.cursor()
                cur.execute("SET statement_timeout TO 60000")
                cur.close()
            except Exception:
                pass
            
            if _IS_FALLBACK_MODE:
                logger.info("PostgreSQL recovered! Switching back to primary.")
            
            _IS_FALLBACK_MODE = False
            return PostgresConnectionWrapper(conn)
        except Exception as e:
            # Only log the error once when it first fails or after cooldown
            if not _IS_FALLBACK_MODE:
                logger.error(f"PostgreSQL Connection failed, falling back to SQLite: {e}")
            else:
                # Optional: log a debug or low-level message
                pass
            
            _IS_FALLBACK_MODE = True
            _LAST_PG_RETRY_TIME = current_time
    
    # 2. SQLite (Fallback)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=timeout, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return SQLiteConnectionWrapper(conn)
    except Exception as e:
        logger.error(f"SQLite Connection failed: {e}")
        raise e

def get_backup_db_connection(timeout=20):
    """Returns a connection to the backup SQLite database."""
    try:
        conn = sqlite3.connect(DB_BACKUP_PATH, timeout=timeout, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return SQLiteConnectionWrapper(conn)
    except Exception as e:
        logger.error(f"Backup SQLite Connection failed: {e}")
        raise e

def is_fallback_mode():
    return _IS_FALLBACK_MODE

def init_schemas():
    """Initializes schemas for both databases to ensure they are ready for failover."""
    logger.info("Initializing Database Schemas...")
    
    # Init primary if available
    if DATABASE_URL:
        try:
            if psycopg2:
                conn = psycopg2.connect(DATABASE_URL)
                _init_pg_schema_on_conn(conn)
                conn.close()
                logger.info("PostgreSQL Schema initialized.")
            else:
                raise Exception("PostgreSQL requested but psycopg2 is not installed.")
        except Exception as e:
            logger.warning(f"Could not initialize PostgreSQL schema: {e}")

    # Init fallback
    try:
        conn = sqlite3.connect(DB_PATH)
        init_sqlite_schema(conn)
        conn.close()
        logger.info("SQLite Schema initialized.")
    except Exception as e:
        logger.error(f"Could not initialize SQLite schema: {e}")

    # Init backup
    try:
        conn = get_backup_db_connection()
        _init_backup_schema_on_conn(conn)
        conn.close()
        logger.info("Backup SQLite Schema initialized.")
    except Exception as e:
        logger.error(f"Could not initialize Backup SQLite schema: {e}")

def _init_pg_schema_on_conn(conn):
    cur = conn.cursor()
    # Using the existing DDL from init_postgres_schema
    queries = [
        "CREATE TABLE IF NOT EXISTS vendors (id SERIAL PRIMARY KEY, company_name TEXT NOT NULL, email TEXT, phone TEXT, address TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'active', registration_config TEXT, contact_person TEXT, web_login_enabled INTEGER DEFAULT 1, frontend_bundle_id TEXT, backend_service_id TEXT, vertical TEXT, attendance_type TEXT DEFAULT 'total_time', retention_days INTEGER DEFAULT 90, num_rectors INTEGER DEFAULT 0, num_hods INTEGER DEFAULT 0, departments TEXT)",
        "CREATE TABLE IF NOT EXISTS companies (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), name TEXT, working_hours REAL, shifts TEXT, draft_timetable TEXT, live_timetable TEXT, last_modified_by TEXT, last_modified_at TIMESTAMP, published_by TEXT, published_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS faces (id SERIAL PRIMARY KEY, name TEXT, templates TEXT, face_image TEXT, department TEXT, designation TEXT, phone TEXT, shift TEXT, daily_wage REAL DEFAULT 0, basic_salary REAL DEFAULT 0, hra REAL DEFAULT 0, conveyance REAL DEFAULT 0, special_allowance REAL DEFAULT 0, pf_enabled INTEGER DEFAULT 0, esi_enabled INTEGER DEFAULT 0, gratuity_enabled INTEGER DEFAULT 0, professional_tax REAL DEFAULT 0, late_allowance_days INTEGER, late_deduction_amount REAL DEFAULT 0, vendor_id INTEGER REFERENCES vendors(id), custom_data TEXT, display_id INTEGER, joining_date DATE)",
        "CREATE TABLE IF NOT EXISTS advances (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), person_id INTEGER REFERENCES faces(id), amount REAL, amount_cash REAL DEFAULT 0, amount_online REAL DEFAULT 0, date DATE, status TEXT DEFAULT 'pending', approved_by TEXT, approved_at TIMESTAMP, rejection_reason TEXT, deduction_month TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS attendance (id SERIAL PRIMARY KEY, name TEXT, timestamp TIMESTAMP, status TEXT, captured_image TEXT, activity TEXT, is_late INTEGER DEFAULT 0, device_id TEXT, vendor_id INTEGER REFERENCES vendors(id), person_id INTEGER REFERENCES faces(id), attendance_date DATE, class_year TEXT, division TEXT, branch TEXT, subject TEXT, lecture_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS system_users (username TEXT PRIMARY KEY, password TEXT, password_plain TEXT, role TEXT, vendor_id INTEGER REFERENCES vendors(id), person_id INTEGER REFERENCES faces(id), has_set_password INTEGER DEFAULT 0, last_active_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS subscriptions (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id) UNIQUE, plan_type TEXT, start_date TIMESTAMP, end_date TIMESTAMP, status TEXT DEFAULT 'active', max_users INTEGER, max_employees INTEGER, cost_per_user REAL, setup_fee REAL, setup_fee_paid INTEGER, features TEXT, max_mobile_devices INTEGER DEFAULT 1, cost_per_employee REAL DEFAULT 0, grace_period_days INTEGER DEFAULT 0, max_web_sessions INTEGER DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS vendor_devices (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), device_id TEXT, device_name TEXT, registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_login_at TIMESTAMP, last_active_at TIMESTAMP, battery_level REAL, geofence_lat REAL, geofence_lng REAL, geofence_radius REAL DEFAULT 0, last_lat REAL, last_lng REAL, UNIQUE(vendor_id, device_id))",
        "CREATE TABLE IF NOT EXISTS vendor_device_slots (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), slot_name TEXT, assigned_device_id TEXT, assigned_at TIMESTAMP, UNIQUE(vendor_id, slot_name))",
        "CREATE TABLE IF NOT EXISTS active_sessions (token TEXT PRIMARY KEY, username TEXT, vendor_id INTEGER, device_id TEXT, platform TEXT, last_active TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS invoices (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), amount REAL, status TEXT DEFAULT 'generated', due_date DATE, generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, paid_at TIMESTAMP, invoice_date DATE, details TEXT)",
        "CREATE TABLE IF NOT EXISTS audit_logs (id SERIAL PRIMARY KEY, actor_username TEXT, actor_role TEXT, target_vendor_id INTEGER, action TEXT, details TEXT, ip TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)",
        "CREATE TABLE IF NOT EXISTS parent_users (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), username TEXT UNIQUE, password TEXT, contact_email TEXT, contact_phone TEXT, student_number TEXT, selected_person_id INTEGER, device_id TEXT, fcm_token TEXT, session_version INTEGER DEFAULT 1, face_image TEXT, face_template TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS leave_requests (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), student_id INTEGER REFERENCES faces(id), leave_type TEXT, reason TEXT, start_date DATE, end_date DATE, start_time TEXT, end_time TEXT, parent_status TEXT DEFAULT 'pending', rector_status TEXT DEFAULT 'pending', hod_status TEXT DEFAULT 'pending', final_status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS student_parents (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), person_id INTEGER REFERENCES faces(id), parent_id INTEGER REFERENCES parent_users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(person_id, parent_id))",
        "CREATE TABLE IF NOT EXISTS parent_tokens (token TEXT PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), student_number TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS person_embeddings (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), person_id INTEGER REFERENCES faces(id), class_year TEXT, division TEXT, branch TEXT, vec BYTEA, dim INTEGER, struct_vec BYTEA, landmarks_3d TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS class_batches (id TEXT PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), class_year TEXT, division TEXT, branch TEXT, status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS class_batch_items (id TEXT PRIMARY KEY, batch_id TEXT REFERENCES class_batches(id), seq INTEGER, image_b64 TEXT, annotated_b64 TEXT, faces_json TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS leave_staff (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), name TEXT, role TEXT, pin TEXT, department TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS archive_objects (id SERIAL PRIMARY KEY, vendor_id INTEGER, table_name TEXT, row_json TEXT, archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, restored_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS bulk_attendance_config (id SERIAL PRIMARY KEY, vendor_id INTEGER UNIQUE REFERENCES vendors(id), fields TEXT DEFAULT '[]', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS lectures (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), subject TEXT NOT NULL, class_year TEXT, division TEXT, branch TEXT, lecture_date DATE, start_time TEXT, teacher TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS lecture_attendance (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), lecture_id INTEGER REFERENCES lectures(id), person_id INTEGER REFERENCES faces(id), status TEXT DEFAULT 'present', marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(lecture_id, person_id))",
        "CREATE TABLE IF NOT EXISTS classes (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), class_year TEXT, division TEXT, branch TEXT, label TEXT, mapped_subjects TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS face_reset_requests (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), parent_id INTEGER REFERENCES parent_users(id), reason TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS registration_batches (id TEXT PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS registration_batch_items (id TEXT PRIMARY KEY, batch_id TEXT REFERENCES registration_batches(id), seq INTEGER, image_b64 TEXT, annotated_b64 TEXT, faces_json TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS subject_master (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), class_year TEXT, branch TEXT, subject_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(vendor_id, class_year, branch, subject_name))",
        "CREATE TABLE IF NOT EXISTS class_thresholds (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), class_year TEXT, division TEXT, branch TEXT, threshold REAL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(vendor_id, class_year, division, branch))",
        "CREATE TABLE IF NOT EXISTS automated_report_schedules (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id) UNIQUE NOT NULL, enabled INTEGER DEFAULT 0, recipient_email TEXT, timezone TEXT DEFAULT 'Asia/Kolkata', send_time TEXT DEFAULT '08:00', operational_day_cutoff TEXT DEFAULT '07:00', grace_minutes INTEGER DEFAULT 30, frequencies TEXT DEFAULT '[]', daily_days TEXT DEFAULT '[]', weekly_days TEXT DEFAULT '[]', monthly_mode TEXT DEFAULT 'last_working_day', monthly_day INTEGER, report_types TEXT DEFAULT '[\"attendance_detail\", \"attendance_summary\"]', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS automated_report_deliveries (id SERIAL PRIMARY KEY, schedule_id INTEGER REFERENCES automated_report_schedules(id) NOT NULL, vendor_id INTEGER REFERENCES vendors(id) NOT NULL, frequency TEXT NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0, recipient_email TEXT, message_id TEXT, error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, sent_at TIMESTAMP, UNIQUE(schedule_id, frequency, period_start, period_end))",
        "CREATE TABLE IF NOT EXISTS xchat_conversations (id TEXT PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id) NOT NULL, username TEXT NOT NULL, title TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS xchat_messages (id SERIAL PRIMARY KEY, conversation_id TEXT REFERENCES xchat_conversations(id) ON DELETE CASCADE, vendor_id INTEGER REFERENCES vendors(id) NOT NULL, username TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, tool_name TEXT, message_metadata TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",

        # --- Performance Indices ---
        "CREATE INDEX IF NOT EXISTS idx_attendance_vendor_time ON attendance(vendor_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_attendance_person ON attendance(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_faces_vendor ON faces(vendor_id)",
        "CREATE INDEX IF NOT EXISTS idx_system_users_vendor ON system_users(vendor_id)",
        "CREATE INDEX IF NOT EXISTS idx_active_sessions_vendor ON active_sessions(vendor_id)",
        "CREATE INDEX IF NOT EXISTS idx_active_sessions_user ON active_sessions(username)",
        "CREATE INDEX IF NOT EXISTS idx_lectures_vendor ON lectures(vendor_id, lecture_date)",
        "CREATE INDEX IF NOT EXISTS idx_lecture_attendance_lecture ON lecture_attendance(lecture_id)",
        "CREATE INDEX IF NOT EXISTS idx_lecture_attendance_person ON lecture_attendance(person_id, vendor_id)"
        ,"CREATE INDEX IF NOT EXISTS idx_auto_report_due ON automated_report_schedules(enabled, vendor_id)"
        ,"CREATE INDEX IF NOT EXISTS idx_auto_report_delivery_vendor ON automated_report_deliveries(vendor_id, created_at)"
        ,"CREATE INDEX IF NOT EXISTS idx_xchat_conversation_owner ON xchat_conversations(vendor_id, username, updated_at)"
        ,"CREATE INDEX IF NOT EXISTS idx_xchat_message_conversation ON xchat_messages(conversation_id, vendor_id, created_at)"
    ]
    for q in queries:
        try:
            cur.execute(q)
        except Exception as e:
            # If a table already exists or something similar, it might fail if not using IF NOT EXISTS
            # but Postgres IF NOT EXISTS should be fine.
            logger.warning(f"Error executing schema query: {e}")
            if getattr(conn, "_is_pg", False): conn.rollback()
            cur = conn.cursor()
    
    # COMMIT early: Ensure tables are created before starting migrations
    if getattr(conn, "_is_pg", False):
        conn.commit()
    cur = conn.cursor()
    
    # --- Migrations: Add columns and update data individually for robustness ---
    is_pg = "psycopg2" in str(type(conn)) or getattr(conn, "_is_pg", False)
    
    def run_migration(query, msg, params=None):
        try:
            cur.execute(query, params)
            if is_pg: conn.commit() # Commit each migration independently
            else: conn.commit()
        except Exception as e:
            if is_pg: conn.rollback()
            # Suppress "already exists" errors for columns
            err_msg = str(e).lower()
            if "already exists" in err_msg or "duplicate column" in err_msg or "already a constraint" in err_msg:
                # logger.debug(f"Migration skip ({msg}): {e}")
                pass
            else:
                logger.error(f"Migration error ({msg}): {e}")

    # 1. Add missing columns
    cols = [
        ("vendor_devices", "last_active_at", "TIMESTAMP"),
        ("vendor_devices", "battery_level", "REAL"),
        ("vendor_devices", "geofence_lat", "REAL"),
        ("vendor_devices", "geofence_lng", "REAL"),
        ("vendor_devices", "geofence_radius", "REAL DEFAULT 0"),
        ("vendor_devices", "last_lat", "REAL"),
        ("vendor_devices", "last_lng", "REAL"),
        ("parent_users", "face_image", "TEXT"),
        ("parent_users", "face_template", "TEXT"),
        ("parent_users", "vendor_id", "INTEGER"),
        ("vendors", "num_rectors", "INTEGER DEFAULT 0"),
        ("vendors", "num_hods", "INTEGER DEFAULT 0"),
        ("vendors", "departments", "TEXT"),
        ("system_users", "person_id", "INTEGER"),
        ("system_users", "password_plain", "TEXT"),
        ("system_users", "has_set_password", "INTEGER DEFAULT 0"),
        ("system_users", "last_active_at", "TIMESTAMP"),
        ("subscriptions", "max_web_sessions", "INTEGER DEFAULT 1"),
        ("subscriptions", "grace_period_days", "INTEGER DEFAULT 0"),
        ("subscriptions", "cost_per_employee", "REAL DEFAULT 0"),
        ("subscriptions", "setup_fee", "REAL DEFAULT 0"),
        ("subscriptions", "setup_fee_paid", "INTEGER DEFAULT 0"),
        ("faces", "basic_salary", "REAL DEFAULT 0"),
        ("faces", "hra", "REAL DEFAULT 0"),
        ("faces", "conveyance", "REAL DEFAULT 0"),
        ("faces", "special_allowance", "REAL DEFAULT 0"),
        ("faces", "pf_enabled", "INTEGER DEFAULT 0"),
        ("faces", "esi_enabled", "INTEGER DEFAULT 0"),
        ("faces", "gratuity_enabled", "INTEGER DEFAULT 0"),
        ("faces", "professional_tax", "REAL DEFAULT 0"),
        ("faces", "joining_date", "DATE"),
        ("advances", "amount_cash", "REAL DEFAULT 0"),
        ("advances", "amount_online", "REAL DEFAULT 0"),
        ("advances", "approved_by", "TEXT"),
        ("advances", "approved_at", "TIMESTAMP"),
        ("advances", "rejection_reason", "TEXT"),
        ("classes", "mapped_subjects", "TEXT"),
        ("attendance", "class_year", "TEXT"),
        ("attendance", "division", "TEXT"),
        ("attendance", "branch", "TEXT"),
        ("attendance", "subject", "TEXT"),
        ("attendance", "lecture_id", "INTEGER"),
        ("attendance", "attendance_date", "DATE"),
        ("person_embeddings", "struct_vec", "BYTEA"),
        ("person_embeddings", "landmarks_3d", "TEXT"),
    ]
    
    for table, col, col_type in cols:
        if is_pg:
            run_migration(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}", f"Add {col} to {table}")
        else:
            run_migration(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}", f"Add {col} to {table}")

    # 1b. PostgreSQL specific unique constraints
    if is_pg:
        # First clean up duplicates to avoid migration failure
        run_migration("DELETE FROM student_parents a USING student_parents b WHERE a.id < b.id AND a.person_id = b.person_id AND a.parent_id = b.parent_id", "Cleanup student_parents duplicates")
        # Try to add unique constraint (will fail if already exists, but run_migration handles that)
        run_migration("ALTER TABLE student_parents ADD CONSTRAINT student_parents_unique_person_parent UNIQUE (person_id, parent_id)", "Add unique constraint to student_parents")

    # 2. Data Migrations
    if is_pg:
        # Link student logins
        run_migration("""
            UPDATE system_users 
            SET person_id = f.id
            FROM faces f
            WHERE system_users.role = 'user' 
              AND system_users.person_id IS NULL 
              AND (
                f.custom_data::jsonb->>'student_number' = system_users.username OR 
                f.custom_data::jsonb->>'admission_number' = system_users.username OR 
                f.custom_data::jsonb->>'roll_number' = system_users.username
              )
              AND f.vendor_id = system_users.vendor_id
        """, "Link student logins (PG)")
        
    else:
        # Link student logins (SQLite)
        run_migration("""
            UPDATE system_users 
            SET person_id = (
                SELECT f.id FROM faces f 
                WHERE f.vendor_id = system_users.vendor_id 
                  AND (
                    json_extract(f.custom_data, '$.student_number') = system_users.username OR 
                    json_extract(f.custom_data, '$.admission_number') = system_users.username OR 
                    json_extract(f.custom_data, '$.roll_number') = system_users.username
                  )
                LIMIT 1
            )
            WHERE role = 'user' AND person_id IS NULL
        """, "Link student logins (SQLite)")
        
    # 3. Preserve the legacy default/custom marker, then scrub recoverable passwords.
    run_migration("""
        UPDATE system_users SET has_set_password = 1 
        WHERE role = 'user' AND password != password_plain AND password_plain IS NOT NULL
    """, "Initialize has_set_password")
    run_migration("UPDATE system_users SET password_plain = NULL WHERE password_plain IS NOT NULL", "Remove legacy plaintext passwords")

    conn.commit()
    cur.close()

def init_sqlite_schema(conn):
    cur = conn.cursor()
    # Simplified SQLite versions (using INTEGER PRIMARY KEY AUTOINCREMENT)
    queries = [
        "CREATE TABLE IF NOT EXISTS vendors (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT NOT NULL, email TEXT, phone TEXT, address TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'active', registration_config TEXT, contact_person TEXT, web_login_enabled INTEGER DEFAULT 1, frontend_bundle_id TEXT, backend_service_id TEXT, vertical TEXT, attendance_type TEXT DEFAULT 'total_time', retention_days INTEGER DEFAULT 90, num_rectors INTEGER DEFAULT 0, num_hods INTEGER DEFAULT 0, departments TEXT)",
        "CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, name TEXT, working_hours REAL, shifts TEXT, draft_timetable TEXT, live_timetable TEXT, last_modified_by TEXT, last_modified_at DATETIME, published_by TEXT, published_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS faces (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, templates TEXT, face_image TEXT, department TEXT, designation TEXT, phone TEXT, shift TEXT, daily_wage REAL DEFAULT 0, basic_salary REAL DEFAULT 0, hra REAL DEFAULT 0, conveyance REAL DEFAULT 0, special_allowance REAL DEFAULT 0, pf_enabled INTEGER DEFAULT 0, esi_enabled INTEGER DEFAULT 0, gratuity_enabled INTEGER DEFAULT 0, professional_tax REAL DEFAULT 0, late_allowance_days INTEGER, late_deduction_amount REAL DEFAULT 0, vendor_id INTEGER, custom_data TEXT, display_id INTEGER, joining_date DATE)",
        "CREATE TABLE IF NOT EXISTS advances (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, person_id INTEGER, amount REAL, amount_cash REAL DEFAULT 0, amount_online REAL DEFAULT 0, date DATE, status TEXT DEFAULT 'pending', approved_by TEXT, approved_at DATETIME, rejection_reason TEXT, deduction_month TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, timestamp DATETIME, status TEXT, captured_image TEXT, activity TEXT, is_late INTEGER DEFAULT 0, device_id TEXT, vendor_id INTEGER, person_id INTEGER, attendance_date DATE, class_year TEXT, division TEXT, branch TEXT, subject TEXT, lecture_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS system_users (username TEXT PRIMARY KEY, password TEXT, password_plain TEXT, role TEXT, vendor_id INTEGER, person_id INTEGER, has_set_password INTEGER DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER UNIQUE, plan_type TEXT, start_date DATETIME, end_date DATETIME, status TEXT DEFAULT 'active', max_users INTEGER, max_employees INTEGER, cost_per_user REAL, setup_fee REAL, setup_fee_paid INTEGER, features TEXT, max_mobile_devices INTEGER DEFAULT 1, cost_per_employee REAL DEFAULT 0, grace_period_days INTEGER DEFAULT 0, max_web_sessions INTEGER DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS vendor_devices (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, device_id TEXT, device_name TEXT, registered_at DATETIME DEFAULT CURRENT_TIMESTAMP, last_login_at DATETIME, last_active_at DATETIME, battery_level REAL, geofence_lat REAL, geofence_lng REAL, geofence_radius REAL DEFAULT 0, last_lat REAL, last_lng REAL, UNIQUE(vendor_id, device_id))",
        "CREATE TABLE IF NOT EXISTS vendor_device_slots (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, slot_name TEXT, assigned_device_id TEXT, assigned_at DATETIME, UNIQUE(vendor_id, slot_name))",
        "CREATE TABLE IF NOT EXISTS active_sessions (token TEXT PRIMARY KEY, username TEXT, vendor_id INTEGER, device_id TEXT, platform TEXT, last_active DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, amount REAL, status TEXT DEFAULT 'generated', due_date DATE, generated_at DATETIME DEFAULT CURRENT_TIMESTAMP, paid_at DATETIME, invoice_date DATE, details TEXT)",
        "CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_username TEXT, actor_role TEXT, target_vendor_id INTEGER, action TEXT, details TEXT, ip TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)",
        "CREATE TABLE IF NOT EXISTS parent_users (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, username TEXT UNIQUE, password TEXT, contact_email TEXT, contact_phone TEXT, student_number TEXT, selected_person_id INTEGER, device_id TEXT, fcm_token TEXT, session_version INTEGER DEFAULT 1, face_image TEXT, face_template TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS leave_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, student_id INTEGER, leave_type TEXT, reason TEXT, start_date DATE, end_date DATE, start_time TEXT, end_time TEXT, parent_status TEXT DEFAULT 'pending', rector_status TEXT DEFAULT 'pending', hod_status TEXT DEFAULT 'pending', final_status TEXT DEFAULT 'pending', created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS student_parents (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, person_id INTEGER, parent_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(person_id, parent_id))",
        "CREATE TABLE IF NOT EXISTS parent_tokens (token TEXT PRIMARY KEY, vendor_id INTEGER, student_number TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS person_embeddings (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, person_id INTEGER, class_year TEXT, division TEXT, branch TEXT, vec BLOB, dim INTEGER, struct_vec BLOB, landmarks_3d TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS class_batches (id TEXT PRIMARY KEY, vendor_id INTEGER, class_year TEXT, division TEXT, branch TEXT, status TEXT DEFAULT 'active', created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS class_batch_items (id TEXT PRIMARY KEY, batch_id TEXT, seq INTEGER, image_b64 TEXT, annotated_b64 TEXT, faces_json TEXT, status TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS leave_staff (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, name TEXT, role TEXT, pin TEXT, department TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS archive_objects (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, table_name TEXT, row_json TEXT, archived_at DATETIME DEFAULT CURRENT_TIMESTAMP, restored_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS bulk_attendance_config (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER UNIQUE, fields TEXT DEFAULT '[]', updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS lectures (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, subject TEXT NOT NULL, class_year TEXT, division TEXT, branch TEXT, lecture_date DATE, start_time TEXT, teacher TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS lecture_attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, lecture_id INTEGER, person_id INTEGER, status TEXT DEFAULT 'present', marked_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(lecture_id, person_id))",
        "CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, class_year TEXT, division TEXT, branch TEXT, label TEXT, mapped_subjects TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS registration_batches (id TEXT PRIMARY KEY, vendor_id INTEGER, status TEXT DEFAULT 'active', created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS registration_batch_items (id TEXT PRIMARY KEY, batch_id TEXT, seq INTEGER, image_b64 TEXT, annotated_b64 TEXT, faces_json TEXT, status TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS subject_master (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, class_year TEXT, branch TEXT, subject_name TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(vendor_id, class_year, branch, subject_name))",
        "CREATE TABLE IF NOT EXISTS class_thresholds (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, class_year TEXT, division TEXT, branch TEXT, threshold REAL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(vendor_id, class_year, division, branch))",
        "CREATE TABLE IF NOT EXISTS automated_report_schedules (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER UNIQUE NOT NULL, enabled INTEGER DEFAULT 0, recipient_email TEXT, timezone TEXT DEFAULT 'Asia/Kolkata', send_time TEXT DEFAULT '08:00', operational_day_cutoff TEXT DEFAULT '07:00', grace_minutes INTEGER DEFAULT 30, frequencies TEXT DEFAULT '[]', daily_days TEXT DEFAULT '[]', weekly_days TEXT DEFAULT '[]', monthly_mode TEXT DEFAULT 'last_working_day', monthly_day INTEGER, report_types TEXT DEFAULT '[\"attendance_detail\", \"attendance_summary\"]', created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS automated_report_deliveries (id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id INTEGER NOT NULL, vendor_id INTEGER NOT NULL, frequency TEXT NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0, recipient_email TEXT, message_id TEXT, error TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, sent_at DATETIME, UNIQUE(schedule_id, frequency, period_start, period_end))",
        "CREATE TABLE IF NOT EXISTS xchat_conversations (id TEXT PRIMARY KEY, vendor_id INTEGER NOT NULL, username TEXT NOT NULL, title TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS xchat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, vendor_id INTEGER NOT NULL, username TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, tool_name TEXT, message_metadata TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(conversation_id) REFERENCES xchat_conversations(id) ON DELETE CASCADE)",

        # --- Performance Indices ---
        "CREATE INDEX IF NOT EXISTS idx_attendance_vendor_time ON attendance(vendor_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_attendance_person ON attendance(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_faces_vendor ON faces(vendor_id)",
        "CREATE INDEX IF NOT EXISTS idx_system_users_vendor ON system_users(vendor_id)",
        "CREATE INDEX IF NOT EXISTS idx_active_sessions_vendor ON active_sessions(vendor_id)",
        "CREATE INDEX IF NOT EXISTS idx_active_sessions_user ON active_sessions(username)",
        "CREATE INDEX IF NOT EXISTS idx_lectures_vendor ON lectures(vendor_id, lecture_date)",
        "CREATE INDEX IF NOT EXISTS idx_lecture_attendance_lecture ON lecture_attendance(lecture_id)",
        "CREATE INDEX IF NOT EXISTS idx_lecture_attendance_person ON lecture_attendance(person_id, vendor_id)"
        ,"CREATE INDEX IF NOT EXISTS idx_auto_report_due ON automated_report_schedules(enabled, vendor_id)"
        ,"CREATE INDEX IF NOT EXISTS idx_auto_report_delivery_vendor ON automated_report_deliveries(vendor_id, created_at)"
        ,"CREATE INDEX IF NOT EXISTS idx_xchat_conversation_owner ON xchat_conversations(vendor_id, username, updated_at)"
        ,"CREATE INDEX IF NOT EXISTS idx_xchat_message_conversation ON xchat_messages(conversation_id, vendor_id, created_at)"
    ]
    for q in queries:
        cur.execute(q)
    
    # Migration: Add columns if they don't exist
    for col in ["last_active_at DATETIME", "battery_level REAL", "geofence_lat REAL", "geofence_lng REAL", "geofence_radius REAL DEFAULT 0", "last_lat REAL", "last_lng REAL"]:
        try:
            cur.execute(f"ALTER TABLE vendor_devices ADD COLUMN {col}")
        except Exception:
            pass
        try:
            cur.execute(f"ALTER TABLE parent_users ADD COLUMN {col}")
        except Exception:
            pass
    
    # Migration: system_users
    try:
        cur.execute("ALTER TABLE system_users ADD COLUMN password_plain TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE system_users ADD COLUMN has_set_password INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE system_users ADD COLUMN person_id INTEGER")
    except Exception:
        pass

    try:
        cur.execute("UPDATE system_users SET has_set_password = 1 WHERE role = 'user' AND password != password_plain AND password_plain IS NOT NULL")
    except Exception:
        pass
    
    for col in ["face_image TEXT", "face_template TEXT", "vendor_id INTEGER"]:
        try:
            cur.execute(f"ALTER TABLE parent_users ADD COLUMN {col}")
        except Exception:
            pass
            
    for col in ["num_rectors INTEGER DEFAULT 0", "num_hods INTEGER DEFAULT 0", "departments TEXT"]:
        try:
            cur.execute(f"ALTER TABLE vendors ADD COLUMN {col}")
        except Exception:
            pass
            
    for col in ["max_web_sessions INTEGER DEFAULT 1", "grace_period_days INTEGER DEFAULT 0", "cost_per_employee REAL DEFAULT 0", "setup_fee REAL DEFAULT 0", "setup_fee_paid INTEGER DEFAULT 0"]:
        try:
            cur.execute(f"ALTER TABLE subscriptions ADD COLUMN {col}")
        except Exception:
            pass
            
    for col in ["basic_salary REAL DEFAULT 0", "hra REAL DEFAULT 0", "conveyance REAL DEFAULT 0", "special_allowance REAL DEFAULT 0", "pf_enabled INTEGER DEFAULT 0", "esi_enabled INTEGER DEFAULT 0", "gratuity_enabled INTEGER DEFAULT 0", "professional_tax REAL DEFAULT 0", "joining_date DATE"]:
        try:
            cur.execute(f"ALTER TABLE faces ADD COLUMN {col}")
        except Exception:
            pass

    for col in ["amount_cash REAL DEFAULT 0", "amount_online REAL DEFAULT 0", "approved_by TEXT", "approved_at DATETIME", "rejection_reason TEXT"]:
        try:
            cur.execute(f"ALTER TABLE advances ADD COLUMN {col}")
        except Exception:
            pass

    for col in ["struct_vec BLOB", "landmarks_3d TEXT"]:
        try:
            cur.execute(f"ALTER TABLE person_embeddings ADD COLUMN {col}")
        except Exception:
            pass

    conn.commit()
    cur.close()


def _init_backup_schema_on_conn(conn):
    cur = conn.cursor()
    # Backup DB only needs data tables for archival
    queries = [
        "CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY, name TEXT, timestamp DATETIME, status TEXT, captured_image TEXT, activity TEXT, is_late INTEGER DEFAULT 0, device_id TEXT, vendor_id INTEGER, person_id INTEGER, archived_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS backup_metadata (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, start_date DATETIME, end_date DATETIME, record_count INTEGER, status TEXT, archived_by TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    ]
    for q in queries:
        cur.execute(q)
    conn.commit()
    cur.close()

def check_and_recover():
    """Checks if PostgreSQL is available and if data needs to be migrated from SQLite."""
    if not DATABASE_URL:
        return

    try:
        # Check if SQlite has data
        conn_lite = sqlite3.connect(DB_PATH)
        cur_lite = conn_lite.cursor()
        
        # Simple heuristic: check if audit_logs or attendance has any rows
        has_data = False
        tables_to_check = ['attendance', 'faces', 'vendors', 'audit_logs']
        for table in tables_to_check:
            try:
                cur_lite.execute(f"SELECT COUNT(*) FROM {table}")
                if cur_lite.fetchone()[0] > 0:
                    has_data = True
                    break
            except Exception:
                continue
        conn_lite.close()

        if has_data:
            logger.info("Found data in SQLite fallback. Attempting recovery to PostgreSQL...")
            try:
                import migrate_to_postgres
                if migrate_to_postgres.run_safe_migration():
                    logger.info("Recovery/Migration successful. Clearing SQLite fallback data...")
                    
                    # Open connection again to clear tables
                    conn_lite = sqlite3.connect(DB_PATH)
                    cur_lite = conn_lite.cursor()
                    tables_to_clear = ['attendance', 'faces', 'vendors', 'audit_logs', 'system_settings', 'companies', 'subscriptions', 'active_sessions', 'vendor_devices', 'vendor_device_slots', 'invoices']
                    for table in tables_to_clear:
                        try:
                            cur_lite.execute(f"DELETE FROM {table}")
                        except Exception:
                            continue
                    conn_lite.commit()
                    conn_lite.close()
                    logger.info("SQLite fallback data cleared.")
                else:
                    logger.warning("Recovery migration reported failure. SQLite data preserved for next attempt.")
            except Exception as e:
                logger.error(f"Recovery failed: {e}")
    except Exception as e:
        logger.error(f"Error during recovery check: {e}")

def ensure_archive_table():
    """Ensures the archive_objects table exists for vendor soft-archives."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Check if DATABASE_URL is set and we're not in fallback
        is_pg = DATABASE_URL and not getattr(conn, "_is_fallback", False)
        if is_pg:
            # Postgres
            c.execute("""
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
            # SQLite
            c.execute("""
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
    except Exception as e:
        logger.error(f"Error ensuring archive_table: {e}")
        if hasattr(conn, "rollback"): conn.rollback()
    finally:
        conn.close()
