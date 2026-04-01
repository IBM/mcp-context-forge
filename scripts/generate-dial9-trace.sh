#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/tools_rust/mcp_runtime"
ARTIFACT_DIR="$ROOT_DIR/artifacts/dial9"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TRACE_STEM="dial9-trace-${TIMESTAMP}"
TRACE_PATH="$ARTIFACT_DIR/${TRACE_STEM}.bin"
LOG_PATH="$ARTIFACT_DIR/${TRACE_STEM}.log"
PORT="${MCP_RUST_TRACE_PORT:-18788}"
RUNTIME_URL="http://127.0.0.1:${PORT}"
RUNTIME_WORKERS="${MCP_RUST_TRACE_RUNTIME_WORKERS:-4}"
CLIENT_WORKERS="${MCP_RUST_TRACE_CLIENT_WORKERS:-12}"
TRACE_DURATION_SECONDS="${MCP_RUST_TRACE_DURATION_SECONDS:-7}"
TRACE_SCENARIO="${MCP_RUST_TRACE_SCENARIO:-local}"
VENV_DIR="${VENV_DIR:-$HOME/.venv/mcpgateway}"
COMPOSE_PROJECT_NAME="${MCP_RUST_TRACE_COMPOSE_PROJECT:-mcp-trace}"
LOCUST_USERS="${MCP_RUST_TRACE_LOCUST_USERS:-24}"
LOCUST_SPAWN_RATE="${MCP_RUST_TRACE_LOCUST_SPAWN_RATE:-6}"
ECHO_DELAY_MS="${MCP_RUST_TRACE_ECHO_DELAY_MS:-300}"
LOCUST_STOP_TIMEOUT="${MCP_RUST_TRACE_LOCUST_STOP_TIMEOUT:-30}"
GATEWAY_PORT="${MCP_RUST_TRACE_GATEWAY_PORT:-18444}"

mkdir -p "$ARTIFACT_DIR"

cleanup() {
  if [[ -n "${runtime_pid:-}" ]] && kill -0 "$runtime_pid" 2>/dev/null; then
    kill "$runtime_pid" 2>/dev/null || true
    wait "$runtime_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT

run_local_trace() {
echo "Building telemetry-enabled runtime with tokio_unstable hooks..."
(
  cd "$RUNTIME_DIR"
  RUSTFLAGS="--cfg tokio_unstable ${RUSTFLAGS:-}" cargo build --features runtime-telemetry
)

echo "Starting runtime on ${RUNTIME_URL}..."
(
  cd "$RUNTIME_DIR"
  export MCP_RUST_TELEMETRY_ENABLED=true
  export MCP_RUST_TELEMETRY_PATH="$TRACE_PATH"
  export MCP_RUST_LOG=info
  export TOKIO_WORKER_THREADS="$RUNTIME_WORKERS"
  ./target/debug/contextforge_mcp_runtime \
    --listen-http "127.0.0.1:${PORT}" \
    --exit-after-startup-ms 8000
) >"$LOG_PATH" 2>&1 &
runtime_pid=$!

for _ in $(seq 1 40); do
  if curl -fsS "${RUNTIME_URL}/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

if ! curl -fsS "${RUNTIME_URL}/healthz" >/dev/null 2>&1; then
  echo "Runtime failed to become healthy; see ${LOG_PATH}" >&2
  exit 1
fi

echo "Driving representative MCP workload..."
deadline=$((SECONDS + TRACE_DURATION_SECONDS))

workload_worker() {
  local worker_id="$1"
  local request_id=0

  while (( SECONDS < deadline )); do
    request_id=$((request_id + 1))
    case $(((worker_id + request_id) % 4)) in
      0)
        curl -fsS "${RUNTIME_URL}/healthz" >/dev/null
        ;;
      1)
        curl -fsS "${RUNTIME_URL}/mcp/" \
          -H 'content-type: application/json' \
          -H 'mcp-protocol-version: 2025-11-25' \
          -d "{\"jsonrpc\":\"2.0\",\"id\":${worker_id}${request_id},\"method\":\"ping\",\"params\":{}}" >/dev/null
        ;;
      2)
        curl -sS "${RUNTIME_URL}/mcp/" \
          -H 'content-type: application/json' \
          -H 'mcp-protocol-version: 1999-01-01' \
          -d "{\"jsonrpc\":\"2.0\",\"id\":${worker_id}${request_id},\"method\":\"ping\",\"params\":{}}" >/dev/null
        ;;
      3)
        curl -sS "${RUNTIME_URL}/mcp/" \
          -H 'content-type: application/json' \
          -H 'mcp-protocol-version: 2025-11-25' \
          -d "[{\"jsonrpc\":\"2.0\",\"id\":${worker_id}${request_id},\"method\":\"ping\",\"params\":{}},{\"jsonrpc\":\"2.0\",\"id\":${worker_id}${request_id}1,\"method\":\"ping\",\"params\":{}}]" >/dev/null
        ;;
    esac
    sleep 0.02
  done
}

