# Testing OAuth with Vault Credentials - Step by Step

## Prerequisites

1. **Vault running** and accessible at `$VAULT_ADDR`
2. **ContextForge running** with `OAUTH_TOKEN_BACKEND=vault`
3. **JWT token** with correct `team_id` in the `teams` claim
4. **Gateway** registered with OAuth configuration
5. **GitHub OAuth App** (or other IdP) registered

## Step 1: Check Your JWT Token

First, verify your JWT contains the correct `team_id`:

```bash
# Decode your JWT
export MCPGATEWAY_BEARER_TOKEN="your_jwt_here"

python3 << 'EOF'
import jwt
import os
token = os.getenv("MCPGATEWAY_BEARER_TOKEN")
decoded = jwt.decode(token, options={"verify_signature": False})
print("JWT Claims:")
print(f"  email: {decoded.get('email')}")
print(f"  teams: {decoded.get('teams')}")
print(f"  is_admin: {decoded.get('is_admin')}")
EOF
```

Expected output:
```
JWT Claims:
  email: alice@example.com
  teams: ['f8927490a44d4ede95889136d004c202']
  is_admin: False
```

**⚠️ Important:** The `team_id` in the JWT (`f8927490a44d4ede95889136d004c202`) will be used to look up OAuth credentials in Vault.

## Step 2: Get Gateway Information

Find your gateway URL and ID:

```bash
curl -X GET "http://localhost:4444/admin/gateways" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  | jq '.[] | {id, name, url, auth_type, team_id}'
```

Example output:
```json
{
  "id": "fb14e7cad11b48f9ac1842e9456f0597",
  "name": "GitHub MCP",
  "url": "https://mcp.github.acme.com",
  "auth_type": "oauth",
  "team_id": "public"
}
```

Note the `gateway_id` and `url`.

## Step 3: Store Team-Scoped OAuth Credentials in Vault

Now store the OAuth credentials for your team in Vault. You need:
- **team_id**: From your JWT (e.g., `f8927490a44d4ede95889136d004c202`)
- **mcp_url**: Gateway URL (e.g., `https://mcp.github.acme.com`)
- **client_id**: GitHub OAuth App Client ID (e.g., `Iv1.abc123def456`)
- **client_secret**: GitHub OAuth App Client Secret

### Option A: Using Shell Script

```bash
export VAULT_ADDR="http://localhost:8200"
export VAULT_TOKEN="your-vault-token"

./scripts/store-oauth-credentials-vault.sh \
  "f8927490a44d4ede95889136d004c202" \
  "https://mcp.github.acme.com" \
  "Iv1.abc123def456" \
  "your_github_oauth_secret" \
  '{"authorization_url": "https://github.com/login/oauth/authorize", "token_url": "https://github.com/login/oauth/access_token", "scopes": ["repo", "read:org"]}'
```

### Option B: Using Vault CLI

```bash
# Calculate server_id
SERVER_ID=$(echo -n "https://mcp.github.acme.com" | sha256sum | cut -c1-8)
echo "Server ID: $SERVER_ID"

# Store credentials
vault kv put secret/contextforge/oauth/credentials/f8927490a44d4ede95889136d004c202/$SERVER_ID \
  team_id="f8927490a44d4ede95889136d004c202" \
  mcp_url="https://mcp.github.acme.com" \
  client_id="Iv1.abc123def456" \
  client_secret="your_github_oauth_secret" \
  authorization_url="https://github.com/login/oauth/authorize" \
  token_url="https://github.com/login/oauth/access_token" \
  scopes='["repo", "read:org"]' \
  grant_type="authorization_code" \
  token_endpoint_auth_method="client_secret_post"
```

### Verify Credentials Stored

```bash
python3 scripts/get-oauth-credentials-vault.py \
  "f8927490a44d4ede95889136d004c202" \
  "https://mcp.github.acme.com"
```

Expected output:
```
✓ OAuth credentials found:

{
  "team_id": "f8927490a44d4ede95889136d004c202",
  "mcp_url": "https://mcp.github.acme.com",
  "client_id": "Iv1.abc123def456",
  "client_secret": "[REDACTED]",
  "authorization_url": "https://github.com/login/oauth/authorize",
  "token_url": "https://github.com/login/oauth/access_token",
  "scopes": ["repo", "read:org"]
}
```

