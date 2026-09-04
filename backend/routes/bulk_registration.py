import json
import re
import uuid
import csv
import io
import secrets
import pandas as pd
from flask import Blueprint, request, jsonify, g
from utils import get_db_connection, log_audit, vendor_has_feature
from services.auth_service import require_auth, hash_password
from openpyxl import load_workbook

bulk_registration_bp = Blueprint('bulk_registration_bp', __name__)

def _fuzzy_match(header, targets):
    h = str(header).strip().lower()
    for t in targets:
        if t.lower() in h:
            return True
    return False

@bulk_registration_bp.route("/bulk-registration/upload", methods=["POST"])
@require_auth(roles=['super_admin', 'vendor_admin', 'owner'])
def bulk_registration_upload():
    vendor_id = g.vendor_id
    if not vendor_id:
        return jsonify({"error": "Select a business before uploading"}), 400
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

        if not data or not isinstance(data, list):
            return jsonify({"error": "File is empty or invalid format"}), 400

        # Optional Class Scope from request (Class-Specific Upload)
        req_class_id = request.form.get('class_id')
        req_class_year = None
        req_division = None
        req_branch = None

        headers = list(data[0].keys())
        excel_class_id_key = next(
            (h for h in headers if str(h).strip().lower().replace(' ', '_') == 'class_id'),
            None,
        )

        # Mapping Logic - Expanded for better auto-identification
        name_targets = ["name", "full name", "student name", "employee name", "person name", "first name"]
        id_targets = [
            "student id", "student_id", "student number", "student_number", "student no",
            "roll number", "roll no", "roll num", "enrollment number", "enrollment no",
            "enroll no", "admission number", "admission no", "id number", "id"
        ]
        phone_targets = [
            "mobile", "phone", "contact", "whatsapp", "parent number", "parent mobile",
            "alternative number", "student mobile number", "student mobile", "student phone",
            "student contact", "contact number", "contact mobile"
        ]
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

        # Treat class metadata from the browser as untrusted. Resolve the class
        # exclusively inside the authenticated vendor before any preview/import
        # data is processed.
        if req_class_id:
            c.execute(
                "SELECT class_year, division, branch FROM classes WHERE id = ? AND vendor_id = ?",
                (req_class_id, vendor_id),
            )
            class_row = c.fetchone()
            if not class_row:
                return jsonify({"error": "The selected class does not belong to this business"}), 400
            req_class_year, req_division, req_branch = class_row[0], class_row[1], class_row[2]

        # Determine the correct custom_data key for student ID based on vendor vertical.
        # AttendX uses 'student_number'; TapInX / school / hostel use 'student_id'.
        c.execute("SELECT vertical FROM vendors WHERE id = ?", (vendor_id,))
        _vrow = c.fetchone()
        _vendor_vertical = ((_vrow['vertical'] or '') if hasattr(_vrow, 'keys') else (_vrow[0] or '')) if _vrow else ''
        student_id_custom_key = 'student_number' if _vendor_vertical == 'bulk_attendance_attendx' else 'student_id'

        # Get features for automated login creation ("Inking")
        c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        s_row = c.fetchone()
        features = json.loads(s_row[0] or '[]') if s_row else []
        inking_enabled = 'leave_management' in features or 'mobile_app' in features

        success_count = 0
        skipped_count = 0
        errors = []
        observed_scope_fields = set()

        # Track existing dynamic fields for bulk_attendance_config
        c.execute("SELECT fields FROM bulk_attendance_config WHERE vendor_id = ?", (vendor_id,))
        bulk_row = c.fetchone()
        
        # Check if 0 users remain, then clear config to start fresh
        c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (vendor_id,))
        if c.fetchone()[0] == 0:
            existing_fields = []
        else:
            existing_fields = json.loads(bulk_row[0] or '[]') if bulk_row else []
        for row_idx, row in enumerate(data):
            try:
                name = str(row.get(name_key) or "").strip()
                if not name:
                    skipped_count += 1
                    continue

                row_class_id = req_class_id
                row_class_year = req_class_year
                row_division = req_division
                row_branch = req_branch
                if not row_class_id and excel_class_id_key:
                    row_class_id = str(row.get(excel_class_id_key) or '').strip()
                    if row_class_id:
                        c.execute(
                            "SELECT class_year, division, branch FROM classes WHERE id = ? AND vendor_id = ?",
                            (row_class_id, vendor_id),
                        )
                        row_class = c.fetchone()
                        if not row_class:
                            errors.append(f"Row {row_idx + 2}: class_id does not belong to this business")
                            skipped_count += 1
                            continue
                        row_class_year, row_division, row_branch = row_class[0], row_class[1], row_class[2]

                phone = str(row.get(phone_key) or "").strip()

                # Duplicate detection: case-insensitive name + phone match within same vendor
                if phone:
                    c.execute(
                        "SELECT id FROM faces WHERE vendor_id = ? AND LOWER(name) = LOWER(?) AND phone = ?",
                        (vendor_id, name, phone)
                    )
                elif row_class_id:
                    c.execute(
                        "SELECT id FROM faces WHERE vendor_id = ? AND LOWER(name) = LOWER(?) AND json_extract(custom_data, '$.class_id') = ?",
                        (vendor_id, name, row_class_id)
                    )
                else:
                    c.execute(
                        "SELECT id FROM faces WHERE vendor_id = ? AND LOWER(name) = LOWER(?)",
                        (vendor_id, name)
                    )
                if c.fetchone():
                    skipped_count += 1
                    continue

                # Build custom_data; exclude name and phone (stored in core columns)
                custom_dict = {}
                for k, v in row.items():
                    if k in [name_key, phone_key, id_key]:
                        continue
                    if v is not None:
                        custom_dict[str(k).strip()] = str(v).strip()

                # Always store student ID in custom_data under the normalised key so
                # the parent login lookup (_extract_student_number_from_custom_data)
                # can find it regardless of what the Excel column was named.
                if id_key:
                    id_val = str(row.get(id_key) or '').strip()
                    if id_val:
                        custom_dict[student_id_custom_key] = id_val

                # Inject Class Scope if provided via Class Cards flow
                if row_class_id: custom_dict['class_id'] = str(row_class_id)
                if row_class_year:
                    custom_dict['class_year'] = row_class_year
                    observed_scope_fields.add('class_year')
                if row_division:
                    custom_dict['division'] = row_division
                    observed_scope_fields.add('division')
                if row_branch:
                    custom_dict['branch'] = row_branch
                    observed_scope_fields.add('branch')

                custom_data_str = json.dumps(custom_dict, separators=(',', ':'))

                # Get next display_id
                c.execute("SELECT COALESCE(MAX(display_id), 0) + 1 FROM faces WHERE vendor_id = ?", (vendor_id,))
                next_display_id = c.fetchone()[0]

                c.execute("""
                    INSERT INTO faces (name, phone, department, designation, shift, vendor_id, custom_data, display_id)
                    VALUES (?, ?, '', '', '', ?, ?, ?)
                """, (name, phone, vendor_id, custom_data_str, next_display_id))

                person_id = c.lastrowid

                # Optional: Automated Login Creation ("Inking")
                student_id_val = str(row.get(id_key) or "").strip() if id_key else ""
                if inking_enabled and student_id_val and phone:
                    c.execute("SELECT username FROM system_users WHERE username = ?", (student_id_val,))
                    if not c.fetchone():
                        c.execute("""
                            INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id)
                            VALUES (?, ?, NULL, 'user', ?, ?)
                        """, (student_id_val, hash_password(phone), vendor_id, person_id))

                success_count += 1
            except Exception as e:
                errors.append(f"Row {row_idx + 2}: {str(e)}")

        # CRITICAL: Strictly synchronize registration config with CURRENT Excel headers
        # This replaces all previous dynamic fields with the ones in the current Excel.
        new_sync_fields = []
        
        for h in headers:
            field_name = str(h).strip()
            if not field_name:
                continue
            canonical_name = (
                'name' if h == name_key else
                'phone' if h == phone_key else
                student_id_custom_key if h == id_key else
                field_name
            )
            existing_f = next((f for f in existing_fields if str(f.get('label') or '').strip().lower() == field_name.lower() or str(f.get('name') or '').strip().lower() == canonical_name.lower()), None)

            field_config = {
                **(existing_f or {}),
                "name": canonical_name,
                "label": field_name, # Use EXACT label from Excel
                "type": (existing_f or {}).get("type") or "text",
                "required": bool((existing_f or {}).get("required", h == name_key)),
                "default": False,
                "is_name": h == name_key,
                "is_phone": h == phone_key,
                "is_id": h == id_key,
            }
                
            new_sync_fields.append(field_config)

        # Class cards can supply scope outside the spreadsheet columns. Record
        # only scope fields actually used by this upload so Reports can expose
        # them without injecting class filters into unrelated vendors.
        scope_labels = {
            'class_year': 'Class / Year',
            'division': 'Division / Section',
            'branch': 'Branch / Department',
        }
        configured_names = {str(field.get('name') or '').strip().lower() for field in new_sync_fields}
        for scope_name in ('class_year', 'division', 'branch'):
            if scope_name in observed_scope_fields and scope_name not in configured_names:
                new_sync_fields.append({
                    'name': scope_name,
                    'label': scope_labels[scope_name],
                    'type': 'text',
                    'required': False,
                    'default': False,
                    'is_name': False,
                    'is_phone': False,
                    'is_id': False,
                })

        # Update strictly
        fields_json = json.dumps(new_sync_fields, separators=(',', ':'))
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
            existing_reg = next((reg for reg in old_reg_config if str(reg.get('field') or '').strip().lower() == str(f['name']).strip().lower() or str(reg.get('label') or '').strip().lower() == str(f['label']).strip().lower()), None)
            if existing_reg:
                new_reg_config.append({
                    **existing_reg,
                    "field": f['name'],
                    "label": f['label'],
                    "type": existing_reg.get('type') or 'text',
                    "enabled": True,
                    "is_name": f.get('is_name', False),
                    "is_phone": f.get('is_phone', False),
                    "is_id": f.get('is_id', False),
                })
            else:
                new_reg_config.append({
                    "field": f['name'],
                    "label": f['label'],
                    "type": "text",
                    "enabled": True,
                    "required": bool(f.get('required', False)),
                    "is_name": f.get('is_name', False),
                    "is_phone": f.get('is_phone', False),
                    "is_id": f.get('is_id', False)
                })
        
        c.execute("UPDATE vendors SET registration_config = ? WHERE id = ?", (json.dumps(new_reg_config, separators=(',', ':')), vendor_id))

        conn.commit()
        log_audit('bulk_registration', details={"success_count": success_count, "skipped_count": skipped_count, "filename": filename}, target_vendor_id=vendor_id)

        return jsonify({
            "success": True,
            "message": f"Successfully registered {success_count} students.",
            "skipped": skipped_count,
            "errors": errors[:10]
        })

    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}"}), 500

    finally:
        try:
            conn.close()
        except Exception:
            pass


EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

@bulk_registration_bp.route("/bulk-registration/faculty", methods=["POST"])
@require_auth(roles=['super_admin', 'vendor_admin', 'owner'])
def create_faculty_single():
    """Create a single faculty login account."""
    from services.auth_service import hash_password
    vendor_id = g.vendor_id
    data = request.json or {}

    email = str(data.get('email') or '').strip().lower()
    name = str(data.get('name') or '').strip()
    phone = str(data.get('phone') or '').strip()
    designation = str(data.get('designation') or '').strip() or 'Faculty'
    password = str(data.get('password') or '').strip()
    if len(password) < 8:
        return jsonify({"error": "Password must contain at least 8 characters"}), 400

    if not email or not EMAIL_RE.match(email):
        return jsonify({"error": "A valid email address is required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT username FROM system_users WHERE username = ? AND vendor_id = ?", (email, vendor_id))
        if c.fetchone():
            return jsonify({"error": "A faculty account with this email already exists"}), 409

        name_val = name or email.split('@')[0]
        c.execute(
            "INSERT INTO faces (name, phone, designation, vendor_id) VALUES (?, ?, ?, ?)",
            (name_val, phone, designation, vendor_id)
        )
        person_id = c.lastrowid

        hashed = hash_password(password)
        c.execute("""
            INSERT INTO system_users (username, password, password_plain, role, vendor_id, has_set_password, person_id)
            VALUES (?, ?, NULL, 'faculty', ?, 0, ?)
        """, (email, hashed, vendor_id, person_id))
        conn.commit()

        log_audit('faculty_created_single', details={"email": email}, target_vendor_id=vendor_id)
        return jsonify({"success": True, "message": f"Faculty {email} created."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@bulk_registration_bp.route("/bulk-registration/upload-faculty", methods=["POST"])
@require_auth(roles=['super_admin', 'vendor_admin', 'owner'])
def bulk_registration_upload_faculty():
    """Extract faculty logins and metadata (Name, Phone, Designation) from Excel/CSV."""
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

        # Attempt to map columns
        headers = list(data[0].keys())
        email_key = None
        name_key = None
        phone_key = None
        desig_key = None

        for h in headers:
            h_low = str(h).lower().strip()
            if 'email' in h_low: email_key = h
            elif 'name' in h_low: name_key = h
            elif 'phone' in h_low or 'mobile' in h_low: phone_key = h
            elif 'designation' in h_low or 'role' in h_low or 'desig' in h_low: desig_key = h

        if not email_key:
            # Fallback to searching all cells if no explicit email column
            emails_to_process = []
            for row in data:
                for val in row.values():
                    if val is None: continue
                    matches = EMAIL_RE.findall(str(val))
                    for m in matches:
                        emails_to_process.append({
                            'email': m.lower().strip(),
                            'name': None,
                            'phone': None,
                            'designation': None
                        })
        else:
            emails_to_process = []
            for row in data:
                email = str(row.get(email_key) or "").strip().lower()
                if not email or not EMAIL_RE.match(email): continue
                emails_to_process.append({
                    'email': email,
                    'name': str(row.get(name_key) or "").strip() if name_key else None,
                    'phone': str(row.get(phone_key) or "").strip() if phone_key else None,
                    'designation': str(row.get(desig_key) or "").strip() if desig_key else None
                })

        if not emails_to_process:
            return jsonify({"error": "No valid email addresses found in the file."}), 400

        conn = get_db_connection()
        c = conn.cursor()
        created = 0
        skipped = 0
        temporary_credentials = []

        for item in emails_to_process:
            email = item['email']
            c.execute("SELECT username FROM system_users WHERE username = ? AND vendor_id = ?", (email, vendor_id))
            if c.fetchone():
                skipped += 1
                continue
            
            # Create a Face record for metadata
            name_val = item['name']
            if not name_val and email:
                name_val = email.split('@')[0]
            elif not name_val:
                name_val = "Faculty"

            c.execute("""
                INSERT INTO faces (name, phone, designation, vendor_id)
                VALUES (?, ?, ?, ?)
            """, (name_val, item['phone'] or '', item['designation'] or 'Faculty', vendor_id))
            person_id = c.lastrowid

            # Create SystemUser
            temporary_password = secrets.token_urlsafe(12)
            c.execute("""
                INSERT INTO system_users (username, password, password_plain, role, vendor_id, has_set_password, person_id)
                VALUES (?, ?, NULL, 'faculty', ?, 0, ?)
            """, (email, hash_password(temporary_password), vendor_id, person_id))
            temporary_credentials.append({"email": email, "temporary_password": temporary_password})
            created += 1

        conn.commit()
        conn.close()

        log_audit('faculty_upload', details={"created": created, "skipped": skipped, "filename": file.filename}, target_vendor_id=vendor_id)

        return jsonify({
            "success": True,
            "message": f"Created {created} faculty login(s). {skipped} already existed.",
            "created": created,
            "skipped": skipped,
            "temporary_credentials": temporary_credentials
        })

    except Exception as e:
        return jsonify({"error": f"Faculty upload failed: {str(e)}"}), 500


@bulk_registration_bp.route("/bulk-registration/faculty-logins", methods=["GET"])
@require_auth(roles=['super_admin', 'vendor_admin', 'admin', 'owner'])
def list_faculty_logins():
    """Vendor-scoped endpoint to list all faculty accounts with metadata."""
    vendor_id = g.vendor_id
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Join with faces to get Name, Phone, Designation
        c.execute("""
            SELECT u.username, u.last_active_at, u.has_set_password,
                   f.name, f.phone, f.designation
            FROM system_users u
            LEFT JOIN faces f ON u.person_id = f.id
            WHERE u.vendor_id = ? AND u.role = 'faculty'
            ORDER BY u.username ASC
        """, (vendor_id,))
        rows = c.fetchall()
        logins = []
        for row in rows:
            try:
                r = dict(row)
            except Exception:
                r = {
                    "username": row[0], "last_active_at": row[1],
                    "has_set_password": row[2], "name": row[3], "phone": row[4], "designation": row[5]
                }
            logins.append({
                "email": r.get("username"),
                "last_login": r.get("last_active_at"),
                "status": "CHANGED" if r.get("has_set_password") == 1 else "DEFAULT",
                "name": r.get("name") or "",
                "phone": r.get("phone") or "",
                "designation": r.get("designation") or ""
            })
        return jsonify({"success": True, "logins": logins})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@bulk_registration_bp.route("/bulk-registration/faculty/<username>", methods=["DELETE"])
@require_auth()
def delete_faculty_login(username):
    """Delete a specific faculty login and its linked face record."""
    vendor_id = g.vendor_id
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Get person_id before deleting
        c.execute("SELECT person_id FROM system_users WHERE username = ? AND vendor_id = ?", (username, vendor_id))
        row = c.fetchone()
        person_id = row[0] if row else None

        # 1. Clear sessions
        c.execute("DELETE FROM active_sessions WHERE username = ? AND vendor_id = ?", (username, vendor_id))
        
        # 2. Delete the user
        c.execute("DELETE FROM system_users WHERE username = ? AND vendor_id = ? AND role = 'faculty'", (username, vendor_id))
        
        # 3. Delete the linked face record if exists
        if person_id:
            c.execute("DELETE FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        
        if c.rowcount == 0 and not person_id:
            return jsonify({"error": "Faculty user not found"}), 404
            
        conn.commit()
        from app import socketio
        socketio.emit('persons_updated', {'vendor_id': vendor_id, 'target': 'faculty'}, room=f"vendor_{vendor_id}")
        
        log_audit('faculty_deleted', details={"username": username}, target_vendor_id=vendor_id)
        return jsonify({"success": True, "message": f"Faculty {username} deleted."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@bulk_registration_bp.route("/bulk-registration/faculty/<username>", methods=["PUT"])
@require_auth(roles=['super_admin', 'vendor_admin', 'owner'])
def update_faculty_login(username):
    """Update metadata and password for a specific faculty login."""
    from services.auth_service import hash_password
    vendor_id = g.vendor_id
    data = request.json or {}
    
    new_password = data.get("password")
    new_name = data.get("name")
    new_phone = data.get("phone")
    new_designation = data.get("designation")
    new_email = data.get("email") # New username

    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Get person_id
        c.execute("SELECT person_id FROM system_users WHERE username = ? AND vendor_id = ?", (username, vendor_id))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Faculty user not found"}), 404
        person_id = row[0]

        # 1. Update system_users
        if new_password:
            hashed_pw = hash_password(new_password)
            c.execute("""
                UPDATE system_users 
                SET password = ?, password_plain = NULL, has_set_password = 1
                WHERE username = ? AND vendor_id = ?
            """, (hashed_pw, username, vendor_id))
        
        if new_email and new_email != username:
            # Check if new username is taken
            c.execute("SELECT 1 FROM system_users WHERE username = ?", (new_email,))
            if c.fetchone():
                return jsonify({"error": "Username already taken"}), 409
            c.execute("UPDATE system_users SET username = ? WHERE username = ? AND vendor_id = ?", (new_email, username, vendor_id))
            username = new_email

        # 2. Update faces record
        if person_id:
            c.execute("""
                UPDATE faces 
                SET name = COALESCE(?, name), 
                    phone = COALESCE(?, phone), 
                    designation = COALESCE(?, designation)
                WHERE id = ? AND vendor_id = ?
            """, (new_name, new_phone, new_designation, person_id, vendor_id))
        elif new_name or new_phone or new_designation:
            # Create Face record if it somehow didn't exist
            c.execute("""
                INSERT INTO faces (name, phone, designation, vendor_id)
                VALUES (?, ?, ?, ?)
            """, (new_name or username.split('@')[0], new_phone or '', new_designation or 'Faculty', vendor_id))
            new_person_id = c.lastrowid
            c.execute("UPDATE system_users SET person_id = ? WHERE username = ? AND vendor_id = ?", (new_person_id, username, vendor_id))
            
        conn.commit()
        log_audit('faculty_updated', details={"username": username}, target_vendor_id=vendor_id)
        return jsonify({"success": True, "message": f"Faculty {username} updated.", "new_username": username})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
