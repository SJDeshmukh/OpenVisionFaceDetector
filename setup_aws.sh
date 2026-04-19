#!/usr/bin/env bash
# ==============================================================================
# OpenVision Master Setup Script (v5.0 - Containerized & Scalable)
# ==============================================================================
# This script automates the setup of the Face Detection system using Docker.
# Handles dependencies, Docker installation, Compose orchestration, and scaling.
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
    echo "==> Selected Mode: BARE-METAL (Normal)"
fi
echo "=============================================================================="

# Shared steps (Swap)
echo "==> [0/6] Checking Disk Space..."
AVAILABLE_DISK=$(df / | tail -1 | awk '{print $4}')
if [ "$AVAILABLE_DISK" -lt 5000000 ]; then
    echo "WARNING: Less than 5GB of disk space available ($((AVAILABLE_DISK/1024)) MB)."
    echo "This build may fail. Consider increasing your AWS EBS volume to at least 40GB."
fi

echo "==> [1/6] Configuring Swap File for Build Stability..."
if [ ! -f /swapfile ]; then
    echo "Creating 2GB swap..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    if ! grep -q "/swapfile" /etc/fstab; then
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    fi
else
    echo "Swap already exists, skipping creation."
fi


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

    # Stop and clear ports
    sudo systemctl stop openvision-backend openvision-celery openvision.service gunicorn nginx 2>/dev/null || true
    sudo docker ps -q --filter "publish=5001" | xargs sudo docker stop 2>/dev/null || true
    sudo fuser -k 5001/tcp 6379/tcp 2>/dev/null || true
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
LOW_RAM_MODE=1
EOF
    else
        sed -i "s|localhost:5432|db:5432|g" backend/.env
        sed -i "s|127.0.0.1:6379|redis:6379|g" backend/.env
    fi

    echo "==> [5/6] Building and Starting Containers..."
    sudo docker compose build api worker
    sudo docker compose up -d --scale worker=2

    echo "CONTAINERIZED DEPLOYMENT COMPLETE!"
else
    # BARE-METAL SETUP (Normal Mode)
    echo "==> [2/6] Installing Local Dependencies (Postgres, Redis, Python)..."
    sudo apt-get update
    sudo apt-get install -y python3-pip python3-venv postgresql postgresql-contrib redis-server nginx libgl1 libglib2.0-0 psmisc lsof

    echo "==> [3/6] Configuring Database..."
    sudo -u postgres psql -c "CREATE DATABASE face_detection;" 2>/dev/null || true
    sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';" || true

    echo "==> [4/6] Setting up Virtual Environment & Dependencies..."
    python3 -m venv backend/.venv
    source backend/.venv/bin/activate
    pip install --upgrade pip
    pip install -r backend/requirements.txt
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

    if [ ! -f "backend/.env" ]; then
        PUBLIC_IP=$(curl -s https://api.ipify.org || echo "localhost")
        cat <<EOF > backend/.env
SECRET_KEY=$(openssl rand -base64 32)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/face_detection
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
BACKEND_URL=http://$PUBLIC_IP:5001
FRONTEND_URL=http://$PUBLIC_IP
LOW_RAM_MODE=1
EOF
    fi

    echo "==> [5/6] Starting Services (Bare-Metal)..."
    # Kill any process on 5001
    sudo fuser -k 5001/tcp 2>/dev/null || true
    
    # Ensure logs have correct permissions
    touch backend.log celery.log
    sudo chown $USER:$USER backend.log celery.log
    
    # Start Backend using venv python
    nohup backend/.venv/bin/python3 backend/app.py > backend.log 2>&1 &
    # Start Celery using venv celery
    nohup backend/.venv/bin/celery -A tasks worker --loglevel=info > celery.log 2>&1 &
    
    echo "BARE-METAL DEPLOYMENT STARTED!"
    echo "Logs available in backend.log and celery.log"
fi
