import ast

with open("backend/app.py", "r") as f:
    source = f.read()

tree = ast.parse(source)

funcs = []
for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        funcs.append({"name": node.name, "lines": node.end_lineno - node.lineno})
        
funcs.sort(key=lambda x: x["lines"], reverse=True)
for f in funcs:
    print(f"{f['name']}: {f['lines']} lines")

