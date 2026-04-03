import sys
import os
import json

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app import app, get_db_connection

def setup_and_test():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Ensure a vendor exists
    c.execute("SELECT id FROM vendors LIMIT 1")
    v = c.fetchone()
    if not v:
        c.execute("INSERT INTO vendors (company_name, status) VALUES ('Test Vendor', 'active') RETURNING id")
        vendor_id = c.fetchone()[0]
        c.execute("INSERT INTO subscriptions (vendor_id, plan_type) VALUES (%s, 'pro')", (vendor_id,))
    else:
        vendor_id = v[0] if not hasattr(v, 'keys') else v['id']
        
    print(f"Using Vendor ID: {vendor_id}")
    
    # 2. Insert test student
    custom_data = json.dumps({"student_number": "kbtug20192"})
    
    # Cleanup previous if any
    c.execute("DELETE FROM system_users WHERE username = 'kbtug20192'")
    c.execute("DELETE FROM faces WHERE phone = '9370449595' OR name = 'Test Student kbtug20192'")
    
    c.execute(
        "INSERT INTO faces (name, phone, vendor_id, custom_data) VALUES (%s, %s, %s, %s)",
        ("Test Student kbtug20192", "9370449595", vendor_id, custom_data)
    )
    conn.commit()
    conn.close()
    
    print("Test student created successfully. Testing login...")
    
    # 3. Test login API
    client = app.test_client()
    response = client.post('/api/auth/login', json={
        "username": "kbtug20192",
        "password": "9370449595",
        "device_id": "test_device_123",
        "platform": "mobile"
    })
    
    print(f"Status Code: {response.status_code}")
    print(f"Response Body: {response.get_json()}")
    
if __name__ == "__main__":
    with app.app_context():
        setup_and_test()
