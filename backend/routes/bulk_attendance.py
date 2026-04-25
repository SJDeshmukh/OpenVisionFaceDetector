"""
Bulk Attendance (Lecture-based) routes
---------------------------------------
- Superadmin configures custom registration fields per vendor
- Vendor creates lectures and marks students present/absent per lecture
- Parents view their child's lecture attendance
"""
import json
import sqlite3
import logging
from flask import Blueprint, request, jsonify, g, current_app
from datetime import datetime
from services.auth_service import authenticate_vendor_access, require_auth, verify_token, extract_token
from db_factory import get_db_connection, set_row_factory
from utils import cache_delete_vendor_prefix

logger = logging.getLogger(__name__)
bulk_attendance_bp = Blueprint('bulk_attendance', __name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _row(conn):
    """Ensure sqlite3.Row factory is set on conn."""
    if not getattr(conn, "_is_pg", False):
        conn.row_factory = sqlite3.Row
    return conn


def _upsert_config(c, vendor_id, fields_json, now):
    c.execute("SELECT id FROM bulk_attendance_config WHERE vendor_id = ?", (vendor_id,))
    if c.fetchone():
        c.execute(
            "UPDATE bulk_attendance_config SET fields = ?, updated_at = ? WHERE vendor_id = ?",
            (fields_json, now, vendor_id)
        )
    else:
        c.execute(
            "INSERT INTO bulk_attendance_config (vendor_id, fields, updated_at) VALUES (?, ?, ?)",
            (vendor_id, fields_json, now)
        )


# ── Config endpoints (superadmin sets custom fields per vendor) ────────────────

@bulk_attendance_bp.route("/bulk-attendance/config", methods=["GET"])
@require_auth()
def get_bulk_attendance_config():
    vendor_id = g.vendor_id
    if g.user_role == 'super_admin':
        qv = request.args.get('vendor_id')
        if qv:
            try:
                vendor_id = int(qv)
            except ValueError:
                pass

    conn = _row(get_db_connection())
    c = conn.cursor()
    c.execute("SELECT fields FROM bulk_attendance_config WHERE vendor_id = ?", (vendor_id,))
    row = c.fetchone()
    conn.close()

    default_fields = [
        {"name": "name",           "label": "Full Name",      "type": "text", "required": True,  "default": True},
        {"name": "student_id",     "label": "Student ID",     "type": "text", "required": True,  "default": True},
        {"name": "mobile_number",  "label": "Mobile Number",  "type": "text", "required": True,  "default": True},
    ]
    custom_fields = []
    if row:
        try:
            raw = row[0] if isinstance(row, (list, tuple)) else row['fields']
            custom_fields = json.loads(raw) if raw else []
        except Exception:
            custom_fields = []

    return jsonify({"fields": default_fields + custom_fields, "custom_fields": custom_fields})


@bulk_attendance_bp.route("/bulk-attendance/config", methods=["PUT"])
@require_auth()
def save_bulk_attendance_config():
    if g.user_role not in ('super_admin', 'admin'):
        return jsonify({"error": "Forbidden"}), 403

    vendor_id = g.vendor_id
    if g.user_role == 'super_admin':
        qv = (request.json or {}).get('vendor_id') or request.args.get('vendor_id')
        if qv:
            try:
                vendor_id = int(qv)
            except ValueError:
                pass

    data = request.json or {}
    raw_fields = data.get('custom_fields', [])

    # Sanitise and deduplicate
    seen = {'student_id', 'mobile_number'}
    valid = []
    for f in raw_fields:
        name = str(f.get('name', '')).strip().replace(' ', '_').lower()
        if not name or name in seen:
            continue
        field_type = f.get('type', 'text')
        if field_type not in ('text', 'number', 'select', 'date'):
            field_type = 'text'
        valid.append({
            "name":     name,
            "label":    str(f.get('label', name)).strip() or name,
            "type":     field_type,
            "required": bool(f.get('required', False)),
            "options":  [str(o) for o in f.get('options', [])] if field_type == 'select' else [],
        })
        seen.add(name)

    conn = get_db_connection()
    c = conn.cursor()
    _upsert_config(c, vendor_id, json.dumps(valid), datetime.utcnow().isoformat())
    conn.commit()
    conn.close()
    return jsonify({"status": "saved", "custom_fields": valid})


# ── Lecture CRUD ───────────────────────────────────────────────────────────────

@bulk_attendance_bp.route("/bulk-attendance/lectures", methods=["GET"])
@require_auth()
def list_lectures():
    vendor_id = g.vendor_id
    date_filter = request.args.get('date', '').strip()
    class_year  = request.args.get('class_year', '').strip()
    division    = request.args.get('division', '').strip()
    branch      = request.args.get('branch', '').strip()

    conn = _row(get_db_connection())
    c = conn.cursor()

    q = """
        SELECT l.*,
               COALESCE(
                 (SELECT COUNT(*) FROM lecture_attendance la
                  WHERE la.lecture_id = l.id AND la.status = 'present'), 0
               ) AS present_count
        FROM lectures l
        WHERE l.vendor_id = ?
    """
    params = [vendor_id]
    if date_filter:
        q += " AND l.lecture_date = ?"; params.append(date_filter)
    if class_year:
        q += " AND l.class_year = ?";  params.append(class_year)
    if division:
        q += " AND l.division = ?";    params.append(division)
    if branch:
        q += " AND l.branch = ?";      params.append(branch)
    q += " ORDER BY l.lecture_date DESC, l.start_time DESC, l.id DESC"

    c.execute(q, params)
    lectures = [dict(r) for r in (c.fetchall() or [])]
    conn.close()
    return jsonify({"lectures": lectures})


@bulk_attendance_bp.route("/bulk-attendance/lectures", methods=["POST"])
@require_auth()
def create_lecture():
    vendor_id = g.vendor_id
    data    = request.json or {}
    subject = (data.get('subject') or '').strip()
    if not subject:
        return jsonify({"error": "subject is required"}), 400

    today = datetime.utcnow().strftime('%Y-%m-%d')
    conn  = get_db_connection()
    c     = conn.cursor()
    c.execute(
        """INSERT INTO lectures
           (vendor_id, subject, class_year, division, branch, lecture_date, start_time, teacher, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            vendor_id,
            subject,
            data.get('class_year', '') or '',
            data.get('division',   '') or '',
            data.get('branch',     '') or '',
            data.get('lecture_date') or today,
            data.get('start_time',  '') or '',
            data.get('teacher',     '') or '',
            datetime.utcnow().isoformat(),
        )
    )
    conn.commit()
    lecture_id = c.lastrowid
    conn.close()
    return jsonify({"status": "created", "lecture_id": lecture_id}), 201
    return jsonify({"status": "created", "lecture_id": lecture_id}), 201


@bulk_attendance_bp.route("/bulk-attendance/lectures/<int:lecture_id>", methods=["GET"])
@require_auth()
def get_lecture(lecture_id):
    vendor_id = g.vendor_id
    conn = _row(get_db_connection())
    c    = conn.cursor()

    c.execute("SELECT * FROM lectures WHERE id = ? AND vendor_id = ?", (lecture_id, vendor_id))
    lec = c.fetchone()
    if not lec:
        conn.close()
        return jsonify({"error": "Lecture not found"}), 404

    c.execute(
        """SELECT la.person_id, la.status, la.marked_at,
                  f.name, f.face_image,
                  f.custom_data
           FROM lecture_attendance la
           JOIN faces f ON f.id = la.person_id
           WHERE la.lecture_id = ? AND la.vendor_id = ?
           ORDER BY f.name""",
        (lecture_id, vendor_id)
    )
    roster = [dict(r) for r in (c.fetchall() or [])]
    conn.close()

    result = dict(lec)
    result['attendance']    = roster
    result['present_count'] = sum(1 for r in roster if r['status'] == 'present')
    result['absent_count']  = sum(1 for r in roster if r['status'] == 'absent')
    return jsonify(result)


@bulk_attendance_bp.route("/bulk-attendance/lectures/<int:lecture_id>", methods=["DELETE"])
@require_auth()
def delete_lecture(lecture_id):
    vendor_id = g.vendor_id
    conn = get_db_connection()
    c    = conn.cursor()
    c.execute("DELETE FROM lecture_attendance WHERE lecture_id = ? AND vendor_id = ?", (lecture_id, vendor_id))
    c.execute("DELETE FROM lectures WHERE id = ? AND vendor_id = ?", (lecture_id, vendor_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


# ── Attendance marking ─────────────────────────────────────────────────────────

@bulk_attendance_bp.route("/bulk-attendance/lectures/<int:lecture_id>/mark", methods=["POST"])
@require_auth()
def mark_lecture_attendance(lecture_id):
    vendor_id = g.vendor_id
    data = request.json or {}
    client_now = data.get('timestamp')

    # Support single {person_id, status} or batch {entries: [{person_id, status}]}
    entries = data.get('entries')
    if not entries:
        pid = data.get('person_id')
        if not pid:
            return jsonify({"error": "person_id required"}), 400
        entries = [{"person_id": int(pid), "status": data.get('status', 'present'), "image": data.get('image', '')}]

    conn = get_db_connection()
    c    = conn.cursor()

    c.execute("SELECT id, subject, class_year, division, branch FROM lectures WHERE id = ? AND vendor_id = ?", (lecture_id, vendor_id))
    lecture = c.fetchone()
    if not lecture:
        conn.close()
        return jsonify({"error": "Lecture not found"}), 404
    
    # Extract metadata safely
    if hasattr(lecture, 'keys') and callable(lecture.keys): # dict-like
        l_subj = lecture.get('subject', '')
        l_year = lecture.get('class_year', '')
        l_div  = lecture.get('division', '')
        l_branch = lecture.get('branch', '')
    else: # tuple
        l_subj = lecture[1] if len(lecture) > 1 else ''
        l_year = lecture[2] if len(lecture) > 2 else ''
        l_div  = lecture[3] if len(lecture) > 3 else ''
        l_branch = lecture[4] if len(lecture) > 4 else ''
        date_str = lecture[5] if len(lecture) > 5 else ''

    now = client_now or datetime.now().isoformat()
    marked = 0
    for entry in entries:
        try:
            pid = int(entry.get('person_id'))
            status = entry.get('status', 'present')
            l_id = int(entry.get('lecture_id') or lecture_id)
            if status not in ('present', 'absent'):
                status = 'present'
            c.execute(
                "SELECT id FROM lecture_attendance WHERE lecture_id = ? AND person_id = ?",
                (l_id, pid)
            )
            if c.fetchone():
                c.execute(
                    "UPDATE lecture_attendance SET status = ?, marked_at = ? WHERE lecture_id = ? AND person_id = ?",
                    (status, now, l_id, pid)
                )
            else:
                c.execute(
                    "INSERT INTO lecture_attendance (vendor_id, lecture_id, person_id, status, marked_at) VALUES (?, ?, ?, ?, ?)",
                    (vendor_id, l_id, pid, status, now)
                )
            
            # Sync to core attendance logs if present
            if status == 'present':
                image = entry.get('image', '')
                c.execute("SELECT name FROM faces WHERE id = ?", (pid,))
                fr = c.fetchone()
                name = fr[0] if fr else "Unknown"
                
                # Check for recent duplicate for this specific lecture to avoid redundant logs
                c.execute(
                    "SELECT id FROM attendance WHERE person_id = ? AND lecture_id = ? AND vendor_id = ?",
                    (pid, l_id, vendor_id)
                )
                if not c.fetchone():
                    c.execute(
                        """INSERT INTO attendance (name, timestamp, status, activity, person_id, vendor_id, captured_image, is_late, device_id, class_year, division, branch, subject, lecture_id) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (name, now, 'CHECK_IN', 'Lecture', pid, vendor_id, image, 0, 'Bulk_Image_API', l_year, l_div, l_branch, l_subj, l_id)
                    )
            marked += 1
        except Exception as e:
            logger.warning("Error marking lecture attendance for person %s: %s", entry.get('person_id'), e)

    conn.commit()
    conn.close()

    # Invalidate attendance cache to show new records immediately
    cache_delete_vendor_prefix(vendor_id)

    # Notify connected clients for real-time updates
    try:
        if 'socketio' in current_app.extensions:
            socketio = current_app.extensions['socketio']
            socketio.emit('attendance_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
    except Exception as e:
        logger.warning(f"Failed to emit attendance_updated socket event: {e}")

    # Push FCM notification to parents for each present student (fire-and-forget)
    try:
        from notifications import notify_parent_async
        _ts_label = datetime.now().strftime('%I:%M %p')
        for entry in entries:
            try:
                _pid = int(entry.get('person_id', 0))
                _status = entry.get('status', 'present')
                if _pid and _status == 'present':
                    _subj_label = l_subj or "Lecture"
                    notify_parent_async(
                        _pid, vendor_id,
                        title=f"Attendance Marked — {_subj_label}",
                        body=f"Present at {_ts_label}",
                        data={"type": "lecture_attendance", "lecture_id": str(lecture_id), "person_id": str(_pid)}
                    )
            except Exception:
                pass
    except Exception:
        pass

    return jsonify({"status": "marked", "count": marked})


# ── Per-student lecture history (vendor view) ──────────────────────────────────

@bulk_attendance_bp.route("/bulk-attendance/student/<int:person_id>", methods=["GET"])
@require_auth()
def get_student_lecture_history(person_id):
    vendor_id  = g.vendor_id
    start_date = request.args.get('start_date', '').strip()
    end_date   = request.args.get('end_date',   '').strip()

    conn = _row(get_db_connection())
    c    = conn.cursor()

    q = """
        SELECT l.id AS lecture_id, l.subject, l.class_year, l.division, l.branch,
               l.lecture_date, l.start_time, l.teacher,
               COALESCE(la.status, 'absent') AS status,
               la.marked_at
        FROM lectures l
        LEFT JOIN lecture_attendance la
               ON la.lecture_id = l.id AND la.person_id = ?
        WHERE l.vendor_id = ?
    """
    params = [person_id, vendor_id]
    if start_date:
        q += " AND l.lecture_date >= ?"; params.append(start_date)
    if end_date:
        q += " AND l.lecture_date <= ?"; params.append(end_date)
    q += " ORDER BY l.lecture_date DESC, l.start_time DESC"

    c.execute(q, params)
    rows = [dict(r) for r in (c.fetchall() or [])]
    conn.close()
    return jsonify({"attendance": rows, "person_id": person_id})


# ── Parent: view child's lecture attendance ────────────────────────────────────

@bulk_attendance_bp.route("/parents/lecture-attendance", methods=["GET"])
def get_parent_lecture_attendance():
    """
    Public-ish endpoint authenticated via parent token (Bearer or cookie).
    Returns lecture attendance for the linked student.
    """
    auth_header = request.headers.get('Authorization')
    token = extract_token(auth_header) or request.cookies.get('token')
    if not token:
        return jsonify({"error": "Authentication required"}), 401

    token_data = verify_token(token)
    if not token_data or token_data.get('role') != 'parent':
        return jsonify({"error": "Invalid or expired token"}), 401

    conn = _row(get_db_connection())
    c    = conn.cursor()

    c.execute(
        "SELECT id, vendor_id, selected_person_id, session_version FROM parent_users WHERE username = ?",
        (token_data['username'],)
    )
    pu = c.fetchone()
    if not pu:
        conn.close()
        return jsonify({"error": "Parent not found"}), 404

    # Validate session_version
    token_sv = token_data.get('sv')
    pu_sv    = pu['session_version'] if 'session_version' in (pu.keys() if hasattr(pu, 'keys') else {}) else 1
    if token_sv is None or int(token_sv) != int(pu_sv or 1):
        conn.close()
        return jsonify({"error": "Session expired"}), 401

    vendor_id = pu['vendor_id']
    person_id = pu['selected_person_id']
    if not person_id:
        # Try to resolve from student_parents
        c.execute(
            "SELECT person_id FROM student_parents WHERE parent_id = ? LIMIT 1",
            (pu['id'],)
        )
        sp = c.fetchone()
        person_id = sp['person_id'] if sp else None

    if not person_id:
        conn.close()
        return jsonify({"error": "No student linked to this parent account"}), 404

    start_date = request.args.get('start_date', '').strip()
    end_date   = request.args.get('end_date',   '').strip()

    q = """
        SELECT l.id AS lecture_id, l.subject, l.class_year, l.division, l.branch,
               l.lecture_date, l.start_time, l.teacher,
               COALESCE(la.status, 'absent') AS status,
               la.marked_at
        FROM lectures l
        LEFT JOIN lecture_attendance la
               ON la.lecture_id = l.id AND la.person_id = ?
        WHERE l.vendor_id = ?
    """
    params = [person_id, vendor_id]
    if start_date:
        q += " AND l.lecture_date >= ?"; params.append(start_date)
    if end_date:
        q += " AND l.lecture_date <= ?"; params.append(end_date)
    q += " ORDER BY l.lecture_date DESC, l.start_time DESC"

    c.execute(q, params)
    rows = [dict(r) for r in (c.fetchall() or [])]
    conn.close()
    return jsonify({"attendance": rows, "person_id": person_id})
