#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

: "${CONC_BASE_URL:=http://127.0.0.1:8000}"
: "${CONC_GATEWAY_URL:=http://127.0.0.1:9000/sse}"
: "${DATABASE_URL:=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/concurrent_test}"
: "${REDIS_URL:=redis://127.0.0.1:6379}"
: "${CONC_TOKEN_USER:=admin@example.com}"
: "${CONC_TOKEN_EXP_MIN:=120}"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "ERROR: python3/python not found in PATH." >&2
    exit 2
  fi
fi

export CONC_BASE_URL
export CONC_GATEWAY_URL
export DATABASE_URL
export REDIS_URL

if [[ -z "${CONC_TOKEN:-}" ]]; then
  echo "ERROR: CONC_TOKEN is not set." >&2
  echo "Generate and export it manually before running this script." >&2
  echo "Example:" >&2
  echo "  export CONC_TOKEN=\"\$(${PYTHON_BIN} -m mcpgateway.utils.create_jwt_token --username ${CONC_TOKEN_USER} --exp ${CONC_TOKEN_EXP_MIN} --secret <jwt-secret>)\"" >&2
  exit 2
fi

echo "Running CONC-01 gateway matrix..."
"${PYTHON_BIN}" tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py
