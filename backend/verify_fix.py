import os
import sqlite3
import json

TEST_DB = 'test_faces_fix.db'
os.environ['DB_PATH'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), TEST_DB)

from app import app, init_db, migrate_faces_pk, generate_token

def setup_module():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    init_db()
    migrate_faces_pk()
    conn = sqlite3.connect(TEST_DB)
    c = conn.cursor()
    c.execute("INSERT INTO vendors (company_name, contact_person, phone, email, status) VALUES (?, ?, ?, ?, ?)",
              ('Test Co', 'Owner', '9999999999', 'owner@testco.com', 'active'))
    vendor_id = c.lastrowid
    c.execute("INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, grace_period_days, max_users) VALUES (?, ?, ?, ?, ?, ?)",
              (vendor_id, 'basic', '2025-01-01', '2099-12-31', 30, 100))
    c.execute("UPDATE system_users SET vendor_id = ? WHERE username = 'superadmin'", (vendor_id,))
    conn.commit()
    conn.close()

def teardown_module():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

def auth_headers():
    token = generate_token('superadmin', 'super_admin')
    return {'Authorization': f'Bearer {token}'}

def test_update_employee():
    client = app.test_client()
    
    payload = {
        "name": "John Doe",
        "face_image": "base64_fake_image",
        "phone": "1234567890"
    }
    resp = client.post("/api/sync/upload", json=payload, headers=auth_headers())
    assert resp.status_code == 200, f"Create status {resp.status_code}, body: {resp.data}"
    data = resp.json
    assert data['status'] == 'success'
    user_id = data.get('person_id')
    assert user_id is not None
    print(f"Created user ID: {user_id}")

    payload_update = {
        "person_id": user_id,
        "name": "John Doe",
        "face_image": "base64_fake_image",
        "phone": "0987654321"
    }
    resp = client.post("/api/sync/upload", json=payload_update, headers=auth_headers())
    assert resp.status_code == 200, f"Update status {resp.status_code}, body: {resp.data}"
    assert resp.json['status'] == 'success'
    assert resp.json.get('person_id') == user_id

    conn = sqlite3.connect(TEST_DB)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM faces")
    count = c.fetchone()[0]
    assert count == 1, f"Expected 1 user, found {count}"
    
    c.execute("SELECT phone FROM faces WHERE id=?", (user_id,))
    phone = c.fetchone()[0]
    assert phone == "0987654321", f"Expected phone '0987654321', got '{phone}'"
    conn.close()

    print("Test passed: User updated successfully without duplicates.")

if __name__ == "__main__":
    setup_module()
    try:
        test_update_employee()
    finally:
        teardown_module()