## Step 4: Initiate OAuth Flow (Browser Required)

**⚠️ You CANNOT use `curl` for this step!** OAuth authorization requires browser redirects.

### Option A: Open in Browser Directly

1. Get the authorization URL:
   ```bash
   echo "http://localhost:4444/oauth/authorize/fb14e7cad11b48f9ac1842e9456f0597"
   ```

2. **Open this URL in your browser** (not curl!)

3. You'll be redirected to the ContextForge OAuth initiation endpoint, which will:
   - Extract `team_id` from your JWT
   - Look up credentials in Vault for your team
   - Redirect you to GitHub (or other IdP) authorization page

### Option B: Use Browser with Token

If you need to pass the JWT via browser:

1. **Method 1**: Set JWT as cookie (most reliable):
   ```bash
   # Open browser dev tools, go to Application → Cookies
   # Add cookie: name="auth_token", value="your_jwt_here"
   # Then visit: http://localhost:4444/oauth/authorize/fb14e7cad11b48f9ac1842e9456f0597
   ```

2. **Method 2**: Use a browser extension like "ModHeader" to set Authorization header

3. **Method 3**: Use a tool like Postman that handles browser redirects

### What Should Happen

1. **ContextForge logs** (check server logs):
   ```
   INFO: Using team-scoped OAuth credentials from Vault for team=f8927490a44d4ede95889136d004c202
   INFO: Initiated OAuth flow for gateway fb14e7cad11b48f9ac1842e9456f0597
   ```

2. **Browser** redirects to GitHub authorization page:
   ```
   https://github.com/login/oauth/authorize?
     client_id=Iv1.abc123def456&
     redirect_uri=http://localhost:4444/oauth/callback&
     state=...&
     scope=repo+read:org&
     ...
   ```

3. **You approve** the authorization on GitHub

4. **GitHub redirects back** to:
   ```
   http://localhost:4444/oauth/callback?code=xxx&state=yyy
   ```

5. **ContextForge exchanges code for tokens** using your team's credentials

6. **Tokens stored in Vault** at:
   ```
   secret/data/contextforge/oauth/f8927490a44d4ede95889136d004c202/647ad7b3/alice%40example.com
   ```

## Step 5: Verify Success

### Check ContextForge Logs

Look for these log lines:

✅ **Success indicators:**
```
INFO: Using team-scoped OAuth credentials from Vault for team=f8927490a44d4ede95889136d004c202
INFO: Successfully exchanged authorization code for tokens
INFO: Stored OAuth tokens in Vault for gateway fb14e7cad11b48f9ac1842e9456f0597
```

❌ **Failure indicators:**
```
WARNING: Using database OAuth credentials for gateway fb14e7cad11b48f9ac1842e9456f0597
ERROR: OAuth callback failed: No access_token in response: {'error': 'incorrect_client_credentials', ...}
```

### Check Vault Structure

```bash
# List tokens stored
vault kv list secret/contextforge/oauth/f8927490a44d4ede95889136d004c202/647ad7b3/

# Get your token (shows metadata, not the actual token)
python3 scripts/check-vault-structure.py
```

Expected output:
```
📂 secret/data/contextforge/oauth/
  📁 f8927490a44d4ede95889136d004c202/
    📁 647ad7b3/
      📄 alice%40example.com
        email: alice@example.com
        team_id: f8927490a44d4ede95889136d004c202
        mcp_url: https://mcp.github.acme.com
        expires_at: 2026-07-13T12:00:00Z
```

## Step 6: Test Tool Execution

Now test that tools can use the stored token:

```bash
curl -X POST "http://localhost:4444/tools/execute" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "github_get_repo",
    "arguments": {"repo": "owner/repo"}
  }'
```

ContextForge should:
1. Extract `team_id` from JWT
2. Look up token in Vault: `{team_id}/{server_id}/{email}`
3. Use token to call MCP server
4. Return tool result

## Troubleshooting

### Error: "No OAuth credentials found in Vault"

**Symptom:** Logs show:
```
WARNING: No OAuth credentials found in Vault for team=f8927490a44d4ede95889136d004c202
WARNING: Using database OAuth credentials for gateway fb14e7cad11b48f9ac1842e9456f0597
```

