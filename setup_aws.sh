#!/usr/bin/env bash
# ==============================================================================
# OpenVision AWS Master Setup Script
# ==============================================================================
# This script automates the setup of the Face Detection system on AWS Ubuntu.
# It configures RAM (Swap), installs dependencies, and launches all services.
# ==============================================================================

set -e

echo "==> [1/6] Configuring 2GB Swap File for RAM Stability..."
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

echo "==> [2/6] Updating System and Installing Dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip postgresql redis-server libgl1-mesa-glx libglib2.0-0

echo "==> [3/6] Setting Up Python Virtual Environment..."
if [ ! -d "backend/.venv" ]; then
    cd backend
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -U pip
    pip install -r requirements.txt
    cd ..
else
    echo "Virtual environment already exists."
fi

echo "==> [4/6] Configuring Environment (.env)..."
if [ ! -f "backend/.env" ]; then
    cp backend/.env.example backend/.env
    echo "Created .env from .env.example. PLEASE EDIT backend/.env with your S3 and Database credentials!"
fi

echo "==> [5/6] Initializing Database (PostgreSQL)..."
# Note: Assumes local Postgres is configured. Update DATABASE_URL in .env first.
echo "Run 'python3 backend/setup_postgres.py' after configuring your DATABASE_URL in backend/.env"

echo "==> [6/6] Launching Services..."
echo "Starting Backend API (Gunicorn)..."
cd backend
source .venv/bin/activate
nohup gunicorn -w 2 -b 0.0.0.0:5001 app:app > gunicorn.log 2>&1 &
echo $! > .gunicorn.pid

echo "Starting Celery Worker (Background Tasks)..."
nohup python3 -m celery -A celery_app worker --loglevel=info > celery_worker.log 2>&1 &
echo $! > .celery_worker.pid

echo "Starting Celery Beat (Scheduler)..."
nohup python3 -m celery -A celery_app beat --loglevel=info > celery_beat.log 2>&1 &
echo $! > .celery_beat.pid

echo ""
echo "=============================================================================="
echo "SETUP COMPLETE!"
echo "=============================================================================="
echo "- API is starting on port 5001"
echo "- Logs are in: backend/gunicorn.log"
echo "- Mobile App Sync: Already active in FaceRecognition-Android"
echo "- S3 Storage: Enabled if S3_BUCKET is set in backend/.env"
echo "=============================================================================="
echo "IMPORTANT: Don't forget to open port 5001 in your AWS Security Group!"
echo "=============================================================================="
