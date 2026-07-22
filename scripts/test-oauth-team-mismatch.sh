#!/bin/bash
# Test OAuth with JWT team_id different from gateway team_id
#
# This tests the fix for the issue where OAuth credentials should come from
# the JWT team_id, not the gateway team_id.

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Testing OAuth with Team ID Mismatch${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Load environment
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Configuration
GATEWAY_ID="${1:-fb14e7cad11b48f9ac1842e9456f0597}"
JWT_TOKEN="${MCPGATEWAY_BEARER_TOKEN:-}"
VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-}"

if [ -z "$JWT_TOKEN" ]; then
    echo -e "${RED}Error: MCPGATEWAY_BEARER_TOKEN is not set${NC}"
    exit 1
fi

if [ -z "$VAULT_TOKEN" ]; then
    echo -e "${RED}Error: VAULT_TOKEN is not set${NC}"
    exit 1
fi

# Extract JWT claims
echo -e "${YELLOW}Step 1: Extracting JWT claims${NC}"
JWT_CLAIMS=$(python3 << 'EOF'
import jwt
import os
import json
token = os.getenv("MCPGATEWAY_BEARER_TOKEN")
decoded = jwt.decode(token, options={"verify_signature": False})
print(json.dumps({
    "email": decoded.get("email"),
    "teams": decoded.get("teams"),
    "is_admin": decoded.get("is_admin", False)
}))
EOF
)

JWT_EMAIL=$(echo "$JWT_CLAIMS" | jq -r '.email')
JWT_TEAMS=$(echo "$JWT_CLAIMS" | jq -r '.teams[]' | head -1)
JWT_IS_ADMIN=$(echo "$JWT_CLAIMS" | jq -r '.is_admin')

echo "  Email: $JWT_EMAIL"
echo "  Team ID (from JWT): $JWT_TEAMS"
echo "  Is Admin: $JWT_IS_ADMIN"
echo ""

# Get gateway info
echo -e "${YELLOW}Step 2: Getting gateway information${NC}"
GATEWAY_INFO=$(curl -s -X GET "http://localhost:4444/admin/gateways/$GATEWAY_ID" \
    -H "Authorization: Bearer $JWT_TOKEN")

GATEWAY_NAME=$(echo "$GATEWAY_INFO" | jq -r '.name // "Unknown"')
GATEWAY_URL=$(echo "$GATEWAY_INFO" | jq -r '.url // ""')
GATEWAY_TEAM_ID=$(echo "$GATEWAY_INFO" | jq -r '.team_id // "public"')
GATEWAY_VISIBILITY=$(echo "$GATEWAY_INFO" | jq -r '.visibility // "public"')

echo "  Gateway ID: $GATEWAY_ID"
echo "  Gateway Name: $GATEWAY_NAME"
echo "  Gateway URL: $GATEWAY_URL"
echo "  Gateway Team ID: $GATEWAY_TEAM_ID"
echo "  Gateway Visibility: $GATEWAY_VISIBILITY"
echo ""

# Check if team IDs match
if [ "$JWT_TEAMS" = "$GATEWAY_TEAM_ID" ]; then
    echo -e "${GREEN}✓ JWT team_id matches gateway team_id${NC}"
else
    echo -e "${YELLOW}⚠ JWT team_id ($JWT_TEAMS) differs from gateway team_id ($GATEWAY_TEAM_ID)${NC}"
    echo -e "${YELLOW}  This is the scenario we're testing!${NC}"
fi
echo ""

# Calculate server_id
if [ -z "$GATEWAY_URL" ]; then
    echo -e "${RED}Error: Could not retrieve gateway URL${NC}"
    exit 1
fi

SERVER_ID=$(echo -n "$GATEWAY_URL" | sha256sum | cut -c1-8)
echo -e "${YELLOW}Step 3: Checking Vault credentials${NC}"
echo "  Server ID (hash of URL): $SERVER_ID"
echo ""

# Check if credentials exist in Vault for JWT team
VAULT_CREDS_PATH="secret/data/contextforge/oauth/credentials/${JWT_TEAMS}/${SERVER_ID}"
echo "  Checking Vault path: $VAULT_CREDS_PATH"

VAULT_RESPONSE=$(curl -s -H "X-Vault-Token: ${VAULT_TOKEN}" \
    "${VAULT_ADDR}/v1/${VAULT_CREDS_PATH}")

if echo "$VAULT_RESPONSE" | jq -e '.data.data.client_id' > /dev/null 2>&1; then
    VAULT_CLIENT_ID=$(echo "$VAULT_RESPONSE" | jq -r '.data.data.client_id')
    echo -e "${GREEN}✓ Vault credentials found for team: $JWT_TEAMS${NC}"
    echo "    Client ID: $VAULT_CLIENT_ID"