**Solution:** Store credentials in Vault (Step 3)

### Error: "incorrect_client_credentials" from GitHub

**Symptom:** OAuth callback fails with:
```
{'error': 'incorrect_client_credentials', 'error_description': 'The client_id and/or client_secret passed are incorrect.'}
```

**Root Cause:** Wrong credentials being used.

**Solution:**
1. Verify correct credentials stored in Vault:
   ```bash
   python3 scripts/get-oauth-credentials-vault.py \
     "f8927490a44d4ede95889136d004c202" \
     "https://mcp.github.acme.com"
   ```

2. If wrong, update in Vault:
   ```bash
   ./scripts/store-oauth-credentials-vault.sh \
     "f8927490a44d4ede95889136d004c202" \
     "https://mcp.github.acme.com" \
     "CORRECT_CLIENT_ID" \
     "CORRECT_SECRET"
   ```

3. Retry OAuth flow

### Error: "State parameter invalid"

**Symptom:** OAuth callback fails with state validation error.

**Solution:** The state expires after 5 minutes. Restart OAuth flow from Step 4.

### Error: "User authentication required"

**Symptom:** `/oauth/authorize` returns 401.

**Solution:** 
1. Check JWT token is valid:
   ```bash
   python3 -m mcpgateway.utils.create_jwt_token \
     --username alice@example.com \
     --teams '["f8927490a44d4ede95889136d004c202"]' \
     --secret your-secret \
     --decode
   ```

2. Pass JWT via cookie or Authorization header (not URL parameter!)

## Complete Example Flow

```bash
# 1. Setup
export VAULT_ADDR="http://localhost:8200"
export VAULT_TOKEN="your-vault-token"
export MCPGATEWAY_BEARER_TOKEN="your_jwt_with_team_id"

# 2. Verify JWT
python3 << 'EOF'
import jwt, os
token = os.getenv("MCPGATEWAY_BEARER_TOKEN")
decoded = jwt.decode(token, options={"verify_signature": False})
print(f"email: {decoded.get('email')}, teams: {decoded.get('teams')}")
EOF

# 3. Get gateway info
GATEWAY_ID="fb14e7cad11b48f9ac1842e9456f0597"
GATEWAY_URL="https://mcp.github.acme.com"

# 4. Store OAuth credentials in Vault
./scripts/store-oauth-credentials-vault.sh \
  "f8927490a44d4ede95889136d004c202" \
  "$GATEWAY_URL" \
  "Iv1.YOUR_GITHUB_CLIENT_ID" \
  "YOUR_GITHUB_CLIENT_SECRET" \
  '{"authorization_url": "https://github.com/login/oauth/authorize", "token_url": "https://github.com/login/oauth/access_token", "scopes": ["repo", "read:org"]}'

# 5. Verify stored
python3 scripts/get-oauth-credentials-vault.py \
  "f8927490a44d4ede95889136d004c202" \
  "$GATEWAY_URL"

# 6. Open in browser (NOT curl!)
echo "Open this URL in your browser:"
echo "http://localhost:4444/oauth/authorize/$GATEWAY_ID"
echo ""
echo "Make sure your browser has the JWT token as a cookie or header!"

# 7. After authorization completes, check Vault
vault kv list secret/contextforge/oauth/f8927490a44d4ede95889136d004c202/

# 8. Test tool execution
curl -X POST "http://localhost:4444/tools/execute" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "your_tool_name",
    "arguments": {}
  }'
```

## Key Takeaways

1. **OAuth authorization requires a browser** - you cannot use `curl` for the authorize endpoint
2. **JWT team_id is authoritative** - credentials are looked up by `team_id` from JWT
3. **Store credentials in Vault per team** - enables multi-team isolation
4. **Database credentials are fallback** - if Vault lookup returns None
5. **Verify credentials before testing** - use `get-oauth-credentials-vault.py`
6. **Check logs for team-scoped credential usage** - confirms Vault lookup succeeded

## References

- [Team-Scoped OAuth Credentials in Vault](./vault-oauth-credentials-storage.md)
- [OAuth + Vault: Team-Isolated Token Storage](./oauth-vault-team-isolation.md)
- [Troubleshooting OAuth with Vault](../TROUBLESHOOTING_OAUTH_VAULT.md)
