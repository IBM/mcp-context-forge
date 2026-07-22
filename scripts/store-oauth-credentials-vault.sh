#!/bin/bash
# Store team-scoped OAuth credentials in Vault
#
# Usage:
#   ./scripts/store-oauth-credentials-vault.sh <team_id> <mcp_url> <client_id> <client_secret> [additional_fields_json]
#
# Example:
#   ./scripts/store-oauth-credentials-vault.sh \
#     "f8927490a44d4ede95889136d004c202" \
#     "https://mcp.github.acme.com" \
#     "Iv1.abc123def456" \
#     "secret_value_here" \
#     '{"authorization_url": "https://github.com/login/oauth/authorize", "token_url": "https://github.com/login/oauth/access_token", "scopes": ["repo", "read:org"]}'

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check arguments
if [ $# -lt 4 ]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    echo ""
    echo "Usage: $0 <team_id> <mcp_url> <client_id> <client_secret> [additional_fields_json]"
    echo ""
    echo "Example:"
    echo "  $0 \\"
    echo "    \"f8927490a44d4ede95889136d004c202\" \\"
    echo "    \"https://mcp.github.acme.com\" \\"
    echo "    \"Iv1.abc123def456\" \\"
    echo "    \"secret_value_here\" \\"
    echo "    '{\"authorization_url\": \"https://github.com/login/oauth/authorize\", \"token_url\": \"https://github.com/login/oauth/access_token\", \"scopes\": [\"repo\", \"read:org\"]}'"
    exit 1
fi

TEAM_ID="$1"
MCP_URL="$2"
CLIENT_ID="$3"
CLIENT_SECRET="$4"
ADDITIONAL_FIELDS="${5:-{}}"

# Load environment
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Vault configuration
VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-}"
VAULT_KV_MOUNT="${VAULT_KV_MOUNT:-secret}"
VAULT_KV_PATH_PREFIX="${VAULT_KV_PATH_PREFIX:-contextforge/oauth}"

if [ -z "$VAULT_TOKEN" ]; then
    echo -e "${RED}Error: VAULT_TOKEN is not set${NC}"
    exit 1
fi

# Calculate server_id (SHA-256 hash of mcp_url, first 8 chars)
SERVER_ID=$(echo -n "$MCP_URL" | sha256sum | cut -c1-8)

# Construct Vault path
VAULT_PATH="${VAULT_KV_MOUNT}/data/${VAULT_KV_PATH_PREFIX}/credentials/${TEAM_ID}/${SERVER_ID}"

echo -e "${YELLOW}Storing OAuth credentials in Vault${NC}"
echo "  Team ID: $TEAM_ID"
echo "  MCP URL: $MCP_URL"
echo "  Server ID: $SERVER_ID"
echo "  Client ID: $CLIENT_ID"
echo "  Vault Path: $VAULT_PATH"
echo ""

# Build JSON payload
PAYLOAD=$(cat <<EOF
{
  "data": {
    "team_id": "${TEAM_ID}",
    "mcp_url": "${MCP_URL}",
    "client_id": "${CLIENT_ID}",
    "client_secret": "${CLIENT_SECRET}",
    "grant_type": "authorization_code",
    "token_endpoint_auth_method": "client_secret_post",
    "updated_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  }
}
EOF
)

# Merge additional fields if provided
if [ "$ADDITIONAL_FIELDS" != "{}" ]; then
    PAYLOAD=$(echo "$PAYLOAD" | jq --argjson extra "$ADDITIONAL_FIELDS" '.data += $extra')
fi

# Store in Vault
RESPONSE=$(curl -s -X POST \
    -H "X-Vault-Token: ${VAULT_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "${VAULT_ADDR}/v1/${VAULT_PATH}")

# Check response
if echo "$RESPONSE" | jq -e '.errors' > /dev/null 2>&1; then
    echo -e "${RED}Error storing credentials in Vault:${NC}"
    echo "$RESPONSE" | jq -r '.errors[]'
    exit 1
fi

echo -e "${GREEN}✓ OAuth credentials stored successfully${NC}"
echo ""
echo "Verify with:"
echo "  vault kv get ${VAULT_KV_MOUNT}/${VAULT_KV_PATH_PREFIX}/credentials/${TEAM_ID}/${SERVER_ID}"
echo ""
echo "Or retrieve via Python:"
echo "  python3 scripts/get-oauth-credentials-vault.py ${TEAM_ID} ${MCP_URL}"
