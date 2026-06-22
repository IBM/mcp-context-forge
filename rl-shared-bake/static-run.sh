#!/usr/bin/env bash
# Run the static-config rate-limiter test against the ISOLATED static stack
# (port 8001, container rl-static-redis). Bring it up first with static-up.sh.
#
#   ./rl-shared-bake/static-run.sh            # run the static test
#   ./rl-shared-bake/static-run.sh -q         # pass extra pytest args
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

PORT="${STATIC_PORT:-8001}"
if ! curl -fsS -m 3 "http://localhost:${PORT}/health" >/dev/null 2>&1; then
  echo "✗ static gateway not reachable at http://localhost:${PORT} — run ./rl-shared-bake/static-up.sh first" >&2
  exit 1
fi

RUN_RATE_LIMITER_STATIC=1 \
INSPECT=1 \
GATEWAY_URL="http://localhost:${PORT}" \
REDIS_CONTAINER_NAME='rl-static-redis' \
REDIS_CLI_PASSWORD='rlTlsTest_pw_2026' \
JWT_SECRET_KEY='rl-e2e-jwt-secret-2026' \
STATIC_LIMIT=3 STATIC_BURST=5 \
.venv/bin/python -m pytest \
  tests/live_gateway/plugins/test_rate_limiter_static_config_container.py \
  -v -s -p no:cacheprovider "$@"
