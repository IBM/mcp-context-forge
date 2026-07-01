#!/usr/bin/env bash
# scripts/verify_otel_plugin_e2e.sh
#
# Location: ./scripts/verify_otel_plugin_e2e.sh
# Copyright 2026
# SPDX-License-Identifier: Apache-2.0
#
# Task C1 (Refs #5458) -- manual, real-usage verification against a LIVE
# gateway (not TestClient/pytest): proves that a genuinely traced HTTP
# tool-invoke request causes the `pii_filter` CPEX plugin's metrics to reach
# `GET /observability/traces/{trace_id}`, and that the raw PII value the
# plugin detected never leaks into that response (S1).
#
# What this script does, all via real HTTP against a real running gateway:
#   1. Mint an admin JWT with the CLI (mcpgateway.utils.create_jwt_token).
#   2. Register a REST tool via a real `POST /tools` call.
#   3. Invoke it via a real `POST /rpc` (`tools/call`) call carrying a W3C
#      `traceparent` header with a trace_id we chose ourselves, and a
#      synthetic PII value (email) in the tool arguments -- so `pii_filter`'s
#      tool_pre_invoke hook has something to detect before any outbound
#      network call is attempted. (The tool's own upstream URL is
#      intentionally unreachable -- see NOTE below -- this script does not
#      depend on any 3rd-party network service.)
#   4. Query `GET /observability/traces/{trace_id}` for that exact trace_id
#      and assert the `plugin.metrics.pii_filter` span's attributes contain
#      the expected counts/type-names, AND that the raw PII value is absent
#      from the entire response body (S1).
#
# NOTE on the tool's upstream URL: pii_filter's tool_pre_invoke hook runs
# BEFORE the gateway makes its outbound call to the tool's backend, so this
# script deliberately points the registered tool at an unreachable local
# port. The subsequent tool invocation is expected to fail at the network
# layer -- that failure is irrelevant to what we're proving; the
# `plugin.metrics.pii_filter` span (stage="tool_pre_invoke") is already
# recorded by the time the network call is attempted.
#
# Usage:
#   scripts/verify_otel_plugin_e2e.sh
#
# By default this script starts its own throwaway `uvicorn` instance (the
# same command `make dev` runs) with PLUGINS_ENABLED=true,
# OBSERVABILITY_ENABLED=true, PLUGINS_CONFIG_FILE=plugins/config.yaml (which
# must contain the pii_filter entry -- see Step 2 of the C1 task brief) and a
# throwaway SQLite DB, waits for it to become healthy, runs the verification,
# then stops it.
#
# To run against a gateway you already started yourself (e.g. `make dev` in
# another terminal, with the same env vars set), skip the built-in server:
#
#   GATEWAY_URL=http://localhost:8000 SKIP_SERVER_START=1 JWT_SECRET_KEY=<your-secret> \
#     scripts/verify_otel_plugin_e2e.sh
#
# Required env vars when SKIP_SERVER_START=1: JWT_SECRET_KEY must match the
# secret the already-running gateway is using (JWT_SECRET_KEY in its .env),
# and that gateway must have been started with PLUGINS_ENABLED=true,
# PLUGINS_CONFIG_FILE pointing at a config with the pii_filter entry enabled
# for tool_pre_invoke/tool_post_invoke, OBSERVABILITY_ENABLED=true, and
# (for the CLI-minted admin JWT to work without a pre-seeded DB user)
# REQUIRE_USER_IN_DB=false.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Config (override via env)
# ---------------------------------------------------------------------------
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8000}"
SKIP_SERVER_START="${SKIP_SERVER_START:-0}"
JWT_SECRET_KEY="${JWT_SECRET_KEY:-e2e-otel-plugin-verify-secret-do-not-use-in-prod}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

# Synthetic PII -- not a real person's data. Realistic enough to trip
# pii_filter's email detector; the whole point of this script is to prove
# this value never reaches /observability.
RAW_PII_EMAIL="verify-otel-e2e.synthetic-subject@pii-shell-fixture.invalid"

TOOL_NAME_INPUT="pii_probe_shell_tool_$$"
# Deliberately unreachable -- see NOTE above. Port 1 is not a listening
# service on any normal host, so the connection is refused immediately
# rather than timing out.
UPSTREAM_TOOL_URL="http://127.0.0.1:1/pii-e2e-fixture-unreachable"

SERVER_LOG=""
SERVER_PID=""
DB_FILE=""

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
for bin in curl jq "$PYTHON_BIN"; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "❌ Required tool not found: $bin" >&2
    exit 1
  fi
done

