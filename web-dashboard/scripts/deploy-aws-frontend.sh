#!/usr/bin/env bash
set -euo pipefail

BUCKET_NAME="${BUCKET_NAME:-}"
API_URL="${API_URL:-}"
CLOUDFRONT_DISTRIBUTION_ID="${CLOUDFRONT_DISTRIBUTION_ID:-}"

if [ -z "${BUCKET_NAME}" ]; then
  echo "BUCKET_NAME required" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

if [ -n "${API_URL}" ]; then
  export VITE_API_URL="${API_URL}"
fi

npm ci
npm run build

aws s3 sync dist "s3://${BUCKET_NAME}/" --delete
aws s3 cp dist/index.html "s3://${BUCKET_NAME}/index.html" --cache-control "no-cache, no-store, must-revalidate"

if [ -n "${CLOUDFRONT_DISTRIBUTION_ID}" ]; then
  aws cloudfront create-invalidation --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}" --paths "/*"
fi
