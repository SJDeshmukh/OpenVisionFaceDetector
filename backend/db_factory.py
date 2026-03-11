import os
import sqlite3
import psycopg2
from psycopg2.extras import DictCursor
import re
import logging
from datetime import datetime
import time

def get_table_columns(conn, table_name):
    """Returns a list of column names for a given table."""
    c = conn.cursor()
    is_pg = getattr(conn, "_is_pg", False)
    try:
        if is_pg:
            # PostgreSQL uses %s for parameters
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table_name,))
            return [str(r[0]) for r in c.fetchall()]
        else:
            # SQLite PRAGMA doesn't support ? for table names
            # table_name is trusted here since it's used internally
            c.execute(f"PRAGMA table_info({table_name})")
            return [str(r[1]) for r in c.fetchall()]
    except Exception:
        if is_pg and hasattr(conn, "rollback"): conn.rollback()
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
        
        # Handle "INSERT OR IGNORE" -> "INSERT ... ON CONFLICT DO NOTHING"
        if "INSERT OR IGNORE" in sql_pg.upper():
            sql_pg = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', sql_pg, flags=re.IGNORECASE)
            # Find the core part to determine where to append ON CONFLICT
            # We assume for now that standard tables have a UNIQUE constraint or PRIMARY KEY
            # If it's system_users, the constraint is on 'username'
            if "system_users" in sql_pg.lower():
                sql_pg += " ON CONFLICT (username) DO NOTHING"
            elif "active_sessions" in sql_pg.lower():
                sql_pg += " ON CONFLICT (token) DO NOTHING"
            elif "vendors" in sql_pg.lower() and "id" in sql_pg.lower():
                sql_pg += " ON CONFLICT (id) DO NOTHING"
            else:
                # Generic fallback if we can't determine the conflict target easily
                # This is a bit risky but standard for our SQLite-compatibility layer
                # We'll try to detect the table name and append a generic ON CONFLICT if possible
                pass

        # Handle "INSERT OR REPLACE" -> "INSERT ... ON CONFLICT (...) DO UPDATE SET ..."
        # This is more complex because we need the list of columns
        if "INSERT OR REPLACE" in sql_pg.upper():
            sql_pg = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO', 'INSERT INTO', sql_pg, flags=re.IGNORECASE)
            # This is hard to do generically without full SQL parsing. 
            # We'll handle the most common ones or log an error if we can't.
            if "system_settings" in sql_pg.lower():
                # INSERT INTO system_settings (key, value) VALUES (%s, %s)
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

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn
        self.row_factory = None
        self._is_pg = True

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor(cursor_factory=DictCursor))

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()
        
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
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=timeout)
            try:
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
        return conn
    except Exception as e:
        logger.error(f"SQLite Connection failed: {e}")
        raise e

def is_fallback_mode():
    return _IS_FALLBACK_MODE

def init_schemas():
    """Initializes schemas for both databases to ensure they are ready for failover."""
    logger.info("Initializing Database Schemas...")
    
    # Init primary if available
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            _init_pg_schema_on_conn(conn)
            conn.close()
            logger.info("PostgreSQL Schema initialized.")
        except Exception as e:
            logger.warning(f"Could not initialize PostgreSQL schema: {e}")

    # Init fallback
    try:
        conn = sqlite3.connect(DB_PATH)
        _init_sqlite_schema_on_conn(conn)
        conn.close()
        logger.info("SQLite Schema initialized.")
    except Exception as e:
        logger.error(f"Could not initialize SQLite schema: {e}")

