"""Pure helpers for shift-aware attendance history queries."""

from datetime import date, datetime, timedelta
from typing import Any, Optional

from services.attendance_shift_service import ShiftPolicy


def build_operational_date_filter(
    start_date: Optional[str],
    end_date: Optional[str],
    *,
    placeholder: str = "?",
) -> tuple[str, list[str]]:
    """Build a safe filter for persisted and pre-migration attendance rows."""

    if not start_date and not end_date:
        return "", []

    stored_parts = []
    stored_params = []
    if start_date:
        stored_parts.append(f"a.attendance_date >= {placeholder}")
        stored_params.append(start_date)
    if end_date:
        stored_parts.append(f"a.attendance_date <= {placeholder}")
        stored_params.append(end_date)

    legacy_parts = ["a.attendance_date IS NULL"]
    legacy_params = []
    if start_date:
        legacy_parts.append(f"a.timestamp >= {placeholder}")
        legacy_params.append(f"{start_date} 00:00:00")
    if end_date:
        legacy_parts.append(f"a.timestamp < {placeholder}")
        legacy_params.append(
            (
                datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=2)
            ).strftime("%Y-%m-%d 00:00:00")
        )

    clause = (
        f" AND ((a.attendance_date IS NOT NULL AND {' AND '.join(stored_parts)})"
        f" OR ({' AND '.join(legacy_parts)}))"
    )
    return clause, stored_params + legacy_params


def resolve_operational_date(
    stored_attendance_date: Any,
    row_timestamp: Optional[datetime],
    shift_policy: ShiftPolicy,
) -> Optional[date]:
    """Prefer the immutable capture-day snapshot over today's shift settings."""

    if stored_attendance_date not in (None, ""):
        if isinstance(stored_attendance_date, datetime):
            return stored_attendance_date.date()
        if isinstance(stored_attendance_date, date):
            return stored_attendance_date
        try:
            return datetime.strptime(
                str(stored_attendance_date)[:10], "%Y-%m-%d"
            ).date()
        except (TypeError, ValueError):
            pass
    return shift_policy.attendance_date(row_timestamp) if row_timestamp else None
