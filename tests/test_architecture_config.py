import unittest
import json
import os
import sys
import sqlite3
from unittest.mock import patch

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app import app, DB_PATH

class TestArchitectureConfig(unittest.TestCase):

    def setUp(self):
        self.test_db = 'test_config.db'
        self.app = app.test_client()
        self.app.testing = True
        
        # Setup clean DB
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self._init_test_db()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def _init_test_db(self):
        conn = sqlite3.connect(self.test_db)
        conn.execute("PRAGMA journal_mode=WAL")
        c = conn.cursor()
        
        # Create necessary tables
        c.execute('''CREATE TABLE IF NOT EXISTS system_users
                     (username TEXT PRIMARY KEY, password TEXT, role TEXT, vendor_id INTEGER)''')
                     
        c.execute('''CREATE TABLE IF NOT EXISTS vendors
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      company_name TEXT UNIQUE, 
                      contact_person TEXT,
                      phone TEXT,
                      email TEXT,
                      status TEXT DEFAULT 'active',
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                      web_login_enabled BOOLEAN DEFAULT 1,
                      frontend_bundle_id TEXT DEFAULT 'default_attendance',
                      backend_service_id TEXT DEFAULT 'default_api',
                      config TEXT DEFAULT '{}')''')

        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      vendor_id INTEGER, 
                      plan_type TEXT DEFAULT 'basic',
                      start_date DATE,
                      end_date DATE,
                      grace_period_days INTEGER DEFAULT 7,
                      max_users INTEGER DEFAULT 10,
                      max_employees INTEGER DEFAULT 50,
                      max_mobile_devices INTEGER DEFAULT 5,
                      cost_per_user REAL DEFAULT 199.0,
                      cost_per_employee REAL DEFAULT 0.0,
                      setup_fee REAL DEFAULT 0.0,
                      setup_fee_paid BOOLEAN DEFAULT 0,
                      status TEXT DEFAULT 'active')''')
                      
        c.execute('''CREATE TABLE IF NOT EXISTS invoices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      vendor_id INTEGER, 
                      status TEXT,
                      due_date DATE)''')

        c.execute('''CREATE TABLE IF NOT EXISTS companies
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      name TEXT UNIQUE, 
                      shifts TEXT DEFAULT '[]',
                      draft_timetable TEXT, 
                      live_timetable TEXT,
                      last_modified_by TEXT,
                      last_modified_at DATETIME,
                      published_by TEXT,
                      published_at DATETIME,
                      working_hours REAL DEFAULT 8.0,
                      vendor_id INTEGER)''')

        c.execute('''CREATE TABLE IF NOT EXISTS active_sessions
                     (token TEXT PRIMARY KEY,
                      username TEXT,
                      vendor_id INTEGER,
                      device_id TEXT,
                      platform TEXT,
                      last_active DATETIME,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        # Create Default SuperAdmin
        c.execute("INSERT INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)", 
                  ('superadmin', 'admin123', 'super_admin', None))
                  
        conn.commit()
        conn.close()

    def test_vendor_config_lifecycle(self):
        # Combined test to ensure order and state
        with patch('app.DB_PATH', self.test_db):
            
            # 1. Login as SuperAdmin
            login_resp = self.app.post('/api/auth/login', json={
                "username": "superadmin",
                "password": "admin123",
                "platform": "web"
            })
            self.assertEqual(login_resp.status_code, 200)
            token = login_resp.json['token']
            headers = {'Authorization': f'Bearer {token}'}

            # 2. Create Vendor with Specific Bundle/Service
            vendor_data = {
                "company_name": "ConfigTestCorp",
                "contact_person": "Tester",
                "phone": "1234567890",
                "email": "config@test.com",
                "start_date": "2024-01-01",
                "end_date": "2030-01-01",
                "admin_username": "config_admin",
                "admin_password": "password123",
                "user_username": "config_user",
                "user_password": "password123",
                "frontend_bundle_id": "attendance_payroll_ui",
                "backend_service_id": "dedicated_db_api"
            }
            
            create_resp = self.app.post('/api/admin/vendors', json=vendor_data, headers=headers)
            self.assertEqual(create_resp.status_code, 200) # Assuming 200 for success
            
            # 3. Verify in DB
            conn = sqlite3.connect(self.test_db)
            c = conn.cursor()
            c.execute("SELECT frontend_bundle_id, backend_service_id FROM vendors WHERE company_name = ?", ('ConfigTestCorp',))
            row = c.fetchone()
            conn.close()
            
            self.assertEqual(row[0], 'attendance_payroll_ui')
            self.assertEqual(row[1], 'dedicated_db_api')

            # 4. Login as the new Vendor Admin
            login_resp = self.app.post('/api/auth/login', json={
                "username": "config_admin",
                "password": "password123",
                "platform": "web"
            })
            self.assertEqual(login_resp.status_code, 200)
            data = login_resp.json
            
            # 5. Check if config is present in response
            self.assertIn('frontend_bundle_id', data)
            self.assertIn('backend_service_id', data)
            self.assertEqual(data['frontend_bundle_id'], 'attendance_payroll_ui')
            self.assertEqual(data['backend_service_id'], 'dedicated_db_api')

if __name__ == '__main__':
    unittest.main()
