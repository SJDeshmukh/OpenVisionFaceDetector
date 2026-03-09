import os
import re

app_path = os.path.join("backend", "app.py")
with open(app_path, "r") as f:
    content = f.read()

replacement = r'''from routes.faces import faces_bp
app.register_blueprint(faces_bp)

from routes.vendor import vendor_bp
app.register_blueprint(vendor_bp)

from routes.attendance import attendance_bp
app.register_blueprint(attendance_bp)

# --- Serve Frontend (SPA) ---'''

content = re.sub(r'from routes\.faces import faces_bp\napp\.register_blueprint\(faces_bp\)\n\n# --- Serve Frontend \(SPA\) ---', replacement, content, flags=re.DOTALL)

with open(app_path, "w") as f:
    f.write(content)

print("Registered vendor_bp and attendance_bp")
