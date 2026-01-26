import unittest
from unittest import mock
import sqlite3
import json
import os
from datetime import datetime, timedelta
from app import app, DB_PATH, generate_token

class PayrollEndpointTest(unittest.TestCase):
    
    def setUp(self):
        # Use a temporary database
        self.test_db = "test_payroll.db"
        app.config['TESTING'] = True
        
        # Override the global DB_PATH in app.py logic (if possible) or just swap the file
        # Since app.py imports DB_PATH, we might need to patch it or ensure app uses a config.
        # However, app.py uses a global variable DB_PATH.
        # A safer way is to rely on the fact that we can manipulate the file at DB_PATH if we controlled it,
        # but here DB_PATH is likely fixed. 
        # Actually, looking at app.py, DB_PATH is defined at the top.
        # Let's just use a separate test file and point app.py's DB_PATH to it if we can, 
        # or mock sqlite3.connect. 
        # Given the complexity of patching globals, I will use `unittest.mock.patch` for sqlite3.connect.
        
        self.conn = sqlite3.connect(self.test_db)
        self.create_tables()
        self.populate_data()
        self.conn.close()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def create_tables(self):
        c = self.conn.cursor()
        # Create minimal tables required for payroll
        c.execute('''CREATE TABLE IF NOT EXISTS faces 
                     (id INTEGER PRIMARY KEY, name TEXT, vendor_id INTEGER, 
                      daily_wage REAL, department TEXT, designation TEXT, 
                      face_image TEXT, phone TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS attendance 
                     (id INTEGER PRIMARY KEY, name TEXT, timestamp TEXT, 
                      status TEXT, vendor_id INTEGER, activity TEXT, device_id TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS timetable 
                     (id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, 
                      start_time TEXT, end_time TEXT, type TEXT, is_payable INTEGER, tolerance INTEGER)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS companies 
                     (id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, working_hours REAL, 
                      live_timetable TEXT, draft_timetable TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS system_users 
                     (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, vendor_id INTEGER)''')

        c.execute('''CREATE TABLE IF NOT EXISTS system_settings 
                     (id INTEGER PRIMARY KEY, vendor_id INTEGER, key TEXT, value TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS vendors 
                     (id INTEGER PRIMARY KEY, status TEXT, web_login_enabled INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                     (id INTEGER PRIMARY KEY, vendor_id INTEGER, end_date TEXT, grace_period_days INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS invoices 
                     (id INTEGER PRIMARY KEY, vendor_id INTEGER, status TEXT, due_date TEXT)''')
                     
        self.conn.commit()

    def populate_data(self):
        c = self.conn.cursor()
        vendor_id = 1
        
        # 1. Company (8 hours working day)
        timetable_json = json.dumps([
            {"name": "Morning Shift", "start_time": "09:00", "end_time": "18:00", "type": "Work", "is_payable": True, "tolerance": 15},
            {"name": "Coffee Break", "start_time": "11:00", "end_time": "11:30", "type": "Break", "is_payable": True, "tolerance": 0},
            {"name": "Lunch Break", "start_time": "13:00", "end_time": "14:00", "type": "Break", "is_payable": False, "tolerance": 0}
        ])
        
        c.execute("INSERT INTO companies (vendor_id, name, working_hours, live_timetable) VALUES (?, ?, ?, ?)", 
                  (vendor_id, "Test Corp", 8.0, timetable_json))
        
        # 2. Employee (Daily Wage 800 -> 100/hr)
        c.execute("INSERT INTO faces (name, vendor_id, daily_wage, department, designation) VALUES (?, ?, ?, ?, ?)",
                  ("John Doe", vendor_id, 800.0, "IT", "Dev"))
        
        # 3. Timetable
        # Shift: 09:00 - 18:00 (Work)
        # Break: 13:00 - 14:00 (Break, Unpaid)
        c.execute("INSERT INTO timetable (vendor_id, name, start_time, end_time, type, is_payable, tolerance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (vendor_id, "Morning Shift", "09:00", "18:00", "Work", 1, 15))
        c.execute("INSERT INTO timetable (vendor_id, name, start_time, end_time, type, is_payable, tolerance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (vendor_id, "Lunch Break", "13:00", "14:00", "Break", 0, 0)) # Unpaid
        
        # 4. User for Auth
        c.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)",
                  ("admin", "pass", "admin", vendor_id))
        
        # 5. Vendor & Subscription
        c.execute("INSERT INTO vendors (id, status, web_login_enabled) VALUES (?, ?, ?)", (vendor_id, 'active', 1))
        c.execute("INSERT INTO subscriptions (vendor_id, end_date, grace_period_days) VALUES (?, ?, ?)", 
                  (vendor_id, '2099-12-31', 0))
                  
        self.conn.commit()

    def test_payroll_cross_day_logic(self):
        """
        Scenario:
        User works a night shift.
        Start: 2023-10-27 22:00:00 (Check In)
        End:   2023-10-28 02:00:00 (Check Out)
        
        Total Duration: 4 hours.
        Should be attributed to 2023-10-27.
        Payroll for 2023-10-27 should show 4 hours.
        Payroll for 2023-10-28 should show 0 hours (to avoid double count).
        """
        self.conn = sqlite3.connect(self.test_db)
        c = self.conn.cursor()
        # c.execute("ATTACH DATABASE ? AS test_db", (self.test_db,)) # Not needed if we just connect to it
        
        # Insert Attendance
        # Day 1: 22:00
        c.execute("INSERT INTO attendance (name, timestamp, status, vendor_id, activity) VALUES (?, ?, ?, ?, ?)",
                  ("John Doe", "2023-10-27 22:00:00", "CHECK_IN", 1, "Morning Shift")) # Using 'Morning Shift' as activity name for simplicity, though mapped to 'Work'
        
        # Day 2: 02:00
        c.execute("INSERT INTO attendance (name, timestamp, status, vendor_id, activity) VALUES (?, ?, ?, ?, ?)",
                  ("John Doe", "2023-10-28 02:00:00", "CHECK_OUT", 1, "Morning Shift"))
        
        self.conn.commit()
        
        # Mocking logic
        # We need to mock sqlite3.connect in app.py to point to self.test_db
        original_connect = sqlite3.connect
        with mock.patch('sqlite3.connect', side_effect=lambda *args, **kwargs: original_connect(self.test_db)):
            with app.test_client() as client:
                # Generate Token
                token = generate_token("admin", "admin")
                headers = {"Authorization": f"Bearer {token}"}
                
                # Request Report for Day 1 (Oct 27)
                resp = client.get('/api/reports/payroll?start_date=2023-10-27&end_date=2023-10-27', headers=headers)
                if resp.status_code != 200:
                    print(f"Server Error: {resp.data}")
                self.assertEqual(resp.status_code, 200)
                data = resp.json['payroll']
                
                john = next((p for p in data if p['name'] == "John Doe"), None)
                self.assertIsNotNone(john)
                print(f"\n[Day 1 Check] Hours: {john['total_hours']}")
                self.assertEqual(john['total_hours'], 4.0)
                self.assertEqual(john['total_cost'], 400.0) # 4 hours * 100/hr

                # Request Report for Day 2 (Oct 28)
                resp = client.get('/api/reports/payroll?start_date=2023-10-28&end_date=2023-10-28', headers=headers)
                data = resp.json['payroll']
                john = next((p for p in data if p['name'] == "John Doe"), None)
                print(f"[Day 2 Check] Hours: {john['total_hours']}")
                self.assertEqual(john['total_hours'], 0.0) # Should be 0, as the shift belongs to Day 1

    def test_payable_gap_logic(self):
        """
        Scenario:
        User takes a PAID break.
        09:00 CHECK_IN (Work)
        11:00 CHECK_OUT (Coffee Break - Paid)
        11:30 CHECK_IN (Work)
        13:00 CHECK_OUT (Lunch - Unpaid)
        14:00 CHECK_IN (Work)
        18:00 CHECK_OUT
        
        Total Work: (09-11) 2h + (11:30-13) 1.5h + (14-18) 4h = 7.5h
        Paid Break: (11-11:30) 0.5h
        Unpaid Break: (13-14) 1h (Excluded)
        
        Total Payable: 7.5 + 0.5 = 8.0 hours
        """
        self.conn = sqlite3.connect(self.test_db)
        # Coffee Break is already in live_timetable from populate_data
        c = self.conn.cursor()
        
        c.execute("DELETE FROM attendance")
        
        # Sequence
        events = [
            ("09:00:00", "CHECK_IN", "Morning Shift"),
            ("11:00:00", "CHECK_OUT", "Coffee Break"), # User selects Coffee Break on exit
            ("11:30:00", "CHECK_IN", "Morning Shift"),
            ("13:00:00", "CHECK_OUT", "Lunch Break"),  # User selects Lunch on exit (Unpaid)
            ("14:00:00", "CHECK_IN", "Morning Shift"),
            ("18:00:00", "CHECK_OUT", "Morning Shift")
        ]
        
        for time_str, status, activity in events:
            c.execute("INSERT INTO attendance (name, timestamp, status, vendor_id, activity) VALUES (?, ?, ?, ?, ?)",
                      ("John Doe", f"2023-10-27 {time_str}", status, 1, activity))
        self.conn.commit()

        original_connect = sqlite3.connect
        with mock.patch('sqlite3.connect', side_effect=lambda *args, **kwargs: original_connect(self.test_db)):
            with app.test_client() as client:
                token = generate_token("admin", "admin")
                headers = {"Authorization": f"Bearer {token}"}
                
                resp = client.get('/api/reports/payroll?start_date=2023-10-27&end_date=2023-10-27', headers=headers)
                data = resp.json['payroll']
                john = next((p for p in data if p['name'] == "John Doe"), None)
                
                print(f"\n[Gap Logic Check] Total Hours: {john['total_hours']}")
                # Calculation:
                # 09:00-11:00 (Work): 2h
                # 11:00-11:30 (Coffee): 0.5h (Payable Gap)
                # 11:30-13:00 (Work): 1.5h
                # 13:00-14:00 (Lunch): 1h (Unpaid Gap - Excluded)
                # 14:00-18:00 (Work): 4h
                # Total: 2 + 0.5 + 1.5 + 4 = 8.0 hours
                
                self.assertEqual(john['total_hours'], 8.0)

if __name__ == '__main__':
    unittest.main()
