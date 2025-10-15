#!/usr/bin/env bash
# ==============================================================================
# Configurable Performance Test Runner
# Reads configuration from config.yaml and runs tests with monitoring and reporting
# ==============================================================================

set -Eeuo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
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

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

header() {
    echo ""
    echo -e "${MAGENTA}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║${NC} $1"
    echo -e "${MAGENTA}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Graceful shutdown handler
cleanup_partial_results() {
    log "Received shutdown signal, saving partial results..."

    # Stop monitoring if running
    if [ -n "${MONITOR_PID:-}" ]; then
        kill "$MONITOR_PID" 2>/dev/null || true
        wait "$MONITOR_PID" 2>/dev/null || true
    fi

    # Kill any background processes
    jobs -p | xargs -r kill 2>/dev/null || true

    # Save summary
    if [ -d "${RESULTS_DIR:-}" ]; then
        echo "Test interrupted at $(date)" > "$RESULTS_DIR/PARTIAL_RESULTS.txt"
        log "Partial results saved to: $RESULTS_DIR"
    fi

    # Exit with proper code for SIGINT (130)
    exit 130
}

# Enable immediate signal handling
trap 'cleanup_partial_results' SIGTERM SIGINT

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." &>/dev/null && pwd)"

# Configuration
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/config.yaml}"
PROFILE="${PROFILE:-medium}"
SKIP_SETUP="${SKIP_SETUP:-false}"
SKIP_WARMUP="${SKIP_WARMUP:-false}"
SKIP_MONITORING="${SKIP_MONITORING:-false}"
SKIP_REPORT="${SKIP_REPORT:-false}"

# Parse command-line arguments
usage() {
    cat <<EOF
Usage: ${0##*/} [options]

Configurable performance testing with monitoring and HTML reporting

Options:
  -c, --config <file>       Configuration file [default: config.yaml]
  -p, --profile <name>      Load profile (smoke, light, medium, heavy, sustained)
  --skip-setup              Skip service checks and auth setup
  --skip-warmup             Skip warmup requests
  --skip-monitoring         Skip system monitoring during tests
  --skip-report             Skip HTML report generation
  --scenario <name>         Run only specified scenario
  --list-scenarios          List available scenarios
  -h, --help                Display this help

Environment Variables:
  CONFIG_FILE               Path to config file
  PROFILE                   Load profile name
  SKIP_SETUP                Skip setup (true/false)
  SKIP_MONITORING           Skip monitoring (true/false)

Examples:
  # Run with default configuration
  $0

  # Run light profile with custom config
  $0 -p light -c my-config.yaml

  # Run only tools benchmark
  $0 --scenario tools_benchmark

  # Quick run without monitoring
  $0 -p smoke --skip-monitoring --skip-report

EOF
    exit 1
}

RUN_SCENARIO=""

while (( "$#" )); do
    case "$1" in
        -c|--config) CONFIG_FILE="$2"; shift 2 ;;
        -p|--profile) PROFILE="$2"; shift 2 ;;
        --skip-setup) SKIP_SETUP=true; shift ;;
        --skip-warmup) SKIP_WARMUP=true; shift ;;
        --skip-monitoring) SKIP_MONITORING=true; shift ;;
        --skip-report) SKIP_REPORT=true; shift ;;
        --scenario) RUN_SCENARIO="$2"; shift 2 ;;
        --list-scenarios)
            if [ -f "$CONFIG_FILE" ]; then
                echo "Available scenarios:"
                python3 -c "import yaml; config = yaml.safe_load(open('$CONFIG_FILE')); [print(f'  - {name}') for name in config.get('scenarios', {}).keys()]"
            else
                error "Config file not found: $CONFIG_FILE"
            fi
            exit 0
            ;;
        -h|--help) usage ;;
        *) error "Unknown option: $1"; usage ;;
    esac
done

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    error "Configuration file not found: $CONFIG_FILE"
    exit 1
fi

# Check for required tools
command -v python3 >/dev/null 2>&1 || { error "python3 is required but not installed"; exit 1; }
command -v hey >/dev/null 2>&1 || { error "hey is required but not installed. Install with: brew install hey"; exit 1; }

# Install yq for YAML parsing if not available, use Python as fallback
parse_yaml() {
    local key=$1
    python3 -c "import yaml, sys; config = yaml.safe_load(open('$CONFIG_FILE')); print(config$key)" 2>/dev/null || echo ""
}

# Banner
header "🚀 Configurable Performance Test Runner"
log "Configuration: $CONFIG_FILE"
log "Profile: $PROFILE"
log "Project Root: $PROJECT_ROOT"
echo ""

