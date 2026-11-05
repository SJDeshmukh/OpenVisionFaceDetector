"""Timestamped tenant attendance-action mode history."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


VALID_ACTION_MODES = {"automatic", "manual"}
DEFAULT_TIMEZONE = "Asia/Kolkata"


def normalize_action_mode(value, default="automatic") -> str:
    mode = str(value or "").strip().lower()
    if mode in VALID_ACTION_MODES:
        return mode
    return default


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def event_time_to_utc_naive(value: datetime, timezone_name: Optional[str]) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Attendance event time must be a datetime")
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    zone_name = str(timezone_name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        source_zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown attendance event timezone: {zone_name}") from exc
    return value.replace(tzinfo=source_zone).astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class AttendanceActionModeResolution:
    mode: str
    effective_from_utc: Optional[datetime]


def record_action_mode_change(
    cursor,
    vendor_id: int,
    mode: str,
    changed_by: Optional[str],
    *,
    effective_from_utc: Optional[datetime] = None,
) -> bool:
    """Append a server-timestamped mode version only when the mode changed."""

    normalized = normalize_action_mode(mode, default="")
    if normalized not in VALID_ACTION_MODES:
        raise ValueError("Attendance action mode must be automatic or manual")
    cursor.execute(
        """SELECT mode FROM attendance_action_mode_history
           WHERE vendor_id = ?
           ORDER BY effective_from_utc DESC, id DESC LIMIT 1""",
        (vendor_id,),
    )
    latest = cursor.fetchone()
    if latest and normalize_action_mode(latest[0]) == normalized:
        return False
    effective = effective_from_utc or utc_now_naive()
    if effective.tzinfo is not None:
        effective = effective.astimezone(timezone.utc).replace(tzinfo=None)
    cursor.execute(
        """INSERT INTO attendance_action_mode_history
           (vendor_id, mode, effective_from_utc, changed_by, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            vendor_id,
            normalized,
            effective.isoformat(sep=" "),
            str(changed_by or "system"),
            utc_now_naive().isoformat(sep=" "),
        ),
    )
    return True


def resolve_action_mode_at(
    cursor,
    vendor_id: int,
    event_time: datetime,
    source_timezone: Optional[str],
    fallback_mode: str,
) -> AttendanceActionModeResolution:
    """Resolve the mode version in effect when a timestamped event occurred."""

    event_time_utc = event_time_to_utc_naive(event_time, source_timezone)
    cursor.execute(
        """SELECT mode, effective_from_utc
           FROM attendance_action_mode_history
           WHERE vendor_id = ? AND effective_from_utc <= ?
           ORDER BY effective_from_utc DESC, id DESC LIMIT 1""",
        (vendor_id, event_time_utc.isoformat(sep=" ")),
    )
    row = cursor.fetchone()
    if not row:
        # The first row is the migration/creation baseline. It also defines how
        # pre-baseline queued events are interpreted when older history is unknowable.
        cursor.execute(
            """SELECT mode, effective_from_utc
               FROM attendance_action_mode_history
               WHERE vendor_id = ?
               ORDER BY effective_from_utc ASC, id ASC LIMIT 1""",
            (vendor_id,),
        )
        row = cursor.fetchone()
    if not row:
        return AttendanceActionModeResolution(
            normalize_action_mode(fallback_mode), None
        )
    effective = row[1]
    if not isinstance(effective, datetime) and effective not in (None, ""):
        try:
            effective = datetime.fromisoformat(str(effective))
        except (TypeError, ValueError):
            effective = None
    return AttendanceActionModeResolution(
        normalize_action_mode(row[0]), effective
    )


def latest_action_mode_record(
    cursor, vendor_id: int, fallback_mode: str
) -> AttendanceActionModeResolution:
    cursor.execute(
        """SELECT mode, effective_from_utc
           FROM attendance_action_mode_history
           WHERE vendor_id = ?
           ORDER BY effective_from_utc DESC, id DESC LIMIT 1""",
        (vendor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return AttendanceActionModeResolution(
            normalize_action_mode(fallback_mode), None
        )
    effective = row[1]
    if not isinstance(effective, datetime) and effective not in (None, ""):
        try:
            effective = datetime.fromisoformat(str(effective))
        except (TypeError, ValueError):
            effective = None
    return AttendanceActionModeResolution(normalize_action_mode(row[0]), effective)
