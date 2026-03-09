import os
import re
import subprocess

app_path = os.path.join("backend", "app.py")

# Get original app.py to preserve decorators
result = subprocess.run(["git", "show", "HEAD:backend/app.py"], capture_output=True, text=True)
original_app = result.stdout
original_lines = original_app.split('\n')

with open(app_path, "r", encoding="utf-8") as f:
    current_app_content = f.read()

# Face routes prefixes
target_prefixes = ["/sync", "/persons", "/utils/detect-faces", "/utils/search-embedding"]

def should_extract(route_path):
    for p in target_prefixes:
        if route_path.startswith(p):
            return True
    return False

# 1. Parse original app.py to get the full functions + decorators
func_decorators = {}
func_bodies = {}

current_decs = []
in_target = False
target_path = ""

i = 0
while i < len(original_lines):
    line = original_lines[i]
    stripped = line.strip()
    
    if stripped.startswith("@greeting_bp.route("):
        # check path
        match = re.search(r'@greeting_bp\.route\("([^"]+)"', stripped)
        if match:
            path = match.group(1)
            if should_extract(path):
                in_target = True
                target_path = path
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
            decs = "\n".join(current_decs).replace("@greeting_bp", "@faces_bp")
            
            # Now gather body
            body_lines = [line]
            j = i + 1
            while j < len(original_lines):
                b_line = original_lines[j]
                # End of function if not indented, not empty, not comment
                if b_line.strip() != "" and not b_line.startswith(" ") and not b_line.startswith("\t") and not b_line.startswith("#"):
                    break
                body_lines.append(b_line)
                j += 1
            
            # Inject local imports
            body = "\n".join(body_lines)
            body = re.sub(r'(def .*?\(.*?\):)', r'\1\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES\n    from services.auth_service import extract_token, verify_token', body, count=1)
            
            func_decorators[func_name] = decs
            func_bodies[func_name] = body
            
        current_decs = []
        in_target = False
    elif in_target and stripped != "" and not stripped.startswith("#"):
        current_decs = []
        in_target = False
    i += 1

# 2. Write routes/faces.py
faces_path = os.path.join("backend", "routes", "faces.py")
faces_template = """from flask import Blueprint, request, jsonify, send_file
import sqlite3
import json
import base64
import os
import io
import time
from datetime import datetime
import numpy as np
import cv2

faces_bp = Blueprint('faces_bp', __name__)

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

# Mock track_metrics
def track_metrics(endpoint_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator

"""

with open(faces_path, "w") as f:
    f.write(faces_template + "\n")
    for fname in func_decorators:
        f.write(func_decorators[fname] + "\n" + func_bodies[fname] + "\n\n")

# 3. Remove routes from app.py
lines_app = current_app_content.split('\n')
new_lines_app = []
skip = False

print(f"To remove: {list(func_bodies.keys())}")

for line in lines_app:
    if line.startswith("@greeting_bp.route("):
        match = re.search(r'@greeting_bp\.route\("([^"]+)"', line)
        if match and should_extract(match.group(1)):
            skip = True
        else:
            skip = False
    
    if skip and line.startswith("def "):
        # Check if it's one of ours just in case
        match = re.search(r'^def ([a-zA-Z0-9_]+)\(', line)
        if match and match.group(1) in func_bodies:
            pass # Keep skipping
        else:
            skip = False # Stop skipping, it's a false positive or another route
            
    if not skip:
        # Check if line is a leftover decorator
        # We know log_audit etc.
        # It's safer to just skip decorators if we are in a skip block.
        pass
        
    # Python functions end on dedent. But since app.py decorators might be orphaned...
    # Let's use a simpler replacement: Just search and replace the whole block we extracted.
    
# Actually, replacing by string matching the extracted bodies from original_app inside current app.py
import sys
content = current_app_content
for fname in func_bodies:
    # Build regex to match the route and the definition
    # Because app.py might have modified body, we search for the def and remove until next def or @
    pattern = re.compile(r'(@greeting_bp\.route\("[^"]+"\)[^{]+?def ' + fname + r'\(.*?\):.*?)(?=\n@|\ndef |\Z)', re.MULTILINE | re.DOTALL)
    content = pattern.sub('', content)

# Remove orphaned decorators in app.py one more time
cleaned_lines = []
lines = content.split("\n")
i = 0
while i < len(lines):
    line = lines[i]
    if line.startswith("@greeting_bp.route(") and should_extract(re.search(r'@greeting_bp\.route\("([^"]+)"', line).group(1) if re.search(r'@greeting_bp\.route\("([^"]+)"', line) else ""):
        # skip decorators
        while i < len(lines) and (lines[i].startswith("@") or lines[i].strip() == ""):
            i += 1
        continue
    cleaned_lines.append(line)
    i += 1

with open(app_path, "w") as f:
    f.write("\n".join(cleaned_lines))

print(f"Extracted {len(func_bodies)} face routes")
