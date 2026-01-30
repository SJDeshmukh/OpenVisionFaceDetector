import os
import sqlite3
import unittest
import json
from datetime import datetime, timedelta
from app import app, init_db, migrate_faces_pk, serializer

# Set Test DB Path
TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_late_id.db')
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
os.environ['DB_PATH'] = TEST_DB

class TestLateWithId(unittest.TestCase):
    def setUp(self):
        import db_factory
        import app as app_module
        
        self.original_db_path = db_factory.DB_PATH
        self.original_db_type = db_factory.DB_TYPE
        self.original_app_db_type = app_module.DB_TYPE
        
        db_factory.DB_PATH = TEST_DB
        db_factory.DB_TYPE = 'sqlite'
        app_module.DB_TYPE = 'sqlite'
        
        self.app = app.test_client()
        self.app.testing = True
        
        # Initialize DB
        with app.app_context():
            init_db()
            migrate_faces_pk()
            
            conn = sqlite3.connect(TEST_DB)
            conn.execute("PRAGMA journal_mode=WAL")
            c = conn.cursor()
            
            # 1. Setup Vendor & Company
            c.execute("INSERT OR IGNORE INTO vendors (email, company_name, status, web_login_enabled) VALUES (?, ?, ?, ?)", ('test@late.com', 'Late Corp', 'active', 1))
            self.vendor_id = c.lastrowid
            
            # Add Subscription
            c.execute("INSERT INTO subscriptions (vendor_id, plan_type, features, start_date, end_date, max_employees) VALUES (?, ?, ?, ?, ?, ?)",
                      (self.vendor_id, 'Enterprise', '["shifts", "mobile_app"]', '2024-01-01', '2099-12-31', 100))

            c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ('test_admin', 'pass', 'admin', self.vendor_id))
            
            # 2. Define Timetable (Day Work 09:00 - 17:00) with Grace Period 15 mins
            timetable = [
                {
                    "name": "Day Work",
                    "type": "Work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "rules": {
                        "grace_period": 15
                    }
                }
            ]
            timetable_json = json.dumps(timetable)
            
            c.execute("INSERT INTO companies (name, vendor_id, shifts, live_timetable) VALUES (?, ?, ?, ?)",
                      ('Late Company', self.vendor_id, '[]', timetable_json))
            
            conn.commit()
            conn.close()
            
            # Generate Token
            self.token = serializer.dumps({'username': 'test_admin', 'role': 'admin'})
            self.headers = {'Authorization': f'Bearer {self.token}'}

    def tearDown(self):
        import db_factory
        db_factory.DB_PATH = self.original_db_path
        db_factory.DB_TYPE = self.original_db_type
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_duplicate_name_late_logic(self):
        # 1. Create Two "John Doe" Users
        # User 1
        res1 = self.app.post('/api/sync/upload', json={
            "name": "John Doe",
            "vendor_id": self.vendor_id
        }, headers=self.headers)
        if res1.status_code != 200:
            print(f"DEBUG: test_duplicate_name_late_logic failed. Status: {res1.status_code}, Data: {res1.data}")
        self.assertEqual(res1.status_code, 200)
        id1 = res1.json.get('person_id')
        
        # User 2
        res2 = self.app.post('/api/sync/upload', json={
            "name": "John Doe",
            "vendor_id": self.vendor_id
        }, headers=self.headers)
        if res2.status_code != 200:
            print(f"DEBUG: User 2 upload failed. Status: {res2.status_code}, Data: {res2.data}")
        self.assertEqual(res2.status_code, 200)
        id2 = res2.json.get('person_id')
        
        self.assertNotEqual(id1, id2, "IDs should be different for duplicate names")
        print(f"DEBUG: Created John Doe 1 [ID={id1}] and John Doe 2 [ID={id2}]")

        # 2. Simulate Check-In
        # User 1: LATE (09:30)
        # We need to construct a timestamp for today at 09:30
        now = datetime.now()
        time_late = now.replace(hour=9, minute=30, second=0, microsecond=0)
        
        res_evt1 = self.app.post('/api/person-event', json={
            "person_id": id1,
            "name": "John Doe",
            "timestamp": time_late.strftime("%Y-%m-%dT%H:%M:%S"),
            "detected": True,
            "recognized": True
        })
        if res_evt1.status_code != 200:
            print(f"DEBUG: User 1 event failed. Status: {res_evt1.status_code}, Data: {res_evt1.data}")
        self.assertEqual(res_evt1.status_code, 200)
        
        # User 2: ON TIME (09:00)
        time_ontime = now.replace(hour=9, minute=0, second=0, microsecond=0)
        
        res_evt2 = self.app.post('/api/person-event', json={
            "person_id": id2,
            "name": "John Doe",
            "timestamp": time_ontime.strftime("%Y-%m-%dT%H:%M:%S"),
            "detected": True,
            "recognized": True
        })
        if res_evt2.status_code != 200:
            print(f"DEBUG: User 2 event failed. Status: {res_evt2.status_code}, Data: {res_evt2.data}")
        self.assertEqual(res_evt2.status_code, 200)
        
        # 3. Verify Attendance Table
        conn = sqlite3.connect(TEST_DB)
        c = conn.cursor()
        c.execute("SELECT person_id, name, is_late FROM attendance ORDER BY person_id")
        rows = c.fetchall()
        conn.close()
        
        print("DEBUG: Attendance Rows:", rows)
        
        # Expected:
        # Row 1: ID=id1, Late=1
        # Row 2: ID=id2, Late=0
        
        # Find row for id1
        row1 = next((r for r in rows if r[0] == id1), None)
        self.assertIsNotNone(row1)
        self.assertEqual(row1[2], 1, f"User {id1} should be LATE")
        
        # Find row for id2
        row2 = next((r for r in rows if r[0] == id2), None)
        self.assertIsNotNone(row2)
        self.assertEqual(row2[2], 0, f"User {id2} should be ON TIME")
        
        print("SUCCESS: Duplicate names handled correctly with IDs for Late Logic!")

if __name__ == '__main__':
    unittest.main()
