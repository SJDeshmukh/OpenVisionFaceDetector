import os
import sys
import time
import json

# Ensure backend package imports resolve when run from project root
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app, bootstrap_db


def main():
    # Optional inputs
    company_name = os.environ.get("COMPANY_NAME")
    if not company_name:
        company_name = "Vendor " + str(int(time.time()))

    # Prepare app and client
    bootstrap_db()
    client = app.test_client()

    # Try default superadmin passwords
    token = None
    last_resp = None
    for pwd in ("admin123", "super123"):
        r = client.post("/api/auth/login", json={"username": "superadmin", "password": pwd})
        last_resp = r
        if r.status_code == 200:
            token = r.json.get("token")
            break

    if not token:
        print(json.dumps({
            "error": "superadmin login failed",
            "status": getattr(last_resp, "status_code", None),
            "body": getattr(last_resp, "data", b"").decode("utf-8", errors="ignore")
        }))
        return 1

    headers = {"Authorization": f"Bearer {token}"}

    payload = {"company_name": company_name}
    resp = client.post("/api/admin/vendors", json=payload, headers=headers)

    out = {
        "status": resp.status_code,
        "data": resp.json if hasattr(resp, "json") else None
    }
    print(json.dumps(out, indent=2))
    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())

