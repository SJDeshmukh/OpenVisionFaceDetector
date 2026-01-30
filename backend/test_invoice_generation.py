import unittest
from unittest import mock
import sqlite3
import json
import os
import time
from app import app
import db_factory

class TestInvoiceGeneration(unittest.TestCase):
    
    def setUp(self):
        self.test_db = os.path.abspath(f"test_invoice_{int(time.time())}.db")
        self.original_db_path = db_factory.DB_PATH
        db_factory.DB_PATH = self.test_db
        app.config['TESTING'] = True
        
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
                     (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, vendor_id INTEGER)''')
                     
        c.execute('''CREATE TABLE IF NOT EXISTS companies 
                     (id INTEGER PRIMARY KEY, name TEXT, shifts TEXT, draft_timetable TEXT, 
                      live_timetable TEXT, vendor_id INTEGER)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS invoices 
                     (id INTEGER PRIMARY KEY, vendor_id INTEGER, amount REAL, 
                      status TEXT, invoice_date TEXT, due_date TEXT, details TEXT)''')
        
        # SuperAdmin
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)",
                  ('superadmin_invoice_test', 'test1234', 'super_admin'))
                  
        self.conn.commit()

    def test_invoice_generation(self):
        # Patch sqlite3.connect
        original_connect = sqlite3.connect
        def side_effect(db_name, *args, **kwargs):
            # If it's the test DB, let it pass
            if str(db_name) == self.test_db or str(db_name).endswith(self.test_db):
                return original_connect(db_name, *args, **kwargs)
            # Otherwise redirect
            return original_connect(self.test_db, *args, **kwargs)

        with mock.patch('sqlite3.connect', side_effect=side_effect):
            with app.test_client() as client:
                # 1. Login
                res = client.post('/api/auth/login', json={
                    "username": "superadmin_invoice_test",
                    "password": "test1234"
                })
                self.assertEqual(res.status_code, 200)
                token = res.get_json()['token']
                headers = {"Authorization": f"Bearer {token}"}

                # 2. Create Vendor with Specific Costs
                unique_suffix = int(time.time())
                vendor_data = {
                    "company_name": f"Invoice Test Co {unique_suffix}",
                    "contact_person": "Invoice Tester",
                    "phone": "9876543210",
                    "email": f"invoice{unique_suffix}@test.com",
                    "admin_username": f"inv_admin_{unique_suffix}",
                    "admin_password": "password",
                    "user_username": f"inv_user_{unique_suffix}",
                    "user_password": "password",
                    # Subscription Details
                    "max_employees": 10,
                    "cost_per_employee": 100,
                    "max_users": 2,          # Devices
                    "cost_per_user": 200     # Cost per Device
                }

                res = client.post('/api/admin/vendors', json=vendor_data, headers=headers)
                self.assertEqual(res.status_code, 200)
                vendor_id = res.get_json()['vendor_id']

                # 3. Generate Invoice (Initial)
                # Expected: (10 * 100) + (2 * 200) = 1000 + 400 = 1400
                expected_amount = (10 * 100) + (2 * 200)

                res = client.post(f'/api/admin/vendors/{vendor_id}/invoices/generate', headers=headers)
                
                if res.status_code != 200:
                    print(f"Invoice Generation Failed: {res.get_json()}")
                    
                self.assertEqual(res.status_code, 200)
                invoice = res.get_json()
                amount = invoice['amount']
                
                print(f"Invoice Generated. Amount: {amount} (Expected: {expected_amount})")
                self.assertEqual(float(amount), float(expected_amount))

if __name__ == '__main__':
    unittest.main()
