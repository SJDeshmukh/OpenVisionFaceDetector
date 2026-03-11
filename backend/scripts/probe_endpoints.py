import os
import sys
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app  # ensure env


def main():
    username = os.environ.get("USERNAME", "admin_2")
    password = os.environ.get("PASSWORD", "default123")

    client = app.test_client()
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    if login.status_code != 200:
        print(json.dumps({"login_status": login.status_code, "login_data": login.json}, indent=2))
        return 1
    token = login.json.get("token")
    headers = {"Authorization": f"Bearer {token}"}

    for path in ("/api/reports/analytics", "/api/attendance"):
        resp = client.get(path, headers=headers)
        try:
            data = resp.json
        except Exception:
            data = resp.get_data(as_text=True)
        print(json.dumps({"path": path, "status": resp.status_code, "data": data}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
