
import requests
import json

BASE_URL = "http://localhost:5001/api"

def test_payroll_response_structure():
    # 1. Login to get token
    login_payload = {
        "username": "admin",
        "password": "admin1234"
    }
    
    try:
        res = requests.post(f"{BASE_URL}/auth/login", json=login_payload)
        if res.status_code != 200:
            print(f"Login Failed: {res.text}")
            return
            
        data = res.json()
        token = data['token']
        print("Login Successful")
        
        # 2. Call Payroll Endpoint
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31"
        }
        
        res = requests.get(f"{BASE_URL}/reports/payroll", headers=headers, params=params)
        
        if res.status_code == 200:
            data = res.json()
            print("Payroll Response Keys:", data.keys())
            
            if 'global_settings' in data:
                print("Global Settings Found:", data['global_settings'])
            else:
                print("ERROR: global_settings missing from response")
                
            if 'payroll' in data:
                print(f"Payroll Records: {len(data['payroll'])}")
                if len(data['payroll']) > 0:
                    sample = data['payroll'][0]
                    print("Sample Record Keys:", sample.keys())
                    required_keys = ['late_marks_count', 'late_deduction', 'final_payout']
                    missing = [k for k in required_keys if k not in sample]
                    if missing:
                        print(f"ERROR: Missing keys in payroll record: {missing}")
                    else:
                        print("Payroll record structure looks correct.")
        else:
            print(f"Payroll Request Failed: {res.status_code} {res.text}")
            
    except Exception as e:
        print(f"Test Error: {e}")

if __name__ == "__main__":
    test_payroll_response_structure()
