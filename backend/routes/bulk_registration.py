import json
import re
import uuid
import csv
import io
import pandas as pd
from flask import Blueprint, request, jsonify, g
from utils import get_db_connection, log_audit, vendor_has_feature
from services.auth_service import require_auth
from openpyxl import load_workbook

bulk_registration_bp = Blueprint('bulk_registration_bp', __name__)

def _fuzzy_match(header, targets):
    h = str(header).strip().lower()
    for t in targets:
        if t.lower() in h:
            return True
    return False

@bulk_registration_bp.route("/bulk-registration/upload", methods=["POST"])
@require_auth()
def bulk_registration_upload():
    vendor_id = g.vendor_id
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    filename = file.filename
    if not filename:
        return jsonify({"error": "No file selected"}), 400

    ext = filename.split('.')[-1].lower()
    
    try:
        data = []
        if ext == 'csv':
            content = file.read().decode('utf-8-sig') # handle BOM
            reader = csv.DictReader(io.StringIO(content))
            data = [row for row in reader]
        elif ext in ['xls', 'xlsx']:
            df = pd.read_excel(file)
            # Convert NaN to None for JSON compatibility
            df = df.where(pd.notnull(df), None)
            data = df.to_dict(orient='records')
        else:
            return jsonify({"error": f"Unsupported file extension: {ext}"}), 400

        if not data:
            return jsonify({"error": "File is empty"}), 400

        headers = list(data[0].keys())
        
        # Mapping Logic
        name_targets = ["name", "full name", "student name", "employee name", "person name"]
        id_targets = ["student id", "student_id", "id", "id number"]
        phone_targets = ["mobile", "phone", "contact", "whatsapp"]
        dept_targets = ["department", "dept", "branch", "class", "section"]
        desig_targets = ["designation", "role", "post"]
        shift_targets = ["shift", "timing"]

        name_key = next((h for h in headers if _fuzzy_match(h, name_targets)), None)
        phone_key = next((h for h in headers if _fuzzy_match(h, phone_targets)), None)
        
        # Identify ID column for Automated Login Creation logic
        id_key = next((h for h in headers if _fuzzy_match(h, id_targets)), None)
        if not id_key and data:
            first_row = data[0]
            for h in headers:
                val = str(first_row.get(h) or "").strip()
                # Pattern: Alphanumeric, 4-20 chars, must contain at least one digit
                if re.match(r'^(?=.*[0-9])[A-Za-z0-9\-_]{4,20}$', val):
                    id_key = h
                    break

        if not name_key:
            return jsonify({"error": "Could not identify 'Name' column. Please ensure one of the headers contains 'Name'."}), 400

        conn = get_db_connection()
        c = conn.cursor()

        # Get features for automated login creation ("Inking")
        c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        s_row = c.fetchone()
        features = json.loads(s_row[0] or '[]') if s_row else []
        inking_enabled = 'leave_management' in features or 'mobile_app' in features

        success_count = 0
        skipped_count = 0
        errors = []

        # Track existing dynamic fields for bulk_attendance_config
        c.execute("SELECT fields FROM bulk_attendance_config WHERE vendor_id = ?", (vendor_id,))
        bulk_row = c.fetchone()
        
        # Check if 0 users remain, then clear config to start fresh
        c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (vendor_id,))
        if c.fetchone()[0] == 0:
            existing_fields = []
        else:
            existing_fields = json.loads(bulk_row[0] or '[]') if bulk_row else []
        existing_keys = {f.get('name') for f in existing_fields}
        new_fields = list(existing_fields)

        for row_idx, row in enumerate(data):
            try:
                name = str(row.get(name_key) or "").strip()
                if not name:
                    skipped_count += 1
                    continue

                phone = str(row.get(phone_key) or "").strip()
                
                # Strictly collect custom data based on ACTUAL headers from the current row
                # (headers list was identified at the start of upload)
                custom_data_obj = {}
                core_headers = {h for h in [name_key, phone_key] if h}
                
                for h in headers:
                    if h in core_headers:
                        continue
                    val = row.get(h)
                    if val is not None:
                        custom_key = str(h).strip()
                        custom_data_obj[custom_key] = str(val).strip()

                custom_data_str = json.dumps(custom_data_obj)

                # Get next display_id
                c.execute("SELECT COALESCE(MAX(display_id), 0) + 1 FROM faces WHERE vendor_id = ?", (vendor_id,))
                next_display_id = c.fetchone()[0]

                # Insert into faces: 
                # Note: Dept, Desig, Shift are now handled via custom_data if present in Excel
                # We pass empty strings for them in the core table columns for now
                c.execute("""
                    INSERT INTO faces (name, phone, department, designation, shift, vendor_id, custom_data, display_id)
                    VALUES (?, ?, '', '', '', ?, ?, ?)
                """, (name, phone, vendor_id, custom_data_str, next_display_id))
                
                person_id = c.lastrowid

                # Optional: Automated Login Creation ("Inking")
                # Use id_key value if found in row
                student_id_val = str(row.get(id_key) or "").strip() if id_key else ""
                if inking_enabled and student_id_val and phone:
                    # Check if user already exists
                    c.execute("SELECT username FROM system_users WHERE username = ?", (student_id_val,))
                    if not c.fetchone():
                        c.execute("""
                            INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id)
                            VALUES (?, ?, ?, 'user', ?, ?)
                        """, (student_id_val, phone, phone, vendor_id, person_id))

                success_count += 1
            except Exception as e:
                errors.append(f"Row {row_idx + 2}: {str(e)}")

        # CRITICAL: Strictly synchronize registration config with CURRENT Excel headers
        # This replaces all previous dynamic fields with the ones in the current Excel.
        new_sync_fields = []
        
        for h in headers:
            field_name = str(h).strip()
            # Preserve existing metadata if the label matches (case-insensitive)
            existing_f = next((f for f in existing_fields if f.get('label', '').lower() == field_name.lower()), None)
            
            field_config = existing_f if existing_f else {
                "name": field_name,
                "label": field_name, # Use EXACT label from Excel
                "type": "text",
                "required": False,
                "default": False
            }
            
            # Map core metadata so frontend can intelligently display them
            if h == name_key:
                field_config["is_name"] = True
            if h == phone_key:
                field_config["is_phone"] = True
            if h == id_key:
                field_config["is_id"] = True
                
            new_sync_fields.append(field_config)

        # Update strictly
        fields_json = json.dumps(new_sync_fields)
        c.execute("""
            INSERT INTO bulk_attendance_config (vendor_id, fields)
            VALUES (?, ?)
            ON CONFLICT (vendor_id) DO UPDATE SET fields = EXCLUDED.fields, updated_at = CURRENT_TIMESTAMP
        """, (vendor_id, fields_json))
        
        # Sync with vendors.registration_config to reflect in People Management UI
        c.execute("SELECT registration_config FROM vendors WHERE id = ?", (vendor_id,))
        v_row = c.fetchone()
        old_reg_config = json.loads(v_row[0] or '[]') if v_row else []
        
        new_reg_config = []
        for f in new_sync_fields:
            # Preserve existing manual tweaks if available
            existing_reg = next((reg for reg in old_reg_config if reg.get('field') == f['name']), None)
            if existing_reg:
                new_reg_config.append(existing_reg)
            else:
                new_reg_config.append({
                    "field": f['name'],
                    "label": f['label'],
                    "type": "text",
                    "enabled": True,
                    "required": False,
                    "is_name": f.get('is_name', False),
                    "is_phone": f.get('is_phone', False),
                    "is_id": f.get('is_id', False)
                })
        
        c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (json.dumps(new_reg_config), vendor_id))

        conn.commit()
        conn.close()

        log_audit('bulk_registration', details={"success_count": success_count, "skipped_count": skipped_count, "filename": filename}, target_vendor_id=vendor_id)

        return jsonify({
            "success": True, 
            "message": f"Successfully registered {success_count} students.", 
            "skipped": skipped_count,
            "errors": errors[:10] # Return first 10 errors
        })

    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}"}), 500


