#!/usr/bin/env bash
# ==============================================================================
# OpenVision Master Setup Script (v5.1 - Containerized & Scalable)
# ==============================================================================
# This script automates the setup of the Face Detection system.
# Handles dependencies, Docker installation, OR Bare-Metal Systemd setup.
# ==============================================================================

set -e

echo "=============================================================================="
echo "Deployment Mode Selection"
echo "=============================================================================="
read -p "Do you want to use Docker for deployment? (y/n): " USE_DOCKER
echo ""

if [[ "$USE_DOCKER" =~ ^[Yy]$ ]]; then
    echo "==> Selected Mode: CONTAINERIZED (Docker)"
else
    echo "==> Selected Mode: BARE-METAL (Systemd)"
fi
echo "=============================================================================="

echo "==> [0/8] NUCLEAR CLEANUP: Stopping and Killing All Services..."
# Stop Systemd Services (cover both old and new service name variants)
echo "Stopping OpenVision services..."
sudo systemctl stop openvision-backend openvision-celery face-backend 2>/dev/null || true
sudo systemctl stop nginx redis-server postgresql 2>/dev/null || true

# Stop Docker Services (if any)
if command -v docker &> /dev/null; then
    echo "Stopping Docker containers..."
    sudo docker ps -q | xargs -r sudo docker stop || true
fi

# Deep Kill by Process Name
echo "Killing lingering Gunicorn, Celery, and Python workers..."
sudo pkill -9 -f gunicorn || true
sudo pkill -9 -f celery || true
sudo pkill -9 -f "python3 app.py" || true
sudo killall -9 gunicorn celery 2>/dev/null || true

# Force release ports (The most critical part for [Errno 98])
for port in 80 443 5001 5432 6379 5173; do
    echo "Forcefully releasing port $port..."
    sudo fuser -k -9 ${port}/tcp 2>/dev/null || true
    # Wait a moment for OS to release the socket
    sleep 0.5
done

# FRESH START: Flush Redis to clear stale Celery task queues from previous run
echo "Performing final cleanup of logs and queues..."
sudo systemctl start redis-server 2>/dev/null || true
redis-cli flushdb 2>/dev/null || true
sudo journalctl --vacuum-time=1s 2>/dev/null || true

echo "Environment is now CLEAN. Ready for setup."

echo "==> [1/8] Configuring 4GB Swap File for RAM Stability..."
if [ ! -f /swapfile ] && [ ! -L /swapfile ]; then
    sudo fallocate -l 4G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=4096
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    if ! grep -q "/swapfile" /etc/fstab; then
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    fi
else
    echo "Swap already exists, skipping creation."
fi
# Tune swap behaviour for low-RAM instances
sudo sysctl -w vm.swappiness=30 2>/dev/null || true
sudo sysctl -w vm.vfs_cache_pressure=50 2>/dev/null || true
grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=30' | sudo tee -a /etc/sysctl.conf
grep -q 'vm.vfs_cache_pressure' /etc/sysctl.conf || echo 'vm.vfs_cache_pressure=50' | sudo tee -a /etc/sysctl.conf

