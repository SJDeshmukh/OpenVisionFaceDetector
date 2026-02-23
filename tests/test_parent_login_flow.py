
import sqlite3
import json
import os
import requests
from datetime import datetime

# Setup
DB_PATH = 'face_db.sqlite'
URL = 'http://127.0.0.1:5002'

def run_test():
    print("--- Starting Parent Login Test ---")
    
    # 1. Direct DB Injection to simulate a registered student
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Clean up previous test data
    c.execute("DELETE FROM faces WHERE name = 'Test Student'")
    c.execute("DELETE FROM parent_users WHERE student_number = 'STU_TEST_001'")
    conn.commit()
    
    # Create a dummy student in 'faces' table
    # We need a valid vendor_id. Let's use 1.
    vendor_id = 1
    student_id = "STU_TEST_001"
    mobile = "9998887776"
    
    # Custom Data stores the dynamic fields
    custom_data = json.dumps([
        {"key": "student_number", "value": student_id},
        {"key": "department", "value": "Class X"}
    ])
    
    print(f"Injecting Student: ID={student_id}, Mobile={mobile}")
    c.execute("INSERT INTO faces (name, vendor_id, phone, custom_data) VALUES (?, ?, ?, ?)",
              ('Test Student', vendor_id, mobile, custom_data))
    conn.commit()
    conn.close()
    
    # 2. Attempt Parent Login (Should trigger the fallback logic)
    print("Attempting Parent Login via API...")
    payload = {
        "student_id": student_id,
        "mobile_number": mobile,
        "device_id": "test_device_123",
        "vendor_id": vendor_id
    }
    
    try:
        resp = requests.post(f"{URL}/api/parents/login", json=payload)
        print(f"Response Code: {resp.status_code}")
        print(f"Response Body: {resp.text}")
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                print("SUCCESS: Parent Login Successful!")
                
                # Verify parent_users table was populated
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT * FROM parent_users WHERE student_number = ?", (student_id,))
                row = c.fetchone()
                conn.close()
                
                if row:
                    print("VERIFIED: Parent User entry was automatically created.")
                else:
                    print("FAILURE: Parent User entry was NOT created.")
            else:
                print("FAILURE: Login status not success.")
        else:
            print("FAILURE: API request failed.")
            
    except Exception as e:
        print(f"Error during request: {e}")

if __name__ == "__main__":
    run_test()
