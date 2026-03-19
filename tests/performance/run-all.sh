#!/usr/bin/env bash
# ==============================================================================
# Comprehensive Performance Test Runner
# Runs all performance benchmarks for ContextForge with fast-time-server
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

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." &>/dev/null && pwd)"

# Configuration
PROFILE="${PROFILE:-medium}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:4444}"
SKIP_SETUP="${SKIP_SETUP:-false}"
RUN_TOOLS="${RUN_TOOLS:-true}"
RUN_RESOURCES="${RUN_RESOURCES:-true}"
RUN_PROMPTS="${RUN_PROMPTS:-true}"
GENERATE_REPORT="${GENERATE_REPORT:-true}"

# Usage
usage() {
    cat <<EOF
Usage: ${0##*/} [options]

Comprehensive performance testing suite for ContextForge

Options:
  -p, --profile <name>      Load profile (light, medium, heavy) [default: medium]
  -u, --url <url>           Gateway URL [default: http://localhost:4444]
  --skip-setup              Skip service health checks and auth setup
  --tools-only              Run only tool benchmarks
  --resources-only          Run only resource benchmarks
  --prompts-only            Run only prompt benchmarks
  --no-report               Skip report generation
  -h, --help                Display this help and exit

Environment Variables:
  PROFILE                   Load profile (light, medium, heavy)
  GATEWAY_URL               Gateway URL
  SKIP_SETUP                Skip setup steps (true/false)

Examples:
  # Run all tests with medium profile
  $0

  # Run with light profile for quick testing
  $0 -p light

  # Run only tool benchmarks with heavy load
  $0 -p heavy --tools-only

  # Run all tests against a remote gateway
  $0 -u https://gateway.example.com

Before running:
  1. Start the stack: make compose-up
  2. Wait for services to be healthy
  3. Run this script

EOF
    exit 1
}

# Parse command-line arguments
while (( "$#" )); do
    case "$1" in
        -p|--profile) PROFILE="$2"; shift 2 ;;
        -u|--url) GATEWAY_URL="$2"; shift 2 ;;
        --skip-setup) SKIP_SETUP=true; shift ;;
        --tools-only) RUN_TOOLS=true; RUN_RESOURCES=false; RUN_PROMPTS=false; shift ;;
        --resources-only) RUN_TOOLS=false; RUN_RESOURCES=true; RUN_PROMPTS=false; shift ;;
        --prompts-only) RUN_TOOLS=false; RUN_RESOURCES=false; RUN_PROMPTS=true; shift ;;
        --no-report) GENERATE_REPORT=false; shift ;;
        -h|--help) usage ;;
        *) error "Unknown option: $1"; usage ;;
    esac
done

# Banner
header "🚀 ContextForge Performance Testing Suite"
log "Profile: $PROFILE"
log "Gateway: $GATEWAY_URL"
log "Project Root: $PROJECT_ROOT"
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Step 1: Check services (unless skipped)
if [ "$SKIP_SETUP" = false ]; then
    header "📋 Step 1: Checking Service Health"
    if ! bash "$SCRIPT_DIR/utils/check-services.sh"; then
        error "Services are not healthy. Please run: make compose-up"
        exit 1
    fi
else
    warn "Skipping service health checks"
fi

# Step 2: Setup authentication (unless skipped)
if [ "$SKIP_SETUP" = false ]; then
    header "🔐 Step 2: Setting Up Authentication"
    if ! bash "$SCRIPT_DIR/utils/setup-auth.sh" > /dev/null; then
        error "Failed to setup authentication"
        exit 1
    fi
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.auth_token"
    export MCPGATEWAY_BEARER_TOKEN
else
    warn "Skipping authentication setup"
fi

# Export configuration for child scripts
export PROFILE
export GATEWAY_URL

# Step 3: Run benchmarks
BENCHMARK_START=$(date +%s)
FAILED_TESTS=()

if [ "$RUN_TOOLS" = true ]; then
    header "🔧 Step 3a: Running Tool Invocation Benchmarks"
    if bash "$SCRIPT_DIR/scenarios/tools-benchmark.sh"; then
        success "Tool benchmarks completed"
    else
        error "Tool benchmarks failed"
        FAILED_TESTS+=("tools")
    fi
