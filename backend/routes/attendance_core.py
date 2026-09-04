import json
import logging
import sqlite3
import numpy as np
import base64
from datetime import datetime
from collections import defaultdict
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

from utils import (
    get_db_connection, get_table_columns, parse_db_datetime, 
    cache_get, cache_set, cache_delete_vendor_prefix,
    vendor_has_feature, track_metrics, rate_limit,
    check_vendor_status, _run
)
from db_factory import set_row_factory
from services.attendance_service import (
    calculate_daily_hours, calculate_expected_hours, calculate_arrival_status
)
from services.auth_service import require_auth, verify_token, extract_token
from middleware.validation import validate_request
from schemas import AttendanceFilterSchema, PersonEventSchema, PublicAttendanceRequest
from services.person_scope_service import (
    class_scope_for,
    parse_custom_data,
    person_type_for,
    requested_person_type,
    vendor_vertical,
)
from services.report_filter_service import custom_value
from flask import Blueprint, request, jsonify, g

attendance_core_bp = Blueprint('attendance_core_bp', __name__)

def _person_scope_context(cursor, vendor_id, requested_type=None):
    vertical = vendor_vertical(cursor, vendor_id)
    wanted_type = requested_person_type(requested_type, vertical)
    cursor.execute("""
        SELECT f.id, f.name, f.custom_data,
               (SELECT su.role FROM system_users su
                WHERE su.person_id = f.id AND su.vendor_id = f.vendor_id
                ORDER BY CASE WHEN LOWER(su.role) = 'faculty' THEN 0 ELSE 1 END
                LIMIT 1) AS system_role
        FROM faces f WHERE f.vendor_id = ?
    """, (vendor_id,))
    people = {}
    for row in cursor.fetchall() or []:
        resolved = person_type_for(row[2], row[3], vertical)
        people[int(row[0])] = {
            "name": row[1], "custom_data": parse_custom_data(row[2]),
            "person_type": resolved,
        }
    return vertical, wanted_type, people

