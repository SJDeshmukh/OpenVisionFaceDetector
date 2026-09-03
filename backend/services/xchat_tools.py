"""Allow-listed, read-only XChat business tools.

Every public tool receives vendor_id from the authenticated server context.  It is
intentionally absent from every model-visible schema.
"""

import json
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


def _period(start_date, end_date):
    try:
        start = datetime.strptime(str(start_date), "%Y-%m-%d").date()
        end = datetime.strptime(str(end_date), "%Y-%m-%d").date()
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


def get_attendance_summary(vendor_id, start_date, end_date, department=None):
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
    """Return an individual person's estimated payroll, defaulting to this month."""
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
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "query": search_name, "matched_people": len(matches), "people": matches[:MAX_RESULT_ROWS],
        "estimated_wages": round(sum(item["estimated_wages"] for item in matches), 2),
        "total_payable_hours": round(sum(item["hours"] for item in matches), 2),
        "currency": "INR",
        "note": "Estimated wages use recorded payable hours and the person's daily-wage rate; statutory and manual adjustments are not included.",
        "source_path": "/wages",
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


def get_leave_summary(vendor_id, start_date, end_date, status=None, limit=20):
    start, end = _period(start_date, end_date)
    conn = _db()
    c = conn.cursor()
    try:
        query = """
            SELECT lr.id, f.name, lr.leave_type, lr.start_date, lr.end_date, lr.final_status, lr.created_at
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
        "name": row.get("name"), "leave_type": row.get("leave_type"),
        "start_date": str(row.get("start_date")), "end_date": str(row.get("end_date")),
        "status": row.get("final_status"),
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
    "get_attendance_summary": get_attendance_summary,
    "get_payroll_summary": get_payroll_summary,
    "get_person_payroll": get_person_payroll,
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
    {"type": "function", "function": {"name": "get_attendance_summary", "description": "Summarize attendance, presence, late days, and attendance rate for a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_payroll_summary", "description": "Calculate total payable hours and estimated wages for a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_person_payroll", "description": "Look up estimated wages and payable hours for a named individual. Use this whenever a user asks about one person's wage, salary, payroll, or hours. Dates are optional and default to the current month through today.", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Full or partial person name"}, **_date_properties("start_date", "end_date")}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "compare_payroll_periods", "description": "Compare estimated wages between two date periods.", "parameters": {"type": "object", "properties": {**_date_properties("current_start", "current_end", "previous_start", "previous_end"), "department": {"type": "string"}}, "required": ["current_start", "current_end", "previous_start", "previous_end"]}}},
    {"type": "function", "function": {"name": "get_employee_hours_ranking", "description": "Rank employees by payable hours in a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}, "order": {"type": "string", "enum": ["highest", "lowest"]}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_incomplete_attendance", "description": "Find attendance days ending with a check-in but no later check-out.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_people_summary", "description": "Count or list registered people by department, designation, or shift.", "parameters": {"type": "object", "properties": {"department": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}}}},
    {"type": "function", "function": {"name": "get_person_images", "description": "Find a named person's registered photo and recent attendance capture images. Use this for requests to find, show, or view photos/images of an individual.", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Full or partial person name"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_device_status", "description": "List registered cameras/mobile devices and summarize activity, battery, and geofence configuration.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25}}}}},
    {"type": "function", "function": {"name": "get_shift_configuration", "description": "Read the published work timetable, working hours, payable activities, and overnight shifts.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_leave_summary", "description": "Summarize or list leave requests for an overlapping date period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "status": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_class_activity_summary", "description": "Summarize configured classes, lectures, subjects, teachers, and lecture attendance for a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_automated_report_status", "description": "Read the automated email report schedule and recent delivery statuses.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25}}}}},
    {"type": "function", "function": {"name": "get_parent_access_summary", "description": "Summarize parent accounts, student links, and pending face-reset requests.", "parameters": {"type": "object", "properties": {}}}},
]


TOOL_FEATURES = {
    "get_attendance_summary": {"reports", "report_detailed", "live_attendance", "enable_attendance", "checkin_checkout"},
    "get_incomplete_attendance": {"reports", "report_detailed", "live_attendance", "enable_attendance", "checkin_checkout"},
    "get_payroll_summary": {"payroll", "report_payroll", "payable_hours"},
    "get_person_payroll": {"payroll", "report_payroll", "payable_hours"},
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
