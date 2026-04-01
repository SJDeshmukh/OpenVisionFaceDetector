import os
import time
import re
import redis
from functools import wraps
from flask import request, jsonify

# Redis setup
redis_client = None
try:
    REDIS_URL = os.environ.get("REDIS_URL")
    if REDIS_URL:
        redis_client = redis.from_url(REDIS_URL)
except Exception:
    redis_client = None

# Prometheus metrics setup
try:
    from prometheus_client import Counter, Histogram
except ImportError:
    Counter = Histogram = None

class _DummyMetric:
    def labels(self, **kwargs): return self
    def inc(self, *args, **kwargs): pass
    def observe(self, *args, **kwargs): pass

if Counter and Histogram:
    try:
        REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["endpoint", "method", "status"])
        REQUEST_LATENCY = Histogram("http_request_latency_seconds", "Request latency", ["endpoint", "method"])
    except Exception:
        REQUEST_COUNT = _DummyMetric()
        REQUEST_LATENCY = _DummyMetric()
else:
    REQUEST_COUNT = _DummyMetric()
    REQUEST_LATENCY = _DummyMetric()

def track_metrics(endpoint):
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            start = time.time()
            resp = fn(*args, **kwargs)
            dur = time.time() - start
            try:
                status = resp[1] if isinstance(resp, tuple) else 200
            except Exception:
                status = 200
            REQUEST_COUNT.labels(endpoint=endpoint, method=request.method, status=status).inc()
            REQUEST_LATENCY.labels(endpoint=endpoint, method=request.method).observe(dur)
            return resp
        return inner
    return wrapper

def rate_limit(key_func=lambda: request.remote_addr, limit=100, window=60):
    def decorator(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if redis_client:
                key = f"rl:{key_func()}"
                try:
                    pipe = redis_client.pipeline()
                    pipe.incr(key, 1)
                    pipe.expire(key, window)
                    count, _ = pipe.execute()
                    if count and int(count) > limit:
                        return jsonify({"error": "Too Many Requests"}), 429
                except Exception:
                    pass
            return fn(*args, **kwargs)
        return inner
    return decorator

def setup_middleware(app):
    """Configures global middleware and hooks for the Flask app."""
    
    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    allowed_origins = [
        FRONTEND_URL, 
        "http://localhost:5173", 
        "http://127.0.0.1:5173",
        "https://face-detection-frontend-kepx.onrender.com",
        r"^https?://.*\.vercel\.app$",
        r"^https?://.*\.ngrok-free\.(app|dev)$",
        r"^https?://.*\.ngrok\.io$"
    ]

    @app.after_request
    def add_cors_headers(resp):
        try:
            origin = request.headers.get('Origin')
            origin_allowed = False
            if origin in allowed_origins or origin == '*':
                origin_allowed = True
            else:
                for pat in allowed_origins:
                    if isinstance(pat, str) and pat.startswith('^') and re.match(pat, origin or ''):
                        origin_allowed = True; break
            
            if origin_allowed:
                resp.headers['Access-Control-Allow-Origin'] = origin
                resp.headers['Access-Control-Allow-Credentials'] = 'true'
                resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Vendor-ID, x-vendor-id'
                resp.headers['Access-Control-Expose-Headers'] = 'Authorization'
        except Exception:
            pass
        return resp
