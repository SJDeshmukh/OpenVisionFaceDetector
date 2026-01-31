import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta


class TestVendorIsolation(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.environ["DB_PATH"] = self.db_path
        os.environ.pop("DATABASE_URL", None)

        if "db_factory" in sys.modules:
            del sys.modules["db_factory"]
        if "app" in sys.modules:
            del sys.modules["app"]
        self.app = importlib.import_module("app")
        self.client = self.app.app.test_client()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute(
            "INSERT INTO vendors (id, company_name, status, created_at, web_login_enabled, frontend_bundle_id, backend_service_id) VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1, 'default_attendance', 'default_api')",
            (1, "Vendor One", "active"),
        )
        c.execute(
            "INSERT INTO vendors (id, company_name, status, created_at, web_login_enabled, frontend_bundle_id, backend_service_id) VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1, 'default_attendance', 'default_api')",
            (2, "Vendor Two", "active"),
        )

        end_date = (date.today() + timedelta(days=365)).isoformat()
        features = '["mobile_app","reports","payroll","shifts","live_attendance","cameras"]'
        c.execute(
            "INSERT INTO subscriptions (vendor_id, end_date, grace_period_days, max_employees, max_users, max_web_sessions, features) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, end_date, 7, 500, 50, 10, features),
        )
        c.execute(
            "INSERT INTO subscriptions (vendor_id, end_date, grace_period_days, max_employees, max_users, max_web_sessions, features) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (2, end_date, 7, 500, 50, 10, features),
        )

        c.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ("v1", "x", "vendor_admin", 1))
        c.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ("v2", "x", "vendor_admin", 2))

        c.execute(
            "INSERT INTO faces (id, name, templates, vendor_id, department) VALUES (?, ?, ?, ?, ?)",
            (101, "Alex", "t1", 1, "Dept-A"),
        )
        c.execute(
            "INSERT INTO faces (id, name, templates, vendor_id, department) VALUES (?, ?, ?, ?, ?)",
            (202, "Alex", "t2", 2, "Dept-B"),
        )

        c.execute(
            "INSERT INTO attendance (name, timestamp, status, vendor_id, person_id) VALUES (?, datetime('now'), ?, ?, NULL)",
            ("Alex", "CHECK_IN", 1),
        )

        conn.commit()
        conn.close()

        self.v1_token = self.app.generate_token("v1", "vendor_admin")
        self.v2_token = self.app.generate_token("v2", "vendor_admin")

    def tearDown(self):
        try:
            os.close(self.db_fd)
        except Exception:
            pass
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_sync_upload_cannot_update_other_vendor_person(self):
        resp = self.client.post(
            "/api/sync/upload",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            json={"person_id": 202, "name": "Alex", "department": "HACKED"},
        )
        self.assertIn(resp.status_code, (403, 404), resp.data.decode("utf-8"))

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT department, vendor_id FROM faces WHERE id = 202")
        dept, vid = c.fetchone()
        conn.close()

        self.assertEqual(vid, 2)
        self.assertEqual(dept, "Dept-B")

    def test_attendance_join_does_not_mix_vendor_faces_by_name(self):
        resp = self.client.get(
            "/api/attendance?limit=10&offset=0",
            headers={"Authorization": f"Bearer {self.v1_token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.data.decode("utf-8"))
        data = resp.get_json()
        self.assertIn("attendance", data)
        self.assertGreaterEqual(len(data["attendance"]), 1)
        row = data["attendance"][0]
        self.assertEqual(row.get("department"), "Dept-A")


if __name__ == "__main__":
    unittest.main()
