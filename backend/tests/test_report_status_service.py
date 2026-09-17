import sys
from datetime import datetime
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import report_status_service


class FakeConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.closed = False

    def cursor(self):
        connection = self

        class Cursor:
            def execute(self, _statement, _params=()):
                return None

            def fetchall(self):
                return connection.responses.pop(0)

        return Cursor()

    def close(self):
        self.closed = True


def test_batch_status_reports_reconciled_progress(monkeypatch):
    created = datetime(2026, 9, 17, 10, 0, 0)
    connection = FakeConnection([
        [("sent", 1), ("prepared", 1)],
        [
        {
            "id": "one", "person_id": 1, "recipient_email": "one@example.test",
            "status": "sent", "attempts": 1, "message_id": "<one>", "error": None,
            "created_at": created, "prepared_at": created, "sent_at": created,
        },
        {
            "id": "two", "person_id": 2, "recipient_email": "two@example.test",
            "status": "prepared", "attempts": 1, "message_id": None, "error": None,
            "created_at": created, "prepared_at": created, "sent_at": None,
        },
        ],
    ])
    monkeypatch.setattr(report_status_service, "_db", lambda: connection)

    result = report_status_service.report_batch_status(8, "request-8")

    assert result["status"] == "processing"
    assert result["counts"] == {"sent": 1, "prepared": 1}
    assert result["deliveries"][0]["created_at"] == "2026-09-17T10:00:00"
    assert connection.closed is True


def test_health_is_degraded_when_dlq_contains_messages(monkeypatch):
    connection = FakeConnection([
        [("sent", 4), ("failed", 1)],
        [("sent", 2)],
    ])
    monkeypatch.setattr(report_status_service, "_db", lambda: connection)
    monkeypatch.setenv("REPORT_TASK_BACKEND", "lambda_sqs")
    monkeypatch.setenv("REPORT_LAMBDA_VENDOR_IDS", "8")
    monkeypatch.setenv("REPORT_DATABASE_QUEUE_URL", "https://sqs.test/database-jobs")
    monkeypatch.setenv("REPORT_DLQ_URL", "https://sqs.test/dead-letter")
    monkeypatch.setattr(
        report_status_service,
        "_queue_status",
        lambda url: {
            "configured": True,
            "queue": url.rsplit("/", 1)[-1],
            "visible": 2 if url.endswith("dead-letter") else 0,
            "in_flight": 0,
            "delayed": 0,
        },
    )

    result = report_status_service.hybrid_report_health()

    assert result["status"] == "degraded"
    assert result["canary_vendor_ids"] == ["8"]
    assert "Report dead-letter queue is not empty" in result["problems"]
    assert "1 report deliveries failed in the last 24 hours" in result["problems"]
