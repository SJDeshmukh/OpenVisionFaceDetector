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
        import app as app_module
        self.original_db_path = app_module.DB_PATH
        app_module.DB_PATH = TEST_DB
        print(f"DEBUG: app.DB_PATH is {app_module.DB_PATH}")
        
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
            c.execute("INSERT OR IGNORE INTO vendors (email, company_name) VALUES (?, ?)", ('test@shift.com', 'Shift Corp'))
            self.vendor_id = c.lastrowid
            
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
        import app as app_module
        app_module.DB_PATH = self.original_db_path
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_strict_shift_filtering(self):
        # 1. Create "Night Owl" User (Assigned to Night Shift)
        res = self.app.post('/api/sync/upload', json={
            "name": "Night Owl",
            "vendor_id": self.vendor_id,
            "shift": "Night Shift" # Must match shift name in DB
        }, headers=self.headers)
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
