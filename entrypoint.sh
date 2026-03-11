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

# 3. Start PostgreSQL in the background if no external DATABASE_URL is provided
if [ -z "$DATABASE_URL" ]; then
  echo "No external DATABASE_URL provided. Starting internal PostgreSQL..."
  
  # Ensure the data directory exists and has correct permissions
  PGDATA="/var/lib/postgresql/data"
  mkdir -p "$PGDATA"
  chown -R postgres:postgres "$PGDATA"
  
  # Ensure the socket directory exists and has correct permissions
  mkdir -p /var/run/postgresql
  chown -R postgres:postgres /var/run/postgresql
  chmod 2775 /var/run/postgresql

  # Initialize DB if not already initialized
  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL data directory..."
    su - postgres -c "/usr/lib/postgresql/*/bin/initdb -D $PGDATA" || { echo "initdb failed"; exit 1; }
  fi
  
  # Start PG
  echo "Starting PostgreSQL..."
  # Clear old logs
  > /tmp/postgres.log
  chown postgres:postgres /tmp/postgres.log
  
  su - postgres -c "/usr/lib/postgresql/*/bin/pg_ctl -D $PGDATA -l /tmp/postgres.log start"
  
  # Wait for PG to be ready
  echo "Waiting for PostgreSQL to be ready..."
  for i in {1..30}; do
    if su - postgres -c "pg_isready" > /dev/null 2>&1; then
      echo "PostgreSQL is ready."
      break
    fi
    if [ $i -eq 30 ]; then
      echo "PostgreSQL failed to start. Logs:"
      cat /tmp/postgres.log
      exit 1
    fi
    sleep 1
  done
  
  # Create face_db if it doesn't exist
  echo "Ensuring face_db exists..."
  su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname = 'face_db'\" | grep -q 1 || psql -c \"CREATE DATABASE face_db\""
  
  # Set auto-connection URL for the backend
  export DATABASE_URL="postgresql://postgres@localhost/face_db"
  echo "DATABASE_URL auto-set to internal PostgreSQL: $DATABASE_URL"
else
  echo "Using external DATABASE_URL provided by environment: $DATABASE_URL"
fi

# 4. Pre-flight Check: Auto-Download Models
echo "Verifying and downloading AI model weights..."
python3 backend/download_models.py

# 5. Start Backend (Gunicorn) in the background
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

# 6. Start Celery Workers in the background
echo "Starting Celery workers (concurrency=$CELERY_CONCURRENCY)..."
for i in $(seq 1 "$CELERY_CONCURRENCY"); do
  C_FORCE_ROOT=1 celery -A celery_app worker \
    --loglevel=info \
    --concurrency=1 \
    --pool=solo \
    -n "worker${i}@%h" \
    -Q celery,default \
    --include tasks \
    --logfile=/dev/stdout &
done
echo "Celery workers started."

# 7. Start Nginx in the foreground (so Docker keeps running)
echo "Starting Nginx..."
nginx -g 'daemon off;'
