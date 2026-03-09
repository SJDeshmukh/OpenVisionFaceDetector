import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Fix Blueprint registration
replacement = r'''app.register_blueprint(greeting_bp)

from routes.auth import auth_bp
app.register_blueprint(auth_bp)

from routes.admin import admin_bp
app.register_blueprint(admin_bp)

# --- Serve Frontend (SPA) ---'''

content = re.sub(r'app\.register_blueprint\(greeting_bp\).*?# --- Serve Frontend \(SPA\) ---', replacement, content, flags=re.DOTALL)

with open(app_path, 'w') as f:
    f.write(content)

# Fix paths in auth.py
auth_path = os.path.join(os.path.dirname(__file__), 'routes/auth.py')
with open(auth_path, 'r') as f:
    auth_content = f.read()

auth_content = auth_content.replace('@auth_bp.route("/login"', '@auth_bp.route("/auth/login"')
auth_content = auth_content.replace('@auth_bp.route("/register"', '@auth_bp.route("/auth/register"')
auth_content = auth_content.replace('@auth_bp.route("/logout"', '@auth_bp.route("/auth/logout"')

with open(auth_path, 'w') as f:
    f.write(auth_content)

