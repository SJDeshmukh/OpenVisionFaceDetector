import importlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date, datetime, timedelta


class TestVendorIsolation(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        self.backup_db_fd, self.backup_db_path = tempfile.mkstemp(suffix=".sqlite")
        os.environ["DB_PATH"] = self.db_path
        os.environ["DB_BACKUP_PATH"] = self.backup_db_path
        os.environ["SECRET_KEY"] = "test-only-secret-key"
        # Keep load_dotenv() from restoring the developer machine's PostgreSQL
        # URL.  These isolation tests must always use their temporary SQLite
        # database and never touch a configured external database.
        os.environ["DATABASE_URL"] = ""
        os.environ["REDIS_URL"] = ""
        os.environ["CELERY_BROKER_URL"] = ""
        os.environ["CELERY_RESULT_BACKEND"] = ""

        for module_name in list(sys.modules):
            if module_name in {'app', 'db_factory', 'utils', 'socket_handlers', 'background_tasks'} or module_name.startswith(('routes.', 'services.auth_service', 'database.')):
                sys.modules.pop(module_name, None)
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
        features = '["mobile_app","reports","payroll","shifts","live_attendance","cameras","classes","bulk_image_attendance"]'
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
            "INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, NULL)",
            ("superadmin", "x", "super_admin"),
        )

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

        from services.auth_service import generate_token
        self.v1_token = generate_token("v1", "vendor_admin", 1)
        self.v2_token = generate_token("v2", "vendor_admin", 2)
        self.super_token = generate_token("superadmin", "super_admin", None)

    def tearDown(self):
        try:
            os.close(self.db_fd)
        except Exception:
            pass
        try:
            os.remove(self.db_path)
        except Exception:
            pass
        try:
            os.close(self.backup_db_fd)
        except Exception:
            pass
        try:
            os.remove(self.backup_db_path)
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

    def test_attendance_is_idempotent_and_follows_person_across_devices(self):
        first_time = datetime.now().replace(microsecond=0)
        second_time = first_time + timedelta(minutes=1)
        first_timestamp = first_time.isoformat(timespec="milliseconds")
        second_timestamp = second_time.isoformat(timespec="milliseconds")
        first = self.client.post(
            "/api/person-event",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            json={
                "detected": True,
                "recognized": True,
                "person_id": "101",
                "name": "Untrusted Client Name",
                "confidence": 0.91,
                "is_attendance": True,
                "timestamp": first_timestamp,
                "source_event_id": f"device-a:101:{first_timestamp}",
                "source_timezone": "Asia/Kolkata",
                "device_id": "device-a",
            },
        )
        self.assertEqual(first.status_code, 200, first.data.decode())
        self.assertEqual(first.get_json()["status"], "CHECK_IN")
        self.assertTrue(first.get_json()["accepted"])

        duplicate = self.client.post(
            "/api/person-event",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            json={
                "detected": True,
                "recognized": True,
                "person_id": "101",
                "name": "Untrusted Client Name",
                "confidence": 0.91,
                "is_attendance": True,
                "timestamp": first_timestamp,
                "source_event_id": f"device-a:101:{first_timestamp}",
                "source_timezone": "Asia/Kolkata",
                "device_id": "device-a",
            },
        )
        self.assertEqual(duplicate.status_code, 200, duplicate.data.decode())
        self.assertTrue(duplicate.get_json()["duplicate"])
        self.assertEqual(duplicate.get_json()["status"], "CHECK_IN")

        second_device = self.client.post(
            "/api/person-event",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            json={
                "detected": True,
                "recognized": True,
                "person_id": "101",
                "name": "Another Wrong Name",
                "confidence": 0.92,
                "is_attendance": True,
                "timestamp": second_timestamp,
                "source_event_id": f"device-b:101:{second_timestamp}",
                "source_timezone": "Asia/Kolkata",
                "device_id": "device-b",
            },
        )
        self.assertEqual(second_device.status_code, 200, second_device.data.decode())
        self.assertEqual(second_device.get_json()["status"], "CHECK_OUT")

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT name, status, device_id FROM attendance WHERE vendor_id = 1 AND person_id = 101 ORDER BY timestamp"
        ).fetchall()
        conn.close()
        self.assertEqual(rows, [("Alex", "CHECK_IN", "device-a"), ("Alex", "CHECK_OUT", "device-b")])

    def test_attendance_rejects_cross_vendor_person_id(self):
        response = self.client.post(
            "/api/person-event",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            json={
                "detected": True,
                "recognized": True,
                "person_id": "202",
                "name": "Alex",
                "confidence": 0.9,
                "is_attendance": True,
                "source_event_id": "device-a:202:cross-tenant",
                "device_id": "device-a",
            },
        )
        self.assertEqual(response.status_code, 404, response.data.decode())

        conn = sqlite3.connect(self.db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE vendor_id = 1 AND person_id = 202"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_concurrent_live_attendance_is_serialized_per_person(self):
        barrier = Barrier(2)

        def submit(device_id):
            client = self.app.app.test_client()
            barrier.wait(timeout=2)
            return client.post(
                "/api/person-event",
                headers={"Authorization": f"Bearer {self.v1_token}"},
                json={
                    "detected": True,
                    "recognized": True,
                    "person_id": "101",
                    "name": "Alex",
                    "confidence": 0.9,
                    "is_attendance": True,
                    "source_event_id": f"{device_id}:101:live",
                    "device_id": device_id,
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, ("device-a", "device-b")))

        self.assertEqual([response.status_code for response in responses], [200, 200])
        bodies = [response.get_json() for response in responses]
        self.assertEqual(sum(body.get("accepted") is True for body in bodies), 1)
        self.assertEqual(sum(body.get("reason") == "cooldown" for body in bodies), 1)

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT status FROM attendance WHERE vendor_id = 1 AND person_id = 101"
        ).fetchall()
        conn.close()
        self.assertEqual(rows, [("CHECK_IN",)])

    def test_mobile_registration_retry_is_idempotent_and_vendor_scoped(self):
        local_uid = "device-enrollment-7f3a"
        first = self.client.post(
            "/api/sync/upload",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            json={"local_uid": local_uid, "name": "Local Alice"},
        )
        self.assertEqual(first.status_code, 200, first.data.decode())
        first_id = str(first.get_json()["person_id"])

        # Simulate a lost HTTP response followed by a retry containing newer
        # metadata. The device UUID, rather than a non-unique name, identifies
        # the already-committed registration.
        retry = self.client.post(
            "/api/sync/upload",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            json={"local_uid": local_uid, "name": "Renamed Alice"},
        )
        self.assertEqual(retry.status_code, 200, retry.data.decode())
        self.assertEqual(str(retry.get_json()["person_id"]), first_id)

        # A different vendor may independently use the same device-local UUID.
        other_vendor = self.client.post(
            "/api/sync/upload",
            headers={"Authorization": f"Bearer {self.v2_token}"},
            json={"local_uid": local_uid, "name": "Vendor Two Alice"},
        )
        self.assertEqual(other_vendor.status_code, 200, other_vendor.data.decode())
        self.assertNotEqual(str(other_vendor.get_json()["person_id"]), first_id)

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT vendor_id, name FROM faces WHERE local_uid = ? ORDER BY vendor_id",
            (local_uid,),
        ).fetchall()
        conn.close()
        self.assertEqual(rows, [(1, "Renamed Alice"), (2, "Vendor Two Alice")])

    def test_classes_and_bulk_upload_reject_another_vendor_class(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "INSERT INTO classes (vendor_id, class_year, division, branch, label, mapped_subjects) VALUES (?, ?, ?, ?, ?, '[]')",
            (1, "10", "A", "Science", "V1 Class"),
        )
        vendor_one_class = c.lastrowid
        c.execute(
            "INSERT INTO classes (vendor_id, class_year, division, branch, label, mapped_subjects) VALUES (?, ?, ?, ?, ?, '[]')",
            (2, "12", "B", "Commerce", "V2 Secret Class"),
        )
        vendor_two_class = c.lastrowid
        conn.commit()
        conn.close()

        response = self.client.get(
            "/api/classes", headers={"Authorization": f"Bearer {self.v1_token}"}
        )
        self.assertEqual(response.status_code, 200, response.data.decode())
        returned_ids = {row["id"] for row in response.get_json()["classes"]}
        self.assertIn(vendor_one_class, returned_ids)
        self.assertNotIn(vendor_two_class, returned_ids)

        response = self.client.post(
            "/api/bulk-registration/upload",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            data={
                "class_id": str(vendor_two_class),
                "file": (io.BytesIO(b"Name,Employee ID\nMallory,E-99\n"), "people.csv"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400, response.data.decode())
        self.assertIn("does not belong", response.get_json()["error"])

    def test_settings_are_persistent_and_vendor_scoped(self):
        response = self.client.post(
            "/api/settings",
            headers={
                "Authorization": f"Bearer {self.super_token}",
                "X-Vendor-ID": "1",
            },
            json={"threshold": 0.75, "cooldown": 45, "voice_greeting": False},
        )
        self.assertEqual(response.status_code, 200, response.data.decode())

        vendor_one = self.client.get(
            "/api/settings", headers={"Authorization": f"Bearer {self.v1_token}"}
        ).get_json()
        vendor_two = self.client.get(
            "/api/settings", headers={"Authorization": f"Bearer {self.v2_token}"}
        ).get_json()
        self.assertEqual(vendor_one["threshold"], "0.75")
        self.assertEqual(vendor_one["cooldown"], "45")
        self.assertEqual(vendor_one["voice_greeting"], "false")
        self.assertEqual(vendor_two["threshold"], "0.60")
        self.assertEqual(vendor_two["cooldown"], "30")
        self.assertNotIn("voice_greeting", vendor_two)

    def test_registration_configuration_is_vendor_scoped(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "UPDATE vendors SET registration_config = ? WHERE id = 1",
            (json.dumps([{"field": "employee_id", "label": "Employee ID", "type": "text"}]),),
        )
        c.execute(
            "UPDATE vendors SET registration_config = ? WHERE id = 2",
            (json.dumps([{"field": "secret", "label": "V2 Secret", "type": "text"}]),),
        )
        conn.commit()
        conn.close()

        response = self.client.get(
            "/api/admin/vendors/1/registration-config",
            headers={"Authorization": f"Bearer {self.v1_token}"},
        )
        self.assertEqual(response.status_code, 200, response.data.decode())
        fields = response.get_json()["config"]
        self.assertEqual([field["field"] for field in fields], ["employee_id"])
        self.assertNotIn("V2 Secret", response.data.decode())

        forbidden = self.client.get(
            "/api/admin/vendors/2/registration-config",
            headers={"Authorization": f"Bearer {self.v1_token}"},
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_excel_columns_replace_stale_schema_with_text_fields(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        stale = json.dumps([{"field": "obsolete", "label": "Obsolete", "type": "date"}])
        c.execute("UPDATE vendors SET registration_config = ? WHERE id = 1", (stale,))
        c.execute(
            "INSERT INTO bulk_attendance_config (vendor_id, fields) VALUES (?, ?)",
            (1, json.dumps([{"name": "obsolete", "label": "Obsolete", "type": "date"}])),
        )
        conn.commit()
        conn.close()

        response = self.client.post(
            "/api/bulk-registration/upload",
            headers={"Authorization": f"Bearer {self.v1_token}"},
            data={
                "file": (
                    io.BytesIO(b"Name,Employee ID,Favorite Color\nJordan,E-100,Blue\n"),
                    "people.csv",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.data.decode())

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT registration_config FROM vendors WHERE id = 1")
        schema = json.loads(c.fetchone()[0])
        conn.close()
        self.assertEqual([field["label"] for field in schema], ["Name", "Employee ID", "Favorite Color"])
        self.assertTrue(all(field["type"] == "text" for field in schema))
        self.assertTrue(schema[0]["required"])
        self.assertNotIn("obsolete", {field["field"] for field in schema})

    def test_daily_wages_cannot_access_face_reset_api(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("UPDATE vendors SET vertical = 'daily_wages' WHERE id = 1")
        c.execute(
            "UPDATE subscriptions SET features = ? WHERE vendor_id = 1",
            ('["parent_login","mobile_app","reports"]',),
        )
        conn.commit()
        conn.close()

        response = self.client.get(
            "/api/admin/face-reset-requests",
            headers={"Authorization": f"Bearer {self.v1_token}"},
        )
        self.assertEqual(response.status_code, 404, response.data.decode())


if __name__ == "__main__":
    unittest.main()
