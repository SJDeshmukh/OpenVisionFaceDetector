#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
OS_PKGMGR=""
if command -v apt-get >/dev/null 2>&1; then OS_PKGMGR="apt"; fi
if command -v yum >/dev/null 2>&1; then OS_PKGMGR="yum"; fi
if ! command -v python3 >/dev/null 2>&1; then
  if [ "$OS_PKGMGR" = "apt" ]; then sudo apt-get update -y && sudo apt-get install -y python3 python3-venv python3-pip || true; fi
  if [ "$OS_PKGMGR" = "yum" ]; then sudo yum install -y python3 python3-pip || true; fi
fi
PY="python3"
if ! command -v $PY >/dev/null 2>&1; then PY="python"; fi
if [ ! -d ".venv" ]; then
  $PY -m venv .venv 2>/dev/null || true
fi
if [ -x ".venv/bin/python" ]; then
  PIP=".venv/bin/pip"
  PYV=".venv/bin/python"
else
  PIP="$PY -m pip"
  PYV="$PY"
fi
$PY -m pip install --upgrade pip wheel setuptools || true
$PIP install Flask Flask-Cors numpy Pillow || true
$PIP install opencv-python || $PIP install opencv-python-headless || true
$PIP install onnxruntime || $PIP install onnxruntime-silicon || $PIP install onnxruntime-cpu || true
$PIP install mediapipe || true
if [ -f "sdk_src/requirements.txt" ]; then
  if ! $PIP install -r sdk_src/requirements.txt; then
    TMP_REQ="$(mktemp)"
    grep -v -E '^opencv-python(==.*)?$' sdk_src/requirements.txt > "$TMP_REQ" || true
    $PIP install -r "$TMP_REQ" || true
    $PIP install "opencv-python-headless>=4.8.0" || $PIP install "opencv-python>=4.8.0" || true
    rm -f "$TMP_REQ" || true
  fi
fi
mkdir -p backend/models
MINI_PATH="backend/models/minifasnet.onnx"
if [ ! -f "$MINI_PATH" ]; then
  URL1="${MINIFASNET_URL:-https://raw.githubusercontent.com/SuriAI/face-antispoof-onnx/main/models/best_model.onnx}"
  curl -fL "$URL1" -o "$MINI_PATH" || wget -O "$MINI_PATH" "$URL1" || true
fi
SF_DIR="third_party/Silent-Face-Anti-Spoofing/resources/anti_spoof_models"
if [ -d "$SF_DIR" ]; then
  if [ ! -f "$SF_DIR/2.7_80x80_MiniFASNetV2.pth" ]; then
    URL2="${SILENTFACE_PTH_URL:-https://raw.githubusercontent.com/minivision-ai/Silent-Face-Anti-Spoofing/master/resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth}"
    curl -fL "$URL2" -o "$SF_DIR/2.7_80x80_MiniFASNetV2.pth" || wget -O "$SF_DIR/2.7_80x80_MiniFASNetV2.pth" "$URL2" || true
  fi
fi
API_PORT="${API_PORT:-5001}"
FRONT_PORT="${FRONT_PORT:-8000}"
export API_PORT
if lsof -iTCP:$API_PORT -sTCP:LISTEN >/dev/null 2>&1; then kill $(lsof -t -iTCP:$API_PORT -sTCP:LISTEN) 2>/dev/null || true; fi
if lsof -iTCP:$FRONT_PORT -sTCP:LISTEN >/dev/null 2>&1; then kill $(lsof -t -iTCP:$FRONT_PORT -sTCP:LISTEN) 2>/dev/null || true; fi
nohup "$PYV" backend/api.py >/tmp/backend.log 2>&1 &
BACK_PID=$!
nohup "$PYV" -m http.server "$FRONT_PORT" --directory ui >/tmp/frontend.log 2>&1 &
FRONT_PID=$!
echo "$BACK_PID" > .backend.pid
echo "$FRONT_PID" > .frontend.pid
sleep 1
echo "BACKEND=$BACK_PID PORT=$API_PORT LOG=/tmp/backend.log"
echo "FRONTEND=$FRONT_PID PORT=$FRONT_PORT LOG=/tmp/frontend.log"
echo "Open: http://localhost:$FRONT_PORT/"
if [ -n "${NO_WAIT:-}" ]; then
  echo "NO_WAIT set; not waiting on backend process (PID $BACK_PID)"
  exit 0
fi
wait $BACK_PID
