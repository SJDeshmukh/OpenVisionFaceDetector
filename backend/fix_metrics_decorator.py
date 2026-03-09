import re
import os

admin_path = os.path.join("backend", "routes", "admin.py")
with open(admin_path, "r") as f:
    content = f.read()

mock_decorator = """
def track_metrics(endpoint_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated
    return decorator

admin_bp = Blueprint('admin_bp', __name__)
"""

content = content.replace("admin_bp = Blueprint('admin_bp', __name__)", mock_decorator)

with open(admin_path, "w") as f:
    f.write(content)

print("Added track_metrics")
