from datetime import datetime

from services.attendance_shift_service import ShiftPolicy
from services.manual_attendance_action_service import (
    should_use_manual_kiosk_mode,
    validate_manual_action,
)


def test_explicit_action_rules_allow_one_ordered_pair_per_shift_day():
    now = datetime(2026, 11, 5, 10, 0)
    assert validate_manual_action("CHECK_IN", [], now, "Anant").accepted

    check_in = [("CHECK_IN", datetime(2026, 11, 5, 8, 0))]
    assert not validate_manual_action("CHECK_IN", check_in, now, "Anant").accepted
    assert validate_manual_action("CHECK_OUT", check_in, now, "Anant").accepted

    completed = check_in + [("CHECK_OUT", now)]
    decision = validate_manual_action("CHECK_OUT", completed, now, "Anant")
    assert not decision.accepted
    assert decision.reason == "already_checked_out"


def test_checkout_requires_an_earlier_checkin():
    now = datetime(2026, 11, 5, 8, 0)
    decision = validate_manual_action("CHECK_OUT", [], now, "Anant")
    assert not decision.accepted
    assert decision.reason == "not_checked_in"


def test_six_am_shift_groups_pre_six_am_checkout_with_previous_day():
    policy = ShiftPolicy(None, "Work", "06:00", "05:59")
    check_in_time = datetime(2026, 11, 4, 21, 0)
    checkout_time = datetime(2026, 11, 5, 5, 30)
    assert policy.attendance_date(check_in_time) == policy.attendance_date(checkout_time)

    events = [("CHECK_IN", check_in_time)]
    assert validate_manual_action("CHECK_OUT", events, checkout_time, "Anant").accepted


def test_live_kiosk_uses_current_tenant_mode_only():
    assert should_use_manual_kiosk_mode("KIOSK", "CHECK_IN", False, "manual")
    assert not should_use_manual_kiosk_mode("KIOSK", "CHECK_IN", False, "automatic")
    assert not should_use_manual_kiosk_mode("KIOSK_MANUAL", "CHECK_IN", False, "manual")


def test_offline_replay_preserves_capture_mode_across_configuration_changes():
    assert should_use_manual_kiosk_mode("KIOSK_MANUAL", "CHECK_OUT", True, "automatic")
    assert not should_use_manual_kiosk_mode("KIOSK", "CHECK_IN", True, "manual")
    assert not should_use_manual_kiosk_mode("KIOSK_MANUAL", "", True, "manual")
