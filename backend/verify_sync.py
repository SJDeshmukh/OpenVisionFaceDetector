import sqlite3
import os
import json
from datetime import datetime, date, timedelta

DB_PATH = 'backend/faces.db'

def verify_sync():
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print("--- Verifying Schema Sync ---")

    # 1. Check Tables
    tables = ['faces', 'attendance', 'companies', 'system_users', 'vendors', 'subscriptions', 'invoices', 'system_settings']
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = [row[0] for row in c.fetchall()]
    
    for t in tables:
        if t in existing_tables:
            print(f"[OK] Table '{t}' exists.")
        else:
            print(f"[FAIL] Table '{t}' MISSING!")

    # 2. Check Vendor ID Propagation
    # Check if all attendance records have a vendor_id
    c.execute("SELECT COUNT(*) FROM attendance WHERE vendor_id IS NULL")
    orphaned_attendance = c.fetchone()[0]
    if orphaned_attendance > 0:
        print(f"[WARN] {orphaned_attendance} attendance records missing vendor_id.")
    else:
        print(f"[OK] All attendance records have vendor_id.")

    # 3. Check Date Formats in Database
    print("\n--- Checking Date Formats ---")
    
    # Check Invoices
    c.execute("SELECT invoice_date FROM invoices LIMIT 5")
    for row in c.fetchall():
        print(f"Invoice Date: {row['invoice_date']}")
    
    # Check Attendance
    c.execute("SELECT timestamp FROM attendance ORDER BY id DESC LIMIT 5")
    for row in c.fetchall():
        print(f"Attendance Timestamp: {row['timestamp']}")

    # 4. Simulate Queries
    print("\n--- Simulating Critical Queries ---")
    
    # A. Analytics Query (Late Users)
    # This query uses date(timestamp) and joins faces
    try:
        c.execute("""
            SELECT COUNT(DISTINCT a.name) as count 
            FROM attendance a
            JOIN faces f ON a.name = f.name
            WHERE f.vendor_id IS NOT NULL
        """)
        print(f"[OK] Analytics Join Query executed. Count: {c.fetchone()['count']}")
    except Exception as e:
        print(f"[FAIL] Analytics Join Query failed: {e}")

    # B. Payroll Query (Faces Iteration)
    try:
        c.execute("SELECT name FROM faces")
        users = [r[0] for r in c.fetchall()]
        print(f"[OK] Fetched {len(users)} users for Payroll.")
        
        if users:
            placeholders = ','.join(['?'] * len(users))
            c.execute(f"SELECT COUNT(*) FROM attendance WHERE name IN ({placeholders})", users)
            print(f"[OK] Fetched attendance for users. Count: {c.fetchone()[0]}")
    except Exception as e:
        print(f"[FAIL] Payroll Query failed: {e}")

    # --- Data Integrity Checks ---
    print("\n--- Checking Data Integrity ---")
    
    # 1. Orphaned Faces (No Vendor)
    c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id IS NULL")
    orphans = c.fetchone()[0]
    if orphans > 0:
        print(f"[WARN] Found {orphans} faces with NULL vendor_id (Legacy data?).")
    else:
        print("[OK] No orphaned faces found.")

    # 2. Orphaned Attendance (No Vendor)
    c.execute("SELECT COUNT(*) FROM attendance WHERE vendor_id IS NULL")
    orphans = c.fetchone()[0]
    if orphans > 0:
        print(f"[WARN] Found {orphans} attendance records with NULL vendor_id.")
    else:
        print("[OK] No orphaned attendance records found.")

    # 3. Cross-Reference Integrity (Attendance vs Face Vendor)
    # Ensure attendance.vendor_id matches faces.vendor_id for the same person
    c.execute("""
        SELECT COUNT(*) 
        FROM attendance a
        JOIN faces f ON a.name = f.name
        WHERE a.vendor_id != f.vendor_id
    """)
    mismatches = c.fetchone()[0]
    if mismatches > 0:
        print(f"[FAIL] Found {mismatches} attendance records where vendor_id mismatch with face vendor_id!")
    else:
        print("[OK] Attendance vendor consistency check passed.")

    # 5. Check Manual Cascade Logic (Simulation)
    # We won't delete, but we'll check if related data exists for a vendor
    print("\n--- Checking Related Data Distribution ---")
    c.execute("SELECT id, company_name FROM vendors LIMIT 5")
    vendors = c.fetchall()
    for v in vendors:
        v_id = v['id']
        c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (v_id,))
        faces_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM attendance WHERE vendor_id = ?", (v_id,))
        att_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM companies WHERE vendor_id = ?", (v_id,))
        comp_count = c.fetchone()[0]
        print(f"Vendor '{v['company_name']}' (ID: {v_id}): Faces={faces_count}, Attendance={att_count}, Companies={comp_count}")

    conn.close()

if __name__ == "__main__":
    verify_sync()
