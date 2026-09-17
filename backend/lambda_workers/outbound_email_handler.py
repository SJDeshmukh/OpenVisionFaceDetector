"""Non-VPC email worker.

Messages must already contain all recipient/content data. This worker never
opens a database connection, so it retains outbound SMTP access without NAT.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import smtplib
import time
import urllib.parse
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from lambda_workers.worker_common import InvalidTask, process_sqs_event


logger = logging.getLogger(__name__)


def _required(payload, field):
    value = str(payload.get(field) or "").strip()
    if not value:
        raise InvalidTask(f"Email field is required: {field}")
    return value


def send_email(payload):
    recipient = _required(payload, "recipient")
    subject = _required(payload, "subject")
    text_body = _required(payload, "body")
    username = os.environ.get("MAIL_SMTP_USERNAME", "").strip()
    password = os.environ.get("MAIL_SMTP_APP_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError("SMTP credentials are not configured")

    sender = os.environ.get("MAIL_FROM_ADDRESS", username).strip()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((os.environ.get("MAIL_FROM_NAME", "OpenVisionX Reports"), sender))
    message["To"] = recipient
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = str(payload.get("message_id") or make_msgid(domain=sender.partition("@")[2] or None))
    message.set_content(text_body)

    for item in payload.get("attachments") or []:
        try:
            content = base64.b64decode(item["content_base64"], validate=True)
            maintype, subtype = str(item.get("mimetype") or "application/octet-stream").split("/", 1)
            filename = _required(item, "filename")
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidTask("Invalid email attachment") from exc
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    with smtplib.SMTP(
        os.environ.get("MAIL_SMTP_HOST", "smtp.gmail.com"),
        int(os.environ.get("MAIL_SMTP_PORT", "587")),
        timeout=int(os.environ.get("MAIL_SMTP_TIMEOUT_SECONDS", "30")),
    ) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(username, password)
        refused = server.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    return {"sent": True, "recipient": recipient, "message_id": message["Message-ID"]}


def _clients():
    import boto3

    return boto3.client("s3"), boto3.client("sqs"), boto3.resource("dynamodb")


def _acquire_idempotency(table, key, artifact):
    now = int(time.time())
    lease_until = now + int(os.environ.get("REPORT_IDEMPOTENCY_LEASE_SECONDS", "180"))
    ttl = now + int(os.environ.get("REPORT_IDEMPOTENCY_TTL_SECONDS", str(35 * 86400)))
    item = {
        "idempotency_key": key,
        "status": "processing",
        "lease_expires": lease_until,
        "expires_at": ttl,
        "artifact": artifact,
        "updated_at": now,
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(idempotency_key)")
        return "acquired", item
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        existing = table.get_item(Key={"idempotency_key": key}, ConsistentRead=True).get("Item") or {}
        if existing.get("status") == "sent":
            return "already_sent", existing
        try:
            table.update_item(
                Key={"idempotency_key": key},
                UpdateExpression=(
                    "SET #status = :processing, lease_expires = :lease, expires_at = :ttl, "
                    "artifact = :artifact, updated_at = :now REMOVE error"
                ),
                ConditionExpression="#status = :failed OR lease_expires < :now",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":processing": "processing", ":failed": "failed", ":lease": lease_until,
                    ":ttl": ttl, ":artifact": artifact, ":now": now,
                },
            )
            return "acquired", item
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise RuntimeError("Report delivery is already being processed") from exc


def _mark_idempotency(table, key, status, message_id=None, error=None):
    now = int(time.time())
    values = {":status": status, ":now": now, ":lease": 0}
    expression = "SET #status = :status, updated_at = :now, lease_expires = :lease"
    if message_id:
        expression += ", message_id = :message_id"
        values[":message_id"] = message_id
    if error:
        expression += ", error = :error"
        values[":error"] = str(error)[:2000]
    else:
        expression += " REMOVE error"
    table.update_item(
        Key={"idempotency_key": key},
        UpdateExpression=expression,
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues=values,
    )


def _reconcile(sqs, metadata, status, message_id=None, error=None):
    queue_url = os.environ.get("DATABASE_JOBS_QUEUE_URL", "").strip()
    if not queue_url:
        raise RuntimeError("DATABASE_JOBS_QUEUE_URL is required")
    payload = {
        **(metadata or {}),
        "status": status,
        "message_id": message_id,
        "error": str(error)[:2000] if error else None,
    }
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"version": 1, "task": "reports.delivery_result", "payload": payload}),
    )


def send_report_artifact(bucket, key):
    s3, sqs, dynamodb = _clients()
    response = s3.get_object(Bucket=bucket, Key=key)
    try:
        document = json.loads(response["Body"].read())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidTask("Report artifact must contain valid JSON") from exc
    if not isinstance(document, dict) or int(document.get("version", 0)) != 1:
        raise InvalidTask("Unsupported report artifact version")
    if document.get("task") != "outbound.send_report_artifact":
        raise InvalidTask("Artifact task is not allowed")
    key_value = str(document.get("idempotency_key") or "").strip()
    email_payload = document.get("email")
    reconcile = document.get("reconcile")
    if not key_value or not isinstance(email_payload, dict) or not isinstance(reconcile, dict):
        raise InvalidTask("Artifact idempotency, email, and reconciliation fields are required")

    table_name = os.environ.get("REPORT_IDEMPOTENCY_TABLE", "").strip()
    if not table_name:
        raise RuntimeError("REPORT_IDEMPOTENCY_TABLE is required")
    table = dynamodb.Table(table_name)
    state, existing = _acquire_idempotency(table, key_value, f"s3://{bucket}/{key}")
    if state == "already_sent":
        message_id = existing.get("message_id") or email_payload.get("message_id")
        _reconcile(sqs, reconcile, "sent", message_id=message_id)
    else:
        try:
            result = send_email(email_payload)
        except Exception as exc:
            _mark_idempotency(table, key_value, "failed", error=exc)
            try:
                _reconcile(sqs, reconcile, "failed", error=exc)
            except Exception:
                logger.exception("Unable to queue failed report reconciliation")
            raise
        # Persist `sent` before reconciliation. If reconciliation itself fails,
        # the S3 retry observes `sent`, skips SMTP, and retries only the status
        # message. Do not downgrade DynamoDB to failed after SMTP succeeded.
        _mark_idempotency(table, key_value, "sent", message_id=result["message_id"])
        _reconcile(sqs, reconcile, "sent", message_id=result["message_id"])

    try:
        s3.delete_object(Bucket=bucket, Key=key)
    except Exception:
        # Lifecycle cleanup is the safety net. Never retry SMTP because cleanup failed.
        logger.warning("Unable to delete delivered report artifact s3://%s/%s", bucket, key, exc_info=True)
    return {"sent": True, "idempotency_key": key_value}


def _is_s3_event(event):
    records = event.get("Records") or []
    return bool(records and str(records[0].get("eventSource") or "").lower() == "aws:s3")


def _process_s3_event(event):
    for record in event.get("Records") or []:
        try:
            bucket = record["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        except (KeyError, TypeError) as exc:
            raise InvalidTask("Malformed S3 event") from exc
        if not key.startswith("prepared-email/") or not key.endswith(".json"):
            logger.info("Ignoring non-report object s3://%s/%s", bucket, key)
            continue
        send_report_artifact(bucket, key)
    return {"processed": len(event.get("Records") or [])}


PROCESSORS = {"outbound.send_email": send_email}


def handler(event, _context):
    if _is_s3_event(event):
        return _process_s3_event(event)
    return process_sqs_event(event, PROCESSORS)
