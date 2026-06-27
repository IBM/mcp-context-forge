#!/usr/bin/env bash
# Run the static-config rate-limiter test against the ISOLATED static stack
# (port 8001, container rl-static-redis). Bring it up first with static-up.sh.
#
#   ./rl-shared-bake/static-run.sh            # run the static test
#   ./rl-shared-bake/static-run.sh -q         # pass extra pytest args
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

PORT="${STATIC_PORT:-8001}"
GATEWAY_CA_CERT="${GATEWAY_CA_CERT:-tls-certs/ca.crt}"
STATIC_GATEWAY_SSL="${STATIC_GATEWAY_SSL:-1}"
if [ "$STATIC_GATEWAY_SSL" = "0" ]; then
  BASE_URL="http://localhost:${PORT}"
  GATEWAY_VERIFY_TLS=0
else
  BASE_URL="https://localhost:${PORT}"
  GATEWAY_VERIFY_TLS=1
fi
STATIC_LIMIT="${STATIC_LIMIT:-3}"
STATIC_BURST="${STATIC_BURST:-$((STATIC_LIMIT + 2))}"
STATIC_CONCURRENCY="${STATIC_CONCURRENCY:-1}"
STATIC_RUN_REQUIRE_READY="${STATIC_RUN_REQUIRE_READY:-1}"
GATEWAY_CONTAINER_NAME="${GATEWAY_CONTAINER_NAME:-rl-static-gw}"
EXPECT_GATEWAY_PLUGIN_BACKEND_UNAVAILABLE="${EXPECT_GATEWAY_PLUGIN_BACKEND_UNAVAILABLE:-0}"
REDIS_CLI_PASSWORD="${REDIS_CLI_PASSWORD:-rlTlsTest_pw_2026}" # pragma: allowlist secret
JWT_SECRET_KEY="${JWT_SECRET_KEY:-rl-e2e-jwt-secret-2026}" # pragma: allowlist secret

curl_gateway() {
  if [ "$STATIC_GATEWAY_SSL" = "0" ]; then
    curl "$@"
  else
    curl --cacert "$GATEWAY_CA_CERT" "$@"
  fi
}

CHECK_PATH="/ready"
if [ "$STATIC_RUN_REQUIRE_READY" = "0" ]; then
  CHECK_PATH="/health"
fi

if ! curl_gateway -fsS -m 3 "${BASE_URL}${CHECK_PATH}" >/dev/null 2>&1; then
  echo "✗ static gateway not reachable at ${BASE_URL}${CHECK_PATH} — run ./rl-shared-bake/static-up.sh first" >&2
  exit 1
fi

RUN_RATE_LIMITER_STATIC=1 \
INSPECT=1 \
GATEWAY_URL="$BASE_URL" \
GATEWAY_CA_CERT="$GATEWAY_CA_CERT" \
GATEWAY_VERIFY_TLS="$GATEWAY_VERIFY_TLS" \
EXPECT_AUTH_REQUIRED=1 \
GATEWAY_CONTAINER_NAME="$GATEWAY_CONTAINER_NAME" \
EXPECT_GATEWAY_PLUGIN_BACKEND_UNAVAILABLE="$EXPECT_GATEWAY_PLUGIN_BACKEND_UNAVAILABLE" \
REDIS_CONTAINER_NAME='rl-static-redis' \
REDIS_CLI_PASSWORD="$REDIS_CLI_PASSWORD" \
JWT_SECRET_KEY="$JWT_SECRET_KEY" \
STATIC_LIMIT="$STATIC_LIMIT" \
STATIC_BURST="$STATIC_BURST" \
STATIC_CONCURRENCY="$STATIC_CONCURRENCY" \
.venv/bin/python -m pytest \
  tests/live_gateway/plugins/test_rate_limiter_static_config_container.py \
  -v -s -p no:cacheprovider "$@"
