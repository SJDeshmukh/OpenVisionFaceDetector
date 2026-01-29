
import unittest
import json
import os
import sqlite3
import tempfile
from app import app, get_db_connection, BUNDLE_FEATURES

class TestComprehensiveFeatures(unittest.TestCase):
    def setUp(self):
        # Create a temporary database
        self.db_fd, self.db_path = tempfile.mkstemp()
        app.config['TESTING'] = True
        
        # Override the database connection in app.py to use our temp db
        # We'll patch get_db_connection indirectly by setting the global DB path if possible, 
        # or by manually initializing the DB at the path app uses.
        # Since app.py likely uses a hardcoded string or env var, let's assume we need to 
        # initialize the schema in the file pointed to by 'face_db.sqlite' if we were running locally,
        # but here we are in a test environment.
        # For simplicity in this existing codebase structure, we will use the app's test_client
        # but we need to make sure it uses a clean DB.
        
        # ACTUALLY: The best way is to use a separate DB file and monkeypatch get_db_connection
        # But app.py imports get_db_connection. 
        # Let's try to mock it or just use a distinct file name if app.py allows config.
        # Looking at app.py, it uses 'face_db.sqlite'.
        # We will backup the existing DB and use a test one, or just trust the isolation if we can.
        # SAFE APPROACH: Use a unique DB file name and set it in environment if app supports it, 
        # OR just mock the connection.
        
        # Given the limitations/speed, let's just create a new DB file and tell app to use it 
        # IF app.py reads from env. 
        # Checking app.py (from memory/previous reads): 
        # It usually does `sqlite3.connect('face_db.sqlite')`.
        
        # Let's create the schema in a fresh file and rename it temporarily or patch.
        # To be safe and fast, I will just create the tables in the temp db 
        # and assume I can patch the connection function or just use the existing logic if it allows injection.
        
        # Wait, I can't easily patch `app.get_db_connection` without reloading.
        # I'll define a wrapper and overwrite the function in the app module.
        
        self.original_connect = sqlite3.connect
        
        # Initialize Schema
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Create Tables (Simplified Schema for Features/Vendors)
        c.execute('''CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            contact_person TEXT,
            phone TEXT,
            email TEXT,
            frontend_bundle_id TEXT,
            backend_service_id TEXT,
            config TEXT,
            web_login_enabled INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
            vendor_id INTEGER PRIMARY KEY,
            plan_type TEXT,
            start_date DATE,
            end_date DATE,
            max_users INTEGER,
            max_employees INTEGER,
            max_mobile_devices INTEGER,
            cost_per_user REAL,
            cost_per_employee REAL,
            setup_fee REAL,
            setup_fee_paid INTEGER,
            grace_period_days INTEGER DEFAULT 0,
            features TEXT,
            FOREIGN KEY (vendor_id) REFERENCES vendors (id)
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS system_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            vendor_id INTEGER,
            FOREIGN KEY (vendor_id) REFERENCES vendors (id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            name TEXT,
            embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vendor_id) REFERENCES vendors (id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS vendor_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            device_name TEXT,
            device_id TEXT,
            status TEXT DEFAULT 'active',
            last_seen TIMESTAMP,
            FOREIGN KEY (vendor_id) REFERENCES vendors (id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            shifts TEXT,
            draft_timetable TEXT,
            live_timetable TEXT,
            vendor_id INTEGER,
            FOREIGN KEY (vendor_id) REFERENCES vendors (id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            amount REAL,
            status TEXT,
            due_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vendor_id) REFERENCES vendors (id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS active_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            token TEXT,
            vendor_id INTEGER,
            device_id TEXT,
            platform TEXT,
            ip_address TEXT,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vendor_id) REFERENCES vendors (id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        
        # Create SuperAdmin
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)",
                  ('superadmin', 'admin123', 'super_admin'))
        
        conn.commit()
        conn.close()
        
        # Patch app.get_db_connection
        self.app_module = __import__('app')
        self.original_get_db = self.app_module.get_db_connection
        
        def mock_get_db():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
            
        self.app_module.get_db_connection = mock_get_db
        self.client = app.test_client()
        
        # Login to get token
        resp = self.client.post('/api/auth/login', json={
            'username': 'superadmin',
            'password': 'admin123'
        })
        if resp.status_code != 200:
            print(f"Login Failed: {resp.status_code}")
            print(resp.data.decode())
        self.token = resp.json['token']
        self.headers = {'Authorization': f'Bearer {self.token}'}

    def tearDown(self):
        # Restore DB connection
        self.app_module.get_db_connection = self.original_get_db
        os.close(self.db_fd)
        os.remove(self.db_path)

    def test_1_create_vendor_with_bundle_defaults(self):
        """Test that creating a vendor with just a bundle ID assigns default features."""
        print("\n--- Test 1: Bundle Defaults ---")
        payload = {
            "company_name": "Bundle Test Co",
            "frontend_bundle_id": "attendance_ui",
            # features is OMITTED, should derive from bundle
            "start_date": "2024-01-01",
            "end_date": "2024-12-31"
        }
        
        resp = self.client.post('/api/admin/vendors', json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        
        # Verify DB
        conn = self.app_module.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (1,))
        features_json = c.fetchone()[0]
        conn.close()
        
        features = json.loads(features_json)
        expected = BUNDLE_FEATURES['attendance_ui']
        
        print(f"Bundle: attendance_ui")
        print(f"Expected: {expected}")
        print(f"Actual:   {features}")
        
        self.assertEqual(set(features), set(expected))

    def test_2_create_vendor_with_custom_features(self):
        """Test that explicit features override bundle defaults."""
        print("\n--- Test 2: Custom Features ---")
        custom_features = ['payroll', 'shifts', 'live_attendance', 'cameras', 'night_shift_logic', 'geofencing', 'api_access']
        payload = {
            "company_name": "Custom Feat Co",
            "frontend_bundle_id": "attendance_ui", # Should be ignored for features
            "features": custom_features,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31"
        }
        
        resp = self.client.post('/api/admin/vendors', json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        
        # Verify DB
        conn = self.app_module.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (1,))
        features_json = c.fetchone()[0]
        conn.close()
        
        features = json.loads(features_json)
        
        print(f"Input:    {custom_features}")
        print(f"Actual:   {features}")
        
        self.assertEqual(set(features), set(custom_features))

    def test_3_update_plan_limits_and_costs(self):
        """Test updating plan limits and costs."""
        print("\n--- Test 3: Plan Limits & Costs ---")
        # 1. Create Vendor
        self.client.post('/api/admin/vendors', json={"company_name": "Plan Co"}, headers=self.headers)
        
        # 2. Update Subscription
        update_payload = {
            "max_users": 10,
            "max_employees": 100,
            "max_mobile_devices": 15,
            "cost_per_user": 5.5,
            "cost_per_employee": 1.2,
            "features": ["reports"]
        }
        
        resp = self.client.put('/api/admin/vendors/1/subscription', json=update_payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        
        # Verify DB
        conn = self.app_module.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, features FROM subscriptions WHERE vendor_id = 1")
        row = c.fetchone()
        conn.close()
        
        print(f"Updated Plan: Users={row[0]}, Emps={row[1]}, Devs={row[2]}, CostUser={row[3]}, CostEmp={row[4]}")
        
        self.assertEqual(row[0], 10)
        self.assertEqual(row[1], 100)
        self.assertEqual(row[2], 15)
        self.assertEqual(row[3], 5.5)
        self.assertEqual(row[4], 1.2)
        self.assertEqual(json.loads(row[5]), ["reports"])

    def test_4_update_features_preserves_plan(self):
        """Test that updating features doesn't reset plan limits."""
        print("\n--- Test 4: Update Features Preserves Plan ---")
        # 1. Create with limits
        payload = {
            "company_name": "Preserve Co",
            "max_employees": 99,
            "features": ["reports"]
        }
        self.client.post('/api/admin/vendors', json=payload, headers=self.headers)
        
        # 2. Update Features Only
        update_payload = {
            "features": ["reports", "payroll"]
        }
        self.client.put('/api/admin/vendors/1/subscription', json=update_payload, headers=self.headers)
        
        # Verify DB
        conn = self.app_module.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT max_employees, features FROM subscriptions WHERE vendor_id = 1")
        row = c.fetchone()
        conn.close()
        
        print(f"Max Employees: {row[0]}")
        print(f"Features: {row[1]}")
        
        self.assertEqual(row[0], 99) # Should still be 99
        self.assertEqual(set(json.loads(row[1])), set(["reports", "payroll"]))

    def test_5_access_control_enforcement(self):
        """Test that features actually block/allow access to endpoints."""
        print("\n--- Test 5: Access Control Enforcement ---")
        
        # Setup: Create Vendor Admin
        self.client.post('/api/admin/vendors', json={
            "company_name": "Access Co",
            "features": ["reports"] # Has reports, NO payroll
        }, headers=self.headers)
        
        # Login as Vendor Admin
        resp = self.client.post('/api/auth/login', json={
            'username': 'admin_1',
            'password': 'default123'
        })
        vendor_token = resp.json['token']
        vendor_headers = {'Authorization': f'Bearer {vendor_token}'}
        
        # 1. Try accessing /reports/filters (Requires 'reports') -> Should Succeed
        # Note: /reports/filters is a POST usually or GET? Checking app.py
        # It's POST in my memory or recent changes. Let's try POST.
        # Actually, let's check a known protected endpoint.
        # /reports/payroll requires 'payroll'.
        
        print("Attempting /api/reports/payroll without 'payroll' feature...")
        resp = self.client.get('/api/reports/payroll', headers=vendor_headers)
        print(f"Status: {resp.status_code}, Response: {resp.json}")
        self.assertEqual(resp.status_code, 403) # Should be Forbidden
        
        # 2. Grant 'payroll' feature
        self.client.put('/api/admin/vendors/1/subscription', json={"features": ["reports", "payroll"]}, headers=self.headers)
        
        # Re-login to refresh features in session (if cached) or just retry if checked per request
        # The current implementation checks per request using the decorator which queries DB or token?
        # @require_feature checks DB usually.
        # Let's retry.
        
        print("Attempting /api/reports/payroll WITH 'payroll' feature...")
        resp = self.client.get('/api/reports/payroll', headers=vendor_headers)
        print(f"Status: {resp.status_code}")
        
        # Note: It might be 400 or 200 depending on params, but definitely NOT 403
        self.assertNotEqual(resp.status_code, 403)

    def test_6_super_admin_stats(self):
        """Test Super Admin Stats Endpoint."""
        print("\n--- Test 6: Super Admin Stats ---")
        
        # Use existing superadmin session from setUp
        response = self.client.get('/api/admin/stats', headers=self.headers)
        
        if response.status_code == 200:
            stats = response.json
            print(f"Stats received: {stats}")
            self.assertIn("total_vendors", stats)
            self.assertIn("active_vendors", stats)
            self.assertIn("total_employees", stats)
            self.assertIn("monthly_recurring_revenue", stats)
            print("✅ Admin Stats verification passed")
        else:
             print(f"❌ Failed to get stats: {response.status_code} - {response.data.decode()}")
             self.fail("Could not retrieve admin stats")

if __name__ == '__main__':
    unittest.main()
