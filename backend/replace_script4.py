import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Remove the leftover session limit checks from login endpoint
content = re.sub(r'# --- Session Limit Checks ---.*?if platform == \'web\':.*?(?=@greeting_bp|# ---)', '', content, flags=re.DOTALL)

with open(app_path, 'w') as f:
    f.write(content)
