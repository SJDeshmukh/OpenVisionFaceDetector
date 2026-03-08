# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY web-dashboard/package*.json ./
RUN npm install
COPY web-dashboard/ ./
# Build with relative path base to ensure it works when served from root
RUN npm run build

# Stage 2: Build Backend & Runtime
FROM python:3.10-slim

# Install Nginx, Redis, and system dependencies including build tools for C++ extensions
RUN apt-get update && apt-get install -y \
    nginx \
    redis-server \
    git \
    g++ \
    make \
    cmake \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install Backend Dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

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
ENV PORT=10000
ENV HOST=0.0.0.0
ENV CELERY_BROKER_URL=redis://127.0.0.1:6379/0
ENV CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
ENV REDIS_URL=redis://127.0.0.1:6379/0
ENV CELERY_CONCURRENCY=1
ENV PYTHONPATH=/app:/app/multiple_face_detection:/app/backend

# Expose ports
EXPOSE 10000 5001

# Start via entrypoint
CMD ["./entrypoint.sh"]
