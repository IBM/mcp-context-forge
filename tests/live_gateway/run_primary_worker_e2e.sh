#!/usr/bin/env bash
# Boot a local multi-worker gateway with the marker plugin, run the
# primary-worker e2e assertion, and tear down. Invoked via
# `make test-primary-worker-e2e` (runs inside the project venv).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8080}"
WORKERS="${WORKERS:-2}"

TMP="$(mktemp -d)"
MARKER="$TMP/marker.log"
LOCK="$TMP/primary.lock"
LOG="$TMP/gunicorn.log"
DB="$TMP/e2e.db"
GPID=""

cleanup() {
  [ -n "$GPID" ] && kill "$GPID" 2>/dev/null || true
  [ -n "$GPID" ] && wait "$GPID" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "▶ starting gateway: $WORKERS workers on 127.0.0.1:$PORT"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
PLUGINS_ENABLED=true \
PLUGINS_CONFIG_FILE=tests/live_gateway/fixtures/primary_worker_e2e_config.yaml \
MCPGW_PRIMARY_WORKER_E2E_MARKER="$MARKER" \
PRIMARY_WORKER_LOCK_PATH="$LOCK" \
DATABASE_URL="sqlite:///$DB" \
HOST=127.0.0.1 PORT="$PORT" \
  gunicorn -c gunicorn.config.py \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "$WORKERS" --bind "127.0.0.1:$PORT" --timeout 600 \
    --error-logfile "$LOG" --access-logfile /dev/null \
    mcpgateway.main:app &
GPID=$!

echo "▶ waiting for $WORKERS workers + /health ..."
ready=0
for _ in $(seq 1 60); do
  if ! kill -0 "$GPID" 2>/dev/null; then echo "❌ gateway exited early"; cat "$LOG"; exit 1; fi
  booted=$(grep -c "Booting worker" "$LOG" 2>/dev/null || echo 0)
  if [ "$booted" -ge "$WORKERS" ] && curl -fsS -o /dev/null "http://127.0.0.1:$PORT/health" 2>/dev/null; then
    ready=1; break
  fi
  sleep 1
done
[ "$ready" = 1 ] || { echo "❌ gateway not ready in time"; cat "$LOG"; exit 1; }
sleep 2  # settle: let every worker finish plugin initialize()

echo "▶ running assertion"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
MCP_CLI_BASE_URL="http://127.0.0.1:$PORT" \
MCPGW_PRIMARY_WORKER_E2E_MARKER="$MARKER" \
  pytest tests/live_gateway/plugins/test_primary_worker_e2e.py -v -s --tb=short