request_pids=()
for worker_id in $(seq 1 "$CLIENT_WORKERS"); do
  workload_worker "$worker_id" &
  request_pids+=("$!")
done

for request_pid in "${request_pids[@]}"; do
  wait "$request_pid"
done

echo "Waiting for clean runtime shutdown..."
wait "$runtime_pid"
trap - EXIT
}

run_compose_echo_delay_trace() {
  local trace_mount_dir="$ARTIFACT_DIR/${TRACE_STEM}-telemetry"
  local override_file="$ARTIFACT_DIR/${TRACE_STEM}.compose.override.yml"
  local summary_report="$ROOT_DIR/reports/${TRACE_STEM}.locust.txt"
  local summary_file="$ARTIFACT_DIR/${TRACE_STEM}.locust.txt"
  local finalized_trace="$ARTIFACT_DIR/${TRACE_STEM}.0.bin"
  local gateway_url="http://127.0.0.1:${GATEWAY_PORT}"

  mkdir -p "$trace_mount_dir"

  cat >"$override_file" <<'EOF'
services:
  nginx:
    ports: []
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
        reservations:
          cpus: "0.25"
          memory: 128M
  gateway:
    ports:
      - "127.0.0.1:__GATEWAY_PORT__:4444"
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: "1.5"
          memory: 2G
        reservations:
          cpus: "0.5"
          memory: 512M
    environment:
      RUST_MCP_MODE: "full"
      RUST_MCP_LOG: "info"
      HTTP_SERVER: "gunicorn"
      GUNICORN_WORKERS: "4"
      TOKIO_WORKER_THREADS: "4"
      EXPERIMENTAL_RUST_MCP_TELEMETRY_ENABLED: "true"
      EXPERIMENTAL_RUST_MCP_TELEMETRY_PATH: "/tmp/contextforge-mcp-runtime/telemetry/trace.bin"
      EXPERIMENTAL_RUST_MCP_TELEMETRY_ROTATE_BYTES: "8388608"
      EXPERIMENTAL_RUST_MCP_TELEMETRY_MAX_BYTES: "67108864"
    volumes:
      - __TRACE_MOUNT_DIR__:/tmp/contextforge-mcp-runtime/telemetry
  fast_test_server:
    ports: !reset []
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 1G
        reservations:
          cpus: "0.25"
          memory: 256M
  postgres:
    ports: !reset []
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 1G
        reservations:
          cpus: "0.25"
          memory: 256M
  redis:
    ports: !reset []
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
        reservations:
          cpus: "0.1"
          memory: 64M
  pgbouncer:
    ports: !reset []
EOF

  perl -0pi -e '
    s#__TRACE_MOUNT_DIR__#'"$trace_mount_dir"'#g;
    s#__GATEWAY_PORT__#'"$GATEWAY_PORT"'#g;
    s#__LOCUST_USERS__#'"$LOCUST_USERS"'#g;
    s#__LOCUST_SPAWN_RATE__#'"$LOCUST_SPAWN_RATE"'#g;
    s#__TRACE_DURATION_SECONDS__#'"$TRACE_DURATION_SECONDS"'#g;
    s#__ECHO_DELAY_MS__#'"$ECHO_DELAY_MS"'#g;
    s#__LOCUST_STOP_TIMEOUT__#'"$LOCUST_STOP_TIMEOUT"'#g;
    s#__TRACE_STEM__#'"$TRACE_STEM"'#g;
  ' "$override_file"

  compose_trace_cleanup() {
    COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" docker compose -f "$ROOT_DIR/docker-compose.yml" -f "$override_file" --profile testing down --remove-orphans >/dev/null 2>&1 || true
    rm -f "$override_file"
  }

  trap 'compose_trace_cleanup' EXIT

  echo "Building telemetry-enabled Rust gateway image..."
  (
    cd "$ROOT_DIR"
    ENABLE_RUST_MCP_TELEMETRY_BUILD=1 make docker-prod-rust
  )

  echo "Starting compose-backed Rust MCP testing stack..."
  (
    cd "$ROOT_DIR"
    COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" HOST_UID="$(id -u)" HOST_GID="$(id -g)" docker compose -f docker-compose.yml -f "$override_file" --profile testing up -d \
      postgres redis pgbouncer fast_test_server gateway
  )

  for _ in $(seq 1 120); do
    if curl -fsS "${gateway_url}/health" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  if ! curl -fsS "${gateway_url}/health" >/dev/null 2>&1; then
    echo "Testing stack failed to become healthy at ${gateway_url}" >&2
    exit 1
  fi

  echo "Running host-side fast_test registration..."
  if [[ ! -d "$VENV_DIR" ]]; then
    (
      cd "$ROOT_DIR"
      make venv
    )
  fi

  local admin_token
  admin_token="$(
    /bin/bash -eu -o pipefail -c "source \"$VENV_DIR/bin/activate\" && python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --admin --exp 10080 --secret 'my-test-key-but-now-longer-than-32-bytes' --algo HS256 2>/dev/null"
  )"

  GATEWAY_URL="$gateway_url" ADMIN_TOKEN="$admin_token" /bin/bash -eu -o pipefail <<'EOF'
