#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/web-dashboard"
SESSION_NAME="face_detection_dev"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed. Please install tmux first."
  exit 1
fi

cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
  bash scripts/setup_env.sh
fi

cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install
fi

tmux new-session -d -s "$SESSION_NAME" -c "$BACKEND_DIR" 'bash -lc ". .venv/bin/activate 2>/dev/null || true; python app.py"'
tmux split-window -v -t "$SESSION_NAME:0" -c "$FRONTEND_DIR" 'bash -lc "npm run dev"'
tmux select-pane -t "$SESSION_NAME:0.0"
tmux attach -t "$SESSION_NAME"

