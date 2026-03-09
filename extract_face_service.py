import ast
import os
import re

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

# We also need to get the globals they depend on, or just import them in face_service.py.
# Things like vendor_embeddings_cache, vendor_threads, get_db_connection, cache_get, cache_set
# But wait, vendor_embeddings_cache is defined in app.py. If we move this to face_service.py, 
# we should move the cache definitions there too!

# Let's just output the service outline first.

service_template = """import numpy as np
import cv2
import base64
import time
from threading import Lock

# Local imports to avoid circular dependencies where needed
# In a real refactor, these caches should probably live here.

vendor_embeddings_cache = {}
vendor_threads = {}
cache_lock = Lock()

def get_realtime_engine():
    from app import get_realtime_engine as _get
    return _get()

"""

with open("backend/services/face_service.py", "w", encoding="utf-8") as f:
    f.write(service_template)
    f.write("\n\n".join(extracted))

# Don't delete from app.py just yet until we verify what globals we need to move.
print(f"Extracted {len(extracted)} face functions to services/face_service.py")
