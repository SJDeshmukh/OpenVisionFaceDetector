import os
import re

faces_path = os.path.join("backend", "routes", "faces.py")
with open(faces_path, "r") as f:
    content = f.read()

mock = """
def require_feature(feature_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated
    return decorator
"""

if "def require_feature" not in content:
    content = content.replace("faces_bp = Blueprint(", mock + "\nfaces_bp = Blueprint(")

with open(faces_path, "w") as f:
    f.write(content)

print("Add require_feature mock")
