"""Build role-scoped web notifications from existing operational records."""

from __future__ import annotations

import json
import re
from datetime import date, datetime


NOTIFICATION_KEY_RE = re.compile(r"^[A-Za-z0-9:_-]{1,160}$")


def _row_dict(row):
    if row is None:
        return None
    try:
        return dict(row)
    except (TypeError, ValueError):
        return row


def _iso(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _item(key, category, title, message, created_at, href, priority="normal"):
    return {
        "key": key,
        "category": category,
        "title": title,
        "message": message,
        "created_at": _iso(created_at),
        "href": href,
        "priority": priority,
    }


def _normalize_department(value):
    value = re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())
    aliases = {
        "cs": "computer",
        "cse": "computer",
        "comp": "computer",
        "computerscience": "computer",
        "computerscienceandengineering": "computer",
        "it": "it",
        "informationtechnology": "it",
        "mech": "mechanical",
        "mechanicalengineering": "mechanical",
        "civilengineering": "civil",
        "entc": "entc",
        "extc": "entc",
        "electronicstelecommunication": "entc",
        "electronicsandtelecommunication": "entc",
        "electricalengineering": "electrical",
    }
    return aliases.get(value, value)


def _student_department(row):
    row = row if isinstance(row, dict) else {}
    custom = {}
    raw = row.get("custom_data")
    if raw:
        try:
            custom = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            custom = {}
    return (
        row.get("department")
        or custom.get("department")
        or custom.get("Department")
        or custom.get("branch")
        or custom.get("Branch")
        or custom.get("stream")
        or ""
    )


def _fetch_current_leave_stages(cursor, vendor_id):
    cursor.execute(
        """
        SELECT lr.id, lr.leave_type, lr.start_date, lr.end_date, lr.created_at,
               f.name AS student_name, f.department, f.custom_data,
               lrs.stage_key, lrs.display_name, lrs.role_key,
               lrs.department_scoped, lrs.created_at AS stage_created_at
          FROM leave_requests lr
          JOIN faces f ON f.id = lr.student_id AND f.vendor_id = lr.vendor_id
          JOIN leave_request_stages lrs
            ON lrs.request_id = lr.id AND lrs.vendor_id = lr.vendor_id
         WHERE lr.vendor_id = ?
           AND LOWER(COALESCE(lr.final_status, 'pending')) = 'pending'
           AND LOWER(COALESCE(lrs.status, 'pending')) = 'pending'
           AND NOT EXISTS (
                SELECT 1
                  FROM leave_request_stages earlier
                 WHERE earlier.request_id = lrs.request_id
                   AND earlier.vendor_id = lrs.vendor_id
                   AND earlier.sequence < lrs.sequence
                   AND LOWER(COALESCE(earlier.status, 'pending')) <> 'approved'
           )
         ORDER BY COALESCE(lrs.created_at, lr.created_at) DESC
         LIMIT 80
        """,
        (vendor_id,),
    )
    return [_row_dict(row) for row in cursor.fetchall()]


def _leave_action_items(cursor, principal):
    role = str(principal.get("role") or "").strip().lower()
    vendor_id = principal.get("vendor_id")
    department = principal.get("department")
    show_all = role in {"admin", "vendor_admin"}
    if not show_all and role not in {"rector", "hod", "faculty", "warden", "staff"}:
        return []

    items = []
    for row in _fetch_current_leave_stages(cursor, vendor_id):
        stage_role = str(row.get("role_key") or "").strip().lower()
        if not show_all and stage_role != role:
            continue
        if not show_all and row.get("department_scoped"):
            if not department or _normalize_department(_student_department(row)) != _normalize_department(department):
                continue
        student = row.get("student_name") or "Student"
        stage = row.get("display_name") or stage_role.replace("_", " ").title() or "Approval"
        start = _iso(row.get("start_date")) or ""
        end = _iso(row.get("end_date")) or start
        items.append(
            _item(
                f"leave-action:{row['id']}:{row.get('stage_key') or stage_role}",
                "leave",
                "Leave approval pending",
                f"{student} · {stage} · {start} to {end}",
                row.get("stage_created_at") or row.get("created_at"),
                "/leave-management?tab=pending",
                "high",
            )
        )
    return items


