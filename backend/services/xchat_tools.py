"""Allow-listed, read-only XChat business tools.

Every public tool receives vendor_id from the authenticated server context.  It is
intentionally absent from every model-visible schema.
"""

import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta


MAX_RANGE_DAYS = 366
MAX_RESULT_ROWS = 25

FEATURE_GUIDE = {
    "reports": "Attendance summaries, trends, exports, and workforce reporting.",
    "report_detailed": "Detailed check-in/check-out attendance reporting and export.",
    "report_payroll": "Payroll and payable-hours reporting and export.",
    "automated_email_reports": "Scheduled daily, weekly, or monthly attendance reports by email.",
    "xchat_ai": "Read-only vendor assistant with private history, charts, tables, and downloads.",
    "mobile_app": "Registered mobile-device access and device-slot management.",
    "payroll": "Employee wage rates, payable hours, deductions, advances, and estimated payouts.",
    "shifts": "Published work timetable and shift configuration.",
    "live_attendance": "Live attendance events and currently checked-in workforce visibility.",
    "cameras": "Registered attendance camera/device visibility and status.",
    "add_shift": "Creation and publication of shift/timetable activities.",
    "payable_hours": "Payable work-session and hours calculations.",
    "enable_attendance": "Attendance capture and attendance record access.",
    "night_shift_logic": "Overnight shift pairing across calendar-day boundaries.",
    "geofencing": "Per-device attendance location boundaries and last-known locations.",
    "whatsapp_alerts": "WhatsApp attendance-alert capability when an external provider is configured.",
    "api_access": "Authenticated integration access to the platform APIs.",
    "white_labeling": "Vendor-specific branding and interface configuration.",
    "late_mark": "Late-arrival tracking and configured payroll deductions.",
    "bulk_image_attendance": "Class or group attendance through bulk image processing.",
    "classes": "Classes, divisions, branches, subjects, and class-scoped attendance.",
    "leave_management": "Student/employee leave requests, approvals, pending items, and history.",
    "parent_login": "Parent accounts linked to registered students.",
    "lecture_wise_reports": "Lecture-level attendance and subject reporting.",
    "parent_alerts": "Parent-facing attendance notifications when notification delivery is configured.",
    "checkin_checkout": "Explicit check-in/check-out attendance workflow.",
}


def _db():
    from utils import get_db_connection
    return get_db_connection()


def _dict(row):
    return dict(row) if row is not None else None


def _parse_date(value, default=None):
    if not value:
        return default or date.today()
    clean = str(value).strip().lower()
    if clean in ("today", "now"):
        return date.today()
    if clean == "yesterday":
        return date.today() - timedelta(days=1)
    if clean == "tomorrow":
        return date.today() + timedelta(days=1)
    try:
        if "t" in clean or " " in clean:
            return datetime.fromisoformat(clean.replace("z", "").split(".")[0]).date()
        return datetime.strptime(clean[:10], "%Y-%m-%d").date()
    except Exception:
        return default or date.today()


def _safe_period(start_date=None, end_date=None, default_days=7):
    if start_date and end_date:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
    elif start_date and not end_date:
        start = _parse_date(start_date)
        end = start
    elif end_date and not start_date:
        end = _parse_date(end_date)
        start = end - timedelta(days=default_days)
    else:
        end = date.today()
        start = end - timedelta(days=default_days)
    if end < start:
        start, end = end, start
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        start = end - timedelta(days=MAX_RANGE_DAYS - 1)
    return start, end


def _period(start_date, end_date):
    try:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
    except (TypeError, ValueError):
        raise ValueError("Dates must use YYYY-MM-DD format")
    if end < start:
        raise ValueError("end_date cannot be before start_date")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"Date range cannot exceed {MAX_RANGE_DAYS} days")
    return start, end


def _limit(value):
    try:
        return max(1, min(int(value or 10), MAX_RESULT_ROWS))
    except (TypeError, ValueError):
        return 10


def _display_image(value):
    if not value or not isinstance(value, str):
        return value
    if value.startswith("s3://"):
        try:
            from storage import presigned_url_for_key
            return presigned_url_for_key(value)
        except Exception:
            return None
    return value


def _company_settings(c, vendor_id):
    c.execute("SELECT live_timetable, working_hours FROM companies WHERE vendor_id = ? LIMIT 1", (vendor_id,))
    row = c.fetchone()
    timetable, working_hours = [], 8.0
    if row:
        try: timetable = json.loads(row[0] or "[]")
        except Exception: timetable = []
        try: working_hours = float(row[1] or 8.0)
        except (TypeError, ValueError): working_hours = 8.0
    return timetable, max(0.25, working_hours)


def _employee_metrics(vendor_id, start, end, department=None):
    from services.attendance_service import calculate_daily_hours
    conn = _db()
    c = conn.cursor()
    try:
        timetable, working_hours = _company_settings(c, vendor_id)
        query = "SELECT id, name, department, designation, daily_wage FROM faces WHERE vendor_id = ?"
        params = [vendor_id]
        if department:
            query += " AND department = ?"
            params.append(str(department))
        query += " ORDER BY name"
        c.execute(query, params)
        people = [_dict(row) for row in (c.fetchall() or [])]
        person_ids = {person["id"] for person in people}
        c.execute("""
            SELECT person_id, timestamp, status, activity, is_late
            FROM attendance
            WHERE vendor_id = ? AND date(timestamp) BETWEEN ? AND ? AND person_id IS NOT NULL
            ORDER BY person_id, timestamp
        """, (vendor_id, (start - timedelta(days=1)).isoformat(), (end + timedelta(days=1)).isoformat()))
        grouped = defaultdict(list)
        for raw in c.fetchall() or []:
            row = _dict(raw)
            if row["person_id"] in person_ids:
                grouped[row["person_id"]].append(row)
    finally:
        conn.close()

    metrics = []
    for person in people:
        stats = calculate_daily_hours(grouped.get(person["id"], []), timetable)
        sessions = []
        for session in stats.get("sessions", []):
            try:
                session_day = datetime.fromisoformat(session["start_ts"]).date()
            except (KeyError, TypeError, ValueError):
                continue
            if start <= session_day <= end and session.get("is_payable", True):
                sessions.append(session)
        hours = round(sum(float(item.get("duration_mins") or 0) for item in sessions) / 60.0, 2)
        daily_wage = float(person.get("daily_wage") or 0)
        estimated_wages = round(hours * (daily_wage / working_hours), 2) if daily_wage else 0.0
        metrics.append({
            "person_id": person["id"], "name": person.get("name"),
            "department": person.get("department"), "designation": person.get("designation"),
            "hours": hours, "estimated_wages": estimated_wages,
        })
    return metrics


def get_attendance_summary(vendor_id, start_date=None, end_date=None, department=None):
    start, end = _period(start_date, end_date)
    conn = _db()
    c = conn.cursor()
    try:
        people_sql = "SELECT id FROM faces WHERE vendor_id = ?"
        people_params = [vendor_id]
        if department:
            people_sql += " AND department = ?"
            people_params.append(str(department))
        c.execute(people_sql, people_params)
        person_ids = {row[0] for row in (c.fetchall() or [])}
        c.execute("""
            SELECT person_id, date(timestamp) AS attendance_day, is_late, status
            FROM attendance WHERE vendor_id = ? AND date(timestamp) BETWEEN ? AND ?
            AND person_id IS NOT NULL ORDER BY timestamp
        """, (vendor_id, start.isoformat(), end.isoformat()))
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    rows = [row for row in rows if row["person_id"] in person_ids]
    present_person_days = {(row["person_id"], str(row["attendance_day"])) for row in rows}
    late_person_days = {(row["person_id"], str(row["attendance_day"])) for row in rows if row.get("is_late")}
    day_events = defaultdict(int)
    day_people = defaultdict(set)
    day_late_people = defaultdict(set)
    for row in rows:
        day = str(row.get("attendance_day"))
        day_events[day] += 1
        day_people[day].add(row["person_id"])
        if row.get("is_late"):
            day_late_people[day].add(row["person_id"])
    daily = {}
    current = start
    while current <= end:
        daily[current.isoformat()] = {"date": current.isoformat(), "present_employees": 0, "late_employees": 0, "attendance_events": 0}
        current += timedelta(days=1)
    for attendance_day in daily:
        daily[attendance_day]["present_employees"] = len(day_people[attendance_day])
        daily[attendance_day]["late_employees"] = len(day_late_people[attendance_day])
        daily[attendance_day]["attendance_events"] = day_events[attendance_day]
    possible = len(person_ids) * ((end - start).days + 1)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "department": department or "All",
        "employees": len(person_ids), "attendance_events": len(rows),
        "present_person_days": len(present_person_days), "late_person_days": len(late_person_days),
        "attendance_rate_percent": round(len(present_person_days) * 100 / possible, 1) if possible else 0,
        "daily_breakdown": list(daily.values()),
        "note": "Attendance rate uses all calendar days in the requested range.",
        "source_path": "/reports",
    }


