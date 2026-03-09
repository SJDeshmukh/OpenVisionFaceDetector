import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Remove the rest of the leftover auth code (Web Session Limits and Record Session)
content = re.sub(r'# --- Auth Endpoints ---.*?return jsonify\(\{"error": "Invalid credentials"\}\), 401', '', content, flags=re.DOTALL)

with open(app_path, 'w') as f:
    f.write(content)
