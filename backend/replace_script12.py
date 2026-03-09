import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Make check_vendor_status available in app.py
match = re.search(r'def check_vendor_status\(vendor_id\):.*?return True, "OK"', content, flags=re.DOTALL)
if match:
    func_code = match.group(0)
    
    auth_service_path = os.path.join(os.path.dirname(__file__), 'services/auth_service.py')
    imports = "\nimport sqlite3\nfrom datetime import datetime\n\n"
    with open(auth_service_path, 'a') as f_auth:
        f_auth.write(f"{imports}{func_code}\n")
    
    content = content.replace(func_code, '# check_vendor_status moved to services/auth_service.py')
    with open(app_path, 'w') as f:
        f.write(content)
