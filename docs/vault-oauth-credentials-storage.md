# Team-Scoped OAuth Credentials in Vault

## Problem Statement

When using `OAUTH_TOKEN_BACKEND=vault`, OAuth **tokens** (access_token/refresh_token) are stored per team in Vault, but OAuth **credentials** (client_id/client_secret) are stored in the database `gateways.oauth_config` table, which is **not team-scoped**.

This creates a mismatch in multi-team scenarios:
- **Token storage**: Team-scoped (Vault path includes `team_id`)
- **OAuth credentials**: Gateway-scoped (database `gateways` table, shared across teams)

### Symptoms

When a user with JWT `team_id: f8927490a44d4ede95889136d004c202` tries to complete OAuth:
1. OAuth flow is initiated with correct team context
2. OAuth state stores the `team_id` from JWT
3. On callback, code retrieves credentials from `gateway.oauth_config` (database)
4. But these credentials might be for a different team's OAuth app!
5. GitHub (or other IdP) rejects with `incorrect_client_credentials` error

### Root Cause

The `gateway.oauth_config` in the database contains OAuth credentials that are NOT team-specific. In a multi-team deployment where the same MCP server URL is registered by multiple teams with different OAuth apps, each team needs its own `client_id` and `client_secret`.

## Solution: Store OAuth Credentials Per Team in Vault

### Architecture

OAuth credentials should be stored in Vault at a team-scoped path, parallel to token storage:

**Token storage path:**
```
{mount}/data/{prefix}/{team_id}/{server_id}/{email}
```

**Credentials storage path:**
```
{mount}/data/{prefix}/credentials/{team_id}/{server_id}
```

### Example

For team `f8927490a44d4ede95889136d004c202` accessing `https://mcp.github.acme.com`:

```bash
# Calculate server_id
$ echo -n "https://mcp.github.acme.com" | sha256sum | cut -c1-8
647ad7b3

# Credentials path
secret/data/contextforge/oauth/credentials/f8927490a44d4ede95889136d004c202/647ad7b3

# Token path (per user)
secret/data/contextforge/oauth/f8927490a44d4ede95889136d004c202/647ad7b3/alice%40example.com
```

### Credentials Payload Structure

```json
{
  "data": {
    "team_id": "f8927490a44d4ede95889136d004c202",
    "mcp_url": "https://mcp.github.acme.com",
    "client_id": "Iv1.abc123def456",
    "client_secret": "ghp_secret_value_here",
    "authorization_url": "https://github.com/login/oauth/authorize",
    "token_url": "https://github.com/login/oauth/access_token",
    "scopes": ["repo", "read:org"],
    "grant_type": "authorization_code",
    "token_endpoint_auth_method": "client_secret_post",
    "resource": "https://mcp.github.acme.com",
    "updated_at": "2026-07-13T11:00:00Z"
  }
}
```

## Implementation

### Backend Methods

The `VaultTokenBackend` now includes two new methods:

#### `get_oauth_credentials(team_id: str, mcp_url: str) -> dict | None`

Retrieves team-scoped OAuth credentials from Vault.

**Returns:**
- OAuth config dict if found in Vault
- `None` if not found (falls back to database `gateway.oauth_config`)

**Example:**
```python
vault_backend = VaultTokenBackend(db, settings)
credentials = await vault_backend.get_oauth_credentials(
    team_id="f8927490a44d4ede95889136d004c202",
    mcp_url="https://mcp.github.acme.com"
)
```

#### `store_oauth_credentials(team_id: str, mcp_url: str, credentials: dict) -> bool`

Stores team-scoped OAuth credentials in Vault.

**Example:**
```python
success = await vault_backend.store_oauth_credentials(
    team_id="f8927490a44d4ede95889136d004c202",
    mcp_url="https://mcp.github.acme.com",
    credentials={
        "client_id": "Iv1.abc123def456",
        "client_secret": "ghp_secret_value_here",
        "authorization_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "read:org"],
    }
)
```

### OAuth Callback Flow

Both `/oauth/callback` and `/vault/callback` now follow this logic:

1. **Retrieve state data** (includes `team_id` from JWT)
2. **Try Vault credentials first**:
   ```python
   if team_id and hasattr(token_storage._backend, 'get_oauth_credentials'):
       vault_credentials = await token_storage._backend.get_oauth_credentials(
           team_id, gateway.url
       )
       if vault_credentials:
           # Use team-scoped credentials
           oauth_config_with_resource = vault_credentials.copy()
   ```
3. **Fall back to database** if Vault returns `None`:
   ```python
   if not oauth_config_with_resource:
       # Use gateway.oauth_config from database
       oauth_config_with_resource = gateway.oauth_config.copy()
   ```
4. **Complete OAuth flow** with resolved credentials

### Backward Compatibility

- Existing deployments continue working (database fallback)
- Only teams that store credentials in Vault use team-scoped OAuth
- No breaking changes to API or database schema

