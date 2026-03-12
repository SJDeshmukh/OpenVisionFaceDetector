#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

API_PORT="${API_PORT:-5001}"
FRONT_PORT="${FRONT_PORT:-8000}"
MOBILE="${MOBILE:-1}"

echo "==> Starting backend and web UI (ports: API=$API_PORT, UI=$FRONT_PORT)"
NO_WAIT=1 bash ./run_webapp.sh

sleep 2
if [ -f ".backend.pid" ]; then echo "Backend PID: $(cat .backend.pid)"; fi
if [ -f ".frontend.pid" ]; then echo "Frontend PID: $(cat .frontend.pid)"; fi
echo "Web UI:   http://localhost:${FRONT_PORT}/"
echo "Backend:  http://localhost:${API_PORT}/"

if [ "${MOBILE}" = "1" ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "==> Starting mobile app (Expo) in mobile-expo/"
    pushd mobile-expo >/dev/null
      if [ ! -d "node_modules" ]; then
        echo "Installing mobile dependencies..."
        (npm ci || npm install)
      fi
      npx expo start --non-interactive --clear >/tmp/expo.log 2>&1 &
      echo $! > .expo.pid
      echo "Expo dev server started (PID $(cat .expo.pid))."
      echo "Open another terminal and run: (cd mobile-expo && npx expo start) to view QR/Logs"
    popd >/dev/null
  else
    echo "Skipping mobile app (npm not found). Set MOBILE=0 to suppress this message."
  fi
else
  echo "Skipping mobile app startup (MOBILE=${MOBILE})."
fi

echo ""
echo "==> All services started."
echo "- Web UI:   http://localhost:${FRONT_PORT}/"
echo "- Backend:  http://localhost:${API_PORT}/"
echo "- Expo log: /tmp/expo.log (if started)"
echo ""
echo "To stop:"
echo "  pkill -f 'backend/api.py' || true"
echo "  if [ -f .frontend.pid ]; then kill \"$(cat .frontend.pid)\" 2>/dev/null || true; fi"
echo "  (cd mobile-expo && [ -f .expo.pid ] && kill \"$(cat .expo.pid)\" 2>/dev/null || true)"

