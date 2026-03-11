import os
import sys
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app


def main():
    vendor_id = int(os.environ.get("VENDOR_ID", "0"))
    features_env = os.environ.get("FEATURES", "")
    if not vendor_id or not features_env:
        print("VENDOR_ID and FEATURES envs required")
        return 1
    features = [f.strip() for f in features_env.split(",") if f.strip()]

    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "superadmin", "password": "admin123"})
    if resp.status_code != 200:
        resp = client.post("/api/auth/login", json={"username": "superadmin", "password": "super123"})
    if resp.status_code != 200:
        print(json.dumps({"error": "superadmin login failed", "status": resp.status_code, "data": resp.get_json(silent=True)}, indent=2))
        return 1
    token = resp.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = client.put(f"/api/admin/vendors/{vendor_id}/subscription", json={"features": features, "plan_type": "custom"}, headers=headers)
    try:
        data = r.get_json()
    except Exception:
        data = r.get_data(as_text=True)
    print(json.dumps({"status": r.status_code, "data": data}, indent=2))
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
