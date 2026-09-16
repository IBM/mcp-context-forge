#!/usr/bin/env bash
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
CLIENT_ROOT=${MCP_REVERSE_PROXY_CLIENT_ROOT:-"$ROOT/../../../mcp-reverse-proxy"}
RP_CLIENT_IMAGE=${RP_CLIENT_IMAGE:-}
RUN_ID=${RP_E2E_RUN_ID:-"$$-$RANDOM"}
RUN_SLUG=$(printf '%s' "$RUN_ID" | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:]_-' '-')
RUN_SLUG=${RUN_SLUG:0:32}
PROJECT="mcpgw-rp-e2e-$RUN_SLUG"
ARTIFACTS="$ROOT/artifacts/reverse-proxy-e2e/$RUN_SLUG"
export IMAGE_LOCAL=${RP_GATEWAY_IMAGE:-mcpgateway/mcpgateway:reverse-proxy-e2e-$RUN_SLUG}
export JWT_SECRET_KEY=${RP_JWT_SECRET_KEY:-"t8-jwt-$RUN_SLUG-0123456789abcdef0123456789abcdef"}
export AUTH_ENCRYPTION_SECRET=${RP_AUTH_ENCRYPTION_SECRET:-"t8-auth-$RUN_SLUG-0123456789abcdef0123456789abcdef"}  # pragma: allowlist secret
export PLATFORM_ADMIN_PASSWORD=${RP_PLATFORM_ADMIN_PASSWORD:-"t8-admin-$RUN_SLUG-0123456789abcdef"}  # pragma: allowlist secret
export DEFAULT_USER_PASSWORD=${RP_DEFAULT_USER_PASSWORD:-"t8-user-$RUN_SLUG-0123456789abcdef"}  # pragma: allowlist secret
export REVERSE_PROXY_E2E_RUN_SLUG="$RUN_SLUG"
export REVERSE_PROXY_E2E_COMPOSE_PROJECT="$PROJECT"
export REVERSE_PROXY_E2E_ARTIFACTS="$ARTIFACTS"
export REVERSE_PROXY_E2E_FAST_SERVER_NAME="t8-fast-test-$RUN_SLUG"
export REVERSE_PROXY_E2E_COMPLIANCE_SERVER_NAME="t8-compliance-$RUN_SLUG"
export REVERSE_PROXY_E2E_AUTH_SERVER_NAME="t8-auth-probe-$RUN_SLUG"
export REVERSE_PROXY_E2E_AUTHORITY_SERVER_NAME="t8-authority-probe-$RUN_SLUG"
COMPOSE=(docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" -f "$ROOT/tests/live_gateway/reverse_proxy/docker-compose.reverse-proxy.yml")

pick_port() {
  uv run python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}

export FAST_TEST_PORT=${FAST_TEST_PORT:-$(pick_port)}
export POSTGRES_HOST_PORT=${POSTGRES_HOST_PORT:-$(pick_port)}
export PGBOUNCER_HOST_PORT=${PGBOUNCER_HOST_PORT:-$(pick_port)}
export REDIS_HOST_PORT=${REDIS_HOST_PORT:-$(pick_port)}
export NGINX_PORT=${NGINX_PORT:-$(pick_port)}
export RP_COMPLIANCE_PORT=${RP_COMPLIANCE_PORT:-$(pick_port)}
export RP_AUTH_PORT=${RP_AUTH_PORT:-$(pick_port)}
export RP_FEATURE_OFF_PORT=${RP_FEATURE_OFF_PORT:-$(pick_port)}
export RP_FEATURE_OFF_CONTAINER="${PROJECT}-feature-off"
export RP_FAST_CLIENT_CONTAINER="${PROJECT}-client-fast"
export RP_COMPLIANCE_CLIENT_CONTAINER="${PROJECT}-client-compliance"
export RP_AUTH_CLIENT_CONTAINER="${PROJECT}-client-auth"
export REVERSE_PROXY_E2E_BASE_URL="http://127.0.0.1:$NGINX_PORT"
export RP_HEARTBEAT_TIMEOUT=${RP_HEARTBEAT_TIMEOUT:-3}

mkdir -p "$ARTIFACTS"
if [[ -z "$RP_CLIENT_IMAGE" ]]; then
  [[ -f "$CLIENT_ROOT/pyproject.toml" ]] || { printf 'Maintained client clone not found: %s\n' "$CLIENT_ROOT" >&2; exit 2; }
fi
CLIENT_GATEWAY_URL="ws://127.0.0.1:$NGINX_PORT/reverse-proxy/ws"
FAST_LOCAL_URL="http://127.0.0.1:$FAST_TEST_PORT/mcp"
COMPLIANCE_LOCAL_URL="http://127.0.0.1:$RP_COMPLIANCE_PORT/mcp"
AUTH_LOCAL_URL="http://127.0.0.1:$RP_AUTH_PORT/mcp"
DOWNSTREAM_BIND_HOST="127.0.0.1"
if [[ -n "$RP_CLIENT_IMAGE" ]]; then
  CLIENT_GATEWAY_URL="ws://nginx:80/reverse-proxy/ws"
  FAST_LOCAL_URL="http://fast_test_server:8880/mcp"
  COMPLIANCE_LOCAL_URL="http://host.docker.internal:$RP_COMPLIANCE_PORT/mcp"
  AUTH_LOCAL_URL="http://host.docker.internal:$RP_AUTH_PORT/mcp"
  DOWNSTREAM_BIND_HOST="0.0.0.0"
fi

launch_client() {
  local container_name=$1 log_file=$2
  shift 2
  if [[ -n "$RP_CLIENT_IMAGE" ]]; then
    docker run -d --name "$container_name" --network "${PROJECT}_mcpnet" \
      --add-host host.docker.internal:host-gateway \
      -e REVERSE_PROXY_TOKEN="$TOKEN" -e REVERSE_PROXY_GATEWAY="$CLIENT_GATEWAY_URL" \
      "$RP_CLIENT_IMAGE" "$@" >"$ARTIFACTS/$log_file" 2>&1
  else
    REVERSE_PROXY_TOKEN="$TOKEN" uv run --project "$CLIENT_ROOT" mcp-reverse-proxy "$@" \
      >"$ARTIFACTS/$log_file" 2>&1 &
  fi
}

collect_client_container_logs() {
  [[ -n "$RP_CLIENT_IMAGE" ]] || return 0
  docker logs "$RP_FAST_CLIENT_CONTAINER" >"$ARTIFACTS/client-fast.log" 2>&1 || true
  docker logs "$RP_COMPLIANCE_CLIENT_CONTAINER" >"$ARTIFACTS/client-compliance.log" 2>&1 || true
  docker logs "$RP_AUTH_CLIENT_CONTAINER" >"$ARTIFACTS/client-auth.log" 2>&1 || true
}
cleanup() {
  local status=$?
  trap - EXIT
  set +e
  "${COMPOSE[@]}" logs gateway >"$ARTIFACTS/gateway.log" 2>&1 || true
  collect_client_container_logs
  for launcher_pid in "${CLIENT_PID:-}" "${COMPLIANCE_CLIENT_PID:-}" "${AUTH_CLIENT_PID:-}"; do
    if [[ -n "$launcher_pid" ]]; then pkill -KILL -P "$launcher_pid" 2>/dev/null || true; fi
  done
  if [[ -n "${CLIENT_PID:-}" ]]; then kill "$CLIENT_PID" 2>/dev/null || true; fi
  if [[ -n "${COMPLIANCE_CLIENT_PID:-}" ]]; then kill "$COMPLIANCE_CLIENT_PID" 2>/dev/null || true; fi
  if [[ -n "${COMPLIANCE_SERVER_PID:-}" ]]; then kill "$COMPLIANCE_SERVER_PID" 2>/dev/null || true; fi
  if [[ -n "${AUTH_CLIENT_PID:-}" ]]; then kill "$AUTH_CLIENT_PID" 2>/dev/null || true; fi
  if [[ -n "${AUTH_SERVER_PID:-}" ]]; then kill "$AUTH_SERVER_PID" 2>/dev/null || true; fi
  for process_pid in "${CLIENT_PID:-}" "${COMPLIANCE_CLIENT_PID:-}" "${COMPLIANCE_SERVER_PID:-}" "${AUTH_CLIENT_PID:-}" "${AUTH_SERVER_PID:-}"; do
    if [[ -n "$process_pid" ]]; then wait "$process_pid" 2>/dev/null || true; fi
  done
  docker rm -f "$RP_FEATURE_OFF_CONTAINER" >/dev/null 2>&1 || true
  docker rm -f "$RP_FAST_CLIENT_CONTAINER" "$RP_COMPLIANCE_CLIENT_CONTAINER" "$RP_AUTH_CLIENT_CONTAINER" >/dev/null 2>&1 || true
  "${COMPOSE[@]}" rm -sf fast_test_server >/dev/null 2>&1 || true
  "${COMPOSE[@]}" down -v --remove-orphans || status=1
  if [[ -z "${RP_GATEWAY_IMAGE:-}" ]]; then docker rmi -f "$IMAGE_LOCAL" >/dev/null 2>&1 || true; fi
  if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] ||
    [[ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]] ||
    [[ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
    printf 'Reverse-proxy E2E cleanup left Docker resources behind\n' >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT

"${COMPOSE[@]}" up -d --build gateway nginx fast_test_server
TOKEN=$(uv run python -c "import os,time,uuid,jwt; now=int(time.time()); print(jwt.encode({'sub':'admin@example.com','email':'admin@example.com','user':{'email':'admin@example.com','full_name':'T8 Admin','is_admin':True,'auth_provider':'cli'},'teams':None,'iat':now,'exp':now+3600,'iss':'mcpgateway','aud':'mcpgateway-api','jti':str(uuid.uuid4())},os.environ['JWT_SECRET_KEY'],algorithm='HS256'))")
RESTRICTED_TOKEN=$(uv run python -c "import os,time,uuid,jwt; now=int(time.time()); print(jwt.encode({'sub':'admin@example.com','email':'admin@example.com','user':{'email':'admin@example.com','full_name':'T8 Admin','is_admin':True,'auth_provider':'api_token'},'teams':None,'scopes':{'permissions':['tools.read']},'iat':now,'exp':now+3600,'iss':'mcpgateway','aud':'mcpgateway-api','jti':str(uuid.uuid4())},os.environ['JWT_SECRET_KEY'],algorithm='HS256'))")

uv run --project "$ROOT/mcp-servers/python/compliance_reference_server" compliance-reference-server \
  --transport http --host "$DOWNSTREAM_BIND_HOST" --port "$RP_COMPLIANCE_PORT" >"$ARTIFACTS/compliance-server.log" 2>&1 &
COMPLIANCE_SERVER_PID=$!
T8_EXPECTED_AUTHORIZATION="Bearer t8-forwarded-token" uv run --project "$ROOT/mcp-servers/python/compliance_reference_server" \
  python "$ROOT/tests/live_gateway/reverse_proxy/helpers/auth_probe_server.py" --host "$DOWNSTREAM_BIND_HOST" --port "$RP_AUTH_PORT" >"$ARTIFACTS/auth-server.log" 2>&1 &
AUTH_SERVER_PID=$!

launch_client "$RP_FAST_CLIENT_CONTAINER" client-fast.log \
  --local-streamable-http "$FAST_LOCAL_URL" \
  --gateway "$CLIENT_GATEWAY_URL" \
  --server-name "$REVERSE_PROXY_E2E_FAST_SERVER_NAME" --server-description "T8 real fast_test_server" \
  --keepalive 1 --mcp-health-check-retry-interval 1 --log-level DEBUG
if [[ -z "$RP_CLIENT_IMAGE" ]]; then CLIENT_PID=$!; fi

launch_client "$RP_COMPLIANCE_CLIENT_CONTAINER" client-compliance.log \
  --local-streamable-http "$COMPLIANCE_LOCAL_URL" \
  --gateway "$CLIENT_GATEWAY_URL" \
  --server-name "$REVERSE_PROXY_E2E_COMPLIANCE_SERVER_NAME" --server-description "T8 resource and prompt server" \
  --keepalive 1 --mcp-health-check-retry-interval 1 --log-level INFO
if [[ -z "$RP_CLIENT_IMAGE" ]]; then COMPLIANCE_CLIENT_PID=$!; fi

launch_client "$RP_AUTH_CLIENT_CONTAINER" client-auth.log \
  --local-streamable-http "$AUTH_LOCAL_URL" \
  --gateway "$CLIENT_GATEWAY_URL" \
  --server-name "$REVERSE_PROXY_E2E_AUTH_SERVER_NAME" --server-description "T8 downstream auth probe" \
  --keepalive 1 --mcp-health-check-retry-interval 1 --log-level INFO
if [[ -z "$RP_CLIENT_IMAGE" ]]; then AUTH_CLIENT_PID=$!; fi

REVERSE_PROXY_E2E_TOKEN="$TOKEN" REVERSE_PROXY_E2E_RESTRICTED_TOKEN="$RESTRICTED_TOKEN" \
  REVERSE_PROXY_E2E_FAST_CLIENT_PID="${CLIENT_PID:-0}" REVERSE_PROXY_E2E_COMPLIANCE_CLIENT_PID="${COMPLIANCE_CLIENT_PID:-0}" \
  REVERSE_PROXY_E2E_AUTH_CLIENT_PID="${AUTH_CLIENT_PID:-0}" \
  REVERSE_PROXY_E2E_FAST_CLIENT_CONTAINER="${RP_CLIENT_IMAGE:+$RP_FAST_CLIENT_CONTAINER}" \
  REVERSE_PROXY_E2E_COMPLIANCE_CLIENT_CONTAINER="${RP_CLIENT_IMAGE:+$RP_COMPLIANCE_CLIENT_CONTAINER}" \
  REVERSE_PROXY_E2E_AUTH_CLIENT_CONTAINER="${RP_CLIENT_IMAGE:+$RP_AUTH_CLIENT_CONTAINER}" \
  uv run pytest "$ROOT/tests/live_gateway/reverse_proxy" \
  -v --junitxml="$ARTIFACTS/junit.xml"
"${COMPOSE[@]}" logs gateway >"$ARTIFACTS/gateway.log" 2>&1
collect_client_container_logs
for log_file in "$ARTIFACTS"/*.log; do
  ! grep -E 'Authorization: Bearer|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' "$log_file"
  ! grep -F 't8-forwarded-token' "$log_file"
done
! grep -F "$TOKEN" "$ARTIFACTS/gateway.log"
