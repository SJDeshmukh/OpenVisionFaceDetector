import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app as _app
from db_factory import get_db_connection
from services.auth_service import hash_password


def main():
    username = os.environ.get("USERNAME")
    password = os.environ.get("PASSWORD")
    plain = os.environ.get("PLAIN", "0").strip().lower() in ("1","true","yes")
    if not username or not password:
        print("USERNAME and PASSWORD envs required")
        return 1
    conn = get_db_connection()
    c = conn.cursor()
    try:
        new_pw = password if plain else hash_password(password)
        c.execute("UPDATE system_users SET password = ? WHERE username = ?", (new_pw, username))
        conn.commit()
        print("ok")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