def _personal_leave_items(cursor, principal):
    person_id = principal.get("person_id")
    if not person_id:
        return []
    cursor.execute(
        """
        SELECT lr.id, lr.leave_type, lr.start_date, lr.end_date, lr.final_status,
               lr.cancellation_status, lr.created_at,
               COALESCE(
                   (SELECT MAX(decided_at) FROM leave_request_stages decided
                     WHERE decided.request_id = lr.id AND decided.vendor_id = lr.vendor_id),
                   lr.created_at
               ) AS activity_at,
               lrs.stage_key, lrs.display_name
          FROM leave_requests lr
          LEFT JOIN leave_request_stages lrs
            ON lrs.request_id = lr.id
           AND lrs.vendor_id = lr.vendor_id
           AND LOWER(COALESCE(lrs.status, 'pending')) = 'pending'
           AND NOT EXISTS (
                SELECT 1 FROM leave_request_stages earlier
                 WHERE earlier.request_id = lrs.request_id
                   AND earlier.vendor_id = lrs.vendor_id
                   AND earlier.sequence < lrs.sequence
                   AND LOWER(COALESCE(earlier.status, 'pending')) <> 'approved'
           )
         WHERE lr.vendor_id = ? AND lr.student_id = ?
         ORDER BY lr.created_at DESC
         LIMIT 20
        """,
        (principal.get("vendor_id"), person_id),
    )
    items = []
    for raw in cursor.fetchall():
        row = _row_dict(raw)
        status = str(row.get("final_status") or "pending").strip().lower()
        stage_key = row.get("stage_key") or "complete"
        cancellation = str(row.get("cancellation_status") or "").strip().lower()
        leave_type = str(row.get("leave_type") or "Leave").replace("_", " ").title()
        if cancellation in {"approved", "cancelled"}:
            title = "Leave cancelled"
            message = f"{leave_type} request #{row['id']} was cancelled."
            category = "leave"
        elif status == "approved":
            title = "Leave approved"
            message = f"{leave_type} request #{row['id']} has completed the approval cycle."
            category = "success"
        elif status == "rejected":
            title = "Leave rejected"
            message = f"{leave_type} request #{row['id']} was not approved."
            category = "warning"
        else:
            stage = row.get("display_name") or "the next approver"
            title = "Leave request in review"
            message = f"Request #{row['id']} is awaiting {stage}."
            category = "leave"
        items.append(
            _item(
                f"leave:{row['id']}:{status}:{stage_key}:{cancellation or 'active'}",
                category,
                title,
                message,
                row.get("activity_at") or row.get("created_at"),
                "/leave-management?tab=history",
            )
        )
    return items


def _advance_items(cursor, principal):
    if principal.get("role") != "owner":
        return []
    cursor.execute(
        """
        SELECT a.id, a.amount, a.created_at, f.name AS employee_name
          FROM advances a
          JOIN faces f ON f.id = a.person_id AND f.vendor_id = a.vendor_id
         WHERE a.vendor_id = ? AND LOWER(COALESCE(a.status, 'pending')) = 'pending'
         ORDER BY a.created_at DESC
         LIMIT 30
        """,
        (principal.get("vendor_id"),),
    )
    return [
        _item(
            f"advance:{row['id']}:pending",
            "advance",
            "Advance approval pending",
            f"{row.get('employee_name') or 'Employee'} requested ₹{float(row.get('amount') or 0):,.2f}.",
            row.get("created_at"),
            "/owner/advances",
            "high",
        )
        for row in (_row_dict(raw) for raw in cursor.fetchall())
    ]


def _face_reset_items(cursor, principal):
    if principal.get("role") not in {"admin", "vendor_admin"}:
        return []
    if "parent_login" not in principal.get("features", set()):
        return []
    cursor.execute(
        """
        SELECT fr.id, fr.reason, fr.created_at, pu.username AS parent_username
          FROM face_reset_requests fr
          LEFT JOIN parent_users pu ON pu.id = fr.parent_id AND pu.vendor_id = fr.vendor_id
         WHERE fr.vendor_id = ? AND LOWER(COALESCE(fr.status, 'pending')) = 'pending'
         ORDER BY fr.created_at DESC
         LIMIT 30
        """,
        (principal.get("vendor_id"),),
    )
    return [
        _item(
            f"face-reset:{row['id']}:pending",
            "security",
            "Face reset requires review",
            f"Request from {row.get('parent_username') or 'a parent account'}.",
            row.get("created_at"),
            "/face-reset-requests",
            "high",
        )
        for row in (_row_dict(raw) for raw in cursor.fetchall())
    ]


