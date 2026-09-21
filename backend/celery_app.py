import os
import sys as _sys
import logging
from urllib.parse import urlsplit, urlunsplit

# Ensure project root (parent of backend/) is importable so multiple_face_detection can be found
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in (_BACKEND_DIR, _PROJECT_ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# Load .env so the worker process also sees REDIS_URL / DATABASE_URL
try:
    from dotenv import load_dotenv as _ld
    _ld()
except Exception:
    pass

from celery import Celery
from kombu import Exchange, Queue

logger = logging.getLogger(__name__)

def _broker_type(url):
    return (urlsplit(url).scheme or "unknown").split("+")[0] if url else "disabled"


def _safe_url(url):
    """Return a log-safe URL; broker credentials must never appear in logs."""
    if not url:
        return "disabled"
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    if parts.username:
        host = f"{parts.username}:***@{host}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


REDIS_URL = os.environ.get("REDIS_URL")
BROKER_URL = os.environ.get("CELERY_BROKER_URL") or REDIS_URL
# AMQP is the message broker, while Redis remains the result store and cache.
# Existing Redis-only deployments retain their previous behavior.
BROKER_TYPE = _broker_type(BROKER_URL)
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL
if not RESULT_BACKEND and BROKER_TYPE not in {"amqp", "pyamqp"}:
    RESULT_BACKEND = BROKER_URL
if BROKER_TYPE in {"amqp", "pyamqp"} and not RESULT_BACKEND:
    raise RuntimeError("RabbitMQ requires CELERY_RESULT_BACKEND or REDIS_URL; AMQP is not used as a result store")

TASK_EXCHANGE = Exchange("openvision.tasks", type="direct", durable=True)
DEAD_EXCHANGE = Exchange("openvision.dead", type="fanout", durable=True)
QUEUE_NAMES = ("face_priority", "notifications", "reports", "bulk_jobs", "maintenance")


def _task_queue(name):
    arguments = None
    if BROKER_TYPE in {"amqp", "pyamqp"}:
        arguments = {
            "x-dead-letter-exchange": DEAD_EXCHANGE.name,
            "x-dead-letter-routing-key": name,
        }
        if name == "face_priority":
            arguments["x-max-priority"] = 10
    return Queue(
        name, TASK_EXCHANGE, routing_key=name, durable=True,
        queue_arguments=arguments,
    )


TASK_QUEUES = tuple(_task_queue(name) for name in QUEUE_NAMES) + (
    Queue("dead_letter", DEAD_EXCHANGE, durable=True),
)

TASK_ROUTES = {
    "tasks.detect_faces": {"queue": "face_priority", "routing_key": "face_priority"},
    "tasks.search_embedding": {"queue": "face_priority", "routing_key": "face_priority"},
    "tasks.process_class_batch_items": {"queue": "face_priority", "routing_key": "face_priority"},
    "tasks.refresh_class_batch_items": {"queue": "face_priority", "routing_key": "face_priority"},
    "tasks.process_registration_batch_items": {"queue": "face_priority", "routing_key": "face_priority"},
    "tasks.send_advance_notification": {"queue": "notifications", "routing_key": "notifications"},
    "tasks.deliver_parent_notification": {"queue": "notifications", "routing_key": "notifications"},
    "tasks.process_hostel_attendance_alerts": {"queue": "notifications", "routing_key": "notifications"},
    "tasks.send_employee_monthly_reports": {"queue": "reports", "routing_key": "reports"},
    "tasks.dispatch_automated_reports": {"queue": "reports", "routing_key": "reports"},
    "tasks.send_automated_report": {"queue": "reports", "routing_key": "reports"},
    "tasks.process_import_employees": {"queue": "bulk_jobs", "routing_key": "bulk_jobs"},
    "tasks.bulk_vendor_action": {"queue": "bulk_jobs", "routing_key": "bulk_jobs"},
    "tasks.process_vendor_creation": {"queue": "maintenance", "routing_key": "maintenance"},
    "tasks.process_delete_vendor": {"queue": "maintenance", "routing_key": "maintenance"},
    # This must execute in the dedicated face worker, which owns the resident
    # detector/embedder memory. The I/O worker deliberately never preloads it.
    "tasks.reconcile_optional_models": {"queue": "face_priority", "routing_key": "face_priority"},
}

def make_celery():
    if not BROKER_URL:
        logger.warning("[CELERY] No broker configured; background tasks are disabled")
        return None

    logger.info(
        "[CELERY] broker=%s result_backend=%s",
        _safe_url(BROKER_URL), _safe_url(RESULT_BACKEND),
    )
    # Explicitly include 'tasks' so workers register the background functions
    app = Celery("face_backend", broker=BROKER_URL, backend=RESULT_BACKEND, include=['tasks'])
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_ignore_result=False,
        result_expires=int(os.environ.get("CELERY_RESULT_EXPIRES", "86400")),
        task_default_queue="maintenance",
        task_default_exchange=TASK_EXCHANGE.name,
        task_default_exchange_type="direct",
        task_default_routing_key="maintenance",
        task_queues=TASK_QUEUES,
        task_routes=TASK_ROUTES,
        task_default_delivery_mode="persistent",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry=True,
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=None,
        broker_heartbeat=int(os.environ.get("CELERY_BROKER_HEARTBEAT", "30")),
        broker_pool_limit=int(os.environ.get("CELERY_BROKER_POOL_LIMIT", "10")),
        broker_transport_options={"confirm_publish": True} if BROKER_TYPE in {"amqp", "pyamqp"} else {},
        beat_schedule={
            "dispatch-automated-reports-every-minute": {
                "task": "tasks.dispatch_automated_reports",
                "schedule": 60.0,
                "options": {"queue": "reports", "routing_key": "reports"},
            },
            "process-hostel-attendance-alerts-every-minute": {
                "task": "tasks.process_hostel_attendance_alerts",
                "schedule": 60.0,
                "options": {"queue": "notifications", "routing_key": "notifications"},
            },
        },
    )
    return app

celery = make_celery()
