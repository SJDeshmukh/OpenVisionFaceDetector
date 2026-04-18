from flask import Blueprint, request, jsonify
from datetime import datetime
import json
import sqlite3
import logging
from db_factory import get_db_connection
from services.auth_service import authenticate_vendor_access, verify_token, extract_token

logger = logging.getLogger(__name__)
parent_reset_bp = Blueprint('parent_reset_bp', __name__)

@parent_reset_bp.route("/parents/face-reset-request", methods=["POST"])
def request_face_reset():
    auth_header = request.headers.get('Authorization')
    token = extract_token(auth_header)
    data = verify_token(token)
    
    if not data or data.get('role') != 'parent':
        return jsonify({"error": "Unauthorized: Parent access required"}), 401
    
    req_data = request.json or {}
    reason = req_data.get("reason", "")
    vendor_id = data.get('vendor_id')
    student_number = data.get('student_number')
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Find parent_id
        c.execute("SELECT id FROM parent_users WHERE vendor_id = ? AND student_number = ?", (vendor_id, student_number))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Parent record not found"}), 404
        
        parent_id = row[0]
        
        # Check if a pending request already exists
        c.execute("SELECT id FROM face_reset_requests WHERE parent_id = ? AND status = 'pending'", (parent_id,))
        if c.fetchone():
            return jsonify({"error": "A reset request is already pending approval"}), 400
            
        c.execute(
            "INSERT INTO face_reset_requests (vendor_id, parent_id, reason, status) VALUES (?, ?, ?, 'pending')",
            (vendor_id, parent_id, reason)
        )
        conn.commit()
        return jsonify({"status": "success", "message": "Face reset request submitted to admin"})
    except Exception as e:
        logger.error(f"Error submitting face reset request: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@parent_reset_bp.route("/admin/face-reset-requests", methods=["GET"])
def list_face_reset_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    try:
        if not getattr(conn, "_is_pg", False):
            conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        query = """
            SELECT fr.*, pu.username as parent_username, pu.student_number 
            FROM face_reset_requests fr
            JOIN parent_users pu ON fr.parent_id = pu.id
            WHERE fr.vendor_id = ? AND fr.status = 'pending'
            ORDER BY fr.created_at DESC
        """
        c.execute(query, (vendor_id,))
        rows = c.fetchall()
        
        requests = []
        for r in rows:
            requests.append(dict(r))
            
        return jsonify({"status": "success", "requests": requests})
    except Exception as e:
        logger.error(f"Error fetching face reset requests: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@parent_reset_bp.route("/admin/handle-face-reset", methods=["POST"])
def handle_face_reset():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    data = request.json or {}
    request_id = data.get("request_id")
    action = data.get("action") # 'approved' or 'rejected'
    
    if not request_id or action not in ['approved', 'rejected']:
        return jsonify({"error": "Invalid request parameters"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Get request details
        c.execute("SELECT parent_id FROM face_reset_requests WHERE id = ? AND vendor_id = ?", (request_id, vendor_id))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Request not found"}), 404
            
        parent_id = row[0]
        
        if action == 'approved':
            # 1. Clear parent face data
            c.execute(
                "UPDATE parent_users SET face_image = NULL, face_template = NULL WHERE id = ?",
                (parent_id,)
            )
            # 2. Update request status
            c.execute("UPDATE face_reset_requests SET status = 'approved' WHERE id = ?", (request_id,))
            conn.commit()
            return jsonify({"status": "success", "message": "Parent face reset approved. They can now register a new face."})
        else:
            # Reject request
            c.execute("UPDATE face_reset_requests SET status = 'rejected' WHERE id = ?", (request_id,))
            conn.commit()
            return jsonify({"status": "success", "message": "Reset request rejected"})
            
    except Exception as e:
        logger.error(f"Error handling face reset: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
