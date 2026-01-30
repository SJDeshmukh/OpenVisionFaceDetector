import unittest
from unittest import mock
import sqlite3
import json
import os
import time
from app import app, generate_token

class TestVendorFeatures(unittest.TestCase):
    
    def setUp(self):
        self.test_db = f"test_features_{int(time.time())}.db"
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
        
        c.execute('''CREATE TABLE IF NOT EXISTS system_settings
                     (key TEXT PRIMARY KEY, value TEXT)''')
        
        # Add faces table for payroll endpoint
        c.execute('''CREATE TABLE IF NOT EXISTS faces
                     (id INTEGER PRIMARY KEY, name TEXT, vendor_id INTEGER, daily_wage REAL, 
                      department TEXT, designation TEXT, face_image TEXT, phone TEXT,
                      late_allowance_days INTEGER, late_deduction_amount REAL,
                      shift TEXT)''')
        
        # Add attendance table
        c.execute('''CREATE TABLE IF NOT EXISTS attendance
                     (id INTEGER PRIMARY KEY, name TEXT, timestamp TEXT, status TEXT, 
                      activity TEXT, is_late INTEGER, vendor_id INTEGER)''')

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

        # Invoices
        c.execute('''CREATE TABLE IF NOT EXISTS invoices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      vendor_id INTEGER, 
                      invoice_date DATE, 
                      due_date DATE,
                      amount REAL,
                      status TEXT DEFAULT 'generated',
                      details TEXT,
                      FOREIGN KEY(vendor_id) REFERENCES vendors(id))''')

        self.conn.commit()

    def test_feature_toggling(self):
        # Patch sqlite3.connect to point to our test DB
        original_connect = sqlite3.connect
        def side_effect(db_name, *args, **kwargs):
            if str(db_name) == self.test_db or str(db_name).endswith(self.test_db):
                return original_connect(db_name, *args, **kwargs)
            return original_connect(self.test_db, *args, **kwargs)

        with mock.patch('sqlite3.connect', side_effect=side_effect):
            with app.test_client() as client:
                # 1. Login as SuperAdmin
                res = client.post('/api/auth/login', json={
                    "username": "superadmin_test",
                    "password": "test1234"
                })
                self.assertEqual(res.status_code, 200)
                token = res.get_json()['token']
                headers = {"Authorization": f"Bearer {token}"}

                # 2. Create Vendor with 'payroll' feature ENABLED
                unique_suffix = int(time.time())
                vendor_data = {
                    "company_name": f"Feature Test Co {unique_suffix}",
                    "contact_person": "Tester",
                    "features": ["payroll", "mobile_app"]
                }
                
                res = client.post('/api/admin/vendors', json=vendor_data, headers=headers)
                self.assertEqual(res.status_code, 200)
                data = res.get_json()
                vendor_id = data['vendor_id']
                admin_creds = data['admin_credentials']
                
                # 3. Verify Subscription has features
                res = client.get(f'/api/admin/vendors/{vendor_id}/subscription', headers=headers)
                self.assertEqual(res.status_code, 200)
                sub_data = res.get_json()
                self.assertIn("payroll", sub_data['features'])
                self.assertIn("mobile_app", sub_data['features'])
                
                # 4. Login as Vendor Admin
                res = client.post('/api/auth/login', json={
                    "username": admin_creds['username'],
                    "password": admin_creds['password']
                })
                self.assertEqual(res.status_code, 200)
                vendor_token = res.get_json()['token']
                vendor_headers = {"Authorization": f"Bearer {vendor_token}"}
                
                # 5. Access Payroll (Should Succeed)
                # Need start_date and end_date
                res = client.get('/api/reports/payroll?start_date=2023-01-01&end_date=2023-01-31', headers=vendor_headers)
                # Expect 200 (Empty list is fine, but not 403)
                self.assertEqual(res.status_code, 200)
                
                # 6. Disable Payroll Feature (as SuperAdmin)
                # Update subscription to remove 'payroll'
                res = client.put(f'/api/admin/vendors/{vendor_id}/subscription', json={
                    "features": ["mobile_app"] # Removed payroll
                }, headers=headers)
                self.assertEqual(res.status_code, 200)
                
                # 7. Access Payroll (Should Fail with 403)
                res = client.get('/api/reports/payroll?start_date=2023-01-01&end_date=2023-01-31', headers=vendor_headers)
                self.assertEqual(res.status_code, 403)
                self.assertIn("Feature 'payroll' is not enabled", res.get_json()['error'])
                
                # 8. Re-enable Payroll
                res = client.put(f'/api/admin/vendors/{vendor_id}/subscription', json={
                    "features": ["payroll"]
                }, headers=headers)
                self.assertEqual(res.status_code, 200)
                
                # 9. Access Payroll (Should Succeed again)
                res = client.get('/api/reports/payroll?start_date=2023-01-01&end_date=2023-01-31', headers=vendor_headers)
                self.assertEqual(res.status_code, 200)

                # 10. Check /persons/wages (Requires 'payroll') - Should Succeed
                res = client.put('/api/persons/wages', json={"updates": []}, headers=vendor_headers)
                self.assertEqual(res.status_code, 200)

                # 11. Check /reports/analytics (Requires 'reports') - Should Fail (not enabled)
                res = client.get('/api/reports/analytics', headers=vendor_headers)
                self.assertEqual(res.status_code, 403)
                self.assertIn("Feature 'reports' is not enabled", res.get_json()['error'])

                # 12. Enable 'reports' feature
                res = client.put(f'/api/admin/vendors/{vendor_id}/subscription', json={
                    "features": ["payroll", "reports"]
                }, headers=headers)
                self.assertEqual(res.status_code, 200)

                # 13. Check /reports/analytics - Should Succeed
                res = client.get('/api/reports/analytics', headers=vendor_headers)
                self.assertEqual(res.status_code, 200)

    def test_extended_features(self):
        # Patch sqlite3.connect to point to our test DB
        original_connect = sqlite3.connect
        def side_effect(db_name, *args, **kwargs):
            if str(db_name) == self.test_db or str(db_name).endswith(self.test_db):
                return original_connect(db_name, *args, **kwargs)
            return original_connect(self.test_db, *args, **kwargs)

        with mock.patch('sqlite3.connect', side_effect=side_effect):
            with app.test_client() as client:
                # 1. Login as SuperAdmin
                res = client.post('/api/auth/login', json={
                    "username": "superadmin_test",
                    "password": "test1234"
                })
                self.assertEqual(res.status_code, 200)
                token = res.get_json()['token']
                headers = {"Authorization": f"Bearer {token}"}

                # 2. Create Vendor with NO features
                unique_suffix = int(time.time())
                vendor_data = {
                    "company_name": f"Feature Test Ext {unique_suffix}",
                    "contact_person": "Tester",
                    "features": []
                }
                
                res = client.post('/api/admin/vendors', json=vendor_data, headers=headers)
                self.assertEqual(res.status_code, 200)
                data = res.get_json()
                vendor_id = data['vendor_id']
                admin_creds = data['admin_credentials']
                
                # 3. Login as Vendor Admin
                res = client.post('/api/auth/login', json={
                    "username": admin_creds['username'],
                    "password": admin_creds['password']
                })
                self.assertEqual(res.status_code, 200)
                vendor_token = res.get_json()['token']
                vendor_headers = {"Authorization": f"Bearer {vendor_token}"}
                
                # 4. Check /reports/filters (Should Fail)
                res = client.get('/api/reports/filters', headers=vendor_headers)
                self.assertEqual(res.status_code, 403)
                
                # 5. Check /sync/upload (Should Fail)
                res = client.post('/api/sync/upload', json={"name": "test"}, headers=vendor_headers)
                self.assertEqual(res.status_code, 403)
                
                # 6. Check /sync/download (Should Fail)
                res = client.get('/api/sync/download', headers=vendor_headers)
                self.assertEqual(res.status_code, 403)
                
                # 7. Enable 'reports' feature
                res = client.put(f'/api/admin/vendors/{vendor_id}/subscription', json={
                    "features": ["reports"]
                }, headers=headers)
                self.assertEqual(res.status_code, 200)
                
                # 8. Check /reports/filters (Should Succeed)
                res = client.get('/api/reports/filters', headers=vendor_headers)
                self.assertEqual(res.status_code, 200)
                
                # 9. Enable 'mobile_app' feature
                res = client.put(f'/api/admin/vendors/{vendor_id}/subscription', json={
                    "features": ["reports", "mobile_app"]
                }, headers=headers)
                self.assertEqual(res.status_code, 200)
                
                # 10. Check /sync/upload (Should Succeed - but might fail validation, not auth/feature)
                res = client.post('/api/sync/upload', json={"name": "test"}, headers=vendor_headers)
                if res.status_code == 403:
                    error_msg = res.get_json().get('error', '')
                    self.assertNotIn("Feature 'mobile_app' is not enabled", error_msg)
                
                # 11. Check /sync/download (Should Succeed)
                res = client.get('/api/sync/download', headers=vendor_headers)
                self.assertEqual(res.status_code, 200)

                # 12. Check /companies/{id}/draft (Requires 'shifts') - Should Fail
                # Need company_id first
                res = client.get(f'/api/companies?vendor_id={vendor_id}', headers=vendor_headers)
                companies = res.get_json()['companies']
                if not companies:
                    # Create one if not exists (though setup should have created one)
                    res = client.post('/api/companies', json={"name": "Test Co"}, headers=vendor_headers)
                    company_id = res.get_json()['id']
                else:
                    company_id = companies[0]['id']
                
                res = client.put(f'/api/companies/{company_id}/draft', json={"draft_timetable": []}, headers=vendor_headers)
                self.assertEqual(res.status_code, 403)
                
                # 13. Enable 'shifts' feature
                res = client.put(f'/api/admin/vendors/{vendor_id}/subscription', json={
                    "features": ["reports", "mobile_app", "shifts"]
                }, headers=headers)
                self.assertEqual(res.status_code, 200)
                
                # 14. Check /companies/{id}/draft (Should Succeed)
                res = client.put(f'/api/companies/{company_id}/draft', json={"draft_timetable": []}, headers=vendor_headers)
                self.assertEqual(res.status_code, 200)

if __name__ == '__main__':
    unittest.main()
