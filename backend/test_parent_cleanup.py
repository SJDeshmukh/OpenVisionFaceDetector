import os
import sqlite3
import unittest
from datetime import datetime

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parent_cleanup.db')
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
os.environ['DB_PATH'] = TEST_DB
from app import app, init_db, migrate_faces_pk, serializer

class TestParentCleanup(unittest.TestCase):
    def setUp(self):
        init_db()
        migrate_faces_pk()
        self.client = app.test_client()
        self.super_headers = {
            "Authorization": f"Bearer {serializer.dumps({'username':'superadmin','role':'super_admin'})}",
            "X-Vendor-ID": "1",
        }
        conn = sqlite3.connect(TEST_DB)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS vendors (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT, status TEXT DEFAULT 'active', web_login_enabled INTEGER DEFAULT 1, frontend_bundle_id TEXT, backend_service_id TEXT, registration_config TEXT, vertical TEXT, config TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, features TEXT DEFAULT '[]')")
        c.execute("INSERT INTO vendors (id, company_name, status, web_login_enabled, frontend_bundle_id, backend_service_id, vertical, config) VALUES (?, ?, 'active', 1, 'attendance_payroll_ui', 'default_api', 'school', '{}')", (1, "Demo School"))
        c.execute("INSERT INTO subscriptions (vendor_id, features) VALUES (?, ?)", (1, '["mobile_app","reports","payroll","shifts"]'))
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def _create_student(self, name="sudhanshu deshmukh", student_number="111", phone="9370449595"):
        res = self.client.post('/api/sync/upload', json={
            "vendor_id": 1,
            "name": name,
            "phone": phone,
            "templates": "[]",
            "face_image": "",
            "department": "classA",
            "designation": "student",
            "shift": "morning",
            "student_number": student_number
        })
        self.assertEqual(res.status_code, 200, f"Upload failed: {res.data}")
        conn = sqlite3.connect(TEST_DB)
        c = conn.cursor()
        c.execute("SELECT id FROM faces WHERE vendor_id = ? AND name = ?", (1, name))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def _parent_login(self, student_id="111", mobile="9370449595"):
        return self.client.post('/api/parents/login', json={
            "student_id": student_id,
            "mobile_number": mobile,
            "device_id": "dev1",
            "vendor_id": 1,
            "fcm_token": "token123"
        })

    def test_parent_login_blocked_after_delete(self):
        pid = self._create_student()
        self.assertIsNotNone(pid, "Student person_id not created")

        res_login = self._parent_login()
        self.assertEqual(res_login.status_code, 200, f"Initial parent login should succeed: {res_login.data}")
        parent_token = res_login.json.get("token")
        self.assertTrue(parent_token, "Parent token missing")

        res_del = self.client.delete(f"/api/sync/delete/id/{pid}", headers=self.super_headers)
        self.assertEqual(res_del.status_code, 200, f"Delete failed: {res_del.data}")

        res_login2 = self._parent_login()
        self.assertEqual(res_login2.status_code, 404, f"Parent login should fail after deletion: {res_login2.data}")

        res_day = self.client.get("/api/parents/student-day?date=" + datetime.now().strftime("%Y-%m-%d"),
                                  headers={"Authorization": f"Bearer {parent_token}"})
        self.assertIn(res_day.status_code, (401, 404), f"Parent day should not show data: {res_day.data}")

if __name__ == '__main__':
    unittest.main()
