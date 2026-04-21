#!/usr/bin/env bash
# Unified Development Orchestrator for OpenVision Face Detector
set -e

# --- Configuration ---
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/web-dashboard"

echo "🚀 Starting Unified Development Orchestrator..."

# --- 1. PostgreSQL + Redis Activation (Mac) ---
if [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew >/dev/null 2>&1; then
        echo "🐘 Checking PostgreSQL status..."
        if ! brew services list | grep -q "postgresql.*started"; then
            echo "🐘 Starting PostgreSQL via Homebrew..."
            brew services start postgresql || echo "⚠️ Failed to start PostgreSQL via brew. Please ensure it is running manually."
        else
            echo "🐘 PostgreSQL is already running."
        fi

        echo "🔴 Checking Redis status..."
        if ! brew services list | grep -q "redis.*started"; then
            echo "🔴 Starting Redis via Homebrew..."
            brew services start redis || echo "⚠️ Failed to start Redis via brew. Celery tasks will fall back to threads."
        else
            echo "🔴 Redis is already running."
        fi
    fi
fi

# --- 2. Environment & Dependency Checks ---
echo "🛠️ Verifying environments..."

# Backend Setup
cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
    echo "🐍 Creating Python virtual environment..."
    bash scripts/setup_env.sh
fi
source .venv/bin/activate

echo "📦 Verifying Backend requirements..."
pip install -r requirements.txt --quiet

echo "🧠 Verifying AI Models..."
python download_models.py

# Frontend Setup
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
    echo "📦 Installing Frontend dependencies..."
    npm install
fi

if [ "$1" == "--setup-only" ]; then
    echo "✅ Setup complete!"
    exit 0
fi

# --- 3. Start Concurrent Services ---
echo "📡 Starting Services Concurrently..."
cd "$ROOT_DIR"

# Ensure concurrently is available, otherwise run via npx
if ! command -v concurrently >/dev/null 2>&1; then
    echo "⬇️ Installing concurrency tool..."
    npm install --no-save concurrently
fi

npx concurrently \
  --kill-others \
  --prefix "[{name}]" \
  --names "BACKEND,CELERY,FRONTEND" \
  --prefix-colors "blue,yellow,green" \
  "cd backend && source .venv/bin/activate && python app.py" \
  "cd backend && source .venv/bin/activate && celery -A celery_app worker --loglevel=info --pool=solo --concurrency=1 --include tasks" \
  "cd web-dashboard && npm run dev"
