import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Register auth_bp
replacement = r'''# Bootstrap DB in WSGI environments (Render/Gunicorn) to ensure base tables exist
try:
    bootstrap_db()
except Exception as _e:
    try:
        pass # print(f"Bootstrap Error: {_e}")
    except Exception:
        pass

app.register_blueprint(greeting_bp)

from routes.auth import auth_bp
app.register_blueprint(auth_bp, url_prefix='/api/auth')

# --- Serve Frontend (SPA) ---'''

content = re.sub(r'# Bootstrap DB in WSGI environments \(Render/Gunicorn\) to ensure base tables exist.*?# --- Serve Frontend \(SPA\) ---', replacement, content, flags=re.DOTALL)

with open(app_path, 'w') as f:
    f.write(content)
