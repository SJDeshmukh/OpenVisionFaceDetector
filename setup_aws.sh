#!/usr/bin/env bash
# ==============================================================================
# OpenVision Master Setup Script (v5.0 - Containerized & Scalable)
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

echo "==> [0/8] Aggressive Port Cleanup (Ensuring clean state)..."
# Stop services and processes that might occupy required ports
sudo systemctl stop nginx 2>/dev/null || true
sudo systemctl stop apache2 2>/dev/null || true
sudo systemctl stop openvision-backend 2>/dev/null || true
sudo systemctl stop openvision-celery 2>/dev/null || true
sudo systemctl stop postgresql 2>/dev/null || true
sudo systemctl stop redis-server 2>/dev/null || true

# Kill any remaining gunicorn or celery workers
sudo pkill -f gunicorn || true
sudo pkill -f celery || true

# Explicitly kill processes on key ports
for port in 80 5001 5432 6379 5173 443; do
    PID=$(sudo lsof -t -i:$port 2>/dev/null || true)
    if [ ! -z "$PID" ]; then
        echo "Clearing port $port (PID: $PID)..."
        sudo kill -9 $PID 2>/dev/null || true
    fi
done

echo "System cleaned. Proceeding with setup..."

echo "==> [1/8] Configuring 2GB Swap File for RAM Stability..."
if [ ! -f /swapfile ] && [ ! -L /swapfile ]; then
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
    # BARE-METAL SETUP (Systemd Mode)
    echo "==> [2/8] Fixing Permissions and Installing Dependencies..."
    sudo chown -R $USER:$USER $(pwd) 2>/dev/null || true
    
    sudo apt-get update
    sudo apt-get install -y python3-pip python3-venv postgresql postgresql-contrib redis-server nginx libgl1 libglib2.0-0 psmisc lsof curl

    echo "==> [3/8] Configuring Database..."
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
    sudo -u postgres psql -c "CREATE DATABASE face_detection;" 2>/dev/null || true
    sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';" || true
    sudo systemctl restart postgresql redis-server

    echo "==> [4/8] Setting up Virtual Environment..."
    if [ ! -d "backend/.venv" ]; then
        python3 -m venv backend/.venv
    fi
    source backend/.venv/bin/activate
    pip install --upgrade pip
    pip install -r backend/requirements.txt
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

    echo "==> [5/8] Managing Environment (.env)..."
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

    echo "==> [6/8] Initializing Database Schema..."
    cd backend
    source .venv/bin/activate
    export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/face_detection"
    export DB_TYPE="postgres"
    python3 migrate_to_postgres.py || echo "Warning: migrate_to_postgres.py encountered issues."
    cd ..

    echo "==> [7/8] Building Frontend & Configuring Nginx..."
    echo "Building web-dashboard for production..."
    cd web-dashboard
    npm run build || echo "Warning: Frontend build failed. Check RAM/Swap."

    if [ ! -d "dist" ]; then
        echo "ERROR: 'dist' folder was not created. Build failed."
        exit 1
    fi

    echo "Moving frontend assets to /var/www/face_detection..."
    sudo mkdir -p /var/www/face_detection
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

    # Create Backend Service
    sudo bash -c "cat <<EOF > /etc/systemd/system/openvision-backend.service
[Unit]
Description=Gunicorn instance to serve OpenVision Face Detection
After=network.target postgresql.service redis.service

[Service]
User=$USER
Group=www-data
WorkingDirectory=$WORKING_DIR/backend
Environment=\"PATH=$WORKING_DIR/backend/.venv/bin\"
Environment=\"LOW_RAM_MODE=1\"
EnvironmentFile=$WORKING_DIR/backend/.env
ExecStart=$GUNICORN_PATH --worker-class eventlet -w 1 -b 0.0.0.0:5001 app:app --timeout 600
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

    # Create Celery Service
    sudo bash -c "cat <<EOF > /etc/systemd/system/openvision-celery.service
[Unit]
Description=Celery worker for OpenVision Face Detection
After=network.target postgresql.service redis.service

[Service]
User=$USER
Group=www-data
WorkingDirectory=$WORKING_DIR/backend
Environment=\"PATH=$WORKING_DIR/backend/.venv/bin\"
EnvironmentFile=$WORKING_DIR/backend/.env
ExecStart=$CELERY_PATH -A celery_app worker --loglevel=info --concurrency=1 --pool=solo
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF"

    sudo systemctl daemon-reload
    sudo systemctl enable openvision-backend openvision-celery
    sudo systemctl restart openvision-backend openvision-celery

    # Firewall setup
    sudo ufw allow 80/tcp || true
    sudo ufw allow 5001/tcp || true

    echo "=============================================================================="
    echo "PRODUCTION BARE-METAL SETUP COMPLETE!"
    echo "=============================================================================="
    echo "- Dashboard: http://$(curl -s https://api.ipify.org || echo "YOUR_IP")"
    echo "- API:       http://$(curl -s https://api.ipify.org || echo "YOUR_IP")/api"
    echo "=============================================================================="
fi