def get_company_profile(vendor_id):
    """Return organization profile, business vertical, headcount, working hours, and devices."""
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT v.company_name, v.vertical, v.departments, v.attendance_type,
                   c.working_hours, c.shifts, c.live_timetable
            FROM vendors v
            LEFT JOIN companies c ON c.vendor_id = v.id
            WHERE v.id = ? LIMIT 1
        """, (vendor_id,))
        row = _dict(c.fetchone())

        c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (vendor_id,))
        total_people = (c.fetchone() or [0])[0]

        c.execute("SELECT COUNT(*) FROM vendor_devices WHERE vendor_id = ?", (vendor_id,))
        total_devices = (c.fetchone() or [0])[0]

        c.execute("""
            SELECT DISTINCT department FROM faces
            WHERE vendor_id = ? AND department IS NOT NULL AND department <> ''
            ORDER BY department LIMIT 20
        """, (vendor_id,))
        departments = [r[0] for r in (c.fetchall() or [])]
    finally:
        conn.close()

    working_hours = 8.0
    shifts = []
    if row:
        try:
            working_hours = float(row.get("working_hours") or 8.0)
        except (TypeError, ValueError):
            working_hours = 8.0
        try:
            raw_shifts = json.loads(row.get("shifts") or "[]") if isinstance(row.get("shifts"), str) else row.get("shifts")
            if isinstance(raw_shifts, list):
                shifts = [s.get("name") for s in raw_shifts if isinstance(s, dict) and s.get("name")]
        except Exception:
            shifts = []

    return {
        "company_name": (row.get("company_name") if row else None) or "OpenVision Business",
        "vendor_id": vendor_id,
        "vertical": (row.get("vertical") if row else None) or "general",
        "total_registered_people": total_people,
        "standard_working_hours": working_hours,
        "departments": departments,
        "shifts": shifts,
        "registered_devices": total_devices,
        "source_path": "/settings",
    }


def get_today_attendance_summary(vendor_id, attendance_date=None, department=None, class_year=None, division=None):
    """Real-time comprehensive attendance dashboard: total registered, present, absent, late, and on-leave."""
    target_date = _parse_date(attendance_date, default=date.today())
    target_str = target_date.isoformat()
    conn = _db()
    c = conn.cursor()
    try:
        faces_sql = "SELECT id, display_id, name, department, designation, shift FROM faces WHERE vendor_id = ?"
        faces_params = [vendor_id]
        if department:
            faces_sql += " AND department = ?"
            faces_params.append(str(department))
        c.execute(faces_sql, faces_params)
        all_people = [_dict(row) for row in (c.fetchall() or [])]
        person_ids = {p["id"] for p in all_people}

        att_sql = """
            SELECT a.person_id, a.timestamp, a.status, a.is_late, a.activity, f.name, f.department, f.display_id
            FROM attendance a
            JOIN faces f ON f.id = a.person_id AND f.vendor_id = a.vendor_id
            WHERE a.vendor_id = ? AND date(a.timestamp) = ?
        """
        att_params = [vendor_id, target_str]
        if department:
            att_sql += " AND f.department = ?"
            att_params.append(str(department))
        att_sql += " ORDER BY a.timestamp DESC"
        c.execute(att_sql, att_params)
        raw_punches = [_dict(row) for row in (c.fetchall() or [])]

        leave_sql = """
            SELECT lr.student_id, lr.leave_type, lr.reason, f.name, f.department
            FROM leave_requests lr
            JOIN faces f ON f.id = lr.student_id AND f.vendor_id = lr.vendor_id
            WHERE lr.vendor_id = ? AND ? BETWEEN lr.start_date AND lr.end_date
              AND LOWER(lr.final_status) = 'approved'
        """
        c.execute(leave_sql, (vendor_id, target_str))
        leaves = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()

    present_person_ids = {p["person_id"] for p in raw_punches if p["person_id"] in person_ids}
    late_person_ids = {p["person_id"] for p in raw_punches if p.get("is_late") and p["person_id"] in person_ids}
    leave_person_ids = {l["student_id"] for l in leaves if l["student_id"] in person_ids}
    absent_person_ids = person_ids - present_person_ids - leave_person_ids

    total_count = len(person_ids)
    present_count = len(present_person_ids)
    absent_count = len(absent_person_ids)
    late_count = len(late_person_ids)
    on_leave_count = len(leave_person_ids)
    rate = round(present_count * 100.0 / total_count, 1) if total_count else 0.0

    dept_totals = defaultdict(int)
    dept_present = defaultdict(int)
    dept_absent = defaultdict(int)
    dept_late = defaultdict(int)

    for p in all_people:
        dept = p.get("department") or "Unassigned"
        dept_totals[dept] += 1
        if p["id"] in present_person_ids:
            dept_present[dept] += 1
        elif p["id"] in leave_person_ids:
            pass
        else:
            dept_absent[dept] += 1
        if p["id"] in late_person_ids:
            dept_late[dept] += 1

    dept_summary = []
    for dept in sorted(dept_totals.keys()):
        dept_summary.append({
            "department": dept,
            "total": dept_totals[dept],
            "present": dept_present[dept],
            "absent": dept_absent[dept],
            "late": dept_late[dept],
            "rate_percent": round(dept_present[dept] * 100.0 / dept_totals[dept], 1) if dept_totals[dept] else 0.0,
        })

    seen = set()
    recent_arrivals = []
    for p in raw_punches:
        if p["person_id"] not in seen:
            seen.add(p["person_id"])
            recent_arrivals.append({
                "name": p.get("name"),
                "display_id": p.get("display_id"),
                "department": p.get("department"),
                "time": str(p.get("timestamp") or ""),
                "status": p.get("status") or "CHECK_IN",
                "is_late": bool(p.get("is_late")),
            })
            if len(recent_arrivals) >= 15:
                break

    return {
        "date": target_str,
        "department": department or "All",
        "total_registered": total_count,
        "present_count": present_count,
        "absent_count": absent_count,
        "late_count": late_count,
        "on_leave_count": on_leave_count,
        "attendance_rate_percent": rate,
        "recent_arrivals": recent_arrivals,
        "department_summary": dept_summary,
        "source_path": "/attendance",
    }


def get_employee_attendance(vendor_id, query, start_date=None, end_date=None, limit=25):
    """Return entry/exit punch logs, working hours, and late marks for an individual."""
    search = str(query or "").strip()
    if not search:
        raise ValueError("Person name or ID is required")
    start, end = _safe_period(start_date, end_date, default_days=30)
    row_limit = _limit(limit)
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT id, display_id, name, department, designation, shift, custom_data
            FROM faces
            WHERE vendor_id = ? AND (
                LOWER(name) LIKE LOWER(?) OR 
                CAST(display_id AS TEXT) = ? OR 
                LOWER(custom_data) LIKE LOWER(?)
            )
            ORDER BY CASE WHEN LOWER(name) = LOWER(?) THEN 0 ELSE 1 END, name
            LIMIT 5
        """, (vendor_id, f"%{search}%", search, f"%{search}%", search))
        matches = [_dict(row) for row in (c.fetchall() or [])]
        if not matches:
            return {
                "found": False,
                "query": search,
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "message": f"No person found matching '{search}'.",
                "source_path": "/attendance",
            }

        person = matches[0]
        person_id = person["id"]

        roll_no = None
        if person.get("custom_data"):
            try:
                cd = json.loads(person["custom_data"]) if isinstance(person["custom_data"], str) else person["custom_data"]
                if isinstance(cd, dict):
                    roll_no = cd.get("student_number") or cd.get("admission_number") or cd.get("employee_id") or cd.get("roll_number")
            except Exception:
                pass

        c.execute("""
            SELECT id, timestamp, status, activity, is_late, device_id
            FROM attendance
            WHERE vendor_id = ? AND person_id = ? AND date(timestamp) BETWEEN ? AND ?
            ORDER BY timestamp ASC
        """, (vendor_id, person_id, start.isoformat(), end.isoformat()))
        punches = [_dict(row) for row in (c.fetchall() or [])]

        c.execute("""
            SELECT id, leave_type, reason, start_date, end_date, start_time, end_time, final_status
            FROM leave_requests
            WHERE vendor_id = ? AND student_id = ? AND start_date <= ? AND end_date >= ?
        """, (vendor_id, person_id, end.isoformat(), start.isoformat()))
        leaves = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()

    day_groups = defaultdict(list)
    for p in punches:
        try:
            day = str(p.get("timestamp"))[:10]
            day_groups[day].append(p)
        except Exception:
            continue

    timeline = []
    total_punches = len(punches)
    total_present_days = len(day_groups)
    late_days = 0

    for day_str, day_punches in sorted(day_groups.items(), reverse=True)[:row_limit]:
        first_in = next((p for p in day_punches if p.get("status") in ("CHECK_IN", "IN")), day_punches[0])
        last_out = next((p for p in reversed(day_punches) if p.get("status") in ("CHECK_OUT", "OUT")), None)
        is_late = any(bool(p.get("is_late")) for p in day_punches)
        if is_late:
            late_days += 1

        duration_hours = None
        if first_in and last_out and first_in.get("id") != last_out.get("id"):
            try:
                t1 = datetime.fromisoformat(str(first_in["timestamp"]).replace("Z", ""))
                t2 = datetime.fromisoformat(str(last_out["timestamp"]).replace("Z", ""))
                duration_hours = round(max(0.0, (t2 - t1).total_seconds() / 3600.0), 2)
            except Exception:
                pass

        timeline.append({
            "date": day_str,
            "first_in": str(first_in.get("timestamp") or "") if first_in else None,
            "last_out": str(last_out.get("timestamp") or "") if last_out else None,
            "punch_count": len(day_punches),
            "is_late": is_late,
            "duration_hours": duration_hours,
            "punches": [{
                "time": str(p.get("timestamp") or ""),
                "type": p.get("status") or "PUNCH",
                "is_late": bool(p.get("is_late")),
            } for p in day_punches],
        })

    leave_records = [{
        "leave_type": lr.get("leave_type") or "Leave",
        "reason": lr.get("reason"),
        "start_date": str(lr.get("start_date")),
        "end_date": str(lr.get("end_date")),
        "status": lr.get("final_status"),
    } for lr in leaves]

    return {
        "found": True,
        "query": search,
        "person": {
            "id": person["id"],
            "name": person.get("name"),
            "display_id": person.get("display_id"),
            "roll_no": roll_no,
            "department": person.get("department"),
            "designation": person.get("designation"),
            "shift": person.get("shift"),
        },
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "total_present_days": total_present_days,
        "late_days_count": late_days,
        "total_punches": total_punches,
        "attendance_timeline": timeline,
        "leave_records": leave_records,
        "source_path": "/attendance",
    }


