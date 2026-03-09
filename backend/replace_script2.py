import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Remove /auth/logout
content = re.sub(r'@greeting_bp\.route\("/auth/logout".*?def logout\(\):.*?(?=# Bootstrap DB|\Z)', '', content, flags=re.DOTALL)

with open(app_path, 'w') as f:
    f.write(content)
