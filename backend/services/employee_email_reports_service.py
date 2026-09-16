"""Employee-facing monthly attendance and wage email reports."""

import calendar
import csv
import io
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from services.email_service import send_email
from services.payroll_service import calculate_salary_breakdown, get_approved_advances
from services.person_scope_service import person_type_for, requested_person_type, vendor_vertical


logger = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_FIELDS = frozenset({
    "email", "email_address", "email_id", "employee_email", "employee_email_address",
    "official_email", "work_email", "student_email", "faculty_email",
})


def _db():
    from utils import get_db_connection
    return get_db_connection()


def _row_dict(row):
    return dict(row) if row is not None else {}


def _custom_data(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def employee_email(person):
    custom = _custom_data(person.get("custom_data"))
    normalized_custom = {
        re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_"): value
        for key, value in custom.items()
    }
    candidates = [person.get("email"), *(normalized_custom.get(field) for field in EMAIL_FIELDS)]
    for candidate in candidates:
        value = str(candidate or "").strip().lower()
        if EMAIL_RE.match(value):
            return value
    return None


def month_period(month):
    try:
        start = datetime.strptime(str(month), "%Y-%m").date().replace(day=1)
    except (TypeError, ValueError):
        raise ValueError("month must use YYYY-MM format")
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    return start, end


def _matches_filters(person, filters):
    if not filters or not isinstance(filters, dict):
        return True

    # 1. Standard filters: department, designation, shift, phone
    standard_keys = ("department", "designation", "shift", "phone")
    for key in standard_keys:
        expected = str(filters.get(key) or "").strip()
        if expected and str(person.get(key) or "").strip().lower() != expected.lower():
            return False

    # 2. Dynamic / custom_data filters
    dynamic_filters = {}
    if isinstance(filters.get("dynamic"), dict):
        dynamic_filters.update(filters["dynamic"])
    if isinstance(filters.get("custom_filters"), dict):
        dynamic_filters.update(filters["custom_filters"])

    skip_keys = set(standard_keys) | {
        "dynamic", "custom_filters", "month", "person_type",
        "startDate", "endDate", "type", "start_date", "end_date",
    }
    for k, v in filters.items():
        if k not in skip_keys and v:
            dynamic_filters[k] = v

    if dynamic_filters:
        custom = _custom_data(person.get("custom_data"))
        from services.report_filter_service import custom_filter_values
        for dyn_key, expected_val in dynamic_filters.items():
            expected = str(expected_val or "").strip().lower()
            if not expected:
                continue
            actual_values = [value.lower() for value in custom_filter_values(custom, dyn_key)]
            if expected not in actual_values:
                return False

    return True


def _load_people(cursor, vendor_id, person_type=None, filters=None):
    # Resolve scope first. Executing this query after the faces query on the
    # same cursor would replace the pending employee result set.
    vertical = vendor_vertical(cursor, vendor_id)
    cursor.execute("""
        SELECT f.*,
               (SELECT su.role FROM system_users su
                WHERE su.person_id = f.id AND su.vendor_id = f.vendor_id
                ORDER BY CASE WHEN LOWER(su.role) = 'faculty' THEN 0 ELSE 1 END
                LIMIT 1) AS system_role
        FROM faces f WHERE f.vendor_id = ? ORDER BY f.name
    """, (vendor_id,))
    rows = cursor.fetchall() or []
    wanted_type = requested_person_type(person_type, vertical)
    people = []
    for raw in rows:
        person = _row_dict(raw)
        resolved_type = person_type_for(person.get("custom_data"), person.get("system_role"), vertical)
        if wanted_type and resolved_type != wanted_type:
            continue
        if filters and not _matches_filters(person, filters):
            continue
        person["person_type"] = resolved_type
        person["email"] = employee_email(person)
        people.append(person)
    return people


def count_employee_report_recipients(vendor_id, person_type=None, filters=None):
    conn = _db()
    try:
        people = _load_people(conn.cursor(), vendor_id, person_type, filters=filters)
        return sum(1 for person in people if person.get("email"))
    finally:
        conn.close()


def preview_employee_report_recipients(vendor_id, person_type=None, filters=None):
    conn = _db()
    try:
        people = _load_people(conn.cursor(), vendor_id, person_type, filters=filters)
        matching_count = len(people)
        eligible = [p for p in people if p.get("email")]
        missing_email = [p for p in people if not p.get("email")]
        return {
            "total_matching": matching_count,
            "eligible_count": len(eligible),
            "missing_email_count": len(missing_email),
            "sample_recipients": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "email": p.get("email"),
                    "department": p.get("department"),
                    "designation": p.get("designation"),
                }
                for p in people[:15]
            ]
        }
    finally:
        conn.close()


