import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
import sys
import base64
import json
import sqlite3
import threading
import time
import psutil
import glob
import shutil
from dotenv import load_dotenv

# --- Basic Path Setup ---
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# Also add project root if needed for packages like multiple_face_detection
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv()

# --- Internal Imports (Now safe since paths are set) ---
from utils import (
    LOW_RAM_MODE, DET_MAX_SIDE_DEFAULT, USE_FAISS, _faiss, _FAISS_LOCK, 
    _VENDOR_EMB_CACHE, get_db_connection, 
    _run, postgres_available, DATABASE_URL,
    log_audit, ensure_audit_logs_table, vendor_has_feature, 
    _ensure_class_batch_tables, _now_ts, check_vendor_status,
    BUNDLE_FEATURES, ALL_FEATURES, REGISTRATION_TEMPLATES
)
import db_factory
DB_TYPE = db_factory.DB_TYPE
from db_factory import get_table_columns
from services.attendance_service import calculate_daily_hours, calculate_arrival_status, calculate_expected_hours
from services.face_service import (
    _detect_faces_from_bytes, _ensure_vendor_emb_cache, _suggest_from_cache, 
    _extract_structural_vector, _decode_data_uri_to_rgb, _normalize_vec
)

# --- Standard Library & Framework Imports ---
from flask import Flask, Blueprint, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, leave_room
import cv2
import numpy as np

# --- 3D STRUCTURAL INTEGRATION ---
import sys
_mesh_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standalone_live_mesh")
if _mesh_dir not in sys.path:
    sys.path.append(_mesh_dir)

try:
    from standalone_live_mesh.inference import get_realtime_engine
except ImportError as e:
    print(f"[3DDFA] import error: {e}", flush=True)
    def get_realtime_engine(): return None
except Exception as e:
    print(f"[3DDFA] other error: {e}", flush=True)
    def get_realtime_engine(): return None

# ----------------------------------

import sys as _sys
# Ensure project root is importable so `multiple_face_detection` can be imported as a package
try:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _BASE_DIR not in _sys.path:
        _sys.path.insert(0, _BASE_DIR)
except Exception:
    pass
try:
    from flask_compress import Compress
except Exception:
    class Compress:
        def __init__(self, *args, **kwargs): pass
try:
    import eventlet
    import eventlet.tpool
except Exception:
    eventlet = None

def _run_in_native_thread(fn, *args, **kwargs):
    """Run a function in a native OS thread so it doesn't block the eventlet event loop.
    Falls back to direct execution if eventlet is not available."""
    if eventlet:
        try:
            def _worker():
                try:
                    eventlet.tpool.execute(fn, *args, **kwargs)
                except Exception as ex:
                    pass # print(f"tpool execution failed for {fn.__name__}: {ex}")
            eventlet.spawn_n(_worker)
        except Exception:
            fn(*args, **kwargs)
    else:
        fn(*args, **kwargs)
from services.llm_service import generate_greeting
import uuid
import time
try:
    import redis
except Exception:
    redis = None
# Reduce native thread usage to avoid OpenMP mutex init failures on small instances
try:
    import cv2 as _cv2_i
    try:
        _cv2_i.setNumThreads(int(os.environ.get("OPENCV_NUM_THREADS", "1") or "1"))
    except Exception:
        pass
except Exception:
    pass
try:
    from threadpoolctl import threadpool_limits as _tpl_limits
    _tpl_limits(limits=int(os.environ.get("BLAS_NUM_THREADS", "1") or "1"))
except Exception:
    pass
try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
except Exception:
    class _DummyMetric:
        def labels(self, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
    Counter = Histogram = None
    def generate_latest(*args, **kwargs): return b""
    CONTENT_TYPE_LATEST = "text/plain"
from functools import wraps
from storage import upload_base64_image, presigned_url_for_key, OBJECT_STORAGE_ENABLED
from werkzeug.security import generate_password_hash, check_password_hash
try:
    from celery_app import celery
except Exception:
    celery = None
from datetime import datetime, timedelta
from collections import defaultdict
from datetime import date
from functools import wraps
from itsdangerous import URLSafeTimedSerializer
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None
    class RealDictCursor: pass

from socket_handlers import register_socket_handlers, start_socket_background_tasks, latest_frames
from background_tasks import start_background_tasks, start_archival_thread
from database.bootstrap import bootstrap_db
from middleware.handlers import setup_middleware, track_metrics, rate_limit
# from config import BASE_URL, FRONTEND_URL # Removed config.py per user request

from db_factory import init_db_sqlalchemy
app = Flask(__name__) 
init_db_sqlalchemy(app)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_change_this_in_prod')
serializer = URLSafeTimedSerializer(app.secret_key)
Compress(app)

load_dotenv()
# Configuration (Simplified for Render)
# Priority: Env Var > Default
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:5001")
BASE_URL = BACKEND_URL # Alias for compatibility
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

try:
    if _faiss is not None:
        _FAISS_THREADS = int(os.environ.get("FAISS_NUM_THREADS", "1") or "1")
        try:
            _faiss.omp_set_num_threads(_FAISS_THREADS)
        except Exception:
            try:
                _faiss.set_num_threads(_FAISS_THREADS)
            except Exception:
                pass
except Exception:
    pass
try:
    # Reduce OpenCV internal threads to stabilize on small instances
    cv2.setNumThreads(int(os.environ.get("OPENCV_NUM_THREADS", "1") or "1"))
except Exception:
    pass

def is_testing():
    try:
        import os as _os
        return bool(app.config.get('TESTING')) or bool(_os.environ.get('PYTEST_CURRENT_TEST'))
    except Exception:
        return False

# CORS and Middleware setup moved to middleware/handlers.py
setup_middleware(app)

# Initialize SocketIO
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25,
    allow_upgrades=True
)

