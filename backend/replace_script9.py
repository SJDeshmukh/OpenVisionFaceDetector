import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'routes/auth.py')
with open(app_path, 'r') as f:
    content = f.read()

# Fix import back
content = content.replace(
    'from services.auth_service import authenticate_vendor_access, verify_password, generate_token, verify_token, hash_password, generate_token_with_claims, extract_token\nfrom app import check_vendor_status',
    'from services.auth_service import authenticate_vendor_access, verify_password, generate_token, check_vendor_status, verify_token, hash_password, generate_token_with_claims, extract_token'
)

with open(app_path, 'w') as f:
    f.write(content)
