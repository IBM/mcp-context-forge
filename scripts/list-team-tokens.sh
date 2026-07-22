#!/bin/bash
# List all OAuth tokens for a team
#
# Usage:
#   ./list-team-tokens.sh <team_id>
#
# Example:
#   ./list-team-tokens.sh d855a360a0f24f56ac2b5a1ab54cbb70

set -euo pipefail

# Load Vault config from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep 'VAULT_' | xargs)
fi

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-}"

if [ -z "$VAULT_TOKEN" ]; then
    echo "ERROR: VAULT_TOKEN not set in .env"
    exit 1
fi

if [ $# -lt 1 ]; then
    echo "Usage: $0 <team_id>"
    echo ""
    echo "Example:"
    echo "  $0 d855a360a0f24f56ac2b5a1ab54cbb70"
    exit 1
fi

TEAM_ID="$1"
BASE_PATH="contextforge/oauth/${TEAM_ID}"

echo "=== OAuth Tokens for Team: ${TEAM_ID} ==="
echo ""

# Step 1: List all provider hashes
PROVIDERS=$(curl -s \
    -H "X-Vault-Token: $VAULT_TOKEN" \
    "${VAULT_ADDR}/v1/secret/metadata/${BASE_PATH}?list=true" \
    | jq -r '.data.keys[]?' 2>/dev/null || echo "")

if [ -z "$PROVIDERS" ]; then
    echo "No tokens found for team ${TEAM_ID}"
    exit 0
fi

# Step 2: For each provider, list all users
for provider in $PROVIDERS; do
    # Remove trailing slash
    provider=${provider%/}

    echo "Provider: ${provider}"
    echo "----------------------------------------"

    # List all users for this provider
    USERS=$(curl -s \
        -H "X-Vault-Token: $VAULT_TOKEN" \
        "${VAULT_ADDR}/v1/secret/metadata/${BASE_PATH}/${provider}?list=true" \
        | jq -r '.data.keys[]?' 2>/dev/null || echo "")

    if [ -z "$USERS" ]; then
        echo "  No users found"
        echo ""
        continue
    fi

    # Step 3: Fetch each user's token
    for user in $USERS; do
        TOKEN_PATH="${BASE_PATH}/${provider}/${user}"

        echo "  User: ${user}"

        TOKEN_DATA=$(curl -s \
            -H "X-Vault-Token: $VAULT_TOKEN" \
            "${VAULT_ADDR}/v1/secret/data/${TOKEN_PATH}")

        # Extract key fields
        ACCESS_TOKEN=$(echo "$TOKEN_DATA" | jq -r '.data.data.token.access_token // "N/A"')
        USER_ID=$(echo "$TOKEN_DATA" | jq -r '.data.data.user_id // "N/A"')
        MCP_URL=$(echo "$TOKEN_DATA" | jq -r '.data.data.mcp_url // "N/A"')
        CREATED_AT=$(echo "$TOKEN_DATA" | jq -r '.data.data.created_at // "N/A"')

        echo "    Access Token: ${ACCESS_TOKEN:0:20}..."
        echo "    User ID: ${USER_ID}"
        echo "    MCP URL: ${MCP_URL}"
        echo "    Created: ${CREATED_AT}"
        echo ""
    done
done

echo "=== Summary ==="
TOTAL_USERS=$(curl -s \
    -H "X-Vault-Token: $VAULT_TOKEN" \
    "${VAULT_ADDR}/v1/secret/metadata/${BASE_PATH}?list=true" \
    | jq -r '.data.keys[]' 2>/dev/null \
    | while read provider; do
        curl -s \
            -H "X-Vault-Token: $VAULT_TOKEN" \
            "${VAULT_ADDR}/v1/secret/metadata/${BASE_PATH}/${provider%/}?list=true" \
            | jq -r '.data.keys[]?' 2>/dev/null
    done | wc -l | tr -d ' ')

echo "Total tokens: ${TOTAL_USERS}"
