#!/usr/bin/env bash
# Run the containerized rate-limiter TLS+AUTH e2e against the running rl-gw stack.
# Bring the stack up first with ./rl-shared-bake/up.sh.
#
# Usage:
#   ./rl-shared-bake/run-e2e.sh            # run the container test
#   ./rl-shared-bake/run-e2e.sh -k full    # pass extra pytest args
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

# Guard: the stack must be up (up.sh handles the env/cert/fast-time wiring).
if ! curl -fsS -m 3 http://localhost:8000/health >/dev/null 2>&1; then
  echo "✗ gateway not reachable at http://localhost:8000 — run ./rl-shared-bake/up.sh first" >&2
  exit 1
fi

RUN_BINDING_SINGLE_INSTANCE=1 \
INSPECT=1 \
JWT_SECRET_KEY='rl-e2e-jwt-secret-2026' \
REDIS_CLI_PASSWORD='rlTlsTest_pw_2026' \
GATEWAY_URL='http://localhost:8000' \
.venv/bin/python -m pytest \
  tests/live_gateway/plugins/test_rate_limiter_binding_single_instance_tls_container.py \
  -v -s -p no:cacheprovider "$@"
