import sqlite3
import psycopg2
import os
import sys
import logging
from psycopg2.extras import execute_values
import db_factory

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SQLITE_DB_PATH = os.environ.get("DB_PATH", "face_db.sqlite")
POSTGRES_DB_URL = os.environ.get("DATABASE_URL")

def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_postgres_conn():
    return psycopg2.connect(POSTGRES_DB_URL)

def migrate_table(sqlite_conn, pg_conn, table_name, columns, pg_columns=None, conflict_col='id'):
    if pg_columns is None:
        pg_columns = columns
        
    logger.info(f"Migrating table: {table_name}...")
    
    # Read from SQLite
    c_lite = sqlite_conn.cursor()
    try:
        query = f"SELECT {', '.join(columns)} FROM {table_name}"
        c_lite.execute(query)
        rows = c_lite.fetchall()
    except sqlite3.OperationalError as e:
        logger.warning(f"Skipping {table_name}: {e}")
        return

    if not rows:
        logger.info(f"  No data in {table_name}.")
        return

    # Prepare Data
    data = [tuple(row) for row in rows]

    # Write to Postgres
    c_pg = pg_conn.cursor()
    
    # Construct INSERT query with ON CONFLICT DO NOTHING for idempotency
    cols_str = ', '.join(pg_columns)
    placeholders = ', '.join(['%s'] * len(pg_columns))
    
    conflict_clause = ""
    if conflict_col:
        conflict_clause = f" ON CONFLICT ({conflict_col}) DO NOTHING"
    
    insert_query = f"INSERT INTO {table_name} ({cols_str}) VALUES %s {conflict_clause}"
    insert_query_single = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders}) {conflict_clause}"
    
    try:
        execute_values(c_pg, insert_query, data)
    except Exception as e:
        logger.warning(f"  Batch insert failed for {table_name}, falling back to row-by-row: {e}")
        pg_conn.rollback()
        
        # Row-by-row fallback to skip problematic rows (like missing foreign keys)
        rows_migrated = 0
        for row in data:
            try:
                c_pg.execute(insert_query_single, row)
                rows_migrated += 1
            except Exception as row_error:
                logger.error(f"  Skipping row in {table_name} due to error: {row_error}")
                pg_conn.rollback()
                continue
        logger.info(f"  Row-by-row migration finished: {rows_migrated}/{len(data)} rows migrated.")
    
    # Reset Sequence (if table has 'id' column)
    if 'id' in pg_columns:
        logger.info(f"  Resetting sequence for {table_name}...")
        # Use is_called=false if table is empty to ensure next value is 1
        c_pg.execute(f"""
            SELECT setval(
                pg_get_serial_sequence('{table_name}', 'id'), 
                COALESCE((SELECT MAX(id) FROM {table_name}), 1), 
                (SELECT MAX(id) FROM {table_name}) IS NOT NULL
            )
        """)
        
    pg_conn.commit()
    logger.info(f"  Table {table_name} migration/check finished.")

def run_safe_migration():
    """
    Runs migration safely. Returns True if successful.
    """
    # Improved path detection: check current dir, then parent dir
    db_path = SQLITE_DB_PATH
    if not os.path.exists(db_path):
        parent_path = os.path.join("..", SQLITE_DB_PATH)
        if os.path.exists(parent_path):
            db_path = parent_path
            logger.info(f"Found SQLite database at {db_path}")
        else:
            logger.info(f"Migration Skipped: SQLite database not found at {SQLITE_DB_PATH} or {parent_path}")
            return True
    
    # Update global path for get_sqlite_conn
    global SQLITE_DB_PATH
    SQLITE_DB_PATH = db_path

    if not POSTGRES_DB_URL:
        logger.info("Migration Skipped: DATABASE_URL not set.")
        return False

    # Initialize Schemas
    db_factory.init_schemas()

    logger.info("Starting Idempotent Migration from SQLite to PostgreSQL...")
    
    try:
        sqlite_conn = get_sqlite_conn()
        pg_conn = get_postgres_conn()
    except Exception as e:
        logger.error(f"Connection Failed: {e}")
        return False
    
    # Migration mappings: (table_name, sqlite_columns, pg_columns, conflict_col)
    tables = [
        ('vendors', 
         ['id', 'company_name', 'email', 'phone', 'status', 'created_at', 'contact_person', 'web_login_enabled', 'frontend_bundle_id', 'backend_service_id', 'config'], 
         ['id', 'company_name', 'email', 'phone', 'status', 'created_at', 'contact_person', 'web_login_enabled', 'frontend_bundle_id', 'backend_service_id', 'registration_config'],
         'id'),
        ('companies', 
         ['id', 'name', 'draft_timetable', 'live_timetable', 'last_modified_by', 'last_modified_at', 'published_by', 'published_at', 'shifts', 'working_hours', 'vendor_id'], 
         None, 'id'),
        ('faces', 
         ['id', 'name', 'templates', 'face_image', 'department', 'designation', 'phone', 'shift', 'daily_wage', 'vendor_id', 'late_allowance_days', 'late_deduction_amount', 'display_id', 'custom_data'], 
         None, 'id'),
        ('attendance', 
         ['id', 'name', 'timestamp', 'status', 'captured_image', 'activity', 'is_late', 'vendor_id', 'person_id'], 
         None, 'id'),
        ('system_users', ['username', 'password', 'role', 'vendor_id'], None, 'username'),
        ('subscriptions', 
         ['id', 'vendor_id', 'plan_type', 'start_date', 'end_date', 'status', 'grace_period_days', 'max_users', 'cost_per_user', 'setup_fee', 'setup_fee_paid', 'max_mobile_devices', 'max_employees', 'cost_per_employee'], 
         None, 'id'),
        ('active_sessions', ['token', 'username', 'vendor_id', 'device_id', 'platform', 'last_active', 'created_at'], None, 'token'),
        ('vendor_devices', ['id', 'vendor_id', 'device_id', 'device_name', 'registered_at', 'last_login_at'], None, 'id'),
        ('invoices', 
         ['id', 'vendor_id', 'invoice_date', 'due_date', 'amount', 'status', 'details'], 
         None, 'id'),
        ('audit_logs', ['id', 'actor_username', 'action', 'target_vendor_id', 'details', 'timestamp'], None, 'id'),
        ('system_settings', ['key', 'value'], None, 'key')
    ]

    success = True
    try:
        for table_name, columns, pg_columns, conflict_col in tables:
            try:
                migrate_table(sqlite_conn, pg_conn, table_name, columns, pg_columns, conflict_col)
            except Exception as e:
                logger.error(f"Failed to migrate table {table_name}: {e}")
                success = False
    finally:
        sqlite_conn.close()
        pg_conn.close()

    if success:
        logger.info("Migration Complete Successfully.")
    else:
        logger.warning("Migration completed with errors.")
    return success

def main():
    run_safe_migration()

if __name__ == "__main__":
    main()
