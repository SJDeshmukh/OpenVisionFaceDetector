from flask import Blueprint, request, jsonify
from datetime import datetime
from services.auth_service import authenticate_vendor_access, verify_token, extract_token
import json
import logging
from db_factory import get_table_columns

logger = logging.getLogger(__name__)
owner_bp = Blueprint('owner_bp', __name__)

def get_db_connection():
    from app import get_db_connection as _get_db
    return _get_db()

@owner_bp.route("/owner/advances", methods=["GET"])
def get_owner_advances():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    status = request.args.get('status', 'pending')
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        if status == 'all':
            query = """
                SELECT a.*, f.name as employee_name, f.display_id
                FROM advances a
                JOIN faces f ON a.person_id = f.id
                WHERE a.vendor_id = ?
                ORDER BY a.created_at DESC
            """
            c.execute(query, (vendor_id,))
        else:
            query = """
                SELECT a.*, f.name as employee_name, f.display_id
                FROM advances a
                JOIN faces f ON a.person_id = f.id
                WHERE a.vendor_id = ? AND a.status = ?
                ORDER BY a.created_at DESC
            """
            c.execute(query, (vendor_id, status))
        
        rows = c.fetchall()
        advances = []
        for r in rows:
            d = dict(r)
            advances.append(d)
        
        return jsonify({"status": "success", "advances": advances})
    except Exception as e:
        logger.error(f"Error fetching owner advances: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@owner_bp.route("/owner/advances/approve", methods=["POST"])
def approve_advance():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    auth_header = request.headers.get('Authorization')
    token_str = extract_token(auth_header)
    token_data = verify_token(token_str)
    if not token_data or token_data.get('role') != 'owner':
        return jsonify({"error": "Only owners can approve advances"}), 403
    
    owner_username = token_data.get('username')
    data = request.json
    advance_id = data.get('advance_id')
    
    if not advance_id:
        return jsonify({"error": "advance_id is required"}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Verify ownership and status
        c.execute("SELECT status FROM advances WHERE id = ? AND vendor_id = ?", (advance_id, vendor_id))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Advance request not found"}), 404
        
        if row['status'] != 'pending':
            return jsonify({"error": f"Advance is already {row['status']}"}), 400
        
        c.execute("""
            UPDATE advances 
            SET status = 'approved', approved_by = ?, approved_at = ?
            WHERE id = ? AND vendor_id = ?
        """, (owner_username, datetime.now(), advance_id, vendor_id))
        conn.commit()
        
        return jsonify({"status": "success", "message": "Advance approved"})
    except Exception as e:
        logger.error(f"Error approving advance: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@owner_bp.route("/owner/advances/reject", methods=["POST"])
def reject_advance():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    auth_header = request.headers.get('Authorization')
    token_str = extract_token(auth_header)
    token_data = verify_token(token_str)
    if not token_data or token_data.get('role') != 'owner':
        return jsonify({"error": "Only owners can reject advances"}), 403
    
    owner_username = token_data.get('username')
    data = request.json
    advance_id = data.get('advance_id')
    reason = data.get('reason', '')
    
    if not advance_id:
        return jsonify({"error": "advance_id is required"}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT status FROM advances WHERE id = ? AND vendor_id = ?", (advance_id, vendor_id))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Advance request not found"}), 404
        
        if row['status'] != 'pending':
            return jsonify({"error": f"Advance is already {row['status']}"}), 400
        
        c.execute("""
            UPDATE advances 
            SET status = 'rejected', approved_by = ?, approved_at = ?, rejection_reason = ?
            WHERE id = ? AND vendor_id = ?
        """, (owner_username, datetime.now(), reason, advance_id, vendor_id))
        conn.commit()
        
        return jsonify({"status": "success", "message": "Advance rejected"})
    except Exception as e:
        logger.error(f"Error rejecting advance: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@owner_bp.route("/owner/insights", methods=["GET"])
def get_owner_insights():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Total Employees
        c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (vendor_id,))
        total_employees = c.fetchone()[0]
        
        # Pending Advances
        c.execute("SELECT COUNT(*), SUM(amount) FROM advances WHERE vendor_id = ? AND status = 'pending'", (vendor_id,))
        pending_row = c.fetchone()
        pending_advances_count = pending_row[0] or 0
        pending_advances_amount = pending_row[1] or 0
        
        # Approved Advances (This Month)
        current_month = datetime.now().strftime('%Y-%m')
        c.execute("SELECT COUNT(*), SUM(amount) FROM advances WHERE vendor_id = ? AND status = 'approved' AND date LIKE ?", (vendor_id, f"{current_month}%"))
        approved_row = c.fetchone()
        approved_advances_count = approved_row[0] or 0
        approved_advances_amount = approved_row[1] or 0
        
        # Attendance Summary (Today)
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(DISTINCT person_id) FROM attendance WHERE vendor_id = ? AND timestamp LIKE ?", (vendor_id, f"{today}%"))
        present_today = c.fetchone()[0] or 0
        
        return jsonify({
            "status": "success",
            "insights": {
                "total_employees": total_employees,
                "present_today": present_today,
                "pending_advances_count": pending_advances_count,
                "pending_advances_amount": pending_advances_amount,
                "approved_advances_this_month_count": approved_advances_count,
                "approved_advances_this_month_amount": approved_advances_amount
            }
        })
    except Exception as e:
        logger.error(f"Error fetching owner insights: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
