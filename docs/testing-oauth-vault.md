# Testing OAuth Authorization with Vault Token Storage

This guide walks through testing the complete OAuth Authorization Code flow with Vault token storage backend.

## Prerequisites

### 1. Start Vault (Docker Compose)

```bash
docker-compose -f docker-compose.vault-test.yml up -d
```

This starts Vault at `http://localhost:8200` with:
- Root token: `test-root-token`
- KV v2 secrets engine enabled at `secret/`

### 2. Environment Configuration

Create or update your `.env` file:

```bash
# OAuth Token Storage Backend
OAUTH_TOKEN_BACKEND=vault

# Vault Configuration
VAULT_ADDR=http://localhost:8200
VAULT_TOKEN=test-root-token
VAULT_NAMESPACE=
VAULT_KV_MOUNT=secret
VAULT_KV_PATH_PREFIX=contextforge/oauth
VAULT_TLS_VERIFY=false

# Token Cache (optional but recommended)
VAULT_TOKEN_CACHE_ENABLED=true
VAULT_TOKEN_CACHE_TTL=300
VAULT_TOKEN_CACHE_MAX_SIZE=10000

# Enable Admin UI and API
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
MCPGATEWAY_A2A_ENABLED=true

# Database
DATABASE_URL=sqlite:///./mcp.db

# JWT Secret
JWT_SECRET_KEY=your-secret-key-here

# Basic Auth for Admin UI
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
AUTH_REQUIRED=true
```

### 3. Start ContextForge

```bash
make dev
```

The server will start at `http://localhost:8000`.

## Testing Flow

### Step 1: Create a Gateway with OAuth Configuration

Use the Admin UI (`http://localhost:8000/admin`) or API:

```bash
# Generate a JWT token
export BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username user2@example.com \
  --exp 10080 \
  --secret your-secret-key-here \
  --teams '["team1"]')

# Create a gateway with OAuth config
curl -X POST "http://localhost:8000/gateways" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GitHub MCP Server",
    "url": "https://mcp.github.example.com",
    "description": "GitHub MCP server with OAuth",
    "team_id": "team1",
    "visibility": "team",
    "oauth_config": {
      "grant_type": "authorization_code",
      "client_id": "your-oauth-client-id",
      "client_secret": "your-oauth-client-secret",
      "authorization_url": "https://github.com/login/oauth/authorize",
      "token_url": "https://github.com/login/oauth/access_token",
      "redirect_uri": "http://localhost:8000/oauth/callback",
      "scopes": ["read:org", "repo"],
      "resource": "https://mcp.github.example.com"
    }
  }'
```

Note the returned `gateway_id` (e.g., `ca602dd4-...`).

### Step 2: Initiate OAuth Flow

Visit the OAuth authorization URL in your browser:

```
http://localhost:8000/oauth/authorize/{gateway_id}
```

Replace `{gateway_id}` with the actual gateway ID from Step 1.

**What happens:**
1. ContextForge redirects you to the OAuth provider (e.g., GitHub)
2. You authorize the application
3. The provider redirects back to `/oauth/callback` with an authorization code
4. ContextForge exchanges the code for tokens
5. Tokens are stored in Vault

### Step 3: Verify Token Storage in Vault

After completing the OAuth flow, check Vault:

```bash
# Set Vault environment
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=test-root-token

# List team_ids
vault kv list secret/contextforge/oauth/

# List server_ids within a team
vault kv list secret/contextforge/oauth/team1/

# The server_id is SHA-256 hash of gateway.url (first 8 chars)
# For url="https://mcp.github.example.com":
# server_id=$(echo -n "https://mcp.github.example.com" | sha256sum | cut -c1-8)
# Example: ca602dd4

# Get the token for user2@example.com
vault kv get secret/contextforge/oauth/team1/ca602dd4/user2%40example.com
```

Expected output:
```
====== Data ======
Key              Value
---              -----
access_token     gho_xxxxxxxxxxxxx
expires_at       2026-07-09T15:30:00Z
gateway_id       ca602dd4-1234-5678-90ab-cdef12345678
refresh_token    ghr_xxxxxxxxxxxxx (optional)
scopes           ["read:org", "repo"]
user_id          user2@example.com
```

### Step 4: Test Token Retrieval

