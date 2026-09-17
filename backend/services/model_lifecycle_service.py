"""Feature-aware lifecycle controls for optional, memory-heavy AI models."""

import json
import logging
import sys


logger = logging.getLogger(__name__)


def _feature_list(raw):
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return []
    else:
        value = raw
    return value if isinstance(value, (list, tuple, set)) else []


def any_active_vendor_has_feature(feature_name, connection_factory=None):
    """Return whether an active vendor currently owns the supplied feature."""
    if connection_factory is None:
        from utils import get_db_connection
        factory = get_db_connection
    else:
        factory = connection_factory
    conn = factory()
    try:
        c = conn.cursor()
        try:
            c.execute("""
                SELECT s.features
                FROM subscriptions s
                JOIN vendors v ON v.id = s.vendor_id
                WHERE LOWER(COALESCE(v.status, 'active')) = 'active'
            """)
        except Exception:
            # Compatibility for small legacy/test schemas without vendor status.
            c.execute("SELECT features FROM subscriptions")
        for row in c.fetchall() or []:
            raw = row["features"] if hasattr(row, "keys") else row[0]
            if feature_name in _feature_list(raw):
                return True
        return False
    finally:
        conn.close()


def reconcile_loaded_models(connection_factory=None):
    """Unload already-imported models whose paid feature is no longer in use.

    This function deliberately consults ``sys.modules`` instead of importing the
    model packages: disabling a feature must never load the model just to unload it.
    """
    bulk_enabled = any_active_vendor_has_feature(
        "bulk_image_attendance", connection_factory=connection_factory
    )
    xchat_enabled = any_active_vendor_has_feature(
        "xchat_ai", connection_factory=connection_factory
    )
    result = {
        "bulk_image_attendance_enabled": bulk_enabled,
        "xchat_ai_enabled": xchat_enabled,
        "face_models_unloaded": False,
        "stt_model_unloaded": False,
    }

    mfd_module = sys.modules.get("multiple_face_detection.app")
    if mfd_module is not None:
        invalidate = getattr(mfd_module, "invalidate_bulk_feature_cache", None)
        if callable(invalidate):
            invalidate()
        if not bulk_enabled:
            unload = getattr(mfd_module, "unload_all_models", None)
            if callable(unload):
                result["face_models_unloaded"] = bool(unload(reason="bulk feature disabled"))

    stt_module = sys.modules.get("services.stt_service")
    if stt_module is not None and not xchat_enabled:
        service = getattr(stt_module, "speech_to_text", None)
        unload = getattr(service, "unload", None)
        if callable(unload):
            result["stt_model_unloaded"] = bool(unload(reason="xchat_ai disabled"))

    logger.info("Optional model lifecycle reconciled: %s", result)
    return result


def queue_worker_reconciliation():
    """Ask the Celery worker process to apply the same unload decision."""
    try:
        from tasks import reconcile_optional_models_task
        delay = getattr(reconcile_optional_models_task, "delay", None)
        if callable(delay):
            delay()
            return True
    except Exception:
        logger.debug("Unable to queue worker model reconciliation", exc_info=True)
    return False


def reconcile_after_feature_change():
    result = reconcile_loaded_models()
    result["worker_reconciliation_queued"] = queue_worker_reconciliation()
    return result
