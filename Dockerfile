# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

# Optional build-time API base (used by Vite)
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}

COPY web-dashboard/package*.json ./
RUN npm install
COPY web-dashboard/ ./
RUN npm run build

# Stage 2: Build Backend & Runtime
FROM python:3.10-slim

# Labels for CI/CD
LABEL maintainer="OpenVision"
LABEL version="1.1"
LABEL description="Face Detection and Attendance System (Optimized)"

# Install System Dependencies (Consolidated)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    redis-server \
    postgresql \
    postgresql-contrib \
    git \
    g++ \
    make \
    cmake \
    libgl1 \
    libglib2.0-0 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install Backend Dependencies & Torch (CPU)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt && \
    pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 2. Copy Local Packages & Install local links
COPY multiple_face_detection ./multiple_face_detection
RUN cd multiple_face_detection/third_party/BasicSR && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd ../facexlib && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd ../GFPGAN && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd ../Real-ESRGAN && pip install --no-cache-dir -e . 2>/dev/null || true

# 3. Copy Backend Code & 3DDFA Requirements
COPY backend/ ./backend
RUN pip install --no-cache-dir -r backend/standalone_live_mesh/requirements.txt

# 4. PRE-DOWNLOAD AI MODELS (IMPORTANT: This caches weights in the image)
# We need to set PYTHONPATH so download_models.py can find internal modules if needed
ENV PYTHONPATH=/app/backend:/app:/app/multiple_face_detection
RUN python3 backend/download_models.py

# 5. Copy Frontend Build from Stage 1
# Ensure path matches Nginx config
RUN mkdir -p /var/www/face-detection/web-dashboard/
COPY --from=frontend-builder /app/frontend/dist /var/www/face-detection/web-dashboard/dist

# Copy Configs & Entrypoint
COPY nginx.conf /etc/nginx/sites-available/default
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Environment Defaults
ARG APP_PORT=10000
ENV PORT=${APP_PORT}
ENV HOST=0.0.0.0
ENV CELERY_BROKER_URL=redis://127.0.0.1:6379/0
ENV CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
ENV REDIS_URL=redis://127.0.0.1:6379/0
ENV CELERY_CONCURRENCY=1
ENV PYTHONUNBUFFERED=1

# Expose ports
EXPOSE 10000 5001

# Healthcheck for backend
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD curl -fsS http://127.0.0.1:5001/api/ping || exit 1

# Start via entrypoint
CMD ["./entrypoint.sh"]
