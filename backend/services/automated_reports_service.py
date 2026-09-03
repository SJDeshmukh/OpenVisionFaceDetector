import calendar
import csv
import io
import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
FREQUENCIES = ("daily", "weekly", "monthly")
REPORT_TYPES = ("attendance_detail", "attendance_summary")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEFAULT_SCHEDULE = {
    "enabled": False,
    "recipient_email": "",
    "timezone": "Asia/Kolkata",
    "send_time": "08:00",
    "operational_day_cutoff": "07:00",
    "grace_minutes": 30,
    "frequencies": [],
    "daily_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "weekly_days": ["Sun"],
    "monthly_mode": "last_working_day",
    "monthly_day": None,
    "report_types": ["attendance_detail", "attendance_summary"],
}


def _row_dict(row):
    return dict(row) if row is not None else None


def _get_db_connection():
    # Keep calendar validation importable in lightweight worker/test environments.
    from utils import get_db_connection
    return get_db_connection()


def _json_list(value, default=None):
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else list(default or [])
    except Exception:
        return list(default or [])


def serialize_schedule(row, vendor_email=""):
    result = dict(DEFAULT_SCHEDULE)
    if row:
        result.update(_row_dict(row))
        result["enabled"] = bool(result.get("enabled"))
        for key in ("frequencies", "daily_days", "weekly_days", "report_types"):
            result[key] = _json_list(result.get(key), DEFAULT_SCHEDULE[key])
    result["recipient_email"] = result.get("recipient_email") or vendor_email or ""
    return result


def validate_schedule(payload, vendor_email=""):
    data = dict(DEFAULT_SCHEDULE)
    data.update(payload or {})
    data["enabled"] = bool(data.get("enabled"))
    data["recipient_email"] = str(data.get("recipient_email") or vendor_email or "").strip().lower()
    if data["enabled"] and not EMAIL_RE.match(data["recipient_email"]):
        raise ValueError("A valid report recipient email is required")

    try:
        ZoneInfo(str(data["timezone"]))
    except ZoneInfoNotFoundError:
        raise ValueError("Invalid timezone")

    for field in ("send_time", "operational_day_cutoff"):
        try:
            datetime.strptime(str(data[field]), "%H:%M")
        except ValueError:
            raise ValueError(f"{field} must use HH:MM format")

    data["grace_minutes"] = int(data.get("grace_minutes", 30))
    if not 0 <= data["grace_minutes"] <= 720:
        raise ValueError("grace_minutes must be between 0 and 720")

    data["frequencies"] = [x for x in dict.fromkeys(data.get("frequencies") or []) if x in FREQUENCIES]
    data["daily_days"] = [x for x in dict.fromkeys(data.get("daily_days") or []) if x in DAYS]
    data["weekly_days"] = [x for x in dict.fromkeys(data.get("weekly_days") or []) if x in DAYS]
    data["report_types"] = [x for x in dict.fromkeys(data.get("report_types") or []) if x in REPORT_TYPES]
    if data["enabled"] and not data["frequencies"]:
        raise ValueError("Select at least one report frequency")
    if "daily" in data["frequencies"] and not data["daily_days"]:
        raise ValueError("Select at least one daily reporting day")
    if "weekly" in data["frequencies"] and not data["weekly_days"]:
        raise ValueError("Select at least one weekly period-ending day")
    if data["enabled"] and not data["report_types"]:
        raise ValueError("Select at least one report type")

    data["monthly_mode"] = str(data.get("monthly_mode") or "last_working_day")
    if data["monthly_mode"] not in ("last_working_day", "day_of_month"):
        raise ValueError("Invalid monthly mode")
    if data["monthly_mode"] == "day_of_month":
        data["monthly_day"] = int(data.get("monthly_day") or 1)
        if not 1 <= data["monthly_day"] <= 31:
            raise ValueError("Monthly day must be between 1 and 31")
    else:
        data["monthly_day"] = None

    cutoff_minutes = _minutes(data["operational_day_cutoff"]) + data["grace_minutes"]
    if data["frequencies"] and _minutes(data["send_time"]) < cutoff_minutes:
        raise ValueError("Send time must be after the operational cutoff and grace period")
    return data


def _minutes(value):
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


