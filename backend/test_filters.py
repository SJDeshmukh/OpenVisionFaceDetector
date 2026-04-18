import os
import json
import sqlite3
import psycopg2
from collections import defaultdict

conn = psycopg2.connect('postgresql://postgres:postgres@localhost:5432/face_db')
c = conn.cursor()
vendor_id = 1
c.execute("SELECT company_name, registration_config FROM vendors WHERE id = %s", (vendor_id,))
vendor_row = c.fetchone()
vendor_name = vendor_row[0] if vendor_row else ''
raw_reg = vendor_row[1] if vendor_row else None

c.execute("SELECT features FROM subscriptions WHERE vendor_id = %s", (vendor_id,))
sub_row = c.fetchone()
vendor_features = []
try:
    vendor_features = json.loads(sub_row[0] or '[]') if sub_row else []
except Exception:
    vendor_features = []

visible_standard_filters = {"department": False, "designation": False, "shift": False, "phone": False}
enabled_dynamic_fields = []
if raw_reg:
    config = json.loads(raw_reg) if isinstance(raw_reg, str) else raw_reg
    for f in config:
        field_key = f.get("field") or f.get("key")
        is_enabled = f.get("enabled", True) is not False
        if field_key in visible_standard_filters:
            visible_standard_filters[field_key] = is_enabled
        elif is_enabled:
            enabled_dynamic_fields.append({
                "key": str(field_key),
                "label": str(f.get("label") or field_key),
                "options": f.get("options")
            })

if 'bulk_image_attendance' in vendor_features:
    c.execute("SELECT fields FROM bulk_attendance_config WHERE vendor_id = %s", (vendor_id,))
    bulk_row = c.fetchone()
    if bulk_row:
        bulk_fields = json.loads(bulk_row[0] or '[]')
        existing_keys = {f['key'] for f in enabled_dynamic_fields}
        for bf in bulk_fields:
            bkey = str(bf.get('name', '')).strip()
            if not bkey or bkey in existing_keys:
                continue
            enabled_dynamic_fields.append({
                "key": bkey,
                "label": str(bf.get('label') or bkey),
                "options": bf.get('options') or []
            })
            existing_keys.add(bkey)

print("Enabled Dynamic Fields:", enabled_dynamic_fields)

c.execute(
    "SELECT department, designation, shift, phone, custom_data "
    "FROM faces WHERE vendor_id = %s",
    (vendor_id,)
)
faces = []
for r in c.fetchall():
    faces.append({'custom': json.loads(r[4] or "{}")})

dynamic_filters = {}
for field in enabled_dynamic_fields:
    fk, fl = field['key'], field['label']
    unique_values = set()
    for f in faces:
        val = f['custom'].get(fk)
        if val is not None and str(val).strip():
            unique_values.add(str(val).strip())
    options = sorted(list(unique_values))[:200]
    if field.get('options'):
        options = [str(x) for x in field['options']]
    dynamic_filters[fk] = {'label': fl, 'options': options}

print("Dynamic Filters:", json.dumps(dynamic_filters, indent=2))
