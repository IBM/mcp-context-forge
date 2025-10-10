#!/usr/bin/env bash
# ==============================================================================
# Gateway Core Performance Testing
# Tests gateway internals without MCP server dependencies
# ==============================================================================

set -Eeuo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." &>/dev/null && pwd)"

# Configuration
GATEWAY_URL="${GATEWAY_URL:-http://localhost:4444}"
PROFILE="${PROFILE:-medium}"
RESULTS_DIR="${RESULTS_DIR:-$PROJECT_ROOT/tests/performance/results}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Load profile
PROFILE_FILE="$PROJECT_ROOT/tests/performance/profiles/$PROFILE.env"
if [ -f "$PROFILE_FILE" ]; then
    # shellcheck disable=SC1090
    source "$PROFILE_FILE"
fi

REQUESTS="${REQUESTS:-10000}"
CONCURRENCY="${CONCURRENCY:-50}"
TIMEOUT="${TIMEOUT:-60}"

# Create results directory
mkdir -p "$RESULTS_DIR"

# Load auth token
if [ -f "$PROJECT_ROOT/tests/performance/.auth_token" ]; then
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/tests/performance/.auth_token"
fi

AUTH_HEADER=""
if [ -n "${MCPGATEWAY_BEARER_TOKEN:-}" ]; then
    AUTH_HEADER="Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
    info "Using authentication token"
fi

# Check hey is installed
if ! command -v hey &>/dev/null; then
    error "hey is not installed"
    exit 1
fi

log "🔧 Gateway Core Performance Test"
log "Profile: $PROFILE"
log "Requests: $REQUESTS"
log "Concurrency: $CONCURRENCY"
log "Gateway: $GATEWAY_URL"
echo ""

# Test 1: Health endpoint (unauthenticated)
log "════════════════════════════════════════════════════════"
log "Test 1: Health Check Endpoint (Unauthenticated)"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_health_unauth_${PROFILE}_${TIMESTAMP}.txt"

hey -n "$REQUESTS" -c "$CONCURRENCY" -t "$TIMEOUT" \
    "$GATEWAY_URL/health" 2>&1 | tee "$output_file"

echo ""

# Test 2: Health endpoint (authenticated)
log "════════════════════════════════════════════════════════"
log "Test 2: Health Check Endpoint (Authenticated)"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_health_auth_${PROFILE}_${TIMESTAMP}.txt"

hey_cmd=(hey -n "$REQUESTS" -c "$CONCURRENCY" -t "$TIMEOUT")
if [ -n "$AUTH_HEADER" ]; then
    hey_cmd+=(-H "$AUTH_HEADER")
fi
hey_cmd+=("$GATEWAY_URL/health")

"${hey_cmd[@]}" 2>&1 | tee "$output_file"

echo ""

# Test 3: Admin API - List Tools
log "════════════════════════════════════════════════════════"
log "Test 3: Admin API - List Tools (Registry Performance)"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_admin_list_tools_${PROFILE}_${TIMESTAMP}.txt"

hey_cmd=(hey -n "$REQUESTS" -c "$CONCURRENCY" -t "$TIMEOUT")
if [ -n "$AUTH_HEADER" ]; then
    hey_cmd+=(-H "$AUTH_HEADER")
fi
hey_cmd+=("$GATEWAY_URL/tools")

"${hey_cmd[@]}" 2>&1 | tee "$output_file"

echo ""

# Test 4: Admin API - List Servers
log "════════════════════════════════════════════════════════"
log "Test 4: Admin API - List Servers"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_admin_list_servers_${PROFILE}_${TIMESTAMP}.txt"

hey_cmd=(hey -n "$REQUESTS" -c "$CONCURRENCY" -t "$TIMEOUT")
if [ -n "$AUTH_HEADER" ]; then
    hey_cmd+=(-H "$AUTH_HEADER")
fi
hey_cmd+=("$GATEWAY_URL/servers")

"${hey_cmd[@]}" 2>&1 | tee "$output_file"

echo ""

# Test 5: Admin API - List Gateways (Federation)
log "════════════════════════════════════════════════════════"
log "Test 5: Admin API - List Gateways (Federation Discovery)"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_admin_list_gateways_${PROFILE}_${TIMESTAMP}.txt"