@attendance_core_bp.route("/attendance/filters", methods=["GET"])
@require_auth()
@validate_request(AttendanceFilterSchema)
def get_attendance_filters(valid_data: AttendanceFilterSchema):
    vendor_id = g.vendor_id
    
    cache_key = f"vendor:{vendor_id}:attendance_filters:{hash(tuple(sorted(request.args.items())))}"
    cached = cache_get(cache_key)
    if cached: return jsonify(cached)

    conn = get_db_connection()
    set_row_factory(conn)
    c = conn.cursor()
    vertical = vendor_vertical(c, vendor_id)
    wanted_type = requested_person_type(valid_data.person_type, vertical)
    
    c.execute("SELECT registration_config FROM vendors WHERE id = ?", (vendor_id,))
    row = c.fetchone()
    raw = row['registration_config'] if row else None
    
    visible_standard_filters = {"department": True, "designation": True, "shift": True, "phone": True}
    enabled_fields = []
    if raw:
        try:
            config_data = json.loads(raw) if isinstance(raw, str) else raw
            from services.config_utils import hydrate_registration_config
            config = hydrate_registration_config(vendor_id, config_data, conn=conn)
            
            if isinstance(config, list):
                for f in config:
                    if f.get("enabled", True) is False:
                        if f.get("field") in visible_standard_filters:
                            visible_standard_filters[f.get("field")] = False
                    else:
                        key = f.get("field") or f.get("key")
                        if key:
                            enabled_fields.append({"key": str(key), "label": str(f.get("label") or key), "options": f.get("options")})
        except Exception:
            logger.debug("Failed to load registration config for vendor %s", vendor_id, exc_info=True)

    c.execute("""SELECT f.id, f.name, f.department, f.designation, f.shift, f.phone,
                        f.custom_data,
                        (SELECT su.role FROM system_users su
                         WHERE su.person_id = f.id AND su.vendor_id = f.vendor_id
                         ORDER BY CASE WHEN LOWER(su.role) = 'faculty' THEN 0 ELSE 1 END
                         LIMIT 1) AS system_role
                 FROM faces f WHERE f.vendor_id = ?""", (vendor_id,))
    faces = []
    for r in c.fetchall():
        d = dict(r)
        d["custom"] = parse_custom_data(d.get("custom_data"))
        d["person_type"] = person_type_for(d["custom"], d.get("system_role"), vertical)
        if wanted_type and d["person_type"] != wanted_type:
            continue
        faces.append(d)
    c.execute("SELECT id, class_year, division, branch, label FROM classes WHERE vendor_id = ?", (vendor_id,))
    class_option_labels = {}
    for class_row in c.fetchall() or []:
        class_id = str(class_row[0])
        fallback_label = " - ".join(
            str(value).strip() for value in (class_row[1], class_row[2], class_row[3])
            if value not in (None, "")
        )
        class_option_labels[class_id] = str(class_row[4] or fallback_label or class_id)
    conn.close()
    
    # Apply standard request filters if any
    request_args = {
        key: value for key, value in request.args.items()
        if value not in (None, "") and key not in {
            "start_date", "end_date", "limit", "offset", "person_type", "device_name",
        }
    }
    
    def _fuzzy_get_local(custom_dict, key):
        if not key: return None
        val = custom_dict.get(key)
        if val is not None: return val
        key_aliases = {
            'student_id': ['id_number'],
            'id_number': ['student_id'],
            'class_section': ['class_id'],
            'class_id': ['class_section']
        }
        for alias in key_aliases.get(key, []):
            if alias in custom_dict: return custom_dict[alias]
        return None

    def face_matches(face):
        for k, v in request_args.items():
            kl = k.lower()
            rv = None
            base_keys = {"name", "department", "designation", "shift", "phone"}
            if k in face: rv = face.get(k)
            if rv is None and kl in base_keys:
                for bk in base_keys:
                    if kl == bk and bk in face:
                        rv = face.get(bk); break
            if rv is None: rv = _fuzzy_get_local(face["custom"], k)
            if rv is None:
                for ef in enabled_fields:
                    if ef.get("key") == k:
                        rv = _fuzzy_get_local(face["custom"], ef.get("label")); break
            if rv is None or str(rv).strip() != str(v).strip(): return False
        return True

    filtered_faces = [f for f in faces if face_matches(f)]
    
    names = sorted({str(f.get("name")).strip() for f in filtered_faces if str(f.get("name") or "").strip() != ""})
    departments = sorted({str(f.get("department")).strip() for f in filtered_faces if f.get("department")}) if visible_standard_filters["department"] else []
    designations = sorted({str(f.get("designation")).strip() for f in filtered_faces if f.get("designation")}) if visible_standard_filters["designation"] else []
    shifts = sorted({str(f.get("shift")).strip() for f in filtered_faces if f.get("shift")}) if visible_standard_filters["shift"] else []
    phones = sorted({str(f.get("phone")).strip() for f in filtered_faces if f.get("phone")}) if visible_standard_filters["phone"] else []

    dynamic_filters = {}
    if enabled_fields:
        base_keys = {"name", "department", "designation", "shift", "phone"}
        for field in enabled_fields:
            fk, fl = str(field.get("key") or "").strip(), str(field.get("label") or field.get("key")).strip()
            if not fk: continue
            unique_values = set()
            for f in filtered_faces:
                val = f.get(fk)
                if val is None:
                    fkl, fll = fk.lower(), fl.lower()
                    if fkl in base_keys:
                        for bk in base_keys:
                            if fkl == bk: val = f.get(bk); break
                    if val is None and fll in base_keys:
                        for bk in base_keys:
                            if fll == bk: val = f.get(bk); break
                if val is None: val = _fuzzy_get_local(f["custom"], fk)
                if val is None: val = _fuzzy_get_local(f["custom"], fl)
                if val is not None and str(val).strip() != "": unique_values.add(str(val).strip())
            
            options = sorted(list(unique_values))[:200]
            if field.get("options"):
                allowed = [str(x) for x in (field.get("options") or [])]
                options = [x for x in allowed if x in unique_values] if unique_values else allowed
            filter_config = {"label": fl, "options": options}
            normalized_filter_key = fk.strip().lower().replace(" ", "_").replace("-", "_")
            if normalized_filter_key in {"class", "class_id", "class_section"}:
                filter_config["option_labels"] = {
                    value: class_option_labels.get(str(value), str(value)) for value in options
                }
            dynamic_filters[fk] = filter_config

    result = {
        "names": names, "departments": departments, "designations": designations,
        "shifts": shifts, "phones": phones, "visible_standard_filters": visible_standard_filters,
        "dynamic_filters": dynamic_filters
    }
    cache_set(cache_key, result, 15)
    return jsonify(result)