fi

if [ "$RUN_RESOURCES" = true ]; then
    header "📁 Step 3b: Running Resource Access Benchmarks"
    if bash "$SCRIPT_DIR/scenarios/resources-benchmark.sh"; then
        success "Resource benchmarks completed"
    else
        error "Resource benchmarks failed"
        FAILED_TESTS+=("resources")
    fi
fi

if [ "$RUN_PROMPTS" = true ]; then
    header "💬 Step 3c: Running Prompt Execution Benchmarks"
    if bash "$SCRIPT_DIR/scenarios/prompts-benchmark.sh"; then
        success "Prompt benchmarks completed"
    else
        error "Prompt benchmarks failed"
        FAILED_TESTS+=("prompts")
    fi
fi

BENCHMARK_END=$(date +%s)
TOTAL_TIME=$((BENCHMARK_END - BENCHMARK_START))

# Step 4: Generate summary report
if [ "$GENERATE_REPORT" = true ]; then
    header "📊 Step 4: Generating Summary Report"

    RESULTS_DIR="$PROJECT_ROOT/tests/performance/results"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    SUMMARY_FILE="$RESULTS_DIR/summary_${PROFILE}_${TIMESTAMP}.md"

    cat > "$SUMMARY_FILE" <<EOF
# Performance Test Summary

**Date:** $(date '+%Y-%m-%d %H:%M:%S')
**Profile:** $PROFILE
**Gateway:** $GATEWAY_URL
**Total Duration:** ${TOTAL_TIME}s

## Test Results

EOF

    # Count result files
    TOOL_RESULTS=$(find "$RESULTS_DIR" -name "tools_*_${PROFILE}_*.txt" -type f 2>/dev/null | wc -l || echo 0)
    RESOURCE_RESULTS=$(find "$RESULTS_DIR" -name "resources_*_${PROFILE}_*.txt" -type f 2>/dev/null | wc -l || echo 0)
    PROMPT_RESULTS=$(find "$RESULTS_DIR" -name "prompts_*_${PROFILE}_*.txt" -type f 2>/dev/null | wc -l || echo 0)

    cat >> "$SUMMARY_FILE" <<EOF
| Category  | Tests Run | Status |
|-----------|-----------|--------|
| Tools     | $TOOL_RESULTS | $([ "$RUN_TOOLS" = true ] && echo "✅ Complete" || echo "⏭️ Skipped") |
| Resources | $RESOURCE_RESULTS | $([ "$RUN_RESOURCES" = true ] && echo "✅ Complete" || echo "⏭️ Skipped") |
| Prompts   | $PROMPT_RESULTS | $([ "$RUN_PROMPTS" = true ] && echo "✅ Complete" || echo "⏭️ Skipped") |

## Failed Tests

EOF

    if [ ${#FAILED_TESTS[@]} -eq 0 ]; then
        echo "None ✅" >> "$SUMMARY_FILE"
    else
        for test in "${FAILED_TESTS[@]}"; do
            echo "- $test ❌" >> "$SUMMARY_FILE"
        done
    fi

    cat >> "$SUMMARY_FILE" <<EOF

## Results Location

All detailed results are available in: \`$RESULTS_DIR\`

## Next Steps

1. Review individual test results for detailed metrics
2. Compare with baseline performance
3. Investigate any failed tests or performance regressions
4. Adjust load profiles as needed for your use case

---
*Generated by ContextForge Performance Testing Suite*
EOF

    log "Summary report generated: $SUMMARY_FILE"
    echo ""
    cat "$SUMMARY_FILE"
fi

# Final status
header "🎉 Performance Testing Complete"
log "Total execution time: ${TOTAL_TIME}s"
log "Results directory: $RESULTS_DIR"

if [ ${#FAILED_TESTS[@]} -eq 0 ]; then
    success "All tests completed successfully! ✅"
    exit 0
else
    error "Some tests failed: ${FAILED_TESTS[*]}"
    exit 1
fi
