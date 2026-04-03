#!/usr/bin/env bash
# ==============================================================================
# OpenVision AWS Master Setup Script (v2.0 - Unified Launch)
# ==============================================================================
# This script automates the setup of the Face Detection system on AWS Ubuntu.
# It configures RAM (Swap), installs dependencies (Python + Node.js),
# and launches everything (Frontend + Backend) with one command.
# ==============================================================================

set -e

echo "==> [1/7] Configuring 2GB Swap File for RAM Stability..."
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

echo "==> [2/7] Updating System and Installing Dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip postgresql redis-server libgl1 libglib2.0-0 nodejs npm

echo "==> [3/7] Setting Up Backend Environment..."
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

echo "==> [4/7] Setting Up Frontend Environment..."
echo "Installing root dependencies..."
npm install
echo "Installing web-dashboard dependencies..."
cd web-dashboard
npm install
cd ..

echo "==> [5/7] Configuring Environment (.env)..."
if [ ! -f "backend/.env" ]; then
    cp backend/.env.example backend/.env
    echo "LOW_RAM_MODE=1" >> backend/.env
    echo "Created .env. PLEASE EDIT backend/.env with your S3 and Database credentials!"
fi

echo "==> [6/7] Initializing Database (PostgreSQL)..."
# Note: User must set DATABASE_URL first
echo "Reminder: Run 'python3 backend/setup_postgres.py' after configuring your DATABASE_URL in backend/.env"

echo "==> [7/7] Launching UI + Backend Concurrently..."
# We use the orchestrator but in the background
export LOW_RAM_MODE=1
nohup npm run dev > app.log 2>&1 &

echo ""
echo "=============================================================================="
echo "SETUP COMPLETE!"
echo "=============================================================================="
echo "- Everything is starting in the background."
echo "- Dashboard: Port 5173"
echo "- API:       Port 5001"
echo "- Logs:      tail -f app.log"
echo "=============================================================================="
echo "IMPORTANT: Open ports 5173 and 5001 in your AWS Security Group!"
echo "=============================================================================="