@attendance_core_bp.route("/attendance/summary", methods=["GET"])
@require_auth()
@validate_request(AttendanceFilterSchema)
def get_attendance_summary(valid_data: AttendanceFilterSchema):
    vendor_id = g.vendor_id

    date_str = valid_data.start_date or datetime.now().strftime('%Y-%m-%d')
    cache_key = f"vendor:{vendor_id}:attendance_summary:{date_str}:{valid_data.person_type or 'default'}"
    cached = cache_get(cache_key)
    if cached: return jsonify(cached)

    conn = get_db_connection()
    set_row_factory(conn)
    c = conn.cursor()
    _vertical, wanted_type, people = _person_scope_context(c, vendor_id, valid_data.person_type)
    
    c.execute("SELECT live_timetable FROM companies WHERE vendor_id = ?", (vendor_id,))
    crow = c.fetchone()
    timetable = json.loads(crow['live_timetable']) if crow and crow['live_timetable'] else []
            
    target_date = datetime.strptime(date_str, '%Y-%m-%d')
    day_name = target_date.strftime('%a')
    day_acts = sorted([a for a in timetable if day_name in a.get('days', [])], key=lambda x: x.get('start_time', '00:00'))
    
    exp_hours = calculate_expected_hours(day_acts)
    exp_start = day_acts[0]['start_time'] if day_acts else None
    exp_end = day_acts[-1]['end_time'] if day_acts else None

    c.execute("SELECT * FROM attendance WHERE date(timestamp) = ? AND vendor_id = ? ORDER BY timestamp ASC", (date_str, vendor_id))
    rows = c.fetchall()
    conn.close()

    user_recs = defaultdict(list)
    user_names = {}
    user_person_ids = {}
    allowed_names = {
        person["name"] for person in people.values()
        if not wanted_type or person["person_type"] == wanted_type
    }
    for r in rows:
        row_dict = dict(r)
        person = people.get(int(row_dict.get("person_id"))) if row_dict.get("person_id") else None
        if person:
            if wanted_type and person["person_type"] != wanted_type:
                continue
        elif wanted_type and row_dict.get("name") not in allowed_names:
            continue
        group_key = f"id:{row_dict['person_id']}" if row_dict.get("person_id") else f"name:{row_dict['name']}"
        user_names[group_key] = person["name"] if person else row_dict["name"]
        user_person_ids[group_key] = row_dict.get("person_id")
        user_recs[group_key].append(row_dict)

    summary = []
    for user_key, records in user_recs.items():
        stats = calculate_daily_hours(records, timetable, date_str=date_str)
        status = "Present"
        if stats['total_hours'] == 0: status = "Absent"
        elif exp_hours > 0:
            if stats['total_hours'] < (exp_hours - 0.5): status = "Undertime"
            elif stats['total_hours'] > (exp_hours + 1): status = "Overtime"
            else: status = "On Track"
        
        arr_status = calculate_arrival_status(exp_start, stats['sessions'], day_acts)
        summary.append({
            "name": user_names[user_key], "person_id": user_person_ids[user_key],
            "date": date_str, "status": status, "arrival_status": arr_status,
            "schedule": {"expected_hours": round(exp_hours, 2), "expected_start": exp_start, "expected_end": exp_end},
            **stats
        })

    result = {"summary": summary}
    cache_set(cache_key, result, 600)
    return jsonify(result)

