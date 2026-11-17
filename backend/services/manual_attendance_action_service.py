"""Validation rules for operator-selected kiosk attendance actions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional


_ACTION_ALIASES = {
    "CHECK_IN": "CHECK_IN",
    "CHECKIN": "CHECK_IN",
    "CHECK IN": "CHECK_IN",
    "IN": "CHECK_IN",
    "CHECK_OUT": "CHECK_OUT",
    "CHECKOUT": "CHECK_OUT",
    "CHECK OUT": "CHECK_OUT",
    "OUT": "CHECK_OUT",
}


def normalize_manual_action(value: object) -> str:
    """Return the canonical status used by the attendance state machine.

    Historical rows and older integrations used labels such as Check In.
    Treating those rows as unknown makes a second check-in look valid, so the
    backend normalizes every stored and requested action before validation.
    """

    raw = str(value or "").strip().upper().replace("-", "_")
    return _ACTION_ALIASES.get(raw, raw)


@dataclass(frozen=True)
class ManualActionDecision:
    accepted: bool
    reason: Optional[str] = None
    text: Optional[str] = None


def should_use_manual_kiosk_mode(
    requested_event_source: str,
    provided_status: str,
    has_timestamp: bool,
    configured_mode: str,
) -> bool:
    """Identify live manual punches and explicit offline manual replays.

    Timestamped automatic events may contain a stale predicted status from an
    older client, so only the dedicated replay source makes that status
    authoritative. Live requests always follow the tenant's current setting.
    """

    source = str(requested_event_source or "KIOSK").strip().upper()
    mode = str(configured_mode or "automatic").strip().lower()
    if has_timestamp and source == "KIOSK_MANUAL":
        # A deliberate offline action remains manual even if the tenant mode
        # changed before synchronization. Missing/invalid actions are rejected
        # later by validate_manual_action instead of being auto-interpreted.
        return True
    if not has_timestamp and source == "KIOSK_MANUAL":
        source = "KIOSK"
    return source == "KIOSK" and mode == "manual"


def validate_manual_action(
    action: str,
    shift_day_events: Iterable[tuple[str, datetime]],
    current_time: datetime,
    name: str,
) -> ManualActionDecision:
    """Require explicit actions to alternate within the active shift day."""

    normalized = normalize_manual_action(action)
    safe_name = str(name or "Employee").strip() or "Employee"
    events = sorted(
        [
            (normalize_manual_action(status), timestamp)
            for status, timestamp in shift_day_events
            if (
                isinstance(timestamp, datetime)
                and normalize_manual_action(status) in {"CHECK_IN", "CHECK_OUT"}
                and timestamp <= current_time
            )
        ],
        key=lambda event: event[1],
    )
    last_status = events[-1][0] if events else None

    if normalized not in {"CHECK_IN", "CHECK_OUT"}:
        return ManualActionDecision(
            False,
            "manual_action_required",
            "Select Check In or Check Out before scanning.",
        )
    if normalized == "CHECK_IN":
        if last_status == "CHECK_IN":
            return ManualActionDecision(
                False,
                "already_checked_in",
                f"{safe_name}, check in is already active.",
            )
        return ManualActionDecision(True)

    if last_status == "CHECK_OUT":
        return ManualActionDecision(
            False,
            "already_checked_out",
            f"{safe_name}, check out is already marked.",
        )
    if last_status != "CHECK_IN":
        return ManualActionDecision(
            False,
            "not_checked_in",
            f"{safe_name}, check in must be marked first.",
        )
    return ManualActionDecision(True)
