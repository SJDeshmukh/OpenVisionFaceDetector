import ast
import os
import re

app_path = os.path.join("backend", "app.py")
with open(app_path, "r", encoding="utf-8") as f:
    source = f.read()

funcs_to_extract = {
    "calculate_daily_hours",
    "calculate_arrival_status",
    "calculate_expected_hours"
}

tree = ast.parse(source)
lines = source.split("\n")

extracted = []
to_remove = set()

for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in funcs_to_extract:
        start = node.lineno - 1
        end = node.end_lineno
        for i in range(start, end):
            to_remove.add(i)
        
        func_lines = lines[start:end]
        extracted.append("\n".join(func_lines))

service_template = """import json
from datetime import datetime, date, timedelta

"""

with open("backend/services/attendance_service.py", "w", encoding="utf-8") as f:
    f.write(service_template)
    f.write("\n\n".join(extracted))

new_lines = []
for i, line in enumerate(lines):
    if i not in to_remove:
        new_lines.append(line)

import_stmt = "\nfrom services.attendance_service import calculate_daily_hours, calculate_arrival_status, calculate_expected_hours\n"

for i, line in enumerate(new_lines):
    if line.startswith("import") or line.startswith("from"):
        pass
    else:
        new_lines.insert(i, import_stmt)
        break

with open(app_path, "w", encoding="utf-8") as f:
    f.write("\n".join(new_lines))

print(f"Extracted {len(extracted)} attendance functions to services/attendance_service.py")
