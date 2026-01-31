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
        os.environ.pop("DATABASE_URL", None)

        if "db_factory" in sys.modules:
            del sys.modules["db_factory"]
        if "app" in sys.modules:
            del sys.modules["app"]
        self.app_module = importlib.import_module("app")
        self.client = self.app_module.app.test_client()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ("hash_user", self.app_module.hash_password("secret"), "admin", None))
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

    def test_login_upgrades_plain_password_to_hash(self):
        resp = self.client.post("/api/auth/login", json={"username": "plain_user", "password": "plainpw", "platform": "web", "device_id": "d1"})
        self.assertEqual(resp.status_code, 200, resp.data.decode("utf-8"))

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT password FROM system_users WHERE username = ?", ("plain_user",))
        stored = c.fetchone()[0]
        conn.close()
        self.assertNotEqual(stored, "plainpw")
        self.assertTrue(self.app_module.verify_password("plainpw", stored))


if __name__ == "__main__":
    unittest.main()

