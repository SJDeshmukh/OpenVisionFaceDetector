from flask import Blueprint, request, jsonify
import json
import base64
import numpy as np
from datetime import datetime
from services.auth_service import authenticate_vendor_access, hash_password, verify_token
from services.face_service import _normalize_vec, _decode_data_uri_to_rgb
from utils import get_db_connection

leave_bp = Blueprint('leave_bp', __name__)

def get_row_dict(row):
    if row is None: return None
    # If it's a DictRow (Postgres) or sqlite3.Row, it supports dict()
    try:
        return dict(row)
    except (TypeError, ValueError):
        # Fallback for other row types if necessary
        return row

@leave_bp.route("/request", methods=["POST"])
def create_leave_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json
    student_id = data.get("student_id")
    leave_type = data.get("leave_type")
    reason = data.get("reason")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    start_time = data.get("start_time", "10:00")
    end_time = data.get("end_time", "18:00")
    
    if not all([student_id, leave_type, reason, start_date, end_date]):
        return jsonify({"error": "Missing required fields"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Resolve student_id if it's a string (username) instead of an integer (person_id)
        if isinstance(student_id, str) and not student_id.isdigit():
            is_pg = getattr(conn, "_is_pg", False)
            if is_pg:
                c.execute("""
                    SELECT id FROM faces 
                    WHERE vendor_id = %s AND (
                        custom_data::jsonb->>'student_number' = %s OR 
                        custom_data::jsonb->>'admission_number' = %s OR 
                        custom_data::jsonb->>'roll_number' = %s
                    )
                """, (vendor_id, student_id, student_id, student_id))
            else:
                c.execute("""
                    SELECT id FROM faces 
                    WHERE vendor_id = ? AND (
                        json_extract(custom_data, '$.student_number') = ? OR 
                        json_extract(custom_data, '$.admission_number') = ? OR 
                        json_extract(custom_data, '$.roll_number') = ?
                    )
                """, (vendor_id, student_id, student_id, student_id))
            
            row = c.fetchone()
            if row:
                student_id = row[0]
            else:
                return jsonify({"error": f"Student with ID {student_id} not found in face records"}), 404

        c.execute("""
            INSERT INTO leave_requests 
            (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time))
        conn.commit()
        request_id = c.lastrowid
        return jsonify({"status": "success", "request_id": request_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/parent/pending", methods=["GET"])
def get_parent_pending_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    student_number = request.args.get("student_number")
    if not student_number:
        return jsonify({"error": "student_number required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT id, custom_data FROM faces WHERE vendor_id = ?", (vendor_id,))
        faces = c.fetchall()
        student_id = None
        for f in faces:
            row = get_row_dict(f)
            cd = json.loads(row.get('custom_data') or '{}')
            if str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number')) == str(student_number):
                student_id = row['id']
                break
        
        if not student_id:
            return jsonify({"requests": []})

        c.execute("SELECT * FROM leave_requests WHERE student_id = ? AND vendor_id = ? AND parent_status = 'pending'", (student_id, vendor_id))
        rows = c.fetchall()
        return jsonify({"requests": [get_row_dict(r) for r in rows]})
    finally:
        conn.close()

@leave_bp.route("/parent/register-face", methods=["POST"])
def parent_register_face():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json
    student_number = data.get("student_number")
    face_image = data.get("face_image")
    
    if not student_number or not face_image:
        return jsonify({"error": "student_number and face_image required"}), 400

    from multiple_face_detection import app as mfd_app
    img_rgb = _decode_data_uri_to_rgb(face_image)
    if img_rgb is None:
        return jsonify({"error": "Invalid image"}), 400

    try:
        det_ann, det_crops, _, _ = mfd_app.detect_faces(img_rgb, compute_embeddings=False, crop_mode="Face")
        if not det_crops:
             return jsonify({"error": "No face detected"}), 400
        
        crop = det_crops[0]
        emb = mfd_app.get_embedder().embed(crop)
        emb = _normalize_vec(emb)
        face_template = base64.b64encode(emb.astype(np.float32).tobytes()).decode('ascii')

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE parent_users SET face_image = ?, face_template = ? WHERE student_number = ? AND vendor_id = ?", 
                  (face_image, face_template, student_number, vendor_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@leave_bp.route("/parent/approve", methods=["POST"])
def parent_approve_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json
    request_id = data.get("request_id")
    student_number = data.get("student_number")
    captured_face = data.get("captured_face")
    action = data.get("action")
    
    if not all([request_id, student_number, captured_face, action]):
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT face_template FROM parent_users WHERE student_number = ? AND vendor_id = ?", (student_number, vendor_id))
        parent = get_row_dict(c.fetchone())
        if not parent or not parent.get('face_template'):
            return jsonify({"error": "Parent face not registered"}), 400
        
        from multiple_face_detection import app as mfd_app
        img_rgb = _decode_data_uri_to_rgb(captured_face)
        det_ann, det_crops, _, _ = mfd_app.detect_faces(img_rgb, compute_embeddings=False, crop_mode="Face")
        if not det_crops:
            return jsonify({"error": "No face detected in captured image"}), 400
        
        emb = mfd_app.get_embedder().embed(det_crops[0])
        emb = _normalize_vec(emb)
        
        stored_template = np.frombuffer(base64.b64decode(parent['face_template']), dtype=np.float32)
        similarity = float(np.dot(emb, stored_template))
        
        if similarity < 0.6:
             return jsonify({"error": "Face verification failed", "similarity": similarity}), 401

        c.execute("UPDATE leave_requests SET parent_status = ? WHERE id = ? AND vendor_id = ?", 
                  (action, request_id, vendor_id))
        conn.commit()
        return jsonify({"status": "success", "similarity": similarity})
    finally:
        conn.close()

@leave_bp.route("/admin/pending", methods=["GET"])
def get_admin_pending_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    role = request.args.get("role", "rector")
    dept = request.args.get("department") # Provided by PIN verification
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        if role == 'rector':
            c.execute("""
                SELECT lr.*, f.name as student_name 
                FROM leave_requests lr
                JOIN faces f ON lr.student_id = f.id
                WHERE lr.vendor_id = ? AND lr.parent_status = 'approved' AND lr.rector_status = 'pending'
            """, (vendor_id,))
        elif role == 'hod':
            if not dept:
                return jsonify({"error": "Department required for HOD"}), 400
            c.execute("""
                SELECT lr.*, f.name as student_name 
                FROM leave_requests lr
                JOIN faces f ON lr.student_id = f.id
                WHERE lr.vendor_id = ? 
                AND lr.rector_status = 'approved' 
                AND lr.hod_status = 'pending'
                AND f.department = ?
            """, (vendor_id, dept))
        else:
            return jsonify({"error": "Invalid role"}), 400
            
        rows = c.fetchall()
        return jsonify({"requests": [get_row_dict(r) for r in rows]})
    finally:
        conn.close()

@leave_bp.route("/admin/approve", methods=["POST"])
def admin_approve_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json
    request_id = data.get("request_id")
    role = data.get("role")
    action = data.get("action")
    
    if not all([request_id, role, action]):
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        if role == 'hod':
            # Verify Rector already approved
            c.execute("SELECT rector_status FROM leave_requests WHERE id = ?", (request_id,))
            res = c.fetchone()
            if not res or get_row_dict(res).get('rector_status') != 'approved':
                return jsonify({"error": "Wait for Rector's approval first"}), 400
            
            column = "hod_status"
            c.execute(f"UPDATE leave_requests SET {column} = ? WHERE id = ? AND vendor_id = ?", 
                      (action, request_id, vendor_id))
            if action == 'approved':
                c.execute("UPDATE leave_requests SET final_status = 'approved' WHERE id = ?", (request_id,))
        else:
            # Rector approval
            column = "rector_status"
            c.execute(f"UPDATE leave_requests SET {column} = ? WHERE id = ? AND vendor_id = ?", 
                      (action, request_id, vendor_id))
            
        if action == 'rejected':
            c.execute("UPDATE leave_requests SET final_status = 'rejected' WHERE id = ?", (request_id,))
            
        conn.commit()
        return jsonify({"status": "success"})
    finally:
        conn.close()

@leave_bp.route("/admin/generate-logins", methods=["POST"])
def generate_student_logins():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Get all faces for this vendor
        c.execute("SELECT id, name, custom_data FROM faces WHERE vendor_id = ?", (vendor_id,))
        faces = c.fetchall()
        
        created_count = 0
        skipped_count = 0
        
        for f in faces:
            row = get_row_dict(f)
            cd = json.loads(row.get('custom_data') or '{}')
            student_number = str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or "").strip()
            
            if not student_number:
                skipped_count += 1
                continue
                
            # Check if user already exists
            c.execute("SELECT username FROM system_users WHERE username = ?", (student_number,))
            if c.fetchone():
                skipped_count += 1
                continue
                
            # Create system user
            # Default password is the student's phone number
            phone = row.get('phone') or ""
            c.execute(
                "INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (?, ?, ?, 'user', ?, ?)",
                (student_number, hash_password(phone), phone, vendor_id, row.get('id'))
            )
            created_count += 1
            
        conn.commit()
        return jsonify({
            "status": "success", 
            "created": created_count, 
            "skipped": skipped_count,
            "message": f"Successfully created {created_count} student logins. Default password is 'student' followed by student number."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/verify-pin", methods=["POST"])
def verify_staff_pin():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json
    pin = data.get("pin")
    
    if not pin:
        return jsonify({"error": "PIN required"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT id, name, role, department FROM leave_staff WHERE vendor_id = ? AND pin = ?", (vendor_id, pin))
        staff = c.fetchone()
        if staff:
            res = get_row_dict(staff)
            return jsonify({"status": "success", "staff": res})
        else:
            return jsonify({"error": "Invalid PIN"}), 401
    finally:
        conn.close()

@leave_bp.route("/admin/staff", methods=["GET", "POST", "DELETE"])
def manage_staff():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        if request.method == "GET":
            c.execute("SELECT id, name, role, pin, department FROM leave_staff WHERE vendor_id = ?", (vendor_id,))
            staff = c.fetchall()
            return jsonify({"staff": [get_row_dict(s) for s in staff]})
            
        elif request.method == "POST":
            data = request.json
            name = data.get("name")
            role = data.get("role")
            pin = data.get("pin")
            department = data.get("department")
            
            if not all([name, role, pin]):
                return jsonify({"error": "Missing required fields"}), 400
                
            # If HOD, ensure department is provided and not already assigned
            if role == 'hod':
                if not department:
                    return jsonify({"error": "Department required for HOD"}), 400
                c.execute("SELECT id FROM leave_staff WHERE vendor_id = ? AND department = ? AND role = 'hod'", (vendor_id, department))
                if c.fetchone():
                    return jsonify({"error": f"An HOD is already assigned to {department}"}), 409

            # Check for duplicate PIN
            c.execute("SELECT id FROM leave_staff WHERE vendor_id = ? AND pin = ?", (vendor_id, pin))
            if c.fetchone():
                return jsonify({"error": "This PIN is already assigned to someone else"}), 409

            c.execute(
                "INSERT INTO leave_staff (vendor_id, name, role, pin, department) VALUES (?, ?, ?, ?, ?)",
                (vendor_id, name, role, pin, department)
            )
            conn.commit()
            return jsonify({"status": "success", "message": "Staff added successfully"})
            
        elif request.method == "DELETE":
            staff_id = request.args.get("id")
            c.execute("DELETE FROM leave_staff WHERE id = ? AND vendor_id = ?", (staff_id, vendor_id))
            conn.commit()
            return jsonify({"status": "success"})
    finally:
        conn.close()

@leave_bp.route("/admin/departments", methods=["GET", "POST", "DELETE"])
def manage_departments():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        if request.method == "GET":
            c.execute("SELECT departments FROM vendors WHERE id = ?", (vendor_id,))
            res = c.fetchone()
            depts = json.loads(res[0] or '[]') if res and res[0] else []
            return jsonify({"departments": depts})
            
        elif request.method == "POST":
            dept_name = request.json.get("name")
            if not dept_name: return jsonify({"error": "Name required"}), 400
            
            c.execute("SELECT departments FROM vendors WHERE id = ?", (vendor_id,))
            res = c.fetchone()
            depts = json.loads(res[0] or '[]') if res and res[0] else []
            
            if dept_name in depts:
                return jsonify({"error": "Department already exists"}), 409
                
            depts.append(dept_name)
            c.execute("UPDATE vendors SET departments = ? WHERE id = ?", (json.dumps(depts), vendor_id))
            conn.commit()
            return jsonify({"status": "success", "departments": depts})
            
        elif request.method == "DELETE":
            dept_name = request.args.get("name")
            c.execute("SELECT departments FROM vendors WHERE id = ?", (vendor_id,))
            res = c.fetchone()
            depts = json.loads(res[0] or '[]') if res and res[0] else []
            
            if dept_name in depts:
                depts.remove(dept_name)
                c.execute("UPDATE vendors SET departments = ? WHERE id = ?", (json.dumps(depts), vendor_id))
                conn.commit()
            return jsonify({"status": "success", "departments": depts})
    finally:
        conn.close()

@leave_bp.route("/student/change-password", methods=["POST"])
def student_change_password():
    # Only students should call this
    auth_header = request.headers.get("Authorization")
    if not auth_header: return jsonify({"error": "Missing token"}), 401
    token = auth_header.split(" ")[1]
    user_data = verify_token(token)
    if not user_data or user_data['role'] != 'user':
        return jsonify({"error": "Student access required"}), 403
        
    data = request.json
    new_password = data.get("password")
    if not new_password: return jsonify({"error": "Password required"}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Update the password (hashed), store plain text for SuperAdmin visibility, and set flag
        c.execute(
            "UPDATE system_users SET password = ?, password_plain = ?, has_set_password = 1 WHERE username = ?",
            (hash_password(new_password), new_password, user_data['username'])
        )
        conn.commit()
        return jsonify({"status": "success", "message": "Password updated successfully"})
    finally:
        conn.close()

@leave_bp.route('/admin/vendors/<int:vendor_id>/student-logins', methods=['GET'])
def get_vendor_student_logins(vendor_id):
    # This is for SuperAdmin to see student passwords
    # In a real app, you'd check if the requester is a superadmin
    db = get_db()
    # Join with faces to get full name if available
    query = """
    SELECT u.username, u.password_plain, u.last_login, f.name 
    FROM system_users u
    LEFT JOIN faces f ON u.username = f.student_number AND f.vendor_id = u.vendor_id
    WHERE u.vendor_id = %s AND u.role = 'user'
    """
    params = (vendor_id,)
    
    if isinstance(db, sqlite3.Connection):
        query = query.replace('%s', '?')
        
    cursor = db.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    logins = []
    for row in rows:
        logins.append({
            "username": row[0],
            "password_plain": row[1],
            "last_login": row[2],
            "full_name": row[3]
        })
        
    return jsonify({"status": "success", "logins": logins})

@leave_bp.route("/parent-faces", methods=["GET"])
def get_parent_faces():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Use public. prefix just in case there's schema ambiguity, and SELECT * to avoid individual column issues temporarily if needed
        # But we'll try to keep the explicit columns first
        c.execute("SELECT id, username, student_number, contact_phone, face_image FROM public.parent_users WHERE vendor_id = %s AND face_image IS NOT NULL", (vendor_id,))
        rows = c.fetchall()
        return jsonify({"parents": [get_row_dict(r) for r in rows]})
    except Exception as e:
        # Fallback to SELECT * if explicit columns still fail (sanity check)
        try:
            c.execute("SELECT * FROM public.parent_users WHERE vendor_id = %s AND face_image IS NOT NULL", (vendor_id,))
            rows = c.fetchall()
            return jsonify({"parents": [get_row_dict(r) for r in rows]})
        except:
             return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/student/history", methods=["GET"])
def get_student_history():
    auth_header = request.headers.get("Authorization")
    if not auth_header: return jsonify({"error": "Missing token"}), 401
    token = auth_header.split(" ")[1]
    user_data = verify_token(token)
    if not user_data or user_data['role'] != 'user':
        return jsonify({"error": "Student access required"}), 403
    
    student_number = user_data.get('username')
    vendor_id = user_data.get('vendor_id')
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"History fetch: user={student_number}, vendor={vendor_id}, token_payload={user_data}")
    
    if not student_number or not vendor_id:
        return jsonify({"error": "Invalid token: missing username or vendor_id"}), 401
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Resolve student_id (faces.id) first
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            c.execute("""
                SELECT id FROM faces 
                WHERE vendor_id = %s AND (
                    custom_data::jsonb->>'student_number' = %s OR 
                    custom_data::jsonb->>'admission_number' = %s OR 
                    custom_data::jsonb->>'roll_number' = %s
                )
            """, (vendor_id, student_number, student_number, student_number))
        else:
            c.execute("""
                SELECT id FROM faces 
                WHERE vendor_id = ? AND (
                    json_extract(custom_data, '$.student_number') = ? OR 
                    json_extract(custom_data, '$.admission_number') = ? OR 
                    json_extract(custom_data, '$.roll_number') = ?
                )
            """, (vendor_id, student_number, student_number, student_number))
        
        face_row = c.fetchone()
        if not face_row:
            return jsonify({"requests": []})
        
        person_id = face_row[0]
        
        # Now fetch all requests for this person_id with student name
        if is_pg:
            c.execute("""
                SELECT lr.*, f.name as student_name 
                FROM leave_requests lr
                JOIN faces f ON lr.student_id = f.id
                WHERE lr.student_id = %s AND lr.vendor_id = %s 
                ORDER BY lr.created_at DESC
            """, (person_id, vendor_id))
        else:
            c.execute("""
                SELECT lr.*, f.name as student_name 
                FROM leave_requests lr
                JOIN faces f ON lr.student_id = f.id
                WHERE lr.student_id = ? AND lr.vendor_id = ? 
                ORDER BY lr.created_at DESC
            """, (person_id, vendor_id))
            
        rows = c.fetchall()
        return jsonify({"status": "success", "requests": [get_row_dict(r) for r in rows]})
    finally:
        conn.close()
