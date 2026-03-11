import os
import sys
import json

# Ensure backend imports
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app  # loads env and app


def main():
    username = os.environ.get("USERNAME")
    password = os.environ.get("PASSWORD")
    if not username or not password:
        print(json.dumps({"error": "USERNAME and PASSWORD required via env"}))
        return 1
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    data = None
    try:
        data = resp.json
    except Exception:
        pass
    print(json.dumps({"status": resp.status_code, "data": data}, indent=2))
    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
