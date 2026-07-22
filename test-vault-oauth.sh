#!/bin/bash
# Test OAuth with Vault backend

set -e

export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=root
export JWT_SECRET_KEY=$(grep JWT_SECRET_KEY .env | cut -d '=' -f2)
export GATEWAY_ID="fb14e7cad11b48f9ac1842e9456f0597"

echo "=== Testing OAuth with Vault Backend ==="
echo ""

# Step 1: Generate token
echo "1. Generating authentication token..."
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username "user@example.com" \
  --teams "d855a360a0f24f56ac2b5a1ab54cbb70" \
  --exp 10080 \
  --secret "$JWT_SECRET_KEY")
echo "✓ Token generated"
echo ""

# Step 2: Check Vault is empty
echo "2. Checking Vault (should be empty before OAuth)..."
VAULT_DATA=$(curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth?list=true" | jq -r '.data.keys // []')
echo "Current keys in Vault: $VAULT_DATA"
echo ""

# Step 3: Initiate OAuth
echo "3. Initiating OAuth authorization..."
echo "   GET http://localhost:4444/oauth/authorize/$GATEWAY_ID"
RESPONSE=$(curl -s -i "http://localhost:4444/oauth/authorize/$GATEWAY_ID" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN")

HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP/" | awk '{print $2}')
LOCATION=$(echo "$RESPONSE" | grep -i "^location:" | cut -d ' ' -f2 | tr -d '\r')

echo "   HTTP Status: $HTTP_CODE"

if [ "$HTTP_CODE" = "302" ]; then
  echo "✓ Redirect to OAuth provider"
  echo ""
  echo "Authorization URL:"
  echo "$LOCATION"
  echo ""
  echo "=== Next Steps ==="
  echo "1. Open the authorization URL in your browser"
  echo "2. Authenticate and authorize"
  echo "3. After callback, check tokens in Vault with:"
  echo ""
  echo "   curl -s -H \"X-Vault-Token: \$VAULT_TOKEN\" \\"
  echo "     \"\${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth?list=true\" | jq '.data'"
  echo ""
  echo "4. List specific token:"
  echo ""
  echo "   curl -s -H \"X-Vault-Token: \$VAULT_TOKEN\" \\"
  echo "     \"\${VAULT_ADDR}/v1/secret/data/contextforge/oauth/TEAM_ID/GATEWAY_ID/USER_EMAIL\" | jq '.data.data'"
else
  echo "❌ Failed to initiate OAuth (HTTP $HTTP_CODE)"
  echo ""
  echo "Response:"
  echo "$RESPONSE"
fi