def save_schedule(vendor_id, payload):
    conn = _get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT email FROM vendors WHERE id = ?", (vendor_id,))
        vendor = c.fetchone()
        if not vendor:
            raise LookupError("Vendor not found")
        vendor_email = vendor[0]
        data = validate_schedule(payload, vendor_email)
        c.execute("""
            INSERT INTO automated_report_schedules
                (vendor_id, enabled, recipient_email, timezone, send_time,
                 operational_day_cutoff, grace_minutes, frequencies, daily_days,
                 weekly_days, monthly_mode, monthly_day, report_types, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(vendor_id) DO UPDATE SET
                enabled=excluded.enabled, recipient_email=excluded.recipient_email,
                timezone=excluded.timezone, send_time=excluded.send_time,
                operational_day_cutoff=excluded.operational_day_cutoff,
                grace_minutes=excluded.grace_minutes, frequencies=excluded.frequencies,
                daily_days=excluded.daily_days, weekly_days=excluded.weekly_days,
                monthly_mode=excluded.monthly_mode, monthly_day=excluded.monthly_day,
                report_types=excluded.report_types, updated_at=CURRENT_TIMESTAMP
        """, (
            vendor_id, 1 if data["enabled"] else 0, data["recipient_email"], data["timezone"],
            data["send_time"], data["operational_day_cutoff"], data["grace_minutes"],
            json.dumps(data["frequencies"]), json.dumps(data["daily_days"]),
            json.dumps(data["weekly_days"]), data["monthly_mode"], data["monthly_day"],
            json.dumps(data["report_types"]),
        ))
        conn.commit()
        c.execute("SELECT * FROM automated_report_schedules WHERE vendor_id = ?", (vendor_id,))
        return serialize_schedule(c.fetchone(), vendor_email)
    finally:
        conn.close()


def get_schedule(vendor_id):
    conn = _get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT email FROM vendors WHERE id = ?", (vendor_id,))
        vendor = c.fetchone()
        if not vendor:
            raise LookupError("Vendor not found")
        c.execute("SELECT * FROM automated_report_schedules WHERE vendor_id = ?", (vendor_id,))
        return serialize_schedule(c.fetchone(), vendor[0])
    finally:
        conn.close()


def _working_days_for_vendor(c, vendor_id):
    c.execute("SELECT live_timetable FROM companies WHERE vendor_id = ? LIMIT 1", (vendor_id,))
    row = c.fetchone()
    try:
        timetable = json.loads(row[0] or "[]") if row else []
        days = {d for activity in timetable if activity.get("enabled", True) for d in activity.get("days", [])}
        return days or {"Mon", "Tue", "Wed", "Thu", "Fri"}
    except Exception:
        return {"Mon", "Tue", "Wed", "Thu", "Fri"}


def _is_month_end_date(candidate, schedule, working_days):
    last_day = calendar.monthrange(candidate.year, candidate.month)[1]
    if schedule["monthly_mode"] == "day_of_month":
        return candidate.day == min(int(schedule["monthly_day"]), last_day)
    cursor = date(candidate.year, candidate.month, last_day)
    while cursor.strftime("%a") not in working_days:
        cursor -= timedelta(days=1)
    return candidate == cursor


def due_periods(schedule, now=None, working_days=None):
    tz = ZoneInfo(schedule["timezone"])
    now = now.astimezone(tz) if now else datetime.now(tz)
    send_at = datetime.combine(now.date(), datetime.strptime(schedule["send_time"], "%H:%M").time(), tzinfo=tz)
    # Catch a temporarily delayed Beat/worker on the same delivery day.
    if now < send_at or now >= send_at + timedelta(hours=24):
        return []
    completed = now.date() - timedelta(days=1)
    cutoff_at = datetime.combine(completed + timedelta(days=1), datetime.strptime(schedule["operational_day_cutoff"], "%H:%M").time(), tzinfo=tz)
    if now < cutoff_at + timedelta(minutes=int(schedule["grace_minutes"])):
        return []

    periods = []
    completed_day = completed.strftime("%a")
    if "daily" in schedule["frequencies"] and completed_day in schedule["daily_days"]:
        periods.append(("daily", completed, completed))
    if "weekly" in schedule["frequencies"] and completed_day in schedule["weekly_days"]:
        periods.append(("weekly", completed - timedelta(days=6), completed))
    if "monthly" in schedule["frequencies"] and _is_month_end_date(completed, schedule, working_days or {"Mon", "Tue", "Wed", "Thu", "Fri"}):
        periods.append(("monthly", completed.replace(day=1), completed))
    return periods


