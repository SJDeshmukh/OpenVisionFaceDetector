import os
import sys

# Ensure backend package imports resolve when run from project root
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app as _app  # ensures .env is loaded
from db_factory import get_db_connection
from app import hash_password


def main():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM system_users WHERE role = 'super_admin' LIMIT 1")
        row = c.fetchone()
        if not row:
            c.execute(
                "INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)",
                ("superadmin", hash_password("admin123"), "super_admin", None),
            )
            conn.commit()
            print("created")
        else:
            print("exists")
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