def get_live_punches(vendor_id, limit=20, department=None, class_year=None, division=None, attendance_date=None):
    """Return real-time stream of latest punch events across the organization."""
    target_date = _parse_date(attendance_date, default=date.today())
    target_str = target_date.isoformat()
    row_limit = _limit(limit)
    conn = _db()
    c = conn.cursor()
    try:
        sql = """
            SELECT a.id, a.timestamp, a.status, a.activity, a.is_late, a.device_id,
                   f.id AS person_id, f.display_id, f.name, f.department, f.designation
            FROM attendance a
            JOIN faces f ON f.id = a.person_id AND f.vendor_id = a.vendor_id
            WHERE a.vendor_id = ? AND date(a.timestamp) = ?
        """
        params = [vendor_id, target_str]
        if department:
            sql += " AND f.department = ?"
            params.append(str(department))
        sql += " ORDER BY a.timestamp DESC LIMIT ?"
        params.append(row_limit)
        c.execute(sql, params)
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()

    punches = [{
        "id": r["id"],
        "name": r.get("name"),
        "display_id": r.get("display_id") or r.get("person_id"),
        "department": r.get("department") or "Unassigned",
        "timestamp": str(r.get("timestamp") or ""),
        "punch_type": r.get("status") or "CHECK_IN",
        "is_late": bool(r.get("is_late")),
        "device_id": r.get("device_id") or "Kiosk",
    } for r in rows]

    return {
        "date": target_str,
        "count": len(punches),
        "department": department or "All",
        "punches": punches,
        "source_path": "/live-attendance",
    }


