from io import BytesIO
import sys
from pathlib import Path

import pytest


flask = pytest.importorskip("flask")
Flask = flask.Flask


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from routes import xchat


def _route_function(view):
    while hasattr(view, "__wrapped__"):
        view = view.__wrapped__
    return view


class FakeSpeechService:
    max_audio_bytes = 64_000

    def __init__(self):
        self.received = None

    def status(self):
        return {
            "enabled": True, "ready": True, "state": "ready", "model": "base",
            "device": "cpu", "compute_type": "int8", "max_audio_seconds": 20,
        }

    def transcribe(self, audio_bytes, content_type):
        self.received = (audio_bytes, content_type)
        return {"text": "Who is present today?", "duration_seconds": 1.5, "language": "en"}


def test_transcription_status_reports_startup_model_state(monkeypatch):
    app = Flask(__name__)
    service = FakeSpeechService()
    monkeypatch.setattr(xchat, "_feature_guard", lambda: None)
    monkeypatch.setattr(xchat.stt_service, "speech_to_text", service)

    with app.test_request_context("/api/xchat/transcription/status"):
        response = _route_function(xchat.transcription_status)()

    assert response.get_json()["state"] == "ready"
    assert response.get_json()["model"] == "base"


def test_transcription_route_reads_bounded_audio_and_returns_text(monkeypatch):
    app = Flask(__name__)
    service = FakeSpeechService()
    monkeypatch.setattr(xchat, "_feature_guard", lambda: None)
    monkeypatch.setattr(xchat.stt_service, "speech_to_text", service)

    with app.test_request_context(
        "/api/xchat/transcribe",
        method="POST",
        data={"audio": (BytesIO(b"voice bytes"), "voice.webm", "audio/webm")},
    ):
        response = _route_function(xchat.transcription_create)()

    assert response.get_json()["text"] == "Who is present today?"
    assert service.received == (b"voice bytes", "audio/webm")


def test_transcription_route_rejects_missing_audio(monkeypatch):
    app = Flask(__name__)
    monkeypatch.setattr(xchat, "_feature_guard", lambda: None)
    monkeypatch.setattr(xchat.stt_service, "speech_to_text", FakeSpeechService())

    with app.test_request_context("/api/xchat/transcribe", method="POST"):
        response, status = _route_function(xchat.transcription_create)()

    assert status == 400
    assert response.get_json()["code"] == "INVALID_AUDIO"
