#!/bin/bash

# Default to port 10000 if PORT is not set (Render default)
# On EC2, you might set PORT=80 in .env or docker run command
PORT="${PORT:-10000}"

echo "Starting deployment on port $PORT..."

# 1. Update Nginx Configuration to listen on the correct PORT
# We replace 'listen 80 default_server;' with 'listen $PORT default_server;' in the default config
sed -i "s/listen 80 default_server;/listen $PORT default_server;/g" /etc/nginx/sites-available/default

# 2. Start Backend (Gunicorn) in the background
# We bind to 127.0.0.1:5001 because Nginx will proxy to it locally
echo "Starting Gunicorn Backend..."
cd backend
gunicorn app:app --bind 127.0.0.1:5001 --daemon

# 3. Start Nginx in the foreground (so Docker keeps running)
echo "Starting Nginx..."
nginx -g 'daemon off;'
