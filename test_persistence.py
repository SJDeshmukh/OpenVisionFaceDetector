
import requests
import json

BASE_URL = "http://localhost:5001/api"

def test_shift_persistence():
    print("Testing Shift Persistence...")
    
    # 1. Get Company ID (assuming ID 1 exists)
    company_id = 1
    
    # 2. Create some shifts
    shifts = [
        {"id": 101, "name": "Morning Test", "start_time": "09:00", "end_time": "17:00", "active": True},
        {"id": 102, "name": "Evening Test", "start_time": "17:00", "end_time": "01:00", "active": True}
    ]
    
    # 3. Save Shifts
    print(f"Saving shifts to /companies/{company_id}/shifts...")
    res = requests.put(f"{BASE_URL}/companies/{company_id}/shifts", json={"shifts": shifts})
    if res.status_code != 200:
        print(f"Failed to save shifts: {res.text}")
        return
    print("Shifts saved.")
    
    # 4. Fetch Company Details to verify
    print(f"Fetching company details...")
    res = requests.get(f"{BASE_URL}/companies/{company_id}")
    data = res.json()
    
    fetched_shifts = data.get("shifts")
    print(f"Fetched Shifts Type: {type(fetched_shifts)}")
    print(f"Fetched Shifts Content: {fetched_shifts}")
    
    if isinstance(fetched_shifts, list) and len(fetched_shifts) == 2:
        print("✅ Shift Persistence Verified: Retrieved as List")
    elif isinstance(fetched_shifts, str):
        print("⚠️ Shift Persistence Verified: Retrieved as String (Frontend needs to parse)")
        try:
            parsed = json.loads(fetched_shifts)
            print(f"Parsed Content: {parsed}")
        except:
            print("❌ Failed to parse string shifts")
    else:
        print("❌ Shift Persistence Failed")

def test_draft_persistence():
    print("\nTesting Draft Activity Persistence...")
    company_id = 1
    
    activities = [
        {"id": 201, "name": "Lunch Test", "type": "Meal", "start_time": "12:00", "end_time": "13:00", "days": ["Mon", "Tue"]}
    ]
    
    print(f"Saving draft to /companies/{company_id}/draft...")
    res = requests.put(f"{BASE_URL}/companies/{company_id}/draft", json={"draft_timetable": activities, "modified_by": "test_script"})
    if res.status_code != 200:
        print(f"Failed to save draft: {res.text}")
        return
    print("Draft saved.")
    
    print(f"Fetching company details...")
    res = requests.get(f"{BASE_URL}/companies/{company_id}")
    data = res.json()
    
    fetched_draft = data.get("draft_timetable")
    print(f"Fetched Draft Type: {type(fetched_draft)}")
    print(f"Fetched Draft Content: {fetched_draft}")
    
    if isinstance(fetched_draft, list) and len(fetched_draft) == 1:
        print("✅ Draft Persistence Verified: Retrieved as List")
    else:
        print("❌ Draft Persistence Failed")

if __name__ == "__main__":
    try:
        test_shift_persistence()
        test_draft_persistence()
    except Exception as e:
        print(f"Test Error: {e}")
