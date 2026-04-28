#!/usr/bin/env bash
# ==============================================================================
# OpenVision Master Setup Script (v5.3 - Stop Command + Reliable Port Handling)
# ==============================================================================
#
# Usage:
#   bash setup_aws.sh          — interactive full setup
#   bash setup_aws.sh stop     — gracefully stop all services and free all ports
#
# ==============================================================================
set -e

# ──────────────────────────────────────────────────────────────────────────────
# STOP COMMAND — graceful shutdown of every OpenVision service and port
# ──────────────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "stop" ]]; then
    echo "=============================================================================="
    echo "OpenVision — Stopping All Services"
    echo "=============================================================================="

    echo "  [1/4] Stopping systemd services..."
    sudo systemctl stop openvision-backend openvision-celery 2>/dev/null && echo "  openvision-backend + celery stopped." || echo "  (services were not running)"
    sudo systemctl stop nginx              2>/dev/null && echo "  nginx stopped."          || true
    sudo systemctl stop redis-server       2>/dev/null && echo "  redis stopped."          || true
    sudo systemctl stop postgresql         2>/dev/null && echo "  postgresql stopped."     || true

    echo "  [2/4] Killing any lingering process by name..."
    sudo pkill -TERM -f gunicorn  2>/dev/null && sleep 2 || true
    sudo pkill -9    -f gunicorn  2>/dev/null || true
    sudo pkill -TERM -f celery    2>/dev/null && sleep 2 || true
    sudo pkill -9    -f celery    2>/dev/null || true
    sudo pkill -9    -f "python3 app.py" 2>/dev/null || true

    echo "  [3/4] Releasing all ports..."
    for port in 80 443 5001 5432 6379 5173; do
        if sudo fuser ${port}/tcp &>/dev/null 2>&1; then
            sudo fuser -k -9 ${port}/tcp 2>/dev/null || true
            echo "  Port $port released."
        else
            echo "  Port $port already free."
        fi
    done
    sleep 1

    echo "  [4/4] Stopping Docker containers (if any)..."
    if command -v docker &>/dev/null; then
        RUNNING=$(sudo docker ps -q 2>/dev/null)
        if [ -n "$RUNNING" ]; then
            echo "$RUNNING" | xargs sudo docker stop
            echo "  Docker containers stopped."
        else
            echo "  No Docker containers running."
        fi
    fi

    echo "=============================================================================="
    echo "All OpenVision services stopped. Ports 80, 443, 5001, 5432, 6379 are free."
    echo "To restart:  sudo systemctl start openvision-backend openvision-celery nginx"
    echo "To redeploy: bash setup_aws.sh"
    echo "=============================================================================="
    exit 0
fi

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

# Set WORKING_DIR once at the top so every step can reference it
WORKING_DIR=$(pwd)

# ──────────────────────────────────────────────────────────────────────────────
# Helper: wait until a TCP port is confirmed free (up to $2 seconds)
# ──────────────────────────────────────────────────────────────────────────────
wait_port_free() {
    local port=$1
    local timeout=${2:-15}
    local elapsed=0
    while sudo ss -tlnp "sport = :${port}" 2>/dev/null | grep -q ":${port}"; do
        if [ $elapsed -ge $timeout ]; then
            echo "  WARNING: port $port still in use after ${timeout}s — forcing kill"
            sudo fuser -k -9 ${port}/tcp 2>/dev/null || true
            sleep 1
            return
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
}

echo "==> [0/8] NUCLEAR CLEANUP: Stopping and Killing All Services..."

# 1. Stop systemd services gracefully (covers old and new service name variants)
echo "Stopping systemd services..."
sudo systemctl stop openvision-backend openvision-celery face-backend 2>/dev/null || true
sudo systemctl stop nginx redis-server postgresql 2>/dev/null || true
sleep 2

# 2. Stop any Docker containers
if command -v docker &> /dev/null; then
    echo "Stopping Docker containers..."
    sudo docker ps -q | xargs -r sudo docker stop 2>/dev/null || true
fi

