#!/bin/bash

# Configuration
API_URL="http://127.0.0.1:5001/api"
DB_PATH="backend/faces.db"

# 1. Login as Super Admin to get token
echo "Logging in as Super Admin..."
LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "superadmin", "password": "super123"}')

echo "Login Response: $LOGIN_RESPONSE"

TOKEN=$(echo $LOGIN_RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin).get('token', ''))")

if [ -z "$TOKEN" ]; then
  echo "Login failed. Check superadmin credentials."
  exit 1
fi
echo "SuperAdmin Token obtained."

# 2. Create Vendor with Custom Credentials
TIMESTAMP=$(date +%s)
COMPANY="TestComp_$TIMESTAMP"
ADMIN_USER="admin_$TIMESTAMP"
ADMIN_PASS="pass_$TIMESTAMP"
USER_USER="user_$TIMESTAMP"
USER_PASS="userpass_$TIMESTAMP"

echo "Creating Vendor with:"
echo "  Company: $COMPANY"
echo "  Admin: $ADMIN_USER / $ADMIN_PASS"
echo "  User: $USER_USER / $USER_PASS"

RESPONSE=$(curl -s -X POST "$API_URL/admin/vendors" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"company_name\": \"$COMPANY\",
    \"contact_person\": \"Test Person\",
    \"phone\": \"1234567890\",
    \"email\": \"test@example.com\",
    \"admin_username\": \"$ADMIN_USER\",
    \"admin_password\": \"$ADMIN_PASS\",
    \"user_username\": \"$USER_USER\",
    \"user_password\": \"$USER_PASS\",
    \"start_date\": \"2024-01-01\",
    \"end_date\": \"2027-12-31\",
    \"cost\": 1000,
    \"max_users\": 50
  }")

echo "Create Response: $RESPONSE"

# 3. Verify in Database (Direct SQL Check)
echo "Verifying in Database..."
sqlite3 "$DB_PATH" "SELECT username, role, vendor_id FROM system_users WHERE username='$ADMIN_USER';"

ADMIN_ROLE=$(sqlite3 "$DB_PATH" "SELECT role FROM system_users WHERE username='$ADMIN_USER';")
USER_ROLE=$(sqlite3 "$DB_PATH" "SELECT role FROM system_users WHERE username='$USER_USER';")

if [ "$ADMIN_ROLE" == "vendor_admin" ]; then
  echo "SUCCESS: Admin created with correct role 'vendor_admin'."
else
  echo "FAILURE: Admin role mismatch. Expected 'vendor_admin', got '$ADMIN_ROLE'."
fi

if [ "$USER_ROLE" == "user" ]; then
  echo "SUCCESS: User created with correct role 'user'."
else
  echo "FAILURE: User role mismatch. Expected 'user', got '$USER_ROLE'."
fi

# 4. Try Login as Vendor Admin
echo "Attempting Login as Vendor Admin..."
VENDOR_LOGIN=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$ADMIN_USER\", \"password\": \"$ADMIN_PASS\"}")

echo "Vendor Login Response: $VENDOR_LOGIN"
VENDOR_ROLE=$(echo $VENDOR_LOGIN | python3 -c "import sys, json; print(json.load(sys.stdin).get('role', ''))")

if [ "$VENDOR_ROLE" == "vendor_admin" ]; then
  echo "SUCCESS: Vendor Admin login returned role 'vendor_admin'."
else
  echo "FAILURE: Vendor Admin login returned role '$VENDOR_ROLE'."
fi
