import os
import sqlite3
import unittest
import json
from datetime import datetime
from app import app, init_db, migrate_faces_pk, serializer

# Set Test DB Path
TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verify_late.db')
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
os.environ['DB_PATH'] = TEST_DB

class VerifyLateEndToEnd(unittest.TestCase):
    def setUp(self):
        import app as app_module
        app_module.DB_PATH = TEST_DB
        
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
            c.execute("INSERT OR IGNORE INTO vendors (email, company_name) VALUES (?, ?)", ('verify@late.com', 'Verify Corp'))
            self.vendor_id = c.lastrowid
            
            c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ('verify_admin', 'pass', 'admin', self.vendor_id))
            
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
                      ('Verify Company', self.vendor_id, '[]', timetable_json))
            
            conn.commit()
            conn.close()
            
            # Generate Token
            self.token = serializer.dumps({'username': 'verify_admin', 'role': 'admin'})
            self.headers = {'Authorization': f'Bearer {self.token}'}

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_late_verification(self):
        print("\n=== STEP 1: Creating User ===")
        res = self.app.post('/api/sync/upload', json={
            "name": "Late User",
            "vendor_id": self.vendor_id
        }, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        user_id = res.json.get('person_id')
        print(f"User Created: Late User [ID={user_id}]")

        print("\n=== STEP 2: Simulating Late Check-In ===")
        # Late Check-In at 09:30 (30 mins late, > 15 min grace)
        now = datetime.now()
        time_late = now.replace(hour=9, minute=30, second=0, microsecond=0)
        
        # This triggers app.py logic
        print(">>> Triggering app.py logic...")
        res_evt = self.app.post('/api/person-event', json={
            "person_id": user_id,
            "name": "Late User",
            "timestamp": time_late.strftime("%Y-%m-%dT%H:%M:%S"),
            "detected": True,
            "recognized": True
        })
        self.assertEqual(res_evt.status_code, 200)
        print(">>> app.py logic execution complete.")

        print("\n=== STEP 3: Verifying Database Value ===")
        conn = sqlite3.connect(TEST_DB)
        c = conn.cursor()
        c.execute("SELECT person_id, name, is_late, timestamp FROM attendance WHERE person_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        
        db_is_late = row[2]
        print(f"Database Record: Name={row[1]}, Timestamp={row[3]}, is_late={db_is_late}")
        
        if db_is_late == 1:
            print("SUCCESS: Database has is_late=1 (True)")
        else:
            print("FAILURE: Database has is_late=0 (False)")
            
        self.assertEqual(db_is_late, 1, "Database should record Late=1")

        print("\n=== STEP 4: Verifying API Response (Web Page Source) ===")
        # The web page calls GET /api/attendance
        res_api = self.app.get('/api/attendance', headers=self.headers)
        self.assertEqual(res_api.status_code, 200)
        
        attendance_list = res_api.json.get('attendance', [])
        # Find our record
        record = next((r for r in attendance_list if r['person_id'] == user_id), None)
        
        if record:
            api_is_late = record['is_late']
            print(f"API Response: Name={record['name']}, Status={record['status']}, is_late={api_is_late}")
            
            if api_is_late == 1:
                print("SUCCESS: API returns is_late=1 (Web Page will show Late)")
            else:
                print("FAILURE: API returns is_late=0")
                
            self.assertEqual(api_is_late, 1, "API should return is_late=1")
        else:
            print("FAILURE: Record not found in API response")
            self.fail("Record not found in API response")

        print("\n=== CONCLUSION ===")
        print("Logic -> Database -> API/Web Page match confirmed.")

if __name__ == '__main__':
    unittest.main()
