import ast
import os

app_path = os.path.join("backend", "app.py")
with open(app_path, "r", encoding="utf-8") as f:
    source = f.read()

funcs_to_extract = {
    "_detect_faces_from_bytes",
    "_ensure_vendor_emb_cache",
    "_suggest_from_cache",
    "_extract_structural_vector",
    "_decode_data_uri_to_rgb",
    "_normalize_vec"
}

tree = ast.parse(source)
lines = source.split("\n")

to_remove = set()
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in funcs_to_extract:
        start = node.lineno - 1
        end = node.end_lineno
        for i in range(start, end):
            to_remove.add(i)

new_lines = []
for i, line in enumerate(lines):
    if i not in to_remove:
        new_lines.append(line)

# Add import at the top after standard imports
import_stmt = "\nfrom services.face_service import _detect_faces_from_bytes, _ensure_vendor_emb_cache, _suggest_from_cache, _extract_structural_vector, _decode_data_uri_to_rgb, _normalize_vec\n"

for i, line in enumerate(new_lines):
    if line.startswith("import") or line.startswith("from"):
        # find the end of the initial import block
        pass
    else:
        new_lines.insert(i, import_stmt)
        break

with open(app_path, "w", encoding="utf-8") as f:
    f.write("\n".join(new_lines))

print(f"Replaced {len(funcs_to_extract)} functions with imports in app.py")
