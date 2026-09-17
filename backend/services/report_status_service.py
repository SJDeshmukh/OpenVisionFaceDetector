"""Read-only operational status for the hybrid report pipeline."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from services.report_queue_service import lambda_report_vendor_ids


def _db():
    from utils import get_db_connection
    return get_db_connection()


def _counts(cursor, statement, params=()):
    cursor.execute(statement, params)
    return {str(row[0]): int(row[1]) for row in (cursor.fetchall() or [])}


def report_batch_status(vendor_id, reference_id):
    connection = _db()
    try:
        cursor = connection.cursor()
        counts = _counts(
            cursor,
            """SELECT status, COUNT(*) FROM report_delivery_jobs
               WHERE vendor_id = ? AND reference_id = ? GROUP BY status""",
            (vendor_id, reference_id),
        )
        cursor.execute("""
            SELECT id, person_id, recipient_email, status, attempts, message_id,
                   error, created_at, prepared_at, sent_at
            FROM report_delivery_jobs
            WHERE vendor_id = ? AND reference_id = ?
            ORDER BY CASE WHEN status = 'failed' THEN 0 WHEN status = 'sent' THEN 2 ELSE 1 END,
                     created_at, id
            LIMIT 200
        """, (vendor_id, reference_id))
        deliveries = [dict(row) for row in (cursor.fetchall() or [])]
    finally:
        connection.close()

    for delivery in deliveries:
        for field in ("created_at", "prepared_at", "sent_at"):
            value = delivery.get(field)
            if hasattr(value, "isoformat"):
                delivery[field] = value.isoformat()
    total = sum(counts.values())
    if total == 0:
        overall = "not_found"
    elif counts.get("failed"):
        overall = "failed"
    elif counts.get("sent") == total:
        overall = "sent"
    elif counts.get("prepared") or counts.get("preparing"):
        overall = "processing"
    else:
        overall = "queued"
    return {
        "reference_id": reference_id,
        "status": overall,
        "total": total,
        "counts": counts,
        "deliveries": deliveries,
        "details_truncated": total > len(deliveries),
    }


def _queue_status(queue_url):
    if not queue_url:
        return {"configured": False}
    import boto3

    response = boto3.client(
        "sqs", region_name=os.environ.get("AWS_REGION") or None,
    ).get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
            "ApproximateNumberOfMessagesDelayed",
        ],
    )
    attributes = response.get("Attributes") or {}
    return {
        "configured": True,
        "queue": queue_url.rstrip("/").rsplit("/", 1)[-1],
        "visible": int(attributes.get("ApproximateNumberOfMessages", 0)),
        "in_flight": int(attributes.get("ApproximateNumberOfMessagesNotVisible", 0)),
        "delayed": int(attributes.get("ApproximateNumberOfMessagesDelayed", 0)),
    }


def hybrid_report_health():
    backend = os.environ.get("REPORT_TASK_BACKEND", "celery").strip().lower()
    allowed = sorted(lambda_report_vendor_ids())
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    recent = {"employee": {}, "automated": {}}
    database_error = None
    connection = None
    try:
        connection = _db()
        cursor = connection.cursor()
        recent["employee"] = _counts(
            cursor,
            "SELECT status, COUNT(*) FROM report_delivery_jobs WHERE created_at >= ? GROUP BY status",
            (cutoff,),
        )
        recent["automated"] = _counts(
            cursor,
            "SELECT status, COUNT(*) FROM automated_report_deliveries WHERE created_at >= ? GROUP BY status",
            (cutoff,),
        )
    except Exception as exc:
        database_error = str(exc)[:300]
    finally:
        if connection is not None:
            connection.close()

    queues = {}
    queue_error = None
    if backend == "lambda_sqs":
        try:
            queues["database_jobs"] = _queue_status(os.environ.get("REPORT_DATABASE_QUEUE_URL", "").strip())
            queues["dead_letter"] = _queue_status(os.environ.get("REPORT_DLQ_URL", "").strip())
        except Exception as exc:
            queue_error = str(exc)[:300]

    problems = []
    if backend == "lambda_sqs" and not allowed:
        problems.append("No Lambda report canary vendors are configured")
    if backend == "lambda_sqs" and not os.environ.get("REPORT_DATABASE_QUEUE_URL", "").strip():
        problems.append("Database jobs queue URL is missing")
    if backend == "lambda_sqs" and not os.environ.get("REPORT_DLQ_URL", "").strip():
        problems.append("Dead-letter queue URL is missing")
    if database_error:
        problems.append("Report delivery status database query failed")
    if queue_error:
        problems.append("SQS health query failed")
    if queues.get("dead_letter", {}).get("visible", 0) > 0:
        problems.append("Report dead-letter queue is not empty")
    failed = recent["employee"].get("failed", 0) + recent["automated"].get("failed", 0)
    if failed:
        problems.append(f"{failed} report deliveries failed in the last 24 hours")

    if backend != "lambda_sqs":
        status = "disabled"
    else:
        status = "degraded" if problems else "healthy"
    return {
        "status": status,
        "backend": backend,
        "canary_vendor_ids": allowed,
        "full_rollout": "*" in allowed,
        "recent_24h": recent,
        "queues": queues,
        "problems": problems,
        "database_error": database_error,
        "queue_error": queue_error,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
