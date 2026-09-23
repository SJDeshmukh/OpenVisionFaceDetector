"""Idempotent, timezone-aware hostel attendance alert processing."""

from collections import defaultdict
from datetime import datetime, time, timezone
import json
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


logger = logging.getLogger(__name__)
FEATURE_NAME = "hostel_attendance_alerts"
DEFAULT_STUDENT_TEMPLATE = (
    "⚠️ *Hostel Entry Reminder*\n\n"
    "Hello {student_name}, no hostel entry was recorded by {cutoff_time} on {date}. "
    "Please report to the hostel or contact the administrator."
)
DEFAULT_PARENT_TEMPLATE = (
    "⚠️ *Hostel Attendance Alert*\n\n"
    "Dear Parent/Guardian, {student_name} has not recorded hostel entry as of {current_time} "
    "on {date}. Please contact the student or hostel administrator."
)


def ensure_tables(conn):
    c = conn.cursor()
    is_pg = bool(getattr(conn, "_is_pg", False))
    id_column = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_type = "TIMESTAMP" if is_pg else "DATETIME"
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS hostel_alert_settings (
            id {id_column},
            vendor_id INTEGER NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 0,
            owner_phone TEXT,
            cutoff_time TEXT NOT NULL DEFAULT '19:00',
            escalation_minutes INTEGER NOT NULL DEFAULT 60,
            timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
            student_template TEXT,
            parent_template TEXT,
            owner_summary_enabled INTEGER NOT NULL DEFAULT 1,
            schedule_revision INTEGER NOT NULL DEFAULT 1,
            created_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP,
            updated_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS hostel_alert_deliveries (
            id {id_column},
            vendor_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            alert_date DATE NOT NULL,
            alert_type TEXT NOT NULL,
            recipient_phone TEXT,
            status TEXT NOT NULL DEFAULT 'processing',
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP,
            attempted_at {timestamp_type},
            sent_at {timestamp_type},
            UNIQUE(vendor_id, person_id, alert_date, alert_type)
        )
    """)
    if is_pg:
        c.execute("""
            ALTER TABLE hostel_alert_settings
            ADD COLUMN IF NOT EXISTS schedule_revision INTEGER NOT NULL DEFAULT 1
        """)
    else:
        c.execute("PRAGMA table_info(hostel_alert_settings)")
        columns = {row[1] if not hasattr(row, "keys") else row["name"] for row in (c.fetchall() or [])}
        if "schedule_revision" not in columns:
            c.execute("""
                ALTER TABLE hostel_alert_settings
                ADD COLUMN schedule_revision INTEGER NOT NULL DEFAULT 1
            """)
    conn.commit()


def _row_dict(row, columns):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip(columns, row))


def _features(raw):
    try:
        value = json.loads(raw) if isinstance(raw, str) else (raw or [])
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def _parse_custom(raw):
    try:
        value = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _valid_phone(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return str(value).strip() if 7 <= len(digits) <= 15 else None


def _clock(value, default="19:00"):
    try:
        hour, minute = str(value or default).split(":", 1)
        parsed = time(int(hour), int(minute))
        return parsed
    except (TypeError, ValueError):
        raise ValueError("Cutoff time must use HH:MM format")


def _timezone(value):
    try:
        return ZoneInfo(str(value or "Asia/Kolkata"))
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Select a valid IANA timezone") from exc


def validate_settings(data):
    payload = dict(data or {})
    _clock(payload.get("cutoff_time", "19:00"))
    _timezone(payload.get("timezone", "Asia/Kolkata"))
    try:
        escalation = int(payload.get("escalation_minutes", 60))
    except (TypeError, ValueError) as exc:
        raise ValueError("Escalation period must be a whole number of minutes") from exc
    if escalation < 5 or escalation > 1440:
        raise ValueError("Escalation period must be between 5 and 1440 minutes")
    owner_phone = str(payload.get("owner_phone") or "").strip()
    if owner_phone and not _valid_phone(owner_phone):
        raise ValueError("Enter a valid hostel administrator WhatsApp number")
    return {
        "enabled": 1 if payload.get("enabled") else 0,
        "owner_phone": owner_phone or None,
        "cutoff_time": str(payload.get("cutoff_time") or "19:00")[:5],
        "escalation_minutes": escalation,
        "timezone": str(payload.get("timezone") or "Asia/Kolkata"),
        "student_template": str(payload.get("student_template") or "").strip() or None,
        "parent_template": str(payload.get("parent_template") or "").strip() or None,
        "owner_summary_enabled": 1 if payload.get("owner_summary_enabled", True) else 0,
    }


def get_settings(vendor_id, connection_factory=None):
    if connection_factory is None:
        from utils import get_db_connection
        connection_factory = get_db_connection
    conn = connection_factory()
    try:
        ensure_tables(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM hostel_alert_settings WHERE vendor_id = ?", (vendor_id,))
        row = c.fetchone()
        if not row:
            c.execute("INSERT INTO hostel_alert_settings (vendor_id) VALUES (?)", (vendor_id,))
            conn.commit()
            c.execute("SELECT * FROM hostel_alert_settings WHERE vendor_id = ?", (vendor_id,))
            row = c.fetchone()
        columns = [item[0] for item in c.description]
        return _row_dict(row, columns)
    finally:
        conn.close()


def save_settings(vendor_id, data, connection_factory=None):
    normalized = validate_settings(data)
    if connection_factory is None:
        from utils import get_db_connection
        connection_factory = get_db_connection
    conn = connection_factory()
    try:
        ensure_tables(conn)
        c = conn.cursor()
        c.execute("""
            INSERT INTO hostel_alert_settings
                (vendor_id, enabled, owner_phone, cutoff_time, escalation_minutes, timezone,
                 student_template, parent_template, owner_summary_enabled, schedule_revision, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT (vendor_id) DO UPDATE SET
                schedule_revision = CASE WHEN
                    hostel_alert_settings.enabled <> EXCLUDED.enabled OR
                    hostel_alert_settings.cutoff_time <> EXCLUDED.cutoff_time OR
                    hostel_alert_settings.escalation_minutes <> EXCLUDED.escalation_minutes OR
                    hostel_alert_settings.timezone <> EXCLUDED.timezone
                    THEN hostel_alert_settings.schedule_revision + 1
                    ELSE hostel_alert_settings.schedule_revision
                END,
                enabled = EXCLUDED.enabled,
                owner_phone = EXCLUDED.owner_phone,
                cutoff_time = EXCLUDED.cutoff_time,
                escalation_minutes = EXCLUDED.escalation_minutes,
                timezone = EXCLUDED.timezone,
                student_template = EXCLUDED.student_template,
                parent_template = EXCLUDED.parent_template,
                owner_summary_enabled = EXCLUDED.owner_summary_enabled,
                updated_at = CURRENT_TIMESTAMP
        """, (
            vendor_id, normalized["enabled"], normalized["owner_phone"],
            normalized["cutoff_time"], normalized["escalation_minutes"], normalized["timezone"],
            normalized["student_template"], normalized["parent_template"],
            normalized["owner_summary_enabled"],
        ))
        conn.commit()
        return get_settings(vendor_id, connection_factory=connection_factory)
    finally:
        conn.close()


class _SafeValues(defaultdict):
    def __missing__(self, key):
        return ""


def _render(template, values):
    try:
        return str(template).format_map(_SafeValues(str, values))
    except (ValueError, KeyError):
        return str(template)


def _claim_delivery(c, vendor_id, person_id, alert_date, alert_type, phone):
    c.execute("""
        INSERT INTO hostel_alert_deliveries
            (vendor_id, person_id, alert_date, alert_type, recipient_phone, status, attempts)
        VALUES (?, ?, ?, ?, ?, 'processing', 1)
        ON CONFLICT (vendor_id, person_id, alert_date, alert_type) DO NOTHING
    """, (vendor_id, person_id, alert_date, alert_type, phone))
    return int(c.rowcount or 0) > 0


def _revisioned_alert_type(alert_type, revision):
    """Keep legacy first-cycle claims while allowing a newly saved schedule cycle."""
    revision = max(1, int(revision or 1))
    return alert_type if revision == 1 else f"{alert_type}:r{revision}"


def _finish_delivery(c, vendor_id, person_id, alert_date, alert_type, result):
    success = bool(result) and not result.get("error") and result.get("success", True) is not False
    c.execute("""
        UPDATE hostel_alert_deliveries
        SET status = ?, error = ?, attempted_at = CURRENT_TIMESTAMP,
            sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END
        WHERE vendor_id = ? AND person_id = ? AND alert_date = ? AND alert_type = ?
    """, (
        "sent" if success else "failed",
        None if success else str((result or {}).get("error") or "WhatsApp delivery failed")[:500],
        "sent" if success else "failed",
        vendor_id, person_id, alert_date, alert_type,
    ))
    return success


def _latest_status_by_person(c, vendor_id, alert_date):
    c.execute("""
        SELECT person_id, status, timestamp
        FROM attendance
        WHERE vendor_id = ? AND (attendance_date = ? OR DATE(timestamp) = ?)
        ORDER BY timestamp ASC, id ASC
    """, (vendor_id, alert_date, alert_date))
    latest = {}
    for row in c.fetchall() or []:
        person_id = row[0] if not hasattr(row, "keys") else row["person_id"]
        status = row[1] if not hasattr(row, "keys") else row["status"]
        latest[person_id] = str(status or "").upper()
    return latest


def _approved_leave_people(c, vendor_id, alert_date):
    try:
        c.execute("""
            SELECT student_id FROM leave_requests
            WHERE vendor_id = ? AND final_status = 'approved'
              AND start_date <= ? AND end_date >= ?
        """, (vendor_id, alert_date, alert_date))
        return {row[0] if not hasattr(row, "keys") else row["student_id"] for row in (c.fetchall() or [])}
    except Exception:
        return set()


def _parent_phone(c, vendor_id, person_id, custom):
    direct = next((custom.get(key) for key in (
        "parent_phone", "guardian_phone", "parent_mobile", "guardian_mobile", "parent_whatsapp"
    ) if custom.get(key)), None)
    if _valid_phone(direct):
        return direct
    try:
        c.execute("""
            SELECT pu.contact_phone
            FROM student_parents sp
            JOIN parent_users pu ON pu.id = sp.parent_id
            WHERE sp.vendor_id = ? AND sp.person_id = ?
            ORDER BY sp.id ASC LIMIT 1
        """, (vendor_id, person_id))
        row = c.fetchone()
        return (row[0] if row and not hasattr(row, "keys") else (row["contact_phone"] if row else None))
    except Exception:
        return None


def process_due_alerts(now_utc=None, connection_factory=None, sender=None):
    """Process all currently due alert stages and return operational counters."""
    if connection_factory is None:
        from utils import get_db_connection
        connection_factory = get_db_connection
    if sender is None:
        from services.evolution_whatsapp_service import send_whatsapp_text
        sender = send_whatsapp_text

    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    stats = {"vendors": 0, "sent": 0, "failed": 0, "skipped": 0}
    conn = connection_factory()
    try:
        ensure_tables(conn)
        c = conn.cursor()
        c.execute("""
            SELECT h.vendor_id, h.enabled, h.owner_phone, h.cutoff_time,
                   h.escalation_minutes, h.timezone, h.student_template,
                   h.parent_template, h.owner_summary_enabled, h.schedule_revision,
                   v.status AS vendor_status, s.features,
                   w.status AS whatsapp_status
            FROM hostel_alert_settings h
            JOIN vendors v ON v.id = h.vendor_id
            JOIN subscriptions s ON s.vendor_id = h.vendor_id
            LEFT JOIN vendor_whatsapp_settings w ON w.vendor_id = h.vendor_id
        """)
        setting_columns = [item[0] for item in c.description]
        settings = [_row_dict(row, setting_columns) for row in (c.fetchall() or [])]

        for setting in settings:
            vendor_id = setting["vendor_id"]
            if not setting.get("enabled"):
                continue
            if str(setting.get("vendor_status") or "").lower() != "active":
                continue
            if FEATURE_NAME not in _features(setting.get("features")):
                continue
            if str(setting.get("whatsapp_status") or "").lower() != "connected":
                logger.warning("Hostel alerts skipped for vendor %s: WhatsApp is disconnected", vendor_id)
                stats["skipped"] += 1
                continue

            try:
                vendor_tz = _timezone(setting.get("timezone"))
                cutoff_clock = _clock(setting.get("cutoff_time"))
            except ValueError as exc:
                logger.error("Hostel alert configuration invalid for vendor %s: %s", vendor_id, exc)
                stats["failed"] += 1
                continue
            local_now = now_utc.astimezone(vendor_tz)
            alert_date = local_now.date().isoformat()
            cutoff = datetime.combine(local_now.date(), cutoff_clock, tzinfo=vendor_tz)
            if local_now < cutoff:
                continue
            parent_due = (local_now - cutoff).total_seconds() >= int(setting.get("escalation_minutes") or 60) * 60
            schedule_revision = int(setting.get("schedule_revision") or 1)
            student_alert_type = _revisioned_alert_type("student", schedule_revision)
            parent_alert_type = _revisioned_alert_type("parent", schedule_revision)
            summary_alert_type = _revisioned_alert_type("owner_summary", schedule_revision)
            stats["vendors"] += 1

            c.execute("SELECT id, name, phone, custom_data FROM faces WHERE vendor_id = ? ORDER BY id", (vendor_id,))
            people = []
            for row in c.fetchall() or []:
                person = _row_dict(row, ("id", "name", "phone", "custom_data"))
                custom = _parse_custom(person.get("custom_data"))
                person_type = str(custom.get("person_type") or "student").lower()
                if person_type not in {"student", "resident"}:
                    continue
                person["custom"] = custom
                people.append(person)

            latest = _latest_status_by_person(c, vendor_id, alert_date)
            approved_leave = _approved_leave_people(c, vendor_id, alert_date)
            absent = [
                person for person in people
                if person["id"] not in approved_leave
                and latest.get(person["id"], "") not in {"CHECK_IN", "IN", "PRESENT"}
            ]
            owner_summary_names = []
            for person in absent:
                values = {
                    "student_name": person.get("name") or "Resident",
                    "date": local_now.strftime("%d-%b-%Y"),
                    "cutoff_time": cutoff.strftime("%I:%M %p"),
                    "current_time": local_now.strftime("%I:%M %p"),
                    "hostel_name": "Hostel",
                }
                student_phone = _valid_phone(person.get("phone") or person["custom"].get("student_phone"))
                if _claim_delivery(c, vendor_id, person["id"], alert_date, student_alert_type, student_phone):
                    if student_phone:
                        result = sender(
                            vendor_id, student_phone,
                            _render(setting.get("student_template") or DEFAULT_STUDENT_TEMPLATE, values),
                        )
                    else:
                        result = {"success": False, "error": "Student mobile/WhatsApp number is missing or invalid"}
                    if _finish_delivery(c, vendor_id, person["id"], alert_date, student_alert_type, result):
                        stats["sent"] += 1
                    else:
                        stats["failed"] += 1
                    conn.commit()

                if parent_due:
                    parent_phone = _valid_phone(_parent_phone(c, vendor_id, person["id"], person["custom"]))
                    if _claim_delivery(c, vendor_id, person["id"], alert_date, parent_alert_type, parent_phone):
                        if parent_phone:
                            result = sender(
                                vendor_id, parent_phone,
                                _render(setting.get("parent_template") or DEFAULT_PARENT_TEMPLATE, values),
                            )
                        else:
                            result = {"success": False, "error": "Parent/guardian mobile number is missing or invalid"}
                        if _finish_delivery(c, vendor_id, person["id"], alert_date, parent_alert_type, result):
                            stats["sent"] += 1
                        else:
                            stats["failed"] += 1
                        conn.commit()
                    owner_summary_names.append(person.get("name") or f"Resident {person['id']}")

            owner_phone = _valid_phone(setting.get("owner_phone"))
            if parent_due and setting.get("owner_summary_enabled") and owner_summary_names:
                if _claim_delivery(c, vendor_id, 0, alert_date, summary_alert_type, owner_phone):
                    if owner_phone:
                        names = ", ".join(owner_summary_names[:30])
                        suffix = f" and {len(owner_summary_names) - 30} more" if len(owner_summary_names) > 30 else ""
                        result = sender(
                            vendor_id,
                            owner_phone,
                            f"🏫 *Hostel Attendance Summary*\n\n{len(owner_summary_names)} resident(s) have not recorded entry: {names}{suffix}.",
                        )
                    else:
                        result = {"success": False, "error": "Hostel administrator WhatsApp number is missing or invalid"}
                    if _finish_delivery(c, vendor_id, 0, alert_date, summary_alert_type, result):
                        stats["sent"] += 1
                    else:
                        stats["failed"] += 1
                    conn.commit()
        return stats
    except Exception:
        conn.rollback()
        logger.exception("Hostel attendance alert processing failed")
        raise
    finally:
        conn.close()


def recent_deliveries(vendor_id, limit=100, connection_factory=None):
    if connection_factory is None:
        from utils import get_db_connection
        connection_factory = get_db_connection
    conn = connection_factory()
    try:
        ensure_tables(conn)
        c = conn.cursor()
        c.execute("""
            SELECT d.id, d.person_id, f.name, d.alert_date, d.alert_type,
                   d.recipient_phone, d.status, d.error, d.created_at, d.sent_at
            FROM hostel_alert_deliveries d
            LEFT JOIN faces f ON f.id = d.person_id AND f.vendor_id = d.vendor_id
            WHERE d.vendor_id = ?
            ORDER BY d.id DESC LIMIT ?
        """, (vendor_id, max(1, min(int(limit), 500))))
        columns = [item[0] for item in c.description]
        deliveries = [_row_dict(row, columns) for row in (c.fetchall() or [])]
        for delivery in deliveries:
            stored_type = str(delivery.get("alert_type") or "")
            base_type, separator, revision = stored_type.rpartition(":r")
            if separator and revision.isdigit():
                delivery["alert_type"] = base_type
                delivery["schedule_revision"] = int(revision)
        return deliveries
    finally:
        conn.close()