def _hostel_alert_items(cursor, principal):
    role = principal.get("role")
    staff_nav = set(principal.get("navbar_items") or [])
    permitted = role in {"admin", "vendor_admin", "owner"} or "hostel_alerts" in staff_nav
    if not permitted or "hostel_attendance_alerts" not in principal.get("features", set()):
        return []
    cursor.execute(
        """
        SELECT d.id, d.alert_type, d.status, d.attempts, d.error, d.created_at,
               f.name AS student_name
          FROM hostel_alert_deliveries d
          LEFT JOIN faces f ON f.id = d.person_id AND f.vendor_id = d.vendor_id
         WHERE d.vendor_id = ? AND LOWER(COALESCE(d.status, '')) IN ('failed', 'error')
         ORDER BY d.created_at DESC
         LIMIT 20
        """,
        (principal.get("vendor_id"),),
    )
    return [
        _item(
            f"hostel-alert:{row['id']}:{row.get('status')}:{row.get('attempts') or 0}",
            "warning",
            "Hostel alert delivery failed",
            f"{row.get('student_name') or 'Student'} · {str(row.get('alert_type') or 'alert').replace('_', ' ')}",
            row.get("created_at"),
            "/hostel-alerts",
            "high",
        )
        for row in (_row_dict(raw) for raw in cursor.fetchall())
    ]


def _super_admin_items(cursor, principal):
    if principal.get("role") != "super_admin":
        return []
    cursor.execute(
        """
        SELECT id, actor_username, action, target_vendor_id, timestamp
          FROM audit_logs
         ORDER BY timestamp DESC
         LIMIT 25
        """
    )
    items = []
    for raw in cursor.fetchall():
        row = _row_dict(raw)
        action = str(row.get("action") or "system activity").replace("_", " ").title()
        vendor = f" · Vendor {row.get('target_vendor_id')}" if row.get("target_vendor_id") else ""
        items.append(
            _item(
                f"audit:{row['id']}",
                "system",
                action,
                f"{row.get('actor_username') or 'System'}{vendor}",
                row.get("timestamp"),
                "/admin/audit-logs",
            )
        )
    return items


def build_notification_center(conn, principal, limit=40):
    """Return notifications visible to a single authenticated principal."""
    cursor = conn.cursor()
    try:
        items = []
        role = str(principal.get("role") or "").strip().lower()
        if role == "super_admin":
            items.extend(_super_admin_items(cursor, principal))
        else:
            features = principal.get("features", set())
            if "leave_management" in features or "parent_login" in features:
                if role in {"student", "user", "parent"} and principal.get("person_id"):
                    items.extend(_personal_leave_items(cursor, principal))
                else:
                    items.extend(_leave_action_items(cursor, principal))
            items.extend(_advance_items(cursor, principal))
            items.extend(_face_reset_items(cursor, principal))
            items.extend(_hostel_alert_items(cursor, principal))

        cursor.execute(
            """SELECT notification_key FROM notification_read_receipts
                 WHERE scope_vendor_id = ? AND principal_key = ?""",
            (principal.get("scope_vendor_id", 0), principal["principal_key"]),
        )
        read_keys = set()
        for raw in cursor.fetchall():
            row = _row_dict(raw)
            read_keys.add(row.get("notification_key") if isinstance(row, dict) else raw[0])
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        items = items[: max(1, min(int(limit or 40), 100))]
        for item in items:
            item["read"] = item["key"] in read_keys
        return items
    finally:
        cursor.close()


def mark_notifications_read(conn, principal, keys):
    clean_keys = []
    seen = set()
    for value in keys or []:
        key = str(value or "").strip()
        if key in seen or not NOTIFICATION_KEY_RE.fullmatch(key):
            continue
        seen.add(key)
        clean_keys.append(key)
        if len(clean_keys) >= 100:
            break
    if not clean_keys:
        return 0

    cursor = conn.cursor()
    try:
        for key in clean_keys:
            cursor.execute(
                """
                INSERT INTO notification_read_receipts
                    (scope_vendor_id, principal_key, notification_key, read_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(scope_vendor_id, principal_key, notification_key)
                DO UPDATE SET read_at = CURRENT_TIMESTAMP
                """,
                (principal.get("scope_vendor_id", 0), principal["principal_key"], key),
            )
        conn.commit()
        return len(clean_keys)
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
