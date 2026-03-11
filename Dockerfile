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

# Install Nginx, Redis, and system dependencies including build tools for C++ extensions
RUN apt-get update && apt-get install -y \
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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install Backend Dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt

# 2. Install Torch (CPU-only for production compatibility)
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 3. Copy & Install Local Face Detection Package (multiple_face_detection)
# We copy the local version to preserve our bugfixes (RealESRGAN, GFPGAN weights logic)
COPY multiple_face_detection ./multiple_face_detection
RUN cd multiple_face_detection/third_party/BasicSR && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd ../facexlib && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd ../GFPGAN && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd ../Real-ESRGAN && pip install --no-cache-dir -e . 2>/dev/null || true

# 4. Copy Backend Code (including standalone_live_mesh)
COPY backend/ ./backend

# 5. Install 3DDFA-V3 dependencies (for 3D mesh)
RUN pip install --no-cache-dir -r backend/standalone_live_mesh/requirements.txt

# 6. Copy Frontend Build from Stage 1
COPY --from=frontend-builder /app/frontend/dist /var/www/face-detection/web-dashboard/dist

# Copy Configs
COPY nginx.conf /etc/nginx/sites-available/default
COPY entrypoint.sh ./

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Environment Defaults
ARG APP_PORT=10000
ENV PORT=${APP_PORT}
ENV HOST=0.0.0.0
ENV CELERY_BROKER_URL=redis://127.0.0.1:6379/0
ENV CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
ENV REDIS_URL=redis://127.0.0.1:6379/0
ENV CELERY_CONCURRENCY=1
# Ensure backend comes first so `import app` resolves to backend/app.py, not multiple_face_detection/app.py
ENV PYTHONPATH=/app/backend:/app:/app/multiple_face_detection

# Optional public URL for logs (entrypoint prints it)
ARG PUBLIC_URL
ENV PUBLIC_URL=${PUBLIC_URL}

# Expose ports
EXPOSE 10000 5001

# Healthcheck for backend
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD curl -fsS http://127.0.0.1:5001/api/ping || exit 1

# Start via entrypoint
CMD ["./entrypoint.sh"]
