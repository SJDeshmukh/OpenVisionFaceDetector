import json
import io
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from lambda_workers import outbound_email_handler, report_pipeline, vpc_db_handler, worker_common


def _record(message_id, body):
    return {"messageId": message_id, "body": json.dumps(body)}


def test_worker_reports_only_failed_sqs_records():
    received = []
    event = {
        "Records": [
            _record("ok", {"version": 1, "task": "allowed", "payload": {"value": 7}}),
            _record("bad", {"version": 1, "task": "blocked", "payload": {}}),
        ]
    }

    result = worker_common.process_sqs_event(event, {"allowed": lambda payload: received.append(payload)})

    assert received == [{"value": 7}]
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad"}]}


def test_worker_rejects_non_object_payload():
    event = {"Records": [_record("bad", {"version": 1, "task": "allowed", "payload": []})]}
    result = worker_common.process_sqs_event(event, {"allowed": lambda _payload: None})
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad"}]}


def test_outbound_email_worker_uses_complete_payload(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.example.test", 587, 10)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, username, password):
            assert (username, password) == ("sender@example.test", "secret")

        def send_message(self, message):
            sent.append(message)
            return {}

    monkeypatch.setattr(outbound_email_handler.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("MAIL_SMTP_USERNAME", "sender@example.test")
    monkeypatch.setenv("MAIL_SMTP_APP_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("MAIL_SMTP_TIMEOUT_SECONDS", "10")
    event = {"Records": [_record("email-1", {
        "version": 1,
        "task": "outbound.send_email",
        "payload": {
            "recipient": "employee@example.test",
            "subject": "Monthly report",
            "body": "Attached.",
            "message_id": "<stable-id@example.test>",
        },
    })]}

    result = outbound_email_handler.handler(event, None)

    assert result == {"batchItemFailures": []}
    assert len(sent) == 1
    assert sent[0]["To"] == "employee@example.test"
    assert sent[0]["Message-ID"] == "<stable-id@example.test>"


def test_vpc_cleanup_commits_as_one_transaction(monkeypatch):
    statements = []

    class FakeCursor:
        rowcount = 2

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            statements.append(" ".join(statement.split()))

    class FakeConnection:
        committed = False
        rolled_back = False
        closed = False

        def cursor(self):
            return FakeCursor()

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(vpc_db_handler, "_connect", lambda: connection)

    result = vpc_db_handler.cleanup_orphans({})

    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    assert result["attendance"] == 2
    assert statements[0] == "SET LOCAL statement_timeout = '55s'"
    assert statements[1] == "SET LOCAL lock_timeout = '5s'"


def test_s3_report_retry_does_not_send_email_twice(monkeypatch):
    class ConditionalCheckFailedException(Exception):
        pass

    class FakeTable:
        meta = SimpleNamespace(client=SimpleNamespace(exceptions=SimpleNamespace(
            ConditionalCheckFailedException=ConditionalCheckFailedException,
        )))

        def put_item(self, **_kwargs):
            raise ConditionalCheckFailedException()

        def get_item(self, **_kwargs):
            return {"Item": {"status": "sent", "message_id": "<already-sent@example.test>"}}

    artifact = {
        "version": 1,
        "task": "outbound.send_report_artifact",
        "idempotency_key": "employee-monthly:req:1:2026-09:7",
        "email": {
            "recipient": "employee@example.test",
            "subject": "Report",
            "body": "Attached",
            "message_id": "<stable@example.test>",
        },
        "reconcile": {"kind": "employee_monthly", "job_id": "job-7"},
    }

    class FakeS3:
        deleted = []

        def get_object(self, **_kwargs):
            return {"Body": io.BytesIO(json.dumps(artifact).encode())}

        def delete_object(self, **kwargs):
            self.deleted.append(kwargs)

    class FakeSQS:
        messages = []

        def send_message(self, **kwargs):
            self.messages.append(kwargs)

    class FakeDynamo:
        def Table(self, _name):
            return FakeTable()

    s3 = FakeS3()
    sqs = FakeSQS()
    monkeypatch.setattr(outbound_email_handler, "_clients", lambda: (s3, sqs, FakeDynamo()))
    monkeypatch.setattr(
        outbound_email_handler, "send_email",
        lambda _payload: (_ for _ in ()).throw(AssertionError("SMTP must not be called")),
    )
    monkeypatch.setenv("REPORT_IDEMPOTENCY_TABLE", "report-idempotency")
    monkeypatch.setenv("DATABASE_JOBS_QUEUE_URL", "https://sqs.example.test/database")

    result = outbound_email_handler.handler({"Records": [{
        "eventSource": "aws:s3",
        "s3": {"bucket": {"name": "private-reports"}, "object": {"key": "prepared-email/a/report.json"}},
    }]}, None)

    assert result == {"processed": 1}
    assert len(sqs.messages) == 1
    queued = json.loads(sqs.messages[0]["MessageBody"])
    assert queued["task"] == "reports.delivery_result"
    assert queued["payload"]["status"] == "sent"
    assert queued["payload"]["message_id"] == "<already-sent@example.test>"
    assert s3.deleted == [{"Bucket": "private-reports", "Key": "prepared-email/a/report.json"}]


def test_reconciliation_failure_keeps_successful_smtp_idempotency(monkeypatch):
    updates = []

    class FakeTable:
        def put_item(self, **_kwargs):
            return None

        def update_item(self, **kwargs):
            updates.append(kwargs)

    artifact = {
        "version": 1,
        "task": "outbound.send_report_artifact",
        "idempotency_key": "automated-report:42",
        "email": {"recipient": "owner@example.test", "subject": "Report", "body": "Attached"},
        "reconcile": {"kind": "automated", "delivery_id": 42},
    }

    class FakeS3:
        def get_object(self, **_kwargs):
            return {"Body": io.BytesIO(json.dumps(artifact).encode())}

        def delete_object(self, **_kwargs):
            raise AssertionError("Artifact must remain when reconciliation fails")

    class FakeSQS:
        def send_message(self, **_kwargs):
            raise RuntimeError("temporary SQS error")

    class FakeDynamo:
        def Table(self, _name):
            return FakeTable()

    monkeypatch.setattr(outbound_email_handler, "_clients", lambda: (FakeS3(), FakeSQS(), FakeDynamo()))
    monkeypatch.setattr(
        outbound_email_handler, "send_email",
        lambda _payload: {"sent": True, "message_id": "<accepted@example.test>"},
    )
    monkeypatch.setenv("REPORT_IDEMPOTENCY_TABLE", "report-idempotency")
    monkeypatch.setenv("DATABASE_JOBS_QUEUE_URL", "https://sqs.example.test/database")

    event = {"Records": [{
        "eventSource": "aws:s3",
        "s3": {"bucket": {"name": "private-reports"}, "object": {"key": "prepared-email/b/report.json"}},
    }]}
    try:
        outbound_email_handler.handler(event, None)
        assert False, "SQS reconciliation failure should leave the S3 event retryable"
    except RuntimeError as exc:
        assert "temporary SQS error" in str(exc)

    assert len(updates) == 1
    assert updates[0]["ExpressionAttributeValues"][":status"] == "sent"


def test_db_lambda_enforces_vendor_canary_allowlist(monkeypatch):
    monkeypatch.setenv("REPORT_LAMBDA_VENDOR_IDS", "12,19")
    report_pipeline._require_allowed_vendor(12)
    try:
        report_pipeline._require_allowed_vendor(13)
        assert False, "Unlisted vendor must be rejected by the DB Lambda"
    except worker_common.InvalidTask as exc:
        assert "not enabled" in str(exc)
