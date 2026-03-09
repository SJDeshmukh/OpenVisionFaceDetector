import ast
import os

app_path = os.path.join("backend", "app.py")
output_path = os.path.join("backend", "routes", "admin.py")

with open(app_path, "r", encoding="utf-8") as f:
    source = f.read()

lines = source.split("\n")
tree = ast.parse(source)

to_remove = set()
admin_funcs_lines = []

for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        is_admin = False
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if getattr(decorator.func.value, "id", "") == "greeting_bp" and decorator.func.attr == "route":
                    if decorator.args and hasattr(decorator.args[0], "value"):
                        route_path = str(decorator.args[0].value)
                        if route_path.startswith("/admin") or route_path.startswith("/superadmin"):
                            is_admin = True
                            break
        if is_admin:
            # Note: ast lines are 1-indexed
            start = node.lineno - 1
            end = node.end_lineno
            for i in range(start, end):
                to_remove.add(i)
            # Gather lines for this function
            func_lines = lines[start:end]
            # Replace greeting_bp with admin_bp
            func_lines[0] = func_lines[0].replace("@greeting_bp", "@admin_bp")
            
            # Prepend local import
            # Local import is safe inside the function definition body.
            func_code = "\n".join(func_lines)
            
            # We want to add the import statement right after `def ...():`
            # For simplicity, we just inject it into the first line of the body.
            # Easiest way is to find `def .*?:` and put it on next line with 4 spaces.
            import re
            func_code = re.sub(r'(def .*?\(.*?\):)', r'\1\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES', func_code, count=1)
            
            admin_funcs_lines.append(func_code)

print(f"Extracted {len(admin_funcs_lines)} admin functions")

new_app_lines = [line for i, line in enumerate(lines) if i not in to_remove]

with open(app_path, "w", encoding="utf-8") as f:
    f.write("\n".join(new_app_lines))

admin_bp_template = """from flask import Blueprint, request, jsonify, send_file
import sqlite3
from datetime import datetime, date, timedelta
import json
import base64
import re
import os
import secrets
import qrcode
from io import BytesIO

# Import from services
from services.auth_service import verify_token, extract_token, hash_password, verify_password

# Authentication decorators - these might be defined in app.py, so we will import them locally or they might need to be resolved.
def super_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Missing Authorization Header"}), 401
        token = extract_token(auth_header)
        data = verify_token(token)
        if not data or data.get('role') != 'super_admin':
            return jsonify({"error": "Super Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Missing Authorization Header"}), 401
        token = extract_token(auth_header)
        data = verify_token(token)
        if not data or data.get('role') not in ['super_admin', 'vendor_admin']:
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

admin_bp = Blueprint('admin_bp', __name__)

# --- Extracted Admin Routes ---
"""

with open(output_path, "w", encoding="utf-8") as f:
    f.write(admin_bp_template + "\n\n" + "\n\n".join(admin_funcs_lines))
    
