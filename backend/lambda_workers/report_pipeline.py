"""DB-side report preparation and delivery reconciliation.

This module may access only PostgreSQL and S3.  Public email delivery happens
in the non-VPC worker after S3 emits an object-created event.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime

from lambda_workers.db_adapter import get_db_connection
from lambda_workers.worker_common import InvalidTask


MAX_ARTIFACT_BYTES = int(os.environ.get("REPORT_ARTIFACT_MAX_BYTES", str(8 * 1024 * 1024)))
_S3_CLIENT = None


def _allowed_vendor_ids():
    return {
        value.strip()
        for value in os.environ.get("REPORT_LAMBDA_VENDOR_IDS", "").split(",")
        if value.strip()
    }


def _require_allowed_vendor(vendor_id):
    allowed = _allowed_vendor_ids()
    if "*" not in allowed and str(vendor_id) not in allowed:
        raise InvalidTask(f"Vendor {vendor_id} is not enabled for Lambda reports")


def _required(payload, field):
    value = payload.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise InvalidTask(f"Report field is required: {field}")
    return value


def _ensure_jobs_table(connection):
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report_delivery_jobs (
                id TEXT PRIMARY KEY,
                vendor_id INTEGER NOT NULL,
                report_kind TEXT NOT NULL,
                reference_id TEXT,
                person_id INTEGER,
                idempotency_key TEXT NOT NULL UNIQUE,
                recipient_email TEXT NOT NULL,
                artifact_key TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                message_id TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                prepared_at TIMESTAMP,
                sent_at TIMESTAMP
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_report_delivery_vendor "
            "ON report_delivery_jobs(vendor_id, created_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_report_delivery_reference "
            "ON report_delivery_jobs(vendor_id, reference_id)"
        )
    connection.commit()


def _attachment_document(item):
    content = item.get("content", b"")
    if isinstance(content, str):
        content = content.encode("utf-8")
    return {
        "filename": str(item.get("filename") or "report.bin"),
        "mimetype": str(item.get("mimetype") or "application/octet-stream"),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _stable_message_id(idempotency_key):
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    domain = os.environ.get("REPORT_MESSAGE_ID_DOMAIN", "reports.tapinx.in").strip()
    return f"<{digest[:48]}@{domain}>"


def _artifact_key(idempotency_key):
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"prepared-email/{digest[:2]}/{digest}.json"


def _put_artifact(email_payload, idempotency_key, reconcile):
    bucket = os.environ.get("REPORT_ARTIFACT_BUCKET", "").strip()
    if not bucket:
        raise RuntimeError("REPORT_ARTIFACT_BUCKET is required")
    document = {
        "version": 1,
        "task": "outbound.send_report_artifact",
        "idempotency_key": idempotency_key,
        "email": {
            **email_payload,
            "message_id": _stable_message_id(idempotency_key),
        },
        "reconcile": reconcile,
        "prepared_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    body = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"Prepared report artifact is {len(body)} bytes; limit is {MAX_ARTIFACT_BYTES}"
        )
    key = _artifact_key(idempotency_key)
    global _S3_CLIENT
    if _S3_CLIENT is None:
        import boto3
        _S3_CLIENT = boto3.client("s3")
    _S3_CLIENT.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        ServerSideEncryption="AES256",
        Metadata={"idempotency-key-sha256": hashlib.sha256(idempotency_key.encode()).hexdigest()},
    )
    return key


def _record_preparing(connection, job):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO report_delivery_jobs
                    (id, vendor_id, report_kind, reference_id, person_id,
                     idempotency_key, recipient_email, artifact_key, status,
                     attempts, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'preparing', 1, NULL)
                ON CONFLICT (idempotency_key) DO UPDATE SET
                    artifact_key = EXCLUDED.artifact_key,
                    status = CASE
                        WHEN report_delivery_jobs.status = 'sent' THEN 'sent'
                        ELSE 'preparing'
                    END,
                    attempts = report_delivery_jobs.attempts + 1,
                    error = CASE
                        WHEN report_delivery_jobs.status = 'sent' THEN report_delivery_jobs.error
                        ELSE NULL
                    END
                RETURNING status
            """, (
                job["id"], job["vendor_id"], job["report_kind"],
                job.get("reference_id"), job.get("person_id"),
                job["idempotency_key"], job["recipient_email"], job["artifact_key"],
            ))
            status = cursor.fetchone()[0]
        connection.commit()
        return status
    except Exception:
        connection.rollback()
        raise


