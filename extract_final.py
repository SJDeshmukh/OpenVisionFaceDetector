import os
import re
import subprocess

app_path = os.path.join("backend", "app.py")
result = subprocess.run(["git", "show", "HEAD:backend/app.py"], capture_output=True, text=True)
original_app = result.stdout
original_lines = original_app.split('\n')

with open(app_path, "r", encoding="utf-8") as f:
    current_app_content = f.read()

def get_bp_and_type_final(path):
    if path.startswith("/stream"): return "@streaming_bp", "streaming"
    if path == "/attendance" or path == "/person-event": return "@attendance_bp", "attendance"
    if path == "/class-threshold": return "@vendor_bp", "vendor"
    return None, None

func_decorators = {}
func_bodies = {}
func_types = {}

current_decs = []
in_target = False
target_type = ""
target_bp = ""

i = 0
while i < len(original_lines):
    line = original_lines[i]
    stripped = line.strip()
    
    if stripped.startswith("@greeting_bp.route("):
        match = re.search(r'@greeting_bp\.route\("([^"]+)"', stripped)
        if match:
            path = match.group(1)
            bp, tType = get_bp_and_type_final(path)
            if bp:
                in_target = True
                target_type = tType
                target_bp = bp
                current_decs.append(line)
            else:
                in_target = False
                current_decs = []
        else:
            in_target = False
            current_decs = []
    elif in_target and stripped.startswith("@"):
        current_decs.append(line)
    elif in_target and line.startswith("def "):
        match = re.search(r'^def ([a-zA-Z0-9_]+)\(', line)
        if match:
            func_name = match.group(1)
            decs = "\n".join(current_decs).replace("@greeting_bp", target_bp)
            
            body_lines = [line]
            j = i + 1
            while j < len(original_lines):
                b_line = original_lines[j]
                if b_line.strip() != "" and not b_line.startswith(" ") and not b_line.startswith("\t") and not b_line.startswith("#"):
                    break
                body_lines.append(b_line)
                j += 1
            
            body = "\n".join(body_lines)
            body = re.sub(r'(def .*?\(.*?\):)', r'\1\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES\n    from app import latest_frames, client_counts, device_status\n    from services.auth_service import extract_token, verify_token', body, count=1)
            
            func_decorators[func_name] = decs
            func_bodies[func_name] = body
            func_types[func_name] = target_type
            
        current_decs = []
        in_target = False
    elif in_target and stripped != "" and not stripped.startswith("#"):
        current_decs = []
        in_target = False
    i += 1

def append_to_file(bp_filename):
    bp_funcs = [fn for fn, typ in func_types.items() if typ == bp_filename.split(".")[0]]
    if not bp_funcs: return
    out_path = os.path.join("backend", "routes", bp_filename)
    # create if streaming.py
    if bp_filename == "streaming.py":
        template = """from flask import Blueprint, request, jsonify, send_file
import sqlite3
import base64
from datetime import datetime
import time

# Mock auth decorators for streaming
def vendor_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        from services.auth_service import authenticate_vendor_access
        vendor_id, err = authenticate_vendor_access()
        if err: return err
        request.vendor_id = vendor_id
        return f(*args, **kwargs)
    return decorated

def track_metrics(endpoint_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator

streaming_bp = Blueprint('streaming_bp', __name__)
"""
        with open(out_path, "w") as f:
            f.write(template + "\n")
            for fname in bp_funcs:
                f.write(func_decorators[fname] + "\n" + func_bodies[fname] + "\n\n")
    else:
        with open(out_path, "a") as f:
            for fname in bp_funcs:
                f.write("\n" + func_decorators[fname] + "\n" + func_bodies[fname] + "\n\n")

append_to_file("streaming.py")
append_to_file("attendance.py")
append_to_file("vendor.py")

content = current_app_content
for fname in func_bodies:
    pattern = re.compile(r'(@greeting_bp\.route\("[^"]+"\)[^{]+?def ' + fname + r'\(.*?\):.*?)(?=\n@|\ndef |\Z)', re.MULTILINE | re.DOTALL)
    content = pattern.sub('', content)

cleaned_lines = []
lines = content.split("\n")
k = 0
while k < len(lines):
    line = lines[k]
    if line.startswith("@greeting_bp.route("):
        match = re.search(r'@greeting_bp\.route\("([^"]+)"', line)
        if match:
            bp, tType = get_bp_and_type_final(match.group(1))
            if bp is not None:
                while k < len(lines) and (lines[k].startswith("@") or lines[k].strip() == ""):
                    k += 1
                continue
    cleaned_lines.append(line)
    k += 1

with open(app_path, "w") as f:
    f.write("\n".join(cleaned_lines))

# Register streaming_bp
with open(app_path, "r") as f:
    app_text = f.read()
if "from routes.streaming import streaming_bp" not in app_text:
    import re
    app_text = re.sub(r'from routes\.attendance import attendance_bp\napp\.register_blueprint\(attendance_bp\)', r'from routes.attendance import attendance_bp\napp.register_blueprint(attendance_bp)\n\nfrom routes.streaming import streaming_bp\napp.register_blueprint(streaming_bp)', app_text)
    with open(app_path, "w") as f:
        f.write(app_text)

print(f"Extracted {len(func_bodies)} remaining routes")
