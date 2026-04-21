import os
import sys as _sys

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

import logging
logger = logging.getLogger(__name__)

BROKER_URL = os.environ.get("CELERY_BROKER_URL") or os.environ.get("REDIS_URL")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or BROKER_URL

def make_celery():
    if not BROKER_URL:
        print("[CELERY] No BROKER_URL found. Background tasks disabled.")
        return None
    
    print(f"[CELERY] Initializing with broker: {BROKER_URL}")
    app = Celery("face_backend", broker=BROKER_URL, backend=RESULT_BACKEND, include=["tasks"])
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
