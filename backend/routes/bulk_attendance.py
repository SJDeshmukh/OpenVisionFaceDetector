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
import traceback
import uuid as _uuid
import threading as _threading
import time as _time
from flask import Blueprint, request, jsonify, g, current_app
from datetime import datetime
from services.auth_service import authenticate_vendor_access, require_auth, verify_token, extract_token
from db_factory import get_db_connection, set_row_factory
from utils import cache_delete_vendor_prefix

logger = logging.getLogger(__name__)
bulk_attendance_bp = Blueprint('bulk_attendance', __name__)

# ── Async scan job store ───────────────────────────────────────────────────────
_SCAN_JOBS: dict = {}
_SCAN_JOBS_LOCK = _threading.Lock()


def _cleanup_scan_jobs():
    now = _time.time()
    with _SCAN_JOBS_LOCK:
        expired = [k for k, v in _SCAN_JOBS.items() if now - v.get("created_at", 0) > 600]
        for k in expired:
            del _SCAN_JOBS[k]


def _run_scan_job(job_id: str, raw: bytes, params: dict, vendor_id: int):
    try:
        from services.face_service import _detect_faces_from_bytes
        faces_raw, _ = _detect_faces_from_bytes(raw, params, vendor_id)
    except Exception as exc:
        logger.warning("async scan job %s error: %s", job_id, exc)
        faces_raw = []

    results = []
    for face in faces_raw:
        suggestions = face.get("suggestions") or []
        if suggestions:
            best       = suggestions[0]
            person_id  = best.get("person_id")
            name       = best.get("name") or "Unknown"
            confidence = round(float(best.get("similarity", 0.0)) * 100, 1)
            matched    = True
        else:
            person_id  = None
            name       = "Unknown"
            confidence = 0.0
            matched    = False
        face_thumb = (face.get("thumbs") or {}).get("face") or ""
        emb_vec    = face.get("emb_vec") or ""
        results.append({
            "person_id":  str(person_id) if person_id is not None else None,
            "name":       name,
            "confidence": confidence,
            "matched":    matched,
            "face_thumb": face_thumb,
            "emb_vec":    emb_vec,
        })

    with _SCAN_JOBS_LOCK:
        if job_id in _SCAN_JOBS:
            _SCAN_JOBS[job_id]["status"] = "done"
            _SCAN_JOBS[job_id]["faces"]  = results


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

    # Build lecture class key for validation (empty means no restriction)
    lecture_class_year   = (l_year or '').strip()
    lecture_class_div    = (l_div  or '').strip()
    lecture_has_class    = bool(lecture_class_year or lecture_class_div)

    now = client_now or datetime.now().isoformat()
    marked = 0
    skipped_class_mismatch = 0
    for entry in entries:
        try:
            pid = int(entry.get('person_id'))
            status = entry.get('status', 'present')
            l_id = int(entry.get('lecture_id') or lecture_id)

            # Class segregation: skip students whose class doesn't match this lecture
            if lecture_has_class:
                c.execute("SELECT custom_data FROM faces WHERE id = ? AND vendor_id = ?", (pid, vendor_id))
                face_row = c.fetchone()
                if face_row:
                    raw_cd = face_row[0] if isinstance(face_row, (list, tuple)) else face_row.get('custom_data')
                    try:
                        cd = json.loads(raw_cd) if isinstance(raw_cd, str) else (raw_cd if isinstance(raw_cd, dict) else {})
                    except Exception:
                        cd = {}
                    
                    # Robust extraction of student year/division/class from metadata
                    s_year  = str(cd.get('class_year') or cd.get('year') or cd.get('Year') or '').strip().lower()
                    s_div   = str(cd.get('division') or cd.get('Division') or '').strip().lower()
                    s_class = str(cd.get('class_section') or cd.get('class') or '').strip().lower()
                    
                    # Normalize lecture values
                    l_year_norm = str(lecture_class_year or '').strip().lower()
                    l_div_norm  = str(lecture_class_div or '').strip().lower()
                    
                    year_match = (not l_year_norm) or (l_year_norm in s_year) or (l_year_norm in s_class)
                    div_match  = (not l_div_norm)  or (l_div_norm == s_div)  or (l_div_norm in s_class)
                    
                    if not (year_match and div_match):
                        skipped_class_mismatch += 1
                        continue
            
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
            
            # Sync to core attendance logs
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
                    device_id = 'Faculty_App' if g.user_role == 'faculty' else 'Bulk_Image_API'
                    c.execute(
                        """INSERT INTO attendance (name, timestamp, status, activity, person_id, vendor_id, captured_image, is_late, device_id, class_year, division, branch, subject, lecture_id) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (name, now, 'CHECK_IN', 'Lecture', pid, vendor_id, image, 0, device_id, l_year, l_div, l_branch, l_subj, l_id)
                    )
            elif status == 'absent':
                # Remove from global attendance logs if it was previously marked present for this lecture
                c.execute(
                    "DELETE FROM attendance WHERE person_id = ? AND lecture_id = ? AND vendor_id = ?",
                    (pid, l_id, vendor_id)
                )
            marked += 1
        except Exception as e:
            logger.error("Error marking lecture attendance for person %s: %s\n%s", 
                         entry.get('person_id'), e, traceback.format_exc())
            # Don't stop the whole batch for one failing record
            pass

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
        try:
            _ts_label = datetime.fromisoformat(now[:19]).strftime('%I:%M %p')
        except Exception:
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

    return jsonify({
        "status": "marked", 
        "count": marked, 
        "skipped_class_mismatch": skipped_class_mismatch
    })


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

    c.execute("SELECT id, vendor_id, selected_person_id, session_version FROM parent_users WHERE username = %s" if getattr(conn, "_is_pg", False) else "SELECT id, vendor_id, selected_person_id, session_version FROM parent_users WHERE username = ?", (token_data['username'],))
    pu = c.fetchone()
    if not pu:
        import logging
        logging.error(f"[DEBUG] Parent not found in lecture-attendance for username: '{token_data.get('username')}'")
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

    # Resolve student's class_section for lecture filtering
    c.execute("SELECT custom_data FROM faces WHERE id = ? AND vendor_id = ?" if not getattr(conn, "_is_pg", False) else "SELECT custom_data FROM faces WHERE id = %s AND vendor_id = %s", (person_id, vendor_id))
    face_row = c.fetchone()
    student_class = ''
    if face_row:
        raw_cd = face_row[0] if isinstance(face_row, (list, tuple)) else face_row.get('custom_data')
        try:
            cd = json.loads(raw_cd) if raw_cd else {}
            # Robust metadata extraction (handles multiple key formats)
            s_year = str(cd.get('class_year') or cd.get('year') or '').strip().lower()
            s_div  = str(cd.get('division') or cd.get('Division') or '').strip().lower()
            s_class = str(cd.get('class_section') or cd.get('class') or '').strip().lower()
            
            # Combine them for checking against lecture fields
            student_class_context = f"{s_year} {s_div} {s_class}"
            
            # We overwrite student_class here so the logic below works
            student_class = student_class_context.strip()
        except Exception:
            pass

    start_date = request.args.get('start_date', '').strip()
    end_date   = request.args.get('end_date',   '').strip()

    is_pg = getattr(conn, "_is_pg", False)
    ph = "%s" if is_pg else "?"

    q = f"""
        SELECT l.id AS lecture_id, l.subject, l.class_year, l.division, l.branch,
               l.lecture_date, l.start_time, l.teacher,
               COALESCE(la.status, 'absent') AS status,
               la.marked_at
        FROM lectures l
        LEFT JOIN lecture_attendance la
               ON la.lecture_id = l.id AND la.person_id = {ph}
        WHERE l.vendor_id = {ph}
    """
    params = [person_id, vendor_id]
    if start_date:
        q += f" AND l.lecture_date >= {ph}"; params.append(start_date)
    if end_date:
        q += f" AND l.lecture_date <= {ph}"; params.append(end_date)
    q += " ORDER BY l.lecture_date DESC, l.start_time DESC"

    c.execute(q, tuple(params))
    rows = []
    for r in (c.fetchall() or []):
        d = dict(r)
        if student_class:
            l_class_year = str(d.get('class_year') or '').strip().lower()
            l_class_div  = str(d.get('division')   or '').strip().lower()
            # If lecture has year/div, it must be found within the student's normalized class context
            if l_class_year and l_class_year not in student_class:
                continue
            if l_class_div and l_class_div not in student_class:
                continue
        # Format date for mobile app regex: YYYY-MM-DD
        if 'lecture_date' in d and d['lecture_date']:
            try:
                if hasattr(d['lecture_date'], 'strftime'):
                    d['lecture_date'] = d['lecture_date'].strftime('%Y-%m-%d')
                else:
                    d['lecture_date'] = str(d['lecture_date'])[:10]
            except Exception:
                pass
        rows.append(d)

    conn.close()
    return jsonify({"attendance": rows, "person_id": person_id})


# ── Faculty Mobile Sync ───────────────────────────────────────────────────────

@bulk_attendance_bp.route("/bulk-attendance/faculty/classes", methods=["GET"])
@require_auth()
def faculty_assigned_classes():
    """Return classes (+ subjects) assigned to the logged-in faculty.

    For vendor_admin / super_admin returns all classes.
    For faculty returns only classes where their username appears in mapped_subjects.
    Response: {classes: [{id, class_year, division, branch, label, subjects: [str]}]}
    """
    if g.user_role not in ("faculty", "vendor_admin", "super_admin"):
        return jsonify({"error": "Forbidden"}), 403

    vendor_id = g.vendor_id
    username  = g.username

    conn = get_db_connection()
    c    = conn.cursor()
    c.execute(
        "SELECT id, class_year, division, branch, label, mapped_subjects "
        "FROM classes WHERE vendor_id = ? ORDER BY class_year, division",
        (vendor_id,)
    )
    rows = c.fetchall() or []
    conn.close()

    result = []
    for r in rows:
        try:
            ms = json.loads(r[5]) if r[5] else []
        except Exception:
            ms = []

        if g.user_role == "faculty":
            def _fm(mf):
                a = (mf or "").lower().strip(); b = username.lower().strip()
                return a == b or a.split("@")[0] == b.split("@")[0] or a.split("@")[0] == b or a == b.split("@")[0]
            if not any(_fm(m.get("faculty", "")) for m in ms):
                continue
            subjects = [m["subject"] for m in ms if m.get("subject") and _fm(m.get("faculty", ""))]
        else:
            subjects = list({m["subject"] for m in ms if m.get("subject")})

        result.append({
            "id":         r[0],
            "class_year": r[1] or "",
            "division":   r[2] or "",
            "branch":     r[3] or "",
            "label":      r[4] or f"{r[1]}-{r[2]}",
            "subjects":   subjects,
        })

    return jsonify({"classes": result})


@bulk_attendance_bp.route("/bulk-attendance/faculty/sync", methods=["POST"])
@require_auth()
def faculty_sync_attendance():
    """Accept queued attendance records from AttendX faculty mobile app."""
    if g.user_role not in ("faculty", "vendor_admin", "super_admin"):
        return jsonify({"error": "Forbidden"}), 403

    vendor_id = g.vendor_id
    payload   = request.get_json(silent=True) or {}
    records   = payload.get("records", [])
    if not records:
        return jsonify({"error": "No records provided"}), 400

    conn = get_db_connection()
    c    = conn.cursor()
    is_pg = getattr(conn, "_is_pg", False)
    ph    = "%s" if is_pg else "?"

    synced = 0
    errors = 0
    now    = datetime.now().isoformat()

    for rec in records:
        try:
            lecture_id = int(rec.get("lecture_id", 0))
            person_id  = str(rec.get("person_id", "")).strip()
            status     = str(rec.get("status", "present")).strip()
            ts         = str(rec.get("timestamp", now))
            if not lecture_id or not person_id:
                errors += 1
                continue

            # Verify lecture belongs to vendor and get metadata
            c.execute(
                f"SELECT id, subject, class_year, division, branch FROM lectures WHERE id = {ph} AND vendor_id = {ph}",
                (lecture_id, vendor_id),
            )
            lecture = c.fetchone()
            if not lecture:
                errors += 1
                continue

            if hasattr(lecture, 'keys') and callable(lecture.keys):
                l_subj = lecture.get('subject', '')
                l_year = lecture.get('class_year', '')
                l_div  = lecture.get('division', '')
                l_branch = lecture.get('branch', '')
            else:
                l_subj = lecture[1] if len(lecture) > 1 else ''
                l_year = lecture[2] if len(lecture) > 2 else ''
                l_div  = lecture[3] if len(lecture) > 3 else ''
                l_branch = lecture[4] if len(lecture) > 4 else ''

            if is_pg:
                c.execute(
                    """INSERT INTO lecture_attendance (lecture_id, vendor_id, person_id, status, marked_at)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (lecture_id, person_id) DO UPDATE
                       SET status = EXCLUDED.status, marked_at = EXCLUDED.marked_at""",
                    (lecture_id, vendor_id, person_id, status, ts),
                )
            else:
                c.execute(
                    """INSERT OR REPLACE INTO lecture_attendance
                       (lecture_id, vendor_id, person_id, status, marked_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (lecture_id, vendor_id, person_id, status, ts),
                )

            # Sync to core attendance logs if present
            if status == 'present':
                c.execute(f"SELECT name FROM faces WHERE id = {ph}", (person_id,))
                fr = c.fetchone()
                name = fr[0] if fr else "Unknown"
                
                c.execute(
                    f"SELECT id FROM attendance WHERE person_id = {ph} AND lecture_id = {ph} AND vendor_id = {ph}",
                    (person_id, lecture_id, vendor_id)
                )
                if not c.fetchone():
                    img = rec.get("image", "")
                    c.execute(
                        f"""INSERT INTO attendance (name, timestamp, status, activity, person_id, vendor_id, captured_image, is_late, device_id, class_year, division, branch, subject, lecture_id) 
                           VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})""",
                        (name, ts, 'CHECK_IN', 'Lecture', person_id, vendor_id, img, 0, 'Faculty_App', l_year, l_div, l_branch, l_subj, lecture_id)
                    )
            synced += 1
        except Exception as e:
            logger.warning("faculty_sync record error: %s", e)
            errors += 1

    conn.commit()
    conn.close()
    return jsonify({"synced": synced, "errors": errors})


@bulk_attendance_bp.route("/bulk-attendance/faculty/scan", methods=["POST"])
@require_auth()
def faculty_scan_image():
    """Faculty submits a photo; starts async detection, returns job_id immediately.

    POST  {image: base64_str, lecture_id: int (optional)}
    Returns {job_id, status: "processing"}  — poll /scan/status/<job_id>
    """
    import base64 as _b64

    if g.user_role not in ("faculty", "vendor_admin", "super_admin"):
        return jsonify({"error": "Faculty access required"}), 403

    vendor_id = g.vendor_id
    data      = request.get_json(silent=True) or {}
    img_b64   = data.get("image")

    if not img_b64:
        if "image" in request.files:
            img_b64 = "data:image/jpeg;base64," + _b64.b64encode(
                request.files["image"].read()
            ).decode()
        else:
            return jsonify({"error": "image required"}), 400

    try:
        _, encoded = img_b64.split(",", 1) if "," in img_b64 else ("", img_b64)
        raw = _b64.b64decode(encoded)
    except Exception:
        return jsonify({"error": "invalid image encoding"}), 400

    params = {"fast": True, "crop_mode": "Portrait", "det_max_side": 1280}

    _cleanup_scan_jobs()
    job_id = str(_uuid.uuid4())
    with _SCAN_JOBS_LOCK:
        _SCAN_JOBS[job_id] = {"status": "processing", "faces": [], "created_at": _time.time()}

    t = _threading.Thread(target=_run_scan_job, args=(job_id, raw, params, vendor_id), daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "status": "processing"})