else
    echo -e "${RED}✗ No Vault credentials found for team: $JWT_TEAMS${NC}"
    echo ""
    echo -e "${YELLOW}You need to store credentials first:${NC}"
    echo "  ./scripts/store-oauth-credentials-vault.sh \\"
    echo "    \"${JWT_TEAMS}\" \\"
    echo "    \"${GATEWAY_URL}\" \\"
    echo "    \"YOUR_CLIENT_ID\" \\"
    echo "    \"YOUR_CLIENT_SECRET\" \\"
    echo "    '{\"authorization_url\": \"https://github.com/login/oauth/authorize\", \"token_url\": \"https://github.com/login/oauth/access_token\", \"scopes\": [\"repo\"]}'"
    exit 1
fi
echo ""

# Check database credentials for comparison
echo -e "${YELLOW}Step 4: Checking database credentials (for comparison)${NC}"
DB_CLIENT_ID=$(echo "$GATEWAY_INFO" | jq -r '.oauth_config.client_id // "Not set"')
echo "  Database Client ID: $DB_CLIENT_ID"

if [ "$VAULT_CLIENT_ID" = "$DB_CLIENT_ID" ]; then
    echo -e "${GREEN}  ✓ Vault and database credentials match${NC}"
else
    echo -e "${YELLOW}  ⚠ Vault credentials differ from database${NC}"
    echo -e "${YELLOW}    This is expected for team-scoped OAuth${NC}"
fi
echo ""

# Initiate OAuth flow
echo -e "${YELLOW}Step 5: Initiating OAuth flow${NC}"
echo "  Calling: GET /oauth/authorize/$GATEWAY_ID"

AUTH_RESPONSE=$(curl -s -v -X GET "http://localhost:4444/oauth/authorize/$GATEWAY_ID" \
    -H "Authorization: Bearer $JWT_TOKEN" 2>&1)

# Extract redirect location
AUTH_URL=$(echo "$AUTH_RESPONSE" | grep -i "^< location:" | sed 's/< location: //' | tr -d '\r\n')

if [ -z "$AUTH_URL" ]; then
    echo -e "${RED}✗ Failed to get authorization URL${NC}"
    echo ""
    echo "Response:"
    echo "$AUTH_RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ Got authorization URL${NC}"
echo ""

# Extract client_id from auth URL
AUTH_CLIENT_ID=$(echo "$AUTH_URL" | grep -oP 'client_id=\K[^&]+' || echo "Unknown")
echo -e "${BLUE}Analysis:${NC}"
echo "  Authorization URL client_id: $AUTH_CLIENT_ID"
echo "  Vault credentials client_id: $VAULT_CLIENT_ID"
echo "  Database credentials client_id: $DB_CLIENT_ID"
echo ""

# Determine which credentials were used
if [ "$AUTH_CLIENT_ID" = "$VAULT_CLIENT_ID" ]; then
    echo -e "${GREEN}✓✓✓ SUCCESS! Using Vault credentials for team: $JWT_TEAMS${NC}"
    echo ""
    echo -e "${GREEN}The fix is working correctly:${NC}"
    echo "  - JWT team_id: $JWT_TEAMS"
    echo "  - Gateway team_id: $GATEWAY_TEAM_ID"
    echo "  - Credentials source: Vault (team-scoped)"
    echo "  - Client ID used: $AUTH_CLIENT_ID"
elif [ "$AUTH_CLIENT_ID" = "$DB_CLIENT_ID" ]; then
    echo -e "${YELLOW}⚠ Using database credentials (fallback)${NC}"
    echo ""
    echo "This means Vault credentials were not found or an error occurred."
    echo "Check server logs for:"
    echo "  - 'Using team-scoped OAuth credentials from Vault' (expected)"
    echo "  - 'Using database OAuth credentials' (fallback)"
else
    echo -e "${RED}✗ Unexpected client_id in authorization URL${NC}"
fi
echo ""

# Show next steps
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Next Steps:${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "1. Open this URL in your browser to complete OAuth:"
echo ""
echo -e "${GREEN}${AUTH_URL}${NC}"
echo ""
echo "2. After authorization, check server logs:"
echo "   tail -50 /path/to/logs | grep -i 'oauth'"
echo ""
echo "3. Verify tokens stored in Vault:"
echo "   vault kv list secret/contextforge/oauth/${JWT_TEAMS}/${SERVER_ID}/"
echo ""
echo "4. Expected log line:"
echo -e "   ${GREEN}INFO: Using team-scoped OAuth credentials from Vault for team=${JWT_TEAMS}${NC}"
