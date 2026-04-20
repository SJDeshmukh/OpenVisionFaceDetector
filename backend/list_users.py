import os
import sys

# Add backend to path
sys.path.append(os.getcwd())

from db_factory import get_db_connection

def list_users():
    print("Connecting to DB...")
    try:
        conn = get_db_connection()
        print(f"Connected to {'Postgres' if getattr(conn, '_is_pg', False) else 'SQLite'}")
        c = conn.cursor()
        c.execute("SELECT username, role, vendor_id FROM system_users")
        users = c.fetchall()
        print(f"Total users: {len(users)}")
        for u in users:
            print(dict(u) if hasattr(u, 'keys') else u)
        conn.close()
    except Exception as e:
        print(f"Error listing users: {e}")

if __name__ == "__main__":
    list_users()