@bulk_attendance_bp.route("/bulk-attendance/faculty/scan/status/<job_id>", methods=["GET"])
@require_auth()
def faculty_scan_status(job_id):
    """Poll for async scan result.

    Returns {status: "processing"} or {status: "done", faces: [...], count: N}
    """
    if g.user_role not in ("faculty", "vendor_admin", "super_admin"):
        return jsonify({"error": "Faculty access required"}), 403

    with _SCAN_JOBS_LOCK:
        job = dict(_SCAN_JOBS.get(job_id, {}))

    if not job:
        return jsonify({"error": "Job not found or expired"}), 404

    if job["status"] == "processing":
        return jsonify({"status": "processing"})

    return jsonify({"status": "done", "faces": job["faces"], "count": len(job["faces"])})


@bulk_attendance_bp.route("/bulk-attendance/faculty/class-students", methods=["GET"])
@require_auth()
def faculty_class_students():
    """Return students in a specific class/division (for relabeling UI).

    GET ?class_year=FY&division=A
    Returns {students: [{id, name}]}
    """
    if g.user_role not in ("faculty", "vendor_admin", "super_admin"):
        return jsonify({"error": "Forbidden"}), 403

    vendor_id  = g.vendor_id
    class_year = request.args.get("class_year", "").strip()
    division   = request.args.get("division", "").strip()

    conn   = get_db_connection()
    c      = conn.cursor()
    is_pg  = getattr(conn, "_is_pg", False)
    ph     = "%s" if is_pg else "?"

    c.execute(
        f"""SELECT DISTINCT pe.person_id, f.name, f.display_id
            FROM person_embeddings pe
            JOIN faces f ON f.id = pe.person_id
            WHERE pe.vendor_id = {ph}
              AND LOWER(TRIM(pe.class_year)) = LOWER(TRIM({ph}))
              AND LOWER(TRIM(pe.division))   = LOWER(TRIM({ph}))
            ORDER BY f.display_id ASC""",
        (vendor_id, class_year, division),
    )
    rows = c.fetchall() or []

    # Fallback: if person_embeddings had no results, query faces table
    # and filter by custom_data JSON containing class_section info
    if not rows and (class_year or division):
        c.execute(
            f"SELECT id, name, custom_data, display_id FROM faces WHERE vendor_id = {ph} ORDER BY display_id ASC",
            (vendor_id,),
        )
        all_faces = c.fetchall() or []
        filtered = []
        for fr in all_faces:
            fid   = fr[0]
            fname = fr[1] or ""
            raw_cd = fr[2]
            try:
                cd = json.loads(raw_cd) if raw_cd else {}
            except Exception:
                cd = {}
            
            s_year = str(cd.get('class_year') or cd.get('year') or '').strip().lower()
            s_div  = str(cd.get('division') or cd.get('Division') or '').strip().lower()
            s_class = str(cd.get('class_section') or cd.get('class') or '').strip().lower()
            
            year_ok = (not class_year) or (class_year.lower() in s_year) or (class_year.lower() in s_class)
            div_ok  = (not division)   or (division.lower()   in s_div)  or (division.lower()   in s_class)
            if year_ok and div_ok:
                filtered.append((fid, fname, fr[3]))
        if filtered:
            rows = filtered

    conn.close()

    students = [{"id": str(r[0]), "name": (f"#{r[2]} {r[1]}" if r[2] else r[1]) or ""} for r in rows]
    return jsonify({"students": students})