## Usage

### Storing Credentials in Vault

#### Using Shell Script

```bash
./scripts/store-oauth-credentials-vault.sh \
  "f8927490a44d4ede95889136d004c202" \
  "https://mcp.github.acme.com" \
  "Iv1.abc123def456" \
  "ghp_secret_value_here" \
  '{"authorization_url": "https://github.com/login/oauth/authorize", "token_url": "https://github.com/login/oauth/access_token", "scopes": ["repo", "read:org"]}'
```

#### Using Python Script

```python
from mcpgateway.services.token_backends import VaultTokenBackend
from mcpgateway.config import get_settings
from mcpgateway.db import get_db

db = next(get_db())
settings = get_settings()
vault = VaultTokenBackend(db, settings)

await vault.store_oauth_credentials(
    team_id="f8927490a44d4ede95889136d004c202",
    mcp_url="https://mcp.github.acme.com",
    credentials={
        "client_id": "Iv1.abc123def456",
        "client_secret": "ghp_secret_value_here",
        "authorization_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "read:org"],
        "grant_type": "authorization_code",
        "token_endpoint_auth_method": "client_secret_post",
    }
)
```

#### Using Vault CLI

```bash
# Calculate server_id
SERVER_ID=$(echo -n "https://mcp.github.acme.com" | sha256sum | cut -c1-8)

# Store credentials
vault kv put secret/contextforge/oauth/credentials/f8927490a44d4ede95889136d004c202/$SERVER_ID \
  team_id="f8927490a44d4ede95889136d004c202" \
  mcp_url="https://mcp.github.acme.com" \
  client_id="Iv1.abc123def456" \
  client_secret="ghp_secret_value_here" \
  authorization_url="https://github.com/login/oauth/authorize" \
  token_url="https://github.com/login/oauth/access_token" \
  scopes='["repo", "read:org"]' \
  grant_type="authorization_code" \
  token_endpoint_auth_method="client_secret_post"
```

### Retrieving Credentials from Vault

#### Using Python Script

```bash
python3 scripts/get-oauth-credentials-vault.py \
  "f8927490a44d4ede95889136d004c202" \
  "https://mcp.github.acme.com"
```

Output:
```
Retrieving OAuth credentials from Vault
  Team ID: f8927490a44d4ede95889136d004c202
  MCP URL: https://mcp.github.acme.com
  Server ID: 647ad7b3
  Vault Path: secret/data/contextforge/oauth/credentials/f8927490a44d4ede95889136d004c202/647ad7b3

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

#### Using Vault CLI

```bash
vault kv get secret/contextforge/oauth/credentials/f8927490a44d4ede95889136d004c202/647ad7b3
```

## Multi-Team Same-URL Scenario

### Setup

Two teams register the same GitHub MCP server URL with different OAuth apps:

**Team Engineering:**
```bash
# GitHub OAuth App ID: Iv1.engineering123
./scripts/store-oauth-credentials-vault.sh \
  "engineering" \
  "https://mcp.github.acme.com" \
  "Iv1.engineering123" \
  "secret_engineering"
```

**Team Sales:**
```bash
# GitHub OAuth App ID: Iv1.sales456
./scripts/store-oauth-credentials-vault.sh \
  "sales" \
  "https://mcp.github.acme.com" \
  "Iv1.sales456" \
  "secret_sales"
