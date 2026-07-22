# Testing Vault OAuth Endpoints

This guide shows how to test the `/vault/authorize/{server_id}` and `/vault/callback` endpoints.

## Prerequisites

### 1. Start Vault (if using Docker)
```bash
# Start Vault container
docker run -d --name vault-dev \
  -p 8200:8200 \
  -e VAULT_DEV_ROOT_TOKEN_ID=test-root-token \
  --cap-add=IPC_LOCK \
  hashicorp/vault:latest

# Or if you have docker-compose.vault-test.yml (removed from branch but may be in your working copy):
docker-compose -f docker-compose.vault-test.yml up -d
```

### 2. Configure Environment
```bash
# Set Vault backend
export OAUTH_TOKEN_BACKEND=vault
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=test-root-token
export VAULT_KV_MOUNT=secret
export VAULT_KV_PATH_PREFIX=contextforge/oauth

# Optional: Enable caching
export VAULT_TOKEN_CACHE_ENABLED=true
export VAULT_TOKEN_CACHE_TTL=300

# Generate JWT token for testing
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username testuser@example.com \
  --exp 10080 \
  --secret your-jwt-secret-key)
```

### 3. Start ContextForge
```bash
make dev
# Server runs on http://localhost:8000
```

## Test Setup

### 1. Create an OAuth-Enabled Gateway
```bash
curl -X POST http://localhost:8000/gateways \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GitHub MCP Server",
    "url": "http://localhost:9000/sse",
    "type": "http",
    "auth_type": "oauth",
    "oauth_client_id": "your-github-client-id",
    "oauth_client_secret": "your-github-client-secret",
    "oauth_authorization_url": "https://github.com/login/oauth/authorize",
    "oauth_token_url": "https://github.com/login/oauth/access_token",
    "oauth_scopes": ["repo", "user"]
  }'

# Save the gateway ID from response
export GATEWAY_ID="<gateway-id-from-response>"
```

### 2. Create a Virtual Server
```bash
curl -X POST http://localhost:8000/servers \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My GitHub Server",
    "url": "github-mcp",
    "description": "GitHub MCP tools"
  }'

# Save the server ID from response
export SERVER_ID="<server-id-from-response>"
```

### 3. Link Gateway to Server via Tools
```bash
# First, list available tools from the gateway
curl http://localhost:8000/gateways/$GATEWAY_ID/tools \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Create a tool (or use an existing tool_id)
curl -X POST http://localhost:8000/tools \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "create_issue",
    "description": "Create GitHub issue",
    "gateway_id": "'$GATEWAY_ID'",
    "input_schema": {"type": "object", "properties": {}}
  }'

export TOOL_ID="<tool-id-from-response>"

# Associate tool with server
curl -X POST http://localhost:8000/servers/$SERVER_ID/tools \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_ids": ["'$TOOL_ID'"]
  }'
```

## Testing the OAuth Flow

### Method 1: Browser Testing (Manual)

1. **Initiate OAuth flow:**
```bash
# Open this URL in your browser
http://localhost:8000/vault/authorize/$SERVER_ID
```

2. **What happens:**
   - You'll be redirected to GitHub (or your OAuth provider)
   - Log in and authorize the application
   - You'll be redirected back to `/vault/callback`
   - Tokens will be stored in Vault at path: `{team_id}/{server_id}/{email}`

3. **Success response:**
```html
<html>
  <body style="font-family: sans-serif; padding: 2rem;">
    <h2>✓ Authorization Complete</h2>
    <p>OAuth tokens stored in Vault for server: <code>github-mcp</code></p>
    <p>You can close this window.</p>
  </body>
</html>
```

### Method 2: API Testing (Automated)

```bash
# Step 1: Initiate authorization (this will return a redirect URL)
curl -i http://localhost:8000/vault/authorize/$SERVER_ID \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Step 2: Follow the redirect manually or use the URL from Location header
# The redirect will be to GitHub OAuth authorization URL like:
# https://github.com/login/oauth/authorize?client_id=...&state=...

# Step 3: After authorization, GitHub redirects to /vault/callback with code and state
# This happens automatically in a browser
```

### Method 3: Integration Test

Check the existing integration tests:
```bash
# Run Vault integration tests
pytest tests/integration/test_vault_integration.py -v

# Run with specific test
pytest tests/integration/test_vault_integration.py::test_store_and_get_token -v
```

