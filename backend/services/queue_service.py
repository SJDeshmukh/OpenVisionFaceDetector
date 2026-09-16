"""Broker-neutral Celery queue health and depth inspection."""
from urllib.parse import urlsplit

QUEUE_NAMES = (
    "face_priority",
    "notifications",
    "reports",
    "bulk_jobs",
    "maintenance",
    "dead_letter",
)


def broker_type(celery_app):
    url = getattr(getattr(celery_app, "conf", None), "broker_url", "") or ""
    return (urlsplit(url).scheme or "unknown").split("+")[0]


def queue_depths(celery_app, queue_names=QUEUE_NAMES):
    """Inspect queue depths through Kombu without exposing broker credentials."""
    depths = {}
    errors = {}
    with celery_app.connection_for_read() as connection:
        connection.ensure_connection(max_retries=1, timeout=3)
        for name in queue_names:
            channel = connection.channel()
            try:
                result = channel.queue_declare(queue=name, passive=True)
                # py-amqp returns (queue, message_count, consumer_count).
                # Other transports expose a declaration object with equivalents.
                if isinstance(result, (tuple, list)):
                    message_count = result[1]
                    consumer_count = result[2] if len(result) > 2 else None
                else:
                    message_count = getattr(result, "message_count", 0)
                    consumer_count = getattr(result, "consumer_count", None)
                depths[name] = {
                    "messages": int(message_count or 0),
                    "consumers": None if consumer_count is None else int(consumer_count),
                }
            except Exception as exc:
                # A passive declaration of a queue that has never been used can fail.
                errors[name] = type(exc).__name__
            finally:
                try:
                    channel.close()
                except Exception:
                    pass
    return depths, errors


def broker_snapshot(celery_app):
    snapshot = {
        "type": broker_type(celery_app),
        "status": "disabled" if celery_app is None else "unknown",
        "queues": {},
    }
    if celery_app is None:
        return snapshot
    try:
        snapshot["queues"], queue_errors = queue_depths(celery_app)
        snapshot["status"] = "ok"
        if queue_errors:
            snapshot["queue_errors"] = queue_errors
    except Exception as exc:
        snapshot["status"] = "error"
        snapshot["error"] = f"{type(exc).__name__}: {exc}"
    return snapshot


def update_prometheus_metrics(celery_app):
    """Refresh queue gauges on metrics scrape; failures remain observable as broker_up=0."""
    try:
        from prometheus_client import Gauge
        global _BROKER_UP, _QUEUE_MESSAGES, _QUEUE_CONSUMERS
        try:
            _BROKER_UP
        except NameError:
            _BROKER_UP = Gauge("openvision_celery_broker_up", "Whether the Celery broker is reachable")
            _QUEUE_MESSAGES = Gauge("openvision_celery_queue_messages", "Ready messages", ["queue"])
            _QUEUE_CONSUMERS = Gauge("openvision_celery_queue_consumers", "Active consumers", ["queue"])
        snapshot = broker_snapshot(celery_app)
        _BROKER_UP.set(1 if snapshot["status"] == "ok" else 0)
        for queue, values in snapshot.get("queues", {}).items():
            _QUEUE_MESSAGES.labels(queue=queue).set(values["messages"])
            if values.get("consumers") is not None:
                _QUEUE_CONSUMERS.labels(queue=queue).set(values["consumers"])
        return snapshot
    except Exception:
        return None
