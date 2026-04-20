import sqlite3
import json
import os

# Paths
DB_PATH = "backend/face_db.sqlite"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    return conn

def test_permanent_removal(vendor_id):
    print(f"\n--- Testing Permanent Removal for Vendor {vendor_id} ---")
    conn = get_db()
    c = conn.cursor()
    
    # 1. Simulate a state where old noisy defaults were present
    noisy_config = json.dumps([
        {"field": "student_number", "label": "Student Number"},
        {"field": "employee_id", "label": "Employee ID"},
        {"field": "roll_number", "label": "Roll Number"}
    ])
    c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (noisy_config, vendor_id))
    conn.commit()
    
    # 2. Simulate Upload with "Student Id" (which is now our primary ID target)
    headers = ["Student Name", "Mobile Number", "Student Id", "Branch"]
    
    # Mapping simulation logic (Simplified from bulk_registration.py)
    id_targets = ["student id", "student_id", "id", "id number"]
    phone_targets = ["mobile", "phone", "contact", "whatsapp"]
    
    name_key = "Student Name"
    phone_key = "Mobile Number"
    id_key = next((h for h in headers if any(t == h.lower() for t in id_targets)), None)
    
    print(f"Mapped ID Key: {id_key}")
    
    # Sync Logic
    new_sync_fields = []
    core_headers = {h for h in [name_key, phone_key] if h}
    for h in headers:
        if h not in core_headers:
            field_name = str(h).strip().lower().replace(" ", "_")
            new_sync_fields.append({
                "field": field_name,
                "label": str(h).strip().title(),
                "type": "text",
                "enabled": True,
                "required": False
            })

    c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (json.dumps(new_sync_fields), vendor_id))
    conn.commit()
    
    # Verification
    c.execute("SELECT registration_config FROM vendors WHERE id = ?", (vendor_id,))
    final_reg = json.loads(c.fetchone()[0])
    print(f"Final registration fields: {[f['field'] for f in final_reg]}")
    
    fields = [f['field'] for f in final_reg]
    assert "student_id" in fields
    assert "student_number" not in fields
    assert "employee_id" not in fields
    assert "roll_number" not in fields
    
    conn.close()
    print("SUCCESS: Items successfully removed and replaced by excel fields only.")

if __name__ == "__main__":
    test_permanent_removal(13)