# Create results directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_BASE="${RESULTS_BASE:-$SCRIPT_DIR/results}"
RESULTS_DIR="$RESULTS_BASE/${PROFILE}_${TIMESTAMP}"
mkdir -p "$RESULTS_DIR"

log "Results directory: $RESULTS_DIR"

# Parse configuration using Python
parse_config() {
    python3 <<EOF
import yaml
import json
import sys

with open('$CONFIG_FILE') as f:
    config = yaml.safe_load(f)

profile = config['profiles']['$PROFILE']
environment = config['environment']
scenarios = config['scenarios']
monitoring = config.get('monitoring', {})
reporting = config.get('reporting', {})

output = {
    'gateway_url': environment.get('gateway_url', 'http://localhost:4444'),
    'requests': profile['requests'],
    'concurrency': profile['concurrency'],
    'duration': profile['duration'],
    'timeout': profile['timeout'],
    'scenarios': {name: data for name, data in scenarios.items() if data.get('enabled', True)},
    'monitoring_enabled': monitoring.get('enabled', False),
    'monitoring_interval': monitoring.get('interval_seconds', 5),
    'reporting_enabled': reporting.get('enabled', True),
}

print(json.dumps(output))
EOF
}

CONFIG_JSON=$(parse_config)
GATEWAY_URL=$(echo "$CONFIG_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['gateway_url'])")
REQUESTS=$(echo "$CONFIG_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['requests'])")
CONCURRENCY=$(echo "$CONFIG_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['concurrency'])")
TIMEOUT=$(echo "$CONFIG_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['timeout'])")
MONITORING_ENABLED=$(echo "$CONFIG_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['monitoring_enabled'])")
REPORTING_ENABLED=$(echo "$CONFIG_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['reporting_enabled'])")

export GATEWAY_URL
export REQUESTS
export CONCURRENCY
export TIMEOUT

log "Gateway URL: $GATEWAY_URL"
log "Requests: $REQUESTS, Concurrency: $CONCURRENCY, Timeout: ${TIMEOUT}s"

# Step 1: Check services
if [ "$SKIP_SETUP" = false ]; then
    header "📋 Step 1: Checking Service Health"
    if ! bash "$SCRIPT_DIR/utils/check-services.sh"; then
        error "Services are not healthy. Please run: make compose-up"
        exit 1
    fi
else
    warn "Skipping service health checks"
fi

# Step 2: Setup authentication
if [ "$SKIP_SETUP" = false ]; then
    header "🔐 Step 2: Setting Up Authentication"
    if ! bash "$SCRIPT_DIR/utils/setup-auth.sh" > /dev/null 2>&1; then
        error "Failed to setup authentication"
        exit 1
    fi
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.auth_token"
    export MCPGATEWAY_BEARER_TOKEN
    success "Authentication configured"
else
    warn "Skipping authentication setup"
fi

# Step 3: Start monitoring
MONITOR_PID=""
if [ "$SKIP_MONITORING" = false ] && [ "$MONITORING_ENABLED" = "True" ]; then
    header "📊 Step 3: Starting System Monitoring"

    # Start background monitoring
    {
        while true; do
            echo "$(date +%s),$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1),$(free | grep Mem | awk '{print ($3/$2) * 100.0}')" >> "$RESULTS_DIR/system_metrics.csv"

            # Docker stats if available
            if command -v docker >/dev/null 2>&1; then
                docker stats --no-stream --format "{{.Container}},{{.CPUPerc}},{{.MemPerc}}" >> "$RESULTS_DIR/docker_stats.csv" 2>/dev/null
            fi

            sleep "${MONITORING_INTERVAL:-5}"
        done
    } &
    MONITOR_PID=$!
    success "Monitoring started (PID: $MONITOR_PID)"
else
    info "Monitoring disabled"
fi

# Step 4: Warmup
if [ "$SKIP_WARMUP" = false ]; then
    header "🔥 Step 4: Warmup"
    log "Sending 100 warmup requests..."

    hey -n 100 -c 10 -m GET "$GATEWAY_URL/health" >/dev/null 2>&1 || true

    success "Warmup complete"
    sleep 5
else
    warn "Skipping warmup"
fi

# Step 5: Run test scenarios
header "🧪 Step 5: Running Test Scenarios"

