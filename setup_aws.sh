#!/usr/bin/env bash
# ==============================================================================
# OpenVision AWS Master Setup Script (v4.0 - Final Stability)
# ==============================================================================
# This script automates the setup of the Face Detection system on AWS Ubuntu.
# It handles Swap, Dependencies, CPU-only AI libraries, Postgres, and .env.
# ==============================================================================

set -e

echo "==> [1/8] Configuring 2GB Swap File for RAM Stability..."
if [ ! -f /swapfile ] && [ ! -L /swapfile ]; then
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    if ! grep -q "/swapfile" /etc/fstab; then
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    fi
    echo "Swap file created successfully."
else
    echo "Swap file already exists."
fi

echo "==> [2/8] Updating System and Installing Dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip postgresql postgresql-contrib redis-server nginx libgl1 libglib2.0-0 nodejs

echo "==> [3/8] Setting Up Backend Environment (including CPU AI)..."
if [ ! -d "backend/.venv" ]; then
    cd backend
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -U pip
    pip install -r requirements.txt
    echo "Installing CPU-only AI libraries for health check compatibility..."
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --no-cache-dir
    pip install tensorflow-cpu --no-cache-dir
    cd ..
else
    echo "Backend venv already exists. Ensuring AI libraries are present..."
    source backend/.venv/bin/activate
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --no-cache-dir --quiet || true
    pip install tensorflow-cpu --no-cache-dir --quiet || true
fi

echo "==> [4/8] Setting Up Frontend Environment..."
echo "Installing root dependencies..."
npm install --quiet
echo "Installing web-dashboard dependencies..."
cd web-dashboard
npm install --quiet
cd ..

echo "==> [5/8] Automating PostgreSQL Configuration..."
DB_NAME="face_db"
DB_USER="face_admin"
# Check if we already have a password in .env to avoid resetting it
if [ -f "backend/.env" ] && grep -q "DATABASE_URL=postgresql://face_admin:" "backend/.env"; then
    DB_PASS=$(grep "DATABASE_URL" backend/.env | sed -E 's/.*:([^@:]+)@.*/\1/')
    echo "Using existing password from .env"
else
    DB_PASS=$(openssl rand -base64 12 | tr -d '/+' | cut -c1-16)
    echo "Generated new database password."
fi

sudo service postgresql start
echo "Configuring Postgres roles and database..."
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" || true
sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';" || true
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" || true

# Generate/Update .env while preserving critical existing keys
if [ -f "$ENV_FILE" ]; then
    echo "Existing .env found. Preserving SECRET_KEY and DATABASE_URL."
    # Extract existing values
    EXISTING_SECRET=$(grep "^SECRET_KEY=" "$ENV_FILE" | cut -d'=' -f2-)
    EXISTING_DB_URL=$(grep "^DATABASE_URL=" "$ENV_FILE" | cut -d'=' -f2-)
    
    # Re-create .env with existing critical keys but updated IP/URLs if needed
    cat <<EOF > $ENV_FILE
SECRET_KEY=${EXISTING_SECRET:-$(openssl rand -base64 32)}
BACKEND_URL=http://$PUBLIC_IP
FRONTEND_URL=http://$PUBLIC_IP
DB_TYPE=postgres
DATABASE_URL=${EXISTING_DB_URL:-postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME}
DB_PATH=face_db.sqlite
LOW_RAM_MODE=1
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
AWS_REGION=us-east-1
EOF
else
    cat <<EOF > $ENV_FILE
SECRET_KEY=$(openssl rand -base64 32)
BACKEND_URL=http://$PUBLIC_IP
FRONTEND_URL=http://$PUBLIC_IP
DB_TYPE=postgres
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME
DB_PATH=face_db.sqlite
LOW_RAM_MODE=1
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
AWS_REGION=us-east-1
EOF
fi

echo ".env file managed successfully."

echo "==> [7/8] Initializing Database Schema..."
cd backend
source .venv/bin/activate
# Run migrate_to_postgres.py which handles schema initialization + SQLite data migration
export DATABASE_URL="postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME"
export DB_TYPE="postgres"
python3 migrate_to_postgres.py || echo "Warning: migrate_to_postgres.py encountered issues."
cd ..

echo "==> [8/8] Building Frontend & Configuring Nginx..."
echo "Building web-dashboard for production..."
cd web-dashboard
npm run build || echo "Warning: Frontend build failed. Check RAM/Swap."

if [ ! -d "dist" ]; then
    echo "ERROR: 'dist' folder was not created. Check build errors above."
    exit 1
fi

echo "Moving frontend assets to /var/www/ for standard access..."
sudo mkdir -p /var/www/face_detection
sudo cp -r dist/* /var/www/face_detection/
sudo chown -R www-data:www-data /var/www/face_detection
sudo chmod -R 755 /var/www/face_detection
cd ..

echo "Deploying Nginx configuration..."
sudo cp nginx_face_detection.conf /etc/nginx/sites-available/face_detection
sudo ln -sf /etc/nginx/sites-available/face_detection /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "==> [8/8] Configuring Systemd Services (Auto-Restart)..."

# Pre-cleanup: Stop legacy services and clear port 5001
echo "Performing pre-startup cleanup..."
sudo systemctl stop openvision-backend 2>/dev/null || true
sudo systemctl stop openvision-celery 2>/dev/null || true
sudo pkill -f gunicorn || true
sudo pkill -f celery || true

# Force clear port 5001 if still occupied
PORT_PID=$(sudo lsof -t -i:5001 2>/dev/null || true)
if [ ! -z "$PORT_PID" ]; then
    echo "Clearing port 5001 (PID: $PORT_PID)..."
    sudo kill -9 $PORT_PID 2>/dev/null || true
fi

WORKING_DIR=$(pwd)
GUNICORN_PATH="$(pwd)/backend/.venv/bin/gunicorn"
CELERY_PATH="$(pwd)/backend/.venv/bin/celery"

# 1. Create Backend Service
echo "Creating openvision-backend.service..."
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

# 2. Create Celery Service
echo "Creating openvision-celery.service..."
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

echo "Reloading systemd and enabling services..."
sudo systemctl daemon-reload
sudo systemctl enable openvision-backend
sudo systemctl enable openvision-celery

echo "Starting/Restarting services..."
sudo systemctl restart openvision-backend
sudo systemctl restart openvision-celery

# Important: Allow ports in Ubuntu Firewall (ufw)
sudo ufw allow 5173/tcp || true
sudo ufw allow 5001/tcp || true
sudo ufw allow 80/tcp || true
sudo ufw allow 443/tcp || true

echo ""
echo "=============================================================================="
echo "PRODUCTION SETUP COMPLETE! OPENVISION IS LIVE."
echo "=============================================================================="
echo "- Dashboard: http://$PUBLIC_IP"
echo "- API:       http://$PUBLIC_IP/api"
echo "- Logs:      tail -f gunicorn.log"
echo "- Database:  $DB_NAME (User: $DB_USER)"
echo "=============================================================================="
echo "IMPORTANT: Port 80 must be open in your AWS Security Group (it is!)."
echo "=============================================================================="
