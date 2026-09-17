import json
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import report_queue_service


def test_report_queue_defaults_to_celery(monkeypatch):
    class Result:
        id = "celery-123"

    class Task:
        def apply_async(self, args, queue):
            assert args == [4, "2026-09", None, {"department": "Assembly"}]
            assert queue == "reports"
            return Result()

    monkeypatch.delenv("REPORT_TASK_BACKEND", raising=False)
    queued = report_queue_service.queue_employee_monthly_report(
        4, "2026-09", filters={"department": "Assembly"}, celery_task=Task(),
    )

    assert queued.id == "celery-123"
    assert queued.backend == "celery"


def test_report_queue_canary_uses_versioned_database_message(monkeypatch):
    sent = []

    class SQS:
        def send_message(self, **kwargs):
            sent.append(kwargs)
            return {"MessageId": "sqs-1"}

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: SQS())
    monkeypatch.setenv("REPORT_TASK_BACKEND", "lambda_sqs")
    monkeypatch.setenv("REPORT_DATABASE_QUEUE_URL", "https://sqs.example.test/database")
    monkeypatch.setenv("REPORT_LAMBDA_VENDOR_IDS", "4")

    queued = report_queue_service.queue_automated_report(
        91, vendor_id=4, request_id="request-91",
    )

    assert queued.id == "request-91"
    assert queued.backend == "lambda_sqs"
    body = json.loads(sent[0]["MessageBody"])
    assert body == {
        "version": 1,
        "task": "reports.prepare_automated",
        "payload": {"delivery_id": 91, "request_id": "request-91"},
    }


def test_report_message_id_is_stable():
    from lambda_workers.report_pipeline import _stable_message_id

    first = _stable_message_id("automated-report:91")
    second = _stable_message_id("automated-report:91")
    assert first == second
    assert first.startswith("<") and first.endswith("@reports.tapinx.in>")


def test_unlisted_vendor_stays_on_celery(monkeypatch):
    class Result:
        id = "celery-safe-fallback"

    class Task:
        def apply_async(self, args, queue):
            assert args == [7, "2026-09", None, {}]
            assert queue == "reports"
            return Result()

    monkeypatch.setenv("REPORT_TASK_BACKEND", "lambda_sqs")
    monkeypatch.setenv("REPORT_LAMBDA_VENDOR_IDS", "4,5")

    queued = report_queue_service.queue_employee_monthly_report(
        7, "2026-09", celery_task=Task(),
    )

    assert queued.backend == "celery"
    assert queued.id == "celery-safe-fallback"


def test_full_rollout_requires_explicit_wildcard(monkeypatch):
    monkeypatch.setenv("REPORT_TASK_BACKEND", "lambda_sqs")
    monkeypatch.setenv("REPORT_LAMBDA_VENDOR_IDS", "")
    assert report_queue_service.lambda_reports_enabled(4) is False
    monkeypatch.setenv("REPORT_LAMBDA_VENDOR_IDS", "*")
    assert report_queue_service.lambda_reports_enabled(4) is True
