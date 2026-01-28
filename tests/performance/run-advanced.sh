#!/usr/bin/env bash
# ==============================================================================
# Advanced Performance Test Runner with Server Profile Support
# Supports infrastructure switching, database version comparison, and more
# ==============================================================================

set -Eeuo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
header() {
    echo ""
    echo -e "${MAGENTA}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║${NC} $1"
    echo -e "${MAGENTA}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Graceful shutdown handler
cleanup_on_interrupt() {
    warn "Received interrupt signal, cleaning up..."

    # Kill any child processes
    jobs -p | xargs -r kill 2>/dev/null || true

    # Exit with proper code for SIGINT (130)
    exit 130
}

# Set up signal handling - MUST be before any long-running operations
trap 'cleanup_on_interrupt' SIGTERM SIGINT

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." &>/dev/null && pwd)"

# Configuration
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/config.yaml}"
PROFILE="${PROFILE:-medium}"
SERVER_PROFILE="${SERVER_PROFILE:-standard}"
INFRASTRUCTURE="${INFRASTRUCTURE:-}"
POSTGRES_VERSION="${POSTGRES_VERSION:-}"
INSTANCES="${INSTANCES:-}"
SAVE_BASELINE="${SAVE_BASELINE:-}"
COMPARE_WITH="${COMPARE_WITH:-}"
SKIP_SETUP="${SKIP_SETUP:-false}"
SKIP_MONITORING="${SKIP_MONITORING:-false}"
SKIP_REPORT="${SKIP_REPORT:-false}"
RESTORE_COMPOSE="${RESTORE_COMPOSE:-true}"

usage() {
    cat <<EOF
Usage: ${0##*/} [options]

Advanced performance testing with infrastructure and server profile support

Test Profile Options:
  -p, --profile <name>           Load profile (smoke, light, medium, heavy)

Server Configuration:
  --server-profile <name>        Server profile (minimal, standard, optimized, etc.)
  --infrastructure <name>        Infrastructure profile (development, staging, production)
  --postgres-version <ver>       PostgreSQL version (e.g., 17-alpine)
  --instances <n>                Number of gateway instances

Baseline & Comparison:
  --save-baseline <file>         Save results as baseline
  --compare-with <file>          Compare results with baseline

Test Control:
  --skip-setup                   Skip service checks and auth
  --skip-monitoring              Skip system monitoring
  --skip-report                  Skip HTML report generation
  --no-restore                   Don't restore original docker-compose

List Options:
  --list-profiles                List available profiles
  --list-server-profiles         List server profiles
  --list-infrastructure          List infrastructure profiles

Examples:
  # Test with optimized server profile
  $0 -p medium --server-profile optimized

  # Test production infrastructure
  $0 -p heavy --infrastructure production

  # Compare PostgreSQL versions
  $0 -p medium --postgres-version 15-alpine --save-baseline pg15.json
  $0 -p medium --postgres-version 17-alpine --compare-with pg15.json

  # Test with 4 gateway instances
  $0 -p heavy --instances 4

EOF
    exit 1
}

# Parse arguments
while (( "$#" )); do
    case "$1" in
        -p|--profile) PROFILE="$2"; shift 2 ;;
        --server-profile) SERVER_PROFILE="$2"; shift 2 ;;
        --infrastructure) INFRASTRUCTURE="$2"; shift 2 ;;
        --postgres-version) POSTGRES_VERSION="$2"; shift 2 ;;
        --instances) INSTANCES="$2"; shift 2 ;;
        --save-baseline) SAVE_BASELINE="$2"; shift 2 ;;
        --compare-with) COMPARE_WITH="$2"; shift 2 ;;
        --skip-setup) SKIP_SETUP=true; shift ;;
        --skip-monitoring) SKIP_MONITORING=true; shift ;;
        --skip-report) SKIP_REPORT=true; shift ;;
        --no-restore) RESTORE_COMPOSE=false; shift ;;
        --list-profiles)
            python3 "$SCRIPT_DIR/utils/generate_docker_compose.py" --config "$CONFIG_FILE" --list-profiles
            exit 0
            ;;
        --list-server-profiles)
            python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); [print(f'{k}: {v.get(\"description\",\"\")}') for k,v in c.get('server_profiles',{}).items()]"
            exit 0
            ;;
        --list-infrastructure)
            python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); [print(f'{k}: {v.get(\"description\",\"\")}') for k,v in c.get('infrastructure_profiles',{}).items()]"
            exit 0
            ;;
        -h|--help) usage ;;
        *) error "Unknown option: $1"; usage ;;
    esac