# 3. Deep-kill by process name (catches processes outside systemd)
echo "Killing lingering Gunicorn, Celery, and Python workers..."
sudo pkill -9 -f gunicorn 2>/dev/null || true
sudo pkill -9 -f celery   2>/dev/null || true
sudo pkill -9 -f "python3 app.py" 2>/dev/null || true
sudo pkill -9 -f "python app.py"  2>/dev/null || true
sleep 2

# 4. Force-release each port and then VERIFY it is actually free
echo "Releasing and verifying ports..."
for port in 80 443 5001 5432 6379 5173; do
    echo "  Releasing port $port..."
    sudo fuser -k -9 ${port}/tcp 2>/dev/null || true
    wait_port_free $port 10
    echo "  Port $port confirmed free."
done

# 5. Flush stale Celery queues from Redis
echo "Flushing stale Redis queues..."
sudo systemctl start redis-server 2>/dev/null || true
sleep 1
redis-cli flushdb 2>/dev/null || true
sudo journalctl --vacuum-time=1s 2>/dev/null || true

echo "Environment is now CLEAN. Ready for setup."

# ──────────────────────────────────────────────────────────────────────────────
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
sudo sysctl -w vm.swappiness=30 2>/dev/null || true
sudo sysctl -w vm.vfs_cache_pressure=50 2>/dev/null || true
grep -q 'vm.swappiness'       /etc/sysctl.conf || echo 'vm.swappiness=30'       | sudo tee -a /etc/sysctl.conf
grep -q 'vm.vfs_cache_pressure' /etc/sysctl.conf || echo 'vm.vfs_cache_pressure=50' | sudo tee -a /etc/sysctl.conf

# ──────────────────────────────────────────────────────────────────────────────
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

    sudo usermod -aG docker $USER || true

    if ! command -v docker-compose &> /dev/null; then
        sudo ln -s /usr/libexec/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose || true
    fi

    sudo docker ps -q --filter "publish=5001" | xargs sudo docker stop 2>/dev/null || true
    sudo docker compose down --remove-orphans 2>/dev/null || true
    sudo docker system prune -f --volumes || true
    sleep 2

    echo "==> [3/6] Initializing Docker Environment (.env)..."
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

    echo "==> [4/6] Building and Starting Containers..."
    sudo docker compose build api worker
    sudo docker compose up -d --scale worker=1

    echo "CONTAINERIZED DEPLOYMENT COMPLETE!"

