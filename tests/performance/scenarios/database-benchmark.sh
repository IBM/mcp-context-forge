#!/usr/bin/env bash
# ==============================================================================
# Database Connection Pool Performance Testing
# Tests database connection pool behavior under load
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

REQUESTS="${REQUESTS:-1000}"
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

log "🗄️  Database Connection Pool Performance Test"
log "Profile: $PROFILE"
log "Gateway: $GATEWAY_URL"
echo ""

# Test 1: Connection pool stress - increasing concurrency
log "════════════════════════════════════════════════════════"
log "Test 1: Connection Pool Stress (Increasing Concurrency)"
log "════════════════════════════════════════════════════════"

for concurrency in 10 25 50 100 150 200; do
    log "Testing with $concurrency concurrent connections..."

    output_file="$RESULTS_DIR/db_pool_stress_${concurrency}_${PROFILE}_${TIMESTAMP}.txt"

    hey_cmd=(
        hey
        -n "$REQUESTS"
        -c "$concurrency"
        -m POST
        -T "application/json"
        -D "$PROJECT_ROOT/tests/performance/payloads/tools/list_tools.json"
        -t "$TIMEOUT"
    )

    if [ -n "$AUTH_HEADER" ]; then
        hey_cmd+=(-H "$AUTH_HEADER")
    fi

    hey_cmd+=("$GATEWAY_URL/rpc")

    "${hey_cmd[@]}" 2>&1 | tee "$output_file"

    # Check error rate
    error_count=$(grep "Error" "$output_file" 2>/dev/null | wc -l || echo 0)
    if [ "$error_count" -gt 0 ] 2>/dev/null; then
        error "⚠️  Detected $error_count errors at concurrency $concurrency"
        error "Possible connection pool exhaustion"
    else
        log "✅ No errors at concurrency $concurrency"
    fi

    # Cool down between tests
    sleep 5
done

echo ""

# Test 2: Sustained load - long duration
log "════════════════════════════════════════════════════════"
log "Test 2: Sustained Load (Connection Pool Stability)"
log "════════════════════════════════════════════════════════"

log "Running sustained test for 60 seconds at 50 concurrent connections..."

output_file="$RESULTS_DIR/db_sustained_load_${PROFILE}_${TIMESTAMP}.txt"

hey_cmd=(
    hey
    -z 60s
    -c 50
    -m POST
    -T "application/json"
    -D "$PROJECT_ROOT/tests/performance/payloads/tools/list_tools.json"
    -t "$TIMEOUT"
)

if [ -n "$AUTH_HEADER" ]; then
    hey_cmd+=(-H "$AUTH_HEADER")
fi

hey_cmd+=("$GATEWAY_URL/rpc")

"${hey_cmd[@]}" 2>&1 | tee "$output_file"

echo ""

# Test 3: Burst load - connection acquisition speed
log "════════════════════════════════════════════════════════"
log "Test 3: Burst Load (Connection Acquisition Speed)"
log "════════════════════════════════════════════════════════"

for burst_size in 100 500 1000; do
    log "Testing burst of $burst_size requests with high concurrency..."

    output_file="$RESULTS_DIR/db_burst_${burst_size}_${PROFILE}_${TIMESTAMP}.txt"

    hey_cmd=(
        hey
        -n "$burst_size"
        -c 100
        -m POST
        -T "application/json"
        -D "$PROJECT_ROOT/tests/performance/payloads/tools/list_tools.json"
        -t "$TIMEOUT"
    )

    if [ -n "$AUTH_HEADER" ]; then
        hey_cmd+=(-H "$AUTH_HEADER")
    fi

    hey_cmd+=("$GATEWAY_URL/rpc")

    "${hey_cmd[@]}" 2>&1 | tee "$output_file"

    sleep 3
done

echo ""

# Test 4: Connection pool recovery - test after overload
log "════════════════════════════════════════════════════════"
log "Test 4: Connection Pool Recovery"
log "════════════════════════════════════════════════════════"

log "Step 1: Overload the connection pool..."
hey -n 2000 -c 300 -m POST -T "application/json" \
    -D "$PROJECT_ROOT/tests/performance/payloads/tools/list_tools.json" \
    $([ -n "$AUTH_HEADER" ] && echo "-H \"$AUTH_HEADER\"") \
    -t "$TIMEOUT" \
    "$GATEWAY_URL/rpc" > /dev/null 2>&1 || true

log "Step 2: Wait for recovery (10 seconds)..."
sleep 10

log "Step 3: Test normal load after recovery..."
output_file="$RESULTS_DIR/db_recovery_test_${PROFILE}_${TIMESTAMP}.txt"

hey_cmd=(
    hey
    -n 500
    -c 25
    -m POST
    -T "application/json"
    -D "$PROJECT_ROOT/tests/performance/payloads/tools/list_tools.json"
    -t "$TIMEOUT"
)

if [ -n "$AUTH_HEADER" ]; then
    hey_cmd+=(-H "$AUTH_HEADER")
fi

hey_cmd+=("$GATEWAY_URL/rpc")

"${hey_cmd[@]}" 2>&1 | tee "$output_file"

# Check recovery
error_count=$(grep "Error" "$output_file" 2>/dev/null | wc -l || echo 0)
if [ "$error_count" -eq 0 ] 2>/dev/null; then
    log "✅ Connection pool recovered successfully"
else
    error "⚠️  Connection pool recovery issues detected"
fi

echo ""
log "✅ Database benchmark completed"
log "Results directory: $RESULTS_DIR"
