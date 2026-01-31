import os
import sqlite3
import unittest
import json
from datetime import datetime, timedelta
from app import app, init_db, migrate_faces_pk, serializer

# Set Test DB Path
TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_shift_strict.db')
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
os.environ['DB_PATH'] = TEST_DB

class TestStrictShift(unittest.TestCase):
    def setUp(self):
        import db_factory
        import app as app_module  # Rename to avoid conflict with self.app
        import importlib
        
        # Reload to reset state
        importlib.reload(db_factory)
        importlib.reload(app_module)
        
        # Re-import init_db from reloaded app
        from app import init_db, migrate_faces_pk
        
        self.original_db_path = db_factory.DB_PATH
        self.original_db_type = db_factory.DB_TYPE
        self.original_app_db_type = app_module.DB_TYPE
        
        db_factory.DB_PATH = TEST_DB
        db_factory.DB_TYPE = 'sqlite'
        app_module.DB_TYPE = 'sqlite'
        
        print(f"DEBUG: db_factory.DB_PATH is {db_factory.DB_PATH}")
        
        self.app = app.test_client()
        self.app.testing = True
        
        # Initialize DB
        with app.app_context():
            init_db()
            migrate_faces_pk()
            
            # DEBUG: Check DB Status
            if not os.path.exists(TEST_DB):
                print(f"DEBUG: DB File {TEST_DB} DOES NOT EXIST!")
                print(f"DEBUG: Directory listing for {os.path.dirname(TEST_DB)}: {os.listdir(os.path.dirname(TEST_DB))}")
            else:
                print(f"DEBUG: DB File {TEST_DB} exists. Size: {os.path.getsize(TEST_DB)}")
            
            conn = sqlite3.connect(TEST_DB)
            conn.execute("PRAGMA journal_mode=WAL")
            
            # DEBUG: List Tables
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]
            print(f"DEBUG: Tables in DB: {tables}")
            
            c = conn.cursor()
            
            # 1. Setup Vendor & Company
            c.execute("INSERT OR IGNORE INTO vendors (email, company_name, status, web_login_enabled) VALUES (?, ?, ?, ?)", ('test@shift.com', 'Shift Corp', 'active', 1))
            self.vendor_id = c.lastrowid
            
            # Add Subscription
            c.execute("INSERT INTO subscriptions (vendor_id, plan_type, features, start_date, end_date, max_employees) VALUES (?, ?, ?, ?, ?, ?)",
                      (self.vendor_id, 'Enterprise', '["shifts", "mobile_app"]', '2024-01-01', '2099-12-31', 100))

            c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", ('test_admin', 'pass', 'admin', self.vendor_id))
            
            # 2. Define Shifts
            shifts = [
                {"id": 1, "name": "Day Shift"},
                {"id": 2, "name": "Night Shift"}
            ]
            shifts_json = json.dumps(shifts)
            
            # 3. Define Timetable
            # - Global Work (09:00 - 17:00) -> Type: Work
            # - Night Work (21:00 - 05:00) -> Type: Work, Shift: 2
            timetable = [
                {
                    "name": "Global Day Work",
                    "type": "Work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "shift_id": None # Global
                },
                {
                    "name": "Night Shift Work",
                    "type": "Work",
                    "start_time": "21:00",
                    "end_time": "05:00",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "shift_id": 2 # Night Shift Only
                }
            ]
            timetable_json = json.dumps(timetable)
            
            c.execute("INSERT INTO companies (name, vendor_id, shifts, live_timetable) VALUES (?, ?, ?, ?)",
                      ('Shift Company', self.vendor_id, shifts_json, timetable_json))
            
            conn.commit()
            conn.close()
            
            # Generate Token
            self.token = serializer.dumps({'username': 'test_admin', 'role': 'admin'})
            self.headers = {'Authorization': f'Bearer {self.token}'}

    def tearDown(self):
        import db_factory
        import app as app_module
        
        db_factory.DB_PATH = self.original_db_path
        db_factory.DB_TYPE = self.original_db_type
        app_module.DB_TYPE = self.original_app_db_type
        
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_strict_shift_filtering(self):
        # 1. Create "Night Owl" User (Assigned to Night Shift)
        res = self.app.post('/api/sync/upload', json={
            "name": "Night Owl",
            "vendor_id": self.vendor_id,
            "shift": "Night Shift" # Must match shift name in DB
        }, headers=self.headers)
        if res.status_code != 200:
            print(f"DEBUG: /api/sync/upload failed. Status: {res.status_code}, Data: {res.data}")
        self.assertEqual(res.status_code, 200)
        night_user_id = res.json.get('person_id')

        # 2. Simulate Check-In at 09:15 AM (Time of Global Day Work)
        # Since user is Night Shift, they should IGNORE Global Day Work.
        # They should fall back to Night Shift Work (even though it's very early/late).
        
        # We need to mock the time. app.py uses datetime.now() if timestamp not provided.
        # But we can provide timestamp in the request.
        # Let's say today is Monday.
        today = datetime.now()
        # Find next Monday to be safe? Or just assume today is fine if we override days.
        # The timetable has all days, so day of week doesn't matter much.
        
        # 09:15 AM
        check_in_time = today.replace(hour=9, minute=15, second=0, microsecond=0)
        timestamp_str = check_in_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        res_evt = self.app.post('/api/person-event', json={
            "person_id": night_user_id,
            "name": "Night Owl",
            "timestamp": timestamp_str,
            "detected": True,
            "recognized": True
        })
        
        if res_evt.status_code != 200:
            print(f"DEBUG: /api/person-event failed. Status: {res_evt.status_code}, Data: {res_evt.data}")
        
        self.assertEqual(res_evt.status_code, 200)
        
        # 3. Verify Attendance Record
        conn = sqlite3.connect(TEST_DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT activity, status FROM attendance WHERE person_id = ?", (night_user_id,))
        att = c.fetchone()
        
        print(f"Attendance Recorded: Activity='{att['activity']}', Status='{att['status']}'")
        
        # CRITICAL ASSERTION:
        # Should be "Night Shift Work" (because Global Day Work is filtered out)
        # OR it might be empty/None if the fallback logic is too strict about time.
        # But based on my reading of fallback logic, it sorts by proximity.
        # 09:15 is closer to 09:00 (Global) than 21:00 (Night). 
        # BUT Global is filtered out. So it compares with Night (21:00).
        # So it should pick Night Shift Work.
        
        self.assertEqual(att['activity'], "Night Shift Work")
        
        conn.close()

if __name__ == '__main__':
    unittest.main()
