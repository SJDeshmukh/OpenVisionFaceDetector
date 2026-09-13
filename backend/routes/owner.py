from flask import Blueprint, request, jsonify, g
from datetime import datetime
from services.auth_service import require_auth
import json
import logging

logger = logging.getLogger(__name__)
owner_bp = Blueprint('owner_bp', __name__)

def get_db_connection():
    from app import get_db_connection as _get_db
    return _get_db()

@owner_bp.route("/owner/advances", methods=["GET"])
@require_auth(roles=["owner"])
def get_owner_advances():
    vendor_id = g.vendor_id
    status = request.args.get('status', 'pending')
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        if status == 'all':
            query = """
                SELECT a.*, f.name as employee_name, f.display_id
                FROM advances a
                JOIN faces f ON a.person_id = f.id AND a.vendor_id = f.vendor_id
                WHERE a.vendor_id = ?
                ORDER BY a.created_at DESC
            """
            c.execute(query, (vendor_id,))
        else:
            query = """
                SELECT a.*, f.name as employee_name, f.display_id
                FROM advances a
                JOIN faces f ON a.person_id = f.id AND a.vendor_id = f.vendor_id
                WHERE a.vendor_id = ? AND a.status = ?
                ORDER BY a.created_at DESC
            """
            c.execute(query, (vendor_id, status))
        
        rows = c.fetchall()
        advances = []
        for r in rows:
            d = dict(r)
            d['name'] = d.get('employee_name')
            advances.append(d)
        
        return jsonify({"status": "success", "advances": advances})
    except Exception as e:
        logger.error(f"Error fetching owner advances: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@owner_bp.route("/owner/advances/approve", methods=["POST"])
@require_auth(roles=["owner"])
def approve_advance():
    vendor_id = g.vendor_id
    owner_username = g.username
    data = request.get_json(silent=True) or {}
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
            WHERE id = ? AND vendor_id = ? AND status = 'pending'
        """, (owner_username, datetime.now(), advance_id, vendor_id))
        if c.rowcount != 1:
            conn.rollback()
            return jsonify({"error": "Advance is no longer pending"}), 409
        conn.commit()
        from services.employee_email_reports_service import queue_advance_notification
        email_queued = queue_advance_notification(advance_id, "approved")
        try:
            from services.evolution_whatsapp_service import notify_advance_event_async
            notify_advance_event_async(vendor_id, advance_id, "approved")
        except Exception:
            pass
        
        return jsonify({"status": "success", "message": "Advance approved", "email_queued": email_queued})
    except Exception as e:
        logger.error(f"Error approving advance: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@owner_bp.route("/owner/advances/reject", methods=["POST"])
@require_auth(roles=["owner"])
def reject_advance():
    vendor_id = g.vendor_id
    owner_username = g.username
    data = request.get_json(silent=True) or {}
    advance_id = data.get('advance_id')
    reason = data.get('reason', data.get('rejection_reason', ''))
    
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
            WHERE id = ? AND vendor_id = ? AND status = 'pending'
        """, (owner_username, datetime.now(), reason, advance_id, vendor_id))
        if c.rowcount != 1:
            conn.rollback()
            return jsonify({"error": "Advance is no longer pending"}), 409
        conn.commit()
        from services.employee_email_reports_service import queue_advance_notification
        email_queued = queue_advance_notification(advance_id, "rejected")
        try:
            from services.evolution_whatsapp_service import notify_advance_event_async
            notify_advance_event_async(vendor_id, advance_id, "rejected")
        except Exception:
            pass
        
        return jsonify({"status": "success", "message": "Advance rejected", "email_queued": email_queued})
    except Exception as e:
        logger.error(f"Error rejecting advance: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@owner_bp.route("/owner/insights", methods=["GET"])
@require_auth(roles=["owner"])
def get_owner_insights():
    vendor_id = g.vendor_id
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
        c.execute("SELECT COUNT(*), SUM(amount) FROM advances WHERE vendor_id = ? AND status = 'approved' AND deduction_month = ?", (vendor_id, current_month))
        approved_row = c.fetchone()
        approved_advances_count = approved_row[0] or 0
        approved_advances_amount = approved_row[1] or 0
        
        # Attendance Summary (Today)
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(DISTINCT person_id) FROM attendance WHERE vendor_id = ? AND date(timestamp) = ?", (vendor_id, today))
        present_today = c.fetchone()[0] or 0

        active_shifts_count = 0
        c.execute("SELECT live_timetable FROM companies WHERE vendor_id = ? LIMIT 1", (vendor_id,))
        timetable_row = c.fetchone()
        if timetable_row and timetable_row[0]:
            try:
                timetable = json.loads(timetable_row[0]) if isinstance(timetable_row[0], str) else timetable_row[0]
                active_shifts_count = sum(1 for item in (timetable or []) if item.get('enabled', True))
            except (TypeError, ValueError, AttributeError):
                logger.warning("Could not parse owner timetable for vendor %s", vendor_id)

        c.execute("""
            SELECT a.status, a.amount, a.created_at, a.approved_at, f.name
            FROM advances a
            JOIN faces f ON f.id = a.person_id AND f.vendor_id = a.vendor_id
            WHERE a.vendor_id = ?
            ORDER BY COALESCE(a.approved_at, a.created_at) DESC
            LIMIT 8
        """, (vendor_id,))
        recent_activity = []
        for row in c.fetchall() or []:
            item = dict(row)
            state = str(item.get('status') or 'pending').title()
            recent_activity.append({
                "action": f"Advance {state}",
                "timestamp": item.get('approved_at') or item.get('created_at'),
                "details": f"{item.get('name') or 'Employee'} · ₹{float(item.get('amount') or 0):.2f}",
            })
        
        insights = {
            "total_employees": total_employees,
            "present_today": present_today,
            "pending_advances_count": pending_advances_count,
            "pending_advances_amount": pending_advances_amount,
            "approved_advances_this_month_count": approved_advances_count,
            "approved_advances_this_month_amount": approved_advances_amount,
            # Android owner dashboard compatibility: this is deliberately the
            # approved amount, never the still-pending claim amount.
            "total_advances_month": approved_advances_amount,
            "active_shifts_count": active_shifts_count,
        }
        return jsonify({
            "status": "success",
            "insights": insights,
            "stats": insights,
            "recent_activity": recent_activity,
        })
    except Exception as e:
        logger.error(f"Error fetching owner insights: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
