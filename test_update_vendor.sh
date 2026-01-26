#!/bin/bash

BASE_URL="http://127.0.0.1:5001/api"
DB_PATH="backend/faces.db"

# 1. Create a dummy vendor to test with (assuming Create Vendor endpoint works or exists, 
#    but update needs an ID. I'll insert one manually into DB to be safe and independent of other endpoints).

# Create a temporary vendor in DB
echo "Creating test vendor in DB..."
sqlite3 $DB_PATH "INSERT OR IGNORE INTO vendors (company_name, contact_person, phone, email, status) VALUES ('TestVendor', 'Tester', '1234567890', 'test@test.com', 'active');"
VENDOR_ID=$(sqlite3 $DB_PATH "SELECT id FROM vendors WHERE company_name='TestVendor' LIMIT 1;")

echo "Test Vendor ID: $VENDOR_ID"

# 2. Login as SuperAdmin to get Token
echo "Logging in as SuperAdmin..."
LOGIN_RES=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "superadmin",
    "password": "super123"
  }')

echo "Login Response: $LOGIN_RES"

TOKEN=$(echo "$LOGIN_RES" | grep -o '"token": *"[^"]*' | cut -d'"' -f4)
echo "Token received: ${TOKEN:0:10}..."

# 3. Update Vendor Credentials
echo "Updating Vendor Credentials for ID: $VENDOR_ID..."
RESPONSE=$(curl -s -X PUT "$BASE_URL/admin/vendors/$VENDOR_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "TestVendorUpdated",
    "contact_person": "Tester Updated",
    "phone": "9876543210",
    "email": "updated@test.com",
    "admin_username": "admin_test_updated",
    "admin_password": "newpassword123",
    "user_username": "user_test_updated",
    "user_password": "newpassword123"
  }')

echo "Update Response: $RESPONSE"

echo ""

# 4. Verify in DB
echo "Verifying in DB for Vendor ID: $VENDOR_ID..."
echo "All System Users for this vendor:"
sqlite3 $DB_PATH "SELECT rowid, username, password, role FROM system_users WHERE vendor_id=$VENDOR_ID;"

# Cleanup
# sqlite3 $DB_PATH "DELETE FROM vendors WHERE id=$VENDOR_ID;"
# sqlite3 $DB_PATH "DELETE FROM system_users WHERE vendor_id=$VENDOR_ID;"