run_test() {
    local test_name=$1
    local payload_file=$2
    local endpoint=$3
    local method=${4:-POST}

    local full_endpoint="${GATEWAY_URL}${endpoint}"

    log "Running: $test_name"

    local output_file="$RESULTS_DIR/${test_name}_${PROFILE}_${TIMESTAMP}.txt"

    local hey_cmd=(hey -n "$REQUESTS" -c "$CONCURRENCY" -t "$TIMEOUT" -m "$method")

    if [ "$method" = "POST" ] && [ -n "$payload_file" ] && [ -f "$SCRIPT_DIR/$payload_file" ]; then
        hey_cmd+=(-T "application/json" -D "$SCRIPT_DIR/$payload_file")
    fi

    if [ -n "${MCPGATEWAY_BEARER_TOKEN:-}" ]; then
        hey_cmd+=(-H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN")
    fi

    hey_cmd+=("$full_endpoint")

    # Run test
    if "${hey_cmd[@]}" > "$output_file" 2>&1; then
        # Extract key metrics for quick summary
        local rps=$(grep "Requests/sec:" "$output_file" | awk '{print $2}')
        local p95=$(grep "95%" "$output_file" | awk '{print $4}' | head -1)
        info "  → RPS: $rps, p95: $p95"
        return 0
    else
        error "  → Test failed"
        return 1
    fi
}

# Parse scenarios from config and run them
FAILED_TESTS=()

python3 <<EOF | while IFS='|' read -r scenario_name test_name payload endpoint method; do
import yaml
import sys

with open('$CONFIG_FILE') as f:
    config = yaml.safe_load(f)

scenarios = config.get('scenarios', {})
run_scenario = '$RUN_SCENARIO'

for scenario_name, scenario_data in scenarios.items():
    # Skip if not enabled or if specific scenario requested
    if not scenario_data.get('enabled', True):
        continue
    if run_scenario and scenario_name != run_scenario:
        continue

    tests = scenario_data.get('tests', [])
    for test in tests:
        test_name = test['name']
        payload = test.get('payload', '')
        endpoint = test.get('endpoint', '/rpc')
        method = test.get('method', 'POST')

        # Format: scenario_name|test_name|payload|endpoint|method
        print(f"{scenario_name}|{test_name}|{payload}|{endpoint}|{method}")
EOF

    if [ -n "$scenario_name" ]; then
        if ! run_test "${scenario_name}_${test_name}" "$payload" "$endpoint" "$method"; then
            FAILED_TESTS+=("${scenario_name}/${test_name}")
        fi

        # Cooldown between tests
        sleep 2
    fi
done

# Step 6: Stop monitoring
if [ -n "$MONITOR_PID" ]; then
    header "📊 Step 6: Stopping Monitoring"
    kill "$MONITOR_PID" 2>/dev/null || true
    success "Monitoring stopped"
fi

# Step 7: Collect additional metrics
header "📈 Step 7: Collecting Metrics"

# Save Prometheus metrics if available
if curl -sf "$GATEWAY_URL/metrics" > "$RESULTS_DIR/prometheus_metrics.txt" 2>/dev/null; then
    success "Prometheus metrics collected"
fi

# Save application logs
if command -v docker >/dev/null 2>&1; then
    docker logs gateway --tail 1000 > "$RESULTS_DIR/gateway_logs.txt" 2>&1 || true
    success "Application logs collected"
fi

# Step 8: Generate HTML report
if [ "$SKIP_REPORT" = false ] && [ "$REPORTING_ENABLED" = "True" ]; then
    header "📄 Step 8: Generating HTML Report"

    REPORT_FILE="$SCRIPT_DIR/reports/performance_report_${PROFILE}_${TIMESTAMP}.html"

    if python3 "$SCRIPT_DIR/utils/report_generator.py" \
        --results-dir "$RESULTS_DIR" \
        --output "$REPORT_FILE" \
        --config "$CONFIG_FILE" \
        --profile "$PROFILE"; then

        success "Report generated: $REPORT_FILE"

        # Try to open in browser (optional)
        if command -v xdg-open >/dev/null 2>&1; then
            info "Opening report in browser..."
            xdg-open "$REPORT_FILE" 2>/dev/null || true
        elif command -v open >/dev/null 2>&1; then
            info "Opening report in browser..."
            open "$REPORT_FILE" 2>/dev/null || true
        fi
    else
        error "Failed to generate report"
    fi
else
    info "Report generation disabled"
fi

# Final summary
header "🎉 Test Run Complete"
log "Profile: $PROFILE"
log "Results: $RESULTS_DIR"
log "Duration: $SECONDS seconds"

if [ ${#FAILED_TESTS[@]} -eq 0 ]; then
    success "All tests completed successfully! ✅"
    exit 0
else
    error "Some tests failed: ${FAILED_TESTS[*]}"
    exit 1
fi
