import os
import json
import logging
from datetime import datetime, date
from utils import get_db_connection, _run, ensure_audit_logs_table, logger
import db_factory

def bootstrap_db():
    """Initializes the database, runs migrations, and seeds initial data."""
    # 1. Initialize schemas (PostgreSQL and SQLite fallback)
    db_factory.init_schemas()
    
    # 2. Check for recovery (if SQLite has data and PG is available)
    db_factory.check_and_recover()
    
    # 3. Data seeding and performance tweaks
    seed_superadmin()
    ensure_vendor_companies_and_subscription_features()
    add_performance_indexes()
    
    # 4. Run schema migrations/checks for all database types
    add_missing_columns()
    ensure_audit_logs_table()
    
    # 5. Legacy migration helpers for SQLite
    from db_factory import is_fallback_mode, DATABASE_URL
    if not DATABASE_URL or is_fallback_mode():
        # These are mostly SQLite-specific migrations handled in app.py previously
        pass 

def seed_superadmin():
    """Seeds the default superadmin account if it doesn't exist."""
    from services.auth_service import hash_password
    conn = get_db_connection()
    c = conn.cursor()
    try:
        username = "superadmin"
        default_password = hash_password("admin123")
        # Use ON CONFLICT or INSERT OR IGNORE via wrapper
        c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)",
                   (username, default_password, "super_admin", None))
        conn.commit()
    except Exception as e:
        logger.error(f"Error seeding superadmin: {e}")
    finally:
        conn.close()

def ensure_vendor_companies_and_subscription_features():
    """Ensures each vendor has a corresponding company and subscription record."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT id, company_name FROM vendors")
        vendors = c.fetchall() or []
        today = date.today().isoformat()
        far_future = "2099-12-31"
        default_features = ["mobile_app", "shifts", "late_mark"]

        for v in vendors:
            try:
                vendor_id = int(v[0])
            except Exception: continue
            
            company_name = (v[1] or "").strip() or f"Vendor {vendor_id}"

            # Ensure Company
            try:
                c.execute("SELECT id FROM companies WHERE vendor_id = ? LIMIT 1", (vendor_id,))
                if not c.fetchone():
                    c.execute(
                        "INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)",
                        (company_name, "[]", "[]", "[]", vendor_id),
                    )
            except Exception: pass

            # Ensure Subscription
            try:
                c.execute("SELECT features, start_date, end_date, grace_period_days FROM subscriptions WHERE vendor_id = ? LIMIT 1", (vendor_id,))
                sub = c.fetchone()
                if not sub:
                    c.execute(
                        "INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, grace_period_days, features) VALUES (?, ?, ?, ?, ?, ?)",
                        (vendor_id, "basic", today, far_future, 7, json.dumps(default_features)),
                    )
                else:
                    # Update features if needed
                    raw = sub[0]
                    feats = []
                    if raw:
                        try:
                            feats = json.loads(raw) if isinstance(raw, str) else list(raw)
                        except Exception: feats = []
                    
                    changed = False
                    for f in default_features:
                        if f not in feats:
                            feats.append(f); changed = True
                    
                    if changed:
                        c.execute("UPDATE subscriptions SET features = ? WHERE vendor_id = ?", (json.dumps(feats), vendor_id))
            except Exception: pass

        conn.commit()
    except Exception as e:
        logger.error(f"Error in ensure_vendor_companies: {e}")
    finally:
        conn.close()

def add_performance_indexes():
    """Adds missing indexes to improve query performance."""
    conn = get_db_connection()
    c = conn.cursor()
    indexes = [
        ("idx_system_users_vendor", "system_users(vendor_id)"),
        ("idx_subscriptions_vendor", "subscriptions(vendor_id)"),
        ("idx_vendors_status", "vendors(status)"),
        ("idx_invoices_vendor", "invoices(vendor_id)"),
        ("idx_faces_vendor", "faces(vendor_id)"),
        ("idx_attendance_vendor", "attendance(vendor_id)"),
        ("idx_attendance_timestamp", "attendance(timestamp)")
    ]
    for name, definition in indexes:
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {definition}")
        except Exception: pass
    conn.commit()
    conn.close()

def add_missing_columns():
    """Runs manual migrations to add missing columns to existing tables."""
    from db_factory import get_table_columns
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Attendance: is_late
        if 'is_late' not in get_table_columns(conn, "attendance"):
            try: c.execute("ALTER TABLE attendance ADD COLUMN is_late INTEGER DEFAULT 0")
            except Exception: pass
            
        # Faces: late deduction columns
        faces_cols = get_table_columns(conn, "faces")
        if 'late_allowance_days' not in faces_cols:
            try: c.execute("ALTER TABLE faces ADD COLUMN late_allowance_days INTEGER DEFAULT NULL")
            except Exception: pass
        if 'late_deduction_amount' not in faces_cols:
            try: c.execute("ALTER TABLE faces ADD COLUMN late_deduction_amount REAL DEFAULT NULL")
            except Exception: pass
            
        # Vendors: retention_days
        if 'retention_days' not in get_table_columns(conn, "vendors"):
            try: c.execute("ALTER TABLE vendors ADD COLUMN retention_days INTEGER DEFAULT 90")
            except Exception: pass
            
        conn.commit()
    finally:
        conn.close()
