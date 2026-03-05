#!/bin/bash

# Default to port 10000 if PORT is not set (Render default)
# On EC2, you might set PORT=80 in .env or docker run command
PORT="${PORT:-10000}"

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

# 2. Start Backend (Gunicorn) in the background
# We bind to 127.0.0.1:5001 because Nginx will proxy to it locally
echo "Starting Gunicorn Backend..."
cd backend
# Use gunicorn_config.py to ensure eventlet workers for Socket.IO
PORT=5001 gunicorn -c gunicorn_config.py app:app --daemon

# 3. Start Nginx in the foreground (so Docker keeps running)
echo "Starting Nginx..."
nginx -g 'daemon off;'
