from flask import Blueprint, request, jsonify, g
import json
import base64
import numpy as np
from datetime import datetime, timedelta
from services.auth_service import authenticate_vendor_access, generate_token_with_claims, hash_password, verify_token, require_auth
from services.face_service import _normalize_vec, _decode_data_uri_to_rgb
from services.mobile_face_template import decode_face_template as _decode_face_template
from utils import get_db_connection, require_feature

leave_bp = Blueprint('leave_bp', __name__)

ALLOWED_LEAVE_ACTIONS = {"approved", "rejected"}

def get_row_dict(row):
    if row is None: return None
    # If it's a DictRow (Postgres) or sqlite3.Row, it supports dict()
    try:
        return dict(row)
    except (TypeError, ValueError):
        # Fallback for other row types if necessary
        return row


def _require_role(*allowed_roles):
    """Return a 403 response unless the authenticated principal has an allowed role."""
    if getattr(g, "user_role", None) not in allowed_roles:
        return jsonify({"error": "Forbidden", "code": "FORBIDDEN"}), 403
    return None


def _authenticated_parent(cursor, vendor_id):
    """Resolve the parent and linked student from the signed parent username."""
    if getattr(g, "user_role", None) != "parent" or not getattr(g, "username", None):
        return None
    cursor.execute(
        """SELECT id, student_number, selected_person_id, face_template
           FROM parent_users WHERE vendor_id = ? AND username = ?""",
        (vendor_id, g.username),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    mapped = get_row_dict(row)
    if isinstance(mapped, dict):
        return mapped
    return {
        "id": row[0],
        "student_number": row[1],
        "selected_person_id": row[2],
        "face_template": row[3],
    }


def _authenticated_leave_staff(vendor_id, required_role=None):
    """Validate the short-lived, signed staff session issued after PIN verification."""
    token = request.headers.get("X-Leave-Staff-Token")
    data = verify_token(token) if token else None
    if not data or data.get("role") != "leave_staff" or str(data.get("vendor_id")) != str(vendor_id):
        return None
    if required_role and data.get("staff_role") != required_role:
        return None

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, role, department FROM leave_staff WHERE id = ? AND vendor_id = ?", (data.get("staff_id"), vendor_id))
        row = c.fetchone()
        if not row:
            return None
        role = row["role"] if hasattr(row, "keys") else row[1]
        department = row["department"] if hasattr(row, "keys") else row[2]
        if role != data.get("staff_role") or (required_role and role != required_role):
            return None
        return {"id": data.get("staff_id"), "role": role, "department": department}
    finally:
        conn.close()

@leave_bp.route("/request", methods=["POST"])
@require_feature("leave_management")
def create_leave_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    role_error = _require_role("user", "student")
    if role_error: return role_error
    
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
        is_pg = getattr(conn, "_is_pg", False)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Creating leave request for student_id={student_id}, vendor_id={vendor_id}")

        # Never trust a body-supplied student ID. Resolve the student from the
        # authenticated account and only use the body field as a consistency check.
        if is_pg:
            c.execute(
                "SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s AND role IN ('user', 'student')",
                (vendor_id, g.username),
            )
        else:
            c.execute(
                "SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ? AND role IN ('user', 'student')",
                (vendor_id, g.username),
            )
        authenticated_student = c.fetchone()
        authenticated_person_id = authenticated_student[0] if authenticated_student else None
        if authenticated_person_id is not None:
            student_id = authenticated_person_id
        elif isinstance(student_id, str) and student_id.strip().lower() == str(g.username).strip().lower():
            # Compatibility fallback for older student accounts without person_id.
            student_id = g.username
        else:
            return jsonify({"error": "Student account is not linked to a face record"}), 409

        # Resolve the authenticated username to faces.id for legacy accounts.
        if isinstance(student_id, str):
            if is_pg:
                c.execute("""
                    SELECT id FROM faces 
                    WHERE vendor_id = %s AND (
                        id::text = %s OR
                        LOWER(TRIM(custom_data::jsonb->>'student_id')) = LOWER(TRIM(%s)) OR
                        LOWER(TRIM(custom_data::jsonb->>'id_number')) = LOWER(TRIM(%s)) OR
                        LOWER(TRIM(custom_data::jsonb->>'employee_id')) = LOWER(TRIM(%s))
                    )
                """, (vendor_id, student_id, student_id, student_id, student_id))
            else:
                c.execute("""
                    SELECT id FROM faces 
                    WHERE vendor_id = ? AND (
                        CAST(id AS TEXT) = ? OR
                        LOWER(TRIM(json_extract(custom_data, '$.student_id'))) = LOWER(TRIM(?)) OR
                        LOWER(TRIM(json_extract(custom_data, '$.id_number'))) = LOWER(TRIM(?)) OR
                        LOWER(TRIM(json_extract(custom_data, '$.employee_id'))) = LOWER(TRIM(?))
                    )
                """, (vendor_id, student_id, student_id, student_id, student_id))
            
            row = c.fetchone()
            
            # --- Robust Fallback: Check system_users table if faces lookup failed ---
            if not row:
                logger.info(f"Faces lookup failed for {student_id}, trying system_users fallback...")
                if is_pg:
                    c.execute("SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s AND person_id IS NOT NULL", (vendor_id, student_id))
                else:
                    c.execute("SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ? AND person_id IS NOT NULL", (vendor_id, student_id))
                row = c.fetchone()
            if row:
                if hasattr(row, 'keys') and 'id' in row.keys():
                    student_id = row['id']
                else:
                    student_id = row[0]
                logger.info(f"Resolved student_number {data.get('student_id')} to faces.id={student_id}")
            else:
                # If we couldn't resolve it and it's not numeric, it's definitely missing
                if not student_id.isdigit():
                    logger.error(f"Student {student_id} not found in faces table")
                    return jsonify({"error": f"Student with ID {student_id} not found in face records"}), 404
                return jsonify({"error": "Student account is not linked to a face record"}), 409

        if is_pg:
            c.execute("""
                INSERT INTO leave_requests 
                (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time))
        else:
            c.execute("""
                INSERT INTO leave_requests 
                (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time))
        
        conn.commit()
        request_id = c.lastrowid
        return jsonify({"status": "success", "request_id": request_id})
    except Exception as e:
        if is_pg: conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/parent/pending", methods=["GET"])
def get_parent_pending_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        parent = _authenticated_parent(c, vendor_id)
        if not parent:
            return jsonify({"error": "Parent access required"}), 403

        requested_student = request.args.get("student_number")
        if requested_student and requested_student.strip().lower() != str(parent["student_number"]).strip().lower():
            return jsonify({"error": "This parent account is not linked to that student"}), 403

        student_id = parent.get("selected_person_id")
        if student_id is None:
            # Compatibility for old parent rows created before selected_person_id.
            if is_pg:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s", (vendor_id, parent["student_number"]))
            else:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ?", (vendor_id, parent["student_number"]))
            row = c.fetchone()
            student_id = row[0] if row else None
        if student_id is None:
            return jsonify({"requests": []})

        # Parents only receive the request after Rector and HOD approval.
        if is_pg:
            c.execute("""SELECT * FROM leave_requests
                         WHERE student_id = %s AND vendor_id = %s
                           AND rector_status = 'approved' AND hod_status = 'approved'
                           AND parent_status = 'pending' AND final_status = 'pending'
                         ORDER BY created_at DESC""", (student_id, vendor_id))
        else:
            c.execute("""SELECT * FROM leave_requests
                         WHERE student_id = ? AND vendor_id = ?
                           AND rector_status = 'approved' AND hod_status = 'approved'
                           AND parent_status = 'pending' AND final_status = 'pending'
                         ORDER BY created_at DESC""", (student_id, vendor_id))
        
        rows = c.fetchall()
        return jsonify({"requests": [get_row_dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/parent/register-face", methods=["POST"])
def parent_register_face():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json
    student_number = data.get("student_number")
    face_image = data.get("face_image")
    face_template = data.get("face_template")  # Versioned Base64 from the Android local engine
    
    if not student_number or not face_image:
        return jsonify({"error": "student_number and face_image required"}), 400

    conn = get_db_connection()
    c = conn.cursor()

    parent = _authenticated_parent(c, vendor_id)
    if not parent:
        conn.close()
        return jsonify({"error": "Parent access required"}), 403
    if student_number.strip().lower() != str(parent["student_number"]).strip().lower():
        conn.close()
        return jsonify({"error": "This parent account is not linked to that student"}), 403
    
    # 1. Unique Registration Rule: Check if this face already exists as a student/employee
    if face_template:
        try:
            new_emb, new_family = _decode_face_template(face_template)
            
            # Get all faces for this vendor to compare
            c.execute("SELECT id, templates, name FROM faces WHERE vendor_id = ?", (vendor_id,))
            rows = c.fetchall()
            
            for row in rows:
                r = get_row_dict(row)
                if not r.get('templates'): continue
                try:
                    stored_emb, stored_family = _decode_face_template(r['templates'])
                except (ValueError, TypeError):
                    continue
                # Embeddings from different recognition models are incomparable.
                if stored_family != new_family:
                    continue
                similarity = float(np.dot(new_emb, stored_emb))
                
                if similarity > 0.62:
                    conn.close()
                    return jsonify({"error": f"Violation: Face already registered as student '{r['name']}'"}), 409
        except Exception as e:
            print(f"Error in unique check: {e}")

    # 2. Proceed with registration
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if face_template:
            if is_pg:
                c.execute("UPDATE parent_users SET face_image = %s, face_template = %s WHERE id = %s AND vendor_id = %s",
                          (face_image, face_template, parent["id"], vendor_id))
            else:
                c.execute("UPDATE parent_users SET face_image = ?, face_template = ? WHERE id = ? AND vendor_id = ?",
                          (face_image, face_template, parent["id"], vendor_id))
            
            if c.rowcount == 0:
                conn.close()
                return jsonify({"status": "error", "error": "Parent record not found for this student. Please ensure you are using the correct student ID."}), 404
            
            conn.commit()
            conn.close()
            return jsonify({"status": "success"})

        # Fallback to backend processing (e.g. for web portals registering parents)
        from tasks import detect_faces_task
        data_part = face_image.split(",")[-1] if "," in face_image else face_image
        try:
            result = detect_faces_task.apply_async(args=[data_part, {"fast": True}, vendor_id]).get(timeout=60)
            faces = result.get("faces", [])
            if not faces:
                 conn.close()
                 return jsonify({"error": "No face detected"}), 400
            
            face_template = faces[0].get("emb_vec", "")
            if not face_template:
                 conn.close()
                 return jsonify({"error": "No embedding generated"}), 400
        except Exception as e:
            conn.close()
            return jsonify({"error": f"Inference failed or timed out: {str(e)}"}), 500

        if is_pg:
            c.execute("UPDATE parent_users SET face_image = %s, face_template = %s WHERE id = %s AND vendor_id = %s",
                      (face_image, face_template, parent["id"], vendor_id))
        else:
            c.execute("UPDATE parent_users SET face_image = ?, face_template = ? WHERE id = ? AND vendor_id = ?",
                      (face_image, face_template, parent["id"], vendor_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        if conn: conn.close()
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
    local_verified = data.get("local_verified", False)
    
    if not all([request_id, student_number, action]):
        return jsonify({"error": "Missing fields"}), 400
    if action not in ALLOWED_LEAVE_ACTIONS:
        return jsonify({"error": "Action must be approved or rejected"}), 400
    if not captured_face:
        return jsonify({"error": "Missing captured_face"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        parent = _authenticated_parent(c, vendor_id)
        if not parent:
            return jsonify({"error": "Parent access required"}), 403
        if student_number.strip().lower() != str(parent["student_number"]).strip().lower():
            return jsonify({"error": "This parent account is not linked to that student"}), 403
        student_id = parent.get("selected_person_id")
        if student_id is None:
            return jsonify({"error": "Parent account is not linked to a student record"}), 409

        if is_pg:
            c.execute("""SELECT id FROM leave_requests
                         WHERE id = %s AND vendor_id = %s AND student_id = %s
                           AND rector_status = 'approved' AND hod_status = 'approved'
                           AND parent_status = 'pending' AND final_status = 'pending'""",
                      (request_id, vendor_id, student_id))
        else:
            c.execute("""SELECT id FROM leave_requests
                         WHERE id = ? AND vendor_id = ? AND student_id = ?
                           AND rector_status = 'approved' AND hod_status = 'approved'
                           AND parent_status = 'pending' AND final_status = 'pending'""",
                      (request_id, vendor_id, student_id))
        if not c.fetchone():
            return jsonify({"error": "Leave request is not awaiting this parent's decision"}), 409

        # The FaceIDApp engine performs multi-frame liveness and face matching
        # before setting this flag; the API still requires the capture payload.
        if local_verified:
             if is_pg:
                 c.execute("""UPDATE leave_requests SET parent_status = %s, final_status = %s
                              WHERE id = %s AND vendor_id = %s AND student_id = %s
                                AND rector_status = 'approved' AND hod_status = 'approved'
                                AND parent_status = 'pending' AND final_status = 'pending'""",
                           (action, action, request_id, vendor_id, student_id))
             else:
                 c.execute("""UPDATE leave_requests SET parent_status = ?, final_status = ?
                              WHERE id = ? AND vendor_id = ? AND student_id = ?
                                AND rector_status = 'approved' AND hod_status = 'approved'
                                AND parent_status = 'pending' AND final_status = 'pending'""",
                           (action, action, request_id, vendor_id, student_id))
             if c.rowcount == 0:
                 return jsonify({"error": "Leave request is no longer awaiting the parent's decision"}), 409
             conn.commit()
             return jsonify({"status": "success", "similarity": 1.0})

        if not parent or not parent.get('face_template'):
            return jsonify({"error": "Parent face not registered"}), 400
        
        from tasks import detect_faces_task
        data_part = captured_face.split(",")[-1] if "," in captured_face else captured_face
        try:
            result = detect_faces_task.apply_async(args=[data_part, {"fast": True}, vendor_id]).get(timeout=60)
            faces = result.get("faces", [])
            if not faces:
                return jsonify({"error": "No face detected in captured image"}), 400
            
            emb_vec_b64 = faces[0].get("emb_vec", "")
            if not emb_vec_b64:
                return jsonify({"error": "Failed to extract embeddings"}), 500
                
            emb, live_family = _decode_face_template(emb_vec_b64)
            stored_template, stored_family = _decode_face_template(parent['face_template'])
            if live_family != stored_family:
                return jsonify({
                    "error": "Registered and captured faces use different recognition models; re-register on this device"
                }), 409
            similarity = float(np.dot(emb, stored_template))
        except Exception as e:
            return jsonify({"error": f"Inference failed or timed out: {str(e)}"}), 500
        
        if similarity < 0.6:
             return jsonify({"error": "Face verification failed", "similarity": similarity}), 401

        if is_pg:
            c.execute("""UPDATE leave_requests SET parent_status = %s, final_status = %s
                         WHERE id = %s AND vendor_id = %s AND student_id = %s
                           AND rector_status = 'approved' AND hod_status = 'approved'
                           AND parent_status = 'pending' AND final_status = 'pending'""",
                      (action, action, request_id, vendor_id, student_id))
        else:
            c.execute("""UPDATE leave_requests SET parent_status = ?, final_status = ?
                         WHERE id = ? AND vendor_id = ? AND student_id = ?
                           AND rector_status = 'approved' AND hod_status = 'approved'
                           AND parent_status = 'pending' AND final_status = 'pending'""",
                      (action, action, request_id, vendor_id, student_id))
        if c.rowcount == 0:
            return jsonify({"error": "Leave request is no longer awaiting the parent's decision"}), 409
        conn.commit()
        return jsonify({"status": "success", "similarity": similarity})
    finally:
        conn.close()

@leave_bp.route("/admin/tracking", methods=["GET"])
@require_feature("leave_management")
def get_leave_tracking():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    role = request.args.get("role", "rector")
    if role not in {"rector", "hod"}:
        return jsonify({"error": "Invalid role"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    if not staff:
        return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        today = datetime.now().date()
        
        # Base query for approved leaves
        query = """
            SELECT lr.*, f.name as student_name, f.department as student_dept
            FROM leave_requests lr
            JOIN faces f ON lr.student_id = f.id
            WHERE lr.vendor_id = ? AND lr.final_status = 'approved'
            AND (lr.end_date >= ? OR lr.end_date < ?) -- Show upcoming and past due
        """
        params = [vendor_id, today - timedelta(days=1), today]
        
        if role == 'hod' and dept:
            if is_pg:
                query += """ AND (
                    LOWER(TRIM(f.department)) = LOWER(TRIM(%s)) OR
                    LOWER(TRIM(f.custom_data::jsonb->>'department')) = LOWER(TRIM(%s))
                )"""
            else:
                query += """ AND (
                    LOWER(TRIM(f.department)) = LOWER(TRIM(?)) OR
                    LOWER(TRIM(json_extract(f.custom_data, '$.department'))) = LOWER(TRIM(?))
                )"""
            params.extend([dept, dept])

        if is_pg:
            query = query.replace('?', '%s')
            
        c.execute(query, tuple(params))
        requests = [get_row_dict(r) for r in c.fetchall()]
        
        tracking_data = []
        for req in requests:
            student_id = req['student_id']
            end_date = req['end_date']
            if isinstance(end_date, str):
                from utils import parse_db_date
                end_date = parse_db_date(end_date)
            
            # Check if student has arrived since leave started
            # We look for any attendance record after start_date
            start_date = req['start_date']
            if isinstance(start_date, str):
                from utils import parse_db_date
                start_date = parse_db_date(start_date)

            if is_pg:
                c.execute("SELECT timestamp FROM attendance WHERE person_id = %s AND timestamp >= %s ORDER BY timestamp ASC LIMIT 1", 
                          (student_id, start_date))
            else:
                c.execute("SELECT timestamp FROM attendance WHERE person_id = ? AND timestamp >= ? ORDER BY timestamp ASC LIMIT 1", 
                          (student_id, start_date))
            
            arrival = c.fetchone()
            has_arrived = arrival is not None
            
            status_text = "On Leave"
            status_color = "blue"
            
            if has_arrived:
                status_text = "Arrived"
                status_color = "green"
            else:
                diff = (end_date - today).days
                if diff == 0:
                    status_text = "Will Arrive Today"
                    status_color = "orange"
                elif diff == 1:
                    status_text = "Will Arrive Tomorrow"
                    status_color = "blue"
                elif diff < 0:
                    status_text = "Has Not Arrived"
                    status_color = "red"
            
            req['tracking_status'] = status_text
            req['tracking_color'] = status_color
            req['arrival_time'] = get_row_dict(arrival)['timestamp'] if has_arrived else None
            tracking_data.append(req)
            
        return jsonify({"tracking": tracking_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/pending", methods=["GET"])
@require_feature("leave_management")
def get_admin_pending_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    role = request.args.get("role", "rector")
    if role not in {"rector", "hod"}:
        return jsonify({"error": "Invalid role"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    if not staff:
        return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Admin pending fetch: role={role}, dept={dept}, vendor_id={vendor_id}")

        if role == 'rector':
            if is_pg:
                c.execute("""
                    SELECT lr.*, f.name as student_name 
                    FROM leave_requests lr
                    JOIN faces f ON lr.student_id = f.id
                    WHERE lr.vendor_id = %s AND lr.rector_status = 'pending' AND lr.final_status = 'pending'
                """, (vendor_id,))
            else:
                c.execute("""
                    SELECT lr.*, f.name as student_name 
                    FROM leave_requests lr
                    JOIN faces f ON lr.student_id = f.id
                    WHERE lr.vendor_id = ? AND lr.rector_status = 'pending' AND lr.final_status = 'pending'
                """, (vendor_id,))
        elif role == 'hod':
            if not dept:
                return jsonify({"error": "Department required for HOD"}), 400
            
            # Use case-insensitive and trimmed department matching, searching both column and custom_data
            if is_pg:
                c.execute("""
                    SELECT lr.*, f.name as student_name 
                    FROM leave_requests lr
                    JOIN faces f ON lr.student_id = f.id
                    WHERE lr.vendor_id = %s 
                    AND lr.rector_status = 'approved' 
                    AND lr.hod_status = 'pending'
                    AND lr.final_status = 'pending'
                    AND (
                        LOWER(TRIM(f.department)) = LOWER(TRIM(%s)) OR
                        LOWER(TRIM(f.custom_data::jsonb->>'department')) = LOWER(TRIM(%s))
                    )
                """, (vendor_id, dept, dept))
            else:
                c.execute("""
                    SELECT lr.*, f.name as student_name 
                    FROM leave_requests lr
                    JOIN faces f ON lr.student_id = f.id
                    WHERE lr.vendor_id = ? 
                    AND lr.rector_status = 'approved' 
                    AND lr.hod_status = 'pending'
                    AND lr.final_status = 'pending'
                    AND (
                        LOWER(TRIM(f.department)) = LOWER(TRIM(?)) OR
                        LOWER(TRIM(json_extract(f.custom_data, '$.department'))) = LOWER(TRIM(?))
                    )
                """, (vendor_id, dept, dept))
        else:
            return jsonify({"error": "Invalid role"}), 400
            
        rows = c.fetchall()
        return jsonify({"requests": [get_row_dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/history", methods=["GET"])
@require_feature("leave_management")
def get_admin_leave_history():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    role = request.args.get("role")
    status = request.args.get("status", "all")
    
    if not role:
        return jsonify({"error": "Role required"}), 400
    if role not in {"rector", "hod"}:
        return jsonify({"error": "Invalid role"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    if not staff:
        return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Admin leave history fetch: role={role}, dept={dept}, status={status}, vendor_id={vendor_id}")

        query = """
            SELECT lr.*, f.name as student_name 
            FROM leave_requests lr
            JOIN faces f ON lr.student_id = f.id
            WHERE lr.vendor_id = ?
        """
        params = [vendor_id]

        if role == 'hod':
            if not dept:
                return jsonify({"error": "Department required for HOD history"}), 400
            
            if is_pg:
                query += """ AND (
                    LOWER(TRIM(f.department)) = LOWER(TRIM(%s)) OR
                    LOWER(TRIM(f.custom_data::jsonb->>'department')) = LOWER(TRIM(%s))
                )"""
            else:
                query += """ AND (
                    LOWER(TRIM(f.department)) = LOWER(TRIM(?)) OR
                    LOWER(TRIM(json_extract(f.custom_data, '$.department'))) = LOWER(TRIM(?))
                )"""
            params.extend([dept, dept])
        elif role != 'rector':
            return jsonify({"error": "Invalid role"}), 400

        if status != "all":
            query += " AND lr.final_status = ?"
            params.append(status)
        
        # Invert parameters if Postgres
        if is_pg:
            query = query.replace('?', '%s')

        c.execute(query, tuple(params))
        rows = c.fetchall()
        return jsonify({"history": [get_row_dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/approve", methods=["POST"])
@require_feature("leave_management")
def admin_approve_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json
    request_id = data.get("request_id")
    role = data.get("role")
    action = data.get("action")
    
    if not all([request_id, role, action]):
        return jsonify({"error": "Missing fields"}), 400
    if role not in {"rector", "hod"}:
        return jsonify({"error": "Invalid role"}), 400
    if action not in ALLOWED_LEAVE_ACTIONS:
        return jsonify({"error": "Action must be approved or rejected"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    if not staff:
        return jsonify({"error": "A valid staff PIN session is required"}), 403

    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if role == 'hod':
            # HOD can only decide after Rector approval.
            if is_pg:
                c.execute("""SELECT lr.rector_status, lr.hod_status, lr.final_status
                             FROM leave_requests lr
                             JOIN faces f ON lr.student_id = f.id
                             WHERE lr.id = %s AND lr.vendor_id = %s
                               AND (
                                   LOWER(TRIM(f.department)) = LOWER(TRIM(%s)) OR
                                   LOWER(TRIM(f.custom_data::jsonb->>'department')) = LOWER(TRIM(%s))
                               )""", (request_id, vendor_id, staff.get("department"), staff.get("department")))
            else:
                c.execute("""SELECT lr.rector_status, lr.hod_status, lr.final_status
                             FROM leave_requests lr
                             JOIN faces f ON lr.student_id = f.id
                             WHERE lr.id = ? AND lr.vendor_id = ?
                               AND (
                                   LOWER(TRIM(f.department)) = LOWER(TRIM(?)) OR
                                   LOWER(TRIM(json_extract(f.custom_data, '$.department'))) = LOWER(TRIM(?))
                               )""", (request_id, vendor_id, staff.get("department"), staff.get("department")))
            res = c.fetchone()
            res_dict = get_row_dict(res) if res else None
            rector_status = res_dict.get('rector_status') if isinstance(res_dict, dict) else (res[0] if res else None)
            hod_status = res_dict.get('hod_status') if isinstance(res_dict, dict) else (res[1] if res else None)
            final_status = res_dict.get('final_status') if isinstance(res_dict, dict) else (res[2] if res else None)
            if rector_status != 'approved':
                return jsonify({"error": "Wait for Rector's approval first"}), 400
            if hod_status != 'pending' or final_status != 'pending':
                return jsonify({"error": "Leave request is no longer awaiting HOD approval"}), 409
            
            # Reset parent_status when HOD approves so legacy in-flight requests
            # from the old Parent -> Rector -> HOD order enter the new final queue.
            action_placeholder = "%s" if is_pg else "?"
            assignments = f"hod_status = {action_placeholder}"
            if action == 'approved':
                assignments += ", parent_status = 'pending'"
            if is_pg:
                c.execute(f"""UPDATE leave_requests SET {assignments}
                              WHERE id = %s AND vendor_id = %s
                                AND rector_status = 'approved' AND hod_status = 'pending'
                                AND final_status = 'pending'""",
                          (action, request_id, vendor_id))
            else:
                c.execute(f"""UPDATE leave_requests SET {assignments}
                              WHERE id = ? AND vendor_id = ?
                                AND rector_status = 'approved' AND hod_status = 'pending'
                                AND final_status = 'pending'""",
                          (action, request_id, vendor_id))
            if c.rowcount == 0:
                return jsonify({"error": "Leave request is no longer awaiting HOD approval"}), 409
                
        else:
            # Rector is the first approver after student submission.
            column = "rector_status"
            if is_pg:
                c.execute(f"""UPDATE leave_requests SET {column} = %s
                              WHERE id = %s AND vendor_id = %s
                                AND rector_status = 'pending' AND final_status = 'pending'""",
                          (action, request_id, vendor_id))
            else:
                c.execute(f"""UPDATE leave_requests SET {column} = ?
                              WHERE id = ? AND vendor_id = ?
                                AND rector_status = 'pending' AND final_status = 'pending'""",
                          (action, request_id, vendor_id))
            if c.rowcount == 0:
                return jsonify({"error": "Leave request is no longer awaiting Rector approval"}), 409
            
        if action == 'rejected':
            if is_pg:
                c.execute("UPDATE leave_requests SET final_status = 'rejected' WHERE id = %s AND vendor_id = %s", (request_id, vendor_id))
            else:
                c.execute("UPDATE leave_requests SET final_status = 'rejected' WHERE id = ? AND vendor_id = ?", (request_id, vendor_id))
            
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        if is_pg: conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/generate-logins", methods=["POST"])
@require_feature("leave_management")
def generate_student_logins():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        # Get all faces for this vendor
        if is_pg:
            c.execute("SELECT id, name, phone, custom_data FROM faces WHERE vendor_id = %s", (vendor_id,))
        else:
            c.execute("SELECT id, name, phone, custom_data FROM faces WHERE vendor_id = ?", (vendor_id,))
        faces = c.fetchall()
        
        created_count = 0
        skipped_count = 0
        
        for f in faces:
            row = get_row_dict(f)
            cd = json.loads(row.get('custom_data') or '{}')
            student_number = str(cd.get('student_id') or cd.get('id_number') or "").strip()
            
            if not student_number:
                skipped_count += 1
                continue
                
            # Check if user already exists
            if is_pg:
                c.execute("SELECT username FROM system_users WHERE username = %s", (student_number,))
            else:
                c.execute("SELECT username FROM system_users WHERE username = ?", (student_number,))
            if c.fetchone():
                skipped_count += 1
                continue
                
            # Create system user
            # Default password is the student's phone number
            phone = row.get('phone') or ""
            if is_pg:
                c.execute(
                    "INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (%s, %s, NULL, 'user', %s, %s)",
                    (student_number, hash_password(phone), vendor_id, row.get('id'))
                )
            else:
                c.execute(
                    "INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (?, ?, NULL, 'user', ?, ?)",
                    (student_number, hash_password(phone), vendor_id, row.get('id'))
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
        if is_pg: conn.rollback()
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
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            c.execute("SELECT id, name, role, department FROM leave_staff WHERE vendor_id = %s AND pin = %s", (vendor_id, pin))
        else:
            c.execute("SELECT id, name, role, department FROM leave_staff WHERE vendor_id = ? AND pin = ?", (vendor_id, pin))
        staff = c.fetchone()
        if staff:
            res = get_row_dict(staff)
            if not isinstance(res, dict):
                res = {"id": staff[0], "name": staff[1], "role": staff[2], "department": staff[3]}
            res["access_token"] = generate_token_with_claims(
                f"leave_staff_{res['id']}",
                "leave_staff",
                {
                    "vendor_id": vendor_id,
                    "staff_id": res["id"],
                    "staff_role": res["role"],
                    "department": res.get("department"),
                },
                platform="web",
            )
            return jsonify({"status": "success", "staff": res})
        return jsonify({"error": "Invalid PIN"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/staff", methods=["GET", "POST", "DELETE"], strict_slashes=False)
def manage_staff():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if request.method == "GET":
            if is_pg:
                c.execute("SELECT id, name, role, pin, department FROM leave_staff WHERE vendor_id = %s", (vendor_id,))
            else:
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
                if is_pg:
                    c.execute("SELECT id FROM leave_staff WHERE vendor_id = %s AND LOWER(TRIM(department)) = LOWER(TRIM(%s)) AND role = 'hod'", (vendor_id, department))
                else:
                    c.execute("SELECT id FROM leave_staff WHERE vendor_id = ? AND LOWER(TRIM(department)) = LOWER(TRIM(?)) AND role = 'hod'", (vendor_id, department))
                if c.fetchone():
                    return jsonify({"error": f"An HOD is already assigned to {department}"}), 409

            # Check for duplicate PIN
            if is_pg:
                c.execute("SELECT id FROM leave_staff WHERE vendor_id = %s AND pin = %s", (vendor_id, pin))
            else:
                c.execute("SELECT id FROM leave_staff WHERE vendor_id = ? AND pin = ?", (vendor_id, pin))
            if c.fetchone():
                return jsonify({"error": "This PIN is already assigned to someone else"}), 409

            if is_pg:
                c.execute(
                    "INSERT INTO leave_staff (vendor_id, name, role, pin, department) VALUES (%s, %s, %s, %s, %s)",
                    (vendor_id, name, role, pin, department)
                )
            else:
                c.execute(
                    "INSERT INTO leave_staff (vendor_id, name, role, pin, department) VALUES (?, ?, ?, ?, ?)",
                    (vendor_id, name, role, pin, department)
                )
            conn.commit()
            return jsonify({"status": "success", "message": "Staff added successfully"})
            
        elif request.method == "DELETE":
            staff_id = request.args.get("id")
            if is_pg:
                c.execute("DELETE FROM leave_staff WHERE id = %s AND vendor_id = %s", (staff_id, vendor_id))
            else:
                c.execute("DELETE FROM leave_staff WHERE id = ? AND vendor_id = ?", (staff_id, vendor_id))
            conn.commit()
            return jsonify({"status": "success"})
    finally:
        conn.close()

@leave_bp.route("/admin/departments", methods=["GET", "POST", "DELETE"], strict_slashes=False)
def manage_departments():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if request.method == "GET":
            if is_pg:
                c.execute("SELECT departments FROM vendors WHERE id = %s", (vendor_id,))
            else:
                c.execute("SELECT departments FROM vendors WHERE id = ?", (vendor_id,))
            res = c.fetchone()
            depts = json.loads(res[0] or '[]') if res and res[0] else []
            return jsonify({"departments": depts})
            
        elif request.method == "POST":
            dept_name = request.json.get("name")
            if not dept_name: return jsonify({"error": "Name required"}), 400
            
            if is_pg:
                c.execute("SELECT departments FROM vendors WHERE id = %s", (vendor_id,))
            else:
                c.execute("SELECT departments FROM vendors WHERE id = ?", (vendor_id,))
            res = c.fetchone()
            depts = json.loads(res[0] or '[]') if res and res[0] else []
            
            if dept_name in depts:
                return jsonify({"error": "Department already exists"}), 409
                
            depts.append(dept_name)
            if is_pg:
                c.execute("UPDATE vendors SET departments = %s WHERE id = %s", (json.dumps(depts), vendor_id))
            else:
                c.execute("UPDATE vendors SET departments = ? WHERE id = ?", (json.dumps(depts), vendor_id))
            conn.commit()
            return jsonify({"status": "success", "departments": depts})
            
        elif request.method == "DELETE":
            dept_name = request.args.get("name")
            if is_pg:
                c.execute("SELECT departments FROM vendors WHERE id = %s", (vendor_id,))
            else:
                c.execute("SELECT departments FROM vendors WHERE id = ?", (vendor_id,))
            res = c.fetchone()
            depts = json.loads(res[0] or '[]') if res and res[0] else []
            
            if dept_name in depts:
                depts.remove(dept_name)
                if is_pg:
                    c.execute("UPDATE vendors SET departments = %s WHERE id = %s", (json.dumps(depts), vendor_id))
                    # Also clean up staff associated with this department
                    c.execute("DELETE FROM leave_staff WHERE vendor_id = %s AND department = %s", (vendor_id, dept_name))
                else:
                    c.execute("UPDATE vendors SET departments = ? WHERE id = ?", (json.dumps(depts), vendor_id))
                    # Also clean up staff associated with this department
                    c.execute("DELETE FROM leave_staff WHERE vendor_id = ? AND department = ?", (vendor_id, dept_name))
                conn.commit()
            return jsonify({"status": "success", "departments": depts})
    finally:
        conn.close()

@leave_bp.route("/student/change-password", methods=["POST"])
def student_change_password():
    # Students and faculty on first login call this to set their own password
    auth_header = request.headers.get("Authorization")
    if not auth_header: return jsonify({"error": "Missing token"}), 401
    token = auth_header.split(" ")[1]
    user_data = verify_token(token)
    if not user_data or user_data['role'] not in ['user', 'faculty']:
        return jsonify({"error": "Student or faculty access required"}), 403
        
    data = request.json
    new_password = data.get("password")
    if not new_password: return jsonify({"error": "Password required"}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE system_users SET password = ?, password_plain = NULL, has_set_password = 1 WHERE username = ?",
            (hash_password(new_password), user_data['username'])
        )
        conn.commit()
        return jsonify({"status": "success", "message": "Password updated successfully"})
    finally:
        conn.close()

@leave_bp.route('/admin/vendors/<int:vendor_id>/student-logins', methods=['GET'])
@require_auth(roles=['super_admin'])
def get_vendor_student_logins(vendor_id):
    # This is for SuperAdmin to see student passwords
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            # PostgreSQL uses ->> operator for JSONB
            c.execute("""
                SELECT u.username, u.last_active_at, f.name, u.has_set_password
                FROM system_users u
                LEFT JOIN faces f ON (
                    LOWER(TRIM(f.custom_data::jsonb->>'student_id')) = LOWER(TRIM(u.username)) OR
                    LOWER(TRIM(f.custom_data::jsonb->>'id_number')) = LOWER(TRIM(u.username))
                ) AND f.vendor_id = u.vendor_id
                WHERE u.vendor_id = %s AND u.role = 'user'
            """, (vendor_id,))
        else:
            # SQLite uses json_extract
            c.execute("""
                SELECT u.username, u.last_active_at, f.name, u.has_set_password
                FROM system_users u
                LEFT JOIN faces f ON (
                    LOWER(TRIM(json_extract(f.custom_data, '$.student_id'))) = LOWER(TRIM(u.username)) OR
                    LOWER(TRIM(json_extract(f.custom_data, '$.id_number'))) = LOWER(TRIM(u.username))
                ) AND f.vendor_id = u.vendor_id
                WHERE u.vendor_id = ? AND u.role = 'user'
            """, (vendor_id,))
            
        rows = c.fetchall()
        logins = []
        for row in rows:
            r = get_row_dict(row)
            logins.append({
                "username": r.get('username'),
                "last_login": r.get('last_active_at'),
                "full_name": r.get('name') or "Unknown Student",
                "status": "CHANGED" if r.get('has_set_password') == 1 else "DEFAULT"
            })
            
        return jsonify({"status": "success", "logins": logins})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route('/admin/vendors/<int:vendor_id>/faculty-logins', methods=['GET'])
@require_auth(roles=['super_admin'])
def get_vendor_faculty_logins(vendor_id):
    """SuperAdmin endpoint to view faculty credentials for a vendor."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT username, last_active_at, has_set_password
            FROM system_users
            WHERE vendor_id = ? AND role = 'faculty'
            ORDER BY username ASC
        """, (vendor_id,))
        rows = c.fetchall()
        logins = []
        for row in rows:
            r = get_row_dict(row)
            logins.append({
                "username": r.get('username'),
                "last_login": r.get('last_active_at'),
                "status": "CHANGED" if r.get('has_set_password') == 1 else "DEFAULT"
            })
        return jsonify({"status": "success", "logins": logins})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@leave_bp.route('/admin/vendors/<int:vendor_id>/parents', methods=['GET'])
@require_auth(roles=['super_admin'])
def get_vendor_parents(vendor_id):
    # This is for SuperAdmin to see registered parents
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            # PostgreSQL uses ->> operator for JSONB
            c.execute("""
                SELECT p.id, p.username, p.student_number, p.contact_phone, p.face_image, p.created_at, f.name as student_name
                FROM parent_users p
                LEFT JOIN faces f ON (
                    LOWER(f.custom_data::jsonb->>'student_id') = LOWER(p.student_number) OR
                    LOWER(f.custom_data::jsonb->>'id_number') = LOWER(p.student_number)
                ) AND f.vendor_id = p.vendor_id
                WHERE p.vendor_id = %s AND p.face_image IS NOT NULL
            """, (vendor_id,))
        else:
            # SQLite uses json_extract
            c.execute("""
                SELECT p.id, p.username, p.student_number, p.contact_phone, p.face_image, p.created_at, f.name as student_name
                FROM parent_users p
                LEFT JOIN faces f ON (
                    LOWER(json_extract(f.custom_data, '$.student_id')) = LOWER(p.student_number) OR
                    LOWER(json_extract(f.custom_data, '$.id_number')) = LOWER(p.student_number)
                ) AND f.vendor_id = p.vendor_id
                WHERE p.vendor_id = ? AND p.face_image IS NOT NULL
            """, (vendor_id,))
        rows = c.fetchall()
        return jsonify({"status": "success", "parents": [get_row_dict(r) for r in rows]})
    except Exception as e:
        # Final fallback: just get parents without joining student names if anything else fails
        try:
            if is_pg:
                c.execute("SELECT * FROM parent_users WHERE vendor_id = %s AND face_image IS NOT NULL", (vendor_id,))
            else:
                c.execute("SELECT * FROM parent_users WHERE vendor_id = ? AND face_image IS NOT NULL", (vendor_id,))
            rows = c.fetchall()
            return jsonify({"status": "success", "parents": [get_row_dict(r) for r in rows]})
        except Exception as e2:
            return jsonify({"error": str(e2)}), 500
    finally:
        conn.close()

@leave_bp.route("/parent-faces", methods=["GET"])
def get_parent_faces():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            # Join with faces to get student name
            c.execute("""
                SELECT p.id, p.username, p.student_number, p.contact_phone, p.face_image, p.created_at, f.name as student_name
                FROM public.parent_users p
                LEFT JOIN faces f ON (f.custom_data::jsonb->>'student_id' = p.student_number OR f.custom_data::jsonb->>'id_number' = p.student_number) AND f.vendor_id = p.vendor_id
                WHERE p.vendor_id = %s AND p.face_image IS NOT NULL
            """, (vendor_id,))
        else:
            # Fallback for SQLite
            c.execute("""
                SELECT p.id, p.username, p.student_number, p.contact_phone, p.face_image, p.created_at, f.name as student_name
                FROM parent_users p
                LEFT JOIN faces f ON (json_extract(f.custom_data, '$.student_id') = p.student_number OR json_extract(f.custom_data, '$.id_number') = p.student_number) AND f.vendor_id = p.vendor_id
                WHERE p.vendor_id = ? AND p.face_image IS NOT NULL
            """, (vendor_id,))
        rows = c.fetchall()
        return jsonify({"parents": [get_row_dict(r) for r in rows]})
    except Exception as e:
        # Final fallback: just get parents without joining student names if anything else fails
        try:
            if is_pg:
                c.execute("SELECT * FROM parent_users WHERE vendor_id = %s AND face_image IS NOT NULL", (vendor_id,))
            else:
                c.execute("SELECT * FROM parent_users WHERE vendor_id = ? AND face_image IS NOT NULL", (vendor_id,))
            rows = c.fetchall()
            return jsonify({"parents": [get_row_dict(r) for r in rows]})
        except Exception as e2:
            return jsonify({"error": str(e2)}), 500
    finally:
        conn.close()

@leave_bp.route("/student/history", methods=["GET"])
def get_student_history():
    auth_header = request.headers.get("Authorization")
    if not auth_header: return jsonify({"error": "Missing token"}), 401
    token = auth_header.split(" ")[1]
    user_data = verify_token(token)
    if not user_data or user_data.get('role') not in ('user', 'student'):
        return jsonify({"error": "User access required"}), 403
    
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
                    id::text = %s OR
                    LOWER(TRIM(custom_data::jsonb->>'student_id')) = LOWER(TRIM(%s)) OR
                    LOWER(TRIM(custom_data::jsonb->>'id_number')) = LOWER(TRIM(%s)) OR
                    LOWER(TRIM(custom_data::jsonb->>'employee_id')) = LOWER(TRIM(%s))
                )
            """, (vendor_id, student_number, student_number, student_number, student_number))
        else:
            c.execute("""
                SELECT id FROM faces 
                WHERE vendor_id = ? AND (
                    CAST(id AS TEXT) = ? OR
                    LOWER(TRIM(json_extract(custom_data, '$.student_id'))) = LOWER(TRIM(?)) OR
                    LOWER(TRIM(json_extract(custom_data, '$.id_number'))) = LOWER(TRIM(?)) OR
                    LOWER(TRIM(json_extract(custom_data, '$.employee_id'))) = LOWER(TRIM(?))
                )
            """, (vendor_id, student_number, student_number, student_number, student_number))
        
        face_row = c.fetchone()
        
        # --- Robust Fallback: Check system_users table ---
        if not face_row:
            logger.info(f"Student history faces lookup failed for {student_number}, trying system_users fallback...")
            if is_pg:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s AND person_id IS NOT NULL", (vendor_id, student_number))
            else:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ? AND person_id IS NOT NULL", (vendor_id, student_number))
            face_row = c.fetchone()
        if not face_row:
            logger.error(f"Student history fetch failed: student_number={student_number} not found in faces table")
            return jsonify({"requests": []})
        
        # If row is a dict (Postgres DictRow or similar), use key 'id'
        if hasattr(face_row, 'keys') and 'id' in face_row.keys():
            person_id = face_row['id']
        else:
            person_id = face_row[0]
        
        logger.info(f"Resolved history student_number={student_number} to person_id={person_id}")
        
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