hey_cmd=(hey -n "$REQUESTS" -c "$CONCURRENCY" -t "$TIMEOUT")
if [ -n "$AUTH_HEADER" ]; then
    hey_cmd+=(-H "$AUTH_HEADER")
fi
hey_cmd+=("$GATEWAY_URL/gateways")

"${hey_cmd[@]}" 2>&1 | tee "$output_file"

echo ""

# Test 6: Metrics endpoint
log "════════════════════════════════════════════════════════"
log "Test 6: Prometheus Metrics Endpoint"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_metrics_${PROFILE}_${TIMESTAMP}.txt"

hey -n 1000 -c 10 -t "$TIMEOUT" \
    "$GATEWAY_URL/metrics" 2>&1 | tee "$output_file"

echo ""

# Test 7: OpenAPI spec
log "════════════════════════════════════════════════════════"
log "Test 7: OpenAPI Specification Endpoint"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_openapi_${PROFILE}_${TIMESTAMP}.txt"

hey -n 1000 -c 10 -t "$TIMEOUT" \
    "$GATEWAY_URL/openapi.json" 2>&1 | tee "$output_file"

echo ""

# Test 8: Static file serving (if admin UI enabled)
log "════════════════════════════════════════════════════════"
log "Test 8: Admin UI Static Files"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_admin_ui_${PROFILE}_${TIMESTAMP}.txt"

hey -n 5000 -c 25 -t "$TIMEOUT" \
    "$GATEWAY_URL/admin" 2>&1 | tee "$output_file"

echo ""

# Test 9: Authentication endpoint
log "════════════════════════════════════════════════════════"
log "Test 9: Token Generation (Login Performance)"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_token_generation_${PROFILE}_${TIMESTAMP}.txt"

# Create login payload
LOGIN_PAYLOAD=$(cat <<EOF
{
    "username": "admin@example.com",
    "password": "changeme"
}
EOF
)

echo "$LOGIN_PAYLOAD" > /tmp/login_payload.json

hey -n 1000 -c 10 -t "$TIMEOUT" \
    -m POST \
    -T "application/json" \
    -D /tmp/login_payload.json \
    "$GATEWAY_URL/token" 2>&1 | tee "$output_file" || log "Token endpoint might not exist"

rm -f /tmp/login_payload.json

echo ""

# Test 10: Rate limiting behavior
log "════════════════════════════════════════════════════════"
log "Test 10: Rate Limiting Test"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_rate_limiting_${PROFILE}_${TIMESTAMP}.txt"

log "Sending rapid burst to test rate limiting..."
hey -n 5000 -c 100 -t 10 \
    "$GATEWAY_URL/health" 2>&1 | tee "$output_file"

# Check for 429 responses
rate_limit_hits=$(grep "429" "$output_file" 2>/dev/null | wc -l || echo 0)
if [ "$rate_limit_hits" -gt 0 ] 2>/dev/null; then
    log "✅ Rate limiting working - $rate_limit_hits requests throttled"
else
    info "ℹ️  No rate limiting detected (may not be configured)"
fi

echo ""

# Test 11: Error handling - invalid JSON
log "════════════════════════════════════════════════════════"
log "Test 11: Error Handling - Invalid JSON"
log "════════════════════════════════════════════════════════"

output_file="$RESULTS_DIR/gateway_error_handling_${PROFILE}_${TIMESTAMP}.txt"

echo "invalid json{" > /tmp/invalid.json

hey_cmd=(
    hey -n 100 -c 5 -t "$TIMEOUT"
    -m POST
    -T "application/json"
    -D /tmp/invalid.json
)

if [ -n "$AUTH_HEADER" ]; then
    hey_cmd+=(-H "$AUTH_HEADER")
fi

hey_cmd+=("$GATEWAY_URL/rpc")

"${hey_cmd[@]}" 2>&1 | tee "$output_file" || true

rm -f /tmp/invalid.json

# Check for proper 400 responses
status_400=$(grep "400" "$output_file" 2>/dev/null | wc -l || echo 0)
if [ "$status_400" -gt 0 ] 2>/dev/null; then
    log "✅ Proper error handling - $status_400 × 400 Bad Request"
fi

echo ""
log "✅ Gateway core benchmark completed"
log "Results directory: $RESULTS_DIR"
