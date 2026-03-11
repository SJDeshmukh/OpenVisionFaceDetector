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
        print("VENDOR_ID required")
        return 1
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT id, vendor_id, start_date, end_date, grace_period_days FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        row = c.fetchone()
        print("row:", row)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