done

# Banner
header "🚀 Advanced Performance Test Runner"
log "Profile: $PROFILE"
log "Server Profile: $SERVER_PROFILE"
[ -n "$INFRASTRUCTURE" ] && log "Infrastructure: $INFRASTRUCTURE"
[ -n "$POSTGRES_VERSION" ] && log "PostgreSQL: $POSTGRES_VERSION"
[ -n "$INSTANCES" ] && log "Instances: $INSTANCES"
echo ""

# Create results directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_BASE="${RESULTS_BASE:-$SCRIPT_DIR/results}"
RESULTS_DIR="$RESULTS_BASE/${PROFILE}_${SERVER_PROFILE}_${TIMESTAMP}"
mkdir -p "$RESULTS_DIR"

log "Results directory: $RESULTS_DIR"

# Step 1: Backup original docker-compose if infrastructure switching
COMPOSE_BACKUP=""
if [ -n "$INFRASTRUCTURE" ] || [ -n "$POSTGRES_VERSION" ] || [ -n "$INSTANCES" ]; then
    header "📋 Step 1: Infrastructure Configuration"

    COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
    COMPOSE_BACKUP="$SCRIPT_DIR/docker-compose.backup_${TIMESTAMP}.yml"

    if [ -f "$COMPOSE_FILE" ]; then
        cp "$COMPOSE_FILE" "$COMPOSE_BACKUP"
        success "Backed up docker-compose.yml to $(basename "$COMPOSE_BACKUP")"
    fi

    # Generate new docker-compose
    NEW_COMPOSE="$SCRIPT_DIR/docker-compose.perf.yml"

    GEN_ARGS=(
        --config "$CONFIG_FILE"
        --server-profile "$SERVER_PROFILE"
        --output "$NEW_COMPOSE"
    )

    [ -n "$INFRASTRUCTURE" ] && GEN_ARGS+=(--infrastructure "$INFRASTRUCTURE")
    [ -n "$POSTGRES_VERSION" ] && GEN_ARGS+=(--postgres-version "$POSTGRES_VERSION")
    [ -n "$INSTANCES" ] && GEN_ARGS+=(--instances "$INSTANCES")

    if python3 "$SCRIPT_DIR/utils/generate_docker_compose.py" "${GEN_ARGS[@]}"; then
        # Copy to project root
        cp "$NEW_COMPOSE" "$COMPOSE_FILE"
        success "Applied new docker-compose configuration"

        # Restart services
        log "Stopping current services..."
        cd "$PROJECT_ROOT"
        docker-compose down || true

        log "Starting services with new configuration..."
        docker-compose up -d

        # Wait for health checks
        log "Waiting for services to be healthy..."
        sleep 30
    else
        error "Failed to generate docker-compose"
        exit 1
    fi
fi

# Step 2: Apply server profile environment variables
if [ "$SERVER_PROFILE" != "standard" ] || [ -n "$INFRASTRUCTURE" ]; then
    header "⚙️  Step 2: Applying Server Profile"

    # Extract server profile settings from config
    WORKERS=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print(c['server_profiles']['$SERVER_PROFILE'].get('gunicorn_workers', 4))")
    THREADS=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print(c['server_profiles']['$SERVER_PROFILE'].get('gunicorn_threads', 4))")
    TIMEOUT=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print(c['server_profiles']['$SERVER_PROFILE'].get('gunicorn_timeout', 120))")
    DB_POOL=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print(c['server_profiles']['$SERVER_PROFILE'].get('db_pool_size', 20))")
    DB_OVERFLOW=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print(c['server_profiles']['$SERVER_PROFILE'].get('db_pool_max_overflow', 40))")

    info "Workers: $WORKERS, Threads: $THREADS"
    info "DB Pool: $DB_POOL (max overflow: $DB_OVERFLOW)"

    # Note: These are already in docker-compose if generated, but we log them
    success "Server profile applied via docker-compose"
fi

# Step 3: Service health checks
if [ "$SKIP_SETUP" = false ]; then
    header "🏥 Step 3: Service Health Checks"
    if bash "$SCRIPT_DIR/utils/check-services.sh"; then
        success "All services healthy"
    else
        error "Services not healthy"
        exit 1
    fi
else
    warn "Skipping service health checks"
fi

# Step 4: Authentication
if [ "$SKIP_SETUP" = false ]; then
    header "🔐 Step 4: Authentication Setup"
    if bash "$SCRIPT_DIR/utils/setup-auth.sh" > /dev/null 2>&1; then
        # shellcheck disable=SC1091
        source "$SCRIPT_DIR/.auth_token"
        export MCPGATEWAY_BEARER_TOKEN
        success "Authentication configured"
    else
        error "Failed to setup authentication"
        exit 1
    fi