## Verifying Token Storage in Vault

### CLI Verification
```bash
# Set Vault credentials
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=test-root-token

# List all secrets (KV v2)
vault kv list secret/contextforge/oauth

# Read a specific token (replace with actual path)
vault kv get secret/contextforge/oauth/team123/github-mcp/testuser@example.com
```

### API Verification
```bash
# List secrets via Vault API
curl -H "X-Vault-Token: test-root-token" \
  http://localhost:8200/v1/secret/metadata/contextforge/oauth?list=true

# Read a specific secret
curl -H "X-Vault-Token: test-root-token" \
  http://localhost:8200/v1/secret/data/contextforge/oauth/team123/github-mcp/testuser@example.com
```

## Testing OAuth Callback Directly

If you have a valid OAuth authorization code, you can test the callback endpoint directly:

```bash
curl -i "http://localhost:8000/vault/callback?code=VALID_OAUTH_CODE&state=VALID_STATE_FROM_AUTHORIZE" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
```

**Note:** The `state` parameter must match what was generated during the `/vault/authorize` call, and the `code` must be a valid OAuth authorization code from your provider.

## Common Test Scenarios

### 1. Test Multi-Gateway Server
If a server has multiple OAuth gateways, specify which one:
```bash
curl -i "http://localhost:8000/vault/authorize/$SERVER_ID?gateway_url=http://localhost:9000/sse" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
```

### 2. Test Team Isolation
```bash
# Create token with different team_id
export TEAM1_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username user1@example.com \
  --exp 10080 \
  --secret your-jwt-secret-key \
  --teams team1)

export TEAM2_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username user2@example.com \
  --exp 10080 \
  --secret your-jwt-secret-key \
  --teams team2)

# Authorize with team1
curl -i http://localhost:8000/vault/authorize/$SERVER_ID \
  -H "Authorization: Bearer $TEAM1_TOKEN"

# Authorize with team2
curl -i http://localhost:8000/vault/authorize/$SERVER_ID \
  -H "Authorization: Bearer $TEAM2_TOKEN"

# Verify tokens are stored in different Vault paths:
# secret/contextforge/oauth/team1/...
# secret/contextforge/oauth/team2/...
```

### 3. Test Error Handling

**No OAuth gateway:**
```bash
# Create a server with no OAuth-enabled gateway
curl -i http://localhost:8000/vault/authorize/server-without-oauth \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Expected: 400 Bad Request - No OAuth gateways configured
```

**Invalid server ID:**
```bash
curl -i http://localhost:8000/vault/authorize/nonexistent-server \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Expected: 404 Not Found - Server not found
```

**Invalid callback state:**
```bash
curl -i "http://localhost:8000/vault/callback?code=test&state=invalid-state" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Expected: 400 Bad Request - Invalid or expired state
```

## Token Cache Testing

If `VAULT_TOKEN_CACHE_ENABLED=true`, verify caching works:

```bash
# First request (cache miss - slow ~25ms)
time curl -i http://localhost:8000/servers/$SERVER_ID/tools \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Second request (cache hit - fast ~0.5ms)
time curl -i http://localhost:8000/servers/$SERVER_ID/tools \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
```

## Troubleshooting

### Vault Not Available
```bash
# Check Vault status
curl http://localhost:8200/v1/sys/health

# Expected response: {"initialized":true,"sealed":false,...}
```

### OAuth Provider Issues
- Verify `oauth_client_id` and `oauth_client_secret` are correct
- Check OAuth provider's redirect URI whitelist includes: `http://localhost:8000/vault/callback`
- Enable debug logging: `export LOG_LEVEL=DEBUG`

### Token Storage Issues
```bash
# Check Vault KV engine is enabled
vault secrets list

# Should show: secret/ kv

# Enable if missing
vault secrets enable -path=secret kv-v2
```

## Cleanup

```bash
# Delete test tokens from Vault
vault kv metadata delete secret/contextforge/oauth/team123/github-mcp/testuser@example.com

# Or delete entire prefix
vault kv metadata delete -mount=secret contextforge/oauth

# Stop Vault container
docker stop vault-dev
docker rm vault-dev
```

## Next Steps

- Run integration tests: `pytest tests/integration/test_vault_integration.py -v`
- Check logs: `tail -f logs/mcpgateway.log`
- Review Vault audit logs if enabled
- Test token refresh flows (tokens expire after TTL)
