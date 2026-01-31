import requests
import sys

# Live Backend URL
BASE_URL = "https://face-detection-backend-69o7.onrender.com"

def test_config():
    print(f"Checking Config at {BASE_URL}/api/config...")
    try:
        resp = requests.get(f"{BASE_URL}/api/config")
        if resp.status_code == 200:
            print("Config Response:", resp.json())
        else:
            print(f"Config Check Failed: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Config Check Error: {e}")

def test_auth_flow():
    print(f"\nTesting Auth Flow on {BASE_URL}...")
    
    # 1. Login
    login_url = f"{BASE_URL}/api/auth/login"
    credentials = {
        "username": "superadmin",
        "password": "super123" # Assuming default
    }
    
    try:
        session = requests.Session()
        resp = session.post(login_url, json=credentials)
        
        if resp.status_code != 200:
            print(f"Login Failed: {resp.status_code} - {resp.text}")
            return
            
        data = resp.json()
        print("Login Successful!")
        print(f"User: {data.get('username')}, Role: {data.get('role')}")
        
        token = data.get("token")
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. Create User
        print("\nCreating Test User...")
        create_url = f"{BASE_URL}/api/users"
        new_user = {
            "username": "test_live_user",
            "password": "password123",
            "role": "admin",
            "company_id": 1
        }
        
        resp = session.post(create_url, json=new_user, headers=headers)
        if resp.status_code in [200, 201]:
            print("User Created Successfully!")
        else:
            print(f"User Creation Failed: {resp.status_code} - {resp.text}")
            # Continue to try delete in case it already existed
            
        # 3. List Users (Verify Creation)
        print("\nListing Users...")
        resp = session.get(create_url, headers=headers) # GET on same endpoint usually lists
        if resp.status_code == 200:
            users = resp.json().get("users", [])
            found = any(u['username'] == 'test_live_user' for u in users)
            print(f"Test User Found in List: {found}")
            
            if found:
                # 4. Delete User
                print(f"\nDeleting Test User...")
                delete_url = f"{BASE_URL}/api/users/test_live_user"
                resp = session.delete(delete_url, headers=headers)
                if resp.status_code == 200:
                    print("User Deleted Successfully!")
                else:
                    print(f"User Deletion Failed: {resp.status_code} - {resp.text}")
            else:
                print("Could not find test user for deletion.")
        else:
            print(f"List Users Failed: {resp.status_code} - {resp.text}")

    except Exception as e:
        print(f"Test Error: {e}")

if __name__ == "__main__":
    test_config()
    test_auth_flow()
