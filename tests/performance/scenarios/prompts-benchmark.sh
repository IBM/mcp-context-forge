#!/usr/bin/env bash
# ==============================================================================
# Prompt Execution Performance Benchmark
# Tests MCP prompt execution performance through the gateway
# ==============================================================================

set -Eeuo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." &>/dev/null && pwd)"

# Configuration
GATEWAY_URL="${GATEWAY_URL:-http://localhost:4444}"
PROFILE="${PROFILE:-medium}"
RESULTS_DIR="$PROJECT_ROOT/tests/performance/results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Load profile
PROFILE_FILE="$PROJECT_ROOT/tests/performance/profiles/$PROFILE.env"
if [ ! -f "$PROFILE_FILE" ]; then
    error "Profile $PROFILE not found at $PROFILE_FILE"
    exit 1
fi

# shellcheck disable=SC1090
source "$PROFILE_FILE"

log "🔧 Prompt Execution Performance Benchmark"
log "Profile: $PROFILE"
log "Requests: $REQUESTS"
log "Concurrency: $CONCURRENCY"
log "Gateway: $GATEWAY_URL"

# Create results directory
mkdir -p "$RESULTS_DIR"

# Load auth token if available
if [ -f "$PROJECT_ROOT/tests/performance/.auth_token" ]; then
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/tests/performance/.auth_token"
fi

AUTH_HEADER=""
if [ -n "${MCPGATEWAY_BEARER_TOKEN:-}" ]; then
    AUTH_HEADER="Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
    info "Using authentication token"
fi

# Check if hey is installed
if ! command -v hey &>/dev/null; then
    error "hey is not installed. Install it with: brew install hey (macOS) or go install github.com/rakyll/hey@latest"
    exit 1
fi

run_test() {
    local test_name=$1
    local payload_file=$2
    local endpoint="${3:-$GATEWAY_URL/rpc}"

    log "Running test: $test_name"

    local output_file="$RESULTS_DIR/prompts_${test_name}_${PROFILE}_${TIMESTAMP}.txt"

    local hey_cmd=(
        hey
        -n "$REQUESTS"
        -c "$CONCURRENCY"
        -m POST
        -T "application/json"
        -D "$payload_file"
        -t "$TIMEOUT"
    )

    if [ -n "$AUTH_HEADER" ]; then
        hey_cmd+=(-H "$AUTH_HEADER")
    fi

    hey_cmd+=("$endpoint")

    info "Command: ${hey_cmd[*]}"

    # Run and save results
    "${hey_cmd[@]}" 2>&1 | tee "$output_file"

    log "Results saved to: $output_file"
    echo ""
}

# Test 1: List prompts (discovery)
log "════════════════════════════════════════════════════════"
log "Test 1: List Prompts (Discovery)"
log "════════════════════════════════════════════════════════"
run_test "list_prompts" \
    "$PROJECT_ROOT/tests/performance/payloads/prompts/list_prompts.json" \
    "$GATEWAY_URL/rpc"

# Test 2: Get compare timezones prompt (prompt with arguments)
log "════════════════════════════════════════════════════════"
log "Test 2: Get Compare Timezones Prompt"
log "════════════════════════════════════════════════════════"
run_test "get_compare_timezones" \
    "$PROJECT_ROOT/tests/performance/payloads/prompts/get_compare_timezones.json" \
    "$GATEWAY_URL/rpc"

# Test 3: Get customer greeting prompt (template with required and optional arguments)
log "════════════════════════════════════════════════════════"
log "Test 3: Get Customer Greeting Prompt (Template Arguments)"
log "════════════════════════════════════════════════════════"
run_test "get_customer_greeting" \
    "$PROJECT_ROOT/tests/performance/payloads/prompts/get_customer_greeting.json" \
    "$GATEWAY_URL/rpc"

log "✅ Prompt benchmark completed successfully"
log "Results directory: $RESULTS_DIR"