def get_employee_details(vendor_id, query):
    """Look up an individual's full profile, shift, wage config, and live today status."""
    search = str(query or "").strip()
    if not search:
        raise ValueError("Person name or ID is required")
    today_str = date.today().isoformat()
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT id, display_id, name, department, designation, phone, shift,
                   daily_wage, basic_salary, joining_date, custom_data
            FROM faces
            WHERE vendor_id = ? AND (
                LOWER(name) LIKE LOWER(?) OR 
                CAST(display_id AS TEXT) = ? OR 
                LOWER(custom_data) LIKE LOWER(?)
            )
            ORDER BY CASE WHEN LOWER(name) = LOWER(?) THEN 0 ELSE 1 END, name
            LIMIT 5
        """, (vendor_id, f"%{search}%", search, f"%{search}%", search))
        matches = [_dict(row) for row in (c.fetchall() or [])]
        if not matches:
            return {"found": False, "query": search, "message": f"No person found matching '{search}'"}

        person = matches[0]
        person_id = person["id"]

        c.execute("""
            SELECT timestamp, status, is_late
            FROM attendance
            WHERE vendor_id = ? AND person_id = ? AND date(timestamp) = ?
            ORDER BY timestamp ASC
        """, (vendor_id, person_id, today_str))
        today_punches = [_dict(row) for row in (c.fetchall() or [])]

        c.execute("""
            SELECT leave_type, reason, start_date, end_date, final_status
            FROM leave_requests
            WHERE vendor_id = ? AND student_id = ? AND ? BETWEEN start_date AND end_date
              AND LOWER(final_status) = 'approved'
            LIMIT 1
        """, (vendor_id, person_id, today_str))
        leave_row = _dict(c.fetchone())
    finally:
        conn.close()

    roll_no = None
    if person.get("custom_data"):
        try:
            cd = json.loads(person["custom_data"]) if isinstance(person["custom_data"], str) else person["custom_data"]
            if isinstance(cd, dict):
                roll_no = cd.get("student_number") or cd.get("admission_number") or cd.get("roll_number") or cd.get("employee_id")
        except Exception:
            pass

    if today_punches:
        live_status = "PRESENT"
        first_in = str(today_punches[0].get("timestamp") or "")
        last_out = str(today_punches[-1].get("timestamp") or "") if len(today_punches) > 1 else None
        is_late = any(bool(p.get("is_late")) for p in today_punches)
    elif leave_row:
        live_status = "ON LEAVE"
        first_in = None
        last_out = None
        is_late = False
    else:
        live_status = "ABSENT"
        first_in = None
        last_out = None
        is_late = False

    return {
        "found": True,
        "query": search,
        "id": person["id"],
        "name": person.get("name"),
        "display_id": person.get("display_id"),
        "roll_no": roll_no,
        "department": person.get("department") or "Unassigned",
        "designation": person.get("designation") or "Unassigned",
        "shift": person.get("shift") or "General",
        "wage_configured": bool(person.get("daily_wage")),
        "today_status": {
            "date": today_str,
            "status": live_status,
            "first_punch": first_in,
            "last_punch": last_out,
            "is_late": is_late,
            "leave_info": leave_row,
        },
        "source_path": "/people",
    }


def get_class_attendance_summary(vendor_id, class_year=None, division=None, branch=None, attendance_date=None):
    """Summarize class/section/division attendance for academic institutions (Schools/Colleges)."""
    target_date = _parse_date(attendance_date, default=date.today())
    target_str = target_date.isoformat()
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("SELECT id, class_year, division, branch, label FROM classes WHERE vendor_id = ?", (vendor_id,))
        class_rows = [_dict(row) for row in (c.fetchall() or [])]

        c.execute("""
            SELECT a.person_id, a.class_year, a.division, a.branch, a.status, a.is_late, f.name
            FROM attendance a
            JOIN faces f ON f.id = a.person_id AND f.vendor_id = a.vendor_id
            WHERE a.vendor_id = ? AND date(a.timestamp) = ?
        """, (vendor_id, target_str))
        att_rows = [_dict(row) for row in (c.fetchall() or [])]

        c.execute("SELECT id, department, designation, custom_data FROM faces WHERE vendor_id = ?", (vendor_id,))
        faces = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()

    by_class = defaultdict(lambda: {"present": set(), "events": 0, "late": set()})
    for a in att_rows:
        cy = a.get("class_year") or "Unassigned"
        div = a.get("division") or ""
        key = f"{cy} {div}".strip()
        by_class[key]["present"].add(a["person_id"])
        by_class[key]["events"] += 1
        if a.get("is_late"):
            by_class[key]["late"].add(a["person_id"])

    breakdown = []
    for cls_name, data in sorted(by_class.items()):
        breakdown.append({
            "class_group": cls_name,
            "present_students": len(data["present"]),
            "late_students": len(data["late"]),
            "attendance_events": data["events"],
        })

    return {
        "date": target_str,
        "configured_classes_count": len(class_rows),
        "total_registered_students": len(faces),
        "total_present_today": len({a["person_id"] for a in att_rows}),
        "class_breakdown": breakdown,
        "source_path": "/classes",
    }


def get_present_people(vendor_id, attendance_date=None, department=None, name=None, limit=25):
    """List registered people with at least one attendance event on a day."""
    day = _parse_date(attendance_date, default=date.today())
    row_limit = _limit(limit)
    conn = _db()
    c = conn.cursor()
    try:
        query = """
            SELECT f.id, f.display_id, f.name, f.department, f.designation, f.shift
            FROM faces f
            WHERE f.vendor_id = ?
              AND EXISTS (
                  SELECT 1 FROM attendance a
                  WHERE a.vendor_id = f.vendor_id AND a.person_id = f.id
                    AND date(a.timestamp) = ?
              )
        """
        params = [vendor_id, day.isoformat()]
        if department:
            query += " AND f.department = ?"
            params.append(str(department))
        if name:
            query += " AND LOWER(f.name) LIKE LOWER(?)"
            params.append(f"%{str(name).strip()}%")
        query += " ORDER BY f.name"
        c.execute(query, params)
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    people = [{
        "display_id": row.get("display_id") or row.get("id"), "name": row.get("name"),
        "department": row.get("department"), "designation": row.get("designation"),
        "shift": row.get("shift"),
    } for row in rows[:row_limit]]
    return {
        "date": day.isoformat(), "department": department or "All", "present_count": len(rows),
        "people": people, "truncated": len(rows) > len(people), "source_path": "/attendance",
        "note": "Present means a registered person has at least one attendance event recorded on this date.",
    }


def get_absent_people(vendor_id, attendance_date=None, department=None, name=None, limit=25):
    """List registered people with no attendance event on the requested day."""
    day = _parse_date(attendance_date, default=date.today())
    row_limit = _limit(limit)
    conn = _db()
    c = conn.cursor()
    try:
        query = """
            SELECT f.id, f.display_id, f.name, f.department, f.designation, f.shift
            FROM faces f
            WHERE f.vendor_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM attendance a
                  WHERE a.vendor_id = f.vendor_id AND a.person_id = f.id
                    AND date(a.timestamp) = ?
              )
        """
        params = [vendor_id, day.isoformat()]
        if department:
            query += " AND f.department = ?"
            params.append(str(department))
        if name:
            query += " AND LOWER(f.name) LIKE LOWER(?)"
            params.append(f"%{str(name).strip()}%")
        query += " ORDER BY f.name"
        c.execute(query, params)
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    people = [{
        "display_id": row.get("display_id") or row.get("id"), "name": row.get("name"),
        "department": row.get("department"), "designation": row.get("designation"),
        "shift": row.get("shift"),
    } for row in rows[:row_limit]]
    return {
        "date": day.isoformat(), "department": department or "All", "absent_count": len(rows),
        "people": people, "truncated": len(rows) > len(people), "source_path": "/attendance",
        "note": "Absent means a registered person has no attendance event recorded on this date.",
    }


def get_payroll_summary(vendor_id, start_date, end_date, department=None):
    start, end = _period(start_date, end_date)
    metrics = _employee_metrics(vendor_id, start, end, department)
    active = [item for item in metrics if item["hours"] > 0]
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "department": department or "All", "employees": len(metrics),
        "employees_with_hours": len(active),
        "total_payable_hours": round(sum(item["hours"] for item in metrics), 2),
        "estimated_wages": round(sum(item["estimated_wages"] for item in metrics), 2),
        "employee_breakdown": metrics[:MAX_RESULT_ROWS],
        "truncated": len(metrics) > MAX_RESULT_ROWS,
        "currency": "INR",
        "note": "Estimated wages use recorded payable hours and employee daily-wage rates; statutory and manual adjustments are not included.",
        "source_path": "/wages",
    }


def get_person_payroll(vendor_id, name, start_date=None, end_date=None):
    """Return individual net payroll after approved advances, defaulting to this month."""
    search_name = str(name or "").strip()
    if not search_name:
        raise ValueError("A person's name is required")
    today = date.today()
    start_date = start_date or today.replace(day=1).isoformat()
    end_date = end_date or today.isoformat()
    start, end = _period(start_date, end_date)
    metrics = _employee_metrics(vendor_id, start, end)
    exact = [item for item in metrics if str(item.get("name") or "").casefold() == search_name.casefold()]
    matches = exact or [item for item in metrics if search_name.casefold() in str(item.get("name") or "").casefold()]
    person_ids = [item["person_id"] for item in matches]
    approved_by_person = defaultdict(float)
    if person_ids:
        months = []
        cursor = start.replace(day=1)
        while cursor <= end:
            months.append(cursor.strftime("%Y-%m"))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        conn = _db()
        c = conn.cursor()
        try:
            person_placeholders = ", ".join("?" for _ in person_ids)
            month_placeholders = ", ".join("?" for _ in months)
            c.execute(f"""
                SELECT person_id, COALESCE(SUM(amount), 0) AS approved_total
                FROM advances
                WHERE vendor_id = ? AND status = 'approved'
                  AND person_id IN ({person_placeholders})
                  AND deduction_month IN ({month_placeholders})
                GROUP BY person_id
            """, [vendor_id, *person_ids, *months])
            for row in c.fetchall() or []:
                approved_by_person[row[0]] = float(row[1] or 0)
        finally:
            conn.close()

    for item in matches:
        gross = float(item.get("estimated_wages") or 0)
        advance = round(approved_by_person[item["person_id"]], 2)
        item["gross_earnings"] = round(gross, 2)
        item["approved_advance_deduction"] = advance
        item["net_payable"] = round(gross - advance, 2)

    gross_total = round(sum(item["gross_earnings"] for item in matches), 2)
    approved_advance_total = round(sum(item["approved_advance_deduction"] for item in matches), 2)
    net_total = round(sum(item["net_payable"] for item in matches), 2)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "query": search_name, "matched_people": len(matches), "people": matches[:MAX_RESULT_ROWS],
        "estimated_wages": net_total,
        "gross_earnings": gross_total,
        "approved_advance_deduction": approved_advance_total,
        "net_payable": net_total,
        "total_payable_hours": round(sum(item["hours"] for item in matches), 2),
        "currency": "INR",
        "note": "Net payable uses recorded payable hours and deducts owner-approved advances scheduled for the selected month(s). Pending or rejected advances are not deducted; statutory and other manual adjustments are not included.",
        "source_path": "/wages",
    }


def get_person_advances(vendor_id, name, deduction_month=None, limit=20):
    """Return advance payments for a named person without confusing them with wages."""
    search_name = str(name or "").strip()
    if not search_name:
        raise ValueError("A person's name is required")
    conn = _db()
    c = conn.cursor()
    try:
        query = """
            SELECT a.id, f.name, f.display_id, a.amount, a.amount_cash, a.amount_online,
                   a.date, a.deduction_month, a.status
            FROM advances a JOIN faces f ON f.id = a.person_id AND f.vendor_id = a.vendor_id
            WHERE a.vendor_id = ? AND LOWER(f.name) LIKE LOWER(?)
        """
        params = [vendor_id, f"%{search_name}%"]
        if deduction_month:
            query += " AND a.deduction_month = ?"
            params.append(str(deduction_month))
        query += " ORDER BY CASE WHEN LOWER(f.name) = LOWER(?) THEN 0 ELSE 1 END, a.date DESC, a.id DESC"
        params.append(search_name)
        c.execute(query, params)
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    records = rows[:_limit(limit)]
    by_status = defaultdict(float)
    for row in rows:
        by_status[str(row.get("status") or "unknown")] += float(row.get("amount") or 0)
    return {
        "query": search_name, "deduction_month": deduction_month or "All",
        "advance_count": len(rows), "total_advance": round(sum(float(row.get("amount") or 0) for row in rows), 2),
        "totals_by_status": {key: round(value, 2) for key, value in sorted(by_status.items())},
        "records": records, "truncated": len(rows) > len(records), "currency": "INR", "source_path": "/wages",
    }


def get_advance_approval_summary(vendor_id, status="pending", deduction_month=None, limit=20):
    """Summarize and list the authenticated vendor's advance approval queue."""
    selected_status = str(status or "pending").strip().lower()
    allowed_statuses = {"pending", "approved", "rejected", "deducted", "all"}
    if selected_status not in allowed_statuses:
        raise ValueError("status must be pending, approved, rejected, deducted, or all")
    month = str(deduction_month or "").strip()
    if month and not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", month):
        raise ValueError("deduction_month must use YYYY-MM format")

    conn = _db()
    c = conn.cursor()
    try:
        summary_sql = """
            SELECT status, COUNT(*) AS request_count, COALESCE(SUM(amount), 0) AS total_amount
            FROM advances WHERE vendor_id = ?
        """
        summary_params = [vendor_id]
        if month:
            summary_sql += " AND deduction_month = ?"
            summary_params.append(month)
        summary_sql += " GROUP BY status"
        c.execute(summary_sql, summary_params)
        summary_rows = [_dict(row) for row in (c.fetchall() or [])]

        detail_sql = """
            SELECT a.id, f.name, f.display_id, a.amount, a.amount_cash, a.amount_online,
                   a.date, a.deduction_month, a.status, a.created_at
            FROM advances a
            JOIN faces f ON f.id = a.person_id AND f.vendor_id = a.vendor_id
            WHERE a.vendor_id = ?
        """
        detail_params = [vendor_id]
        if month:
            detail_sql += " AND a.deduction_month = ?"
            detail_params.append(month)
        if selected_status != "all":
            detail_sql += " AND LOWER(a.status) = ?"
            detail_params.append(selected_status)
        detail_sql += " ORDER BY a.created_at DESC, a.id DESC LIMIT ?"
        detail_params.append(_limit(limit))
        c.execute(detail_sql, detail_params)
        detail_rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()

    by_status = {
        str(row.get("status") or "unknown").lower(): {
            "count": int(row.get("request_count") or 0),
            "amount": round(float(row.get("total_amount") or 0), 2),
        }
        for row in summary_rows
    }
    pending = by_status.get("pending", {"count": 0, "amount": 0.0})
    if selected_status == "all":
        matching_count = sum(item["count"] for item in by_status.values())
        matching_amount = round(sum(item["amount"] for item in by_status.values()), 2)
    else:
        selected = by_status.get(selected_status, {"count": 0, "amount": 0.0})
        matching_count, matching_amount = selected["count"], selected["amount"]
    records = [{
        "id": row.get("id"), "name": row.get("name"),
        "display_id": row.get("display_id"), "amount": float(row.get("amount") or 0),
        "amount_cash": float(row.get("amount_cash") or 0),
        "amount_online": float(row.get("amount_online") or 0),
        "date": str(row.get("date") or ""), "deduction_month": row.get("deduction_month"),
        "status": str(row.get("status") or "pending").lower(),
    } for row in detail_rows]
    return {
        "status_filter": selected_status, "deduction_month": month or "All",
        "pending_count": pending["count"], "pending_amount": pending["amount"],
        "matching_count": matching_count, "matching_amount": matching_amount,
        "totals_by_status": by_status, "records": records,
        "truncated": matching_count > len(records), "currency": "INR",
        "source_path": "/owner/advances",
        "note": "Pending advances require an owner decision and do not affect payroll until approved.",
    }


