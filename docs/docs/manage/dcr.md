# Dynamic Client Registration (DCR)

Dynamic Client Registration (DCR) is an OAuth 2.0 extension that enables automatic client registration without manual configuration. This guide explains how to configure and use DCR with ContextForge for streamable HTTP servers.

## Overview

DCR solves a common authentication challenge in distributed MCP deployments:

- **Traditional OAuth2** requires pre-configured client credentials for each MCP server
- **With DCR**, MCP clients can automatically register themselves as OAuth2 clients

**Key Benefits:**

- ✅ Zero-touch OAuth configuration - no manual credential management
- ✅ Automatic discovery via RFC 8414 (Authorization Server Metadata)
- ✅ Support for public clients (PKCE-only, no client secret)
- ✅ Credential encryption and secure storage
- ✅ Issuer allowlist for security

---

## What is Dynamic Client Registration?

Dynamic Client Registration is defined in [RFC 7591](https://tools.ietf.org/html/rfc7591) as a protocol that allows OAuth 2.0 clients to register with authorization servers dynamically. In the context of ContextForge:

1. **Discovery Phase**: Gateway discovers Authorization Server (AS) metadata via [RFC 8414](https://tools.ietf.org/html/rfc8414)
2. **Registration Phase**: Gateway registers itself as an OAuth client with the AS
3. **Token Phase**: Gateway uses registered credentials for standard OAuth flows

---

## Environment Variables

```bash
# DCR Feature Control
MCPGATEWAY_DCR_ENABLED=true                              # Enable/disable DCR (default: true)
MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS=true # Auto-register when gateway has issuer but no client_id (default: true)

# DCR Configuration
MCPGATEWAY_DCR_DEFAULT_SCOPES="mcp:read"                 # Default scopes to request (comma-separated, default: mcp:read)
MCPGATEWAY_DCR_ALLOWED_ISSUERS=""                        # Optional allowlist of issuer URLs (empty = allow any)
MCPGATEWAY_DCR_TOKEN_ENDPOINT_AUTH_METHOD="client_secret_basic" # Auth method: client_secret_basic or client_secret_post
MCPGATEWAY_DCR_METADATA_CACHE_TTL=3600                   # AS metadata cache TTL in seconds (default: 1 hour)
MCPGATEWAY_DCR_CLIENT_NAME_TEMPLATE="ContextForge ({gateway_name})" # Client name template for registration
MCPGATEWAY_DCR_REQUEST_REFRESH_TOKEN_WHEN_UNSUPPORTED=false       # Request refresh_token when AS omits grant_types_supported

# OAuth Settings (used by DCR)
OAUTH_REQUEST_TIMEOUT=30                                 # HTTP request timeout in seconds
AUTH_ENCRYPTION_SECRET=<strong-random-key>               # Required for encrypting client secrets
```

!!! important "Security Note"
    Always set `AUTH_ENCRYPTION_SECRET` to a strong random value. DCR-registered client secrets and refresh tokens are encrypted using this key.

---

## How It Works

### 1. AS Metadata Discovery (RFC 8414)

When you configure a gateway with an `issuer` URL, the gateway automatically discovers the AS configuration:

```
GET https://auth.example.com/.well-known/oauth-authorization-server
```

If that fails, tries OIDC discovery:

```
GET https://auth.example.com/.well-known/openid-configuration
```

The metadata response includes:

- `registration_endpoint` - Where to register clients
- `authorization_endpoint` - OAuth authorization URL
- `token_endpoint` - Token exchange URL
- Supported grant types, scopes, and auth methods

**Caching:** Metadata is cached for `MCPGATEWAY_DCR_METADATA_CACHE_TTL` seconds (default: 1 hour).

### 2. Client Registration (RFC 7591)

If no `client_id` is configured and `MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS=true`, the gateway automatically registers:

```json
POST https://auth.example.com/register
Content-Type: application/json

{
  "client_name": "ContextForge (GitHub MCP)",
  "redirect_uris": ["https://gateway.example.com/oauth/callback"],
  "grant_types": ["authorization_code"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "client_secret_basic",
  "scope": "mcp:read mcp:write"
}
```

The AS responds with registered credentials:

```json
{
  "client_id": "auto-generated-id",
  "client_secret": "auto-generated-secret",
  "registration_access_token": "...",
  "registration_client_uri": "https://auth.example.com/register/auto-generated-id"
}
```

Gateway stores these in the `registered_oauth_clients` table (encrypted).

!!! note "Refresh Token Behavior"
    By default, `refresh_token` is only requested if the AS metadata explicitly includes `"refresh_token"` in `grant_types_supported`. This prevents DCR failures with strict AS servers. To request `refresh_token` when AS metadata omits `grant_types_supported`, set `MCPGATEWAY_DCR_REQUEST_REFRESH_TOKEN_WHEN_UNSUPPORTED=true`.

### 3. OAuth Flow with Registered Credentials

Once registered, the gateway uses the client credentials for standard OAuth flows with automatic PKCE.

---

## Architecture

A simplified architecture. Please view the following guide for an in-depth swimlane chart:

📖 **[Dynamic Client Registration with HyperMCP Tutorial](../tutorials/dcr-hyprmcp.md)**

```mermaid
graph LR
    Client[MCP Client]
    HyprMCP[HyprContextForge]
    Dex[Dex]
    IdP[Federated IdP<br/>GitHub/Google/LDAP]
    ContextForge[ContextForge]

    Client --> HyprMCP
    HyprMCP --> Dex
    Dex -.-> IdP
    HyprMCP --> ContextForge
```

---

## Configuration Examples

### Automatic Registration (Recommended)

Configure a gateway with just the issuer URL - credentials auto-register:

**Admin UI:**

1. Create/Edit Gateway → Authentication Type: OAuth
2. Set Grant Type: `authorization_code`
3. Set Issuer: `https://auth.example.com`
4. Set Redirect URI: `https://gateway.example.com/oauth/callback`
5. Leave Client ID and Client Secret empty
6. Save → Gateway auto-registers and stores credentials

**JSON/API:**

```json
{
  "name": "Auto-DCR Gateway",
  "url": "https://mcp.example.com/sse",
  "auth_type": "oauth",
  "oauth_config": {
    "grant_type": "authorization_code",
    "issuer": "https://auth.example.com",
    "redirect_uri": "https://gateway.example.com/oauth/callback",
    "scopes": ["mcp:read", "mcp:write"]
  }
}
```

### Manual Client Credentials (Fallback)

If DCR is disabled or you have pre-registered credentials:

```json
{
  "name": "Manual OAuth Gateway",
  "url": "https://mcp.example.com/sse",
  "auth_type": "oauth",
  "oauth_config": {
    "grant_type": "authorization_code",
    "client_id": "pre-registered-id",
    "client_secret": "pre-registered-secret",
    "authorization_url": "https://auth.example.com/authorize",
    "token_url": "https://auth.example.com/token",
    "redirect_uri": "https://gateway.example.com/oauth/callback",
    "scopes": ["mcp:read"]
  }
}
```

### Public Client with PKCE Only

For public clients that don't support client secrets:

```json
{
  "name": "Public Client Gateway",
  "url": "https://mcp.example.com/sse",
  "auth_type": "oauth",
  "oauth_config": {
    "grant_type": "authorization_code",
    "issuer": "https://auth.example.com",
    "client_id": "public-client-id",
    "redirect_uri": "https://gateway.example.com/oauth/callback",
    "scopes": ["mcp:read"]
  }
}
```

Note: No `client_secret` - PKCE provides security.

---

## Per-Gateway Control (`use_dcr`)

DCR is normally governed by two **deployment-global** environment variables
(`MCPGATEWAY_DCR_ENABLED`, `MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS`).
For fleets where different authorization servers need different behavior, set
`oauth_config.use_dcr` **per gateway** to override the global auto-register
setting for that gateway alone:

| `oauth_config.use_dcr` | `MCPGATEWAY_DCR_ENABLED` | `MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS` | Result when gateway has `issuer` but no `client_id` |
|------------------------|--------------------------|--------------------------------------------------------|-----------------------------------------------------|
| absent                 | `true`                   | `true`                                                 | DCR (default behavior)                              |
| absent                 | any                      | `false`                                                | 400 - provide credentials manually                  |
| `true`                 | `true`                   | any                                                    | DCR (forces registration)                           |
| `true`                 | `false`                  | any                                                    | 400 - DCR disabled globally                         |
| `false`                | any                      | any                                                    | never DCR - 400 - provide credentials manually      |
| invalid value          | any                      | any                                                    | rejected at create/update (400); treated as absent at runtime |

- `use_dcr` accepts native booleans or the strings `"true"`/`"false"`
  (case-insensitive) for interop with clients that serialize booleans to strings.
- `None`, `""`, or whitespace-only values are treated as **absent**
  (same empty-means-unset convention as every other `oauth_config` field).
- `use_dcr: true` cannot re-enable DCR when the deployment master switch
  `MCPGATEWAY_DCR_ENABLED=false` - the global flag always wins.
- The flag is read only when a gateway has an `issuer` and no `client_id`.
  Gateways with full credentials are unaffected.

### Example: force DCR for one gateway while the global auto-register is off

```json
{
  "name": "Force-DCR Gateway",
  "url": "https://mcp.example.com/sse",
  "auth_type": "oauth",
  "oauth_config": {
    "grant_type": "authorization_code",
    "issuer": "https://keycloak.example.com/realms/mcp",
    "redirect_uri": "https://gateway.example.com/oauth/callback",
    "use_dcr": true
  }
}
```

### Example: explicit opt-out - never auto-register this gateway

```json
{
  "name": "Manual-Only Gateway",
  "url": "https://mcp.example.com/sse",
  "auth_type": "oauth",
  "oauth_config": {
    "grant_type": "authorization_code",
    "issuer": "https://auth.saas-provider.com",
    "client_id": "pre-provisioned-client",
    "client_secret": "pre-provisioned-secret",
    "authorization_url": "https://auth.saas-provider.com/authorize",
    "token_url": "https://auth.saas-provider.com/token",
    "redirect_uri": "https://gateway.example.com/oauth/callback",
    "use_dcr": false
  }
}
```

### Example: absent - defer to global settings (default)

Omit `use_dcr` entirely; behavior matches the global environment variables
exactly (see the [Automatic Registration](#automatic-registration-recommended)
and [Manual Client Credentials](#manual-client-credentials-fallback) examples).

### Migrating from global-only to per-gateway control

1. Audit existing gateways that would be affected by DCR:

   ```sql
   SELECT id, name, oauth_config
   FROM gateways
   WHERE oauth_config->>'issuer' IS NOT NULL
     AND oauth_config->>'client_id' IS NULL;
   ```

2. For each gateway, decide and set `use_dcr`:

   - `true` if the authorization server supports RFC 7591 and the gateway
     should keep auto-registering;
   - `false` if credentials are provisioned out-of-band and registration must
     never happen.

3. Flip the global default:

   ```bash
   MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS=false
   ```

4. Update each gateway via the admin API (`PUT /gateways/{id}`) and verify
   first-use registration works for the `use_dcr: true` gateways.

---

## Per-Gateway Token Endpoint Auth Method (`token_endpoint_auth_method`)

`oauth_config.token_endpoint_auth_method` overrides the global
`MCPGATEWAY_DCR_TOKEN_ENDPOINT_AUTH_METHOD` setting for a single gateway's
DCR registration request (RFC 7591).

| `oauth_config.token_endpoint_auth_method` | Registration behavior |
|---|---|
| `client_secret_basic` | Registers the client with `token_endpoint_auth_method: client_secret_basic` |
| `client_secret_post` | Registers the client with `token_endpoint_auth_method: client_secret_post` |
| absent / empty | Registration uses the global `MCPGATEWAY_DCR_TOKEN_ENDPOINT_AUTH_METHOD` |

- Only `client_secret_basic` and `client_secret_post` are accepted.
  `none`, `private_key_jwt`, and any other value are rejected at create/update
  time: the gateway runtime authenticates DCR-registered clients with a client
  secret, so public-client (`none`) registration is not supported yet.
- The authorization server's registration response is authoritative: the
  `token_endpoint_auth_method` the AS confirms is what gets stored back into
  `oauth_config` and used for subsequent token requests.
- UIs that send the ICA-style boolean `useClientSecretTokenAuthMethod` should
  map it here: `true` -> `client_secret_basic`. The 1.0-style `false` ->
  `none` (public PKCE client) mapping is a separate follow-up; ContextForge
  does not currently support token endpoint auth method `none`.
- Invalid values in an existing gateway row (for example, written before the
  validation landed) are treated as absent at registration time, deferring to
  the global setting.

---

## Database Schema

DCR uses three tables:

### `registered_oauth_clients`

Stores auto-registered OAuth clients:

```sql
CREATE TABLE registered_oauth_clients (
    id VARCHAR(36) PRIMARY KEY,
    gateway_id VARCHAR(255) NOT NULL,
    issuer VARCHAR(500) NOT NULL,
    client_id VARCHAR(255) NOT NULL,
    client_secret_encrypted TEXT,
    redirect_uris TEXT NOT NULL,
    grant_types TEXT NOT NULL,
    scope VARCHAR(1000),
    registration_client_uri VARCHAR(500),
    registration_access_token_encrypted TEXT,
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    is_active BOOLEAN,
    UNIQUE (gateway_id, issuer)
);
```

### `oauth_states`

Stores OAuth authorization state with PKCE verifiers:

```sql
CREATE TABLE oauth_states (
    id VARCHAR(36) PRIMARY KEY,
    gateway_id VARCHAR(255) NOT NULL,
    state VARCHAR(255) NOT NULL UNIQUE,
    code_verifier VARCHAR(255),  -- PKCE code verifier
    app_user_email VARCHAR(255),
    created_at TIMESTAMP,
    expires_at TIMESTAMP
);
```

### `oauth_tokens`

Stores per-user delegated OAuth tokens used after DCR registration and authorization:

```sql
CREATE TABLE oauth_tokens (
    id VARCHAR(36) PRIMARY KEY,
    gateway_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(255) NOT NULL,              -- OAuth provider identity
    app_user_email VARCHAR(255) NOT NULL,       -- ContextForge user identity
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_type VARCHAR(50),
    expires_at TIMESTAMP,
    scopes JSON,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    CONSTRAINT uq_oauth_gateway_user UNIQUE (gateway_id, app_user_email),
    FOREIGN KEY (gateway_id) REFERENCES gateways(id) ON DELETE CASCADE,
    FOREIGN KEY (app_user_email) REFERENCES email_users(email) ON DELETE CASCADE
);
```

!!! note "Index Redundancy"
    Earlier versions created a separate unique index `idx_oauth_gateway_user` on `(gateway_id, app_user_email)`, but migration `7ab59991e017` removes it as redundant—the `UNIQUE` constraint already creates an index automatically.

Historical note: older deployments used `unique_gateway_user` on `(gateway_id, user_id)`. That constraint was removed because multiple ContextForge users can legitimately map to the same upstream OAuth provider `user_id`.

---

## Downgrading from Migration 7ab59991e017

!!! warning "Data Loss Risk"
    Downgrading this migration may require deleting OAuth tokens. Users whose tokens are removed will need to re-authorize.

### Prerequisites

Migration 7ab59991e017 enables multi-user OAuth support, allowing multiple ContextForge users to store tokens for the same OAuth provider `user_id`. If you need to downgrade, you must first resolve any duplicate `(gateway_id, user_id)` pairs.

### Step 1: Check for Duplicates

```sql
-- Identify duplicate pairs
SELECT gateway_id, user_id, COUNT(*) as token_count
FROM oauth_tokens
GROUP BY gateway_id, user_id
HAVING COUNT(*) > 1;
```

If this query returns rows, you have duplicates that must be resolved before downgrading.

### Step 2: Choose Resolution Strategy

#### Option A: Keep Newest Token (Recommended)

Keep only the most recently updated token for each duplicate pair:

**SQLite:**
```sql
DELETE FROM oauth_tokens
WHERE id NOT IN (
    SELECT id FROM (
        SELECT id, gateway_id, user_id,
               ROW_NUMBER() OVER (
                   PARTITION BY gateway_id, user_id
                   ORDER BY updated_at DESC, created_at DESC
               ) as rn
        FROM oauth_tokens
    ) WHERE rn = 1
);
```

**PostgreSQL:**
```sql
DELETE FROM oauth_tokens
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY gateway_id, user_id
                   ORDER BY updated_at DESC, created_at DESC
               ) as rn
        FROM oauth_tokens
    ) t WHERE rn > 1
);
```

#### Option B: Keep Specific User's Token

Keep tokens for a specific ContextForge user (e.g., admin):

```sql
DELETE FROM oauth_tokens
WHERE (gateway_id, user_id) IN (
    SELECT gateway_id, user_id
    FROM oauth_tokens
    GROUP BY gateway_id, user_id
    HAVING COUNT(*) > 1
)
AND app_user_email != 'admin@example.com';
```

#### Option C: Delete All Duplicates

Remove all tokens for duplicate pairs (users must re-authorize):

```sql
DELETE FROM oauth_tokens
WHERE (gateway_id, user_id) IN (
    SELECT gateway_id, user_id
    FROM oauth_tokens
    GROUP BY gateway_id, user_id
    HAVING COUNT(*) > 1
);
```

### Step 3: Verify No Duplicates Remain

```sql
-- Should return 0 rows
SELECT gateway_id, user_id, COUNT(*) as cnt
FROM oauth_tokens
GROUP BY gateway_id, user_id
HAVING COUNT(*) > 1;
```

### Step 4: Run Downgrade

```bash
cd mcpgateway
alembic downgrade c9f8e7d6a4b3
```

### Impact of Downgrade

After downgrading:

- Only ONE ContextForge user can store tokens per OAuth provider `user_id` per gateway
- If multiple users need access to the same gateway, they must use different OAuth provider accounts
- Users whose tokens were removed will need to re-authorize

---

## Security Features

### 1. Issuer Allowlist

Restrict which Authorization Servers can be used:

```bash
MCPGATEWAY_DCR_ALLOWED_ISSUERS='["https://trusted-as1.com", "https://trusted-as2.com"]'
```

If set, gateway will reject DCR for any issuer not in the list.

### 2. Encrypted Credentials

All sensitive data is encrypted at rest using `AUTH_ENCRYPTION_SECRET`:

- Client secrets
- Registration access tokens
- Refresh tokens

### 3. PKCE Integration

All Authorization Code flows automatically use PKCE (RFC 7636) for enhanced security:

- Prevents authorization code interception attacks
- Supports public clients without client secrets
- No configuration needed - always enabled

### 4. Metadata Validation

Gateway validates AS metadata responses:

- Issuer URL must match discovery URL
- Registration endpoint must be present
- Proper HTTP status codes (200/201 for registration)

---

## Troubleshooting

### DCR Registration Fails

**Error: "AS does not support Dynamic Client Registration"**

- The Authorization Server doesn't expose a `registration_endpoint` in its metadata
- Solution: Use manual client credentials instead

**Error: "Issuer not in allowed issuers list"**

- The issuer URL is not in `MCPGATEWAY_DCR_ALLOWED_ISSUERS`
- Solution: Add the issuer to the allowlist or clear the allowlist to allow any

**Error: "Failed to discover AS metadata"**

- The issuer URL is incorrect or unreachable
- Solution: Verify the issuer URL and network connectivity

### Client Registration Rejected

**HTTP 400/401 from AS**

- Check AS logs for specific error messages
- Verify redirect URI matches AS requirements
- Ensure scopes are supported by the AS

**HTTP 200 instead of 201**

- Some ASs return 200 instead of RFC 7591's 201 - this is accepted
- If registration still fails, check response body for errors

### Token Exchange Issues

**Invalid client_id after DCR**

- Verify registration was successful in `registered_oauth_clients` table
- Check that `client_secret_encrypted` was properly stored
- Try re-registering by deleting the record and recreating the gateway

---

## Monitoring

Check DCR activity in logs:

```bash
# Search for DCR operations
grep "Discovered AS metadata" logs/mcpgateway.log
grep "Successfully registered client" logs/mcpgateway.log
grep "Found existing registered client" logs/mcpgateway.log

# Check for errors
grep "DcrError" logs/mcpgateway.log
```

Query registered clients:

```sql
SELECT
    gateway_id,
    issuer,
    client_id,
    created_at,
    is_active
FROM registered_oauth_clients
WHERE is_active = 1;
```

---

## Related Documentation

- [OAuth 2.0 Integration](oauth.md) - General OAuth2 configuration and PKCE details
- [Proxy Authentication](../deployment/proxy-auth.md) - Using authentication proxies
- [SSO Configuration](sso.md) - Single Sign-On setup
- [Security Best Practices](securing.md) - Security guidelines