@app.route('/socket.io/', methods=['OPTIONS'])
def socketio_preflight():
    return ('', 200)

@app.route("/metrics")
def metrics():
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
    except ImportError:
        return jsonify({"error": "metrics not available"}), 501

@app.route("/api/health")
def health_check():
    try:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        # Get DB Pool stats
        pool_stats = {}
        try:
            from db_factory import get_pg_pool
            pool = get_pg_pool()
            if pool:
                pool_stats = {
                    "type": "postgres",
                    "minconn": pool.minconn,
                    "maxconn": pool.maxconn,
                    "used": len(pool._used) if hasattr(pool, "_used") else "unknown"
                }
            else:
                pool_stats = {"type": "sqlite/no-pool"}
        except Exception:
            pool_stats = {"error": "failed to get pool stats"}

        # Get Cache stats
        from utils import CACHE, _VENDOR_EMB_CACHE
        cache_stats = {
            "general_cache_size": len(CACHE),
            "emb_cache_size": len(_VENDOR_EMB_CACHE)
        }

        return jsonify({
            "status": "healthy",
            "uptime_seconds": time.time() - getattr(app, "_start_time", time.time()),
            "memory": {
                "rss_mb": mem_info.rss / (1024 * 1024),
                "vms_mb": mem_info.vms / (1024 * 1024),
                "percent": psutil.virtual_memory().percent
            },
            "db_pool": pool_stats,
            "cache": cache_stats,
            "cpu_percent": psutil.cpu_percent()
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# Background tasks started via modular functions
start_background_tasks(app)
# Socket.IO handlers moved to socket_handlers.py
register_socket_handlers(socketio)

# reset_sequence moved to utils.py

# Ensure database is always accessed from the same location (backend directory)
# Database utilities imported from utils

# Database schema initialization and bootstrap
# We run this on import so it executes under Gunicorn/Docker workers
try:
    bootstrap_db()
except Exception as e:
    print(f"Database bootstrap failed: {e}", flush=True)

# Ghost code and redundant functions removed.
# Database and Auth logic moved to modular files.


# require_feature moved to utils.py


greeting_bp = Blueprint("greeting", __name__, url_prefix="/api")




@greeting_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "message": "Server is running"})





# --- Socket and Task Initialization ---
# Socket background tasks moved to socket_handlers.py
start_socket_background_tasks(socketio)


# --- Blueprint Setup ---

app.register_blueprint(greeting_bp)

from routes.public import public_bp
app.register_blueprint(public_bp, url_prefix='/api/public')

# Legacy route for /api/config (used by some clients)
@app.route('/api/config', methods=['GET'])
def legacy_config():
    from routes.public import get_config
    return get_config()

from routes.auth import auth_bp
app.register_blueprint(auth_bp, url_prefix='/api')

from routes.admin import admin_bp
app.register_blueprint(admin_bp, url_prefix='/api/admin')

from routes.faces import faces_bp
app.register_blueprint(faces_bp, url_prefix='/api')

from routes.vendor import vendor_bp
app.register_blueprint(vendor_bp, url_prefix='/api')

from routes.attendance_class import attendance_class_bp
app.register_blueprint(attendance_class_bp, url_prefix='/api')

from routes.attendance_reports import attendance_reports_bp
from routes.attendance_core import attendance_core_bp
from middleware.error_handlers import register_error_handlers
app.register_blueprint(attendance_reports_bp, url_prefix='/api')
app.register_blueprint(attendance_core_bp, url_prefix='/api')

from routes.streaming import streaming_bp
app.register_blueprint(streaming_bp, url_prefix='/api')

from routes.tasks import tasks_bp
app.register_blueprint(tasks_bp, url_prefix='/api')

from routes.leave_routes import leave_bp
app.register_blueprint(leave_bp, url_prefix='/api/leave')

from routes.bulk_attendance import bulk_attendance_bp
app.register_blueprint(bulk_attendance_bp, url_prefix='/api')

from routes.parent_reset import parent_reset_bp
app.register_blueprint(parent_reset_bp, url_prefix='/api')

from routes.owner import owner_bp
app.register_blueprint(owner_bp, url_prefix='/api')

register_error_handlers(app)

# --- Serve Frontend (SPA) ---
@app.route("/", defaults={'path': ''})
@app.route("/<path:path>")
def serve_frontend(path):
    # Prevent shadowing API/Socket.io routes
    if path.startswith("api/") or path.startswith("socket.io/") or path.startswith("metrics"):
        return abort(404)
        
    static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "../web-dashboard/dist"))
    
    if path != "" and os.path.exists(os.path.join(static_folder, path)):
        return send_from_directory(static_folder, path)
    
    # Fallback to index.html for SPA routing
    return send_from_directory(static_folder, 'index.html')

if __name__ == "__main__":
    start_archival_thread()
    debug_flag = os.environ.get("FLASK_DEBUG") or os.environ.get("DEBUG") or ""
    debug = str(debug_flag).lower() in ("1", "true", "yes", "on")
    port = int(os.environ.get("PORT", "5001"))
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, use_reloader=False)
