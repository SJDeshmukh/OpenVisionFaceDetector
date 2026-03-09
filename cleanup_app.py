import ast
import os
import glob

# 1. Collect all function names from routes/*.py
extracted_funcs = set()
for route_file in glob.glob("backend/routes/*.py"):
    with open(route_file, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                extracted_funcs.add(node.name)

# Exclude some common decorators or functions that might legitimately exist in both
# e.g. track_metrics, rate_limit, admin_required which we mocked in the route files
extracted_funcs -= {"track_metrics", "rate_limit", "admin_required", "vendor_required", "super_admin_required", "require_feature", "log_audit"}

print(f"Functions to remove from app.py: {len(extracted_funcs)}")
# 2. Parse app.py and remove them
app_path = "backend/app.py"
with open(app_path, "r", encoding="utf-8") as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split("\n")

to_remove = set()
removed_names = []

for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in extracted_funcs:
        start = node.lineno - 1
        end = node.end_lineno
        for i in range(start, end):
            to_remove.add(i)
        removed_names.append(node.name)

new_lines = [line for i, line in enumerate(lines) if i not in to_remove]

with open(app_path, "w", encoding="utf-8") as f:
    f.write("\n".join(new_lines))

print(f"Removed {len(removed_names)} functions: {removed_names}")
