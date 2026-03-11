import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app as _app  # ensure env
from db_factory import get_db_connection


def main():
    vendor_id = int(os.environ.get("VENDOR_ID", "0"))
    if not vendor_id:
        print("VENDOR_ID env is required")
        return 1
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE subscriptions SET end_date = NULL WHERE vendor_id = ?", (vendor_id,))
        conn.commit()
        print("ok")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
