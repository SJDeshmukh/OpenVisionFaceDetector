import unittest
import sqlite3
import json
import os
from datetime import datetime, timedelta
from app import app, calculate_daily_hours

# Use a test database
TEST_DB = 'test_face_recognition.db'

class TestIntegration(unittest.TestCase):
    
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.conn = sqlite3.connect(TEST_DB)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.row_factory = sqlite3.Row
        self.c = self.conn.cursor()
        
        self.c.execute('''CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            registration_config TEXT
        )''')

        self.c.execute('''CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id TEXT UNIQUE,
            name TEXT,
            email TEXT,
            password TEXT,
            status TEXT DEFAULT 'active',
            working_hours REAL DEFAULT 8.0,
            live_timetable TEXT,
            shifts TEXT
        )''')
        
        self.c.execute('''CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id TEXT,
            name TEXT,
            department TEXT,
            designation TEXT,
            phone TEXT,
            daily_wage REAL,
            face_image TEXT,
            shift TEXT,
            late_allowance_days INTEGER DEFAULT 0,
            late_deduction_amount REAL DEFAULT 0,
            display_id INTEGER,
            custom_data TEXT
        )''')
        
        self.c.execute('''CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id TEXT,
            name TEXT,
            timestamp TEXT,
            status TEXT,
            activity TEXT,
            captured_image TEXT,
            is_late INTEGER DEFAULT 0,
            department TEXT,
            designation TEXT,
            shift TEXT
        )''')

        self.c.execute('''CREATE TABLE IF NOT EXISTS system_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT,
            vendor_id TEXT,
            frontend_bundle_id TEXT
        )''')
        
        self.c.execute('''CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id TEXT,
            key TEXT,
            value TEXT
        )''')
        
        self.c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id TEXT,
            features TEXT DEFAULT '[]'
        )''')

        # Insert Dummy Company with Timetable
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True},
            {'name': 'TeaBreak', 'type': 'Break', 'is_payable': True, 'start_time': '11:00', 'end_time': '11:15'}
        ]
        self.vendor_id = 123
        self.c.execute("INSERT INTO companies (vendor_id, name, working_hours, live_timetable) VALUES (?, ?, ?, ?)",
                       (self.vendor_id, "Test Corp", 8.0, json.dumps(timetable)))
        
        self.c.execute("INSERT INTO vendors (id, company_name, registration_config) VALUES (?, ?, ?)",
                       (self.vendor_id, "Test Corp", '{"display_id": true}'))

        self.c.execute("INSERT INTO subscriptions (vendor_id, features) VALUES (?, ?)",
                       (self.vendor_id, '["payroll", "reports"]'))

        # Insert Dummy Person
        self.person_name = "John Doe"
        self.c.execute("INSERT INTO faces (vendor_id, name, daily_wage) VALUES (?, ?, ?)",
                       (self.vendor_id, self.person_name, 800.0)) # 100/hr
        
        self.conn.commit()
        
        # Configure App to use Test DB (Mocking DB_PATH is hard without patching, 
        # so we will manually insert data and test the LOGIC functions or use a context manager if app allows)
        # Since app.py imports DB_PATH from config or defines it globally, we can't easily switch it for the app instance 
        # without reloading. 
        # However, `get_payroll_report` opens `DB_PATH`. 
        # We will patch `db_factory.DB_PATH` for the test.
        import db_factory
        self.original_db_path = db_factory.DB_PATH
        self.original_db_url = db_factory.DATABASE_URL
        self.original_db_type = db_factory.DB_TYPE
        
        db_factory.DB_PATH = TEST_DB
        db_factory.DATABASE_URL = ""
        db_factory.DB_TYPE = 'sqlite'

    def tearDown(self):
        self.conn.close()
        import db_factory
        db_factory.DB_PATH = self.original_db_path
        db_factory.DATABASE_URL = self.original_db_url
        db_factory.DB_TYPE = self.original_db_type
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_payroll_report_integration(self):
                # Scenario: 
                # Day 1: 9:00 - 17:00 (8h Work).
                # Day 2: 9:00 - 11:00 (2h Work), 11:00 - 11:15 (Tea, GAP - Strictly Unpaid), 11:15 - 12:15 (1h Work). Total 3.0h.
                # Total: 11.0 Hours.
                # Wage: 800/8 = 100/hr. Total Wage = 1100.
                
                # Insert Attendance
                # Day 1
                self.c.execute("INSERT INTO attendance (vendor_id, name, timestamp, status, activity) VALUES (?, ?, ?, ?, ?)",
                               (self.vendor_id, self.person_name, "2023-10-27 09:00:00", "CHECK_IN", "Work"))
                self.c.execute("INSERT INTO attendance (vendor_id, name, timestamp, status, activity) VALUES (?, ?, ?, ?, ?)",
                               (self.vendor_id, self.person_name, "2023-10-27 17:00:00", "CHECK_OUT", "Work"))
                
                # Day 2
                self.c.execute("INSERT INTO attendance (vendor_id, name, timestamp, status, activity) VALUES (?, ?, ?, ?, ?)",
                               (self.vendor_id, self.person_name, "2023-10-28 09:00:00", "CHECK_IN", "Work"))
                self.c.execute("INSERT INTO attendance (vendor_id, name, timestamp, status, activity) VALUES (?, ?, ?, ?, ?)",
                               (self.vendor_id, self.person_name, "2023-10-28 11:00:00", "CHECK_OUT", "TeaBreak"))
                self.c.execute("INSERT INTO attendance (vendor_id, name, timestamp, status, activity) VALUES (?, ?, ?, ?, ?)",
                               (self.vendor_id, self.person_name, "2023-10-28 11:15:00", "CHECK_IN", "Work"))
                self.c.execute("INSERT INTO attendance (vendor_id, name, timestamp, status, activity) VALUES (?, ?, ?, ?, ?)",
                               (self.vendor_id, self.person_name, "2023-10-28 12:15:00", "CHECK_OUT", "Work"))
                
                self.conn.commit()
                
                # Mock Auth (Since authenticate_vendor_access checks Headers/DB)
                # We will use `unittest.mock` to patch it
                from unittest.mock import patch
                
                with patch('routes.attendance.authenticate_vendor_access', return_value=(self.vendor_id, None)):
                    with app.test_client() as client:
                        # Test JSON Report
                        response = client.get(f'/api/reports/payroll?start_date=2023-10-27&end_date=2023-10-28')
                        self.assertEqual(response.status_code, 200)
                        data = response.get_json()
                        
                        person_data = data['payroll'][0]
                        self.assertEqual(person_data['name'], self.person_name)
                        self.assertEqual(person_data['total_hours'], 11.0)
                        self.assertEqual(person_data['total_hours_str'], "11h 0m")
                        self.assertEqual(person_data['total_cost'], 1100.0)
                        
                        # Test Excel Export (was CSV)
                        response_excel = client.get(f'/api/reports/export?type=summary&start_date=2023-10-27&end_date=2023-10-28')
                        self.assertEqual(response_excel.status_code, 200)
                        self.assertEqual(response_excel.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        
                        # Verify filename ends with .xlsx
                        self.assertIn(".xlsx", response_excel.headers["Content-Disposition"])

if __name__ == '__main__':
    unittest.main()
