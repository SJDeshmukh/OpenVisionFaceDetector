import os
import sys
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app as _app  # ensure env
from db_factory import get_db_connection


def main():
    vendor_id = int(os.environ.get("VENDOR_ID", "0"))
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if not vendor_id or not username or not password:
        print(json.dumps({"error": "VENDOR_ID, ADMIN_USERNAME, ADMIN_PASSWORD envs required"}))
        return 1
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, 'vendor_admin', ?)", (username, password, vendor_id))
        conn.commit()
        print("ok")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
