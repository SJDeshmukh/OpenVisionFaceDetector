import os

faces_path = os.path.join("backend", "routes", "faces.py")
with open(faces_path, "r") as f:
    content = f.read()

mock = """
def rate_limit(*args, **kwargs):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator
"""

if "def rate_limit(" not in content:
    content = content.replace("faces_bp = Blueprint(", mock + "\nfaces_bp = Blueprint(")

with open(faces_path, "w") as f:
    f.write(content)

print("Add rate_limit mock")
