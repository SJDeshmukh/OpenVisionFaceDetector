"""Startup-gated, local speech-to-text service for XChat."""

from io import BytesIO
import gc
import logging
import os
import threading
import time


logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SUPPORTED_AUDIO_TYPES = {
    "audio/flac",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-wav",
}


class SpeechToTextError(Exception):
    status_code = 500
    code = "STT_ERROR"


class SpeechToTextDisabledError(SpeechToTextError):
    status_code = 503
    code = "STT_DISABLED"


class SpeechToTextUnavailableError(SpeechToTextError):
    status_code = 503
    code = "STT_UNAVAILABLE"


class SpeechToTextBusyError(SpeechToTextError):
    status_code = 429
    code = "STT_BUSY"


class InvalidAudioError(SpeechToTextError):
    status_code = 400
    code = "INVALID_AUDIO"


class NoSpeechDetectedError(SpeechToTextError):
    status_code = 422
    code = "NO_SPEECH_DETECTED"


def _enabled(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(environ, name, default, minimum, maximum):
    try:
        value = int(environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


class LocalWhisperService:
    """Own one CPU model and serialize inference for small EC2 instances."""

    def __init__(self, environ=None, model_factory=None, audio_decoder=None):
        environ = os.environ if environ is None else environ
        self.enabled = _enabled(environ.get("STT_ENABLED", "false"))
        self.model_name = str(environ.get("STT_MODEL", "base") or "base").strip()
        self.compute_type = "int8"
        self.cpu_threads = _bounded_int(environ, "STT_CPU_THREADS", 1, 1, 4)
        self.max_audio_seconds = _bounded_int(environ, "STT_MAX_AUDIO_SECONDS", 20, 3, 60)
        self.max_audio_bytes = _bounded_int(environ, "STT_MAX_AUDIO_BYTES", 2_500_000, 64_000, 10_000_000)
        self.vad_min_silence_ms = _bounded_int(environ, "STT_VAD_MIN_SILENCE_MS", 500, 250, 3000)
        self.language = str(environ.get("STT_LANGUAGE", "") or "").strip() or None
        self._model_factory = model_factory
        self._audio_decoder = audio_decoder
        self._model = None
        self._load_error = None
        self._inference_lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._last_used = 0.0
        self._idle_ttl = _bounded_int(environ, "STT_MODEL_TTL_SECONDS", 300, 60, 86400)

        if self.enabled:
            logger.info("Local XChat speech-to-text is enabled; model will load on first voice request")
            self._start_idle_reaper()
        else:
            logger.info("Local XChat speech-to-text is disabled (STT_ENABLED=false)")

    def _load(self):
        with self._load_lock:
            if self._model is not None:
                return True
            try:
                if self._model_factory is None or self._audio_decoder is None:
                    from faster_whisper import WhisperModel
                    from faster_whisper.audio import decode_audio

                    self._model_factory = self._model_factory or WhisperModel
                    self._audio_decoder = self._audio_decoder or decode_audio
                logger.info(
                    "Loading local XChat speech-to-text model '%s' on first use (CPU/INT8)",
                    self.model_name,
                )
                self._model = self._model_factory(
                    self.model_name,
                    device="cpu",
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                    num_workers=1,
                )
                self._load_error = None
                self._last_used = time.monotonic()
                logger.info("Local XChat speech-to-text model is ready")
                return True
            except Exception as exc:
                self._load_error = type(exc).__name__
                self._model = None
                logger.exception("Unable to load the local XChat speech-to-text model")
                return False

    def unload(self, reason="disabled or idle"):
        """Release Whisper memory without disabling future lazy use."""
        with self._inference_lock:
            with self._load_lock:
                if self._model is None:
                    return False
                self._model = None
                self._last_used = 0.0
        gc.collect()
        logger.info("Unloaded local XChat speech-to-text model (%s)", reason)
        return True

    def _start_idle_reaper(self):
        def reap():
            while True:
                time.sleep(60)
                if self._model is None:
                    continue
                feature_enabled = True
                try:
                    from services.model_lifecycle_service import any_active_vendor_has_feature
                    feature_enabled = any_active_vendor_has_feature("xchat_ai")
                except Exception:
                    logger.debug("Unable to check XChat feature state", exc_info=True)
                idle_for = time.monotonic() - self._last_used if self._last_used else 0
                if not feature_enabled:
                    self.unload("xchat_ai disabled for all active vendors")
                elif idle_for >= self._idle_ttl:
                    self.unload(f"idle for {int(idle_for)} seconds")

        threading.Thread(target=reap, daemon=True, name="stt-model-reaper").start()

    @property
    def ready(self):
        # Ready means the service can accept a request. The heavy model may still
        # be unloaded and will be initialized lazily on the first transcription.
        return self.enabled and self._load_error is None

    def status(self):
        state = "loaded" if self._model is not None else ("ready" if self.ready else ("unavailable" if self.enabled else "disabled"))
        return {
            "enabled": self.enabled,
            "ready": self.ready,
            "loaded": self._model is not None,
            "state": state,
            "model": self.model_name if self.enabled else None,
            "device": "cpu" if self.enabled else None,
            "compute_type": self.compute_type if self.enabled else None,
            "max_audio_seconds": self.max_audio_seconds,
        }

    def transcribe(self, audio_bytes, content_type):
        if not self.enabled:
            raise SpeechToTextDisabledError("Voice input is disabled on this server")
        if not self.ready:
            raise SpeechToTextUnavailableError("Voice input is temporarily unavailable")
        if not isinstance(audio_bytes, (bytes, bytearray)) or not audio_bytes:
            raise InvalidAudioError("An audio recording is required")
        if len(audio_bytes) > self.max_audio_bytes:
            raise InvalidAudioError("The audio recording is too large")

        normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
        if normalized_type not in SUPPORTED_AUDIO_TYPES:
            raise InvalidAudioError("Unsupported audio format")

        if not self._load():
            raise SpeechToTextUnavailableError("Voice input is temporarily unavailable")

        try:
            audio = self._audio_decoder(BytesIO(audio_bytes), sampling_rate=SAMPLE_RATE)
        except Exception as exc:
            logger.info("Unable to decode XChat audio: %s", type(exc).__name__)
            raise InvalidAudioError("The audio recording could not be decoded") from exc

        sample_count = len(audio) if audio is not None else 0
        duration_seconds = sample_count / SAMPLE_RATE
        if duration_seconds < 0.15:
            raise NoSpeechDetectedError("No speech was detected")
        if duration_seconds > self.max_audio_seconds + 0.5:
            raise InvalidAudioError(f"Audio cannot exceed {self.max_audio_seconds} seconds")

        if not self._inference_lock.acquire(blocking=False):
            raise SpeechToTextBusyError("Voice transcription is busy; please try again")
        try:
            self._last_used = time.monotonic()
            segments, info = self._model.transcribe(
                audio,
                language=self.language,
                beam_size=1,
                best_of=1,
                temperature=0,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": self.vad_min_silence_ms},
                without_timestamps=True,
                condition_on_previous_text=False,
            )
            text = " ".join(
                str(getattr(segment, "text", "") or "").strip()
                for segment in segments
                if str(getattr(segment, "text", "") or "").strip()
            ).strip()
        except SpeechToTextError:
            raise
        except Exception as exc:
            logger.exception("Local XChat speech transcription failed")
            raise SpeechToTextUnavailableError("Voice transcription failed") from exc
        finally:
            self._last_used = time.monotonic()
            self._inference_lock.release()

        if not text:
            raise NoSpeechDetectedError("No speech was detected")
        return {
            "text": text[:1000],
            "duration_seconds": round(duration_seconds, 2),
            "language": getattr(info, "language", None),
        }


# Importing the XChat route only creates the lightweight service. The model is
# loaded by the first valid voice request and can be released again when idle.
speech_to_text = LocalWhisperService()
