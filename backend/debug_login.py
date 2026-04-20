import os
import sys
from unittest.mock import MagicMock

# Mock Flask request
class MockRequest:
    def __init__(self, json_data):
        self.json = json_data
        self.headers = {}
    @property
    def remote_addr(self):
        return "127.0.0.1"

# Add backend to path
sys.path.append(os.getcwd())

# Force Postgres
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/face_db"

import app
from routes.auth import login

# Setup environment
os.environ["FLASK_DEBUG"] = "1"
os.environ["SECRET_KEY"] = "test_secret"

# Create a mock flask app context
flask_app = app.app
with flask_app.test_request_context(
    path="/api/auth/login",
    method="POST",
    json={"username": "admin", "password": "admin123", "platform": "web"}
):
    print("Simulating login for 'admin'...")
    try:
        response = login()
        print(f"Response status: {response[1] if isinstance(response, tuple) else response.status_code}")
        print(f"Response data: {response[0].get_json() if isinstance(response, tuple) else response.get_json()}")
    except Exception as e:
        print("Caught exception during login:")
        import traceback
        traceback.print_exc()
