import importlib
import os
import sys
from pathlib import Path
import pytest

BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_celery(monkeypatch, broker, redis="redis://127.0.0.1:6379/0"):
    monkeypatch.setenv("CELERY_BROKER_URL", broker)
    monkeypatch.setenv("REDIS_URL", redis)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)
    sys.modules.pop("celery_app", None)
    return importlib.import_module("celery_app")


def test_amqp_uses_redis_result_backend_and_durable_routed_queues(monkeypatch):
    module = _reload_celery(
        monkeypatch,
        "amqp://worker:secret@127.0.0.1:5672/openvision",
    )
    assert module.BROKER_TYPE == "amqp"
    assert module.RESULT_BACKEND == "redis://127.0.0.1:6379/0"
    assert module.celery.conf.task_routes["tasks.detect_faces"]["queue"] == "face_priority"
    assert module.celery.conf.task_routes["tasks.send_automated_report"]["queue"] == "reports"
    queues = {queue.name: queue for queue in module.celery.conf.task_queues}
    assert set(module.QUEUE_NAMES).issubset(queues)
    assert queues["face_priority"].queue_arguments["x-max-priority"] == 10
    assert queues["reports"].queue_arguments["x-dead-letter-exchange"] == "openvision.dead"
    assert module.celery.conf.task_acks_late is True
    assert module.celery.conf.task_reject_on_worker_lost is True
    assert module.celery.conf.worker_prefetch_multiplier == 1
    assert module.celery.conf.broker_transport_options["confirm_publish"] is True


def test_redis_fallback_remains_supported(monkeypatch):
    module = _reload_celery(monkeypatch, "redis://127.0.0.1:6379/0")
    assert module.BROKER_TYPE == "redis"
    queues = {queue.name: queue for queue in module.celery.conf.task_queues}
    assert queues["face_priority"].queue_arguments is None
    assert module.celery.conf.broker_transport_options == {}


def test_broker_url_logging_redacts_password(monkeypatch):
    module = _reload_celery(monkeypatch, "amqp://worker:very-secret@rabbit:5672/openvision")
    safe = module._safe_url(module.BROKER_URL)
    assert "very-secret" not in safe
    assert safe == "amqp://worker:***@rabbit:5672/openvision"


def test_amqp_fails_fast_without_a_result_backend(monkeypatch):
    monkeypatch.setenv("CELERY_BROKER_URL", "amqp://worker:secret@127.0.0.1/openvision")
    # Empty values also prevent python-dotenv from filling these from a developer .env.
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "")
    sys.modules.pop("celery_app", None)
    with pytest.raises(RuntimeError, match="result store"):
        importlib.import_module("celery_app")
