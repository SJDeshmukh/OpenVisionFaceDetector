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


def test_excel_route_downloads_authenticated_users_saved_table(monkeypatch):
    app = Flask(__name__)
    workbook = BytesIO(b"xlsx-data")
    received = {}

    def fake_export(conversation_id, message_id, table_id, vendor_id, username):
        received.update({
            "conversation_id": conversation_id, "message_id": message_id, "table_id": table_id,
            "vendor_id": vendor_id, "username": username,
        })
        return workbook, "attendance.xlsx"

    monkeypatch.setattr(xchat, "_feature_guard", lambda: None)
    monkeypatch.setattr(xchat, "export_table_excel", fake_export)

    with app.test_request_context("/api/xchat/conversations/chat-1/messages/12/tables/daily/excel"):
        flask.g.vendor_id = 7
        flask.g.username = "owner"
        response = _route_function(xchat.conversation_table_excel)("chat-1", 12, "daily")

    assert received == {
        "conversation_id": "chat-1", "message_id": 12, "table_id": "daily",
        "vendor_id": 7, "username": "owner",
    }
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attendance.xlsx" in response.headers["Content-Disposition"]