def _settings(cursor, vendor_id):
    defaults = {
        "global_late_allowance": 7,
        "global_late_deduction": 0,
        "global_pf_percentage": 12,
        "global_esi_percentage": 0.75,
        "global_gratuity_percentage": 4.81,
        "global_gratuity_threshold_years": 5,
    }
    keys = [f"{key}_vendor_{vendor_id}" for key in defaults]
    placeholders = ", ".join("?" for _ in keys)
    try:
        cursor.execute(f"SELECT key, value FROM system_settings WHERE key IN ({placeholders})", keys)
        for row in cursor.fetchall() or []:
            key = str(row[0]).removesuffix(f"_vendor_{vendor_id}")
            defaults[key] = row[1]
    except Exception:
        logger.debug("Payroll settings unavailable while creating employee reports", exc_info=True)
    return defaults


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _timestamp(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _attachments(person, records, period, payroll):
    start, end = period
    slug = f"{start.isoformat()}_{end.isoformat()}"

    attendance_output = io.StringIO()
    writer = csv.writer(attendance_output)
    writer.writerow(["Date", "Timestamp", "Status", "Activity", "Late"])
    for record in records:
        stamp = _timestamp(record.get("timestamp"))
        if stamp and start <= stamp.date() <= end:
            writer.writerow([
                stamp.date().isoformat(), stamp.isoformat(sep=" "), record.get("status") or "",
                record.get("activity") or "", "Yes" if record.get("is_late") else "No",
            ])

    wage_output = io.StringIO()
    writer = csv.writer(wage_output)
    writer.writerow(["Employee", "Period", "Days Present", "Payable Hours", "Daily Wage", "Gross Earnings", "PF", "ESI", "Professional Tax", "Late Deduction", "Approved Advance Deduction", "Net Payable"])
    writer.writerow([
        person.get("name"), f"{start.isoformat()} to {end.isoformat()}", payroll["days_present"],
        payroll["total_hours"], payroll["daily_wage"], payroll["gross"], payroll["pf"],
        payroll["esi"], payroll["professional_tax"], payroll["late_deduction"],
        payroll["approved_advance_deduction"], payroll["net_payable"],
    ])
    return [
        {"filename": f"attendance_{slug}.csv", "content": attendance_output.getvalue(), "mimetype": "text/csv"},
        {"filename": f"wages_{slug}.csv", "content": wage_output.getvalue(), "mimetype": "text/csv"},
    ]


def build_employee_monthly_deliveries(vendor_id, month, person_type=None, filters=None):
    from services.attendance_service import calculate_daily_hours

    start, end = month_period(month)
    conn = _db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT company_name FROM vendors WHERE id = ?", (vendor_id,))
        vendor = cursor.fetchone()
        vendor_name = vendor[0] if vendor else f"Vendor {vendor_id}"
        cursor.execute("SELECT live_timetable, working_hours FROM companies WHERE vendor_id = ? LIMIT 1", (vendor_id,))
        company = cursor.fetchone()
        try:
            timetable = json.loads(company[0] or "[]") if company else []
        except (TypeError, ValueError):
            timetable = []
        working_hours = max(0.25, _as_float(company[1] if company else 8, 8))
        settings = _settings(cursor, vendor_id)
        people = _load_people(cursor, vendor_id, person_type, filters=filters)
        person_ids = {person["id"] for person in people}

        cursor.execute("""
            SELECT person_id, timestamp, status, activity, is_late
            FROM attendance
            WHERE vendor_id = ? AND date(timestamp) BETWEEN ? AND ? AND person_id IS NOT NULL
            ORDER BY person_id, timestamp
        """, (vendor_id, (start - timedelta(days=1)).isoformat(), (end + timedelta(days=1)).isoformat()))
        grouped = defaultdict(list)
        for raw in cursor.fetchall() or []:
            record = _row_dict(raw)
            if record.get("person_id") in person_ids:
                grouped[record["person_id"]].append(record)

        deliveries = []
        skipped_without_email = 0
        for person in people:
            if not person.get("email"):
                skipped_without_email += 1
                continue
            records = grouped.get(person["id"], [])
            sessions = calculate_daily_hours(records, timetable).get("sessions", [])
            total_hours = 0.0
            present_dates = set()
            for session in sessions:
                stamp = _timestamp(session.get("start_ts"))
                if stamp and start <= stamp.date() <= end and session.get("is_payable", False):
                    total_hours += _as_float(session.get("duration_mins")) / 60
                    present_dates.add(stamp.date())

            late_dates = {
                stamp.date() for record in records
                if record.get("is_late") and (stamp := _timestamp(record.get("timestamp"))) and start <= stamp.date() <= end
            }
            allowance = person.get("late_allowance_days")
            allowance = _as_int(allowance, settings["global_late_allowance"]) if allowance is not None else _as_int(settings["global_late_allowance"], 7)
            late_rate = person.get("late_deduction_amount")
            late_rate = _as_float(late_rate, settings["global_late_deduction"]) if late_rate is not None else _as_float(settings["global_late_deduction"])
            late_deduction = round(max(0, len(late_dates) - allowance) * late_rate, 2)
            daily_wage = _as_float(person.get("daily_wage"))
            base_cost = round(total_hours * (daily_wage / working_hours), 2)

            tenure_years = 0.0
            if person.get("joining_date"):
                try:
                    joined = datetime.strptime(str(person["joining_date"])[:10], "%Y-%m-%d").date()
                    tenure_years = max(0, (end - joined).days / 365.25)
                except (TypeError, ValueError):
                    pass
            config = dict(person)
            config["tenure_years"] = tenure_years
            breakdown = calculate_salary_breakdown(
                base_cost, config,
                pf_percent=_as_float(settings["global_pf_percentage"], 12),
                esi_percent=_as_float(settings["global_esi_percentage"], 0.75),
                gratuity_percent=_as_float(settings["global_gratuity_percentage"], 4.81),
                gratuity_threshold_years=_as_int(settings["global_gratuity_threshold_years"], 5),
            )
            advances = get_approved_advances(conn, person["id"], start.strftime("%Y-%m"))
            approved_advance = round(sum(_as_float(row[1]) for row in advances), 2)
            net_payable = round(breakdown["net_before_advances"] - late_deduction - approved_advance, 2)
            payroll = {
                "days_present": len(present_dates), "total_hours": round(total_hours, 2),
                "daily_wage": daily_wage, "gross": round(breakdown["gross"], 2),
                "pf": breakdown["deductions"]["pf"], "esi": breakdown["deductions"]["esi"],
                "professional_tax": breakdown["deductions"]["pt"], "late_deduction": late_deduction,
                "approved_advance_deduction": approved_advance, "net_payable": net_payable,
            }
            body = (
                f"Hello {person.get('name') or 'Employee'},\n\n"
                f"Your attendance and wage report from {start.isoformat()} to {end.isoformat()} is attached.\n\n"
                f"Days present: {payroll['days_present']}\n"
                f"Payable hours: {payroll['total_hours']:.2f}\n"
                f"Gross earnings: INR {payroll['gross']:.2f}\n"
                f"PF deduction: INR {payroll['pf']:.2f}\n"
                f"ESI deduction: INR {payroll['esi']:.2f}\n"
                f"Late deduction: INR {payroll['late_deduction']:.2f}\n"
                f"Approved advance deduction: INR {payroll['approved_advance_deduction']:.2f}\n"
                f"Net payable: INR {payroll['net_payable']:.2f}\n\n"
                "Regards,\nOpenVisionX Reports"
            )
            deliveries.append({
                "person_id": person["id"], "recipient": person["email"],
                "subject": f"{vendor_name} — attendance and wage report ({start.strftime('%B %Y')})",
                "body": body, "attachments": _attachments(person, records, (start, end), payroll),
            })
        return vendor_name, deliveries, skipped_without_email
    finally:
        conn.close()


def send_employee_monthly_reports(vendor_id, month, person_type=None, filters=None):
    vendor_name, deliveries, skipped_without_email = build_employee_monthly_deliveries(vendor_id, month, person_type, filters=filters)
    sent = 0
    failures = []
    for delivery in deliveries:
        try:
            send_email(delivery["subject"], delivery["body"], delivery["recipient"], delivery["attachments"])
            sent += 1
        except Exception as exc:
            logger.exception("Employee report email failed for vendor=%s person=%s", vendor_id, delivery["person_id"])
            failures.append({"person_id": delivery["person_id"], "error": str(exc)[:300]})
    return {
        "vendor": vendor_name, "month": month, "eligible": len(deliveries), "sent": sent,
        "skipped_without_email": skipped_without_email, "failed": len(failures), "failures": failures,
    }


def send_advance_notification(advance_id, event):
    conn = _db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT a.id, a.amount, a.amount_cash, a.amount_online, a.date, a.status,
                   a.deduction_month, a.rejection_reason, f.name, f.custom_data,
                   v.company_name
            FROM advances a
            JOIN faces f ON f.id = a.person_id AND f.vendor_id = a.vendor_id
            JOIN vendors v ON v.id = a.vendor_id
            WHERE a.id = ?
        """, (advance_id,))
        row = cursor.fetchone()
        if not row:
            return {"status": "missing"}
        advance = _row_dict(row)
    finally:
        conn.close()
    recipient = employee_email(advance)
    if not recipient:
        return {"status": "skipped", "reason": "employee has no email"}
    event = str(event or advance.get("status") or "requested").lower()
    if event == "approved":
        detail = f"Your advance request has been approved and will be deducted from payroll for {advance.get('deduction_month') or 'the configured month'}."
    elif event == "rejected":
        reason = str(advance.get("rejection_reason") or "").strip()
        detail = "Your advance request has been rejected and will not be deducted from payroll."
        if reason:
            detail += f" Reason: {reason}"
    else:
        detail = "Your advance request was recorded and is pending owner approval. It will not affect payroll until it is approved."
    subject = f"{advance.get('company_name') or 'OpenVisionX'} — advance request {event}"
    body = (
        f"Hello {advance.get('name') or 'Employee'},\n\n{detail}\n\n"
        f"Amount: INR {_as_float(advance.get('amount')):.2f}\n"
        f"Requested date: {advance.get('date') or '-'}\n"
        f"Deduction month: {advance.get('deduction_month') or '-'}\n\n"
        "Regards,\nOpenVisionX"
    )
    message_id = send_email(subject, body, recipient)
    return {"status": "sent", "message_id": message_id, "recipient": recipient}


def queue_advance_notification(advance_id, event):
    """Queue without ever making the advance transaction depend on SMTP/broker health."""
    try:
        from tasks import send_advance_notification_task
        send_advance_notification_task.apply_async(args=[advance_id, event], queue="notifications")
        return True
    except Exception:
        logger.warning("Advance email could not be queued for advance=%s event=%s", advance_id, event, exc_info=True)
        return False
