from flask import Blueprint, request, jsonify, g, Response
import os
import json
import base64
import numpy as np
from datetime import datetime, timedelta
from services.auth_service import authenticate_vendor_access, generate_token_with_claims, hash_password, verify_token, require_auth, login_email_from_profile
from services.face_service import _normalize_vec, _decode_data_uri_to_rgb
from services.mobile_face_template import decode_face_template as _decode_face_template
from services.leave_workflow_service import (
    attach_approval_steps,
    current_stage,
    decide_current_stage,
    get_active_workflow,
    replace_workflow,
    snapshot_request,
)
from services.staff_navigation_service import (
    load_staff_nav_items_for_features,
    normalize_staff_nav_items,
    serialize_staff_nav_items_for_features,
)
from utils import get_db_connection, log_audit, require_feature

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


def _vendor_subscription_features(cursor, vendor_id):
    cursor.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
    row = cursor.fetchone()
    if not row:
        return []
    if hasattr(row, "keys"):
        return row["features"]
    return row[0]


def _authenticated_parent(cursor, vendor_id):
    """Resolve the parent and linked student from the signed parent username."""
    if getattr(g, "user_role", None) != "parent" or not getattr(g, "username", None):
        return None
    cursor.execute(
        """SELECT id, student_number, selected_person_id, face_template, device_id,
                  face_image, face_server_template
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
        "device_id": row[4],
        "face_image": row[5],
        "face_server_template": row[6],
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
        c.execute("SELECT id, name, role, department, navbar_items FROM leave_staff WHERE id = ? AND vendor_id = ?", (data.get("staff_id"), vendor_id))
        row = c.fetchone()
        if not row:
            return None
        name = row["name"] if hasattr(row, "keys") else row[1]
        role = row["role"] if hasattr(row, "keys") else row[2]
        department = row["department"] if hasattr(row, "keys") else row[3]
        navbar_raw = row["navbar_items"] if hasattr(row, "keys") else row[4]
        if role != data.get("staff_role") or (required_role and role != required_role):
            return None
        navbar_items = load_staff_nav_items_for_features(
            navbar_raw, _vendor_subscription_features(c, vendor_id),
        )
        if "leave_management" not in navbar_items:
            return None
        return {"id": data.get("staff_id"), "name": name, "role": role, "department": department, "navbar_items": navbar_items}
    finally:
        conn.close()


def _student_branch(row):
    raw = row.get("student_custom_data")
    custom = {}
    if raw:
        try:
            custom = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            custom = {}
    return (
        custom.get("branch")
        or row.get("student_branch")
        or row.get("student_dept")
        or custom.get("department")
        or custom.get("Department")
        or ""
    ).strip()


def _student_matches_department(request_row, department):
    if not department:
        return False
    expected = str(department).strip().lower()
    student_branch = _student_branch(request_row).lower()
    if student_branch and student_branch == expected:
        return True
    if str(request_row.get("student_dept") or "").strip().lower() == expected:
        return True
    raw = request_row.get("student_custom_data")
    try:
        custom = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        custom = {}
    return (
        str(custom.get("branch") or "").strip().lower() == expected
        or str(custom.get("department") or "").strip().lower() == expected
        or str(custom.get("Department") or "").strip().lower() == expected
    )


def _notify_parent_when_current(conn, vendor_id, request_row):
    """Notify the linked parent exactly when a request reaches a Parent stage."""
    stages = snapshot_request(conn, vendor_id, request_row["id"], request_row)
    stage = current_stage(stages)
    if not stage or stage.get("actor_type") != "parent":
        return
    try:
        from notifications import notify_parent_async
        notify_parent_async(
            request_row["student_id"],
            vendor_id,
            "Leave request awaiting your approval",
            f"A leave request is ready for {stage.get('display_name') or 'Parent'} review.",
            {
                "type": "leave_approval",
                "request_id": str(request_row["id"]),
                "stage": str(stage.get("stage_key") or "parent"),
            },
        )
    except Exception:
        # Notification delivery must never roll back an approval transaction.
        pass


def _send_leave_stage_email_async(vendor_id, request_id, stage):
    """Notify the assigned staff member(s) via automated email when a request reaches their stage."""
    if not stage or stage.get("actor_type") != "staff":
        return

    import threading
    import logging
    logger = logging.getLogger(__name__)

    def _worker():
        try:
            from utils import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            is_pg = getattr(conn, "_is_pg", False)

            # 1. Fetch leave request details
            try:
                if is_pg:
                    c.execute("""
                        SELECT lr.id, lr.leave_type, lr.reason, lr.start_date, lr.end_date, lr.start_time, lr.end_time,
                               f.name as student_name, f.department as student_dept, f.custom_data, v.company_name as vendor_name
                        FROM leave_requests lr
                        LEFT JOIN faces f ON lr.student_id = f.id
                        LEFT JOIN vendors v ON lr.vendor_id = v.id
                        WHERE lr.id = %s AND lr.vendor_id = %s
                    """, (request_id, vendor_id))
                else:
                    c.execute("""
                        SELECT lr.id, lr.leave_type, lr.reason, lr.start_date, lr.end_date, lr.start_time, lr.end_time,
                               f.name as student_name, f.department as student_dept, f.custom_data, v.company_name as vendor_name
                        FROM leave_requests lr
                        LEFT JOIN faces f ON lr.student_id = f.id
                        LEFT JOIN vendors v ON lr.vendor_id = v.id
                        WHERE lr.id = ? AND lr.vendor_id = ?
                    """, (request_id, vendor_id))
                row = c.fetchone()
                if not row:
                    return
                req = get_row_dict(row)

                student_name = req.get("student_name") or "Student"
                student_dept = req.get("student_dept") or ""
                if not student_dept and req.get("custom_data"):
                    try:
                        cd = json.loads(req["custom_data"]) if isinstance(req["custom_data"], str) else req["custom_data"]
                        student_dept = cd.get("department") or cd.get("branch") or ""
                    except Exception:
                        pass

                vendor_name = req.get("vendor_name") or "TapInX"
                leave_type = str(req.get("leave_type") or "Leave").replace("_", " ").title()
                start_date = str(req.get("start_date") or "")
                end_date = str(req.get("end_date") or "")
                reason = str(req.get("reason") or "No reason provided")
                stage_name = stage.get("display_name") or stage.get("role_key") or "Staff"
                role_key = stage.get("role_key")
                dept_scoped = bool(stage.get("department_scoped"))

                # 2. Fetch staff approvers with valid emails
                if is_pg:
                    if dept_scoped and student_dept:
                        c.execute("""
                            SELECT name, email FROM leave_staff
                            WHERE vendor_id = %s AND LOWER(TRIM(role)) = LOWER(TRIM(%s)) AND email IS NOT NULL AND email <> ''
                              AND (LOWER(TRIM(COALESCE(department, ''))) = LOWER(TRIM(%s)) OR department IS NULL OR department = '')
                        """, (vendor_id, role_key, student_dept))
                    else:
                        c.execute("""
                            SELECT name, email FROM leave_staff
                            WHERE vendor_id = %s AND LOWER(TRIM(role)) = LOWER(TRIM(%s)) AND email IS NOT NULL AND email <> ''
                        """, (vendor_id, role_key))
                else:
                    if dept_scoped and student_dept:
                        c.execute("""
                            SELECT name, email FROM leave_staff
                            WHERE vendor_id = ? AND LOWER(TRIM(role)) = LOWER(TRIM(?)) AND email IS NOT NULL AND email <> ''
                              AND (LOWER(TRIM(COALESCE(department, ''))) = LOWER(TRIM(?)) OR department IS NULL OR department = '')
                        """, (vendor_id, role_key, student_dept))
                    else:
                        c.execute("""
                            SELECT name, email FROM leave_staff
                            WHERE vendor_id = ? AND LOWER(TRIM(role)) = LOWER(TRIM(?)) AND email IS NOT NULL AND email <> ''
                        """, (vendor_id, role_key))
                approvers = c.fetchall() or []

                # Fallback: if department scoping returned no staff, get all staff for this role
                if not approvers and dept_scoped:
                    if is_pg:
                        c.execute("""
                            SELECT name, email FROM leave_staff
                            WHERE vendor_id = %s AND LOWER(TRIM(role)) = LOWER(TRIM(%s)) AND email IS NOT NULL AND email <> ''
                        """, (vendor_id, role_key))
                    else:
                        c.execute("""
                            SELECT name, email FROM leave_staff
                            WHERE vendor_id = ? AND LOWER(TRIM(role)) = LOWER(TRIM(?)) AND email IS NOT NULL AND email <> ''
                        """, (vendor_id, role_key))
                    approvers = c.fetchall() or []
            finally:
                conn.close()

            if not approvers:
                logger.warning(f"No staff email found for stage '{stage_name}' (role={role_key}) in vendor {vendor_id}. Ensure approvers have their email registered in SuperAdmin.")
                return

            from services.email_service import send_email

            portal_url = (
                os.environ.get("TAPINX_PORTAL_URL")
                or os.environ.get("FRONTEND_URL")
                or "https://tapinx.in"
            ).strip().rstrip("/")
            if "openvisionx.in" in portal_url:
                portal_url = "https://tapinx.in"
            portal_link = f"{portal_url}/?redirect=/leave-management"
            badge_url = f"{portal_url}/api/leave/requests/{request_id}/status-badge.png"

            # Distinct subject with request ID to guarantee separate email threads in Gmail/Outlook
            subject = f"Leave Request #{request_id} · {student_name} ({leave_type}) · {stage_name}"
            for staff_row in approvers:
                staff_dict = get_row_dict(staff_row)
                staff_name = staff_dict.get("name") if isinstance(staff_dict, dict) else staff_row[0]
                staff_email = staff_dict.get("email") if isinstance(staff_dict, dict) else staff_row[1]
                if not staff_email:
                    continue

                text_body = f"""Hello {staff_name},

A new leave request is awaiting your review and approval for stage: {stage_name}.

Request ID: #{request_id}
Student: {student_name}
Department / Branch: {student_dept or 'N/A'}
Leave Type: {leave_type}
Duration: {start_date} to {end_date}
Reason: {reason}

Review & Approve Request:
{portal_link}

Regards,
{vendor_name} Leave Management System
"""

                html_body = f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
                    <div style="border-bottom: 2px solid #2563eb; padding-bottom: 12px; margin-bottom: 20px;">
                        <h2 style="color: #1e293b; margin: 0; font-size: 20px;">TapInX | Leave Approval Request</h2>
                        <p style="color: #64748b; margin: 4px 0 0 0; font-size: 13px;">Stage: <strong>{stage_name}</strong> · Request #{request_id} · Vendor: {vendor_name}</p>
                    </div>

                    <p style="color: #334155; font-size: 15px; margin-bottom: 16px;">
                        Hello <strong>{staff_name}</strong>,
                    </p>
                    <p style="color: #475569; font-size: 14px; margin-bottom: 20px; line-height: 1.5;">
                        A student leave request (<strong>#{request_id}</strong>) has advanced to your stage and is awaiting your review and authorization.
                    </p>

                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
                        <table style="width: 100%; border-collapse: collapse; font-size: 13px; color: #334155;">
                            <tr>
                                <td style="padding: 6px 0; color: #64748b; width: 140px;">Request ID:</td>
                                <td style="padding: 6px 0; font-weight: 600; color: #2563eb;">#{request_id}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Student Name:</td>
                                <td style="padding: 6px 0; font-weight: 600;">{student_name}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Department:</td>
                                <td style="padding: 6px 0; font-weight: 600;">{student_dept or 'N/A'}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Leave Type:</td>
                                <td style="padding: 6px 0; font-weight: 600;">{leave_type}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Duration:</td>
                                <td style="padding: 6px 0; font-weight: 600; color: #2563eb;">{start_date} &rarr; {end_date}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b; vertical-align: top;">Reason:</td>
                                <td style="padding: 6px 0; font-style: italic; color: #1e293b;">"{reason}"</td>
                            </tr>
                        </table>
                    </div>

                    <div style="text-align: center; margin: 28px 0 16px 0;">
                        <a href="{portal_link}" style="background: #2563eb; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
                            Open Staff Portal & Review Request
                        </a>
                    </div>

                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0 16px 0;" />
                    <p style="color: #94a3b8; font-size: 11px; text-align: center; margin: 0;">
                        This is an automated operational notification generated by TapInX on behalf of {vendor_name}.
                    </p>
                </div>
                """

                try:
                    send_email(
                        subject=subject,
                        text_body=text_body,
                        recipient=staff_email,
                        html_body=html_body,
                        vendor_id=vendor_id,
                        email_type="leave_stage_notification",
                    )
                    logger.info(f"Leave stage email sent to {staff_email} for stage {stage_name}")
                except Exception as ex:
                    logger.warning(f"Failed to send leave email to {staff_email}: {ex}")

        except Exception as e:
            logger.warning(f"Error in _send_leave_stage_email_async worker: {e}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def _send_cancellation_email_async(vendor_id, request_id):
    """Notify all assigned staff members via email when a leave cancellation is approved by parent."""
    import threading
    import logging
    logger = logging.getLogger(__name__)

    def _worker():
        try:
            from utils import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            is_pg = getattr(conn, "_is_pg", False)

            try:
                if is_pg:
                    c.execute("""
                        SELECT lr.id, lr.leave_type, lr.reason, lr.cancellation_reason, lr.start_date, lr.end_date, lr.start_time, lr.end_time,
                               f.name as student_name, f.department as student_dept, f.custom_data, v.company_name as vendor_name
                        FROM leave_requests lr
                        LEFT JOIN faces f ON lr.student_id = f.id
                        LEFT JOIN vendors v ON lr.vendor_id = v.id
                        WHERE lr.id = %s AND lr.vendor_id = %s
                    """, (request_id, vendor_id))
                else:
                    c.execute("""
                        SELECT lr.id, lr.leave_type, lr.reason, lr.cancellation_reason, lr.start_date, lr.end_date, lr.start_time, lr.end_time,
                               f.name as student_name, f.department as student_dept, f.custom_data, v.company_name as vendor_name
                        FROM leave_requests lr
                        LEFT JOIN faces f ON lr.student_id = f.id
                        LEFT JOIN vendors v ON lr.vendor_id = v.id
                        WHERE lr.id = ? AND lr.vendor_id = ?
                    """, (request_id, vendor_id))
                row = c.fetchone()
                if not row:
                    return
                req = get_row_dict(row)

                student_name = req.get("student_name") or "Student"
                student_dept = req.get("student_dept") or ""
                if not student_dept and req.get("custom_data"):
                    try:
                        cd = json.loads(req["custom_data"]) if isinstance(req["custom_data"], str) else req["custom_data"]
                        student_dept = cd.get("department") or cd.get("branch") or ""
                    except Exception:
                        pass

                vendor_name = req.get("vendor_name") or "TapInX"
                leave_type = str(req.get("leave_type") or "Leave").replace("_", " ").title()
                start_date = str(req.get("start_date") or "")
                end_date = str(req.get("end_date") or "")
                reason = str(req.get("reason") or "No reason provided")
                cancellation_reason = str(req.get("cancellation_reason") or "Student requested cancellation")

                # Fetch all staff approvers with valid emails for this vendor
                if is_pg:
                    c.execute("""
                        SELECT DISTINCT name, email, role FROM leave_staff
                        WHERE vendor_id = %s AND email IS NOT NULL AND email <> ''
                    """, (vendor_id,))
                else:
                    c.execute("""
                        SELECT DISTINCT name, email, role FROM leave_staff
                        WHERE vendor_id = ? AND email IS NOT NULL AND email <> ''
                    """, (vendor_id,))
                approvers = c.fetchall() or []
            finally:
                conn.close()

            if not approvers:
                logger.warning(f"No staff emails found to notify about cancellation of request #{request_id} in vendor {vendor_id}.")
                return

            from services.email_service import send_email

            portal_url = (
                os.environ.get("TAPINX_PORTAL_URL")
                or os.environ.get("FRONTEND_URL")
                or "https://tapinx.in"
            ).strip().rstrip("/")
            if "openvisionx.in" in portal_url:
                portal_url = "https://tapinx.in"
            portal_link = f"{portal_url}/?redirect=/leave-management"
            badge_url = f"{portal_url}/api/leave/requests/{request_id}/status-badge.png"

            subject = f"Leave Cancellation Approved · Request #{request_id} · {student_name} ({leave_type})"
            for staff_row in approvers:
                staff_dict = get_row_dict(staff_row)
                staff_name = staff_dict.get("name") if isinstance(staff_dict, dict) else staff_row[0]
                staff_email = staff_dict.get("email") if isinstance(staff_dict, dict) else staff_row[1]
                if not staff_email:
                    continue

                text_body = f"""Hello {staff_name},

NOTICE: Leave Request #{request_id} for {student_name} has been CANCELLED and approved by parent.

Request ID: #{request_id}
Student: {student_name}
Department / Branch: {student_dept or 'N/A'}
Original Leave Type: {leave_type}
Dates: {start_date} to {end_date}
Cancellation Reason: {cancellation_reason}
Parent Approval: Verified & Approved with Face Scan
Status: CANCELLED

ATTENDANCE NOTICE:
The student's attendance will continue to be marked regularly as normal. The student may now apply for leave again on these dates if needed.

Staff Portal:
{portal_link}

Regards,
{vendor_name} Leave Management System
"""

                html_body = f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #fecaca; border-radius: 12px; background: #ffffff;">
                    <div style="border-bottom: 2px solid #ef4444; padding-bottom: 12px; margin-bottom: 20px;">
                        <span style="background: #fee2e2; color: #b91c1c; font-size: 11px; font-weight: bold; padding: 4px 10px; border-radius: 12px; text-transform: uppercase; letter-spacing: 0.5px;">
                            Cancellation Approved
                        </span>
                        <h2 style="color: #1e293b; margin: 8px 0 0 0; font-size: 20px;">TapInX | Leave Cancellation Notice</h2>
                        <p style="color: #64748b; margin: 4px 0 0 0; font-size: 13px;">Request #{request_id} · Vendor: {vendor_name}</p>
                    </div>

                    <p style="color: #334155; font-size: 15px; margin-bottom: 14px;">
                        Hello <strong>{staff_name}</strong>,
                    </p>
                    <p style="color: #475569; font-size: 14px; margin-bottom: 20px; line-height: 1.5;">
                        Student <strong>{student_name}</strong> requested to cancel their leave request (<strong>#{request_id}</strong>). The cancellation has been <strong>verified and approved by the parent</strong> via mobile face authentication.
                    </p>

                    <div style="background: #fff1f2; border: 1px solid #fecdd3; border-radius: 8px; padding: 14px 16px; margin-bottom: 20px;">
                        <p style="margin: 0; color: #9f1239; font-size: 13px; font-weight: 600;">
                            &#9888; Attendance Notice:
                        </p>
                        <p style="margin: 4px 0 0 0; color: #881337; font-size: 13px; line-height: 1.4;">
                            The student is <strong>no longer on leave</strong>. Regular attendance marking applies as normal. The student may also re-apply for leave during these dates without restriction.
                        </p>
                    </div>

                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
                        <table style="width: 100%; border-collapse: collapse; font-size: 13px; color: #334155;">
                            <tr>
                                <td style="padding: 6px 0; color: #64748b; width: 140px;">Request ID:</td>
                                <td style="padding: 6px 0; font-weight: 600; color: #2563eb;">#{request_id}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Student Name:</td>
                                <td style="padding: 6px 0; font-weight: 600;">{student_name}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Department:</td>
                                <td style="padding: 6px 0; font-weight: 600;">{student_dept or 'N/A'}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Leave Type:</td>
                                <td style="padding: 6px 0; font-weight: 600;">{leave_type}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Duration:</td>
                                <td style="padding: 6px 0; font-weight: 600;">{start_date} &rarr; {end_date}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b; vertical-align: top;">Original Reason:</td>
                                <td style="padding: 6px 0; font-style: italic; color: #64748b;">"{reason}"</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #b91c1c; vertical-align: top; font-weight: 600;">Cancellation Reason:</td>
                                <td style="padding: 6px 0; font-weight: 600; color: #b91c1c;">"{cancellation_reason}"</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #047857; font-weight: 600;">Parent Approval:</td>
                                <td style="padding: 6px 0; font-weight: 600; color: #047857;">&#10004; Verified & Approved with Mobile Face Scan</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Final Status:</td>
                                <td style="padding: 6px 0;"><span style="background: #fee2e2; color: #991b1b; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">CANCELLED</span></td>
                            </tr>
                        </table>
                    </div>

                    <div style="text-align: center; margin: 24px 0 16px 0;">
                        <a href="{portal_link}" style="background: #0f172a; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
                            Open Staff Portal
                        </a>
                    </div>

                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0 16px 0;" />
                    <p style="color: #94a3b8; font-size: 11px; text-align: center; margin: 0;">
                        This is an automated operational notification generated by TapInX on behalf of {vendor_name}.
                    </p>
                </div>
                """

                try:
                    send_email(
                        subject=subject,
                        text_body=text_body,
                        recipient=staff_email,
                        html_body=html_body,
                        vendor_id=vendor_id,
                        email_type="leave_cancellation_notification",
                    )
                    logger.info(f"Leave cancellation email sent to {staff_email} for request #{request_id}")
                except Exception as ex:
                    logger.warning(f"Failed to send cancellation email to {staff_email}: {ex}")

        except Exception as e:
            logger.warning(f"Error in _send_cancellation_email_async worker: {e}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def _extract_server_face_template(face_image, vendor_id):
    """Extract a server-controlled embedding from an audit image."""
    from tasks import detect_faces_task
    from services.task_payload_service import store_image_payload

    data_part = face_image.split(",")[-1] if "," in face_image else face_image
    task_payload = store_image_payload(data_part)
    result = detect_faces_task.apply_async(
        args=[task_payload, {"fast": True}, vendor_id]
    ).get(timeout=60)
    faces = result.get("faces", [])
    if not faces:
        raise ValueError("No face detected in captured image")
    template = faces[0].get("emb_vec", "")
    if not template:
        raise RuntimeError("Failed to extract face embedding")
    return template

@leave_bp.route("/request", methods=["POST"])
@require_feature("leave_management")
def create_leave_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    role_error = _require_role("user", "student", "parent")
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

    if start_date > end_date:
        return jsonify({"error": "Start date cannot be after end date"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Creating leave request for student_id={student_id}, vendor_id={vendor_id}")

        # Authenticate and resolve caller identity (parent vs student/user)
        is_parent_caller = getattr(g, "user_role", None) == "parent"
        parent_account = None

        if is_parent_caller:
            parent_account = _authenticated_parent(c, vendor_id)
            if not parent_account:
                return jsonify({"error": "Parent account not found or session invalid"}), 403

            # Parent must only submit leave for students linked to their account
            linked_person_ids = set()
            if parent_account.get("selected_person_id"):
                linked_person_ids.add(int(parent_account["selected_person_id"]))
            try:
                c.execute(
                    "SELECT person_id FROM student_parents WHERE vendor_id = ? AND parent_id = ?",
                    (vendor_id, parent_account["id"]),
                )
                for r in c.fetchall() or []:
                    pid_val = r[0] if not hasattr(r, "keys") else r["person_id"]
                    if pid_val is not None:
                        linked_person_ids.add(int(pid_val))
            except Exception:
                pass

            resolved_student_id = None
            if student_id:
                if str(student_id).isdigit() and int(student_id) in linked_person_ids:
                    resolved_student_id = int(student_id)
                elif str(student_id).strip().lower() == str(parent_account.get("student_number", "")).strip().lower():
                    resolved_student_id = parent_account.get("selected_person_id")
                else:
                    c.execute("""SELECT id FROM faces WHERE vendor_id = ? AND (
                                    CAST(id AS TEXT) = ? OR
                                    LOWER(TRIM(json_extract(custom_data, '$.student_id'))) = LOWER(TRIM(?)) OR
                                    LOWER(TRIM(json_extract(custom_data, '$.id_number'))) = LOWER(TRIM(?))
                                 )""", (vendor_id, str(student_id), str(student_id), str(student_id)))
                    row = c.fetchone()
                    if row:
                        cand_id = int(row[0] if not hasattr(row, "keys") else row["id"])
                        if cand_id in linked_person_ids:
                            resolved_student_id = cand_id

            if resolved_student_id is None:
                resolved_student_id = parent_account.get("selected_person_id")

            if not resolved_student_id or (linked_person_ids and resolved_student_id not in linked_person_ids):
                return jsonify({"error": "This parent account is not linked to that student"}), 403
            student_id = resolved_student_id

            # Validate student lifecycle status for parent leave request
            c.execute(
                "SELECT student_status, hostel_status, login_enabled FROM faces WHERE id = ? AND vendor_id = ?",
                (int(student_id), vendor_id),
            )
            l_chk = c.fetchone()
            if l_chk:
                st_stat = str(l_chk[0] or "active").lower()
                h_stat = str(l_chk[1] or "not_applicable").lower()
                l_en = l_chk[2] if l_chk[2] is not None else 1
                if st_stat in ("graduated", "left_college", "suspended") or l_en == 0 or h_stat == "left_hostel":
                    conn.close()
                    return jsonify({
                        "error": f"Leave requests cannot be submitted for deactivated students ({st_stat.replace('_', ' ').title()})"
                    }), 400
        else:
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

        # Verify student lifecycle status before inserting leave request
        c.execute(
            "SELECT student_status, hostel_status, login_enabled FROM faces WHERE id = ? AND vendor_id = ?",
            (int(student_id), vendor_id),
        )
        s_chk = c.fetchone()
        if s_chk:
            st_stat = str(s_chk[0] or "active").lower()
            h_stat = str(s_chk[1] or "not_applicable").lower()
            l_en = s_chk[2] if s_chk[2] is not None else 1
            if st_stat in ("graduated", "left_college", "suspended") or l_en == 0 or h_stat == "left_hostel":
                conn.close()
                return jsonify({
                    "error": f"Leave requests cannot be submitted for deactivated students ({st_stat.replace('_', ' ').title()})"
                }), 400

        # Check for overlapping leave requests for this student (active/pending/approved, not rejected or cancelled)
        if is_pg:
            c.execute("""
                SELECT id, leave_type, start_date, end_date, final_status
                FROM leave_requests
                WHERE vendor_id = %s AND student_id = %s
                  AND final_status NOT IN ('rejected', 'cancelled')
                  AND start_date <= %s AND end_date >= %s
                ORDER BY start_date ASC
                LIMIT 1
            """, (vendor_id, student_id, end_date, start_date))
        else:
            c.execute("""
                SELECT id, leave_type, start_date, end_date, final_status
                FROM leave_requests
                WHERE vendor_id = ? AND student_id = ?
                  AND final_status NOT IN ('rejected', 'cancelled')
                  AND start_date <= ? AND end_date >= ?
                ORDER BY start_date ASC
                LIMIT 1
            """, (vendor_id, student_id, end_date, start_date))

        overlap_row = c.fetchone()
        if overlap_row:
            overlap_data = get_row_dict(overlap_row)
            o_type = overlap_data.get("leave_type") if isinstance(overlap_data, dict) else overlap_row[1]
            o_start = overlap_data.get("start_date") if isinstance(overlap_data, dict) else overlap_row[2]
            o_end = overlap_data.get("end_date") if isinstance(overlap_data, dict) else overlap_row[3]
            o_stat = overlap_data.get("final_status") if isinstance(overlap_data, dict) else overlap_row[4]
            return jsonify({
                "error": f"You already have a leave request ({o_type}) from {o_start} to {o_end} (Status: {o_stat}). Overlapping leave dates are not permitted.",
                "error_code": "LEAVE_OVERLAP",
                "overlap": {
                    "leave_type": o_type,
                    "start_date": str(o_start),
                    "end_date": str(o_end),
                    "final_status": str(o_stat),
                }
            }), 409

        if is_pg:
            c.execute("""
                INSERT INTO leave_requests 
                (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time))
            inserted = c.fetchone()
            request_id = inserted["id"] if hasattr(inserted, "keys") else inserted[0]
        else:
            c.execute("""
                INSERT INTO leave_requests 
                (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (vendor_id, student_id, leave_type, reason, start_date, end_date, start_time, end_time))
            request_id = c.lastrowid
        
        conn.commit()
        steps = snapshot_request(conn, vendor_id, request_id) if request_id else []
        if request_id:
            st1 = current_stage(steps)
            if st1 and st1.get("actor_type") == "parent":
                _notify_parent_when_current(conn, vendor_id, {
                    "id": request_id,
                    "vendor_id": vendor_id,
                    "student_id": student_id,
                })
            elif st1 and st1.get("actor_type") == "staff":
                _send_leave_stage_email_async(vendor_id, request_id, st1)
        return jsonify({"status": "success", "request_id": request_id, "approval_steps": steps})
    except Exception as e:
        if is_pg: conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/request/<int:request_id>", methods=["PUT"])
@require_feature("leave_management")
def update_leave_request(request_id):
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    role_error = _require_role("user", "student", "parent", "super_admin")
    if role_error: return role_error

    data = request.json or {}
    new_leave_type = data.get("leave_type")
    new_reason = data.get("reason")
    new_start_date = data.get("start_date")
    new_end_date = data.get("end_date")
    new_start_time = data.get("start_time", "10:00")
    new_end_time = data.get("end_time", "18:00")

    if not all([new_leave_type, new_reason, new_start_date, new_end_date]):
        return jsonify({"error": "Missing required fields"}), 400

    if new_start_date > new_end_date:
        return jsonify({"error": "Start date cannot be after end date"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)

        # 1. Fetch existing request
        if is_pg:
            c.execute("SELECT * FROM leave_requests WHERE id = %s AND vendor_id = %s", (request_id, vendor_id))
        else:
            c.execute("SELECT * FROM leave_requests WHERE id = ? AND vendor_id = ?", (request_id, vendor_id))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Leave request not found"}), 404
        req_row = get_row_dict(row)
        student_id = req_row["student_id"]

        # 2. Authorization check
        caller_role = getattr(g, "user_role", None)
        if caller_role in ("user", "student"):
            # Resolve caller's person_id
            if is_pg:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s AND role IN ('user', 'student')", (vendor_id, g.username))
            else:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ? AND role IN ('user', 'student')", (vendor_id, g.username))
            u_row = c.fetchone()
            caller_person_id = (get_row_dict(u_row).get("person_id") if u_row and hasattr(u_row, "keys") else (u_row[0] if u_row else None))
            if caller_person_id is None:
                # Fallback to faces check
                if is_pg:
                    c.execute("""SELECT id FROM faces WHERE vendor_id = %s AND (
                        id::text = %s OR
                        LOWER(TRIM(custom_data::jsonb->>'student_id')) = LOWER(TRIM(%s)) OR
                        LOWER(TRIM(custom_data::jsonb->>'id_number')) = LOWER(TRIM(%s)) OR
                        LOWER(TRIM(custom_data::jsonb->>'employee_id')) = LOWER(TRIM(%s))
                    )""", (vendor_id, str(g.username), str(g.username), str(g.username), str(g.username)))
                else:
                    c.execute("""SELECT id FROM faces WHERE vendor_id = ? AND (
                        CAST(id AS TEXT) = ? OR
                        LOWER(TRIM(json_extract(custom_data, '$.student_id'))) = LOWER(TRIM(?)) OR
                        LOWER(TRIM(json_extract(custom_data, '$.id_number'))) = LOWER(TRIM(?)) OR
                        LOWER(TRIM(json_extract(custom_data, '$.employee_id'))) = LOWER(TRIM(?))
                    )""", (vendor_id, str(g.username), str(g.username), str(g.username), str(g.username)))
                f_row = c.fetchone()
                if f_row:
                    caller_person_id = f_row["id"] if hasattr(f_row, "keys") else f_row[0]
            if caller_person_id is None or int(caller_person_id) != int(student_id):
                return jsonify({"error": "You are not authorized to edit this leave request"}), 403

        elif caller_role == "parent":
            parent_account = _authenticated_parent(c, vendor_id)
            if not parent_account:
                return jsonify({"error": "Parent account not found or session invalid"}), 403
            linked_person_ids = set()
            if parent_account.get("selected_person_id"):
                linked_person_ids.add(int(parent_account["selected_person_id"]))
            try:
                c.execute("SELECT person_id FROM student_parents WHERE vendor_id = ? AND parent_id = ?", (vendor_id, parent_account["id"]))
                for r in c.fetchall() or []:
                    pid_val = r[0] if not hasattr(r, "keys") else r["person_id"]
                    if pid_val is not None: linked_person_ids.add(int(pid_val))
            except Exception:
                pass
            if int(student_id) not in linked_person_ids:
                return jsonify({"error": "You are not authorized to edit leave for this student"}), 403

        # 3. Check if any approval or rejection has already arrived
        final_status = str(req_row.get("final_status") or "pending").lower()
        if final_status != "pending":
            return jsonify({"error": f"Leave request cannot be edited because it is already {final_status}."}), 400

        stages = snapshot_request(conn, vendor_id, request_id, req_row)
        approved_stage = next((s for s in stages if str(s.get("status") or "").lower() == "approved"), None)
        if approved_stage:
            return jsonify({
                "error": f"Leave request cannot be edited once an approval has been granted ({approved_stage.get('display_name', 'Stage')})."
            }), 400

        rejected_stage = next((s for s in stages if str(s.get("status") or "").lower() == "rejected"), None)
        if rejected_stage:
            return jsonify({"error": "Leave request cannot be edited because it has been rejected."}), 400

        if int(req_row.get("is_cancellation") or 0) == 1:
            return jsonify({"error": "Cannot edit a leave request with an active or pending cancellation."}), 400

        for col in ("rector_status", "hod_status", "parent_status"):
            if str(req_row.get(col) or "").lower() == "approved":
                return jsonify({"error": "Leave request cannot be edited once an approval has been granted."}), 400

        # 4. Check for overlapping leave requests with other leaves
        if is_pg:
            c.execute("""
                SELECT id, leave_type, start_date, end_date, final_status
                FROM leave_requests
                WHERE vendor_id = %s AND student_id = %s
                  AND id != %s
                  AND final_status NOT IN ('rejected', 'cancelled')
                  AND start_date <= %s AND end_date >= %s
                ORDER BY start_date ASC
                LIMIT 1
            """, (vendor_id, student_id, request_id, new_end_date, new_start_date))
        else:
            c.execute("""
                SELECT id, leave_type, start_date, end_date, final_status
                FROM leave_requests
                WHERE vendor_id = ? AND student_id = ?
                  AND id != ?
                  AND final_status NOT IN ('rejected', 'cancelled')
                  AND start_date <= ? AND end_date >= ?
                ORDER BY start_date ASC
                LIMIT 1
            """, (vendor_id, student_id, request_id, new_end_date, new_start_date))

        overlap_row = c.fetchone()
        if overlap_row:
            overlap_data = get_row_dict(overlap_row)
            o_type = overlap_data.get("leave_type") if isinstance(overlap_data, dict) else overlap_row[1]
            o_start = overlap_data.get("start_date") if isinstance(overlap_data, dict) else overlap_row[2]
            o_end = overlap_data.get("end_date") if isinstance(overlap_data, dict) else overlap_row[3]
            o_stat = overlap_data.get("final_status") if isinstance(overlap_data, dict) else overlap_row[4]
            return jsonify({
                "error": f"You already have another leave request ({o_type}) from {o_start} to {o_end} (Status: {o_stat}). Overlapping leave dates are not permitted.",
                "error_code": "LEAVE_OVERLAP",
                "overlap": {
                    "leave_type": o_type,
                    "start_date": str(o_start),
                    "end_date": str(o_end),
                    "final_status": str(o_stat),
                }
            }), 409

        # 5. Execute Update
        if is_pg:
            c.execute("""
                UPDATE leave_requests
                SET leave_type = %s, reason = %s, start_date = %s, end_date = %s, start_time = %s, end_time = %s
                WHERE id = %s AND vendor_id = %s
            """, (new_leave_type, new_reason, new_start_date, new_end_date, new_start_time, new_end_time, request_id, vendor_id))
        else:
            c.execute("""
                UPDATE leave_requests
                SET leave_type = ?, reason = ?, start_date = ?, end_date = ?, start_time = ?, end_time = ?
                WHERE id = ? AND vendor_id = ?
            """, (new_leave_type, new_reason, new_start_date, new_end_date, new_start_time, new_end_time, request_id, vendor_id))

        conn.commit()
        return jsonify({
            "status": "success",
            "message": "Leave request updated successfully",
            "request_id": request_id
        })
    except Exception as e:
        if is_pg: conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@leave_bp.route("/parent/pending", methods=["GET"])
@leave_bp.route("/parent/requests", methods=["GET"])
@leave_bp.route("/parent/history", methods=["GET"])
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

        status_param = request.args.get("status")
        include_all = request.args.get("all") in ("1", "true") or request.path.endswith(("/requests", "/history"))

        def _format_for_parent(item_list):
            for r in item_list:
                if int(r.get("is_cancellation") or 0) == 1:
                    orig_type = str(r.get("leave_type") or "Leave").replace("_", " ").title()
                    c_reason = r.get("cancellation_reason") or "Cancellation requested by student"
                    orig_reason = r.get("reason") or "No reason provided"
                    r["leave_type"] = f"Cancellation: {orig_type}"
                    r["reason"] = f"[CANCELLATION REQUEST] {c_reason} (Original: {orig_reason})"
            return item_list

        if include_all or status_param:
            if status_param and status_param != "all":
                c.execute("""SELECT * FROM leave_requests
                             WHERE student_id = ? AND vendor_id = ? AND final_status = ?
                             ORDER BY created_at DESC""", (student_id, vendor_id, status_param))
            else:
                c.execute("""SELECT * FROM leave_requests
                             WHERE student_id = ? AND vendor_id = ?
                             ORDER BY created_at DESC""", (student_id, vendor_id))
            rows = [get_row_dict(r) for r in c.fetchall()]
            attach_approval_steps(conn, rows)
            formatted = _format_for_parent(rows)
            return jsonify({"requests": formatted, "history": formatted})

        c.execute("""SELECT * FROM leave_requests
                     WHERE student_id = ? AND vendor_id = ? AND final_status = 'pending'
                     ORDER BY created_at DESC""", (student_id, vendor_id))
        rows = [get_row_dict(r) for r in c.fetchall()]
        attach_approval_steps(conn, rows)
        pending = [
            row for row in rows
            if row.get("current_stage") and row["current_stage"].get("actor_type") == "parent"
        ]
        return jsonify({"requests": _format_for_parent(pending)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/parent/face-status", methods=["GET"])
def parent_face_status():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    conn = get_db_connection()
    c = conn.cursor()
    try:
        parent = _authenticated_parent(c, vendor_id)
        if not parent:
            conn.close()
            return jsonify({"error": "Parent access required"}), 403
        face_registered = bool(parent.get("face_template") or parent.get("face_image"))
        conn.close()
        return jsonify({"status": "success", "face_registered": face_registered})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


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

    # If this parent already has a registered face, flag it immediately instead
    # of silently overwriting. Re-registration must go through the face-reset flow.
    if parent.get("face_template") or parent.get("face_image"):
        conn.close()
        return jsonify({
            "status": "already_registered",
            "message": "Face is already registered for this parent account",
        }), 200

    # 1. Proceed with registration
    try:
        is_pg = getattr(conn, "_is_pg", False)
        server_template = None
        try:
            server_template = _extract_server_face_template(face_image, vendor_id)
        except Exception as e:
            if not face_template:
                conn.close()
                return jsonify({"error": f"Inference failed or timed out: {str(e)}"}), 500

        # Cross-entity vector duplicate check:
        # A parent CANNOT have the same face as any active student, or any other parent account.
        from services.face_duplicate_service import (
            check_parent_face_duplicate,
            extract_vectors_from_payload,
        )
        candidate_vecs = []
        if server_template:
            candidate_vecs.extend(extract_vectors_from_payload(server_template))
        if face_template:
            candidate_vecs.extend(extract_vectors_from_payload(face_template))

        is_dup, dup_err = check_parent_face_duplicate(
            conn=conn,
            vendor_id=vendor_id,
            parent_id=parent["id"],
            candidate_vectors=candidate_vecs,
            candidate_image=face_image,
        )
        if is_dup:
            conn.close()
            return jsonify({"error": dup_err}), 409

        # Web clients without the local model may use the server template for
        # local storage too; Android keeps its model-specific FID1 template.
        local_template = face_template or server_template

        if is_pg:
            c.execute("UPDATE parent_users SET face_image = %s, face_template = %s, face_server_template = %s WHERE id = %s AND vendor_id = %s",
                      (face_image, local_template, server_template, parent["id"], vendor_id))
        else:
            c.execute("UPDATE parent_users SET face_image = ?, face_template = ?, face_server_template = ? WHERE id = ? AND vendor_id = ?",
                      (face_image, local_template, server_template, parent["id"], vendor_id))
        if c.rowcount == 0:
            conn.close()
            return jsonify({"status": "error", "error": "Parent record not found for this student."}), 404
        conn.commit()
        conn.close()
        return jsonify({
            "status": "success",
            "server_verification_ready": bool(server_template),
            "verification_note": None if server_template else "Server template will be prepared on first approval",
        })
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

        c.execute("""SELECT * FROM leave_requests
                     WHERE id = ? AND vendor_id = ? AND student_id = ?
                       AND final_status = 'pending'""", (request_id, vendor_id, student_id))
        request_row_raw = c.fetchone()
        if not request_row_raw:
            return jsonify({"error": "Leave request is not awaiting this parent's decision"}), 409
        request_row = get_row_dict(request_row_raw)
        steps = snapshot_request(conn, vendor_id, request_id, request_row)
        stage = current_stage(steps)
        if not stage or stage.get("actor_type") != "parent":
            waiting_for = stage.get("display_name") if stage else "another stage"
            return jsonify({"error": f"Leave request is awaiting {waiting_for} approval"}), 409

        if not parent or not (parent.get('face_server_template') or parent.get('face_image') or parent.get('face_template')):
            return jsonify({"error": "Parent face not registered"}), 400

        client_face_template = data.get("face_template")
        local_verified = bool(data.get("local_verified", False))
        local_similarity = data.get("local_similarity")
        stored_local_template = parent.get("face_template")

        similarity = 0.0
        verified = False
        verification_method = "unknown"

        # 1. Ultra-fast 1:1 match if both client live template and stored template exist (<0.1ms dot product)
        if client_face_template and stored_local_template:
            try:
                emb, live_family = _decode_face_template(client_face_template)
                stored_emb, stored_family = _decode_face_template(stored_local_template)
                if live_family == stored_family:
                    similarity = float(np.dot(emb, stored_emb))
                    if similarity >= 0.58:
                        verified = True
                        verification_method = "fast_1to1_template_match"
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Fast 1:1 template match check exception: {e}")

        # 2. If client already verified locally on-device with anti-spoofing and local similarity >= 0.58
        if not verified and local_verified and local_similarity is not None:
            try:
                sim_float = float(local_similarity)
                if sim_float >= 0.58:
                    similarity = sim_float
                    verified = True
                    verification_method = "client_anti_spoof_verified"
            except (ValueError, TypeError):
                pass

        # 3. Fallback: server-side extraction if client didn't supply template or wasn't verified locally
        if not verified:
            try:
                live_server_template = _extract_server_face_template(captured_face, vendor_id)
                stored_server_template = parent.get("face_server_template")
                if not stored_server_template and parent.get("face_image"):
                    stored_server_template = _extract_server_face_template(parent["face_image"], vendor_id)
                    c.execute(
                        "UPDATE parent_users SET face_server_template = ? WHERE id = ? AND vendor_id = ?",
                        (stored_server_template, parent["id"], vendor_id),
                    )
                    conn.commit()

                if stored_server_template:
                    emb, live_family = _decode_face_template(live_server_template)
                    stored_template, stored_family = _decode_face_template(stored_server_template)
                    if live_family == stored_family:
                        similarity = float(np.dot(emb, stored_template))
                        if similarity >= 0.58:
                            verified = True
                            verification_method = "server_face_match"
            except Exception as e:
                # If inference failed but client had active authenticated parent session and local verified
                if local_verified and data.get("liveness_verified"):
                    verified = True
                    similarity = float(local_similarity or 0.8)
                    verification_method = "local_anti_spoof_fallback"
                else:
                    return jsonify({"error": f"Inference failed or timed out: {str(e)}"}), 500

        if not verified or similarity < 0.58:
             return jsonify({"error": "Face verification failed", "similarity": similarity}), 401

        # Check if this request is a cancellation request
        if int(request_row.get("is_cancellation") or 0) == 1:
            if action == "approved":
                meta_json = json.dumps({
                    "face_similarity": similarity,
                    "verification": verification_method,
                    "device_id": parent.get("device_id"),
                    "ip": request.remote_addr,
                    "captured_face": captured_face,
                    "cancellation_approval": True,
                }, separators=(",", ":"))
                now_iso = datetime.now(timezone.utc).isoformat()

                if is_pg:
                    # 1. Update the parent stage directly in leave_request_stages with verified face capture
                    c.execute("""
                        UPDATE leave_request_stages
                        SET status = 'approved',
                            actor_id = %s,
                            actor_name = %s,
                            decided_at = %s,
                            decision_metadata = %s
                        WHERE request_id = %s AND vendor_id = %s AND actor_type = 'parent'
                    """, (str(parent["id"]), parent["student_number"], now_iso, meta_json, request_id, vendor_id))
                    # 2. Skip any remaining pending stages
                    c.execute("""
                        UPDATE leave_request_stages
                        SET status = 'skipped'
                        WHERE request_id = %s AND vendor_id = %s AND actor_type != 'parent' AND status = 'pending'
                    """, (request_id, vendor_id))
                    # 3. Mark final_status = 'cancelled', parent_status = 'approved', cancellation_status = 'approved', is_cancellation = 0
                    c.execute("""
                        UPDATE leave_requests
                        SET final_status = 'cancelled',
                            parent_status = 'approved',
                            cancellation_status = 'approved',
                            is_cancellation = 0
                        WHERE id = %s AND vendor_id = %s
                    """, (request_id, vendor_id))
                else:
                    c.execute("""
                        UPDATE leave_request_stages
                        SET status = 'approved',
                            actor_id = ?,
                            actor_name = ?,
                            decided_at = ?,
                            decision_metadata = ?
                        WHERE request_id = ? AND vendor_id = ? AND actor_type = 'parent'
                    """, (str(parent["id"]), parent["student_number"], now_iso, meta_json, request_id, vendor_id))
                    c.execute("""
                        UPDATE leave_request_stages
                        SET status = 'skipped'
                        WHERE request_id = ? AND vendor_id = ? AND actor_type != 'parent' AND status = 'pending'
                    """, (request_id, vendor_id))
                    c.execute("""
                        UPDATE leave_requests
                        SET final_status = 'cancelled',
                            parent_status = 'approved',
                            cancellation_status = 'approved',
                            is_cancellation = 0
                        WHERE id = ? AND vendor_id = ?
                    """, (request_id, vendor_id))
                conn.commit()

                # Automated notification email to all staff members
                _send_cancellation_email_async(vendor_id, request_id)

                # Send FCM push notification to student / parent
                try:
                    from notifications import notify_parent_async
                    notify_parent_async(
                        student_id,
                        vendor_id,
                        "Leave Cancellation Approved",
                        "The leave request has been successfully cancelled and all staff members have been notified.",
                        {"type": "leave_cancelled", "request_id": str(request_id)},
                    )
                except Exception:
                    pass

                return jsonify({
                    "status": "success",
                    "message": "Leave cancelled successfully!",
                    "similarity": similarity,
                    "method": verification_method,
                })
            else:
                # Parent rejected cancellation
                if is_pg:
                    c.execute("""
                        UPDATE leave_requests
                        SET is_cancellation = 0,
                            cancellation_status = 'rejected',
                            final_status = 'approved'
                        WHERE id = %s AND vendor_id = %s
                    """, (request_id, vendor_id))
                else:
                    c.execute("""
                        UPDATE leave_requests
                        SET is_cancellation = 0,
                            cancellation_status = 'rejected',
                            final_status = 'approved'
                        WHERE id = ? AND vendor_id = ?
                    """, (request_id, vendor_id))
                conn.commit()
                return jsonify({
                    "status": "success",
                    "message": "Leave cancellation was rejected. Original leave request remains active.",
                    "similarity": similarity,
                    "method": verification_method,
                })

        decide_current_stage(
            conn,
            vendor_id,
            request_row,
            action,
            actor_type="parent",
            role_key="parent",
            actor_id=parent["id"],
            actor_name=parent["student_number"],
            metadata={
                "face_similarity": similarity,
                "verification": verification_method,
                "device_id": parent.get("device_id"),
                "ip": request.remote_addr,
                "captured_face": captured_face,
            },
        )
        if action == "approved":
            new_steps = snapshot_request(conn, vendor_id, request_id)
            nxt_st = current_stage(new_steps)
            if nxt_st and nxt_st.get("actor_type") == "staff":
                _send_leave_stage_email_async(vendor_id, request_id, nxt_st)
        return jsonify({"status": "success", "similarity": similarity, "method": verification_method})
    finally:
        conn.close()

@leave_bp.route("/admin/tracking", methods=["GET"])
@require_feature("leave_management")
def get_leave_tracking():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role", "rector")
    staff = _authenticated_leave_staff(vendor_id, role)
    caller_role = getattr(g, "user_role", None)
    is_vendor_admin = caller_role in ("vendor_admin", "admin", "owner", "super_admin")
    if not staff:
        if is_vendor_admin:
            staff = {"id": None, "name": getattr(g, "username", "Admin"), "role": role or "admin", "department": None}
        else:
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
            LEFT JOIN faces f ON lr.student_id = f.id
            WHERE lr.vendor_id = ? AND lr.final_status = 'approved'
            AND (lr.end_date >= ? OR lr.end_date < ?) -- Show upcoming and past due
        """
        params = [vendor_id, today - timedelta(days=1), today]
        
        workflow = get_active_workflow(conn, vendor_id)
        role_stages = [
            stage for stage in workflow["stages"]
            if stage.get("actor_type") == "staff" and stage.get("role_key") == role
        ]
        if not role_stages:
            return jsonify({"error": "This staff role is not part of the active workflow"}), 403
        if any(stage.get("department_scoped") for stage in role_stages) and dept:
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
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role", "rector")
    staff = _authenticated_leave_staff(vendor_id, role)
    caller_role = getattr(g, "user_role", None)
    is_vendor_admin = caller_role in ("vendor_admin", "admin", "owner", "super_admin")
    if not staff:
        if is_vendor_admin:
            staff = {"id": None, "name": getattr(g, "username", "Admin"), "role": role or "admin", "department": None}
        else:
            return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        c.execute("""
            SELECT lr.*, f.name AS student_name, f.department AS student_dept,
                   f.custom_data AS student_custom_data
            FROM leave_requests lr
            LEFT JOIN faces f ON lr.student_id = f.id
            WHERE lr.vendor_id = ? AND lr.final_status = 'pending'
            ORDER BY lr.created_at ASC
        """, (vendor_id,))
        rows = [get_row_dict(r) for r in c.fetchall()]
        attach_approval_steps(conn, rows)

        # Retrieve all branches configured with an active HOD
        c.execute("SELECT LOWER(TRIM(department)) FROM leave_staff WHERE vendor_id = ? AND role = 'hod' AND department IS NOT NULL AND department <> ''", (vendor_id,))
        configured_hod_branches = {r[0] for r in c.fetchall() if r[0]}

        pending = []
        for row in rows:
            stage = row.get("current_stage")
            if not stage or stage.get("actor_type") != "staff":
                continue
            student_br = _student_branch(row)
            row["student_branch"] = student_br

            # If current stage is HOD, verify that an HOD is configured for this student's branch
            if stage.get("role_key") == "hod":
                has_hod = student_br.lower() in configured_hod_branches if student_br else False
                if not has_hod:
                    row["unassigned_hod"] = True
                    row["no_hod_configured"] = True
                    row["hod_warning"] = f"No HOD is configured for branch '{student_br or 'Unassigned'}'"

            if not is_vendor_admin or (role and role not in ("vendor_admin", "admin", "owner", "super_admin", "all")):
                if stage.get("role_key") != role:
                    continue
            if stage.get("department_scoped") and dept and not _student_matches_department(row, dept):
                continue
            pending.append(row)
        return jsonify({"requests": pending})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/history", methods=["GET"])
@require_feature("leave_management")
def get_admin_leave_history():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role")
    status = request.args.get("status", "all")
    
    if not role:
        return jsonify({"error": "Role required"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    caller_role = getattr(g, "user_role", None)
    is_vendor_admin = caller_role in ("vendor_admin", "admin", "owner", "super_admin")
    if not staff:
        if is_vendor_admin:
            staff = {"id": None, "name": getattr(g, "username", "Admin"), "role": role or "admin", "department": None}
        else:
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

        if status != "all":
            query += " AND lr.final_status = ?"
            params.append(status)
        
        # Invert parameters if Postgres
        if is_pg:
            query = query.replace('?', '%s')

        c.execute(query, tuple(params))
        rows = [get_row_dict(r) for r in c.fetchall()]
        attach_approval_steps(conn, rows)
        filtered = []
        for row in rows:
            matching = [step for step in row.get("approval_steps", []) if step.get("role_key") == role]
            if not matching:
                continue
            if any(step.get("department_scoped") for step in matching):
                # History follows the scope captured with the request, including
                # requests from an older workflow version.
                c.execute("SELECT department, custom_data FROM faces WHERE id = ?", (row["student_id"],))
                person = c.fetchone()
                person_data = get_row_dict(person) if person else {}
                row["student_dept"] = person_data.get("department") if isinstance(person_data, dict) else person[0]
                row["student_custom_data"] = person_data.get("custom_data") if isinstance(person_data, dict) else person[1]
                if not _student_matches_department(row, dept):
                    continue
            filtered.append(row)
        rows = filtered
        return jsonify({"history": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/approve", methods=["POST"])
@require_feature("leave_management")
def admin_approve_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    data = request.json
    request_id = data.get("request_id")
    role = data.get("role")
    action = data.get("action")
    
    if not all([request_id, role, action]):
        return jsonify({"error": "Missing fields"}), 400
    if action not in ALLOWED_LEAVE_ACTIONS:
        return jsonify({"error": "Action must be approved or rejected"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    caller_role = getattr(g, "user_role", None)
    is_vendor_admin = caller_role in ("vendor_admin", "admin", "owner", "super_admin")
    if not staff:
        if is_vendor_admin:
            staff = {"id": None, "name": getattr(g, "username", "Admin"), "role": role or "admin", "department": None}
        else:
            return jsonify({"error": "A valid staff PIN session is required"}), 403

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT lr.*, COALESCE(f.name, 'Resident') AS student_name, f.department AS student_dept,
                   f.custom_data AS student_custom_data
            FROM leave_requests lr LEFT JOIN faces f ON lr.student_id = f.id
            WHERE lr.id = ? AND lr.vendor_id = ? AND lr.final_status = 'pending'
        """, (request_id, vendor_id))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Leave request is no longer awaiting approval"}), 409
        request_row = get_row_dict(row)
        stages = snapshot_request(conn, vendor_id, request_id, request_row)
        stage = current_stage(stages)
        if not stage or (stage.get("actor_type") != "staff" and not is_vendor_admin):
            waiting_for = stage.get("display_name") if stage else "another stage"
            return jsonify({"error": f"Leave request is awaiting {waiting_for} approval"}), 409
        if not is_vendor_admin and stage.get("role_key") != role:
            waiting_for = stage.get("display_name") if stage else "another stage"
            return jsonify({"error": f"Leave request is awaiting {waiting_for} approval"}), 409
        if stage.get("department_scoped") and staff.get("department") and not _student_matches_department(request_row, staff.get("department")):
            return jsonify({"error": "This request is outside your assigned department"}), 403

        is_override = stage.get("actor_type") != "staff" and is_vendor_admin
        decide_current_stage(
            conn,
            vendor_id,
            request_row,
            action,
            actor_type="staff" if not is_override else stage.get("actor_type"),
            role_key=role if not is_override else stage.get("role_key"),
            actor_id=staff.get("id"),
            actor_name=f"{staff.get('name') or role} (Admin override)" if is_override else (staff.get("name") or role),
            metadata={"ip": request.remote_addr, "department": staff.get("department"), "override": is_override},
        )
        _notify_parent_when_current(conn, vendor_id, request_row)
        if action == "approved":
            new_steps = snapshot_request(conn, vendor_id, request_id)
            nxt_st = current_stage(new_steps)
            if nxt_st and nxt_st.get("actor_type") == "staff":
                _send_leave_stage_email_async(vendor_id, request_id, nxt_st)
            elif nxt_st and nxt_st.get("actor_type") == "parent":
                _notify_parent_when_current(conn, vendor_id, request_row)
        try:
            from services.evolution_whatsapp_service import notify_leave_event_async
            notify_leave_event_async(vendor_id, request_id, action)
        except Exception:
            pass
        return jsonify({"status": "success"})
    except (PermissionError, ValueError) as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/admin/generate-logins", methods=["POST"])
@require_feature("leave_management")
def generate_student_logins():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
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
            login_email = login_email_from_profile(cd)
            
            if not login_email:
                skipped_count += 1
                continue
                
            # Check if user already exists
            if is_pg:
                c.execute("SELECT username FROM system_users WHERE LOWER(username) = LOWER(%s)", (login_email,))
            else:
                c.execute("SELECT username FROM system_users WHERE LOWER(username) = LOWER(?)", (login_email,))
            if c.fetchone():
                skipped_count += 1
                continue
                
            # Create system user
            # Default password is the student's phone number.
            # Skip students without a phone instead of raising and rolling back
            # the entire batch (hash_password rejects empty strings).
            phone = (row.get('phone') or "").strip()
            if not phone:
                skipped_count += 1
                continue
            # Normalize the phone before hashing so login comparisons
            # (which also normalize) are format-agnostic.
            phone = phone.replace("+91", "").replace(" ", "").replace("-", "")
            if phone.startswith("0") and len(phone) > 10:
                phone = phone[1:]
            if is_pg:
                c.execute(
                    "INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (%s, %s, NULL, 'user', %s, %s)",
                    (login_email, hash_password(phone), vendor_id, row.get('id'))
                )
            else:
                c.execute(
                    "INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (?, ?, NULL, 'user', ?, ?)",
                    (login_email, hash_password(phone), vendor_id, row.get('id'))
                )
            created_count += 1
            
        conn.commit()
        return jsonify({
            "status": "success", 
            "created": created_count, 
            "skipped": skipped_count,
            "message": f"Successfully created {created_count} email-based student logins."
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
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    data = request.json
    pin = data.get("pin")
    
    if not pin:
        return jsonify({"error": "PIN required"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            c.execute("SELECT id, name, role, department, navbar_items FROM leave_staff WHERE vendor_id = %s AND pin = %s", (vendor_id, pin))
        else:
            c.execute("SELECT id, name, role, department, navbar_items FROM leave_staff WHERE vendor_id = ? AND pin = ?", (vendor_id, pin))
        staff = c.fetchone()
        if staff:
            res = get_row_dict(staff)
            if not isinstance(res, dict):
                res = {"id": staff[0], "name": staff[1], "role": staff[2], "department": staff[3], "navbar_items": staff[4]}
            res["navbar_items"] = load_staff_nav_items_for_features(
                res.get("navbar_items"), _vendor_subscription_features(c, vendor_id),
            )
            if "leave_management" not in res["navbar_items"]:
                return jsonify({"error": "Leave management is not enabled for this vendor"}), 403
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


@leave_bp.route("/admin/staff-session", methods=["GET"])
def get_staff_session():
    """Return fresh staff permissions without asking for the PIN again."""
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error:
        return role_error
    staff = _authenticated_leave_staff(vendor_id)
    if not staff:
        return jsonify({"error": "Staff session is invalid or no longer active", "code": "STAFF_SESSION_INVALID"}), 403
    return jsonify({"status": "success", "staff": staff})


@leave_bp.route("/admin/staff", methods=["GET", "POST", "PUT", "DELETE"], strict_slashes=False)
def manage_staff():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        vendor_features = _vendor_subscription_features(c, vendor_id)
        if request.method == "GET":
            if is_pg:
                c.execute("SELECT id, name, email, role, pin, department, navbar_items FROM leave_staff WHERE vendor_id = %s ORDER BY name, id", (vendor_id,))
            else:
                c.execute("SELECT id, name, email, role, pin, department, navbar_items FROM leave_staff WHERE vendor_id = ? ORDER BY name, id", (vendor_id,))
            staff = c.fetchall()
            payload = []
            for row in staff:
                item = get_row_dict(row)
                if not isinstance(item, dict):
                    item = {"id": row[0], "name": row[1], "email": row[2], "role": row[3], "pin": row[4], "department": row[5], "navbar_items": row[6]}
                item["navbar_items"] = load_staff_nav_items_for_features(
                    item.get("navbar_items"), vendor_features,
                )
                payload.append(item)
            return jsonify({"staff": payload})
            
        elif request.method == "POST":
            data = request.json or {}
            name = data.get("name")
            email = str(data.get("email") or "").strip() or None
            role = data.get("role")
            pin = data.get("pin")
            department = data.get("department")
            try:
                navbar_items = serialize_staff_nav_items_for_features(
                    data.get("navbar_items"), vendor_features,
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            
            if not all([name, role, pin]):
                return jsonify({"error": "Missing required fields"}), 400
                
            workflow = get_active_workflow(conn, vendor_id)
            matching_stages = [
                stage for stage in workflow["stages"]
                if stage.get("actor_type") == "staff" and stage.get("role_key") == role
            ]
            if not matching_stages:
                return jsonify({"error": "Role is not part of the active approval workflow"}), 400

            # Department-scoped roles require one approver per department.
            if any(stage.get("department_scoped") for stage in matching_stages):
                if not department:
                    return jsonify({"error": "Department required for this role"}), 400
                if is_pg:
                    c.execute("SELECT id FROM leave_staff WHERE vendor_id = %s AND LOWER(TRIM(department)) = LOWER(TRIM(%s)) AND role = %s", (vendor_id, department, role))
                else:
                    c.execute("SELECT id FROM leave_staff WHERE vendor_id = ? AND LOWER(TRIM(department)) = LOWER(TRIM(?)) AND role = ?", (vendor_id, department, role))
                if c.fetchone():
                    return jsonify({"error": f"An approver for this role is already assigned to {department}"}), 409

            # Check for duplicate PIN
            if is_pg:
                c.execute("SELECT id FROM leave_staff WHERE vendor_id = %s AND pin = %s", (vendor_id, pin))
            else:
                c.execute("SELECT id FROM leave_staff WHERE vendor_id = ? AND pin = ?", (vendor_id, pin))
            if c.fetchone():
                return jsonify({"error": "This PIN is already assigned to someone else"}), 409

            if is_pg:
                c.execute(
                    "INSERT INTO leave_staff (vendor_id, name, email, role, pin, department, navbar_items) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (vendor_id, name, email, role, pin, department, navbar_items)
                )
            else:
                c.execute(
                    "INSERT INTO leave_staff (vendor_id, name, email, role, pin, department, navbar_items) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (vendor_id, name, email, role, pin, department, navbar_items)
                )
            conn.commit()
            log_audit(
                "leave_staff_created",
                {"name": name, "email": email, "role": role, "department": department, "navbar_items": normalize_staff_nav_items(navbar_items)},
                target_vendor_id=vendor_id,
                actor=getattr(g, "username", None),
            )
            return jsonify({"status": "success", "message": "Staff added successfully"})

        elif request.method == "PUT":
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict):
                return jsonify({"error": "Invalid staff update"}), 400
            staff_id = data.get("id")
            if not staff_id:
                return jsonify({"error": "Staff id is required"}), 400

            if is_pg:
                c.execute(
                    "SELECT id, name, email, role, pin, department, navbar_items FROM leave_staff WHERE id = %s AND vendor_id = %s",
                    (staff_id, vendor_id),
                )
            else:
                c.execute(
                    "SELECT id, name, email, role, pin, department, navbar_items FROM leave_staff WHERE id = ? AND vendor_id = ?",
                    (staff_id, vendor_id),
                )
            current_row = c.fetchone()
            if not current_row:
                return jsonify({"error": "Staff member not found"}), 404
            current = get_row_dict(current_row)
            if not isinstance(current, dict):
                current = {
                    "id": current_row[0],
                    "name": current_row[1],
                    "email": current_row[2],
                    "role": current_row[3],
                    "pin": current_row[4],
                    "department": current_row[5],
                    "navbar_items": current_row[6],
                }

            name = str(data.get("name", current.get("name")) or "").strip()
            email = str(data.get("email", current.get("email")) or "").strip() or None
            role = str(data.get("role", current.get("role")) or "").strip()
            pin = str(data.get("pin", current.get("pin")) or "").strip()
            department = str(data.get("department", current.get("department")) or "").strip()
            if not all((name, role, pin)):
                return jsonify({"error": "Name, role, and PIN are required"}), 400
            profile_update = any(
                field in data for field in ("name", "role", "pin", "department")
            )
            if profile_update and (not pin.isdigit() or len(pin) != 4):
                return jsonify({"error": "PIN must contain exactly 4 digits"}), 400

            if profile_update:
                workflow = get_active_workflow(conn, vendor_id)
                matching_stages = [
                    stage for stage in workflow["stages"]
                    if stage.get("actor_type") == "staff" and stage.get("role_key") == role
                ]
                if not matching_stages:
                    return jsonify({"error": "Role is not part of the active approval workflow"}), 400

                department_scoped = any(stage.get("department_scoped") for stage in matching_stages)
                if department_scoped and not department:
                    return jsonify({"error": "Department required for this role"}), 400
                if not department_scoped:
                    department = None

            if profile_update and department_scoped:
                if is_pg:
                    c.execute(
                        "SELECT id FROM leave_staff WHERE vendor_id = %s AND LOWER(TRIM(department)) = LOWER(TRIM(%s)) AND role = %s AND id <> %s",
                        (vendor_id, department, role, staff_id),
                    )
                else:
                    c.execute(
                        "SELECT id FROM leave_staff WHERE vendor_id = ? AND LOWER(TRIM(department)) = LOWER(TRIM(?)) AND role = ? AND id <> ?",
                        (vendor_id, department, role, staff_id),
                    )
                if c.fetchone():
                    return jsonify({"error": f"An approver for this role is already assigned to {department}"}), 409

            if profile_update:
                if is_pg:
                    c.execute(
                        "SELECT id FROM leave_staff WHERE vendor_id = %s AND pin = %s AND id <> %s",
                        (vendor_id, pin, staff_id),
                    )
                else:
                    c.execute(
                        "SELECT id FROM leave_staff WHERE vendor_id = ? AND pin = ? AND id <> ?",
                        (vendor_id, pin, staff_id),
                    )
                if c.fetchone():
                    return jsonify({"error": "This PIN is already assigned to someone else"}), 409

            try:
                navbar_items = serialize_staff_nav_items_for_features(
                    data.get("navbar_items", current.get("navbar_items")), vendor_features,
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

            if is_pg:
                c.execute(
                    "UPDATE leave_staff SET name = %s, email = %s, role = %s, pin = %s, department = %s, navbar_items = %s WHERE id = %s AND vendor_id = %s",
                    (name, email, role, pin, department, navbar_items, staff_id, vendor_id),
                )
            else:
                c.execute(
                    "UPDATE leave_staff SET name = ?, email = ?, role = ?, pin = ?, department = ?, navbar_items = ? WHERE id = ? AND vendor_id = ?",
                    (name, email, role, pin, department, navbar_items, staff_id, vendor_id),
                )
            if not c.rowcount:
                return jsonify({"error": "Staff member not found"}), 404
            conn.commit()
            normalized_items = normalize_staff_nav_items(navbar_items)
            log_audit(
                "leave_staff_updated",
                {
                    "staff_id": staff_id,
                    "previous_name": current.get("name"),
                    "previous_email": current.get("email"),
                    "previous_role": current.get("role"),
                    "previous_department": current.get("department"),
                    "name": name,
                    "email": email,
                    "role": role,
                    "department": department,
                    "navbar_items": normalized_items,
                },
                target_vendor_id=vendor_id,
                actor=getattr(g, "username", None),
            )
            return jsonify({
                "status": "success",
                "staff": {
                    "id": staff_id,
                    "name": name,
                    "email": email,
                    "role": role,
                    "pin": pin,
                    "department": department,
                    "navbar_items": normalized_items,
                },
            })
            
        elif request.method == "DELETE":
            staff_id = request.args.get("id")
            if is_pg:
                c.execute("DELETE FROM leave_staff WHERE id = %s AND vendor_id = %s", (staff_id, vendor_id))
            else:
                c.execute("DELETE FROM leave_staff WHERE id = ? AND vendor_id = ?", (staff_id, vendor_id))
            conn.commit()
            log_audit(
                "leave_staff_deleted",
                {"staff_id": staff_id},
                target_vendor_id=vendor_id,
                actor=getattr(g, "username", None),
            )
            return jsonify({"status": "success"})
    finally:
        conn.close()


@leave_bp.route("/admin/workflow", methods=["GET", "PUT"])
@require_feature("leave_management")
def manage_leave_workflow():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    conn = get_db_connection()
    try:
        if request.method == "GET":
            return jsonify({"workflow": get_active_workflow(conn, vendor_id)})

        # Workflow configuration can only be modified by super_admin
        if getattr(g, "user_role", None) != "super_admin":
            return jsonify({"error": "Workflow configuration can only be modified by SuperAdmin."}), 403

        payload = request.get_json(silent=True) or {}
        try:
            workflow = replace_workflow(
                conn,
                vendor_id,
                payload.get("name") or "Leave Approval",
                payload.get("stages"),
                getattr(g, "username", None) or "administrator",
            )
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        return jsonify({
            "status": "success",
            "workflow": workflow,
            "message": "Workflow saved. Existing leave requests keep their original approval path.",
        })
    finally:
        conn.close()


@leave_bp.route("/student/workflow", methods=["GET"])
@require_feature("leave_management")
def get_student_leave_workflow():
    """Return the active approval path without exposing approver credentials."""
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    role_error = _require_role("user", "student")
    if role_error:
        return role_error

    conn = get_db_connection()
    try:
        workflow = get_active_workflow(conn, vendor_id)
        return jsonify({
            "workflow": {
                "name": workflow.get("name"),
                "version": workflow.get("version"),
                "stages": [
                    {
                        "stage_key": stage.get("stage_key"),
                        "display_name": stage.get("display_name"),
                        "sequence": stage.get("sequence"),
                        "department_scoped": bool(stage.get("department_scoped")),
                    }
                    for stage in workflow.get("stages", [])
                ],
            }
        })
    finally:
        conn.close()

@leave_bp.route("/admin/departments", methods=["GET", "POST", "DELETE"], strict_slashes=False)
def manage_departments():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
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
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
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

@leave_bp.route("/parent-faces/<int:parent_id>", methods=["DELETE"])
def delete_parent_face(parent_id):
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT student_number FROM parent_users WHERE id = ? AND vendor_id = ?", (parent_id, vendor_id))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Parent record not found"}), 404
        sn = row[0] if not hasattr(row, 'keys') else row['student_number']
        c.execute("DELETE FROM student_parents WHERE parent_id = ? AND vendor_id = ?", (parent_id, vendor_id))
        if sn:
            c.execute("DELETE FROM parent_tokens WHERE student_number = ? AND vendor_id = ?", (str(sn).strip(), vendor_id))
        c.execute("DELETE FROM parent_users WHERE id = ? AND vendor_id = ?", (parent_id, vendor_id))
        conn.commit()
        return jsonify({"status": "success", "message": "Parent account and face registration deleted."})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@leave_bp.route("/student/history", methods=["GET"])
@require_feature("leave_management")
def get_student_history():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    role_error = _require_role("user", "student")
    if role_error:
        return role_error

    student_number = getattr(g, "username", None)
    import logging
    logger = logging.getLogger(__name__)
    logger.info("History fetch: user=%s, vendor=%s", student_number, vendor_id)

    if not student_number or not vendor_id:
        return jsonify({"error": "Authenticated student account is incomplete"}), 401

    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)

        # The account-to-person link is authoritative. It prevents a student
        # from reading another student's history by changing request data.
        if is_pg:
            c.execute(
                """SELECT person_id FROM system_users
                   WHERE vendor_id = %s AND username = %s
                     AND role IN ('user', 'student') AND person_id IS NOT NULL""",
                (vendor_id, student_number),
            )
        else:
            c.execute(
                """SELECT person_id FROM system_users
                   WHERE vendor_id = ? AND username = ?
                     AND role IN ('user', 'student') AND person_id IS NOT NULL""",
                (vendor_id, student_number),
            )
        account_row = c.fetchone()
        if account_row:
            account_data = get_row_dict(account_row)
            person_id = account_data.get("person_id") if isinstance(account_data, dict) else account_row[0]
        else:
            person_id = None

        # Compatibility fallback for accounts created before person_id was
        # persisted on system_users.
        if person_id is None and is_pg:
            c.execute("""
                SELECT id FROM faces 
                WHERE vendor_id = %s AND (
                    id::text = %s OR
                    LOWER(TRIM(custom_data::jsonb->>'student_id')) = LOWER(TRIM(%s)) OR
                    LOWER(TRIM(custom_data::jsonb->>'id_number')) = LOWER(TRIM(%s)) OR
                    LOWER(TRIM(custom_data::jsonb->>'employee_id')) = LOWER(TRIM(%s))
                )
            """, (vendor_id, student_number, student_number, student_number, student_number))
        elif person_id is None:
            c.execute("""
                SELECT id FROM faces 
                WHERE vendor_id = ? AND (
                    CAST(id AS TEXT) = ? OR
                    LOWER(TRIM(json_extract(custom_data, '$.student_id'))) = LOWER(TRIM(?)) OR
                    LOWER(TRIM(json_extract(custom_data, '$.id_number'))) = LOWER(TRIM(?)) OR
                    LOWER(TRIM(json_extract(custom_data, '$.employee_id'))) = LOWER(TRIM(?))
                )
            """, (vendor_id, student_number, student_number, student_number, student_number))

        if person_id is None:
            face_row = c.fetchone()
            if face_row:
                face_data = get_row_dict(face_row)
                person_id = face_data.get("id") if isinstance(face_data, dict) else face_row[0]

        if person_id is None:
            logger.warning("Student history account is not linked: user=%s vendor=%s", student_number, vendor_id)
            return jsonify({"error": "Student account is not linked to a resident record"}), 409

        logger.info("Resolved history user=%s to person_id=%s", student_number, person_id)

        # Now fetch all requests for this person_id with student name
        if is_pg:
            c.execute("""
                SELECT lr.*, f.name as student_name 
                FROM leave_requests lr
                LEFT JOIN faces f ON lr.student_id = f.id AND f.vendor_id = lr.vendor_id
                WHERE lr.student_id = %s AND lr.vendor_id = %s 
                ORDER BY lr.created_at DESC
            """, (person_id, vendor_id))
        else:
            c.execute("""
                SELECT lr.*, f.name as student_name 
                FROM leave_requests lr
                LEFT JOIN faces f ON lr.student_id = f.id AND f.vendor_id = lr.vendor_id
                WHERE lr.student_id = ? AND lr.vendor_id = ? 
                ORDER BY lr.created_at DESC
            """, (person_id, vendor_id))
            
        rows = [get_row_dict(r) for r in c.fetchall()]
        attach_approval_steps(conn, rows)
        return jsonify({"status": "success", "requests": rows})
    finally:
        conn.close()


@leave_bp.route("/student/cancel-request", methods=["POST"])
@leave_bp.route("/cancel-request", methods=["POST"])
@require_feature("leave_management")
def cancel_leave_request():
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    role_error = _require_role("user", "student", "parent")
    if role_error:
        return role_error

    data = request.json or {}
    request_id = data.get("request_id")
    cancellation_reason = (data.get("cancellation_reason") or "").strip()

    if not request_id:
        return jsonify({"error": "Missing request_id"}), 400
    if not cancellation_reason:
        return jsonify({"error": "Please provide a reason for cancelling this leave"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        caller_role = getattr(g, "user_role", None)

        # 1. Resolve student ID
        person_id = None
        if caller_role == "parent":
            parent = _authenticated_parent(c, vendor_id)
            if not parent:
                return jsonify({"error": "Parent access required"}), 403
            person_id = parent.get("selected_person_id")
        else:
            username = getattr(g, "username", None)
            if not username:
                return jsonify({"error": "Student account required"}), 401
            if is_pg:
                c.execute(
                    "SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s AND person_id IS NOT NULL",
                    (vendor_id, username),
                )
            else:
                c.execute(
                    "SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ? AND person_id IS NOT NULL",
                    (vendor_id, username),
                )
            acct = c.fetchone()
            if acct:
                person_id = acct["person_id"] if hasattr(acct, "keys") else acct[0]
            if person_id is None:
                if is_pg:
                    c.execute("""SELECT id FROM faces WHERE vendor_id = %s AND (
                        id::text = %s OR
                        LOWER(TRIM(custom_data::jsonb->>'student_id')) = LOWER(TRIM(%s)) OR
                        LOWER(TRIM(custom_data::jsonb->>'id_number')) = LOWER(TRIM(%s)) OR
                        LOWER(TRIM(custom_data::jsonb->>'employee_id')) = LOWER(TRIM(%s))
                    )""", (vendor_id, username, username, username, username))
                else:
                    c.execute("""SELECT id FROM faces WHERE vendor_id = ? AND (
                        CAST(id AS TEXT) = ? OR
                        LOWER(TRIM(json_extract(custom_data, '$.student_id'))) = LOWER(TRIM(?)) OR
                        LOWER(TRIM(json_extract(custom_data, '$.id_number'))) = LOWER(TRIM(?)) OR
                        LOWER(TRIM(json_extract(custom_data, '$.employee_id'))) = LOWER(TRIM(?))
                    )""", (vendor_id, username, username, username, username))
                fc = c.fetchone()
                if fc:
                    person_id = fc["id"] if hasattr(fc, "keys") else fc[0]

        if person_id is None:
            return jsonify({"error": "Could not identify student record"}), 404

        # 2. Fetch the target leave request
        if is_pg:
            c.execute("""
                SELECT lr.*, f.name as student_name
                FROM leave_requests lr
                LEFT JOIN faces f ON lr.student_id = f.id
                WHERE lr.id = %s AND lr.vendor_id = %s AND lr.student_id = %s
            """, (request_id, vendor_id, person_id))
        else:
            c.execute("""
                SELECT lr.*, f.name as student_name
                FROM leave_requests lr
                LEFT JOIN faces f ON lr.student_id = f.id
                WHERE lr.id = ? AND lr.vendor_id = ? AND lr.student_id = ?
            """, (request_id, vendor_id, person_id))
        req_row = c.fetchone()
        if not req_row:
            return jsonify({"error": "Leave request not found or does not belong to you"}), 404

        req = get_row_dict(req_row)
        current_final = str(req.get("final_status") or "").lower()
        if current_final == "cancelled":
            return jsonify({"error": "This leave request has already been cancelled"}), 400
        if current_final == "rejected":
            return jsonify({"error": "Cannot cancel an already rejected leave request"}), 400
        if int(req.get("is_cancellation") or 0) == 1 and req.get("cancellation_status") == "pending":
            return jsonify({"error": "A cancellation request is already pending parent approval"}), 400

        # 3. Update leave_requests with cancellation intent
        if is_pg:
            c.execute("""
                UPDATE leave_requests
                SET is_cancellation = 1,
                    cancellation_reason = %s,
                    cancellation_status = 'pending',
                    final_status = 'pending',
                    parent_status = 'pending'
                WHERE id = %s AND vendor_id = %s
            """, (cancellation_reason, request_id, vendor_id))
        else:
            c.execute("""
                UPDATE leave_requests
                SET is_cancellation = 1,
                    cancellation_reason = ?,
                    cancellation_status = 'pending',
                    final_status = 'pending',
                    parent_status = 'pending'
                WHERE id = ? AND vendor_id = ?
            """, (cancellation_reason, request_id, vendor_id))

        # 4. In leave_request_stages, ensure stages exist and reset parent stage to pending
        snapshot_request(conn, vendor_id, request_id, req)
        if is_pg:
            c.execute("""
                UPDATE leave_request_stages
                SET status = 'pending', decided_at = NULL, actor_id = NULL, actor_name = NULL, decision_metadata = NULL
                WHERE request_id = %s AND vendor_id = %s AND actor_type = 'parent'
            """, (request_id, vendor_id))
        else:
            c.execute("""
                UPDATE leave_request_stages
                SET status = 'pending', decided_at = NULL, actor_id = NULL, actor_name = NULL, decision_metadata = NULL
                WHERE request_id = ? AND vendor_id = ? AND actor_type = 'parent'
            """, (request_id, vendor_id))

        conn.commit()

        # 5. Send FCM push notification to parent
        try:
            from notifications import notify_parent_async
            student_name = req.get("student_name") or "Your student"
            orig_type = str(req.get("leave_type") or "leave").replace("_", " ").title()
            notify_parent_async(
                person_id,
                vendor_id,
                "Leave Cancellation awaiting your approval",
                f"{student_name} requested to cancel their leave ({orig_type}). Please review and approve with face verification.",
                {
                    "type": "leave_approval",
                    "request_id": str(request_id),
                    "stage": "parent",
                },
            )
        except Exception as ex:
            import logging
            logging.getLogger(__name__).warning("Could not send cancellation FCM: %s", ex)

        return jsonify({
            "status": "success",
            "message": "Leave cancellation request submitted successfully. Awaiting parent face approval."
        })
    finally:
        conn.close()


# ==============================================================================
# LIVE DYNAMIC STATUS BADGE (FOR EMAILS)
# ==============================================================================

def _generate_status_badge_png(status_key):
    """
    Generate an anti-aliased high-DPI (2x) PNG status pill badge.
    Works with Pillow ImageDraw.
    """
    import io
    import os
    from PIL import Image, ImageDraw, ImageFont

    width, height = 520, 72
    corner_radius = height // 2

    config = {
        "pending": {
            "bg": (239, 246, 255, 255),         # #eff6ff
            "border": (147, 197, 253, 255),     # #93c5fd
            "dot": (37, 99, 235, 255),          # #2563eb
            "text_color": (29, 78, 216, 255),   # #1d4ed8
            "label": "Action Required · Pending Review",
        },
        "approved": {
            "bg": (241, 245, 249, 255),         # #f1f5f9
            "border": (203, 213, 225, 255),     # #cbd5e1
            "dot": (16, 185, 129, 255),         # #10b981
            "text_color": (71, 85, 105, 255),   # #475569
            "label": "Completed · Already Approved",
        },
        "cancelled": {
            "bg": (248, 250, 252, 255),         # #f8fafc
            "border": (226, 232, 240, 255),     # #e2e8f0
            "dot": (148, 163, 184, 255),        # #94a3b8
            "text_color": (100, 116, 139, 255), # #64748b
            "label": "Cancelled · Request Withdrawn",
        },
        "rejected": {
            "bg": (254, 242, 242, 255),         # #fef2f2
            "border": (254, 202, 202, 255),     # #fecaca
            "dot": (239, 68, 68, 255),          # #ef4444
            "text_color": (153, 27, 27, 255),   # #991b1b
            "label": "Closed · Request Rejected",
        },
    }

    style = config.get(status_key, config["pending"])

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        draw.rounded_rectangle(
            [(2, 2), (width - 3, height - 3)],
            radius=corner_radius,
            fill=style["bg"],
            outline=style["border"],
            width=3,
        )
    except AttributeError:
        draw.rectangle(
            [(2, 2), (width - 3, height - 3)],
            fill=style["bg"],
            outline=style["border"],
            width=3,
        )

    # Indicator circle
    dot_radius = 11
    dot_cx = 44
    dot_cy = height // 2
    draw.ellipse(
        [
            (dot_cx - dot_radius, dot_cy - dot_radius),
            (dot_cx + dot_radius, dot_cy + dot_radius),
        ],
        fill=style["dot"],
    )

    # Font setup
    font = None
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for p in font_paths:
        try:
            if os.path.exists(p):
                font = ImageFont.truetype(p, 23)
                break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default()
        except Exception:
            pass

    text_x = 72
    try:
        bbox = font.getbbox(style["label"])
        text_h = bbox[3] - bbox[1]
        text_y = (height - text_h) // 2 - bbox[1]
    except Exception:
        text_y = (height // 2) - 12

    draw.text((text_x, text_y), style["label"], fill=style["text_color"], font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _generate_status_badge_svg(status_key):
    """Fallback vector SVG badge."""
    config = {
        "pending": ("#eff6ff", "#93c5fd", "#2563eb", "#1d4ed8", "Action Required · Pending Review"),
        "approved": ("#f1f5f9", "#cbd5e1", "#10b981", "#475569", "Completed · Already Approved"),
        "cancelled": ("#f8fafc", "#e2e8f0", "#94a3b8", "#64748b", "Cancelled · Request Withdrawn"),
        "rejected": ("#fef2f2", "#fecaca", "#ef4444", "#991b1b", "Closed · Request Rejected"),
    }
    bg, border, dot, text_color, label = config.get(status_key, config["pending"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="260" height="36" viewBox="0 0 260 36">
  <rect x="0.5" y="0.5" width="259" height="35" rx="18" fill="{bg}" stroke="{border}" stroke-width="1.5"/>
  <circle cx="20" cy="18" r="5" fill="{dot}"/>
  <text x="34" y="22" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" font-size="12" font-weight="600" fill="{text_color}">{label}</text>
</svg>"""


@leave_bp.route("/requests/<int:request_id>/status-badge.png", methods=["GET"])
@leave_bp.route("/requests/<int:request_id>/status-badge.svg", methods=["GET"])
@leave_bp.route("/requests/<int:request_id>/status-badge", methods=["GET"])
def get_leave_status_badge(request_id):
    """
    Public dynamic status badge for email clients.
    Re-evaluates leave status in real-time every time the email is opened.
    Disables browser & mail proxy caching via strict headers.
    """
    from flask import Response
    from utils import get_db_connection

    status_key = "pending"
    try:
        conn = get_db_connection()
        c = conn.cursor()
        is_pg = getattr(conn, "_is_pg", False)
        try:
            if is_pg:
                c.execute("""
                    SELECT final_status, cancellation_status, is_cancellation
                    FROM leave_requests
                    WHERE id = %s
                """, (request_id,))
            else:
                c.execute("""
                    SELECT final_status, cancellation_status, is_cancellation
                    FROM leave_requests
                    WHERE id = ?
                """, (request_id,))
            row = c.fetchone()
            if row:
                final_status = str(row[0] or "").lower()
                cancellation_status = str(row[1] or "").lower()

                if final_status == "cancelled" or cancellation_status == "approved":
                    status_key = "cancelled"
                elif final_status == "rejected":
                    status_key = "rejected"
                elif final_status == "approved":
                    status_key = "approved"
                else:
                    status_key = "pending"
        finally:
            conn.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Error fetching leave badge status for #%s: %s", request_id, e)
        status_key = "pending"

    is_svg_requested = request.path.endswith(".svg") or "svg" in request.headers.get("Accept", "")

    if is_svg_requested:
        svg_content = _generate_status_badge_svg(status_key)
        resp = Response(svg_content, mimetype="image/svg+xml")
    else:
        try:
            png_bytes = _generate_status_badge_png(status_key)
            resp = Response(png_bytes, mimetype="image/png")
        except Exception as ex:
            import logging
            logging.getLogger(__name__).warning("PNG badge generation failed, falling back to SVG: %s", ex)
            svg_content = _generate_status_badge_svg(status_key)
            resp = Response(svg_content, mimetype="image/svg+xml")

    # Anti-caching headers for email proxies (Gmail Image Proxy, Yahoo, Outlook)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, post-check=0, pre-check=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

