# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY web-dashboard/package*.json ./
RUN npm install
COPY web-dashboard/ ./
# Build with relative path base to ensure it works when served from root
RUN npm run build

# Stage 2: Build Backend & Runtime
FROM python:3.9-slim

# Install Nginx, Redis, and required system dependencies
RUN apt-get update && apt-get install -y \
    nginx \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Backend Requirements & Install
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy Backend Code
COPY backend/ ./backend

# Copy Frontend Build from Stage 1
# We place it where nginx.conf expects it: /var/www/face-detection/web-dashboard/dist
COPY --from=frontend-builder /app/frontend/dist /var/www/face-detection/web-dashboard/dist

# Copy Configs
COPY nginx.conf /etc/nginx/sites-available/default
COPY entrypoint.sh ./

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Environment Defaults
ENV PORT=10000
ENV HOST=0.0.0.0
ENV CELERY_BROKER_URL=redis://127.0.0.1:6379/0
ENV CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
ENV REDIS_URL=redis://127.0.0.1:6379/0
ENV CELERY_CONCURRENCY=1

# Expose ports
EXPOSE 10000 5001

# Start via entrypoint
CMD ["./entrypoint.sh"]
