import importlib
import sys
from pathlib import Path

BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_local_payload_round_trip_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_PAYLOAD_OFFLOAD", "true")
    monkeypatch.setenv("TASK_PAYLOAD_DIR", str(tmp_path))
    import services.task_payload_service as service
    service = importlib.reload(service)

    original = "data:image/jpeg;base64,aGVsbG8="
    reference = service.store_image_payload(original)
    assert reference["payload_ref"].startswith("local://")
    assert "aGVsbG8=" not in str(reference)

    restored, cleanup = service.resolve_image_payload(reference)
    assert restored == original
    assert len(list(tmp_path.glob("*.json"))) == 1
    cleanup()
    assert list(tmp_path.glob("*.json")) == []


def test_payload_offload_is_opt_in(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_PAYLOAD_OFFLOAD", "false")
    monkeypatch.setenv("TASK_PAYLOAD_DIR", str(tmp_path))
    import services.task_payload_service as service
    service = importlib.reload(service)
    value = "data:image/jpeg;base64,aGVsbG8="
    assert service.store_image_payload(value) == value
