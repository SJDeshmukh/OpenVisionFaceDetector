import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Register faces_bp
replacement = r'''from routes.admin import admin_bp
app.register_blueprint(admin_bp)

from routes.faces import faces_bp
app.register_blueprint(faces_bp)

# --- Serve Frontend (SPA) ---'''

content = re.sub(r'from routes\.admin import admin_bp\napp\.register_blueprint\(admin_bp\)\n\n# --- Serve Frontend \(SPA\) ---', replacement, content, flags=re.DOTALL)

with open(app_path, 'w') as f:
    f.write(content)

