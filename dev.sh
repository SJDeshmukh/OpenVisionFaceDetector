#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/web-dashboard"

cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
  bash scripts/setup_env.sh
fi
. ".venv/bin/activate"

echo "Starting backend on http://127.0.0.1:5001 ..."
python app.py &
BACKEND_PID=$!

trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

sleep 5

cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install
fi

echo "Starting frontend on http://127.0.0.1:5173 ..."
npm run dev:vite
