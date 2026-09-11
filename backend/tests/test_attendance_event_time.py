from datetime import datetime, timedelta

from routes.attendance_core import _resolve_event_time


def test_live_event_uses_server_time():
    before = datetime.now()
    resolved = _resolve_event_time(None)
    after = datetime.now()
    assert before <= resolved <= after


def test_recent_offline_event_keeps_client_time():
    client_time = datetime.now() - timedelta(minutes=15)
    resolved = _resolve_event_time(client_time.strftime("%Y-%m-%dT%H:%M:%S.%f"))
    assert resolved == client_time


def test_bad_device_clock_falls_back_to_server_time():
    bad_clock = datetime.now() - timedelta(days=365 * 50)
    before = datetime.now()
    resolved = _resolve_event_time(bad_clock.strftime("%Y-%m-%dT%H:%M:%S.%f"))
    after = datetime.now()
    assert before <= resolved <= after
