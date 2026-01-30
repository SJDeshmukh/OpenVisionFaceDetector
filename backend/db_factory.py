import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.environ.get("DATABASE_URL", "")
# Auto-detect DB_TYPE if DATABASE_URL is present
DB_TYPE = os.environ.get("DB_TYPE", "postgres" if DATABASE_URL else "sqlite")
DB_PATH = os.environ.get("DB_PATH", "face_db.sqlite")

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self._lastrowid = None
        self._rowcount = -1

    def execute(self, sql, params=None):
        # 1. Handle SQLite PRAGMA (Ignore)
        if sql.strip().upper().startswith("PRAGMA"):
            return self

        # 2. Convert ? to %s
        # Note: This is a naive replacement. It might break if '?' is inside a string literal.
        # But for this app's specific usage, it's likely fine.
        sql_pg = sql.replace('?', '%s')
        
        # 3. Handle lastrowid for INSERTs
        # We append RETURNING id if it looks like an INSERT and doesn't already have RETURNING
        is_insert = sql_pg.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in sql_pg.upper():
             # Check if table typically has an ID. Most do in this app.
             # We'll try to append RETURNING id. If it fails (no id column), we catch and retry without it?
             # No, retrying is messy (transaction state). 
             # We will assume all tables we INSERT into have an 'id' column or we don't need lastrowid.
             # Exception: system_users (username PK), active_sessions (token PK).
             # We can check the table name.
             
             # Regex to find table name: INSERT INTO table_name ...
             match = re.search(r"INSERT\s+INTO\s+([a-zA-Z0-9_]+)", sql_pg, re.IGNORECASE)
             if match:
                 table_name = match.group(1)
                 if table_name not in ['system_users', 'active_sessions', 'system_settings', 'audit_logs']: 
                     # audit_logs has id, but we might not use it.
                     # faces, attendance, vendors, subscriptions, vendor_devices, invoices have ID.
                     sql_pg += " RETURNING id"
        
        try:
            self.cursor.execute(sql_pg, params)
            self._rowcount = self.cursor.rowcount
            
            if is_insert and "RETURNING id" in sql_pg:
                row = self.cursor.fetchone()
                if row:
                    # RealDictCursor returns dict, regular returns tuple
                    # We forced RealDictCursor in ConnectionWrapper
                    self._lastrowid = row['id']
            else:
                self._lastrowid = None # Reset
                
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
        self.row_factory = None # Mock property to satisfy app.py assignments

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor(cursor_factory=RealDictCursor))

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
    if DB_TYPE == 'postgres' and DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return PostgresConnectionWrapper(conn)
        except Exception as e:
            logger.error(f"Postgres Connection Error: {e}")
            raise e
    else:
        # SQLite Default
        print(f"DEBUG: Connecting to SQLite DB at {DB_PATH}")
        conn = sqlite3.connect(DB_PATH, timeout=timeout)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

def init_postgres_schema():
    """
    Creates the necessary tables in PostgreSQL if they don't exist.
    """
    if DB_TYPE != 'postgres':
        return

    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Vendors
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            registration_config TEXT, -- JSON
            web_login_enabled INTEGER DEFAULT 0,
            frontend_bundle_id TEXT,
            backend_service_id TEXT
        )
    """)
    
    # 1.5 Companies
    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER REFERENCES vendors(id),
            name TEXT,
            working_hours REAL,
            shifts TEXT, -- JSON
            draft_timetable TEXT, -- JSON
            live_timetable TEXT -- JSON
        )
    """)

    # 2. Faces (Employees)
    c.execute("""
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
            vendor_id INTEGER REFERENCES vendors(id),
            custom_data TEXT -- JSON
        )
    """)
    
    # 3. Attendance
    c.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            name TEXT,
            timestamp TIMESTAMP,
            status TEXT,
            captured_image TEXT,
            activity TEXT,
            is_late INTEGER DEFAULT 0,
            vendor_id INTEGER REFERENCES vendors(id),
            person_id INTEGER REFERENCES faces(id)
        )
    """)
    
    # 4. System Users
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT,
            vendor_id INTEGER REFERENCES vendors(id)
        )
    """)
    
    # 5. Subscriptions
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER REFERENCES vendors(id),
            plan_type TEXT,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            max_users INTEGER,
            max_employees INTEGER,
            cost_per_user REAL,
            setup_fee REAL,
            setup_fee_paid INTEGER,
            features TEXT, -- JSON
            max_mobile_devices INTEGER DEFAULT 1,
            cost_per_employee REAL DEFAULT 0,
            grace_period_days INTEGER DEFAULT 0
        )
    """)
    
    # 6. Vendor Devices
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendor_devices (
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER REFERENCES vendors(id),
            device_id TEXT,
            device_name TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP,
            UNIQUE(vendor_id, device_id)
        )
    """)
    
    # 7. Active Sessions
    c.execute("""
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
    
    # 8. Invoices
    c.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER REFERENCES vendors(id),
            amount REAL,
            status TEXT DEFAULT 'generated',
            due_date DATE,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP
        )
    """)
    
    # 9. Audit Logs
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            actor_username TEXT,
            action TEXT,
            target_vendor_id INTEGER,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 10. System Settings
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    conn.commit()
    conn.close()
