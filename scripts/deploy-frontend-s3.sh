#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/web-dashboard"
DIST_DIR="${FRONTEND_DIR}/dist"

AWS_REGION="${AWS_REGION:-us-east-1}"
FRONTEND_BUCKET="${FRONTEND_BUCKET:-tapinx-web-portal-532025488693-us-east-1-an}"
CLOUDFRONT_DISTRIBUTION_ID="${CLOUDFRONT_DISTRIBUTION_ID:-E28VCKLNUS67BA}"
SKIP_BUILD=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/deploy-frontend-s3.sh [--skip-build] [--dry-run]

Builds the React dashboard, synchronizes it to the existing production S3
bucket, and invalidates the existing CloudFront distribution.

Environment overrides:
  AWS_REGION
  FRONTEND_BUCKET
  CLOUDFRONT_DISTRIBUTION_ID
  VITE_API_URL (leave unset/empty to use the current tapinx.in origin)
EOF
}

while (($#)); do
  case "$1" in
    --skip-build) SKIP_BUILD=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if ((SKIP_BUILD == 0)); then
  if ! command -v npm >/dev/null 2>&1; then
    echo "Required command not found: npm" >&2
    exit 1
  fi
fi

if [[ ! "${FRONTEND_BUCKET}" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  echo "Invalid FRONTEND_BUCKET: ${FRONTEND_BUCKET}" >&2
  exit 1
fi

if [[ ! "${CLOUDFRONT_DISTRIBUTION_ID}" =~ ^[A-Z0-9]+$ ]]; then
  echo "Invalid CLOUDFRONT_DISTRIBUTION_ID: ${CLOUDFRONT_DISTRIBUTION_ID}" >&2
  exit 1
fi

if ((SKIP_BUILD == 0)); then
  echo "Installing frontend dependencies..."
  npm ci --prefix "${FRONTEND_DIR}"

  echo "Building frontend..."
  # An empty value intentionally makes production use window.location.origin.
  VITE_API_URL="${VITE_API_URL:-}" npm run build --prefix "${FRONTEND_DIR}"
fi

if [[ ! -f "${DIST_DIR}/index.html" ]]; then
  echo "Build output is missing: ${DIST_DIR}/index.html" >&2
  exit 1
fi

if ((DRY_RUN == 1)); then
  echo "Dry run: build is valid; no S3 files or CloudFront caches were changed."
  echo "Target: s3://${FRONTEND_BUCKET} (CloudFront ${CLOUDFRONT_DISTRIBUTION_ID})"
  exit 0
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "Required command not found: aws" >&2
  exit 1
fi

echo "Checking AWS access..."
aws sts get-caller-identity --region "${AWS_REGION}" >/dev/null
aws s3api head-bucket --bucket "${FRONTEND_BUCKET}" --region "${AWS_REGION}"

echo "Uploading versioned frontend files..."
aws s3 sync "${DIST_DIR}/" "s3://${FRONTEND_BUCKET}/" \
  --region "${AWS_REGION}" \
  --delete \
  --exclude "index.html" \
  --exclude "assets/*" \
  --cache-control "public,max-age=86400"

if [[ -d "${DIST_DIR}/assets" ]]; then
  aws s3 sync "${DIST_DIR}/assets/" "s3://${FRONTEND_BUCKET}/assets/" \
    --region "${AWS_REGION}" \
    --delete \
    --cache-control "public,max-age=31536000,immutable"
fi

echo "Uploading index.html without browser caching..."
aws s3 cp "${DIST_DIR}/index.html" "s3://${FRONTEND_BUCKET}/index.html" \
  --region "${AWS_REGION}" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "no-cache,no-store,must-revalidate"

echo "Invalidating CloudFront..."
INVALIDATION_ID="$(aws cloudfront create-invalidation \
  --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}" \
  --paths "/*" \
  --query 'Invalidation.Id' \
  --output text)"

echo "Waiting for invalidation ${INVALIDATION_ID}..."
aws cloudfront wait invalidation-completed \
  --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}" \
  --id "${INVALIDATION_ID}"

echo "Frontend deployed successfully: https://tapinx.in"
