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

# Install Nginx, Redis, Git, and required system dependencies
RUN apt-get update && apt-get install -y \
    nginx \
    redis-server \
    git \
    libgl1 \
    libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Backend Requirements & Install
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install face detection dependencies (torch CPU-only to save space)
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir gradio facexlib gfpgan basicsr

# Clone the multiple_face_detection package
RUN git clone --depth 1 --branch version1 \
    https://github.com/SJDeshmukh/class-attendance.git \
    /app/multiple_face_detection

# Install third_party packages from multiple_face_detection
RUN cd /app/multiple_face_detection/third_party/BasicSR && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd /app/multiple_face_detection/third_party/facexlib && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd /app/multiple_face_detection/third_party/GFPGAN && pip install --no-cache-dir -e . 2>/dev/null || true && \
    cd /app/multiple_face_detection/third_party/Real-ESRGAN && pip install --no-cache-dir -e . 2>/dev/null || true

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
ENV PYTHONPATH=/app:/app/multiple_face_detection

# Expose ports
EXPOSE 10000 5001

# Start via entrypoint
CMD ["./entrypoint.sh"]
