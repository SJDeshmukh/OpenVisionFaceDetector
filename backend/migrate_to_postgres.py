import sqlite3
import psycopg2
import os
import sys
from psycopg2.extras import execute_values
import db_factory

# Configuration
SQLITE_DB_PATH = os.environ.get("DB_PATH", "face_db.sqlite")
POSTGRES_DB_URL = os.environ.get("DATABASE_URL")

def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_postgres_conn():
    return psycopg2.connect(POSTGRES_DB_URL)

def migrate_table(sqlite_conn, pg_conn, table_name, columns, pg_columns=None):
    if pg_columns is None:
        pg_columns = columns
        
    print(f"Migrating table: {table_name}...")
    
    # Read from SQLite
    c_lite = sqlite_conn.cursor()
    try:
        query = f"SELECT {', '.join(columns)} FROM {table_name}"
        c_lite.execute(query)
        rows = c_lite.fetchall()
    except sqlite3.OperationalError as e:
        print(f"Skipping {table_name}: {e}")
        return

    if not rows:
        print(f"  No data in {table_name}.")
        return

    # Check if target table is empty
    c_pg = pg_conn.cursor()
    c_pg.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = c_pg.fetchone()[0]
    if count > 0:
        print(f"  Target table {table_name} is not empty (rows={count}). Skipping migration.")
        return

    # Prepare Data
    data = []
    for row in rows:
        data.append(tuple(row))

    # Write to Postgres
    c_pg = pg_conn.cursor()
    
    # Construct INSERT query
    cols_str = ', '.join(pg_columns)
    
    insert_query = f"INSERT INTO {table_name} ({cols_str}) VALUES %s"
    
    try:
        # Using execute_values for batch insertion
        execute_values(c_pg, insert_query, data)
        
        # Reset Sequence (if table has 'id' column)
        if 'id' in pg_columns:
            print(f"  Resetting sequence for {table_name}...")
            c_pg.execute(f"SELECT setval('{table_name}_id_seq', (SELECT MAX(id) FROM {table_name}))")
            
        pg_conn.commit()
        print(f"  Migrated {len(rows)} rows.")
    except Exception as e:
        print(f"  Error migrating {table_name}: {e}")
        pg_conn.rollback()

def run_safe_migration():
    """
    Runs migration safely. Checks for existence of SQLite DB and emptiness of Postgres tables.
    """
    # 1. Check if SQLite DB exists
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"Migration Skipped: SQLite database not found at {SQLITE_DB_PATH}")
        return

    # 2. Check if Postgres is configured
    if not POSTGRES_DB_URL:
        print("Migration Skipped: DATABASE_URL not set.")
        return

    # 3. Initialize Schema (Idempotent)
    import db_factory
    # Ensure we are in postgres mode for schema init
    original_db_type = db_factory.DB_TYPE
    db_factory.DB_TYPE = 'postgres'
    db_factory.DATABASE_URL = POSTGRES_DB_URL
    try:
        db_factory.init_postgres_schema()
    except Exception as e:
        print(f"Schema Init Failed: {e}")
        return
    finally:
        db_factory.DB_TYPE = original_db_type

    print("Starting Safe Migration from SQLite to PostgreSQL...")
    
    try:
        sqlite_conn = get_sqlite_conn()
        pg_conn = get_postgres_conn()
    except Exception as e:
        print(f"Connection Failed: {e}")
        return
    
    # 1. Vendors
    # Map company_name to name if name is NULL (Legacy support)
    migrate_table(sqlite_conn, pg_conn, 'vendors', 
                  ['id', 'COALESCE(name, company_name)', 'email', 'phone', 'address', 'created_at', 'status', 'registration_config', 'web_login_enabled'],
                  pg_columns=['id', 'name', 'email', 'phone', 'address', 'created_at', 'status', 'registration_config', 'web_login_enabled'])
                  
    # 1.5 Companies
    migrate_table(sqlite_conn, pg_conn, 'companies',
                  ['id', 'vendor_id', 'name', 'working_hours', 'shifts', 'draft_timetable', 'live_timetable'])

    # 2. Faces
    migrate_table(sqlite_conn, pg_conn, 'faces',
                  ['id', 'name', 'templates', 'face_image', 'department', 'designation', 'phone', 'shift', 'daily_wage', 'late_allowance_days', 'late_deduction_amount', 'vendor_id', 'custom_data'])

    # 3. Attendance
    migrate_table(sqlite_conn, pg_conn, 'attendance',
                  ['id', 'name', 'timestamp', 'status', 'captured_image', 'activity', 'is_late', 'vendor_id', 'person_id'])
                  
    # 4. System Users
    migrate_table(sqlite_conn, pg_conn, 'system_users',
                  ['username', 'password', 'role', 'vendor_id'])

    # 5. Subscriptions
    migrate_table(sqlite_conn, pg_conn, 'subscriptions',
                  ['id', 'vendor_id', 'plan_type', 'start_date', 'end_date', 'max_users', 'max_employees', 'cost_per_user', 'setup_fee', 'setup_fee_paid', 'features', 'max_mobile_devices', 'cost_per_employee', 'grace_period_days'])

    # 6. Active Sessions
    # Check if table exists in SQLite first
    migrate_table(sqlite_conn, pg_conn, 'active_sessions',
                  ['token', 'username', 'vendor_id', 'device_id', 'platform', 'last_active', 'created_at'])

    # 6.5 Vendor Devices
    migrate_table(sqlite_conn, pg_conn, 'vendor_devices',
                  ['id', 'vendor_id', 'device_id', 'device_name', 'registered_at', 'last_login_at'])

    # 7. Invoices
    migrate_table(sqlite_conn, pg_conn, 'invoices',
                  ['id', 'vendor_id', 'amount', 'status', 'due_date', 'generated_at', 'paid_at'])

    # 8. Audit Logs
    migrate_table(sqlite_conn, pg_conn, 'audit_logs',
                  ['id', 'actor_username', 'action', 'target_vendor_id', 'details', 'timestamp'])

    # 9. System Settings
    migrate_table(sqlite_conn, pg_conn, 'system_settings',
                  ['key', 'value'])

    sqlite_conn.close()
    pg_conn.close()
    print("Migration Complete.")

def main():
    run_safe_migration()

if __name__ == "__main__":
    main()
