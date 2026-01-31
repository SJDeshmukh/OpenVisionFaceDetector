#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
if [ ! -f ".env" ]; then
  cp .env.example .env
fi
echo "Backend environment is ready. Activate with: source backend/.venv/bin/activate"
