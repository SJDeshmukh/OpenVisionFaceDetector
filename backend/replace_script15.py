import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Register admin_bp
replacement = r'''app.register_blueprint(greeting_bp)

from routes.auth import auth_bp
app.register_blueprint(auth_bp, url_prefix='/api/auth')

from routes.admin import admin_bp
app.register_blueprint(admin_bp, url_prefix='/api')

# --- Serve Frontend (SPA) ---'''

content = re.sub(r'app\.register_blueprint\(greeting_bp\).*?# --- Serve Frontend \(SPA\) ---', replacement, content, flags=re.DOTALL)

with open(app_path, 'w') as f:
    f.write(content)
