"""Shared validation and SQS partial-failure handling for hybrid workers."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)


class InvalidTask(ValueError):
    """The queue message does not match the worker's public contract."""


def message_document(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the task name and payload from one SQS record."""
    try:
        document = json.loads(record["body"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidTask("SQS body must be a JSON object") from exc
    if not isinstance(document, dict):
        raise InvalidTask("SQS body must be a JSON object")
    if int(document.get("version", 1)) != 1:
        raise InvalidTask("Unsupported task message version")
    task = str(document.get("task") or "").strip()
    payload = document.get("payload", {})
    if payload is None:
        payload = {}
    if not task or not isinstance(payload, dict):
        raise InvalidTask("Task and object payload are required")
    return task, payload


def process_sqs_event(
    event: dict[str, Any],
    processors: dict[str, Callable[[dict[str, Any]], Any]],
) -> dict[str, list[dict[str, str]]]:
    """Process independently so SQS retries only failed messages."""
    failures: list[dict[str, str]] = []
    for record in event.get("Records") or []:
        message_id = str(record.get("messageId") or "unknown")
        try:
            task, payload = message_document(record)
            processor = processors.get(task)
            if processor is None:
                raise InvalidTask(f"Task is not allowed by this worker: {task}")
            processor(payload)
        except Exception:
            logger.exception("Hybrid task failed: message_id=%s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
