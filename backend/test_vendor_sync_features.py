
import unittest
from unittest import mock
import sqlite3
import json
import os
import time
from app import app

class TestVendorSyncFeatures(unittest.TestCase):
    
    def setUp(self):
        self.test_db = f"test_sync_{int(time.time())}.db"
        app.config['TESTING'] = True
        
        # Create a fresh DB for this test
        self.conn = sqlite3.connect(self.test_db)
        self.create_tables()
        self.conn.close()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def create_tables(self):
        c = self.conn.cursor()
        # Create necessary tables
        c.execute('''CREATE TABLE IF NOT EXISTS vendors 
                     (id INTEGER PRIMARY KEY, company_name TEXT, contact_person TEXT, 
                      phone TEXT, email TEXT, 
                      status TEXT DEFAULT 'active', 
                      web_login_enabled INTEGER DEFAULT 1,
                      frontend_bundle_id TEXT, backend_service_id TEXT,
                      config TEXT DEFAULT '{}',
                      registration_config TEXT,
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
                     (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, vendor_id INTEGER)''')
                     
        c.execute('''CREATE TABLE IF NOT EXISTS companies 
                     (id INTEGER PRIMARY KEY, name TEXT, shifts TEXT, draft_timetable TEXT, 
                      live_timetable TEXT, working_hours REAL, vendor_id INTEGER,
                      last_modified_by TEXT, last_modified_at DATETIME,
                      published_by TEXT, published_at DATETIME)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS audit_logs
                     (id INTEGER PRIMARY KEY, actor_username TEXT, action TEXT, target_vendor_id INTEGER, details TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        c.execute('''CREATE TABLE IF NOT EXISTS vendor_devices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      vendor_id INTEGER,
                      device_id TEXT,
                      device_name TEXT,
                      registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                      last_login_at DATETIME,
                      UNIQUE(vendor_id, device_id))''')

        c.execute('''CREATE TABLE IF NOT EXISTS faces
                     (id INTEGER PRIMARY KEY, name TEXT, vendor_id INTEGER, daily_wage REAL, 
                      department TEXT, designation TEXT, face_image TEXT, phone TEXT,
                      late_allowance_days INTEGER, late_deduction_amount REAL,
                      shift TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        # SuperAdmin
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)",
                  ('superadmin_test', 'test1234', 'super_admin'))
        
        # Active Sessions
        c.execute('''CREATE TABLE IF NOT EXISTS active_sessions
                     (token TEXT PRIMARY KEY,
                      username TEXT,
                      vendor_id INTEGER,
                      device_id TEXT,
                      platform TEXT,
                      last_active DATETIME,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        self.conn.commit()

    def test_vendor_sync_create_and_update(self):
        # Patch sqlite3.connect to point to our test DB
        # We use side_effect to ensure a new connection is created each time, 
        # but pointing to the same test DB file.
        def get_test_db_connection(timeout=30):
            return sqlite3.connect(self.test_db, timeout=timeout)

        with mock.patch('app.get_db_connection', side_effect=get_test_db_connection):
            
            # 1. Login as SuperAdmin
            with app.test_client() as client:
                login_resp = client.post('/api/auth/login', json={
                    "username": "superadmin_test",
                    "password": "test1234"
                })
                self.assertEqual(login_resp.status_code, 200)
                token = login_resp.json['token']
                headers = {'Authorization': f'Bearer {token}'}

                # 2. Create Vendor with Specific Subscription Fields
                vendor_payload = {
                    "company_name": "Test Sync Corp",
                    "contact_person": "John Doe",
                    "phone": "1234567890",
                    "email": "john@example.com",
                    "cost_per_employee": 150.50,
                    "max_mobile_devices": 25,
                    "max_users": 5, # Different from devices
                    "max_employees": 100,
                    "cost_per_user": 200.00
                }
                
                create_resp = client.post('/api/admin/vendors', json=vendor_payload, headers=headers)
                self.assertEqual(create_resp.status_code, 200)
                vendor_id = create_resp.json['vendor_id']
                
                # 3. Verify Persisted Data (via GET)
                get_resp = client.get('/api/admin/vendors', headers=headers)
                self.assertEqual(get_resp.status_code, 200)
                vendors = get_resp.json['vendors']
                target_vendor = next((v for v in vendors if v['id'] == vendor_id), None)
                
                self.assertIsNotNone(target_vendor)
                # Check cost_per_employee
                self.assertEqual(target_vendor['cost_per_employee'], 150.50)
                # Check max_mobile_devices
                self.assertEqual(target_vendor['max_mobile_devices'], 25)
                # Check other fields
                self.assertEqual(target_vendor['cost_per_user'], 200.00)
                self.assertEqual(target_vendor['max_employees'], 100)
                self.assertEqual(target_vendor['max_users'], 5)

                # 4. Update Vendor Subscription
                update_payload = {
                    "cost_per_employee": 250.75,
                    "max_mobile_devices": 40,
                    "max_employees": 150
                }
                
                update_resp = client.put(f'/api/admin/vendors/{vendor_id}/subscription', json=update_payload, headers=headers)
                self.assertEqual(update_resp.status_code, 200)
                
                # 5. Verify Updated Data (via GET)
                get_resp_2 = client.get('/api/admin/vendors', headers=headers)
                updated_vendors = get_resp_2.json['vendors']
                updated_vendor = next((v for v in updated_vendors if v['id'] == vendor_id), None)
                
                self.assertEqual(updated_vendor['cost_per_employee'], 250.75)
                self.assertEqual(updated_vendor['max_mobile_devices'], 40)
                self.assertEqual(updated_vendor['max_employees'], 150)
                # Verify untouched fields remained same
                self.assertEqual(updated_vendor['cost_per_user'], 200.00)
                self.assertEqual(updated_vendor['max_users'], 5)

                print("\nSUCCESS: Vendor Sync Test Passed!")
                print(f"Created with cost_per_employee={vendor_payload['cost_per_employee']}, max_mobile_devices={vendor_payload['max_mobile_devices']}")
                print(f"Updated to cost_per_employee={update_payload['cost_per_employee']}, max_mobile_devices={update_payload['max_mobile_devices']}")

if __name__ == '__main__':
    unittest.main()
