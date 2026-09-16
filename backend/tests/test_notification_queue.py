import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_parent_notification_is_dispatched_to_notification_queue(monkeypatch):
    calls = []

    class FakeTask:
        @staticmethod
        def apply_async(*, args, queue):
            calls.append((args, queue))
            return SimpleNamespace(id="notification-task-1")

    monkeypatch.setitem(
        sys.modules,
        "tasks",
        SimpleNamespace(deliver_parent_notification_task=FakeTask()),
    )
    from notifications import notify_parent_async
    result = notify_parent_async(10, 20, "Checked In", "At 09:00", {"status": "CHECK_IN"})

    assert result == {"queued": True, "task_id": "notification-task-1"}
    assert calls == [([10, 20, "Checked In", "At 09:00", {"status": "CHECK_IN"}], "notifications")]
