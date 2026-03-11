import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app as _app  # ensures .env is loaded
from db_factory import get_db_connection


def main():
    new_pwd = os.environ.get("NEW_SUPERADMIN_PASSWORD", "admin123")
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Store plaintext to avoid hash backend requirements; login verifier accepts plaintext equality
        c.execute("UPDATE system_users SET password = ? WHERE username = ?", (new_pwd, "superadmin"))
        conn.commit()
        print("ok")
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
