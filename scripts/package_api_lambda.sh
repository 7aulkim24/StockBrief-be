#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${ROOT_DIR}"
BUILD_DIR="${ROOT_DIR}/dist/lambda-api"
ZIP_PATH="${ROOT_DIR}/dist/stockbrief-api-lambda.zip"
PYTHON_BIN="${PYTHON_BIN:-python3.13}"

rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}" "${ROOT_DIR}/dist"

"${PYTHON_BIN}" -m pip install \
  --target "${BUILD_DIR}" \
  "${API_DIR}"

find "${BUILD_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +

(
  cd "${BUILD_DIR}"
  zip -qr "${ZIP_PATH}" .
)

echo "Packaged ${ZIP_PATH}"
