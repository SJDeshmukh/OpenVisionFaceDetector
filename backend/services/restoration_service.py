import sqlite3
import psycopg2
import os
import logging
from psycopg2.extras import execute_values
try:
    from db_factory import get_db_connection, init_schemas, DATABASE_URL, init_sqlite_schema
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db_factory import get_db_connection, init_schemas, DATABASE_URL, init_sqlite_schema

logger = logging.getLogger(__name__)

def migrate_table_idempotent(src_conn, dst_conn, table_name, columns, conflict_col='id'):
    """
    Carefully merges data from src into dst.
    """
    # 1. Read from Source (SQLite backup)
    sc = src_conn.cursor()
    try:
        sc.execute(f"SELECT {', '.join(columns)} FROM {table_name}")
        rows = sc.fetchall()
    except sqlite3.OperationalError as e:
        logger.warning(f"Skipping {table_name}: {e}")
        return 0

    if not rows:
        return 0

    # 2. Prepare Data
    data = [tuple(row) for row in rows]

    # 3. Write to Destination
    dc = dst_conn.cursor()
    is_pg = getattr(dst_conn, "_is_pg", False)
    
    cols_str = ', '.join(columns)
    
    if is_pg:
        # PostgreSQL Logic
        placeholders = ', '.join(['%s'] * len(columns))
        conflict_clause = ""
        if conflict_col:
            conflict_clause = f" ON CONFLICT ({conflict_col}) DO NOTHING"
        
        insert_query = f"INSERT INTO {table_name} ({cols_str}) VALUES %s {conflict_clause}"
        try:
            # PostgresCursorWrapper needs the raw cursor for execute_values
            raw_dc = dc.cursor if hasattr(dc, "cursor") else dc
            execute_values(raw_dc, insert_query, data)
        except Exception as e:
            logger.error(f"Postgres merge failed for {table_name}: {e}")
            dst_conn.rollback()
            return 0
            
        # Reset Sequence (only if 'id' exists and is a serial/identity column with a sequence)
        if 'id' in columns:
            # Use dynamic SQL to avoid type mismatch errors on tables with TEXT IDs
            dc.execute(f"""
                DO $$
                DECLARE
                    seq_name TEXT;
                BEGIN
                    SELECT pg_get_serial_sequence('{table_name}', 'id') INTO seq_name;
                    IF seq_name IS NOT NULL THEN
                        EXECUTE 'SELECT setval(' || quote_literal(seq_name) || ', COALESCE((SELECT MAX(id) FROM "{table_name}"), 1), EXISTS (SELECT 1 FROM "{table_name}"))';
                    END IF;
                END $$;
            """)
    else:
        # SQLite Logic
        placeholders = ', '.join(['?'] * len(columns))
        insert_query = f"INSERT OR IGNORE INTO {table_name} ({cols_str}) VALUES ({placeholders})"
        try:
            dc.executemany(insert_query, data)
        except Exception as e:
            logger.error(f"SQLite merge failed for {table_name}: {e}")
            dst_conn.rollback()
            return 0

    dst_conn.commit()
    return len(rows)

def run_restore(sqlite_backup_path):
    """
    Main entry point for restoration.
    Merges backup data into the active primary database.
    """
    if not os.path.exists(sqlite_backup_path):
        raise FileNotFoundError(f"Backup file not found at {sqlite_backup_path}")

    logger.info(f"Starting restoration from {sqlite_backup_path}...")
    
    # 1. Connect to Source
    src_conn = sqlite3.connect(sqlite_backup_path)
    src_conn.row_factory = sqlite3.Row
    
    # 2. Connect to Destination (Active primary)
    dst_conn = get_db_connection()
    
    # Tables and their columns to migrate
    tables = [
        ('vendors', ['id', 'company_name', 'email', 'phone', 'status', 'created_at', 'contact_person', 'web_login_enabled', 'frontend_bundle_id', 'backend_service_id', 'registration_config', 'retention_days']),
        ('companies', ['id', 'vendor_id', 'name', 'working_hours', 'shifts', 'draft_timetable', 'live_timetable', 'last_modified_by', 'last_modified_at', 'published_by', 'published_at']),
        ('faces', ['id', 'name', 'templates', 'face_image', 'department', 'designation', 'phone', 'shift', 'daily_wage', 'vendor_id', 'custom_data', 'display_id']),
        ('attendance', ['id', 'name', 'timestamp', 'status', 'captured_image', 'activity', 'is_late', 'vendor_id', 'person_id']),
        ('system_users', ['username', 'password', 'role', 'vendor_id'], 'username'),
        ('subscriptions', ['id', 'vendor_id', 'plan_type', 'start_date', 'end_date', 'status', 'max_users', 'max_employees', 'cost_per_user', 'setup_fee', 'setup_fee_paid', 'max_mobile_devices', 'cost_per_employee', 'grace_period_days', 'max_web_sessions']),
        ('active_sessions', ['token', 'username', 'vendor_id', 'device_id', 'platform', 'last_active', 'created_at'], 'token'),
        ('vendor_devices', ['id', 'vendor_id', 'device_id', 'device_name', 'registered_at', 'last_login_at']),
        ('invoices', ['id', 'vendor_id', 'amount', 'status', 'due_date', 'generated_at', 'paid_at', 'invoice_date', 'details']),
        ('audit_logs', ['id', 'actor_username', 'actor_role', 'target_vendor_id', 'action', 'details', 'ip', 'timestamp']),
        ('system_settings', ['key', 'value'], 'key'),
        ('parent_users', ['id', 'vendor_id', 'username', 'password', 'contact_email', 'contact_phone', 'student_number', 'selected_person_id', 'device_id', 'fcm_token', 'session_version', 'created_at']),
        ('student_parents', ['id', 'vendor_id', 'person_id', 'parent_id', 'created_at']),
        ('parent_tokens', ['token', 'vendor_id', 'student_number', 'created_at'], 'token'),
        ('person_embeddings', ['id', 'vendor_id', 'person_id', 'class_year', 'division', 'branch', 'vec', 'dim', 'struct_vec', 'landmarks_3d', 'created_at']),
        ('class_batches', ['id', 'vendor_id', 'class_year', 'division', 'branch', 'status', 'created_at']),
        ('class_batch_items', ['id', 'batch_id', 'seq', 'image_b64', 'annotated_b64', 'faces_json', 'status', 'created_at'])
    ]
    logger.info(f"DEBUG: run_restore found {len(tables)} tables to process")
    print(f"DEBUG PRINT: run_restore found {len(tables)} tables to process")

    stats = {}
    try:
        for t in tables:
            table_name = t[0]
            cols = t[1]
            conflict_col = t[2] if len(t) > 2 else 'id'
            
            logger.info(f"  Processing table: {table_name}...")
            count = migrate_table_idempotent(src_conn, dst_conn, table_name, cols, conflict_col)
            stats[table_name] = count
            
        logger.info("Restoration Complete Successfully.")
        return stats
    finally:
        src_conn.close()
        dst_conn.close()

