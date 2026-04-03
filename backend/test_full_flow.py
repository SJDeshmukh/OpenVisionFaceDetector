import sys
import os
import json
import base64

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app import app, get_db_connection

def run_full_test():
    client = app.test_client()
    
    # 1. Create a FRESH Test Vendor
    conn = get_db_connection()
    c = conn.cursor()
    
    test_vendor_name = "Full Flow Test " + base64.b64encode(os.urandom(4)).decode('ascii').strip('=')
    print(f"Creating fresh test vendor: {test_vendor_name}")
    
    # Explicitly set web_login_enabled = 1
    c.execute("INSERT INTO vendors (company_name, status, vertical, web_login_enabled) VALUES (%s, 'active', 'school', 1)", (test_vendor_name,))
    vendor_id = c.lastrowid
    
    print(f"Vendor created with ID: {vendor_id}")
    
    # Enable required features
    features = json.dumps(["leave_management", "mobile_app", "reports"])
    c.execute("INSERT INTO subscriptions (vendor_id, plan_type, features, max_employees) VALUES (%s, 'pro', %s, 100)", (vendor_id, features))
    
    # Create vendor admin
    from services.auth_service import hash_password
    admin_username = "adm_" + base64.b64encode(os.urandom(4)).decode('ascii').replace('=', '').replace('/', '').replace('+', '')
    admin_password = "password123"
    
    print(f"Creating vendor admin: {admin_username}")
    c.execute(
        "INSERT INTO system_users (username, password, password_plain, role, vendor_id) VALUES (%s, %s, %s, %s, %s)",
        (admin_username, hash_password(admin_password), admin_password, "vendor_admin", vendor_id)
    )

    conn.commit()
    conn.close()
    
    print(f"\n--- STEP 1: Vendor Admin Login ({admin_username}) ---")
    resp = client.post('/api/auth/login', json={
        "username": admin_username,
        "password": admin_password,
        "platform": "web"
    })
    if resp.status_code != 200:
        print(f"Admin Login Failed: {resp.get_json()}")
        return
    admin_token = resp.get_json()['token']
    print("Admin Login Success")

    print("\n--- STEP 2: Register Student Face ---")
    student_id = "STU_" + base64.b64encode(os.urandom(4)).decode('ascii').replace('=', '').replace('/', '').replace('+', '')
    student_phone = "9876543210"
    
    print(f"Registering student: {student_id}")
    dummy_face = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDAREAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8xAAUEAQAAAAAAAAAAAAAAAAAAAAD/GBAf/2gAIAWEA/9oACAEBAAAB/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8f/8QAFAERAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8f/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8f/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8f/8QAFAERAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8f/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8f/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8f/8QAFAERAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8f/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8f/9k="
    
    registration_data = {
        "name": "Full Flow Student",
        "phone": student_phone,
        "student_number": student_id,
        "face_image": dummy_face,
        "templates": "[]"
    }
    
    resp = client.post('/api/sync/upload', 
        headers={"Authorization": f"Bearer {admin_token}"},
        json=registration_data
    )
    
    if resp.status_code != 200:
        print(f"Registration Failed: {resp.get_json()}")
        return
    else:
        print(f"Registration Success: {resp.get_json()}")

    print("\n--- STEP 3: Verify Auto-Creation of System User ---")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT username, role, password_plain FROM system_users WHERE username = %s", (student_id,))
    user = c.fetchone()
    if user:
        u = dict(zip([d[0] for d in c.description], user)) if not hasattr(user, 'keys') else dict(user)
        print(f"System User Found: {u}")
    else:
        print("System User NOT auto-created yet (checking fallback logic in login)")
    conn.close()

    print("\n--- STEP 4: Student Login ---")
    resp = client.post('/api/auth/login', json={
        "username": student_id,
        "password": student_phone,
        "device_id": "flow_test_device",
        "platform": "mobile"
    })
    
    print(f"Status: {resp.status_code}")
    login_data = resp.get_json()
    print(f"Response: {login_data}")
    
    if resp.status_code == 200:
        student_token = login_data['token']
        print("\n--- STEP 5: Fetch Student Leave History ---")
        resp = client.get('/api/student/history', headers={"Authorization": f"Bearer {student_token}"})
        print(f"History Status: {resp.status_code}")
        
        print("\n--- STEP 6: Create Leave Request ---")
        resp = client.post('/api/leave/request', 
            headers={"Authorization": f"Bearer {student_token}"},
            json={
                "student_id": student_id,
                "leave_type": "Sick",
                "reason": "Testing full flow",
                "start_date": "2026-04-04",
                "end_date": "2026-04-05"
            }
        )
        print(f"Leave Request Status: {resp.status_code}")
        print(f"Leave Request Data: {resp.get_json()}")

if __name__ == "__main__":
    with app.app_context():
        run_full_test()
