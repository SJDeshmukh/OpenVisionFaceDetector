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

TOKEN=$(echo $LOGIN_RESPONSE | grep -o '"token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
  echo "Login failed. Check superadmin credentials."
  exit 1
fi
echo "Token obtained."

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
    \"end_date\": \"2024-12-31\",
    \"cost\": 1000,
    \"max_users\": 50
  }")

echo "Response: $RESPONSE"

# 3. Verify in Database
echo "Verifying in Database..."
sqlite3 "$DB_PATH" "SELECT username, password, role FROM system_users WHERE username='$ADMIN_USER';"

SAVED_PASS=$(sqlite3 "$DB_PATH" "SELECT password FROM system_users WHERE username='$ADMIN_USER';")

if [ "$SAVED_PASS" == "$ADMIN_PASS" ]; then
  echo "SUCCESS: Admin password saved correctly."
else
  echo "FAILURE: Admin password mismatch. Expected '$ADMIN_PASS', got '$SAVED_PASS'."
fi

SAVED_USER_PASS=$(sqlite3 "$DB_PATH" "SELECT password FROM system_users WHERE username='$USER_USER';")

if [ "$SAVED_USER_PASS" == "$USER_PASS" ]; then
  echo "SUCCESS: User password saved correctly."
else
  echo "FAILURE: User password mismatch. Expected '$USER_PASS', got '$SAVED_USER_PASS'."
fi
