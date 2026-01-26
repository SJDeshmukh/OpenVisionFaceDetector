import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faces.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("Starting SaaS Migration...")
    
    # 1. Create Vendors Table
    print("Creating 'vendors' table...")
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Create Subscriptions Table
    print("Creating 'subscriptions' table...")
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            plan_type TEXT DEFAULT 'basic',
            start_date DATETIME,
            end_date DATETIME,
            status TEXT DEFAULT 'active',
            grace_period_days INTEGER DEFAULT 7,
            FOREIGN KEY(vendor_id) REFERENCES vendors(id)
        )
    """)
    
    # 3. Add vendor_id column to existing tables
    tables = ['faces', 'attendance', 'system_users', 'companies']
    for table in tables:
        try:
            # Check if column exists
            c.execute(f"SELECT vendor_id FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            print(f"Adding vendor_id to '{table}'...")
            c.execute(f"ALTER TABLE {table} ADD COLUMN vendor_id INTEGER")
            
    # 4. Create Default Vendor (Migration for existing data)
    c.execute("SELECT COUNT(*) FROM vendors")
    if c.fetchone()[0] == 0:
        print("Creating Default Vendor (ID 1)...")
        c.execute("INSERT INTO vendors (id, name, status) VALUES (1, 'Default Company', 'active')")
        
        # Create Default Subscription (100 years)
        start = datetime.now()
        end = start + timedelta(days=36500)
        c.execute("""
            INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, status)
            VALUES (1, 'enterprise', ?, ?, 'active')
        """, (start, end))
        
        # 5. Backfill Data
        print("Backfilling data to Vendor 1...")
        
        # Faces
        c.execute("UPDATE faces SET vendor_id = 1 WHERE vendor_id IS NULL")
        
        # Attendance
        c.execute("UPDATE attendance SET vendor_id = 1 WHERE vendor_id IS NULL")
        
        # Companies
        c.execute("UPDATE companies SET vendor_id = 1 WHERE vendor_id IS NULL")
        
        # System Users (Special handling)
        # 'admin' stays NULL (SuperAdmin)
        # 'kiosk' goes to Vendor 1
        # Others go to Vendor 1
        c.execute("UPDATE system_users SET vendor_id = 1 WHERE username != 'admin'")
        
        print("Data backfilled.")
    
    conn.commit()
    conn.close()
    print("Migration Complete.")

if __name__ == "__main__":
    migrate()
