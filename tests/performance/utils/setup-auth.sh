#!/usr/bin/env bash
# ==============================================================================
# Authentication setup for performance tests
# Generates JWT token for authenticated API requests
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
JWT_SECRET="${JWT_SECRET:-my-test-key}"
JWT_ALGO="${JWT_ALGO:-HS256}"
USERNAME="${USERNAME:-admin@example.com}"
EXPIRATION="${EXPIRATION:-10080}" # 7 days in minutes

log "Generating JWT token for performance tests..."
log "  Username: $USERNAME"
log "  Expiration: $EXPIRATION minutes"
log "  Algorithm: $JWT_ALGO"

# Check if we're in the project root
if [ ! -f "mcpgateway/utils/create_jwt_token.py" ]; then
    error "Must be run from project root directory"
    exit 1
fi

# Activate virtual environment if available
if [ -f "/home/cmihai/.venv/mcpgateway/bin/activate" ]; then
    # shellcheck disable=SC1091
    source /home/cmihai/.venv/mcpgateway/bin/activate
fi

# Generate token
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username "$USERNAME" \
    --exp "$EXPIRATION" \
    --secret "$JWT_SECRET" \
    --algo "$JWT_ALGO" 2>/dev/null)

if [ -z "$TOKEN" ]; then
    error "Failed to generate JWT token"
    exit 1
fi

# Export token
export MCPGATEWAY_BEARER_TOKEN="$TOKEN"

# Save to file for easy sourcing
echo "export MCPGATEWAY_BEARER_TOKEN='$TOKEN'" > tests/performance/.auth_token

log "✅ Token generated successfully"
log "Token saved to: tests/performance/.auth_token"
log ""
log "To use in your shell, run:"
log "  source tests/performance/.auth_token"
log ""
log "Or in scripts:"
log "  export MCPGATEWAY_BEARER_TOKEN='$TOKEN'"

# Print the token (useful for CI/CD)
echo "$TOKEN"