if [[ ! -f "plugins/config.yaml" ]] || ! grep -q "cpex_pii_filter.pii_filter.PIIFilterPlugin" plugins/config.yaml; then
  echo "❌ plugins/config.yaml does not contain the pii_filter entry (Step 2 of the C1 task brief)." >&2
  exit 1
fi

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    echo "🧹 Stopping gateway (pid $SERVER_PID)..."
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ -n "$DB_FILE" && -f "$DB_FILE" ]]; then
    rm -f "$DB_FILE"
  fi
  if [[ -n "$SERVER_LOG" && -f "$SERVER_LOG" && -z "${KEEP_SERVER_LOG:-}" ]]; then
    rm -f "$SERVER_LOG"
  fi
}
trap cleanup EXIT

wait_for_http() {
  local url="$1" attempts="${2:-60}" delay="${3:-1}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

# ---------------------------------------------------------------------------
# Step 0: start (or reuse) the gateway
# ---------------------------------------------------------------------------
if [[ "$SKIP_SERVER_START" == "1" ]]; then
  echo "ℹ️  SKIP_SERVER_START=1 -- reusing gateway at $GATEWAY_URL"
  echo "   (it must already have PLUGINS_ENABLED=true and OBSERVABILITY_ENABLED=true)"
else
  if curl -fsS "$GATEWAY_URL/health" >/dev/null 2>&1; then
    echo "ℹ️  Gateway already reachable at $GATEWAY_URL -- reusing it."
    echo "   (it must already have PLUGINS_ENABLED=true and OBSERVABILITY_ENABLED=true)"
  else
    echo "🚀 Starting a throwaway gateway instance for this verification..."
    SERVER_LOG="$(mktemp -t verify-otel-plugin-e2e-server.XXXXXX.log)"
    DB_FILE="$(mktemp -t verify-otel-plugin-e2e.XXXXXX.db)"
    rm -f "$DB_FILE" # let the gateway create the schema fresh

    PLUGINS_ENABLED=true \
      PLUGINS_CONFIG_FILE="$REPO_ROOT/plugins/config.yaml" \
      OBSERVABILITY_ENABLED=true \
      REQUIRE_USER_IN_DB=false \
      AUTH_REQUIRED=true \
      JWT_SECRET_KEY="$JWT_SECRET_KEY" \
      DATABASE_URL="sqlite:///$DB_FILE" \
      "$PYTHON_BIN" -m uvicorn mcpgateway.main:app --host 127.0.0.1 --port 8000 \
      >"$SERVER_LOG" 2>&1 &
    SERVER_PID=$!

    echo "⏳ Waiting for gateway to become healthy (pid $SERVER_PID, log: $SERVER_LOG)..."
    if ! wait_for_http "$GATEWAY_URL/health" 60 1; then
      echo "❌ Gateway did not become healthy in time. Last log lines:" >&2
      tail -n 80 "$SERVER_LOG" >&2 || true
      exit 1
    fi
  fi
fi
echo "✅ Gateway reachable at $GATEWAY_URL"

# ---------------------------------------------------------------------------
# Step 1: mint an admin JWT
# ---------------------------------------------------------------------------
echo "🔑 Minting admin JWT for $ADMIN_EMAIL..."
TOKEN="$("$PYTHON_BIN" -m mcpgateway.utils.create_jwt_token --username "$ADMIN_EMAIL" --secret "$JWT_SECRET_KEY" --exp 30 2>/dev/null)"
if [[ -z "$TOKEN" ]]; then
  echo "❌ Failed to mint JWT" >&2
  exit 1
fi
AUTH_HEADER="Authorization: Bearer $TOKEN"

# ---------------------------------------------------------------------------
# Step 2: register a REST tool
# ---------------------------------------------------------------------------
echo "🛠️  Registering probe tool ($TOOL_NAME_INPUT)..."
REGISTER_PAYLOAD=$(
  jq -n \
    --arg name "$TOOL_NAME_INPUT" \
    --arg url "$UPSTREAM_TOOL_URL" \
    '{tool: {name: $name, description: "C1 e2e fixture tool (upstream intentionally unreachable)", integrationType: "REST", url: $url, requestType: "POST", visibility: "public"}, team_id: null}'
)
REGISTER_RESPONSE=$(curl -fsS -X POST "$GATEWAY_URL/tools" -H "$AUTH_HEADER" -H "Content-Type: application/json" -d "$REGISTER_PAYLOAD")
TOOL_NAME=$(echo "$REGISTER_RESPONSE" | jq -r '.name')
if [[ -z "$TOOL_NAME" || "$TOOL_NAME" == "null" ]]; then
  echo "❌ Tool registration failed. Response:" >&2
  echo "$REGISTER_RESPONSE" >&2
  exit 1
fi
echo "✅ Registered tool as '$TOOL_NAME'"

# ---------------------------------------------------------------------------
# Step 3: invoke the tool over a traced HTTP request carrying PII
# ---------------------------------------------------------------------------
TRACE_ID="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(16))')"
PARENT_SPAN_ID="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(8))')"
TRACEPARENT="00-${TRACE_ID}-${PARENT_SPAN_ID}-01"

echo "📡 Invoking tool via POST /rpc with traceparent: $TRACEPARENT"
RPC_PAYLOAD=$(
  jq -n \
    --arg name "$TOOL_NAME" \
    --arg note "Please update contact on file to $RAW_PII_EMAIL" \
    '{jsonrpc: "2.0", id: "verify-otel-e2e-1", method: "tools/call", params: {name: $name, arguments: {note: $note}}}'
)
RPC_RESPONSE=$(curl -fsS -X POST "$GATEWAY_URL/rpc" -H "$AUTH_HEADER" -H "Content-Type: application/json" -H "traceparent: $TRACEPARENT" -d "$RPC_PAYLOAD")

if echo "$RPC_RESPONSE" | grep -qF "$RAW_PII_EMAIL"; then
  echo "❌ SECURITY: raw PII leaked into the tools/call RPC response body:" >&2
  echo "$RPC_RESPONSE" >&2
  exit 1
fi
echo "✅ tools/call completed; no raw PII in the RPC response body"

# ---------------------------------------------------------------------------
# Step 4: query the observability endpoint for our trace_id
# ---------------------------------------------------------------------------
echo "🔍 Fetching GET /observability/traces/$TRACE_ID ..."
TRACE_RESPONSE=$(curl -fsS "$GATEWAY_URL/observability/traces/$TRACE_ID" -H "$AUTH_HEADER")

echo "$TRACE_RESPONSE" | jq '.' || {
  echo "❌ Observability response was not valid JSON:" >&2
  echo "$TRACE_RESPONSE" >&2
  exit 1
}

# S1: the raw PII value must never appear anywhere in the observability response.
if echo "$TRACE_RESPONSE" | grep -qF "$RAW_PII_EMAIL"; then
  echo "❌ SECURITY: raw PII leaked into /observability/traces/$TRACE_ID response!" >&2
  exit 1
fi
echo "✅ S1 confirmed: no raw PII anywhere in the /observability/traces/$TRACE_ID response"

PII_SPAN=$(echo "$TRACE_RESPONSE" | jq '[.spans[] | select(.name == "plugin.metrics.pii_filter")] | first')
if [[ "$PII_SPAN" == "null" || -z "$PII_SPAN" ]]; then
  echo "❌ No 'plugin.metrics.pii_filter' span found in the trace. Span names present:" >&2
  echo "$TRACE_RESPONSE" | jq '[.spans[].name]' >&2
  exit 1
fi

TOTAL_DETECTIONS=$(echo "$PII_SPAN" | jq -r '.attributes.total_detections // 0')
TOTAL_MASKED=$(echo "$PII_SPAN" | jq -r '.attributes.total_masked // 0')
DETECTION_TYPES=$(echo "$PII_SPAN" | jq -r '.attributes.detection_types // ""')
STAGE=$(echo "$PII_SPAN" | jq -r '.attributes.stage // ""')

echo ""
echo "📊 plugin.metrics.pii_filter span:"
echo "$PII_SPAN" | jq '.'
echo ""

if [[ "$TOTAL_DETECTIONS" -lt 1 ]]; then
  echo "❌ Expected total_detections >= 1, got: $TOTAL_DETECTIONS" >&2
  exit 1
fi
if [[ "$TOTAL_MASKED" -lt 1 ]]; then
  echo "❌ Expected total_masked >= 1, got: $TOTAL_MASKED" >&2
  exit 1
fi
if [[ "$DETECTION_TYPES" != *"email"* ]]; then
  echo "❌ Expected 'email' in detection_types, got: $DETECTION_TYPES" >&2
  exit 1
fi

echo "✅✅✅ SUCCESS: traced HTTP tool call surfaced pii_filter metrics in /observability"
echo "   trace_id=$TRACE_ID stage=$STAGE total_detections=$TOTAL_DETECTIONS total_masked=$TOTAL_MASKED detection_types=$DETECTION_TYPES"
echo "   No raw PII value found anywhere in the RPC response or the /observability response."