@attendance_core_bp.route("/person-event", methods=["POST"])
@require_auth()
@validate_request(PersonEventSchema)
def person_event(valid_data: PersonEventSchema):
    from app import socketio
    detected, recognized = valid_data.detected, valid_data.recognized
    name, person_id = valid_data.name, valid_data.person_id
    
    kiosk_vendor_id, person_vendor_id = g.vendor_id, None
    auth_header = request.headers.get('Authorization')
    if auth_header:
        try:
            ud = verify_token(auth_header.split(" ")[1])
            if ud:
                conn_a = get_db_connection(); ca = conn_a.cursor()
                ca.execute("SELECT vendor_id FROM system_users WHERE username = ?", (ud['username'],))
                ur = ca.fetchone(); conn_a.close()
                if ur: kiosk_vendor_id = ur[0]
        except Exception:
            logger.debug("Auth token lookup failed in person-event", exc_info=True)

    if recognized:
         conn_c = get_db_connection(); cc = conn_c.cursor(); fr = None
         if person_id:
             cc.execute("SELECT vendor_id FROM faces WHERE id = ?", (person_id,))
             fr = cc.fetchone()
         if not fr and name and kiosk_vendor_id:
             cc.execute("SELECT vendor_id FROM faces WHERE name = ? AND vendor_id = ? LIMIT 1", (name, kiosk_vendor_id))
             fr = cc.fetchone()
         conn_c.close()
         if fr: person_vendor_id = fr[0]

    if kiosk_vendor_id and person_vendor_id and kiosk_vendor_id != person_vendor_id:
         return jsonify({"speak": True, "text": "Access Denied: Person belongs to another organization."})

    vendor_id_to_check = kiosk_vendor_id if kiosk_vendor_id else person_vendor_id
    if recognized and not person_id and not vendor_id_to_check and name:
        return jsonify({"speak": True, "text": "Registration must be vendor-wise. Missing person_id."})

    if vendor_id_to_check:
        is_allowed, reason = check_vendor_status(vendor_id_to_check)
        if not is_allowed: return jsonify({"speak": True, "text": f"Service Suspended: {reason}."})

    captured_image = valid_data.image
    is_attendance = valid_data.is_attendance
    ts_str = valid_data.timestamp
    current_time_obj = datetime.now()
    if ts_str:
        try: current_time_obj = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%f")
        except (ValueError, TypeError):
            try: current_time_obj = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError): pass

    if not detected: return jsonify({"speak": False})
    if detected and not recognized:
        return jsonify({"speak": True, "text": "Hello! You are not recognized. Please register first."})

    resolved_pid = person_id
    resolved_scope = {"class_year": "", "division": "", "branch": ""}
    if recognized:
        conn_r = get_db_connection(); cr = conn_r.cursor()
        if isinstance(resolved_pid, str) and resolved_pid.startswith("local:"):
            luid = resolved_pid.replace("local:", "")
            cr.execute("SELECT id, name FROM faces WHERE local_uid = ? LIMIT 1", (luid,))
            rr = cr.fetchone()
            if rr: resolved_pid = rr[0]; name = rr[1] if not name else name
        if not resolved_pid and name and vendor_id_to_check:
            cr.execute("SELECT id FROM faces WHERE name = ? AND vendor_id = ? LIMIT 1", (name, vendor_id_to_check))
            rr = cr.fetchone()
            if rr: resolved_pid = rr[0]
        if resolved_pid:
            cr.execute(
                """SELECT name, vendor_id, custom_data FROM faces
                   WHERE id = ? AND (? IS NULL OR vendor_id = ?) LIMIT 1""",
                (resolved_pid, vendor_id_to_check, vendor_id_to_check),
            )
            rr = cr.fetchone()
            if rr:
                name = rr[0] if not name else name
                vendor_id_to_check = rr[1] if not vendor_id_to_check else vendor_id_to_check
                resolved_scope = class_scope_for(rr[2])
            else: resolved_pid = None
        conn_r.close()

    person_id = resolved_pid
    if not is_attendance: return jsonify({"speak": True, "text": f"Identified: {name} (Admin Mode)"})
    if recognized and not person_id:
        return jsonify({"error": "person_id required", "speak": True, "text": "Missing person_id."}), 400

    conn = get_db_connection(); conn.row_factory = sqlite3.Row; c = conn.cursor()
    curr_dev_id = None
    try:
        t2 = extract_token(request.headers.get('Authorization'))
        if t2:
            c.execute("SELECT device_id FROM active_sessions WHERE token = ? LIMIT 1", (t2,))
            rd = c.fetchone()
            if rd: curr_dev_id = rd[0]
    except Exception:
        logger.debug("Device ID lookup from session failed", exc_info=True)
    if not curr_dev_id: curr_dev_id = str(valid_data.device_id or '').strip() or None

    if person_id:
        if vendor_id_to_check:
            q = "SELECT * FROM attendance WHERE person_id = ? AND vendor_id = ?"
            p = [person_id, vendor_id_to_check]
            if curr_dev_id: q += " AND device_id = ?"; p.append(curr_dev_id)
            c.execute(q + " ORDER BY timestamp DESC LIMIT 1", p)
        else:
            q = "SELECT * FROM attendance WHERE person_id = ?"
            p = [person_id]
            if curr_dev_id: q += " AND device_id = ?"; p.append(curr_dev_id)
            c.execute(q + " ORDER BY timestamp DESC LIMIT 1", p)
    else:
        # Fallback to name...
        c.execute("SELECT * FROM attendance WHERE name = ? ORDER BY timestamp DESC LIMIT 1", (name,))
    
    last_record = c.fetchone()
    new_status = 'CHECK_OUT' if last_record and last_record['status'] == 'CHECK_IN' else 'CHECK_IN'
    if new_status == 'CHECK_OUT':
        try:
            lts = parse_db_datetime(last_record['timestamp'])
            if lts and (current_time_obj - lts).total_seconds() / 3600 > 16: new_status = 'CHECK_IN'
        except (ValueError, TypeError, AttributeError): pass

    activity_name, activity_type = "Work", "Work"
    # (Simplified activity/shift logic for core split - should be fully migrated from monolithic)
    # Full shift matching logic here...
    
    # Cooldown Check
    if last_record:
        try:
            lts = parse_db_datetime(last_record['timestamp'])
            cooldown_key = f"cooldown_vendor_{vendor_id_to_check}" if vendor_id_to_check else "cooldown"
            c.execute("SELECT value FROM system_settings WHERE key=?", (cooldown_key,))
            sv = c.fetchone(); cd_sec = int(sv[0]) if sv else 30
            if 0 <= (datetime.now() - lts).total_seconds() < cd_sec:
                conn.close(); return jsonify({"speak": False})
        except Exception:
            logger.debug("Cooldown check failed", exc_info=True)

    is_late = 0
    if new_status == 'CHECK_IN' and vendor_id_to_check:
        try:
            setting_suffix = f'_vendor_{vendor_id_to_check}'
            c.execute(
                "SELECT key, value FROM system_settings WHERE key IN (?, ?)",
                (f'late_threshold{setting_suffix}', f'work_start_time{setting_suffix}'),
            )
            time_settings = {
                row[0].removesuffix(setting_suffix): row[1] for row in c.fetchall()
            }
            late_after = time_settings.get('late_threshold') or time_settings.get('work_start_time')
            if late_after and current_time_obj.strftime('%H:%M') > str(late_after)[:5]:
                is_late = 1
        except Exception:
            logger.debug("Late threshold evaluation failed", exc_info=True)
    # Full late logic here...

    try:
        c.execute("""INSERT INTO attendance
                     (name, timestamp, status, captured_image, activity, is_late,
                      vendor_id, person_id, device_id, class_year, division, branch)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (name, current_time_obj, new_status, captured_image, activity_name,
                   is_late, vendor_id_to_check, person_id, curr_dev_id,
                   resolved_scope.get("class_year", ""), resolved_scope.get("division", ""),
                   resolved_scope.get("branch", "")))
        conn.commit()
        if vendor_id_to_check: cache_delete_vendor_prefix(vendor_id_to_check)
        if vendor_id_to_check and socketio:
            ev = {"name": name, "timestamp": current_time_obj.strftime('%Y-%m-%d %H:%M:%S'), "status": new_status, "is_late": is_late, "activity": activity_name, "vendor_id": vendor_id_to_check, "device_id": curr_dev_id, "captured_image": captured_image}
            socketio.emit('attendance_updated', ev, room=f"vendor_{vendor_id_to_check}")

        # Push notification to parent (fire-and-forget, never blocks response)
        if person_id and vendor_id_to_check:
            try:
                from notifications import notify_parent_async
                _ts_label = current_time_obj.strftime('%I:%M %p')
                _action = "Checked In" if new_status == "CHECK_IN" else "Checked Out"
                notify_parent_async(
                    person_id, vendor_id_to_check,
                    title=f"{name} — {_action}",
                    body=f"{_action} at {_ts_label}",
                    data={"type": "checkin_out", "status": new_status, "person_id": str(person_id)}
                )
            except Exception:
                pass

        conn.close()
        return jsonify({"speak": True, "text": f"{name}: {new_status.title()}", "status": new_status, "is_late": is_late, "activity": activity_name, "person_id": person_id})
    except Exception as e:
        conn.rollback(); conn.close(); return jsonify({"error": str(e)}), 500

@attendance_core_bp.route("/attendance", methods=["GET"], endpoint="attendance_list_route")
@track_metrics("attendance_list")
@rate_limit(limit=300, window=60)
@require_auth()
@validate_request(AttendanceFilterSchema)
def get_attendance(valid_data: AttendanceFilterSchema):
    vendor_id = g.vendor_id
    cache_params = sorted(request.args.items())
    cache_key = f"vendor:{vendor_id}:attendance_list:{hash(tuple(cache_params))}"
    cached = cache_get(cache_key)
    if cached: return jsonify(cached)

    conn = get_db_connection(); conn.row_factory = sqlite3.Row; c = conn.cursor()
    vertical = vendor_vertical(c, vendor_id)
    wanted_type = requested_person_type(valid_data.person_type, vertical)
    s_date, e_date, name = valid_data.start_date, valid_data.end_date, valid_data.name
    query = """
        SELECT a.*, f.department, f.designation, f.shift, f.phone, f.custom_data AS face_custom_data,
               (SELECT su.role FROM system_users su
                WHERE su.person_id = f.id AND su.vendor_id = f.vendor_id
                ORDER BY CASE WHEN LOWER(su.role) = 'faculty' THEN 0 ELSE 1 END
                LIMIT 1) AS system_role,
               vd.device_name
        FROM attendance a
        LEFT JOIN faces f ON f.vendor_id = a.vendor_id
          AND f.id = COALESCE(
              a.person_id,
              (SELECT MIN(fallback.id)
                 FROM faces fallback
                WHERE fallback.vendor_id = a.vendor_id
                  AND fallback.name = a.name)
          )
        LEFT JOIN vendor_devices vd ON a.device_id = vd.device_id AND a.vendor_id = vd.vendor_id
        WHERE a.vendor_id = ?
    """
    params = [vendor_id]
    if s_date: query += " AND date(a.timestamp) >= ?"; params.append(s_date)
    if e_date: query += " AND date(a.timestamp) <= ?"; params.append(e_date)
    if name: query += " AND a.name LIKE ?"; params.append(f"%{name}%")
    query += " ORDER BY a.timestamp DESC"
    c.execute(query, params)
    columns = [description[0] for description in c.description]
    rows = c.fetchall(); conn.close()

    attendance = []
    dynamic_filters = {
        key: value for key, value in request.args.items()
        if value not in (None, "") and key not in {
            "start_date", "end_date", "name", "person_id", "department",
            "designation", "shift", "phone", "limit", "offset", "person_type",
            "device_name",
        }
    }
    requested_device = str(request.args.get("device_name") or "").strip()
    for row in rows:
        r = dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        custom = parse_custom_data(r.get("face_custom_data"))
        resolved_type = person_type_for(custom, r.get("system_role"), vertical)
        if wanted_type and resolved_type != wanted_type:
            continue
        if valid_data.person_id is not None and int(r.get("person_id") or 0) != int(valid_data.person_id):
            continue
        if valid_data.department and str(r.get("department") or "") != valid_data.department:
            continue
        if valid_data.designation and str(r.get("designation") or "") != valid_data.designation:
            continue
        if valid_data.shift and str(r.get("shift") or "") != valid_data.shift:
            continue
        if valid_data.phone and str(r.get("phone") or "") != valid_data.phone:
            continue
        device_name = r.get("device_name") or r.get("device_id") or ""
        if requested_device and str(device_name) != requested_device:
            continue
        if any(
            str(custom_value(custom, key) or "").strip() != str(value).strip()
            for key, value in dynamic_filters.items()
        ):
            continue
        attendance.append({
            "id": r["id"], "person_id": r.get("person_id"),
            "vendor_id": r.get("vendor_id"), "name": r["name"],
            "timestamp": str(r["timestamp"]),
            "status": r["status"], "activity": r["activity"], "is_late": r.get("is_late", 0),
            "department": r["department"], "designation": r["designation"],
            "captured_image": r["captured_image"],
            "device_name": device_name,
            "class_id": custom.get("class_id"),
            "class_year": r.get("class_year"),
            "division": r.get("division"),
            "branch": r.get("branch"),
            "subject": r.get("subject"),
            "lecture_id": r.get("lecture_id"),
            "person_type": resolved_type,
        })
    offset = max(0, int(valid_data.offset or 0))
    limit = int(valid_data.limit or 500)
    attendance = attendance[offset:offset + limit] if limit > 0 else attendance[offset:]
    result = {"attendance": attendance}
    cache_set(cache_key, result, 60)
    return jsonify(result)

@attendance_core_bp.route("/public/attendance-by-student", methods=["GET"])
@require_auth()
@validate_request(PublicAttendanceRequest)
def public_attendance_by_student(valid_data: PublicAttendanceRequest):
    student_number = valid_data.student_number
    conn = get_db_connection(); c = conn.cursor()
    vertical = vendor_vertical(c, g.vendor_id)
    c.execute("""SELECT f.id, f.vendor_id, f.custom_data,
                        (SELECT su.role FROM system_users su
                         WHERE su.person_id = f.id AND su.vendor_id = f.vendor_id
                         ORDER BY CASE WHEN LOWER(su.role) = 'faculty' THEN 0 ELSE 1 END
                         LIMIT 1) AS system_role
                 FROM faces f WHERE f.vendor_id = ? AND f.custom_data IS NOT NULL""", (g.vendor_id,))
    pid, vid = None, None
    for r in c.fetchall():
        try:
            cd = json.loads(r[2])
            if person_type_for(cd, r[3], vertical) != "student":
                continue
            if str(cd.get('student_id') or cd.get('id_number') or '').strip() == student_number:
                pid, vid = r[0], r[1]; break
        except (json.JSONDecodeError, ValueError): pass
    if not pid: conn.close(); return jsonify({"attendance": []})
    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    c.execute("SELECT name, timestamp, status, activity FROM attendance WHERE person_id = ? ORDER BY timestamp DESC LIMIT ?", (pid, limit))
    rows = []
    for row in c.fetchall():
        rows.append(dict(row) if hasattr(row, "keys") else dict(zip(['name','timestamp','status','activity'], row)))
    conn.close(); return jsonify({"attendance": rows, "student_number": student_number})

@attendance_core_bp.route("/public/register-token", methods=["POST"])
@require_auth()
def public_register_token():
    data = request.json or {}
    sn, token = str(data.get("student_number") or "").strip(), str(data.get("token") or "").strip()
    if not sn or not token: return jsonify({"error": "student_number and token required"}), 400
    conn = get_db_connection(); c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS parent_tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, student_number TEXT, token TEXT UNIQUE, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    c.execute("INSERT OR IGNORE INTO parent_tokens (vendor_id, student_number, token) VALUES (?, ?, ?)", (g.vendor_id, sn, token))
    conn.commit(); conn.close(); return jsonify({"status": "success"})