```bash
# Get tokens programmatically (Python)
python3 << 'EOF'
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pydantic import SecretStr
from mcpgateway.config import Settings
from mcpgateway.services.token_backends.vault_backend import VaultTokenBackend

async def get_token():
    # Database session
    engine = create_engine("sqlite:///./mcp.db")
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # Vault settings
    settings = Settings()
    settings.vault_addr = "http://localhost:8200"
    settings.vault_token = SecretStr("test-root-token")
    settings.vault_kv_mount = "secret"
    settings.vault_kv_path_prefix = "contextforge/oauth"
    settings.vault_tls_verify = False
    
    # Backend
    backend = VaultTokenBackend(db, settings)
    
    # Get token
    token = await backend.get_token(
        gateway_id="ca602dd4-1234-5678-90ab-cdef12345678",  # Your gateway ID
        team_id="team1",
        app_user_email="user2@example.com"
    )
    
    print(f"Access Token: {token.access_token[:20]}...")
    print(f"Expires At: {token.expires_at}")
    print(f"Scopes: {token.scopes}")
    
    db.close()

asyncio.run(get_token())
EOF
```

## Vault Path Structure

Tokens are stored at:
```
{mount}/data/{prefix}/{team_id}/{server_id}/{url-encoded-email}
```

Example:
```
secret/data/contextforge/oauth/team1/ca602dd4/user2%40example.com
```

Where:
- **mount**: `secret` (default KV v2 mount)
- **prefix**: `contextforge/oauth` (configurable via `VAULT_KV_PATH_PREFIX`)
- **team_id**: `team1` (from user's JWT `teams` claim or database)
- **server_id**: `ca602dd4` (first 8 chars of SHA-256 hash of `gateway.url`)
- **email**: `user2%40example.com` (URL-encoded user email)

## Cleanup

### Delete Specific User's Tokens

```bash
# Delete tokens for user2@example.com across all teams
vault kv list -mount=secret contextforge/oauth/ 2>&1 | tail -n +3 | while read team; do
  vault kv delete -mount=secret "contextforge/oauth/${team%/}/ca602dd4/user2@example.com" 2>/dev/null
done
```

### Delete All Team's OAuth Tokens

```bash
vault kv metadata delete -mount=secret "contextforge/oauth/team1"
```

### Delete All OAuth Tokens (Nuclear Option)

```bash
vault kv metadata delete -mount=secret "contextforge/oauth"
```

## Troubleshooting

### Vault Connection Errors

```bash
# Check Vault health
curl http://localhost:8200/v1/sys/health

# Verify token
curl -H "X-Vault-Token: test-root-token" \
  http://localhost:8200/v1/sys/internal/ui/mounts
```

### Token Not Found

1. Verify gateway exists in database:
   ```bash
   sqlite3 mcp.db "SELECT id, url FROM gateways WHERE id='ca602dd4-...';"
   ```

2. Check server_id calculation:
   ```bash
   echo -n "https://mcp.github.example.com" | sha256sum | cut -c1-8
   ```

3. Verify team_id from JWT:
   ```bash
   python -m mcpgateway.utils.create_jwt_token \
     --username user2@example.com \
     --teams '["team1"]' \
     --secret your-secret-key-here \
     --decode
   ```

### OAuth Callback Errors

Check logs:
```bash
# ContextForge logs
tail -f logs/mcpgateway.log

# Look for:
# - "OAuth callback received"
# - "Storing tokens in Vault"
# - "Token storage failed"
```

## Integration Tests

Run the full integration test suite:

```bash
# Ensure Vault is running
docker-compose -f docker-compose.vault-test.yml up -d

# Run integration tests
VAULT_ADDR=http://localhost:8200 \
VAULT_TOKEN=test-root-token \
pytest tests/integration/test_vault_integration.py -v
```

## Security Considerations

1. **Production Vault Setup**:
   - Use TLS (`VAULT_TLS_VERIFY=true`)
   - Never use root token in production
   - Use AppRole or Kubernetes auth
   - Enable audit logging

2. **Token Rotation**:
   - Vault tokens are not automatically rotated
   - Implement refresh token logic in OAuthManager
   - Monitor token expiry

3. **Access Control**:
   - Limit Vault policy to specific path prefixes
   - Use namespaces for multi-tenancy
   - Audit who accessed which tokens

Example production Vault policy:
```hcl
path "secret/data/contextforge/oauth/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "secret/metadata/contextforge/oauth/*" {
  capabilities = ["list", "read", "delete"]
}
```

## Next Steps

1. ✅ Test OAuth flow with Vault storage
2. ✅ Verify token retrieval
3. ✅ Test token refresh (if using refresh tokens)
4. 🔄 Test MCP server calls with delegated tokens
5. 🔄 Test token expiry and refresh logic
6. 🔄 Production Vault setup with proper auth

## References

- [OAuth Design Document](./architecture/oauth-design.md)
- [Vault KV v2 API](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)
- [ContextForge RBAC Guide](./manage/rbac.md)