def compare_payroll_periods(vendor_id, current_start, current_end, previous_start, previous_end, department=None):
    current = get_payroll_summary(vendor_id, current_start, current_end, department)
    previous = get_payroll_summary(vendor_id, previous_start, previous_end, department)
    change = current["estimated_wages"] - previous["estimated_wages"]
    percent = round(change * 100 / previous["estimated_wages"], 1) if previous["estimated_wages"] else None
    return {
        "current": current, "previous": previous, "change": round(change, 2),
        "change_percent": percent, "currency": "INR", "source_path": "/wages",
    }


def get_employee_hours_ranking(vendor_id, start_date, end_date, department=None, limit=10, order="highest"):
    start, end = _period(start_date, end_date)
    metrics = _employee_metrics(vendor_id, start, end, department)
    reverse = str(order).lower() != "lowest"
    ranked = sorted(metrics, key=lambda item: (item["hours"], item.get("name") or ""), reverse=reverse)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "order": "highest" if reverse else "lowest", "employees": ranked[:_limit(limit)],
        "source_path": "/reports",
    }


def get_incomplete_attendance(vendor_id, start_date, end_date, department=None, limit=20):
    start, end = _period(start_date, end_date)
    conn = _db()
    c = conn.cursor()
    try:
        query = """
            SELECT a.person_id, a.name, date(a.timestamp) AS attendance_day, a.timestamp, a.status,
                   f.department, f.designation
            FROM attendance a LEFT JOIN faces f ON f.id = a.person_id
            WHERE a.vendor_id = ? AND date(a.timestamp) BETWEEN ? AND ?
        """
        # Include the following day so an overnight checkout can close a shift
        # that began on end_date instead of being reported as incomplete.
        params = [vendor_id, start.isoformat(), (end + timedelta(days=1)).isoformat()]
        if department:
            query += " AND f.department = ?"
            params.append(str(department))
        query += " ORDER BY a.person_id, a.timestamp"
        c.execute(query, params)
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get("person_id")].append(row)
    incomplete = []
    for records in grouped.values():
        open_checkin = None
        for record in records:
            if record.get("status") == "CHECK_IN":
                if open_checkin is not None:
                    incomplete.append(open_checkin)
                open_checkin = record
            elif record.get("status") == "CHECK_OUT" and open_checkin is not None:
                open_checkin = None
        if open_checkin is not None:
            incomplete.append(open_checkin)
    normalized = []
    for last in incomplete:
        try:
            attendance_day = datetime.fromisoformat(str(last.get("timestamp"))).date()
        except (TypeError, ValueError):
            continue
        if start <= attendance_day <= end:
            normalized.append({
                "name": last.get("name"), "date": attendance_day.isoformat(),
                "last_check_in": str(last.get("timestamp")), "department": last.get("department"),
                "reason": "No later check-out was recorded (including the following day)",
            })
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "count": len(normalized), "records": normalized[:_limit(limit)],
        "truncated": len(normalized) > _limit(limit), "source_path": "/attendance",
    }