def dispatch_due_reports(now=None):
    conn = _get_db_connection()
    c = conn.cursor()
    queued = []
    try:
        c.execute("""
            SELECT ars.*, v.email AS vendor_email, v.status AS vendor_status, s.features
            FROM automated_report_schedules ars
            JOIN vendors v ON v.id = ars.vendor_id
            LEFT JOIN subscriptions s ON s.vendor_id = ars.vendor_id
            WHERE ars.enabled = 1
        """)
        for raw in c.fetchall() or []:
            raw_dict = _row_dict(raw)
            features = _json_list(raw_dict.get("features"))
            if raw_dict.get("vendor_status") != "active" or "automated_email_reports" not in features:
                continue
            schedule = serialize_schedule(raw, raw_dict.get("vendor_email"))
            working_days = _working_days_for_vendor(c, schedule["vendor_id"])
            for frequency, period_start, period_end in due_periods(schedule, now, working_days):
                c.execute("""
                    INSERT INTO automated_report_deliveries
                        (schedule_id, vendor_id, frequency, period_start, period_end, status, recipient_email)
                    VALUES (?, ?, ?, ?, ?, 'queued', ?)
                    ON CONFLICT(schedule_id, frequency, period_start, period_end) DO NOTHING
                """, (schedule["id"], schedule["vendor_id"], frequency, period_start.isoformat(), period_end.isoformat(), schedule["recipient_email"]))
                if c.rowcount:
                    c.execute("SELECT id FROM automated_report_deliveries WHERE schedule_id = ? AND frequency = ? AND period_start = ? AND period_end = ?", (schedule["id"], frequency, period_start.isoformat(), period_end.isoformat()))
                    queued.append(c.fetchone()[0])
        conn.commit()
        return queued
    finally:
        conn.close()


def build_report_attachments(vendor_id, period_start, period_end, cutoff="07:00", report_types=None):
    report_types = report_types or list(REPORT_TYPES)
    cutoff_time = datetime.strptime(cutoff, "%H:%M").time()
    window_start = datetime.combine(period_start, cutoff_time)
    window_end = datetime.combine(period_end + timedelta(days=1), cutoff_time)
    conn = _get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT company_name FROM vendors WHERE id = ?", (vendor_id,))
        vendor = c.fetchone()
        vendor_name = vendor[0] if vendor else f"Vendor {vendor_id}"
        c.execute("""
            SELECT a.name, a.timestamp, a.status, a.activity, a.is_late,
                   f.department, f.designation, f.shift, f.phone
            FROM attendance a LEFT JOIN faces f ON a.person_id = f.id
            WHERE a.vendor_id = ? AND a.timestamp >= ? AND a.timestamp < ?
            ORDER BY a.timestamp ASC
        """, (vendor_id, window_start, window_end))
        rows = [_row_dict(row) for row in (c.fetchall() or [])]
    finally:
        conn.close()

    attachments = []
    slug = f"{period_start.isoformat()}_{period_end.isoformat()}"
    if "attendance_detail" in report_types:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Operational Date", "Name", "Timestamp", "Status", "Activity", "Late", "Department", "Designation", "Shift", "Phone"])
        for row in rows:
            stamp = row.get("timestamp")
            if isinstance(stamp, str):
                try: stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError: stamp = None
            operational_date = (stamp - timedelta(hours=cutoff_time.hour, minutes=cutoff_time.minute)).date() if isinstance(stamp, datetime) else ""
            writer.writerow([operational_date, row.get("name"), stamp, row.get("status"), row.get("activity"), "Yes" if row.get("is_late") else "No", row.get("department"), row.get("designation"), row.get("shift"), row.get("phone")])
        attachments.append({"filename": f"attendance_detail_{slug}.csv", "content": output.getvalue(), "mimetype": "text/csv"})

    if "attendance_summary" in report_types:
        grouped = defaultdict(lambda: {"events": 0, "late": False, "first": None, "last": None})
        for row in rows:
            stamp = row.get("timestamp")
            if isinstance(stamp, str):
                try: stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError: continue
            if not isinstance(stamp, datetime): continue
            operational_date = (stamp - timedelta(hours=cutoff_time.hour, minutes=cutoff_time.minute)).date()
            item = grouped[(operational_date, row.get("name") or "Unknown")]
            item["events"] += 1
            item["late"] = item["late"] or bool(row.get("is_late"))
            item["first"] = min(item["first"], stamp) if item["first"] else stamp
            item["last"] = max(item["last"], stamp) if item["last"] else stamp
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Operational Date", "Name", "First Event", "Last Event", "Events", "Late"])
        for (operational_date, name), item in sorted(grouped.items()):
            writer.writerow([operational_date, name, item["first"], item["last"], item["events"], "Yes" if item["late"] else "No"])
        attachments.append({"filename": f"attendance_summary_{slug}.csv", "content": output.getvalue(), "mimetype": "text/csv"})
    return vendor_name, attachments, len(rows)