def _init_pg_schema_on_conn(conn):
    cur = conn.cursor()
    # Using the existing DDL from init_postgres_schema
    queries = [
        "CREATE TABLE IF NOT EXISTS vendors (id SERIAL PRIMARY KEY, company_name TEXT NOT NULL, email TEXT, phone TEXT, address TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'active', registration_config TEXT, contact_person TEXT, web_login_enabled INTEGER DEFAULT 1, frontend_bundle_id TEXT, backend_service_id TEXT, vertical TEXT)",
        "CREATE TABLE IF NOT EXISTS companies (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), name TEXT, working_hours REAL, shifts TEXT, draft_timetable TEXT, live_timetable TEXT, last_modified_by TEXT, last_modified_at TIMESTAMP, published_by TEXT, published_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS faces (id SERIAL PRIMARY KEY, name TEXT, templates TEXT, face_image TEXT, department TEXT, designation TEXT, phone TEXT, shift TEXT, daily_wage REAL DEFAULT 0, late_allowance_days INTEGER, late_deduction_amount REAL DEFAULT 0, vendor_id INTEGER REFERENCES vendors(id), custom_data TEXT, display_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS attendance (id SERIAL PRIMARY KEY, name TEXT, timestamp TIMESTAMP, status TEXT, captured_image TEXT, activity TEXT, is_late INTEGER DEFAULT 0, device_id TEXT, vendor_id INTEGER REFERENCES vendors(id), person_id INTEGER REFERENCES faces(id))",
        "CREATE TABLE IF NOT EXISTS system_users (username TEXT PRIMARY KEY, password TEXT, role TEXT, vendor_id INTEGER REFERENCES vendors(id))",
        "CREATE TABLE IF NOT EXISTS subscriptions (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), plan_type TEXT, start_date TIMESTAMP, end_date TIMESTAMP, status TEXT DEFAULT 'active', max_users INTEGER, max_employees INTEGER, cost_per_user REAL, setup_fee REAL, setup_fee_paid INTEGER, features TEXT, max_mobile_devices INTEGER DEFAULT 1, cost_per_employee REAL DEFAULT 0, grace_period_days INTEGER DEFAULT 0, max_web_sessions INTEGER DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS vendor_devices (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), device_id TEXT, device_name TEXT, registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_login_at TIMESTAMP, UNIQUE(vendor_id, device_id))",
        "CREATE TABLE IF NOT EXISTS active_sessions (token TEXT PRIMARY KEY, username TEXT, vendor_id INTEGER, device_id TEXT, platform TEXT, last_active TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS invoices (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), amount REAL, status TEXT DEFAULT 'generated', due_date DATE, generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, paid_at TIMESTAMP, invoice_date DATE, details TEXT)",
        "CREATE TABLE IF NOT EXISTS audit_logs (id SERIAL PRIMARY KEY, actor_username TEXT, actor_role TEXT, target_vendor_id INTEGER, action TEXT, details TEXT, ip TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)",
        "CREATE TABLE IF NOT EXISTS parent_users (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), username TEXT UNIQUE, password TEXT, contact_email TEXT, contact_phone TEXT, student_number TEXT, selected_person_id INTEGER, device_id TEXT, fcm_token TEXT, session_version INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS student_parents (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), person_id INTEGER REFERENCES faces(id), parent_id INTEGER REFERENCES parent_users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS parent_tokens (token TEXT PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), student_number TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS person_embeddings (id SERIAL PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), person_id INTEGER REFERENCES faces(id), class_year TEXT, division TEXT, branch TEXT, vec BYTEA, dim INTEGER, struct_vec BYTEA, landmarks_3d TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS class_batches (id TEXT PRIMARY KEY, vendor_id INTEGER REFERENCES vendors(id), class_year TEXT, division TEXT, branch TEXT, status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS class_batch_items (id TEXT PRIMARY KEY, batch_id TEXT REFERENCES class_batches(id), seq INTEGER, image_b64 TEXT, annotated_b64 TEXT, faces_json TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    ]
    for q in queries:
        cur.execute(q)
    conn.commit()
    cur.close()

def _init_sqlite_schema_on_conn(conn):
    cur = conn.cursor()
    # Simplified SQLite versions (using INTEGER PRIMARY KEY AUTOINCREMENT)
    queries = [
        "CREATE TABLE IF NOT EXISTS vendors (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT NOT NULL, email TEXT, phone TEXT, address TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'active', registration_config TEXT, contact_person TEXT, web_login_enabled INTEGER DEFAULT 1, frontend_bundle_id TEXT, backend_service_id TEXT, vertical TEXT)",
        "CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, name TEXT, working_hours REAL, shifts TEXT, draft_timetable TEXT, live_timetable TEXT, last_modified_by TEXT, last_modified_at DATETIME, published_by TEXT, published_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS faces (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, templates TEXT, face_image TEXT, department TEXT, designation TEXT, phone TEXT, shift TEXT, daily_wage REAL DEFAULT 0, late_allowance_days INTEGER, late_deduction_amount REAL DEFAULT 0, vendor_id INTEGER, custom_data TEXT, display_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, timestamp DATETIME, status TEXT, captured_image TEXT, activity TEXT, is_late INTEGER DEFAULT 0, device_id TEXT, vendor_id INTEGER, person_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS system_users (username TEXT PRIMARY KEY, password TEXT, role TEXT, vendor_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, plan_type TEXT, start_date DATETIME, end_date DATETIME, status TEXT DEFAULT 'active', max_users INTEGER, max_employees INTEGER, cost_per_user REAL, setup_fee REAL, setup_fee_paid INTEGER, features TEXT, max_mobile_devices INTEGER DEFAULT 1, cost_per_employee REAL DEFAULT 0, grace_period_days INTEGER DEFAULT 0, max_web_sessions INTEGER DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS vendor_devices (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, device_id TEXT, device_name TEXT, registered_at DATETIME DEFAULT CURRENT_TIMESTAMP, last_login_at DATETIME, UNIQUE(vendor_id, device_id))",
        "CREATE TABLE IF NOT EXISTS active_sessions (token TEXT PRIMARY KEY, username TEXT, vendor_id INTEGER, device_id TEXT, platform TEXT, last_active DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, amount REAL, status TEXT DEFAULT 'generated', due_date DATE, generated_at DATETIME DEFAULT CURRENT_TIMESTAMP, paid_at DATETIME, invoice_date DATE, details TEXT)",
        "CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_username TEXT, actor_role TEXT, target_vendor_id INTEGER, action TEXT, details TEXT, ip TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)",
        "CREATE TABLE IF NOT EXISTS parent_users (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, username TEXT UNIQUE, password TEXT, contact_email TEXT, contact_phone TEXT, student_number TEXT, selected_person_id INTEGER, device_id TEXT, fcm_token TEXT, session_version INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS student_parents (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, person_id INTEGER, parent_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS parent_tokens (token TEXT PRIMARY KEY, vendor_id INTEGER, student_number TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS person_embeddings (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, person_id INTEGER, class_year TEXT, division TEXT, branch TEXT, vec BLOB, dim INTEGER, struct_vec BLOB, landmarks_3d TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS class_batches (id TEXT PRIMARY KEY, vendor_id INTEGER, class_year TEXT, division TEXT, branch TEXT, status TEXT DEFAULT 'active', created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS class_batch_items (id TEXT PRIMARY KEY, batch_id TEXT, seq INTEGER, image_b64 TEXT, annotated_b64 TEXT, faces_json TEXT, status TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
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
                    tables_to_clear = ['attendance', 'faces', 'vendors', 'audit_logs', 'system_settings', 'companies', 'subscriptions', 'active_sessions', 'vendor_devices', 'invoices']
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
