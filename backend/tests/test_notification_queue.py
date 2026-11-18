import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_parent_notification_is_dispatched_to_notification_queue(monkeypatch):
    calls = []
    dispatched = threading.Event()

    class FakeTask:
        @staticmethod
        def apply_async(*, args, queue, ignore_result, retry):
            calls.append((args, queue, ignore_result, retry))
            dispatched.set()
            return SimpleNamespace(id="notification-task-1")

    monkeypatch.setitem(
        sys.modules,
        "tasks",
        SimpleNamespace(deliver_parent_notification_task=FakeTask()),
    )
    from notifications import notify_parent_async
    result = notify_parent_async(10, 20, "Checked In", "At 09:00", {"status": "CHECK_IN"})

    assert result == {"queued": True}
    assert dispatched.wait(1)
    assert calls == [([10, 20, "Checked In", "At 09:00", {"status": "CHECK_IN"}], "notifications", True, False)]


def test_fcm_v1_preserves_leave_notification_type(monkeypatch):
    sent_messages = []

    class FakeMessaging:
        @staticmethod
        def AndroidNotification(**kwargs):
            return SimpleNamespace(**kwargs)

        @staticmethod
        def AndroidConfig(**kwargs):
            return SimpleNamespace(**kwargs)

        @staticmethod
        def Notification(**kwargs):
            return SimpleNamespace(**kwargs)

        @staticmethod
        def Message(**kwargs):
            return SimpleNamespace(**kwargs)

        @staticmethod
        def send(message):
            sent_messages.append(message)
            return "fcm-message-1"

    firebase_module = ModuleType("firebase_admin")
    firebase_module.messaging = FakeMessaging
    monkeypatch.setitem(sys.modules, "firebase_admin", firebase_module)

    import notifications
    monkeypatch.setattr(notifications, "_try_init_firebase", lambda: object())

    assert notifications._send_fcm_v1(
        "parent-fcm-token",
        "Leave request",
        "Student leave from 09:15 to 18:45",
        {"type": "leave_approval", "start_time": "09:15", "end_time": "18:45"},
    )
    assert sent_messages[0].data["type"] == "leave_approval"
    assert sent_messages[0].data["start_time"] == "09:15"
    assert sent_messages[0].data["end_time"] == "18:45"
    assert sent_messages[0].data["channel_id"] == "parent_attendance_alert"