python3 - <<'PY'
import json
import os
import time
import urllib.error
import urllib.request

gateway_url = os.environ["GATEWAY_URL"]
token = os.environ["ADMIN_TOKEN"]
virtual_server_id = "b8e3f1a2c4d5e6f7a1b2c3d4e5f6a7b8"  # pragma: allowlist secret

def api_request(method, path, data=None):
    req = urllib.request.Request(f"{gateway_url}{path}", method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if data is not None:
        req.data = json.dumps(data).encode("utf-8")
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        return json.loads(body.decode("utf-8")) if body else None

for _ in range(30):
    try:
        api_request("GET", "/gateways")
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("gateway admin API never became ready")

try:
    api_request("DELETE", f"/servers/{virtual_server_id}")
except Exception:
    pass

try:
    gateways = api_request("GET", "/gateways") or []
    for gw in gateways:
        if gw.get("name") == "fast_test":
            try:
                api_request("DELETE", f"/gateways/{gw['id']}")
            except Exception:
                pass
except Exception:
    pass

result = api_request("POST", "/gateways", {
    "name": "fast_test",
    "url": "http://fast_test_server:8880/mcp",
    "transport": "STREAMABLEHTTP",
})
gateway_id = result.get("id", "")

tool_ids = []
for _ in range(30):
    time.sleep(1)
    tools = api_request("GET", "/tools") or []
    tool_ids = [t["id"] for t in tools if t.get("gatewayId") == gateway_id]
    if tool_ids:
        break

api_request("POST", "/servers", {
    "server": {
        "id": virtual_server_id,
        "name": "Fast Test Server",
        "description": "Virtual server exposing Fast Test MCP tools",
        "associated_tools": tool_ids,
        "associated_resources": [],
        "associated_prompts": [],
    }
})
PY
EOF

  echo "Running Locust echo-delay workload..."
  local locust_exit_code=0
  (
    cd "$ROOT_DIR"
    /bin/bash -eu -o pipefail -c "source \"$VENV_DIR/bin/activate\" && \
      uv pip show locust >/dev/null 2>&1 || uv pip install locust requests PyJWT && \
      MCPGATEWAY_BEARER_TOKEN=\"$admin_token\" \
      LOCUST_WXO_AUTH_ENABLED=false \
      ECHO_DELAY_MS=\"$ECHO_DELAY_MS\" \
      locust -f tests/loadtest/locustfile_echo_delay.py \
        --host=\"$gateway_url\" \
        --users=\"$LOCUST_USERS\" \
        --spawn-rate=\"$LOCUST_SPAWN_RATE\" \
        --run-time=\"${TRACE_DURATION_SECONDS}s\" \
        --headless \
        --stop-timeout=\"$LOCUST_STOP_TIMEOUT\" \
        --exit-code-on-error=1 \
        --only-summary" | tee "$summary_report"
  ) || locust_exit_code=$?

  cp "$summary_report" "$summary_file"
  sleep 2

  shopt -s nullglob
  trace_files=("$trace_mount_dir"/*.bin)
  shopt -u nullglob

  if [[ "${#trace_files[@]}" -eq 0 ]] && [[ -f "$trace_mount_dir/trace.0.bin.active" ]]; then
    cp "$trace_mount_dir/trace.0.bin.active" "$finalized_trace"
    trace_files=("$finalized_trace")
  fi

  if [[ "${#trace_files[@]}" -eq 0 ]]; then
    echo "No compose-backed Dial9 trace files were created in $trace_mount_dir" >&2
    exit 1
  fi

  printf 'Generated trace artifact(s):\n'
  printf '  %s\n' "${trace_files[@]}"
  printf 'Locust summary:\n  %s\n' "$summary_file"
  trap - EXIT
  compose_trace_cleanup

  if (( locust_exit_code != 0 )); then
    echo "Locust exited with status ${locust_exit_code}; trace and summary were still collected." >&2
    return "$locust_exit_code"
  fi
}
case "$TRACE_SCENARIO" in
  local)
    run_local_trace
    ;;
  compose-echo-delay)
    run_compose_echo_delay_trace
    exit 0
    ;;
  *)
    echo "Unsupported MCP_RUST_TRACE_SCENARIO: $TRACE_SCENARIO" >&2
    exit 1
    ;;
esac

shopt -s nullglob
trace_files=("$ARTIFACT_DIR/${TRACE_STEM}."*.bin)
shopt -u nullglob

if [[ "${#trace_files[@]}" -eq 0 ]]; then
  echo "No finalized Dial9 trace files were created; see ${LOG_PATH}" >&2
  exit 1
fi

printf 'Generated trace artifact(s):\n'
printf '  %s\n' "${trace_files[@]}"
printf 'Runtime log:\n  %s\n' "$LOG_PATH"