if [[ "$USE_DOCKER" =~ ^[Yy]$ ]]; then
    echo "==> [2/6] Installing Docker and Docker Compose..."
    if ! command -v docker &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y ca-certificates curl gnupg lsb-release
        sudo mkdir -p /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    fi

    # Add user to docker group
    sudo usermod -aG docker $USER || true

    # Ensure docker-compose command is available
    if ! command -v docker-compose &> /dev/null; then
        sudo ln -s /usr/libexec/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose || true
    fi

    # Stop and clear ports (redundant but safe)
    sudo docker ps -q --filter "publish=5001" | xargs sudo docker stop 2>/dev/null || true
    sudo docker compose down --remove-orphans 2>/dev/null || true
    sudo docker system prune -f --volumes || true
    sleep 2

    echo "==> [4/6] Initializing Docker Environment (.env)..."
    if [ ! -f "backend/.env" ]; then
        PUBLIC_IP=$(curl -s https://api.ipify.org || echo "localhost")
        cat <<EOF > backend/.env
SECRET_KEY=$(openssl rand -base64 32)
DATABASE_URL=postgresql://postgres:postgres@db:5432/face_detection
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
BACKEND_URL=http://$PUBLIC_IP:5001
FRONTEND_URL=http://$PUBLIC_IP
LOW_RAM_MODE=0
EOF
    else
        sed -i "s|localhost:5432|db:5432|g" backend/.env
        sed -i "s|127.0.0.1:6379|redis:6379|g" backend/.env
    fi

    echo "==> [5/6] Building and Starting Containers..."
    sudo docker compose build api worker
    sudo docker compose up -d --scale worker=1

    echo "CONTAINERIZED DEPLOYMENT COMPLETE!"
else
    # ─────────────────────────────────────────────────────────────────────────
    # BARE-METAL SETUP (Systemd Mode)
    # ─────────────────────────────────────────────────────────────────────────

    echo "==> [2/8] Fixing Permissions and Installing System Dependencies..."
    sudo chown -R $USER:$USER $(pwd) 2>/dev/null || true

    sudo apt-get update -y
    # libheif-dev  → needed if pillow-heif must build from source (HEIC image support)
    # libgl1 / libglib2.0-0 → OpenCV headless runtime
    # psmisc / lsof / fuser → port cleanup tools
    sudo apt-get install -y \
        python3-pip python3-venv \
        postgresql postgresql-contrib \
        redis-server \
        nginx \
        libgl1 libglib2.0-0 \
        libheif-dev \
        psmisc lsof curl \
        build-essential

    # ── Node.js 20.x ─────────────────────────────────────────────────────────
    # Required for building the React frontend. Not included in default Ubuntu.
    if ! command -v node &> /dev/null; then
        echo "Installing Node.js 20.x..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        echo "Node.js already installed: $(node --version)"
    fi

    echo "==> [3/8] Configuring Database..."
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
    sudo -u postgres psql -c "CREATE DATABASE face_detection;" 2>/dev/null || true
    sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';" || true
    sudo systemctl restart postgresql redis-server

    echo "==> [4/8] Setting up Python Virtual Environment..."
    if [ ! -d "backend/.venv" ]; then
        python3 -m venv backend/.venv
    fi
    source backend/.venv/bin/activate
    pip install --upgrade pip

    echo "Installing Python dependencies..."
    pip install -r backend/requirements.txt

    echo "==> [5/8] Managing Environment (.env)..."
    if [ ! -f "backend/.env" ]; then
        PUBLIC_IP=$(curl -s https://api.ipify.org || echo "localhost")
        # Detect RAM to intelligently set LOW_RAM_MODE
        TOTAL_RAM=$(free -g | awk '/^Mem:/{print $2}')
        LRM=1
        if [ "$TOTAL_RAM" -ge 3 ]; then
            echo "Direct RAM detected (${TOTAL_RAM}GB), disabling LOW_RAM_MODE for performance..."
            LRM=0
        fi
        cat <<EOF > backend/.env
SECRET_KEY=$(openssl rand -base64 32)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/face_detection
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
BACKEND_URL=http://$PUBLIC_IP:5001
FRONTEND_URL=http://$PUBLIC_IP
LOW_RAM_MODE=$LRM
EOF
    fi

    echo "==> [6/8] Pre-downloading AI Models..."
    # Create required directories upfront
    mkdir -p multiple_face_detection/models/realesrgan
    mkdir -p multiple_face_detection/models/gfpgan
    mkdir -p backend/standalone_live_mesh/3DDFA-V3/assets

    # Delegate all downloads to the unified downloader script.
    # It resolves paths from its own location so it works from any cwd,
    # and skips any file that already exists and is non-empty.
    echo "Running unified model downloader (skips if already present)..."
    python3 backend/download_models.py || echo "Warning: Some model downloads failed — check above for details."

    # ── [6/8] Initializing Database Schema ────────────────────────────────────
    echo "==> [6/8] Initializing Database Schema..."
    cd backend
    source .venv/bin/activate
    
    # HARDCODED PATHS: Ensure the migration can find all modules
    export PYTHONPATH="$WORKING_DIR/backend:$WORKING_DIR"
    export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/face_detection"
    export DB_TYPE="postgres"
    
    python3 migrate_to_postgres.py || echo "Warning: migrate_to_postgres.py encountered issues."
    cd ..

    echo "==> [7/8] Building Frontend & Configuring Nginx..."
    echo "Building web-dashboard for production..."
    cd web-dashboard

    # Install npm packages (required on every fresh clone / after package.json changes)
    echo "Installing npm packages..."
    npm install --legacy-peer-deps

    # react-is is a peer dependency of recharts not always auto-installed;
    # rolldown-vite fails the build if it is missing, so force it here.
    npm install react-is --legacy-peer-deps

    # Build with a memory cap so the process doesn't OOM on low-RAM instances
    echo "Running production build..."
    NODE_OPTIONS="--max-old-space-size=1024" npm run build || {
        echo "ERROR: Frontend build failed."
        exit 1
    }

    if [ ! -d "dist" ]; then
        echo "ERROR: 'dist' folder was not created. Build failed."
        exit 1
    fi

    echo "Deploying frontend assets to /var/www/face_detection..."
    sudo mkdir -p /var/www/face_detection
    sudo rm -rf /var/www/face_detection/*
    sudo cp -r dist/* /var/www/face_detection/
    sudo chown -R www-data:www-data /var/www/face_detection
    sudo chmod -R 755 /var/www/face_detection
    cd ..

    echo "Deploying Nginx configuration..."
    sudo cp nginx_face_detection.conf /etc/nginx/sites-available/face_detection
    sudo ln -sf /etc/nginx/sites-available/face_detection /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl restart nginx

    echo "==> [8/8] Configuring Systemd Services (Auto-Restart)..."
    WORKING_DIR=$(pwd)
    GUNICORN_PATH="$WORKING_DIR/backend/.venv/bin/gunicorn"
    CELERY_PATH="$WORKING_DIR/backend/.venv/bin/celery"

    # Backend Service
    sudo bash -c "cat <<EOF > /etc/systemd/system/openvision-backend.service
[Unit]
Description=Gunicorn instance to serve OpenVision Face Detection
After=network.target postgresql.service redis.service

[Service]
User=$USER
Group=www-data
WorkingDirectory=$WORKING_DIR/backend
Environment=\"PATH=$WORKING_DIR/backend/.venv/bin\"
Environment=\"PYTHONPATH=$WORKING_DIR/backend:$WORKING_DIR\"
Environment=\"LOW_RAM_MODE=$LRM\"
EnvironmentFile=$WORKING_DIR/backend/.env
ExecStart=$GUNICORN_PATH --worker-class eventlet -w 1 -b 0.0.0.0:5001 app:app --timeout 600
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

    # Celery Worker Service
    # --concurrency=2 --pool=threads : two task threads in one process, models shared (no double RAM)
    # --max-tasks-per-child=500      : occasional GC without frequent model-reload cold-starts
    # --prefetch-multiplier=1        : pick up one task at a time (fair scheduling)
    # FORCE_3D_ENGINE=1              : pre-warm 3D landmark model regardless of DB feature flag
    sudo bash -c "cat <<EOF > /etc/systemd/system/openvision-celery.service
[Unit]
Description=Celery worker for OpenVision Face Detection
After=network.target postgresql.service redis.service

[Service]
User=$USER
Group=www-data
WorkingDirectory=$WORKING_DIR/backend
Environment=\"PATH=$WORKING_DIR/backend/.venv/bin\"
Environment=\"PYTHONPATH=$WORKING_DIR/backend:$WORKING_DIR\"
Environment=\"LOW_RAM_MODE=$LRM\"
Environment=\"OMP_NUM_THREADS=1\"
Environment=\"MKL_NUM_THREADS=1\"
Environment=\"OPENBLAS_NUM_THREADS=1\"
Environment=\"FORCE_3D_ENGINE=1\"
EnvironmentFile=$WORKING_DIR/backend/.env
ExecStart=$CELERY_PATH -A celery_app worker --loglevel=info --concurrency=1 --pool=threads --max-tasks-per-child=500 --prefetch-multiplier=1 -n worker1@%h
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF"

    sudo systemctl daemon-reload
    sudo systemctl enable openvision-backend openvision-celery
    sudo systemctl restart openvision-backend openvision-celery

    # Firewall — allow HTTP (80) and direct API access (5001)
    sudo ufw allow 80/tcp || true
    sudo ufw allow 5001/tcp || true

    PUBLIC_IP=$(curl -s https://api.ipify.org || echo "YOUR_IP")
    echo "=============================================================================="
    echo "PRODUCTION BARE-METAL SETUP COMPLETE!"
    echo "=============================================================================="
    echo "- Dashboard: http://$PUBLIC_IP"
    echo "- API:       http://$PUBLIC_IP/api"
    echo "=============================================================================="
fi
