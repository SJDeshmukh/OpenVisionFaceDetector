import sys
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.stt_service import (
    InvalidAudioError,
    LocalWhisperService,
    NoSpeechDetectedError,
    SpeechToTextBusyError,
    SpeechToTextDisabledError,
)


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeInfo:
    language = "en"


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return [FakeSegment(" name the present employees ")], FakeInfo()


def test_disabled_switch_does_not_load_model():
    called = []
    service = LocalWhisperService(
        environ={"STT_ENABLED": "false", "STT_MODEL": "base"},
        model_factory=lambda *args, **kwargs: called.append((args, kwargs)),
        audio_decoder=lambda *_args, **_kwargs: [0] * 16000,
    )

    assert service.status()["state"] == "disabled"
    assert called == []
    with pytest.raises(SpeechToTextDisabledError):
        service.transcribe(b"audio", "audio/webm")


def test_enabled_switch_loads_base_cpu_int8_once_and_transcribes():
    created = []
    model = FakeModel()

    def factory(name, **kwargs):
        created.append((name, kwargs))
        return model

    service = LocalWhisperService(
        environ={
            "STT_ENABLED": "true",
            "STT_MODEL": "base",
            "STT_CPU_THREADS": "1",
            "STT_MAX_AUDIO_SECONDS": "20",
            "STT_VAD_MIN_SILENCE_MS": "500",
        },
        model_factory=factory,
        audio_decoder=lambda *_args, **_kwargs: [0] * 32000,
    )
    result = service.transcribe(b"valid recording", "audio/webm;codecs=opus")

    assert created == [("base", {
        "device": "cpu", "compute_type": "int8", "cpu_threads": 1, "num_workers": 1,
    })]
    assert result == {"text": "name the present employees", "duration_seconds": 2.0, "language": "en"}
    assert model.calls[0][1]["beam_size"] == 1
    assert model.calls[0][1]["vad_filter"] is True
    assert model.calls[0][1]["vad_parameters"] == {"min_silence_duration_ms": 500}


def test_audio_format_size_duration_and_empty_transcript_are_bounded():
    model = FakeModel()
    service = LocalWhisperService(
        environ={
            "STT_ENABLED": "true",
            "STT_MAX_AUDIO_BYTES": "64000",
            "STT_MAX_AUDIO_SECONDS": "3",
        },
        model_factory=lambda *_args, **_kwargs: model,
        audio_decoder=lambda *_args, **_kwargs: [0] * 64000,
    )

    with pytest.raises(InvalidAudioError, match="Unsupported"):
        service.transcribe(b"audio", "text/plain")
    with pytest.raises(InvalidAudioError, match="too large"):
        service.transcribe(b"x" * 64001, "audio/webm")
    with pytest.raises(InvalidAudioError, match="cannot exceed"):
        service.transcribe(b"audio", "audio/webm")

    empty_model = FakeModel()
    empty_model.transcribe = lambda *_args, **_kwargs: ([], FakeInfo())
    empty_service = LocalWhisperService(
        environ={"STT_ENABLED": "true"},
        model_factory=lambda *_args, **_kwargs: empty_model,
        audio_decoder=lambda *_args, **_kwargs: [0] * 16000,
    )
    with pytest.raises(NoSpeechDetectedError):
        empty_service.transcribe(b"audio", "audio/webm")


def test_only_one_transcription_can_run_at_a_time():
    service = LocalWhisperService(
        environ={"STT_ENABLED": "true"},
        model_factory=lambda *_args, **_kwargs: FakeModel(),
        audio_decoder=lambda *_args, **_kwargs: [0] * 16000,
    )
    service._inference_lock.acquire()
    try:
        with pytest.raises(SpeechToTextBusyError):
            service.transcribe(b"audio", "audio/webm")
    finally:
        service._inference_lock.release()
