import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta


class TestDemoSeedSmoke(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.environ["DB_PATH"] = self.db_path
        os.environ.pop("DATABASE_URL", None)

        scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        import seed_demo_data

        seed_demo_data.seed(db_path=self.db_path, reset=True)

        if "app" in sys.modules:
            del sys.modules["app"]
        self.app_module = importlib.import_module("app")
        self.client = self.app_module.app.test_client()

    def tearDown(self):
        try:
            os.close(self.db_fd)
        except Exception:
            pass
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def _login(self, username, password):
        resp = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password, "platform": "web", "device_id": "demo-web"},
        )
        self.assertEqual(resp.status_code, 200, resp.data.decode("utf-8"))
        payload = resp.get_json()
        self.assertIn("token", payload)
        return payload

    def test_vendor_pages_api_contracts(self):
        login = self._login("demo_admin", "demo123")
        headers = {"Authorization": f"Bearer {login['token']}"}

        resp = self.client.get("/api/sync/download?limit=200&offset=0", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("faces", data)
        self.assertGreaterEqual(len(data["faces"]), 5)

        today = datetime.now().date()
        start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        resp = self.client.get(f"/api/attendance?start_date={start}&end_date={end}&limit=50&offset=0", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("attendance", data)
        self.assertGreater(len(data["attendance"]), 0)
        self.assertIn("custom_data", data["attendance"][0])

        resp = self.client.get(f"/api/reports/analytics?start_date={start}&end_date={end}", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("summary", data)
        self.assertIn("pie_data", data)
        self.assertIn("bar_data", data)

        resp = self.client.get("/api/reports/filters", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("departments", data)
        self.assertIn("designations", data)
        self.assertIn("dynamic_filters", data)

        resp = self.client.get("/api/companies", headers=headers)
        self.assertEqual(resp.status_code, 200)
        companies = resp.get_json().get("companies") or []
        self.assertGreaterEqual(len(companies), 1)
        company_id = companies[0]["id"]

        resp = self.client.get(f"/api/companies/{company_id}", headers=headers)
        self.assertEqual(resp.status_code, 200)
        company = resp.get_json()
        self.assertIn("shifts", company)
        self.assertIn("draft_timetable", company)

        resp = self.client.get(f"/api/reports/payroll?start_date={start}&end_date={end}", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("payroll", data)
        self.assertGreaterEqual(len(data["payroll"]), 1)

    def test_superadmin_pages_api_contracts(self):
        login = self._login("superadmin", "super123")
        headers = {"Authorization": f"Bearer {login['token']}"}

        resp = self.client.get("/api/admin/vendors", headers=headers)
        self.assertEqual(resp.status_code, 200)
        vendors = resp.get_json().get("vendors") or []
        self.assertGreaterEqual(len(vendors), 1)

        resp = self.client.get("/api/admin/audit-logs", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("logs", data)

        resp = self.client.get("/api/admin/system/health", headers=headers)
        self.assertEqual(resp.status_code, 200)
        health = resp.get_json()
        self.assertIn("db", health)
        self.assertIn("active_sessions", health)

        resp = self.client.get("/api/admin/jobs/events?limit=20", headers=headers)
        self.assertEqual(resp.status_code, 200)
        events = resp.get_json().get("events") or []
        self.assertGreaterEqual(len(events), 1)

        resp = self.client.get("/api/admin/jobs/metrics?window_minutes=60", headers=headers)
        self.assertEqual(resp.status_code, 200)
        metrics = resp.get_json()
        self.assertIn("window_minutes", metrics)


if __name__ == "__main__":
    unittest.main()