@bulk_attendance_bp.route("/bulk-attendance/faculty/save-embedding", methods=["POST"])
@require_auth()
def faculty_save_embedding():
    """Store a corrected face embedding (faculty relabels a student).

    POST {person_id, emb_vec: base64(float32 bytes)}
    """
    import base64 as _b64, numpy as _np

    if g.user_role not in ("faculty", "vendor_admin", "super_admin"):
        return jsonify({"error": "Forbidden"}), 403

    vendor_id    = g.vendor_id
    data         = request.get_json(silent=True) or {}
    person_id    = data.get("person_id")
    emb_vec_b64  = data.get("emb_vec")

    if not person_id or not emb_vec_b64:
        return jsonify({"error": "person_id and emb_vec required"}), 400

    try:
        vec_bytes = _b64.b64decode(emb_vec_b64)
        emb       = _np.frombuffer(vec_bytes, dtype=_np.float32).copy()
        if emb.size == 0:
            return jsonify({"error": "empty embedding"}), 400
    except Exception:
        return jsonify({"error": "invalid emb_vec encoding"}), 400

    conn   = get_db_connection()
    c      = conn.cursor()
    is_pg  = getattr(conn, "_is_pg", False)
    ph     = "%s" if is_pg else "?"

    c.execute(f"SELECT id FROM faces WHERE id = {ph} AND vendor_id = {ph}", (person_id, vendor_id))
    if not c.fetchone():
        conn.close()
        return jsonify({"error": "Person not found"}), 404

    c.execute(f"SELECT class_year, division, branch FROM person_embeddings WHERE person_id = {ph} LIMIT 1", (person_id,))
    row = c.fetchone()
    class_year = row[0] if row else ""
    division   = row[1] if row else ""
    branch     = row[2] if row else ""

    vec_blob = emb.astype(_np.float32).tobytes()
    dim      = int(emb.size)
    now      = datetime.now().isoformat()

    if is_pg:
        c.execute(
            """INSERT INTO person_embeddings
               (vendor_id, person_id, class_year, division, branch, vec, dim, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (vendor_id, person_id, class_year, division, branch, vec_blob, dim, now),
        )
    else:
        c.execute(
            """INSERT INTO person_embeddings
               (vendor_id, person_id, class_year, division, branch, vec, dim, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (vendor_id, person_id, class_year, division, branch, vec_blob, dim, now),
        )

    conn.commit()
    conn.close()
    cache_delete_vendor_prefix(vendor_id)

    return jsonify({"success": True})
