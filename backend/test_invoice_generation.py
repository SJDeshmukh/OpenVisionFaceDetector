import requests
import json
import time
import sqlite3
import os

# Configuration
BASE_URL = "http://127.0.0.1:5001"
DB_PATH = "face_db.sqlite"

def setup_super_admin():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check if superadmin_test exists
        c.execute("SELECT * FROM system_users WHERE username = 'superadmin_invoice_test'")
        row = c.fetchone()
        if row:
            print(f"Updating existing superadmin: {row}")
            c.execute("UPDATE system_users SET password = 'test1234', role = 'super_admin' WHERE username = 'superadmin_invoice_test'")
        else:
            print("Inserting new superadmin")
            c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)",
                      ('superadmin_invoice_test', 'test1234', 'super_admin'))
        conn.commit()
        
        # Verify
        c.execute("SELECT * FROM system_users WHERE username = 'superadmin_invoice_test'")
        row = c.fetchone()
        print(f"Verified SuperAdmin in DB: {row}")
        conn.close()
    except Exception as e:
        print(f"Database Setup Error: {e}")

def login_super_admin():
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "superadmin_invoice_test",
        "password": "test1234"
    })
    if response.status_code == 200:
        return response.json()['token']
    print(f"Login Failed: {response.status_code} - {response.text}")
    return None

def test_invoice_generation():
    print("=== Starting Invoice Generation Test ===")
    
    # 1. Setup & Login
    setup_super_admin()
    token = login_super_admin()
    if not token:
        print("Failed to login as SuperAdmin. Exiting.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Create Vendor with Specific Costs
    print("\n1. Creating Vendor with Specific Costs...")
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
    
    res = requests.post(f"{BASE_URL}/api/admin/vendors", json=vendor_data, headers=headers)
    if res.status_code != 200:
        print(f"Failed to create vendor: {res.text}")
        return
    
    vendor_id = res.json()['vendor_id']
    print(f"Vendor Created: {vendor_id}")
    
    # 3. Generate Invoice (Initial)
    print("\n2. Generating Initial Invoice...")
    # Expected: (10 * 100) + (2 * 200) = 1000 + 400 = 1400
    expected_amount = (10 * 100) + (2 * 200)
    
    res = requests.post(f"{BASE_URL}/api/admin/vendors/{vendor_id}/invoices/generate", headers=headers)
    if res.status_code == 200:
        invoice = res.json()
        amount = invoice['amount']
        print(f"Invoice Generated. Amount: {amount} (Expected: {expected_amount})")
        
        if float(amount) == float(expected_amount):
            print("✅ Initial Invoice Amount Correct!")
        else:
            print(f"❌ Initial Invoice Amount Incorrect! Got {amount}, expected {expected_amount}")
            
        # Check details if available
        # Note: The 'details' field in the response might be a JSON string or dict depending on implementation
        # The endpoint returns { "message": "...", "invoice_id": ..., "amount": ... }
        # We might need to fetch the invoice list to see details, but the amount is the key here.
    else:
        print(f"Failed to generate invoice: {res.text}")

    # 4. Update Subscription
    print("\n3. Updating Subscription Costs...")
    update_data = {
        "max_employees": 20,
        "cost_per_employee": 150,
        "max_users": 3,
        "cost_per_user": 250
    }
    
    res = requests.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/subscription", json=update_data, headers=headers)
    if res.status_code == 200:
        print("Subscription Updated.")
    else:
        print(f"Failed to update subscription: {res.text}")
        
    # 5. Generate Second Invoice
    print("\n4. Generating Second Invoice...")
    # Expected: (20 * 150) + (3 * 250) = 3000 + 750 = 3750
    expected_amount_2 = (20 * 150) + (3 * 250)
    
    res = requests.post(f"{BASE_URL}/api/admin/vendors/{vendor_id}/invoices/generate", headers=headers)
    if res.status_code == 200:
        invoice = res.json()
        amount = invoice['amount']
        print(f"Invoice Generated. Amount: {amount} (Expected: {expected_amount_2})")
        
        if float(amount) == float(expected_amount_2):
            print("✅ Second Invoice Amount Correct!")
        else:
            print(f"❌ Second Invoice Amount Incorrect! Got {amount}, expected {expected_amount_2}")
    else:
        print(f"Failed to generate invoice: {res.text}")

    # Cleanup
    print("\nCleaning up...")
    requests.delete(f"{BASE_URL}/api/admin/vendors/{vendor_id}", headers=headers)
    print("Done.")

if __name__ == "__main__":
    test_invoice_generation() 