else
    warn "Skipping authentication setup"
fi

# Step 5: Run tests using the original configurable runner
header "🧪 Step 5: Running Performance Tests"

# Use the original run-configurable.sh for actual test execution
if bash "$SCRIPT_DIR/run-configurable.sh" -p "$PROFILE" --skip-setup; then
    success "Tests completed"
else
    error "Tests failed"
    TEST_FAILED=true
fi

# Step 6: Save baseline if requested
if [ -n "$SAVE_BASELINE" ]; then
    header "💾 Step 6: Saving Baseline"

    BASELINE_FILE="$SCRIPT_DIR/baselines/$SAVE_BASELINE"

    # Build metadata
    METADATA=$(cat <<EOF
{
  "profile": "$PROFILE",
  "server_profile": "$SERVER_PROFILE",
  "infrastructure": "$INFRASTRUCTURE",
  "postgres_version": "$POSTGRES_VERSION",
  "instances": "$INSTANCES",
  "timestamp": "$(date -Iseconds)"
}
EOF
)

    if python3 "$SCRIPT_DIR/utils/baseline_manager.py" save \
        "$RESULTS_DIR" \
        --output "$BASELINE_FILE" \
        --metadata "$METADATA"; then
        success "Baseline saved to $BASELINE_FILE"
    else
        error "Failed to save baseline"
    fi
fi

# Step 7: Compare with baseline if requested
if [ -n "$COMPARE_WITH" ]; then
    header "📊 Step 7: Comparing with Baseline"

    BASELINE_FILE="$SCRIPT_DIR/baselines/$COMPARE_WITH"

    if [ ! -f "$BASELINE_FILE" ]; then
        error "Baseline file not found: $BASELINE_FILE"
    else
        # Create current baseline from results
        CURRENT_BASELINE="/tmp/current_baseline_${TIMESTAMP}.json"

        python3 "$SCRIPT_DIR/utils/baseline_manager.py" save \
            "$RESULTS_DIR" \
            --output "$CURRENT_BASELINE" \
            --metadata "{\"profile\": \"$PROFILE\"}" > /dev/null

        # Compare
        COMPARISON_FILE="$RESULTS_DIR/comparison_vs_$(basename "$COMPARE_WITH" .json).json"

        if python3 "$SCRIPT_DIR/utils/compare_results.py" \
            "$BASELINE_FILE" \
            "$CURRENT_BASELINE" \
            --output "$COMPARISON_FILE"; then
            success "Comparison complete"

            # Check for regressions
            VERDICT=$(python3 -c "import json; print(json.load(open('$COMPARISON_FILE'))['verdict'])")
            case "$VERDICT" in
                recommended)
                    success "✅ RECOMMENDED - Significant improvements detected"
                    ;;
                acceptable)
                    info "✓ ACCEPTABLE - No major regressions"
                    ;;
                caution)
                    warn "⚠️ CAUTION - Some regressions detected"
                    ;;
                not_recommended)
                    error "❌ NOT RECOMMENDED - Critical regressions detected"
                    ;;
            esac
        fi

        # Cleanup
        rm -f "$CURRENT_BASELINE"
    fi
fi

# Step 8: Restore original docker-compose
if [ -n "$COMPOSE_BACKUP" ] && [ "$RESTORE_COMPOSE" = true ]; then
    header "♻️  Step 8: Restoring Original Configuration"

    COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

    cp "$COMPOSE_BACKUP" "$COMPOSE_FILE"
    success "Restored original docker-compose.yml"

    cd "$PROJECT_ROOT"
    log "Restarting services with original configuration..."
    docker-compose down || true
    docker-compose up -d

    log "Waiting for services..."
    sleep 20

    success "Services restored"
fi

# Final summary
header "🎉 Test Run Complete"
log "Profile: $PROFILE"
log "Server Profile: $SERVER_PROFILE"
[ -n "$INFRASTRUCTURE" ] && log "Infrastructure: $INFRASTRUCTURE"
log "Results: $RESULTS_DIR"
log "Duration: $SECONDS seconds"

if [ -n "$SAVE_BASELINE" ]; then
    log "Baseline saved: baselines/$SAVE_BASELINE"
fi

if [ -n "$COMPARE_WITH" ]; then
    log "Comparison: $RESULTS_DIR/comparison_vs_$(basename "$COMPARE_WITH" .json).json"
fi

success "All done! ✅"

exit 0
