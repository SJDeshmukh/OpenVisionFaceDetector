import re
import os

app_path = os.path.join("backend", "app.py")
with open(app_path, "r") as f:
    lines = f.readlines()

# Clean up orphaned decorators in app.py
cleaned_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.startswith("@greeting_bp.route(\"/admin") or line.startswith("@greeting_bp.route(\"/superadmin") or line.startswith("@super_admin_required") or line.startswith("@admin_required"):
        # This is a decorator we left behind. We just skip it!
        pass
    else:
        cleaned_lines.append(line)
    i += 1

with open(app_path, "w") as f:
    f.writelines(cleaned_lines)
print("Cleaned app.py")
