import requests
import json
import os
import sqlite3

# Configuration
BASE_URL = "http://127.0.0.1:5001"
DB_PATH = "face_db.sqlite"

def get_super_admin_token():
    # Helper to generate a token (mocking login or direct generation if possible)
    # Since we can't easily login as superadmin without knowing credentials, 
    # we might need to rely on the fact that we can generate tokens if we have the SECRET_KEY.
    # But for this test, let's assume we can use the "login" endpoint if we have a superadmin.
    
    # Or, we can use the `test_edge_cases.py` approach if it mocks auth?
    # Actually, `app.py` uses `super_admin_required`.
    # Let's try to login as 'admin' (if it exists and is superadmin).
    # If not, we might need to insert a superadmin user first.
    pass

# Direct DB insertion for SuperAdmin if needed
def setup_super_admin():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Check if superadmin_test exists
    c.execute("SELECT * FROM system_users WHERE username = 'superadmin_test'")
    if c.fetchone():
        c.execute("UPDATE system_users SET password = 'test1234', role = 'super_admin' WHERE username = 'superadmin_test'")
    else:
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)",
                  ('superadmin_test', 'test1234', 'super_admin'))
    conn.commit()
    conn.close()

def login_super_admin():
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "superadmin_test",
        "password": "test1234"
    })
    if response.status_code == 200:
        return response.json()['token']
    print(f"Login Failed: {response.status_code} - {response.text}")
    return None

def test_vendor_limits():
    setup_super_admin()
    token = login_super_admin()
    if not token:
        print("Failed to login as SuperAdmin. Skipping test.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Create Vendor with Limits
    print("\n1. Creating Vendor with Limits...")
    import time
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
    
    res = requests.post(f"{BASE_URL}/api/admin/vendors", json=vendor_data, headers=headers)
    if res.status_code != 200:
        print(f"Failed to create vendor: {res.text}")
        return
    
    vendor_id = res.json()['vendor_id']
    print(f"Vendor Created: {vendor_id}")
    
    # 2. Verify Limits in Vendor List
    print("\n2. Verifying Limits in List...")
    res = requests.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
    vendors = res.json()['vendors']
    target_vendor = next((v for v in vendors if v['id'] == vendor_id), None)
    
    if target_vendor:
        print(f"Found Vendor. Max Phones: {target_vendor['max_users']}, Max Employees: {target_vendor['max_employees']}")
        assert target_vendor['max_users'] == 3
        assert target_vendor['max_employees'] == 15
        print("Limits Verified!")
    else:
        print("Vendor not found in list!")
        
    # 3. Update Limits
    print("\n3. Updating Limits...")
    update_data = {
        "max_users": 5,
        "max_employees": 20
    }
    res = requests.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/subscription", json=update_data, headers=headers)
    print(f"Update Status: {res.status_code}")
    
    # 4. Verify Update
    print("\n4. Verifying Update...")
    res = requests.get(f"{BASE_URL}/api/admin/vendors/{vendor_id}/subscription", headers=headers)
    sub = res.json()
    print(f"Updated Subscription: Max Phones: {sub['max_users']}, Max Employees: {sub['max_employees']}")
    assert sub['max_users'] == 5
    assert sub['max_employees'] == 20
    assert sub['max_mobile_devices'] == 5 # Should sync with max_users
    print("Update Verified!")

    # Cleanup
    requests.delete(f"{BASE_URL}/api/admin/vendors/{vendor_id}", headers=headers)
    print("\nCleanup Done.")

if __name__ == "__main__":
    test_vendor_limits()
