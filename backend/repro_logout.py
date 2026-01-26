
import sqlite3
import os
import sys

# Ensure backend directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, DB_PATH

def run_test():
    print(f"Using DB: {DB_PATH}")
    
    # 1. Setup: Create a temp user
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Clean up first
    c.execute("DELETE FROM system_users WHERE username = 'temp_user_logout'")
    conn.commit()
    
    # Create user
    print("Creating temp user...")
    c.execute("INSERT INTO system_users (username, password, role) VALUES ('temp_user_logout', 'password', 'super_admin')")
    conn.commit()
    conn.close()

    try:
        with app.test_client() as client:
            # 2. Login
            print("Logging in...")
            resp = client.post('/api/auth/login', json={'username': 'temp_user_logout', 'password': 'password'})
            if resp.status_code != 200:
                print(f"Login failed: {resp.status_code} {resp.data}")
                return

            data = resp.get_json()
            token = data.get('token')
            print(f"Token obtained: {bool(token)}")

            if token:
                # 3. Delete User
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("DELETE FROM system_users WHERE username = 'temp_user_logout'")
                conn.commit()
                conn.close()
                print("User deleted from DB")

                # 4. Access Protected Endpoint (Super Admin)
                # create_vendor is at /api/admin/vendors POST and uses @super_admin_required
                
                headers = {'Authorization': f'Bearer {token}'}
                print("Attempting to access Super Admin endpoint with deleted user token...")
                
                # Payload doesn't matter much if auth fails first, but let's provide valid dummy data
                # to avoid 400 Bad Request masking the Auth success.
                payload = {"company_name": "Deleted User Corp"}
                
                resp = client.post('/api/admin/vendors', json=payload, headers=headers)
                
                print(f"Status Code after deletion: {resp.status_code}")
                
                if resp.status_code == 401 or resp.status_code == 403:
                    print("SUCCESS: Deleted user denied access")
                else:
                    print(f"FAILURE: Deleted user still has access (Status: {resp.status_code})")
                    print(resp.get_json())

    finally:
        # Cleanup just in case
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM system_users WHERE username = 'temp_user_logout'")
        conn.commit()
        conn.close()

if __name__ == "__main__":
    run_test()
