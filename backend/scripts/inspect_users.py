import os
import sys
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app as _app  # load env
from db_factory import get_db_connection


def main():
    vendor_id = os.environ.get("VENDOR_ID")
    conn = get_db_connection()
    conn.row_factory = __import__("sqlite3").Row if not getattr(conn, "_is_pg", False) else None
    c = conn.cursor()
    if vendor_id:
        c.execute("SELECT username, role, vendor_id FROM system_users WHERE vendor_id = ? ORDER BY username", (int(vendor_id),))
    else:
        c.execute("SELECT username, role, vendor_id FROM system_users ORDER BY username")
    rows = c.fetchall()
    data = []
    for r in rows:
        if isinstance(r, dict):
            data.append(r)
        else:
            data.append({"username": r[0], "role": r[1], "vendor_id": r[2]})
    print(json.dumps(data, indent=2))
    conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
