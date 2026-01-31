import os
from celery import Celery

BROKER_URL = os.environ.get("CELERY_BROKER_URL")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or os.environ.get("CELERY_BROKER_URL")

def make_celery():
    if not BROKER_URL:
        return None
    app = Celery("face_backend", broker=BROKER_URL, backend=RESULT_BACKEND)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_ignore_result=False,
    )
    return app

celery = make_celery()
