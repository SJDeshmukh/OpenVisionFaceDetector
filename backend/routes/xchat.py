from flask import Blueprint, g, jsonify, request

from middleware.handlers import rate_limit
from services.auth_service import require_auth
from services import stt_service
from services.stt_service import SpeechToTextError
from services.xchat_service import (
    XChatError,
    create_conversation,
    delete_conversation,
    get_messages,
    list_conversations,
    process_message,
)
from utils import vendor_has_feature


xchat_bp = Blueprint("xchat", __name__)
XCHAT_ROLES = ("vendor_admin", "admin", "owner")


def _feature_guard():
    if not vendor_has_feature(g.vendor_id, "xchat_ai"):
        return jsonify({"error": "Feature 'xchat_ai' is not enabled", "code": "FEATURE_DISABLED"}), 403
    return None


def _error_response(exc):
    if isinstance(exc, SpeechToTextError):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status_code
    if isinstance(exc, XChatError):
        return jsonify({"error": str(exc), "code": type(exc).__name__.upper()}), exc.status_code
    if isinstance(exc, ValueError):
        return jsonify({"error": str(exc), "code": "VALIDATION_ERROR"}), 400
    return jsonify({"error": "Unable to process XChat request", "code": "INTERNAL_ERROR"}), 500


@xchat_bp.get("/xchat/conversations")
@require_auth(roles=XCHAT_ROLES)
def conversations_list():
    if error := _feature_guard():
        return error
    return jsonify({"status": "success", "conversations": list_conversations(g.vendor_id, g.username)})


@xchat_bp.post("/xchat/conversations")
@require_auth(roles=XCHAT_ROLES)
def conversations_create():
    if error := _feature_guard():
        return error
    data = request.get_json(silent=True) or {}
    conversation_id = create_conversation(g.vendor_id, g.username, data.get("title"))
    return jsonify({"status": "success", "conversation_id": conversation_id}), 201


@xchat_bp.get("/xchat/conversations/<conversation_id>/messages")
@require_auth(roles=XCHAT_ROLES)
def conversation_messages(conversation_id):
    if error := _feature_guard():
        return error
    try:
        return jsonify({"status": "success", "messages": get_messages(conversation_id, g.vendor_id, g.username)})
    except Exception as exc:
        return _error_response(exc)


@xchat_bp.delete("/xchat/conversations/<conversation_id>")
@require_auth(roles=XCHAT_ROLES)
def conversation_delete(conversation_id):
    if error := _feature_guard():
        return error
    try:
        delete_conversation(conversation_id, g.vendor_id, g.username)
        return jsonify({"status": "success"})
    except Exception as exc:
        return _error_response(exc)


@xchat_bp.get("/xchat/transcription/status")
@require_auth(roles=XCHAT_ROLES)
def transcription_status():
    if error := _feature_guard():
        return error
    return jsonify({"status": "success", **stt_service.speech_to_text.status()})


@xchat_bp.post("/xchat/transcribe")
@require_auth(roles=XCHAT_ROLES)
@rate_limit(key_func=lambda: f"xchat-stt:{g.vendor_id}:{g.username}", limit=6, window=60)
def transcription_create():
    if error := _feature_guard():
        return error
    service = stt_service.speech_to_text
    if request.content_length and request.content_length > service.max_audio_bytes + 262_144:
        return jsonify({"error": "The audio recording is too large", "code": "INVALID_AUDIO"}), 413
    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"error": "An audio recording is required", "code": "INVALID_AUDIO"}), 400
    try:
        audio_bytes = audio_file.stream.read(service.max_audio_bytes + 1)
        result = service.transcribe(audio_bytes, audio_file.mimetype)
        return jsonify({"status": "success", **result})
    except Exception as exc:
        return _error_response(exc)


@xchat_bp.post("/xchat/messages")
@require_auth(roles=XCHAT_ROLES)
@rate_limit(key_func=lambda: f"xchat:{g.vendor_id}:{g.username}", limit=20, window=60)
def messages_create():
    if error := _feature_guard():
        return error
    data = request.get_json(silent=True) or {}
    try:
        result = process_message(
            question=data.get("message"),
            conversation_id=data.get("conversation_id"),
            vendor_id=g.vendor_id,
            username=g.username,
            role=g.user_role,
            features=_vendor_features(g.vendor_id),
            page_context=data.get("page_context"),
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip(),
        )
        return jsonify({"status": "success", **result})
    except Exception as exc:
        return _error_response(exc)


def _vendor_features(vendor_id):
    from db_factory import get_db_connection
    import json

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT features FROM subscriptions WHERE vendor_id = ? LIMIT 1", (vendor_id,))
        row = cursor.fetchone()
        raw = (row["features"] if hasattr(row, "keys") else row[0]) if row else "[]"
        return json.loads(raw or "[]") if isinstance(raw, str) else list(raw or [])
    except (TypeError, ValueError):
        return []
    finally:
        conn.close()