```

### Vault Structure

```
secret/data/contextforge/oauth/
├─ credentials/
│  ├─ engineering/
│  │  └─ 647ad7b3/  (hash of https://mcp.github.acme.com)
│  │     [client_id: Iv1.engineering123, client_secret: secret_engineering]
│  └─ sales/
│     └─ 647ad7b3/  (same hash, different team!)
│        [client_id: Iv1.sales456, client_secret: secret_sales]
└─ (tokens stored per user, as before)
   ├─ engineering/
   │  └─ 647ad7b3/
   │     ├─ alice%40example.com
   │     └─ bob%40example.com
   └─ sales/
      └─ 647ad7b3/
         └─ charlie%40example.com
```

### Access Flow

**Alice (engineering team):**
1. JWT: `{"teams": ["engineering"], "email": "alice@example.com"}`
2. Initiates OAuth → `/oauth/authorize/{gateway_id}`
3. OAuth state stores `team_id: "engineering"`
4. Callback retrieves credentials from Vault: `credentials/engineering/647ad7b3`
5. Uses `client_id: Iv1.engineering123` for token exchange
6. ✅ GitHub authorizes with engineering's OAuth app
7. Tokens stored at: `engineering/647ad7b3/alice%40example.com`

**Charlie (sales team):**
1. JWT: `{"teams": ["sales"], "email": "charlie@example.com"}`
2. Initiates OAuth → `/oauth/authorize/{gateway_id}`
3. OAuth state stores `team_id: "sales"`
4. Callback retrieves credentials from Vault: `credentials/sales/647ad7b3`
5. Uses `client_id: Iv1.sales456` for token exchange
6. ✅ GitHub authorizes with sales' OAuth app
7. Tokens stored at: `sales/647ad7b3/charlie%40example.com`

## Security Benefits

1. **Team Isolation**: Each team's OAuth credentials are isolated in Vault
2. **Audit Trail**: Vault audit logs track credential access per team
3. **Independent Rotation**: Teams can rotate OAuth credentials without affecting others
4. **Encryption at Rest**: Vault encrypts all credentials
5. **Access Control**: Vault policies can restrict credential access by team
6. **Fail-Closed**: If Vault is unavailable, OAuth flows fail (no silent fallback to wrong credentials)

## Vault Policies

### Basic Policy (All Teams)

```hcl
# Allow all teams to access their own credentials
path "secret/data/contextforge/oauth/credentials/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "secret/metadata/contextforge/oauth/credentials/*" {
  capabilities = ["list", "read", "delete"]
}
```

### Team-Isolated Policy

```hcl
# Engineering team can only access engineering/ paths
path "secret/data/contextforge/oauth/credentials/engineering/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "secret/data/contextforge/oauth/engineering/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "secret/metadata/contextforge/oauth/credentials/engineering/*" {
  capabilities = ["list", "read", "delete"]
}

path "secret/metadata/contextforge/oauth/engineering/*" {
  capabilities = ["list", "read", "delete"]
}
```

## Troubleshooting

### Issue: "incorrect_client_credentials" from GitHub

**Symptom:**
```
OAuth callback failed: No access_token in response: 
{'error': 'incorrect_client_credentials', ...}
```

**Root Cause:** Wrong OAuth credentials being used for this team.

**Solution:**
1. Verify team_id in JWT:
   ```bash
   python3 -m mcpgateway.utils.create_jwt_token \
     --username alice@example.com \
     --teams '["f8927490a44d4ede95889136d004c202"]' \
     --secret your-secret \
     --decode
   ```

2. Check if credentials exist in Vault:
   ```bash
   python3 scripts/get-oauth-credentials-vault.py \
     "f8927490a44d4ede95889136d004c202" \
     "https://mcp.github.acme.com"
   ```

3. If not found, store correct credentials:
   ```bash
   ./scripts/store-oauth-credentials-vault.sh \
     "f8927490a44d4ede95889136d004c202" \
     "https://mcp.github.acme.com" \
     "Iv1.correct_client_id" \
     "correct_secret"
   ```

4. Retry OAuth flow

### Issue: Credentials Not Found in Vault

**Symptom:** Warning logs:
```
Using database OAuth credentials for gateway xyz. 
For multi-team isolation, store credentials in Vault per team.
```

**This is expected** if you haven't migrated to Vault credentials yet. The system falls back to `gateway.oauth_config` from database.

**To migrate:**
1. Extract current credentials from database:
   ```sql
   SELECT id, url, oauth_config FROM gateways WHERE id = 'gateway-id';
   ```

2. Store in Vault per team:
   ```bash
   ./scripts/store-oauth-credentials-vault.sh \
     "<team_id>" \
     "<gateway_url>" \
     "<client_id>" \
     "<client_secret>" \
     '{"authorization_url": "...", "token_url": "..."}'
   ```

3. Repeat for each team that uses this gateway

## Migration Guide

### Step 1: Identify Multi-Team Gateways

```sql
SELECT 
  g.id,
  g.url,
  g.team_id,
  COUNT(DISTINCT oat.team_id) AS num_teams_using
FROM gateways g
LEFT JOIN oauth_tokens oat ON oat.gateway_id = g.id
WHERE g.auth_type = 'oauth'
GROUP BY g.id, g.url, g.team_id
HAVING num_teams_using > 1;
```

### Step 2: Extract Credentials Per Team

For each gateway with multiple teams, register separate OAuth apps per team on the IdP (GitHub, GitLab, etc.) and store credentials in Vault.

### Step 3: Store Credentials in Vault

Use the provided scripts to store team-scoped credentials.

### Step 4: Test OAuth Flow

1. Generate JWT with correct team_id
2. Initiate OAuth flow
3. Verify credentials are retrieved from Vault (check logs)
4. Complete authorization
5. Verify tokens stored in correct Vault path

### Step 5: Monitor and Validate

Monitor logs for:
- "Using team-scoped OAuth credentials from Vault" (success)
- "Using database OAuth credentials" (fallback - consider migration)

## References

- [OAuth + Vault: Team-Isolated Token Storage](./oauth-vault-team-isolation.md)
- [Testing OAuth with Vault](./testing-oauth-vault.md)
- [Vault Backend Implementation](../mcpgateway/services/token_backends/vault_backend.py)
- [OAuth Router](../mcpgateway/routers/oauth_router.py)
- [Vault Router](../mcpgateway/routers/vault_router.py)
