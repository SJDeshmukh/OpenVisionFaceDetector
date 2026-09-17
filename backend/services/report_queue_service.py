"""Gradual report-queue switch with Celery as the safe default."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class QueuedReport:
    id: str
    backend: str


def lambda_report_vendor_ids():
    return {
        value.strip()
        for value in os.environ.get("REPORT_LAMBDA_VENDOR_IDS", "").split(",")
        if value.strip()
    }


def lambda_reports_enabled(vendor_id=None):
    if os.environ.get("REPORT_TASK_BACKEND", "celery").strip().lower() != "lambda_sqs":
        return False
    allowed = lambda_report_vendor_ids()
    if "*" in allowed:
        return True
    return vendor_id is not None and str(vendor_id) in allowed


def _send_database_job(task, payload, request_id=None):
    queue_url = os.environ.get("REPORT_DATABASE_QUEUE_URL", "").strip()
    if not queue_url:
        raise RuntimeError("REPORT_DATABASE_QUEUE_URL is required when REPORT_TASK_BACKEND=lambda_sqs")
    request_id = str(request_id or uuid.uuid4())
    body = {
        "version": 1,
        "task": task,
        "payload": {**payload, "request_id": request_id},
    }
    import boto3

    response = boto3.client("sqs", region_name=os.environ.get("AWS_REGION") or None).send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(body, separators=(",", ":"), default=str),
    )
    return QueuedReport(id=request_id, backend="lambda_sqs"), response.get("MessageId")


def queue_employee_monthly_report(
    vendor_id, month, person_type=None, filters=None, *, celery_task=None, request_id=None,
):
    if lambda_reports_enabled(vendor_id):
        queued, _ = _send_database_job(
            "reports.prepare_employee_monthly",
            {
                "vendor_id": int(vendor_id),
                "month": str(month),
                "person_type": person_type,
                "filters": filters or {},
            },
            request_id=request_id,
        )
        return queued
    if celery_task is None:
        raise RuntimeError("Celery report task is not configured")
    task = celery_task.apply_async(
        args=[vendor_id, month, person_type, filters or {}], queue="reports",
    )
    return QueuedReport(id=str(task.id), backend="celery")


def queue_automated_report(delivery_id, *, vendor_id=None, celery_task=None, request_id=None):
    if lambda_reports_enabled(vendor_id):
        queued, _ = _send_database_job(
            "reports.prepare_automated",
            {"delivery_id": int(delivery_id)},
            request_id=request_id,
        )
        return queued
    if celery_task is None:
        raise RuntimeError("Celery report task is not configured")
    task = celery_task.apply_async(args=[delivery_id], queue="reports")
    return QueuedReport(id=str(task.id), backend="celery")