def get_people_summary(vendor_id, department=None, limit=20):
    conn = _db()
    c = conn.cursor()
    try:
        query = "SELECT id, name, department, designation, shift, daily_wage, display_id FROM faces WHERE vendor_id = ?"
        params = [vendor_id]
        if department:
            query += " AND department = ?"
            params.append(str(department))
        query += " ORDER BY name"
        c.execute(query, params)
        people = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    departments = defaultdict(int)
    designations = defaultdict(int)
    shifts = defaultdict(int)
    for person in people:
        departments[person.get("department") or "Unassigned"] += 1
        designations[person.get("designation") or "Unassigned"] += 1
        shifts[person.get("shift") or "Unassigned"] += 1
    safe_people = [{
        "display_id": person.get("display_id") or person.get("id"),
        "name": person.get("name"), "department": person.get("department"),
        "designation": person.get("designation"), "shift": person.get("shift"),
        "wage_configured": bool(person.get("daily_wage")),
    } for person in people[:_limit(limit)]]
    return {
        "total_people": len(people), "department": department or "All",
        "by_department": dict(sorted(departments.items())),
        "by_designation": dict(sorted(designations.items())),
        "by_shift": dict(sorted(shifts.items())),
        "people": safe_people, "truncated": len(people) > len(safe_people), "source_path": "/people",
    }


def get_person_images(vendor_id, name, limit=20):
    """Return registered and attendance images for people matching a name."""
    search_name = str(name or "").strip()
    if not search_name:
        raise ValueError("A person's name is required")
    row_limit = _limit(limit)
    conn = _db()
    c = conn.cursor()
    try:
        c.execute(
            """SELECT id, name, display_id, department, designation, face_image
               FROM faces
               WHERE vendor_id = ? AND LOWER(name) LIKE LOWER(?)
               ORDER BY CASE WHEN LOWER(name) = LOWER(?) THEN 0 ELSE 1 END, name
               LIMIT ?""",
            (vendor_id, f"%{search_name}%", search_name, row_limit),
        )
        people = [_dict(row) for row in (c.fetchall() or [])]
        person_ids = [person["id"] for person in people]
        captures = []
        if person_ids:
            placeholders = ",".join("?" for _ in person_ids)
            c.execute(
                f"""SELECT a.person_id, a.captured_image, a.timestamp, a.status, a.activity
                    FROM attendance a
                    WHERE a.vendor_id = ? AND a.person_id IN ({placeholders})
                      AND a.captured_image IS NOT NULL AND a.captured_image <> ''
                    ORDER BY a.timestamp DESC LIMIT ?""",
                [vendor_id, *person_ids, row_limit],
            )
            captures = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()

    by_id = {person["id"]: person for person in people}
    images = []
    for person in people:
        if person.get("face_image"):
            images.append({
                "name": person.get("name"), "display_id": person.get("display_id") or person.get("id"),
                "department": person.get("department"), "designation": person.get("designation"),
                "kind": "Registered photo", "image": _display_image(person.get("face_image")),
            })
    for capture in captures:
        person = by_id.get(capture.get("person_id"), {})
        images.append({
            "name": person.get("name"), "display_id": person.get("display_id") or person.get("id"),
            "department": person.get("department"), "designation": person.get("designation"),
            "kind": "Attendance capture", "image": _display_image(capture.get("captured_image")),
            "timestamp": str(capture.get("timestamp") or ""), "status": capture.get("status"),
            "activity": capture.get("activity"),
        })
    return {
        "query": search_name, "matched_people": len(people), "image_count": len(images),
        "images": images[:row_limit], "truncated": len(images) > row_limit, "source_path": "/people",
    }


