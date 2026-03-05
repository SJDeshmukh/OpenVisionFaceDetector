#!/usr/bin/env bash
set -euo pipefail

RED="$(printf '\033[31m')"; GREEN="$(printf '\033[32m')"; YELLOW="$(printf '\033[33m')"; BLUE="$(printf '\033[34m')"; NC="$(printf '\033[0m')"
log() { printf "%b[info]%b %s\n" "$BLUE" "$NC" "$*"; }
ok()  { printf "%b[ok]%b   %s\n" "$GREEN" "$NC" "$*"; }
warn(){ printf "%b[warn]%b %s\n" "$YELLOW" "$NC" "$*"; }
err() { printf "%b[err]%b  %s\n" "$RED" "$NC" "$*" >&2; }

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_TF_DIR="${ROOT_DIR}/infra/aws/frontend"
BACKEND_TF_DIR="${ROOT_DIR}/infra/aws/backend"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/web-dashboard"
LAMBDA_ZIP="${BACKEND_DIR}/.dist/lambda.zip"

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-}"
FUNCTION_NAME="${FUNCTION_NAME:-face-detection-api}"
BUCKET_NAME="${BUCKET_NAME:-}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -r REGION          AWS region (default: ${AWS_REGION})
  -p PROFILE         AWS CLI profile to use
  -f FUNCTION_NAME   Lambda function name (default: ${FUNCTION_NAME})
  -b BUCKET_NAME     S3 bucket for frontend (default: auto-generate)
  -h                 Show help

Environment variables can also be used:
  AWS_REGION, AWS_PROFILE, FUNCTION_NAME, BUCKET_NAME
EOF
}

while getopts ":r:p:f:b:h" opt; do
  case "${opt}" in
    r) AWS_REGION="${OPTARG}" ;;
    p) AWS_PROFILE="${OPTARG}" ;;
    f) FUNCTION_NAME="${OPTARG}" ;;
    b) BUCKET_NAME="${OPTARG}" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

AWS_ARGS=()
[ -n "${AWS_PROFILE}" ] && AWS_ARGS+=(--profile "${AWS_PROFILE}")
[ -n "${AWS_REGION}" ] && AWS_ARGS+=(--region "${AWS_REGION}")

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    err "Missing required command: $1"
    exit 1
  fi
}

log "Pre-flight checks"
require_cmd aws
require_cmd terraform
require_cmd npm
require_cmd zip
if ! command -v docker >/dev/null 2>&1; then
  err "Docker is required to build a Lambda-compatible package. Please install Docker."
  exit 1
fi
aws "${AWS_ARGS[@]}" sts get-caller-identity >/dev/null || { err "AWS CLI authentication failed"; exit 1; }
ok "Tools present and AWS credentials valid"

log "Building Lambda package"
pushd "${BACKEND_DIR}/deploy" >/dev/null
./build-lambda.sh
popd >/dev/null
[ -f "${LAMBDA_ZIP}" ] || { err "Lambda package not found at ${LAMBDA_ZIP}"; exit 1; }
ok "Lambda package created"

log "Provisioning Backend (Lambda + API Gateway)"
pushd "${BACKEND_TF_DIR}" >/dev/null
terraform init -input=false
terraform apply -auto-approve -var="aws_region=${AWS_REGION}" -var="function_name=${FUNCTION_NAME}" -var="package_path=../../backend/.dist/lambda.zip"
API_ENDPOINT="$(terraform output -raw api_endpoint)"
popd >/dev/null
[ -n "${API_ENDPOINT:-}" ] || { err "Failed to get API endpoint from Terraform outputs"; exit 1; }
ok "API Gateway endpoint: ${API_ENDPOINT}"

generate_bucket_name() {
  local suffix
  suffix="$(python3 - <<'PY'
import random,string
print(''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(10)))
PY
  )"
  echo "face-detection-web-${suffix}"
}

if [ -z "${BUCKET_NAME}" ]; then
  BUCKET_NAME="$(generate_bucket_name)"
  warn "BUCKET_NAME not provided. Using generated name: ${BUCKET_NAME}"
fi

log "Provisioning Frontend (S3 + CloudFront)"
pushd "${FRONTEND_TF_DIR}" >/dev/null
terraform init -input=false
terraform apply -auto-approve -var="aws_region=${AWS_REGION}" -var="bucket_name=${BUCKET_NAME}"
CLOUDFRONT_DOMAIN="$(terraform output -raw cloudfront_domain)"
CLOUDFRONT_DISTRIBUTION_ID="$(terraform output -raw cloudfront_distribution_id)"
popd >/dev/null
[ -n "${CLOUDFRONT_DOMAIN:-}" ] || { err "Failed to get CloudFront domain from Terraform outputs"; exit 1; }
ok "CloudFront domain: https://${CLOUDFRONT_DOMAIN}"

log "Setting Lambda env vars (FRONTEND_URL, BACKEND_URL, AWS_REGION)"
aws "${AWS_ARGS[@]}" lambda update-function-configuration \
  --function-name "${FUNCTION_NAME}" \
  --environment "Variables={FRONTEND_URL=https://${CLOUDFRONT_DOMAIN},BACKEND_URL=${API_ENDPOINT},AWS_REGION=${AWS_REGION}}" >/dev/null
ok "Lambda environment updated"

log "Building and deploying React frontend"
pushd "${FRONTEND_DIR}" >/dev/null
export VITE_API_URL="${API_ENDPOINT}"
if [ -f package-lock.json ]; then
  npm ci || npm install
else
  npm install
fi
npm run build
aws "${AWS_ARGS[@]}" s3 sync dist "s3://${BUCKET_NAME}/" --delete
aws "${AWS_ARGS[@]}" s3 cp dist/index.html "s3://${BUCKET_NAME}/index.html" --cache-control "no-cache, no-store, must-revalidate"
popd >/dev/null
ok "Frontend uploaded to S3"

log "Invalidating CloudFront cache"
aws "${AWS_ARGS[@]}" cloudfront create-invalidation --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}" --paths "/*" >/dev/null
ok "CloudFront invalidation created"

cat <<EOF
====================================
Deployment Complete
====================================
Frontend URL:  https://${CLOUDFRONT_DOMAIN}
API Base URL:  ${API_ENDPOINT}
Lambda Name:   ${FUNCTION_NAME}
S3 Bucket:     ${BUCKET_NAME}
Region:        ${AWS_REGION}

To re-run quickly:
  AWS_REGION=${AWS_REGION} FUNCTION_NAME=${FUNCTION_NAME} BUCKET_NAME=${BUCKET_NAME} \\
  $(basename "$0")
EOF
