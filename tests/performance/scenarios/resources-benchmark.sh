#!/usr/bin/env bash
# ==============================================================================
# Resource Access Performance Benchmark
# Tests MCP resource access performance through the gateway
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

log "🔧 Resource Access Performance Benchmark"
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

    local output_file="$RESULTS_DIR/resources_${test_name}_${PROFILE}_${TIMESTAMP}.txt"

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

# Test 1: List resources (discovery)
log "════════════════════════════════════════════════════════"
log "Test 1: List Resources (Discovery)"
log "════════════════════════════════════════════════════════"
run_test "list_resources" \
    "$PROJECT_ROOT/tests/performance/payloads/resources/list_resources.json" \
    "$GATEWAY_URL/rpc"

# Test 2: Read welcome message (text resource)
log "════════════════════════════════════════════════════════"
log "Test 2: Read Welcome Message (Text Resource)"
log "════════════════════════════════════════════════════════"
run_test "read_timezone_info" \
    "$PROJECT_ROOT/tests/performance/payloads/resources/read_timezone_info.json" \
    "$GATEWAY_URL/rpc"

# Test 3: Read API documentation (markdown resource)
log "════════════════════════════════════════════════════════"
log "Test 3: Read API Documentation (Markdown Resource)"
log "════════════════════════════════════════════════════════"
run_test "read_world_times" \
    "$PROJECT_ROOT/tests/performance/payloads/resources/read_world_times.json" \
    "$GATEWAY_URL/rpc"

log "✅ Resource benchmark completed successfully"
log "Results directory: $RESULTS_DIR"
