#!/usr/bin/env bash
# ==============================================================================
# Mixed Workload Performance Benchmark
# Tests realistic mixed workload patterns (tools + resources + prompts)
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

log "🔧 Mixed Workload Performance Benchmark"
log "Profile: $PROFILE"
log "Requests per test: $REQUESTS"
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

# Array to store background process IDs
declare -a PIDS=()

run_concurrent_test() {
    local test_name=$1
    local payload_file=$2
    local endpoint="${3:-$GATEWAY_URL/rpc}"

    log "Starting concurrent test: $test_name"

    local output_file="$RESULTS_DIR/mixed_${test_name}_${PROFILE}_${TIMESTAMP}.txt"

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

    # Run in background and capture PID
    "${hey_cmd[@]}" > "$output_file" 2>&1 &
    PIDS+=($!)

    info "Started background test $test_name (PID: ${PIDS[-1]})"
}

log "════════════════════════════════════════════════════════"
log "Mixed Workload Test - Running All Tests Concurrently"
log "════════════════════════════════════════════════════════"

# Start all tests concurrently to simulate realistic mixed load
run_concurrent_test "list_tools" \
    "$PROJECT_ROOT/tests/performance/payloads/tools/list_tools.json"

run_concurrent_test "get_system_time" \
    "$PROJECT_ROOT/tests/performance/payloads/tools/get_system_time.json"

run_concurrent_test "convert_time" \
    "$PROJECT_ROOT/tests/performance/payloads/tools/convert_time.json"

run_concurrent_test "list_resources" \
    "$PROJECT_ROOT/tests/performance/payloads/resources/list_resources.json"

run_concurrent_test "read_timezone_info" \
    "$PROJECT_ROOT/tests/performance/payloads/resources/read_timezone_info.json"

run_concurrent_test "list_prompts" \
    "$PROJECT_ROOT/tests/performance/payloads/prompts/list_prompts.json"

# Wait for all background jobs to complete
log "Waiting for all concurrent tests to complete..."
FAILED=0
for pid in "${PIDS[@]}"; do
    if wait "$pid"; then
        info "Process $pid completed successfully"
    else
        error "Process $pid failed"
        FAILED=$((FAILED + 1))
    fi
done

if [ $FAILED -eq 0 ]; then
    log "✅ Mixed workload benchmark completed successfully"
    log "Results directory: $RESULTS_DIR"
    exit 0
else
    error "❌ Mixed workload benchmark completed with $FAILED failures"
    exit 1
fi
