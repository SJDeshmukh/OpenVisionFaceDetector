import sqlite3
import sys
import types
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.model_lifecycle_service import (
    any_active_vendor_has_feature,
    reconcile_loaded_models,
)


def lifecycle_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE subscriptions (vendor_id INTEGER, features TEXT);
        INSERT INTO vendors VALUES (1, 'active'), (2, 'suspended');
        INSERT INTO subscriptions VALUES
            (1, '["xchat_ai"]'),
            (2, '["bulk_image_attendance"]');
    """)
    return conn


def test_only_active_vendor_features_keep_models_eligible():
    conn = lifecycle_db()
    assert any_active_vendor_has_feature("xchat_ai", lambda: conn) is True

    conn = lifecycle_db()
    assert any_active_vendor_has_feature("bulk_image_attendance", lambda: conn) is False


def test_reconcile_unloads_only_models_without_an_active_feature(monkeypatch):
    face_calls = []
    stt_calls = []
    fake_face = types.SimpleNamespace(
        invalidate_bulk_feature_cache=lambda: face_calls.append("invalidate"),
        unload_all_models=lambda reason: face_calls.append(reason) or True,
    )
    fake_stt_service = types.SimpleNamespace(
        unload=lambda reason: stt_calls.append(reason) or True,
    )
    fake_stt = types.SimpleNamespace(speech_to_text=fake_stt_service)
    monkeypatch.setitem(sys.modules, "multiple_face_detection.app", fake_face)
    monkeypatch.setitem(sys.modules, "services.stt_service", fake_stt)

    result = reconcile_loaded_models(connection_factory=lifecycle_db)

    assert result["face_models_unloaded"] is True
    assert result["stt_model_unloaded"] is False
    assert face_calls == ["invalidate", "bulk feature disabled"]
    assert stt_calls == []