def run_backup(dest_path):
    """
    Exports all system data from the active primary database to a SQLite file at dest_path.
    """
    if os.path.exists(dest_path):
        os.remove(dest_path)

    # 1. Connect to Source (Active primary)
    src_conn = get_db_connection()
    
    # 2. Connect to Destination (New SQLite backup)
    dst_conn = sqlite3.connect(dest_path)
    dst_conn.row_factory = sqlite3.Row
    
    try:
        # 3. Initialize full schema in destination
        init_sqlite_schema(dst_conn)
        
        # 4. Tables to backup
        tables = [
            ('vendors', ['id', 'company_name', 'email', 'phone', 'status', 'created_at', 'contact_person', 'web_login_enabled', 'frontend_bundle_id', 'backend_service_id', 'registration_config', 'retention_days']),
            ('companies', ['id', 'vendor_id', 'name', 'working_hours', 'shifts', 'draft_timetable', 'live_timetable', 'last_modified_by', 'last_modified_at', 'published_by', 'published_at']),
            ('faces', ['id', 'name', 'templates', 'face_image', 'department', 'designation', 'phone', 'shift', 'daily_wage', 'vendor_id', 'custom_data', 'display_id']),
            ('attendance', ['id', 'name', 'timestamp', 'status', 'captured_image', 'activity', 'is_late', 'vendor_id', 'person_id']),
            ('system_users', ['username', 'password', 'role', 'vendor_id'], 'username'),
            ('subscriptions', ['id', 'vendor_id', 'plan_type', 'start_date', 'end_date', 'status', 'max_users', 'max_employees', 'cost_per_user', 'setup_fee', 'setup_fee_paid', 'max_mobile_devices', 'cost_per_employee', 'grace_period_days', 'max_web_sessions']),
            ('active_sessions', ['token', 'username', 'vendor_id', 'device_id', 'platform', 'last_active', 'created_at'], 'token'),
            ('vendor_devices', ['id', 'vendor_id', 'device_id', 'device_name', 'registered_at', 'last_login_at']),
            ('invoices', ['id', 'vendor_id', 'amount', 'status', 'due_date', 'generated_at', 'paid_at', 'invoice_date', 'details']),
            ('audit_logs', ['id', 'actor_username', 'actor_role', 'target_vendor_id', 'action', 'details', 'ip', 'timestamp']),
            ('system_settings', ['key', 'value'], 'key'),
            ('parent_users', ['id', 'vendor_id', 'username', 'password', 'contact_email', 'contact_phone', 'student_number', 'selected_person_id', 'device_id', 'fcm_token', 'session_version', 'created_at']),
            ('student_parents', ['id', 'vendor_id', 'person_id', 'parent_id', 'created_at']),
            ('parent_tokens', ['token', 'vendor_id', 'student_number', 'created_at'], 'token'),
            ('person_embeddings', ['id', 'vendor_id', 'person_id', 'class_year', 'division', 'branch', 'vec', 'dim', 'struct_vec', 'landmarks_3d', 'created_at']),
            ('class_batches', ['id', 'vendor_id', 'class_year', 'division', 'branch', 'status', 'created_at']),
            ('class_batch_items', ['id', 'batch_id', 'seq', 'image_b64', 'annotated_b64', 'faces_json', 'status', 'created_at'])
        ]

        
        stats = {}
        for t in tables:
            table_name = t[0]
            cols = t[1]
            
            logger.info(f"  Backing up table: {table_name}...")
            
            sc = src_conn.cursor()
            is_pg = getattr(src_conn, "_is_pg", False)
            
            # Use placeholders based on source DB type
            placeholders = ", ".join(["%s" if is_pg else "?"] * len(cols))
            
            try:
                sc.execute(f"SELECT {', '.join(cols)} FROM {table_name}")
                rows = sc.fetchall()
            except Exception as e:
                logger.warning(f"Skipping {table_name}: {e}")
                continue

            if not rows:
                stats[table_name] = 0
                continue

            dc = dst_conn.cursor()
            placeholders_dst = ", ".join(["?"] * len(cols))
            insert_query = f"INSERT OR IGNORE INTO {table_name} ({', '.join(cols)}) VALUES ({placeholders_dst})"
            
            data = [tuple(row) for row in rows]
            dc.executemany(insert_query, data)
            dst_conn.commit()
            stats[table_name] = len(rows)
            
        logger.info("Backup Complete Successfully.")
        return stats
    finally:
        src_conn.close()
        dst_conn.close()
