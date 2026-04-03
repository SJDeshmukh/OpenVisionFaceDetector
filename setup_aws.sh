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
sudo apt-get install -y python3-venv python3-pip postgresql postgresql-contrib redis-server libgl1 libglib2.0-0 nodejs npm

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

echo "==> [6/8] Generating Clean Environment (.env)..."
ENV_FILE="backend/.env"
# Create/Overwrite .env with clean values
cat <<EOF > $ENV_FILE
SECRET_KEY=$(openssl rand -base64 32)
BACKEND_URL=http://127.0.0.1:5001
FRONTEND_URL=http://localhost:5173
DB_TYPE=postgres
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME
DB_PATH=face_db.sqlite
LOW_RAM_MODE=1
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
AWS_REGION=us-east-1
EOF

echo ".env file generated successfully."

echo "==> [7/8] Initializing Database Schema..."
cd backend
source .venv/bin/activate
# Run setup_postgres.py which handles migrations
export DATABASE_URL="postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME"
export DB_TYPE="postgres"
python3 setup_postgres.py
cd ..

echo "==> [8/8] Launching UI + Backend Concurrently..."
# Kill any old processes
pkill -f gunicorn || true
pkill -f celery || true
pkill -f vite || true

export LOW_RAM_MODE=1
nohup npm run dev > app.log 2>&1 &

echo ""
echo "=============================================================================="
echo "SETUP COMPLETE! STABLE DEPLOYMENT FINISHED."
echo "=============================================================================="
echo "- Dashboard: Port 5173"
echo "- API:       Port 5001"
echo "- Logs:      tail -f app.log"
echo "- Database:  $DB_NAME (User: $DB_USER)"
echo "=============================================================================="
echo "IMPORTANT: Open ports 5173 and 5001 in your AWS Security Group!"
echo "=============================================================================="
