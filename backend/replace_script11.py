import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Update import in app.py to import check_vendor_status from services.auth_service
content = re.sub(r'from services.auth_service import authenticate_vendor_access', 'from services.auth_service import authenticate_vendor_access, check_vendor_status', content)

with open(app_path, 'w') as f:
    f.write(content)
