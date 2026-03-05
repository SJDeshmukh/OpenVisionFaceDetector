#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/.dist"
PKG_DIR="${ROOT_DIR}/.package"

rm -rf "${OUT_DIR}" "${PKG_DIR}"
mkdir -p "${OUT_DIR}" "${PKG_DIR}"

docker run --rm -v "${ROOT_DIR}":/var/task -w /var/task public.ecr.aws/lambda/python:3.11 bash -lc "
pip install -r requirements.txt -t .package &&
cp -r *.py services storage celery_app.py gunicorn_config.py .package 2>/dev/null || true &&
cd .package &&
zip -r ../.dist/lambda.zip .
"

echo "${OUT_DIR}/lambda.zip"
