import os
import sqlite3
import unittest
import json
import base64
from flask import Flask

# Set Test DB Path
TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_faces.db')
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
os.environ['DB_PATH'] = TEST_DB

from app import app, init_db, migrate_faces_pk, serializer

class TestDuplicateUsers(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        
        # Initialize DB
        with app.app_context():
            init_db()
            migrate_faces_pk()
            
            # Setup Vendor & Subscription (required for upload_face)
            conn = sqlite3.connect(TEST_DB)
            c = conn.cursor()
            # Create vendor (No password column)
            c.execute("INSERT OR IGNORE INTO vendors (email, company_name) VALUES (?, ?)",
                      ('test@vendor.com', 'Test Corp'))
            self.vendor_id = c.lastrowid
            
            # Create system user for vendor
            c.execute("INSERT OR IGNORE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)",
                      ('test_vendor', 'pass', 'admin', self.vendor_id))
            
            # Create subscription
            c.execute("INSERT OR IGNORE INTO subscriptions (vendor_id, plan_type, max_users) VALUES (?, ?, ?)",
                      (self.vendor_id, 'basic', 100))
            
            # Create company
            c.execute("INSERT OR IGNORE INTO companies (name, vendor_id) VALUES (?, ?)",
                      ('Test Company', self.vendor_id))
            
            conn.commit()
            conn.close()
            
            # Generate Token
            self.token = serializer.dumps({'username': 'test_vendor', 'role': 'admin'})
            self.headers = {'Authorization': f'Bearer {self.token}'}

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_duplicate_users(self):
        # 1. Create First "John Doe"
        res1 = self.app.post('/api/sync/upload', json={
            "name": "John Doe",
            "vendor_id": self.vendor_id,
            "shift": "Morning"
        }, headers=self.headers)
        
        if res1.status_code != 200:
            print(f"Error 1: {res1.json}")
            
        self.assertEqual(res1.status_code, 200)
        id1 = res1.json.get('person_id')
        self.assertIsNotNone(id1)
        print(f"User 1 ID: {id1}")

        # 2. Create Second "John Doe" (Duplicate Name)
        res2 = self.app.post('/api/sync/upload', json={
            "name": "John Doe",
            "vendor_id": self.vendor_id,
            "shift": "Night"
        }, headers=self.headers)
        
        if res2.status_code != 200:
            print(f"Error 2: {res2.json}")

        self.assertEqual(res2.status_code, 200)
        id2 = res2.json.get('person_id')
        self.assertIsNotNone(id2)
        print(f"User 2 ID: {id2}")

        self.assertNotEqual(id1, id2, "IDs should be different for duplicate names")

        # 3. Verify in DB
        conn = sqlite3.connect(TEST_DB)
        c = conn.cursor()
        c.execute("SELECT id, name, shift FROM faces WHERE name = ?", ("John Doe",))
        rows = c.fetchall()
        self.assertEqual(len(rows), 2, "Should have 2 John Does")
        
        # 4. Verify Person Event (Recognition)
        # Case A: Recognize User 1 (Morning Shift)
        # We simulate what the Android app sends: person_id + name
        res_evt1 = self.app.post('/api/person-event', json={
            "person_id": id1,
            "name": "John Doe",
            "timestamp": "2023-10-27T08:00:00",
            "detected": True,
            "recognized": True
        })
        self.assertEqual(res_evt1.status_code, 200)
        
        c.execute("SELECT person_id, activity FROM attendance WHERE person_id = ?", (id1,))
        att1 = c.fetchone()
        self.assertIsNotNone(att1, "Attendance should be recorded for User 1")
        # Verify it didn't record for User 2
        c.execute("SELECT * FROM attendance WHERE person_id = ?", (id2,))
        att2 = c.fetchone()
        self.assertIsNone(att2, "User 2 should not have attendance")

        # Case B: Recognize User 2 (Night Shift)
        res_evt2 = self.app.post('/api/person-event', json={
            "person_id": id2,
            "name": "John Doe",
            "timestamp": "2023-10-27T20:00:00",
            "detected": True,
            "recognized": True
        })
        self.assertEqual(res_evt2.status_code, 200)
        
        c.execute("SELECT * FROM attendance WHERE person_id = ?", (id2,))
        att2_new = c.fetchone()
        self.assertIsNotNone(att2_new, "Attendance should be recorded for User 2")

        conn.close()

if __name__ == '__main__':
    unittest.main()
