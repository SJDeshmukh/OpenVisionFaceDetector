#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
OUT_DIR="${BACKEND_DIR}/.dist/hybrid"
BUILD_DIR="${BACKEND_DIR}/.build/hybrid"

cleanup() {
  rm -rf "${BUILD_DIR}"
}
trap cleanup EXIT

for command_name in python3 zip; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

rm -rf "${BUILD_DIR}"
mkdir -p "${OUT_DIR}" "${BUILD_DIR}/db/lambda_workers" "${BUILD_DIR}/db/services" "${BUILD_DIR}/outbound/lambda_workers"

cp "${BACKEND_DIR}/lambda_workers/__init__.py" "${BUILD_DIR}/db/lambda_workers/"
cp "${BACKEND_DIR}/lambda_workers/worker_common.py" "${BUILD_DIR}/db/lambda_workers/"
cp "${BACKEND_DIR}/lambda_workers/db_adapter.py" "${BUILD_DIR}/db/lambda_workers/"
cp "${BACKEND_DIR}/lambda_workers/report_pipeline.py" "${BUILD_DIR}/db/lambda_workers/"
cp "${BACKEND_DIR}/lambda_workers/vpc_db_handler.py" "${BUILD_DIR}/db/lambda_workers/"

for service_file in \
  __init__.py \
  attendance_service.py \
  automated_reports_service.py \
  employee_email_reports_service.py \
  payroll_service.py \
  person_scope_service.py \
  report_filter_service.py; do
  cp "${BACKEND_DIR}/services/${service_file}" "${BUILD_DIR}/db/services/"
done

python3 -m pip install \
  --disable-pip-version-check \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  --target "${BUILD_DIR}/db" \
  psycopg2-binary==2.9.10

cp "${BACKEND_DIR}/lambda_workers/__init__.py" "${BUILD_DIR}/outbound/lambda_workers/"
cp "${BACKEND_DIR}/lambda_workers/worker_common.py" "${BUILD_DIR}/outbound/lambda_workers/"
cp "${BACKEND_DIR}/lambda_workers/outbound_email_handler.py" "${BUILD_DIR}/outbound/lambda_workers/"

rm -f "${OUT_DIR}/vpc-db-worker.zip" "${OUT_DIR}/outbound-email-worker.zip"
(cd "${BUILD_DIR}/db" && zip -qr "${OUT_DIR}/vpc-db-worker.zip" .)
(cd "${BUILD_DIR}/outbound" && zip -qr "${OUT_DIR}/outbound-email-worker.zip" .)

echo "Built ${OUT_DIR}/vpc-db-worker.zip"
echo "Built ${OUT_DIR}/outbound-email-worker.zip"
