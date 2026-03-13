import os
import sys
import json
import sqlite3

# --- Basic Path Setup ---
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPTS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Manually load .env if it exists
dotenv_path = os.path.join(_BACKEND_DIR, ".env")
if os.path.exists(dotenv_path):
    with open(dotenv_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

from utils import get_db_connection

def fix_all_display_ids():
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Get all vendors
        c.execute("SELECT id FROM vendors")
        vendors = [r[0] for r in c.fetchall()]
        
        print(f"Found {len(vendors)} vendors. Starting re-indexing...")
        
        for vid in vendors:
            # Get all faces for this vendor ordered by ID (creation order)
            c.execute("SELECT id FROM faces WHERE vendor_id = ? ORDER BY id ASC", (vid,))
            faces = [r[0] for r in c.fetchall()]
            
            if not faces:
                print(f"Vendor {vid}: No faces found.")
                continue
                
            print(f"Vendor {vid}: Re-indexing {len(faces)} faces...")
            for idx, fid in enumerate(faces):
                display_id = idx + 1
                c.execute("UPDATE faces SET display_id = ? WHERE id = ?", (display_id, fid))
        
        conn.commit()
        print("Successfully re-indexed all faces.")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_all_display_ids()