@bulk_registration_bp.route("/bulk-registration/faculty-logins", methods=["GET"])
@require_auth()
def list_faculty_logins():
    """Vendor-scoped endpoint to list all faculty accounts."""
    vendor_id = g.vendor_id
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT username, password_plain, last_active_at, has_set_password
            FROM system_users
            WHERE vendor_id = ? AND role = 'faculty'
            ORDER BY username ASC
        """, (vendor_id,))
        rows = c.fetchall()
        logins = []
        for row in rows:
            try:
                r = dict(row)
            except Exception:
                r = {"username": row[0], "password_plain": row[1], "last_active_at": row[2], "has_set_password": row[3]}
            logins.append({
                "email": r.get("username"),
                "password_plain": r.get("password_plain"),
                "last_login": r.get("last_active_at"),
                "status": "CHANGED" if r.get("has_set_password") == 1 else "DEFAULT"
            })
        return jsonify({"success": True, "logins": logins})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

@bulk_registration_bp.route("/bulk-registration/upload-faculty", methods=["POST"])
@require_auth()
def bulk_registration_upload_faculty():
    """Extract email addresses from any column in an Excel/CSV and create faculty logins."""
    from services.auth_service import hash_password
    vendor_id = g.vendor_id

    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower()
    try:
        data = []
        if ext == 'csv':
            content = file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            data = [row for row in reader]
        elif ext in ['xls', 'xlsx']:
            df = pd.read_excel(file)
            df = df.where(pd.notnull(df), None)
            data = df.to_dict(orient='records')
        else:
            return jsonify({"error": f"Unsupported file type: {ext}"}), 400

        if not data:
            return jsonify({"error": "File is empty"}), 400

        # Collect every email found in any cell across every row
        emails_found = set()
        for row in data:
            for val in row.values():
                if val is None:
                    continue
                matches = EMAIL_RE.findall(str(val))
                for m in matches:
                    emails_found.add(m.lower().strip())

        if not emails_found:
            return jsonify({"error": "No email addresses found in the file. Make sure at least one column contains emails (e.g. teacher@school.edu)."}), 400

        conn = get_db_connection()
        c = conn.cursor()
        hashed_default = hash_password("1234")
        created = 0
        skipped = 0

        for email in emails_found:
            c.execute("SELECT username FROM system_users WHERE username = ? AND vendor_id = ?", (email, vendor_id))
            if c.fetchone():
                skipped += 1
                continue
            c.execute("""
                INSERT INTO system_users (username, password, password_plain, role, vendor_id, has_set_password)
                VALUES (?, ?, ?, 'faculty', ?, 0)
            """, (email, hashed_default, "1234", vendor_id))
            created += 1

        conn.commit()
        conn.close()

        log_audit('faculty_upload', details={"created": created, "skipped": skipped, "filename": file.filename}, target_vendor_id=vendor_id)

        return jsonify({
            "success": True,
            "message": f"Created {created} faculty login(s). {skipped} already existed.",
            "created": created,
            "skipped": skipped
        })

    except Exception as e:
        return jsonify({"error": f"Faculty upload failed: {str(e)}"}), 500
