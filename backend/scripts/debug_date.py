import os
import sys
from datetime import date, timedelta, datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app as _app  # ensure env
from db_factory import get_db_connection
from utils import parse_db_date


def main():
    vendor_id = int(os.environ.get("VENDOR_ID", "0"))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT end_date, grace_period_days FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
    row = c.fetchone()
    print("raw:", row)
    ed = row[0] if not isinstance(row, dict) else row.get("end_date")
    print("type ed:", type(ed))
    parsed = parse_db_date(ed)
    print("parsed:", parsed, type(parsed))
    limit_date = parsed + timedelta(days=row[1] if not isinstance(row, dict) else row.get("grace_period_days") or 0)
    print("limit:", limit_date, type(limit_date))
    print("today:", date.today(), type(date.today()))
    try:
        print("cmp:", date.today() > limit_date)
    except Exception as e:
        print("cmp error:", e, type(e))


if __name__ == "__main__":
    raise SystemExit(main())
