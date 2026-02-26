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

export CONC_BASE_URL
export CONC_GATEWAY_URL
export DATABASE_URL
export REDIS_URL

if [[ -z "${CONC_TOKEN:-}" || "${CONC_REFRESH_TOKEN:-0}" == "1" ]]; then
  if [[ -z "${JWT_SECRET_KEY:-}" ]]; then
    echo "ERROR: JWT_SECRET_KEY is not set; cannot generate CONC_TOKEN." >&2
    echo "Set JWT_SECRET_KEY (or provide CONC_TOKEN) and rerun." >&2
    exit 2
  fi
  echo "Generating CONC_TOKEN (user=${CONC_TOKEN_USER}, exp=${CONC_TOKEN_EXP_MIN}m)..."
  export CONC_TOKEN="$(
    python -m mcpgateway.utils.create_jwt_token \
      --username "${CONC_TOKEN_USER}" \
      --exp "${CONC_TOKEN_EXP_MIN}" \
      --secret "${JWT_SECRET_KEY}"
  )"
fi

echo "Preflight: gateway health at ${CONC_BASE_URL}/health"
curl -fsS "${CONC_BASE_URL}/health" >/dev/null

echo "Preflight: auth token at ${CONC_BASE_URL}/servers?limit=1"
curl -fsS \
  -H "Authorization: Bearer ${CONC_TOKEN}" \
  "${CONC_BASE_URL}/servers?limit=1" >/dev/null

gateway_no_scheme="${CONC_GATEWAY_URL#*://}"
host_port_path="${gateway_no_scheme%%/*}"
gateway_host="${host_port_path%%:*}"
gateway_port="${host_port_path##*:}"
if [[ "${gateway_host}" == "${gateway_port}" ]]; then
  gateway_port=80
fi

if command -v nc >/dev/null 2>&1; then
  echo "Preflight: translator tcp check at ${gateway_host}:${gateway_port}"
  nc -z "${gateway_host}" "${gateway_port}" >/dev/null
else
  echo "WARN: nc not found; skipping translator tcp preflight."
fi

echo "Running CONC-01 gateway matrix..."
python tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py
