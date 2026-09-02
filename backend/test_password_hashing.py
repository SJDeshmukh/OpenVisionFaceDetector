import importlib
import os
import sqlite3
import sys
import tempfile
import unittest


class TestPasswordHashing(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.environ["DB_PATH"] = self.db_path
        os.environ["SECRET_KEY"] = "test-only-secret-key"
        os.environ.pop("DATABASE_URL", None)

        for module_name in list(sys.modules):
            if module_name in {'app', 'db_factory', 'utils', 'socket_handlers', 'background_tasks'} or module_name.startswith(('routes.', 'services.auth_service', 'database.')):
                sys.modules.pop(module_name, None)
        self.app_module = importlib.import_module("app")
        self.client = self.app_module.app.test_client()
        from services.auth_service import hash_password

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ("hash_user", hash_password("secret"), "admin", None))
        c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ("plain_user", "plainpw", "admin", None))
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            os.close(self.db_fd)
        except Exception:
            pass
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_login_accepts_hashed_password(self):
        resp = self.client.post("/api/auth/login", json={"username": "hash_user", "password": "secret", "platform": "web", "device_id": "d1"})
        self.assertEqual(resp.status_code, 200, resp.data.decode("utf-8"))
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")

    def test_login_rejects_plaintext_password_storage(self):
        resp = self.client.post("/api/auth/login", json={"username": "plain_user", "password": "plainpw", "platform": "web", "device_id": "d1"})
        self.assertEqual(resp.status_code, 401, resp.data.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
