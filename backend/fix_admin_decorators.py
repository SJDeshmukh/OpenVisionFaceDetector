import subprocess
import os
import re

# Get original app.py
result = subprocess.run(["git", "show", "HEAD:backend/app.py"], capture_output=True, text=True)
original_app = result.stdout

func_decorators = {}

lines = original_app.split('\n')
current_decs = []
in_target = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith("@greeting_bp.route(\"/admin") or stripped.startswith("@greeting_bp.route(\"/superadmin"):
        in_target = True
        current_decs.append(stripped)
    elif in_target and stripped.startswith("@"):
        current_decs.append(stripped)
    elif in_target and stripped.startswith("def "):
        # found the def
        match = re.search(r'def ([a-zA-Z0-9_]+)\(', stripped)
        if match:
            func_name = match.group(1)
            # rename greeting_bp to admin_bp
            decs = "\n".join(current_decs).replace("@greeting_bp.route", "@admin_bp.route")
            func_decorators[func_name] = decs
        current_decs = []
        in_target = False
    elif in_target and stripped != "" and not stripped.startswith("#"):
        # Not a decorator, not an empty line, not a def? Reset.
        current_decs = []
        in_target = False

admin_path = os.path.join("backend", "routes", "admin.py")
with open(admin_path, "r") as f:
    admin_content = f.read()

# Replace defs with decorators + defs
for func_name, decs in func_decorators.items():
    # Only replace if not already decorated
    if f"@admin_bp.route" not in admin_content.split(f"def {func_name}(")[0].split('\n')[-2:-1]:
        # we do a simple regex replacement
        admin_content = re.sub(r'^def ' + func_name + r'\(', decs + '\ndef ' + func_name + '(', admin_content, flags=re.MULTILINE)

with open(admin_path, "w") as f:
    f.write(admin_content)

print(f"Restored decorators for {len(func_decorators)} functions")
