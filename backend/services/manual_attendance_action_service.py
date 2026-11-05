"""Validation rules for operator-selected kiosk attendance actions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional


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
    """Allow at most one explicit IN and OUT, in order, per shift day."""

    normalized = str(action or "").strip().upper()
    safe_name = str(name or "Employee").strip() or "Employee"
    events = [
        (str(status or "").strip().upper(), timestamp)
        for status, timestamp in shift_day_events
        if isinstance(timestamp, datetime)
    ]

    if normalized not in {"CHECK_IN", "CHECK_OUT"}:
        return ManualActionDecision(
            False,
            "manual_action_required",
            "Select Check In or Check Out before scanning.",
        )
    if normalized == "CHECK_IN":
        if any(status == "CHECK_IN" for status, _timestamp in events):
            return ManualActionDecision(
                False,
                "already_checked_in",
                f"{safe_name}, check in is already marked for this shift.",
            )
        return ManualActionDecision(True)

    if any(status == "CHECK_OUT" for status, _timestamp in events):
        return ManualActionDecision(
            False,
            "already_checked_out",
            f"{safe_name}, check out is already marked for this shift.",
        )
    if not any(
        status == "CHECK_IN" and timestamp <= current_time
        for status, timestamp in events
    ):
        return ManualActionDecision(
            False,
            "not_checked_in",
            f"{safe_name}, check in must be marked first.",
        )
    return ManualActionDecision(True)
