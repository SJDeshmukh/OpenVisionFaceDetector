import unittest
from unittest import mock
import sqlite3
import json
import os
import time
from app import app, generate_token
import db_factory

class TestSuperAdminLimits(unittest.TestCase):
    
    def setUp(self):
        self.test_db = os.path.abspath(f"test_limits_{int(time.time())}.db")
        self.original_db_path = db_factory.DB_PATH
        db_factory.DB_PATH = self.test_db
        app.config['TESTING'] = True
        
        # Create a fresh DB for this test
        self.conn = sqlite3.connect(self.test_db)
        self.create_tables()
        self.conn.close()

    def tearDown(self):
        db_factory.DB_PATH = self.original_db_path
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def create_tables(self):
        c = self.conn.cursor()
        # Create necessary tables
        c.execute('''CREATE TABLE IF NOT EXISTS vendors 
                     (id INTEGER PRIMARY KEY, company_name TEXT, contact_person TEXT, 
                      phone TEXT, email TEXT, status TEXT, web_login_enabled INTEGER,
                      frontend_bundle_id TEXT, backend_service_id TEXT,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS active_sessions
                     (token TEXT PRIMARY KEY,
                      username TEXT,
                      vendor_id INTEGER,
                      device_id TEXT,
                      platform TEXT,
                      last_active DATETIME,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                     (id INTEGER PRIMARY KEY, vendor_id INTEGER, plan_type TEXT, 
                      start_date TEXT, end_date TEXT, max_users INTEGER, 
                      max_employees INTEGER, max_mobile_devices INTEGER, 
                      cost_per_user REAL, cost_per_employee REAL, setup_fee REAL,
                      setup_fee_paid BOOLEAN,
                      grace_period_days INTEGER,
                      features TEXT DEFAULT '[]')''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS system_users 
                     (id INTEGER PRIMARY KEY, username TEXT, password TEXT,
            password_plain TEXT,
            person_id INTEGER,
            has_set_password INTEGER DEFAULT 0, role TEXT, vendor_id INTEGER)''')
                     
        c.execute('''CREATE TABLE IF NOT EXISTS companies 
                     (id INTEGER PRIMARY KEY, name TEXT, shifts TEXT, draft_timetable TEXT, 
                      live_timetable TEXT, vendor_id INTEGER)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS vendor_devices
                     (id INTEGER PRIMARY KEY, vendor_id INTEGER, device_id TEXT, device_name TEXT, 
                      status TEXT, last_seen TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS faces
                     (id INTEGER PRIMARY KEY, name TEXT, vendor_id INTEGER)''')

        # SuperAdmin
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)",
                  ('superadmin_test', 'test1234', 'super_admin'))
                  
        self.conn.commit()

    def test_vendor_limits(self):
        # Patch sqlite3.connect to point to our test DB
        original_connect = sqlite3.connect
        def side_effect(db_name, *args, **kwargs):
            # print(f"DEBUG: Connecting to {db_name}")
            # Redirect any connection that is NOT the test DB itself
            # and is NOT an in-memory DB (if used elsewhere)
            # and matches what app.py would use (likely ends with .db or .sqlite or is equal to DB_PATH)
            
            # Check if it's our test DB
            if str(db_name) == self.test_db or str(db_name).endswith(self.test_db):
                return original_connect(db_name, *args, **kwargs)
                
            # Otherwise, redirect to test DB
            # We assume app.py connects to something else
            # print(f"DEBUG: Redirecting {db_name} to {self.test_db}")
            return original_connect(self.test_db, *args, **kwargs)

        with mock.patch('sqlite3.connect', side_effect=side_effect):
            with app.test_client() as client:
                # 1. Login as SuperAdmin
                # Since we are mocking, we can just generate a token or login
                # Let's login to verify auth flow too
                res = client.post('/api/auth/login', json={
                    "username": "superadmin_test",
                    "password": "test1234"
                })
                self.assertEqual(res.status_code, 200)
                token = res.get_json()['token']
                headers = {"Authorization": f"Bearer {token}"}

                # 2. Create Vendor with Limits
                unique_suffix = int(time.time())
                vendor_data = {
                    "company_name": f"Limit Test Co {unique_suffix}",
                    "contact_person": "Tester",
                    "phone": "1234567890",
                    "email": f"test{unique_suffix}@limit.com",
                    "max_users": 3, # Phones
                    "max_employees": 15,
                    "admin_username": f"limit_admin_{unique_suffix}",
                    "admin_password": "password",
                    "user_username": f"limit_user_{unique_suffix}",
                    "user_password": "password"
                }

                res = client.post('/api/admin/vendors', json=vendor_data, headers=headers)
                if res.status_code != 200:
                    print(f"Create Vendor Failed: {res.json}")
                self.assertEqual(res.status_code, 200)
                vendor_id = res.json['vendor_id']

                # 3. Verify Limits in Vendor List
                res = client.get('/api/admin/vendors', headers=headers)
                self.assertEqual(res.status_code, 200)
                vendors = res.get_json()['vendors']
                target_vendor = next((v for v in vendors if v['id'] == vendor_id), None)
                
                self.assertIsNotNone(target_vendor)
                # Note: The API might return these as part of 'subscription' or top-level depending on implementation
                # Let's check the API response structure.
                # Based on previous reads, get_vendors returns fields from subscriptions too.
                self.assertEqual(target_vendor['max_users'], 3)
                self.assertEqual(target_vendor['max_employees'], 15)

                # 4. Update Limits
                update_data = {
                    "max_users": 5,
                    "max_employees": 20
                }
                res = client.put(f'/api/admin/vendors/{vendor_id}/subscription', json=update_data, headers=headers)
                if res.status_code != 200:
                     print(f"Update Failed: {res.json}")
                self.assertEqual(res.status_code, 200)

                # 5. Verify Update
                res = client.get('/api/admin/vendors', headers=headers)
                target_vendor = next((v for v in res.get_json()['vendors'] if v['id'] == vendor_id), None)
                self.assertEqual(target_vendor['max_users'], 5)
                self.assertEqual(target_vendor['max_employees'], 20)

if __name__ == '__main__':
    unittest.main()
