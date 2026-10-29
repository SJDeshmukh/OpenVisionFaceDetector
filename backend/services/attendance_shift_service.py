"""Shift-aware attendance-day and payroll helpers.

The legacy TapInX UI stores shifts in ``companies.shifts`` and the employee's
assignment in ``faces.shift``.  Normalized v2 shift tables coexist with that
contract.  This module gives every attendance path one interpretation of a
shift day so live punches, offline replay, reports, and payroll cannot disagree.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
from typing import Any, Iterable, Optional


DEFAULT_SHIFT_START = "06:00"
DEFAULT_SHIFT_END = "05:59"


def _time_minutes(value: Any, fallback: str) -> int:
    raw = str(value or fallback).strip()[:5]
    try:
        hours, minutes = (int(part) for part in raw.split(":", 1))
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return hours * 60 + minutes
    except (TypeError, ValueError):
        pass
    hours, minutes = (int(part) for part in fallback.split(":", 1))
    return hours * 60 + minutes


def _render_minutes(value: int) -> str:
    normalized = int(value) % (24 * 60)
    return f"{normalized // 60:02d}:{normalized % 60:02d}"


def parse_shift_list(value: Any) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def first_active_shift_name(value: Any) -> Optional[str]:
    """Return the first active timetable shift name in configured order."""
    for item in parse_shift_list(value):
        if item.get("active", item.get("is_active", True)) is False:
            continue
        name = str(item.get("name") or "").strip()
        if name:
            return name
    return None


def assign_default_shift_to_unassigned(cursor, vendor_id: int, shifts: Any) -> list[int]:
    """Assign the first active shift without overwriting manual assignments.

    Returning the affected person IDs lets callers notify connected clients
    after their transaction commits. Database face-change triggers publish the
    same updates through the mobile delta-sync ledger.
    """
    default_name = first_active_shift_name(shifts)
    if not default_name or not vendor_id:
        return []
    cursor.execute(
        """SELECT id FROM faces
           WHERE vendor_id = ? AND COALESCE(TRIM(shift), '') = ''
           ORDER BY id""",
        (vendor_id,),
    )
    person_ids = [int(row[0]) for row in (cursor.fetchall() or [])]
    if person_ids:
        cursor.execute(
            """UPDATE faces SET shift = ?
               WHERE vendor_id = ? AND COALESCE(TRIM(shift), '') = ''""",
            (default_name, vendor_id),
        )
    return person_ids


def synchronize_shift_assignments(
    cursor,
    vendor_id: int,
    shifts: Any,
    *,
    previous_shifts: Any = None,
) -> list[int]:
    """Keep renamed shifts valid, then fill only currently blank assignments."""
    changed_ids: set[int] = set()
    previous_by_id = {
        str(item.get("id")): str(item.get("name") or "").strip()
        for item in parse_shift_list(previous_shifts)
        if item.get("id") not in (None, "") and str(item.get("name") or "").strip()
    }
    current_by_id = {
        str(item.get("id")): str(item.get("name") or "").strip()
        for item in parse_shift_list(shifts)
        if item.get("id") not in (None, "") and str(item.get("name") or "").strip()
    }
    for shift_id, old_name in previous_by_id.items():
        new_name = current_by_id.get(shift_id)
        if not new_name or new_name.casefold() == old_name.casefold():
            continue
        cursor.execute(
            "SELECT id FROM faces WHERE vendor_id = ? AND LOWER(TRIM(shift)) = LOWER(?)",
            (vendor_id, old_name),
        )
        renamed_ids = [int(row[0]) for row in (cursor.fetchall() or [])]
        if renamed_ids:
            cursor.execute(
                "UPDATE faces SET shift = ? WHERE vendor_id = ? AND LOWER(TRIM(shift)) = LOWER(?)",
                (new_name, vendor_id, old_name),
            )
            changed_ids.update(renamed_ids)
    changed_ids.update(assign_default_shift_to_unassigned(cursor, vendor_id, shifts))
    return sorted(changed_ids)


@dataclass(frozen=True)
class ShiftPolicy:
    shift_id: Optional[str]
    name: str
    start_time: str
    end_time: str
    grace_minutes: int = 0
    timezone: str = "Asia/Kolkata"
    unpaid_break_minutes: int = 0
    assigned: bool = False

    @property
    def start_minutes(self) -> int:
        return _time_minutes(self.start_time, DEFAULT_SHIFT_START)

    @property
    def end_minutes(self) -> int:
        return _time_minutes(self.end_time, DEFAULT_SHIFT_END)

    @property
    def is_cross_midnight(self) -> bool:
        return self.end_minutes <= self.start_minutes

    @property
    def scheduled_minutes(self) -> int:
        duration = self.end_minutes - self.start_minutes
        if duration <= 0:
            duration += 24 * 60
        return max(1, duration - max(0, int(self.unpaid_break_minutes or 0)))

    @property
    def scheduled_hours(self) -> float:
        return self.scheduled_minutes / 60.0

    def attendance_date(self, value: datetime | date) -> date:
        """Return the shift day on which ``value`` belongs.

        For a cross-midnight shift, the shift start is the day boundary.  Thus
        2026-10-29 05:59 belongs to the shift that started on 2026-10-28 when
        the configured start is 06:00.
        """
        if isinstance(value, datetime):
            if self.is_cross_midnight:
                minute = value.hour * 60 + value.minute
                if minute < self.start_minutes:
                    return (value - timedelta(days=1)).date()
            return value.date()
        return value

    def bounds(self, attendance_day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(
            attendance_day,
            time(self.start_minutes // 60, self.start_minutes % 60),
        )
        end_day = attendance_day + timedelta(days=1 if self.is_cross_midnight else 0)
        end = datetime.combine(
            end_day,
            time(self.end_minutes // 60, self.end_minutes % 60),
        )
        return start, end


def default_shift_policy() -> ShiftPolicy:
    return ShiftPolicy(
        shift_id=None,
        name="Work",
        start_time=DEFAULT_SHIFT_START,
        end_time=DEFAULT_SHIFT_END,
        assigned=False,
    )


def shift_policy_from_dict(item: dict, *, assigned: bool = False) -> ShiftPolicy:
    start_minutes = _time_minutes(item.get("start_time"), DEFAULT_SHIFT_START)
    end_minutes = _time_minutes(item.get("end_time"), DEFAULT_SHIFT_END)
    unpaid_break = item.get("unpaid_break_minutes", item.get("break_minutes", 0))
    try:
        unpaid_break = max(0, int(unpaid_break or 0))
    except (TypeError, ValueError):
        unpaid_break = 0
    try:
        grace = max(0, int(item.get("grace_period_mins", item.get("grace_minutes", 0)) or 0))
    except (TypeError, ValueError):
        grace = 0
    raw_id = item.get("id", item.get("shift_id"))
    return ShiftPolicy(
        shift_id=str(raw_id) if raw_id not in (None, "") else None,
        name=str(item.get("name") or "Work").strip() or "Work",
        start_time=_render_minutes(start_minutes),
        end_time=_render_minutes(end_minutes),
        grace_minutes=grace,
        timezone=str(item.get("timezone") or "Asia/Kolkata"),
        unpaid_break_minutes=unpaid_break,
        assigned=assigned,
    )


def choose_shift_policy(shifts: Iterable[dict], assigned_shift: Any = None) -> ShiftPolicy:
    active = [item for item in shifts if item.get("active", item.get("is_active", True)) is not False]
    assigned_text = str(assigned_shift or "").strip()
    if assigned_text:
        for item in active:
            if (
                str(item.get("id", item.get("shift_id", ""))).strip() == assigned_text
                or str(item.get("name") or "").strip().casefold() == assigned_text.casefold()
                or str(item.get("code") or "").strip().casefold() == assigned_text.casefold()
            ):
                return shift_policy_from_dict(item, assigned=True)
    if len(active) == 1:
        return shift_policy_from_dict(active[0], assigned=bool(assigned_text))
    return default_shift_policy()


def load_person_shift_policy(cursor, vendor_id: int, person_id: int | None) -> ShiftPolicy:
    assigned_shift = None
    if person_id is not None:
        cursor.execute(
            "SELECT shift FROM faces WHERE id = ? AND vendor_id = ? LIMIT 1",
            (person_id, vendor_id),
        )
        row = cursor.fetchone()
        assigned_shift = row[0] if row else None

    cursor.execute("SELECT shifts FROM companies WHERE vendor_id = ? LIMIT 1", (vendor_id,))
    company = cursor.fetchone()
    shifts = parse_shift_list(company[0] if company else None)
    policy = choose_shift_policy(shifts, assigned_shift)
    if policy.assigned or shifts:
        return policy

    # Normalized v2 fallback. Employee assignments win over vendor defaults.
    try:
        cursor.execute(
            """SELECT s.id, s.code, s.name, s.is_active, sv.start_time,
                      sv.end_time, sv.timezone, sv.grace_minutes
                 FROM shift_assignments sa
                 JOIN shifts s ON s.id = sa.shift_id AND s.vendor_id = sa.vendor_id
                 JOIN shift_versions sv ON sv.id = (
                     SELECT sv2.id FROM shift_versions sv2
                      WHERE sv2.shift_id = s.id AND sv2.vendor_id = s.vendor_id
                      ORDER BY sv2.version_number DESC LIMIT 1
                 )
                WHERE sa.vendor_id = ?
                  AND ((sa.scope_type = 'EMPLOYEE' AND sa.person_id = ?)
                       OR sa.scope_type = 'VENDOR')
                  AND sa.effective_from <= ?
                  AND (sa.effective_to IS NULL OR sa.effective_to >= ?)
                ORDER BY CASE WHEN sa.scope_type = 'EMPLOYEE' THEN 0 ELSE 1 END,
                         sa.priority DESC, sa.effective_from DESC, sa.id ASC
                LIMIT 1""",
            (vendor_id, person_id, date.today().isoformat(), date.today().isoformat()),
        )
        row = cursor.fetchone()
        if row:
            return shift_policy_from_dict(
                {
                    "id": row[0], "code": row[1], "name": row[2],
                    "is_active": bool(row[3]), "start_time": row[4],
                    "end_time": row[5], "timezone": row[6],
                    "grace_minutes": row[7],
                },
                assigned=True,
            )
    except Exception:
        # Legacy databases may not have normalized shift tables yet.
        pass
    return policy


def attendance_date_for(value: datetime | date, shift_policy: ShiftPolicy | None = None) -> date:
    return (shift_policy or default_shift_policy()).attendance_date(value)


def scheduled_payable_hours(shift_policy: ShiftPolicy, company_working_hours: float = 8.0) -> float:
    """Return payable scheduled hours without treating a day window as 24 paid hours.

    Some TapInX businesses configure 06:00–05:59 as the attendance-day window
    while retaining an eight-hour payable day. Shorter assigned shifts still
    use their actual duration.
    """
    try:
        fallback = max(0.25, float(company_working_hours or 8.0))
    except (TypeError, ValueError):
        fallback = 8.0
    return max(0.25, min(shift_policy.scheduled_hours, fallback))


def group_records_by_attendance_date(records: Iterable[dict], shift_policy: ShiftPolicy | None = None):
    from utils import parse_db_datetime

    grouped: dict[date, list[dict]] = {}
    policy = shift_policy or default_shift_policy()
    for record in records:
        timestamp = parse_db_datetime(record.get("timestamp"))
        if timestamp is None:
            continue
        grouped.setdefault(policy.attendance_date(timestamp), []).append(record)
    return grouped


def calculate_shift_wage(
    daily_wage: float,
    worked_seconds_by_day: dict[date, float],
    scheduled_hours: float,
    *,
    overtime_multiplier: float = 1.0,
) -> dict:
    """Prorate wages by scheduled shift hours and isolate overtime."""
    scheduled_hours = max(0.25, float(scheduled_hours or 0))
    scheduled_seconds = scheduled_hours * 3600.0
    regular_seconds = sum(
        min(max(0.0, float(seconds or 0)), scheduled_seconds)
        for seconds in worked_seconds_by_day.values()
    )
    overtime_seconds = sum(
        max(0.0, float(seconds or 0) - scheduled_seconds)
        for seconds in worked_seconds_by_day.values()
    )
    hourly_rate = max(0.0, float(daily_wage or 0)) / scheduled_hours
    overtime_multiplier = max(0.0, float(overtime_multiplier or 0))
    regular_wage = (regular_seconds / 3600.0) * hourly_rate
    overtime_wage = (overtime_seconds / 3600.0) * hourly_rate * overtime_multiplier
    return {
        "regular_hours": round(regular_seconds / 3600.0, 2),
        "overtime_hours": round(overtime_seconds / 3600.0, 2),
        "hourly_rate": round(hourly_rate, 4),
        "regular_wage": round(regular_wage, 2),
        "overtime_wage": round(overtime_wage, 2),
        "gross_wage": round(regular_wage + overtime_wage, 2),
    }
