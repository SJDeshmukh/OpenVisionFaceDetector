#!/usr/bin/env bash
# ==============================================================================
# OpenVision Master Setup Script (v5.0 - Containerized & Scalable)
# ==============================================================================
# This script automates the setup of the Face Detection system using Docker.
# Handles dependencies, Docker installation, Compose orchestration, and scaling.
# ==============================================================================

set -e

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

# Ensure docker-compose command is available (v2 uses 'docker compose' but some scripts use 'docker-compose')
if ! command -v docker-compose &> /dev/null; then
    sudo ln -s /usr/libexec/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose || true
fi

# Stop all possible legacy service names
sudo systemctl stop openvision-backend openvision-celery openvision.service gunicorn 2>/dev/null || true
sudo systemctl disable openvision-backend openvision-celery openvision.service 2>/dev/null || true

# Force kill anything on port 5001 (backend) and 6379 (redis)
sudo fuser -k 5001/tcp 2>/dev/null || true
sudo fuser -k 6379/tcp 2>/dev/null || true
sudo lsof -t -i:5001 | xargs sudo kill -9 2>/dev/null || true

# Clear stale containers and free up disk space
sudo docker compose down --remove-orphans 2>/dev/null || true
sudo docker system prune -f --volumes || true

echo "==> [4/6] Initializing Environment Configuration (.env)..."
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
    echo "Created new .env file."
else
    echo "Existing .env found. Ensuring DATABASE_URL points to 'db' container..."
    sed -i "s|localhost:5432|db:5432|g" backend/.env
    sed -i "s|127.0.0.1:6379|redis:6379|g" backend/.env
fi

echo "==> [5/6] Building and Starting Containers (Sequential to save Disk)..."
# Pull latest or build locally
sudo docker compose build api
sudo docker compose build worker

# Start core services
sudo docker compose up -d


echo "==> [6/6] Scaling Workers for Bulk Attendance (AttendX)..."
# Start with 2 workers by default, can be scaled manually later
sudo docker compose up -d --scale worker=2

echo ""
echo "=============================================================================="
echo "CONTAINERIZED DEPLOYMENT COMPLETE!"
echo "=============================================================================="
echo "- Dashboard: http://localhost:5173 (Development) or Nginx Mapping"
echo "- API:       http://localhost:5001"
echo "- Monitors:  docker compose ps"
echo "- Logs:      docker compose logs -f worker"
echo ""
echo "To scale for 30+ classes simultaneously, run:"
echo "  docker compose up -d --scale worker=30"

echo "For dynamic auto-scaling based on request load, run the monitor:"
echo "  python3 scripts/autoscale_monitor.py"
echo "=============================================================================="
