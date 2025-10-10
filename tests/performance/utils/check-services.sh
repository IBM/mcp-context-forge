#!/usr/bin/env bash
# ==============================================================================
# Service health checker for performance tests
# Verifies that gateway and fast-time-server are ready
# ==============================================================================

set -Eeuo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

# Configuration
GATEWAY_URL="${GATEWAY_URL:-http://localhost:4444}"
FAST_TIME_URL="${FAST_TIME_URL:-http://localhost:8888}"
MAX_RETRIES="${MAX_RETRIES:-30}"
RETRY_DELAY="${RETRY_DELAY:-2}"

check_service() {
    local name=$1
    local url=$2
    local max_retries=$3
    local retry_delay=$4

    log "Checking $name at $url..."

    for i in $(seq 1 "$max_retries"); do
        if curl -f -s -o /dev/null -w "%{http_code}" "$url/health" | grep -q "200"; then
            log "✅ $name is healthy"
            return 0
        fi

        warn "Waiting for $name... ($i/$max_retries)"
        sleep "$retry_delay"
    done

    error "$name failed to become healthy after $max_retries attempts"
    return 1
}

# Check gateway
if ! check_service "Gateway" "$GATEWAY_URL" "$MAX_RETRIES" "$RETRY_DELAY"; then
    error "Gateway is not available. Please start it with: make compose-up"
    exit 1
fi

# Check fast-time-server
if ! check_service "Fast Time Server" "$FAST_TIME_URL" "$MAX_RETRIES" "$RETRY_DELAY"; then
    error "Fast Time Server is not available. Please start it with: make compose-up"
    exit 1
fi

log "✅ All services are healthy and ready for testing"
