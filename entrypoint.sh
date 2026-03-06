#!/bin/bash

# Default to port 10000 if PORT is not set (Render default)
# On EC2, you might set PORT=80 in .env or docker run command
PORT="${PORT:-10000}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-2}"

echo "Starting deployment on port $PORT..."

# 1. Update Nginx Configuration to listen on the correct PORT
# We replace 'listen 80 default_server;' with 'listen $PORT default_server;' in the default config
sed -i "s/listen 80 default_server;/listen $PORT default_server;/g" /etc/nginx/sites-available/default

# 1b. Display helpful URLs in logs
if [ -n "${PUBLIC_URL:-}" ]; then
  echo ""
  echo "PUBLIC URL (share this): ${PUBLIC_URL}"
  echo "WEBSITE: ${PUBLIC_URL}"
  echo "API (proxied): ${PUBLIC_URL}/api"
  echo "MOBILE SERVER URL: ${PUBLIC_URL}/"
  echo ""
else
  # Best-effort local hints (host may differ depending on port mapping)
  HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  HOST_IP="${HOST_IP:-127.0.0.1}"
  echo ""
  echo "LOCAL WEBSITE (via mapped port): http://localhost:${PORT}"
  echo "LOCAL API (via mapped port):    http://localhost:${PORT}/api"
  echo "DOCKER HOST IP hint:            http://${HOST_IP}:${PORT}"
  echo ""
fi

# 2. Start Redis in the background
echo "Starting Redis..."
redis-server --daemonize yes --port 6379 --loglevel warning
echo "Redis started on port 6379."

# 3. Start Backend (Gunicorn) in the background
# We bind to 127.0.0.1:5001 because Nginx will proxy to it locally
echo "Starting Gunicorn Backend..."
cd backend
# Use gunicorn_config.py to ensure eventlet workers for Socket.IO
# Run in background but stream logs to stdout/stderr
PORT=5001 gunicorn -c gunicorn_config.py app:app --access-logfile - --error-logfile - --log-level info &

# Wait for backend to be reachable before starting Celery & Nginx
echo "Waiting for backend http://127.0.0.1:5001/api/config ..."
python3 - <<'PY'
import time, urllib.request, sys
url = "http://127.0.0.1:5001/api/config"
for i in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            if r.status < 500:
                print("Backend is up")
                sys.exit(0)
    except Exception as e:
        time.sleep(0.5)
print("Backend did not start in time")
sys.exit(1)
PY

# 4. Start Celery Worker in the background
echo "Starting Celery worker (concurrency=$CELERY_CONCURRENCY)..."
celery -A celery_app worker \
  --loglevel=info \
  --concurrency=$CELERY_CONCURRENCY \
  --pool=prefork \
  -Q celery,default \
  --include tasks \
  --logfile=/dev/stdout &
echo "Celery worker started."

# 5. Start Nginx in the foreground (so Docker keeps running)
echo "Starting Nginx..."
nginx -g 'daemon off;'
