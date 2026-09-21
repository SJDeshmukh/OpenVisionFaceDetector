import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.attendance_state_service import next_attendance_status


def test_first_hostel_scan_is_checkout():
    assert next_attendance_status(hostel_mode=True) == "CHECK_OUT"


def test_hostel_return_after_checkout_is_checkin():
    assert next_attendance_status("CHECK_OUT", hours_since_last=2, hostel_mode=True) == "CHECK_IN"


def test_hostel_exit_ignores_sixteen_hour_work_reset():
    assert next_attendance_status("CHECK_IN", hours_since_last=48, hostel_mode=True) == "CHECK_OUT"


def test_normal_attendance_behavior_is_unchanged():
    assert next_attendance_status() == "CHECK_IN"
    assert next_attendance_status("CHECK_IN", hours_since_last=2) == "CHECK_OUT"
    assert next_attendance_status("CHECK_IN", hours_since_last=17) == "CHECK_IN"