def get_device_status(vendor_id, limit=20):
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT device_id, device_name, registered_at, last_login_at, last_active_at,
                   battery_level, geofence_lat, geofence_lng, geofence_radius, last_lat, last_lng
            FROM vendor_devices WHERE vendor_id = ? ORDER BY last_active_at DESC, registered_at DESC
        """, (vendor_id,))
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    devices = []
    for row in rows[:_limit(limit)]:
        devices.append({
            "device_id": row.get("device_id"), "name": row.get("device_name") or row.get("device_id"),
            "last_active": str(row.get("last_active_at") or ""), "battery_percent": row.get("battery_level"),
            "geofence_configured": bool(row.get("geofence_radius")),
            "geofence_radius_m": row.get("geofence_radius"),
            "last_location_available": row.get("last_lat") is not None and row.get("last_lng") is not None,
        })
    return {
        "registered_devices": len(rows), "geofenced_devices": sum(1 for row in rows if row.get("geofence_radius")),
        "devices": devices, "truncated": len(rows) > len(devices), "source_path": "/cameras",
    }


def get_shift_configuration(vendor_id):
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("SELECT name, working_hours, shifts, live_timetable, last_modified_at, published_at FROM companies WHERE vendor_id = ? LIMIT 1", (vendor_id,))
        row = _dict(c.fetchone())
    finally:
        conn.close()
    if not row:
        return {"configured": False, "activities": [], "source_path": "/timetable"}
    def parsed(value):
        try:
            result = json.loads(value or "[]") if isinstance(value, str) else value
            return result if isinstance(result, list) else []
        except (TypeError, ValueError):
            return []
    timetable = parsed(row.get("live_timetable"))
    shifts = parsed(row.get("shifts"))
    activities = [{
        "name": item.get("name"), "start_time": item.get("start_time"), "end_time": item.get("end_time"),
        "type": item.get("type"), "is_payable": item.get("is_payable", item.get("type") == "Work"),
        "overnight": bool(item.get("start_time") and item.get("end_time") and str(item["end_time"]) < str(item["start_time"])),
    } for item in timetable[:MAX_RESULT_ROWS] if isinstance(item, dict)]
    return {
        "configured": bool(timetable or shifts), "company": row.get("name"),
        "working_hours_per_day": row.get("working_hours"), "activities": activities,
        "shift_count": len(shifts), "published_at": str(row.get("published_at") or ""),
        "source_path": "/timetable",
    }


def get_leave_summary(vendor_id, start_date=None, end_date=None, status=None, limit=20):
    start, end = _safe_period(start_date, end_date, default_days=30)
    conn = _db()
    c = conn.cursor()
    try:
        query = """
            SELECT lr.*, f.name, f.display_id
            FROM leave_requests lr LEFT JOIN faces f ON f.id = lr.student_id AND f.vendor_id = lr.vendor_id
            WHERE lr.vendor_id = ? AND lr.start_date <= ? AND lr.end_date >= ?
        """
        params = [vendor_id, end.isoformat(), start.isoformat()]
        if status:
            query += " AND LOWER(lr.final_status) = LOWER(?)"
            params.append(str(status))
        query += " ORDER BY lr.created_at DESC"
        c.execute(query, params)
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    by_status, by_type = defaultdict(int), defaultdict(int)
    for row in rows:
        by_status[row.get("final_status") or "unknown"] += 1
        by_type[row.get("leave_type") or "Unspecified"] += 1
    records = [{
        "id": row.get("id"),
        "name": row.get("name"),
        "display_id": row.get("display_id"),
        "leave_type": row.get("leave_type"),
        "reason": row.get("reason"),
        "start_date": str(row.get("start_date")),
        "end_date": str(row.get("end_date")),
        "start_time": row.get("start_time"),
        "end_time": row.get("end_time"),
        "status": row.get("final_status"),
        "parent_status": row.get("parent_status"),
        "rector_status": row.get("rector_status"),
        "hod_status": row.get("hod_status"),
    } for row in rows[:_limit(limit)]]
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()}, "total_requests": len(rows),
        "by_status": dict(sorted(by_status.items())), "by_type": dict(sorted(by_type.items())),
        "requests": records, "truncated": len(rows) > len(records), "source_path": "/leave-management",
    }


def get_class_activity_summary(vendor_id, start_date, end_date, limit=20):
    start, end = _period(start_date, end_date)
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM classes WHERE vendor_id = ?", (vendor_id,))
        class_count = (c.fetchone() or [0])[0]
        c.execute("""
            SELECT l.id, l.subject, l.class_year, l.division, l.branch, l.lecture_date, l.start_time, l.teacher,
                   COUNT(la.id) AS attendance_count
            FROM lectures l LEFT JOIN lecture_attendance la ON la.lecture_id = l.id AND la.vendor_id = l.vendor_id
            WHERE l.vendor_id = ? AND l.lecture_date BETWEEN ? AND ?
            GROUP BY l.id, l.subject, l.class_year, l.division, l.branch, l.lecture_date, l.start_time, l.teacher
            ORDER BY l.lecture_date DESC, l.start_time DESC
        """, (vendor_id, start.isoformat(), end.isoformat()))
        rows = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    lectures = [{
        "subject": row.get("subject"), "class_year": row.get("class_year"), "division": row.get("division"),
        "branch": row.get("branch"), "date": str(row.get("lecture_date")), "start_time": row.get("start_time"),
        "teacher": row.get("teacher"), "attendance_count": row.get("attendance_count") or 0,
    } for row in rows[:_limit(limit)]]
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()}, "configured_classes": class_count,
        "lecture_count": len(rows), "lectures": lectures, "truncated": len(rows) > len(lectures),
        "source_path": "/classes",
    }


def get_automated_report_status(vendor_id, limit=10):
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("SELECT id, enabled, recipient_email, timezone, send_time, frequencies, report_types, updated_at FROM automated_report_schedules WHERE vendor_id = ? LIMIT 1", (vendor_id,))
        schedule = _dict(c.fetchone())
        deliveries = []
        if schedule:
            c.execute("SELECT frequency, period_start, period_end, status, recipient_email, error, created_at, sent_at FROM automated_report_deliveries WHERE vendor_id = ? ORDER BY created_at DESC LIMIT ?", (vendor_id, _limit(limit)))
            deliveries = [_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()
    if not schedule:
        return {"configured": False, "deliveries": [], "source_path": "/reports"}
    for key in ("frequencies", "report_types"):
        try:
            schedule[key] = json.loads(schedule.get(key) or "[]")
        except (TypeError, ValueError):
            schedule[key] = []
    safe_deliveries = []
    for row in deliveries:
        safe_row = {
            key: str(value) if key in {"period_start", "period_end", "created_at", "sent_at"} else value
            for key, value in row.items()
            if key != "error"
        }
        if row.get("error"):
            safe_row["error_summary"] = str(row["error"])[:200]
        safe_deliveries.append(safe_row)
    return {
        "configured": True, "enabled": bool(schedule.get("enabled")), "recipient_email": schedule.get("recipient_email"),
        "timezone": schedule.get("timezone"), "send_time": schedule.get("send_time"),
        "frequencies": schedule.get("frequencies"), "report_types": schedule.get("report_types"),
        "deliveries": safe_deliveries, "source_path": "/reports",
    }


def get_parent_access_summary(vendor_id):
    conn = _db()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM parent_users WHERE vendor_id = ?", (vendor_id,))
        parents = (c.fetchone() or [0])[0]
        c.execute("SELECT COUNT(*) FROM student_parents WHERE vendor_id = ?", (vendor_id,))
        links = (c.fetchone() or [0])[0]
        c.execute("SELECT COUNT(*) FROM face_reset_requests WHERE vendor_id = ? AND LOWER(status) = 'pending'", (vendor_id,))
        pending_resets = (c.fetchone() or [0])[0]
    finally:
        conn.close()
    return {"parent_accounts": parents, "student_parent_links": links, "pending_face_resets": pending_resets, "source_path": "/settings"}


TOOL_REGISTRY = {
    "get_company_profile": get_company_profile,
    "get_today_attendance_summary": get_today_attendance_summary,
    "get_employee_attendance": get_employee_attendance,
    "get_live_punches": get_live_punches,
    "get_employee_details": get_employee_details,
    "get_class_attendance_summary": get_class_attendance_summary,
    "get_attendance_summary": get_attendance_summary,
    "get_present_people": get_present_people,
    "get_absent_people": get_absent_people,
    "get_payroll_summary": get_payroll_summary,
    "get_person_payroll": get_person_payroll,
    "get_person_advances": get_person_advances,
    "get_advance_approval_summary": get_advance_approval_summary,
    "compare_payroll_periods": compare_payroll_periods,
    "get_employee_hours_ranking": get_employee_hours_ranking,
    "get_incomplete_attendance": get_incomplete_attendance,
    "get_people_summary": get_people_summary,
    "get_person_images": get_person_images,
    "get_device_status": get_device_status,
    "get_shift_configuration": get_shift_configuration,
    "get_leave_summary": get_leave_summary,
    "get_class_activity_summary": get_class_activity_summary,
    "get_automated_report_status": get_automated_report_status,
    "get_parent_access_summary": get_parent_access_summary,
}


def _date_properties(*names):
    return {name: {"type": "string", "description": f"{name.replace('_', ' ')} in YYYY-MM-DD format"} for name in names}


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "get_company_profile", "description": "Look up the authenticated company/organization profile, business vertical (e.g. School, Hostel, Factory, Corporate, Kiosk), total staff/students count, configured departments/classes, standard working hours, and active devices. Use this whenever the user asks about the company name, who they are, their organization details, or general headcount.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_today_attendance_summary", "description": "Real-time comprehensive attendance dashboard for today (or a specific date). Returns total registered personnel, present count, absent count, late count, on-leave count, attendance percentage, department/class breakdown, and recent check-in arrivals with timestamps. Always use this first when asked for today's attendance summary, counts, or how many people are in today.", "parameters": {"type": "object", "properties": {"attendance_date": {"type": "string", "description": "Date in YYYY-MM-DD format or 'today'/'yesterday'; omit for today"}, "department": {"type": "string", "description": "Optional department name"}, "class_year": {"type": "string", "description": "Optional class or academic year for schools/colleges"}, "division": {"type": "string", "description": "Optional division/section"}}}}},
    {"type": "function", "function": {"name": "get_employee_attendance", "description": "Look up the entry/exit punch timeline, working hours, and late marks for an individual employee, student, or resident by name or ID. Use this whenever the user asks about a specific person's punch times (e.g., 'What time did Rahul punch in today?', 'Show attendance of Priya for last week', 'Was Amit late?').", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Name, Employee ID, Display ID, or Student/Roll Number of the person"}, "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format; defaults to 30 days ago"}, "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format; defaults to today"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_live_punches", "description": "Real-time stream of the latest punch events across the organization sorted newest first. Shows who punched, timestamp, punch type (IN/OUT), department, and device. Use this for questions like 'Who just punched in?', 'Show recent attendance events', or 'Live punches'.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Number of recent punches to retrieve (default 20)"}, "department": {"type": "string"}, "attendance_date": {"type": "string", "description": "Date in YYYY-MM-DD format; omit for today"}}}}},
    {"type": "function", "function": {"name": "get_employee_details", "description": "Search the directory for an individual (employee, student, or resident) by name or ID. Returns their profile details, shift, wage setup, and their live attendance status for today (PRESENT with punch-in time, ON LEAVE with reason, or ABSENT). Use this for queries like 'Is John here today?', 'Find student EMP101', or 'Who is Priya?'.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Name, Employee ID, Display ID, or Student/Roll Number of the person"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_class_attendance_summary", "description": "Summarize student attendance grouped by class, division, or section for academic institutions (Schools, Colleges). Returns present and late counts per class. Use this when the user asks about class-wise attendance or student batches.", "parameters": {"type": "object", "properties": {"attendance_date": {"type": "string", "description": "Date in YYYY-MM-DD format; omit for today"}, "class_year": {"type": "string", "description": "Optional class or academic year"}, "division": {"type": "string", "description": "Optional division"}, "branch": {"type": "string", "description": "Optional branch"}}}}},
    {"type": "function", "function": {"name": "get_attendance_summary", "description": "Summarize attendance, presence, late days, and attendance rate for a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "get_present_people", "description": "List the registered people who have an attendance event on a date. Use this for questions asking who is present, which employees are present, or for the names of people present today/on a specific day. Can filter by department or search by name. The date is optional and defaults to today.", "parameters": {"type": "object", "properties": {"attendance_date": {"type": "string", "description": "Date in YYYY-MM-DD format; omit for today"}, "department": {"type": "string"}, "name": {"type": "string", "description": "Optional name filter to search for a specific person"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}}}},
    {"type": "function", "function": {"name": "get_absent_people", "description": "List the registered people who have no attendance event on a date. Use this for questions asking who is absent or missing today/on a specific day. Can filter by department or search by name. The date is optional and defaults to today.", "parameters": {"type": "object", "properties": {"attendance_date": {"type": "string", "description": "Date in YYYY-MM-DD format; omit for today"}, "department": {"type": "string"}, "name": {"type": "string", "description": "Optional name filter to search for a specific person"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}}}},
    {"type": "function", "function": {"name": "get_payroll_summary", "description": "Calculate total payable hours and estimated wages for a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_person_payroll", "description": "Look up gross earnings, owner-approved advance deductions, net payable, and payable hours for a named individual. Use this whenever a user asks about one person's wage, salary, payroll, current amount to pay, or hours. Dates are optional and default to the current month through today.", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Full or partial person name"}, **_date_properties("start_date", "end_date")}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_person_advances", "description": "List advance payments taken by a named person and total them. Use this for questions about an individual's advances; do not use the payroll estimate tool. Optionally filter by deduction month.", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Full or partial person name"}, "deduction_month": {"type": "string", "description": "Optional month in YYYY-MM format"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_advance_approval_summary", "description": "Count, total, or list employee advance requests in the owner approval queue. Use this for pending, awaiting approval, approved, rejected, remaining, or vendor-wide advance questions. Defaults to pending requests.", "parameters": {"type": "object", "properties": {"status": {"type": "string", "enum": ["pending", "approved", "rejected", "deducted", "all"], "description": "Approval status; omit to show pending"}, "deduction_month": {"type": "string", "description": "Optional payroll deduction month in YYYY-MM format"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}}}},
    {"type": "function", "function": {"name": "compare_payroll_periods", "description": "Compare estimated wages between two date periods.", "parameters": {"type": "object", "properties": {**_date_properties("current_start", "current_end", "previous_start", "previous_end"), "department": {"type": "string"}}, "required": ["current_start", "current_end", "previous_start", "previous_end"]}}},
    {"type": "function", "function": {"name": "get_employee_hours_ranking", "description": "Rank employees by payable hours in a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25, "order": {"type": "string", "enum": ["highest", "lowest"]}}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_incomplete_attendance", "description": "Find attendance days ending with a check-in but no later check-out.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_people_summary", "description": "Count or list registered people by department, designation, or shift.", "parameters": {"type": "object", "properties": {"department": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}}}},
    {"type": "function", "function": {"name": "get_person_images", "description": "Find a named person's registered photo and recent attendance capture images. Use this for requests to find, show, or view photos/images of an individual.", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Full or partial person name"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_device_status", "description": "List registered cameras/mobile devices and summarize activity, battery, and geofence configuration.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25}}}}},
    {"type": "function", "function": {"name": "get_shift_configuration", "description": "Read the published work timetable, working hours, payable activities, and overnight shifts.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_leave_summary", "description": "Summarize or list leave requests and gate passes with multi-stage approval statuses (parent, rector/warden, HOD, final).", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "status": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}}}},
    {"type": "function", "function": {"name": "get_class_activity_summary", "description": "Summarize configured classes, lectures, subjects, teachers, and lecture attendance for a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_automated_report_status", "description": "Read the automated email report schedule and recent delivery statuses.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25}}}}},
    {"type": "function", "function": {"name": "get_parent_access_summary", "description": "Summarize parent accounts, student links, and pending face-reset requests.", "parameters": {"type": "object", "properties": {}}}},
]


TOOL_FEATURES = {
    "get_company_profile": {"reports", "report_detailed", "payroll"},
    "get_today_attendance_summary": {"reports", "report_detailed", "live_attendance", "enable_attendance", "checkin_checkout"},
    "get_employee_attendance": {"reports", "report_detailed", "live_attendance", "enable_attendance", "checkin_checkout"},
    "get_live_punches": {"live_attendance", "cameras", "mobile_app"},
    "get_employee_details": {"reports", "report_detailed", "payroll", "shifts"},
    "get_class_attendance_summary": {"classes", "bulk_image_attendance", "lecture_wise_reports"},
    "get_attendance_summary": {"reports", "report_detailed", "live_attendance", "enable_attendance", "checkin_checkout"},
    "get_present_people": {"reports", "report_detailed", "live_attendance", "enable_attendance", "checkin_checkout"},
    "get_absent_people": {"reports", "report_detailed", "live_attendance", "enable_attendance", "checkin_checkout"},
    "get_incomplete_attendance": {"reports", "report_detailed", "live_attendance", "enable_attendance", "checkin_checkout"},
    "get_payroll_summary": {"payroll", "report_payroll", "payable_hours"},
    "get_person_payroll": {"payroll", "report_payroll", "payable_hours"},
    "get_person_advances": {"payroll", "report_payroll", "payable_hours"},
    "get_advance_approval_summary": {"payroll", "report_payroll", "payable_hours", "wages"},
    "compare_payroll_periods": {"payroll", "report_payroll", "payable_hours"},
    "get_employee_hours_ranking": {"payroll", "report_payroll", "payable_hours"},
    "get_device_status": {"cameras", "mobile_app", "geofencing", "live_attendance"},
    "get_shift_configuration": {"shifts", "add_shift", "night_shift_logic", "payable_hours"},
    "get_leave_summary": {"leave_management"},
    "get_class_activity_summary": {"classes", "bulk_image_attendance", "lecture_wise_reports"},
    "get_automated_report_status": {"automated_email_reports"},
    "get_parent_access_summary": {"parent_login", "parent_alerts"},
}


def available_tool_schemas(features):
    enabled = set(features or [])
    available = []
    for schema in TOOL_SCHEMAS:
        name = schema["function"]["name"]
        required = TOOL_FEATURES.get(name)
        if not required or required & enabled:
            available.append(schema)
    return available


def execute_tool(name, arguments, vendor_id, features):
    if name not in TOOL_REGISTRY:
        raise ValueError("Unknown or unauthorized XChat tool")
    required = TOOL_FEATURES.get(name)
    if required and not (required & set(features or [])):
        raise PermissionError("The required feature is not enabled for this vendor")
    safe_arguments = dict(arguments or {})
    safe_arguments.pop("vendor_id", None)
    return TOOL_REGISTRY[name](vendor_id=vendor_id, **safe_arguments)
