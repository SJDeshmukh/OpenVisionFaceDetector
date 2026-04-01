import unittest
import json
import sqlite3
import time
from app import app, get_db_connection

class TestRegistrationConfig(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        
        # Setup Test DB
        self.test_db = f"test_reg_config_{int(time.time())}.db"
        self.app.config['DATABASE'] = self.test_db
        
        # Override get_db_connection
        self.original_get_db_connection = get_db_connection
        def mock_get_db_connection():
            conn = sqlite3.connect(self.test_db)
            conn.row_factory = sqlite3.Row
            return conn
        app.view_functions['greeting.get_vendor_registration_config'].__globals__['get_db_connection'] = mock_get_db_connection
        app.view_functions['greeting.update_vendor_registration_config'].__globals__['get_db_connection'] = mock_get_db_connection
        app.view_functions['greeting.upload_face'].__globals__['get_db_connection'] = mock_get_db_connection
        app.view_functions['greeting.create_vendor'].__globals__['get_db_connection'] = mock_get_db_connection
        app.view_functions['greeting.login'].__globals__['get_db_connection'] = mock_get_db_connection

        self._init_db()
        
    def tearDown(self):
        import os
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def _init_db(self):
        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        
        # Create Tables
        c.execute('''CREATE TABLE IF NOT EXISTS system_users (
            username TEXT PRIMARY KEY,
            password TEXT,
            password_plain TEXT,
            person_id INTEGER,
            has_set_password INTEGER DEFAULT 0,
            role TEXT,
            vendor_id INTEGER
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            registration_config TEXT DEFAULT NULL,
            web_login_enabled INTEGER DEFAULT 1,
            frontend_bundle_id TEXT,
            backend_service_id TEXT,
            contact_person TEXT,
            phone TEXT,
            email TEXT,
            config TEXT
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            templates TEXT,
            face_image TEXT,
            phone TEXT,
            department TEXT,
            designation TEXT,
            shift TEXT,
            vendor_id INTEGER,
            custom_data TEXT
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
            vendor_id INTEGER,
            max_employees INTEGER,
            features TEXT,
            plan_type TEXT,
            start_date DATE,
            end_date DATE,
            max_users INTEGER,
            max_mobile_devices INTEGER,
            cost_per_user REAL,
            cost_per_employee REAL,
            setup_fee REAL,
            grace_period_days INTEGER DEFAULT 7
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_username TEXT,
            action TEXT,
            target_vendor_id INTEGER,
            details TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            shifts TEXT,
            draft_timetable TEXT,
            live_timetable TEXT,
            vendor_id INTEGER,
            working_hours REAL DEFAULT 8.0
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            status TEXT,
            due_date DATE,
            amount REAL,
            created_at DATETIME
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS active_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT,
            username TEXT,
            vendor_id INTEGER,
            device_id TEXT,
            platform TEXT,
            last_active DATETIME
        )''')
        
        # Create SuperAdmin
        c.execute("INSERT INTO system_users (username, password, role) VALUES ('superadmin', 'super123', 'super_admin')")
        
        conn.commit()
        conn.close()

    def test_end_to_end_flow(self):
        print("\n--- Test End-to-End Registration Config Flow ---")
        
        # 1. Login as SuperAdmin
        resp = self.client.post('/api/auth/login', json={
            "username": "superadmin",
            "password": "super123"
        })
        token = resp.json.get('token')
        headers = {'Authorization': f'Bearer {token}'}
        
        # 2. Create Vendor
        vendor_data = {
            "company_name": "Test Vendor Inc",
            "features": ["mobile_app"],
            "admin_username": "vendor_admin",
            "admin_password": "pass"
        }
        resp = self.client.post('/api/admin/vendors', json=vendor_data, headers=headers)
        self.assertEqual(resp.status_code, 200)
        vendor_id = resp.json['vendor_id']
        print(f"Vendor Created: ID {vendor_id}")
        
        # 3. Configure Registration Fields (SuperAdmin)
        config = [
            {"field": "employee_id", "label": "Employee ID", "type": "text", "required": True},
            {"field": "blood_group", "label": "Blood Group", "type": "select", "options": ["A+", "B+", "O+"]}
        ]
        
        resp = self.client.put(f'/api/admin/vendors/{vendor_id}/registration-config', 
                              json={"config": config}, 
                              headers=headers)
        self.assertEqual(resp.status_code, 200)
        print("Registration Config Set by SuperAdmin")
        
        # 4. Verify Vendor Admin can READ config
        # Login as Vendor Admin
        resp = self.client.post('/api/auth/login', json={
            "username": "vendor_admin",
            "password": "pass"
        })
        v_token = resp.json.get('token')
        v_headers = {'Authorization': f'Bearer {v_token}'}
        
        resp = self.client.get(f'/api/admin/vendors/{vendor_id}/registration-config', headers=v_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json['config']), 2)
        print("Vendor Admin verified Config")
        
        # 5. Simulate Mobile App Upload (with dynamic fields)
        # Mobile app uses Vendor Admin credentials (or specific user, but admin works for sync)
        
        upload_data = {
            "name": "John Doe",
            "phone": "1234567890",
            "face_image": "base64...",
            "templates": "base64...",
            "employee_id": "EMP001", # Dynamic Field
            "blood_group": "O+"      # Dynamic Field
        }
        
        resp = self.client.post('/api/sync/upload', json=upload_data, headers=v_headers)
        self.assertEqual(resp.status_code, 200)
        print("Mobile App Uploaded Data with Dynamic Fields")
        
        # 6. Verify Data in DB (custom_data column)
        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT custom_data FROM faces WHERE name = 'John Doe'")
        row = c.fetchone()
        self.assertIsNotNone(row)
        
        custom_data = json.loads(row[0])
        self.assertEqual(custom_data['employee_id'], "EMP001")
        self.assertEqual(custom_data['blood_group'], "O+")
        print("Verified Custom Data in Database")
        conn.close()

if __name__ == '__main__':
    unittest.main()