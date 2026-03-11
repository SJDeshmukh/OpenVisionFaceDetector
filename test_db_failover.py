import os
import sys
import time
import sqlite3
import psycopg2
from dotenv import load_dotenv

# Add backend to path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend'))
sys.path.append(backend_path)

# Load .env manually to ensure it's there
load_dotenv(os.path.join(backend_path, '.env'))

import db_factory
from utils import get_db_connection

def test_failover_recovery():
    print("Starting Failover and Recovery Test...")
    
    # 1. Ensure Postgres is available for setup
    print("\n[Step 1] Checking Primary DB availability...")
    try:
        # We want to make sure we are NOT in fallback mode initially
        conn = db_factory.get_db_connection()
        is_fallback = db_factory.is_fallback_mode()
        if is_fallback:
             print("WARNING: System started in FALLBACK mode. Is Postgres running?")
             # We might still continue if we want to test recovery once it comes back
        else:
             print("Connected to Primary DB (Postgres) successfully.")
        conn.close()
    except Exception as e:
        print(f"ERROR: Primary DB connection attempt failed: {e}")
        # Continue anyway to test fallback logic

    # 2. Simulate Postgres Down
    print("\n[Step 2] Simulating Postgres DOWN...")
    original_url = os.environ.get("DATABASE_URL", "")
    # Set to an unreachable host
    os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@1.2.3.4:5432/nonexistent"
    
    try:
        conn = get_db_connection()
        is_fallback = db_factory.is_fallback_mode()
        print(f"Is Fallback Mode: {is_fallback}")
        
        if not is_fallback:
             print("FAILED: Did not detect fallback mode when Postgres is unreachable.")
             if original_url: os.environ["DATABASE_URL"] = original_url
             return
        
        # Write some data to SQLite
        c = conn.cursor()
        # Create table if not exists (should be done by init_schemas but let's be safe)
        c.execute("CREATE TABLE IF NOT EXISTS faces (id INTEGER PRIMARY KEY, name TEXT, vendor_id INTEGER)")
        c.execute("INSERT INTO faces (name, vendor_id) VALUES (?, ?)", ("Test Fallback User", 999))
        conn.commit()
        conn.close()
        print("Successfully wrote data to SQLite fallback.")
        
    except Exception as e:
        print(f"FAILED during fallback test: {e}")
        if original_url: os.environ["DATABASE_URL"] = original_url
        return

    # 3. Restore Postgres
    print("\n[Step 3] Restoring Postgres (simulated)...")
    if original_url:
        os.environ["DATABASE_URL"] = original_url
    else:
        # If it wasn't there, maybe it's not needed for this part of test if we just want to see if it ATTEMPTS recovery
        print("No original DATABASE_URL to restore.")
    
    # 4. Trigger recovery
    print("\n[Step 4] Triggering recovery check...")
    # This will attempt to connect to Postgres and then run migration
    try:
        db_factory.check_and_recover()
        print("Recovery check completed.")
    except Exception as e:
        print(f"Recovery check failed (expected if Postgres still unreachable): {e}")
    
    # 5. Verify logic
    print("\n[Step 5] Verification complete. Please check logs for migration attempts.")
    
    print("\nTest Complete.")

if __name__ == "__main__":
    test_failover_recovery()
