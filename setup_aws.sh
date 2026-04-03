#!/usr/bin/env bash
# ==============================================================================
# OpenVision AWS Master Setup Script (v3.0 - Full Auto-Postgres)
# ==============================================================================
# This script automates the setup of the Face Detection system on AWS Ubuntu.
# It configures RAM (Swap), installs dependencies, sets up PostgreSQL,
# and launches everything (Frontend + Backend) with one command.
# ==============================================================================

set -e

echo "==> [1/8] Configuring 2GB Swap File for RAM Stability..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "Swap file created successfully."
else
    echo "Swap file already exists."
fi

echo "==> [2/8] Updating System and Installing Dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip postgresql redis-server libgl1 libglib2.0-0 nodejs npm

echo "==> [3/8] Setting Up Backend Environment..."
if [ ! -d "backend/.venv" ]; then
    cd backend
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -U pip
    pip install -r requirements.txt
    cd ..
else
    echo "Backend venv already exists."
fi

echo "==> [4/8] Setting Up Frontend Environment..."
echo "Installing root dependencies..."
npm install
echo "Installing web-dashboard dependencies..."
cd web-dashboard
npm install
cd ..

echo "==> [5/8] Automating PostgreSQL Configuration..."
DB_NAME="face_db"
DB_USER="face_admin"
DB_PASS=$(openssl rand -base64 12 | tr -d '/+' | cut -c1-16)

# Start postgres if not running
sudo service postgresql start

echo "Creating database and user..."
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" || true
sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

echo "PostgreSQL setup complete. User: $DB_USER, DB: $DB_NAME"

echo "==> [6/8] Configuring Environment (.env)..."
if [ ! -f "backend/.env" ]; then
    cp backend/.env.example backend/.env
fi

# Update .env with new DB credentials
sed -i "s|^DB_TYPE=.*|DB_TYPE=postgres|" backend/.env
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME|" backend/.env

if ! grep -q "LOW_RAM_MODE" backend/.env; then
    echo "LOW_RAM_MODE=1" >> backend/.env
fi

echo "==> [7/8] Initializing Database Schema..."
cd backend
source .venv/bin/activate
python3 setup_postgres.py || echo "Warning: setup_postgres.py skipped or failed, ensure tables exist."
cd ..

echo "==> [8/8] Launching UI + Backend Concurrently..."
export LOW_RAM_MODE=1
nohup npm run dev > app.log 2>&1 &

echo ""
echo "=============================================================================="
echo "SETUP COMPLETE! ALL-IN-ONE AUTOMATION FINISHED."
echo "=============================================================================="
echo "- Everything is starting in the background."
echo "- Dashboard: Port 5173"
echo "- API:       Port 5001"
echo "- Logs:      tail -f app.log"
echo "- Database:  $DB_NAME (User: $DB_USER)"
echo "=============================================================================="
echo "IMPORTANT: Open ports 5173 and 5001 in your AWS Security Group!"
echo "=============================================================================="