def _mark_job_prepared(connection, job_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE report_delivery_jobs
                SET status = CASE WHEN status = 'sent' THEN 'sent' ELSE 'prepared' END,
                    prepared_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (job_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _mark_job_failed(connection, job_id, error):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE report_delivery_jobs
                SET status = CASE WHEN status = 'sent' THEN 'sent' ELSE 'failed' END,
                    error = CASE WHEN status = 'sent' THEN error ELSE ? END
                WHERE id = ?
            """, (str(error)[:2000], job_id))
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def prepare_employee_monthly(payload):
    request_id = str(_required(payload, "request_id"))
    vendor_id = int(_required(payload, "vendor_id"))
    _require_allowed_vendor(vendor_id)
    month = str(_required(payload, "month"))
    person_type = payload.get("person_type")
    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        raise InvalidTask("filters must be an object")

    from services.employee_email_reports_service import build_employee_monthly_deliveries

    vendor_name, deliveries, skipped = build_employee_monthly_deliveries(
        vendor_id, month, person_type, filters=filters,
    )
    prepared = 0
    failures = []
    status_connection = get_db_connection()
    try:
        _ensure_jobs_table(status_connection)
        for delivery in deliveries:
            person_id = int(delivery["person_id"])
            idempotency_key = f"employee-monthly:{request_id}:{vendor_id}:{month}:{person_id}"
            job_id = hashlib.sha256(idempotency_key.encode()).hexdigest()
            artifact_key = _artifact_key(idempotency_key)
            delivery_status = _record_preparing(status_connection, {
                "id": job_id,
                "vendor_id": vendor_id,
                "report_kind": "employee_monthly",
                "reference_id": request_id,
                "person_id": person_id,
                "idempotency_key": idempotency_key,
                "recipient_email": delivery["recipient"],
                "artifact_key": artifact_key,
            })
            if delivery_status == "sent":
                continue
            try:
                _put_artifact(
                    {
                        "recipient": delivery["recipient"],
                        "subject": delivery["subject"],
                        "body": delivery["body"],
                        "attachments": [_attachment_document(item) for item in delivery.get("attachments") or []],
                    },
                    idempotency_key,
                    {"kind": "employee_monthly", "job_id": job_id},
                )
                _mark_job_prepared(status_connection, job_id)
                prepared += 1
            except Exception as exc:
                _mark_job_failed(status_connection, job_id, exc)
                failures.append({"person_id": person_id, "error": str(exc)[:300]})
    finally:
        status_connection.close()
    if failures:
        raise RuntimeError(f"Failed to prepare {len(failures)} employee report artifact(s): {failures[:3]}")
    return {
        "vendor": vendor_name,
        "request_id": request_id,
        "prepared": prepared,
        "skipped_without_email": skipped,
    }


def _load_automated_delivery(delivery_id):
    from services.automated_reports_service import _json_list

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT d.*, ars.operational_day_cutoff, ars.report_types,
                       ars.enabled AS schedule_enabled, v.company_name,
                       v.status AS vendor_status, s.features
                FROM automated_report_deliveries d
                JOIN automated_report_schedules ars ON ars.id = d.schedule_id
                JOIN vendors v ON v.id = d.vendor_id
                LEFT JOIN subscriptions s ON s.vendor_id = d.vendor_id
                WHERE d.id = ?
            """, (delivery_id,))
            row = cursor.fetchone()
            if not row:
                return None
            delivery = dict(row)
            features = _json_list(delivery.get("features"))
            is_test = str(delivery.get("frequency") or "").startswith("test-")
            active = (
                (bool(delivery.get("schedule_enabled")) or is_test)
                and delivery.get("vendor_status") == "active"
                and "automated_email_reports" in features
            )
            _require_allowed_vendor(delivery["vendor_id"])
            if not active:
                cursor.execute(
                    "UPDATE automated_report_deliveries SET status = 'skipped', error = ? WHERE id = ?",
                    ("Schedule, vendor, or feature is inactive", delivery_id),
                )
                connection.commit()
                return None
            if delivery.get("status") == "sent":
                return {"already_sent": True, **delivery}
            cursor.execute("""
                UPDATE automated_report_deliveries
                SET status = 'preparing', attempts = COALESCE(attempts, 0) + 1, error = NULL
                WHERE id = ?
            """, (delivery_id,))
            connection.commit()
            return delivery
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def prepare_automated(payload):
    delivery_id = int(_required(payload, "delivery_id"))
    delivery = _load_automated_delivery(delivery_id)
    if not delivery:
        return {"status": "missing_or_skipped"}
    if delivery.get("already_sent"):
        return {"status": "already_sent"}

    from services.automated_reports_service import build_report_attachments, _json_list

    start = datetime.fromisoformat(str(delivery["period_start"])).date()
    end = datetime.fromisoformat(str(delivery["period_end"])).date()
    vendor_name, attachments, event_count = build_report_attachments(
        delivery["vendor_id"], start, end,
        delivery.get("operational_day_cutoff") or "07:00",
        _json_list(delivery.get("report_types")),
    )
    frequency = str(delivery["frequency"])
    frequency_label = "Test" if frequency.startswith("test-") else frequency.title()
    idempotency_key = f"automated-report:{delivery_id}"
    artifact_key = _put_artifact(
        {
            "recipient": delivery["recipient_email"],
            "subject": f"{vendor_name} — {frequency_label} attendance report ({start} to {end})",
            "body": (
                f"Hello {vendor_name},\n\n"
                f"Your automated {frequency_label.lower()} attendance report for {start} to {end} is attached.\n"
                f"The report contains {event_count} attendance events and uses your operational-day cutoff, "
                "so overnight shifts remain together.\n\nRegards,\nOpenVisionX Reports"
            ),
            "attachments": [_attachment_document(item) for item in attachments],
        },
        idempotency_key,
        {"kind": "automated", "delivery_id": delivery_id},
    )
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE automated_report_deliveries
                   SET status = CASE WHEN status = 'sent' THEN 'sent' ELSE 'prepared' END,
                       error = CASE WHEN status = 'sent' THEN error ELSE NULL END
                   WHERE id = ?""",
                (delivery_id,),
            )
        connection.commit()
    finally:
        connection.close()
    return {"status": "prepared", "delivery_id": delivery_id, "artifact_key": artifact_key}


def dispatch_due(_payload):
    from services.automated_reports_service import dispatch_due_reports

    allowed = _allowed_vendor_ids()
    if not allowed:
        return {"queued": 0, "results": [], "reason": "no canary vendors configured"}
    delivery_ids = dispatch_due_reports(vendor_ids=None if "*" in allowed else allowed)
    results = [prepare_automated({"delivery_id": delivery_id}) for delivery_id in delivery_ids]
    return {"queued": len(delivery_ids), "results": results}


def reconcile_delivery(payload):
    kind = str(_required(payload, "kind"))
    status = str(_required(payload, "status"))
    if status not in {"sent", "failed"}:
        raise InvalidTask("Delivery status must be sent or failed")
    message_id = str(payload.get("message_id") or "")[:500] or None
    error = str(payload.get("error") or "")[:2000] or None
    connection = get_db_connection()
    try:
        if kind == "automated":
            delivery_id = int(_required(payload, "delivery_id"))
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE automated_report_deliveries
                    SET status = CASE WHEN status = 'sent' THEN 'sent' ELSE ? END,
                        message_id = COALESCE(?, message_id),
                        error = CASE WHEN status = 'sent' AND ? = 'failed' THEN error ELSE ? END,
                        sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END
                    WHERE id = ?
                """, (status, message_id, status, error, status, delivery_id))
        elif kind == "employee_monthly":
            job_id = str(_required(payload, "job_id"))
            _ensure_jobs_table(connection)
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE report_delivery_jobs
                    SET status = CASE WHEN status = 'sent' THEN 'sent' ELSE ? END,
                        message_id = COALESCE(?, message_id),
                        error = CASE WHEN status = 'sent' AND ? = 'failed' THEN error ELSE ? END,
                        sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END
                    WHERE id = ?
                """, (status, message_id, status, error, status, job_id))
        else:
            raise InvalidTask(f"Unknown reconciliation kind: {kind}")
        connection.commit()
        return {"status": status, "kind": kind}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