else
    # ──────────────────────────────────────────────────────────────────────────
    # BARE-METAL SETUP (Systemd Mode)
    # ──────────────────────────────────────────────────────────────────────────

    echo "==> [2/8] Fixing Permissions and Installing System Dependencies..."
    sudo chown -R $USER:$USER "$WORKING_DIR" 2>/dev/null || true

    sudo apt-get update -y
    sudo apt-get install -y \
        python3-pip python3-venv \
        postgresql postgresql-contrib \
        redis-server \
        nginx \
        libgl1 libglib2.0-0 \
        libheif-dev \
        psmisc lsof curl \
        build-essential \
        certbot python3-certbot-nginx

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
        TOTAL_RAM=$(free -g | awk '/^Mem:/{print $2}')
        LRM=1
        if [ "$TOTAL_RAM" -ge 3 ]; then
            echo "RAM detected: ${TOTAL_RAM}GB — disabling LOW_RAM_MODE"
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
    else
        # Read LRM from existing .env for use in systemd units below
        LRM=$(grep -oP '(?<=LOW_RAM_MODE=)\d' backend/.env 2>/dev/null || echo "1")
    fi

    echo "==> [6/8] Pre-downloading AI Models..."
    mkdir -p multiple_face_detection/models/realesrgan
    mkdir -p multiple_face_detection/models/gfpgan
    mkdir -p backend/standalone_live_mesh/3DDFA-V3/assets

    echo "Running unified model downloader (skips if already present)..."
    python3 backend/download_models.py || echo "Warning: Some model downloads failed — check above for details."

    echo "==> [7/8] Building Frontend & Configuring Nginx..."

    # ── Schema migration (uses WORKING_DIR which is now correctly set) ─────────
    echo "Initializing database schema..."
    cd "$WORKING_DIR/backend"
    source .venv/bin/activate
    export PYTHONPATH="$WORKING_DIR/backend:$WORKING_DIR"
    export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/face_detection"
    export DB_TYPE="postgres"
    python3 migrate_to_postgres.py || echo "Warning: migrate_to_postgres.py encountered issues."
    cd "$WORKING_DIR"

    echo "Building web-dashboard for production..."
    cd "$WORKING_DIR/web-dashboard"
    npm install --legacy-peer-deps
    npm install react-is --legacy-peer-deps
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
    cd "$WORKING_DIR"

    echo "Deploying Nginx configuration..."
    sudo cp nginx_face_detection.conf /etc/nginx/sites-available/face_detection
    sudo ln -sf /etc/nginx/sites-available/face_detection /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl restart nginx

    echo "==> [8/9] Provisioning SSL Certificate (Let's Encrypt)..."
    # --no-redirect = certbot selection 1 (keep HTTP alongside HTTPS, no forced redirect)
    # --non-interactive + --agree-tos + --register-unsafely-without-email = fully unattended
    sudo certbot --nginx \
        -d tapinx.in \
        -d www.tapinx.in \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        --no-redirect \
        2>&1 || echo "Warning: Certbot failed — check DNS resolution for tapinx.in and re-run 'sudo certbot --nginx -d tapinx.in -d www.tapinx.in' manually."

    # Enable auto-renewal (certbot installs a systemd timer; this is a belt-and-suspenders cron)
    (crontab -l 2>/dev/null | grep -v certbot; echo "0 3 * * * sudo certbot renew --quiet --nginx") | crontab -
    echo "SSL auto-renewal cron registered (runs daily at 03:00)."

    # Allow HTTPS through firewall
    sudo ufw allow 443/tcp || true

    echo "==> [9/9] Configuring Systemd Services (Auto-Restart)..."
    GUNICORN_PATH="$WORKING_DIR/backend/.venv/bin/gunicorn"
    CELERY_PATH="$WORKING_DIR/backend/.venv/bin/celery"

    # Backend Service
    # KillMode=mixed + TimeoutStopSec: systemd kills the master with SIGTERM,
    # then sends SIGKILL to any remaining workers after 15s so the port is
    # always released before the next start attempt.
    sudo tee /etc/systemd/system/openvision-backend.service > /dev/null <<UNIT
[Unit]
Description=Gunicorn instance to serve OpenVision Face Detection
After=network.target postgresql.service redis.service

[Service]
User=$USER
Group=www-data
WorkingDirectory=$WORKING_DIR/backend
Environment="PATH=$WORKING_DIR/backend/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=$WORKING_DIR/backend:$WORKING_DIR"
Environment="LOW_RAM_MODE=$LRM"
EnvironmentFile=$WORKING_DIR/backend/.env
ExecStartPre=/bin/bash -c '/usr/bin/fuser -k -9 5001/tcp 2>/dev/null || true; /bin/sleep 1'
ExecStart=$GUNICORN_PATH --worker-class gthread -w 1 --threads 4 -b 0.0.0.0:5001 app:app --timeout 600
ExecStop=/bin/kill -s TERM \$MAINPID
KillMode=mixed
TimeoutStopSec=15
Restart=always
RestartSec=8

[Install]
WantedBy=multi-user.target
UNIT

    # Celery Worker Service
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
KillMode=mixed
TimeoutStopSec=20
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF"

    sudo systemctl daemon-reload
    sudo systemctl enable openvision-backend openvision-celery

    # Services were already stopped and ports released above — use 'start', not 'restart'
    sudo systemctl start openvision-backend openvision-celery

    # Firewall — allow HTTP (80), HTTPS (443), and direct API access (5001)
    sudo ufw allow 80/tcp   || true
    sudo ufw allow 443/tcp  || true
    sudo ufw allow 5001/tcp || true

    echo "=============================================================================="
    echo "PRODUCTION BARE-METAL SETUP COMPLETE!"
    echo "=============================================================================="
    echo "- Dashboard: https://tapinx.in"
    echo "- API:       https://tapinx.in/api"
    echo "=============================================================================="
fi
