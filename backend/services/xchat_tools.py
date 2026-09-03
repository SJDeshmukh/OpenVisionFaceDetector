"""Allow-listed, read-only XChat business tools.

Every public tool receives vendor_id from the authenticated server context.  It is
intentionally absent from every model-visible schema.
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta


MAX_RANGE_DAYS = 366
MAX_RESULT_ROWS = 25


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


TOOL_REGISTRY = {
    "get_attendance_summary": get_attendance_summary,
    "get_payroll_summary": get_payroll_summary,
    "compare_payroll_periods": compare_payroll_periods,
    "get_employee_hours_ranking": get_employee_hours_ranking,
    "get_incomplete_attendance": get_incomplete_attendance,
}


def _date_properties(*names):
    return {name: {"type": "string", "description": f"{name.replace('_', ' ')} in YYYY-MM-DD format"} for name in names}


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "get_attendance_summary", "description": "Summarize attendance, presence, late days, and attendance rate for a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_payroll_summary", "description": "Calculate total payable hours and estimated wages for a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "compare_payroll_periods", "description": "Compare estimated wages between two date periods.", "parameters": {"type": "object", "properties": {**_date_properties("current_start", "current_end", "previous_start", "previous_end"), "department": {"type": "string"}}, "required": ["current_start", "current_end", "previous_start", "previous_end"]}}},
    {"type": "function", "function": {"name": "get_employee_hours_ranking", "description": "Rank employees by payable hours in a period.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}, "order": {"type": "string", "enum": ["highest", "lowest"]}}, "required": ["start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "get_incomplete_attendance", "description": "Find attendance days ending with a check-in but no later check-out.", "parameters": {"type": "object", "properties": {**_date_properties("start_date", "end_date"), "department": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "required": ["start_date", "end_date"]}}},
]


PAYROLL_TOOLS = {"get_payroll_summary", "compare_payroll_periods", "get_employee_hours_ranking"}


def execute_tool(name, arguments, vendor_id, features):
    if name not in TOOL_REGISTRY:
        raise ValueError("Unknown or unauthorized XChat tool")
    if name in PAYROLL_TOOLS and not ({"payroll", "report_payroll"} & set(features or [])):
        raise PermissionError("Payroll is not enabled for this vendor")
    safe_arguments = dict(arguments or {})
    safe_arguments.pop("vendor_id", None)
    return TOOL_REGISTRY[name](vendor_id=vendor_id, **safe_arguments)
