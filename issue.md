# fix: OAuth-protected MCP servers (Salesforce) - token works but tool fetch fails

## Problem Statement

When connecting MCP Gateway to OAuth-protected MCP servers (like Salesforce MCP), the **OAuth flow completes successfully** and a valid token is obtained, but **fetching tools with that token fails**.

### What Works
- OAuth authorization_code flow completes
- User is redirected to Salesforce, grants consent
- Token is received and stored in the database
- Token storage/retrieval works correctly

### What Fails
- When clicking "Fetch Tools" after OAuth completion, the connection to the MCP server fails
- The gateway cannot use the valid OAuth token to communicate with the Salesforce MCP endpoint

### Workaround (Manual 3-Step Process)
Currently requires external tooling:

```bash
# Step 1: Run mcp-remote to handle OAuth flow (requires browser interaction)
npx -y mcp-remote \
  https://api.salesforce.com/platform/mcp/v1-beta.2/sobject-all \
  8080 \
  --static-oauth-client-info '{"client_id":"...","client_secret":"..."}'

# Step 2: Extract the token from local file system
export TOKEN=$(cat ~/.mcp-auth/mcp-remote-*/..._tokens.json | jq -r .access_token)

# Step 3: Register gateway with the manually extracted token
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "salesforce-mcp",
    "url": "https://api.salesforce.com/platform/mcp/v1-beta.2/sobject-all",
    "transport": "sse",
    "headers": {"Authorization": "Bearer '$TOKEN'"}
  }'
```

**Why this is problematic:**
- Requires external tooling (`mcp-remote`) and user intervention
- Token must be manually extracted and injected
- No automatic token refresh when tokens expire
- Not suitable for production deployments or automation
- Claude Code can connect directly (via stdio to mcp-remote), but Gateway cannot

## Current State of OAuth Implementation

MCP Gateway has **comprehensive OAuth infrastructure** that works well for:
- **Upstream authentication**: Users authenticating TO the gateway
- **User-scoped tokens**: Authorization Code flow with PKCE for user consent
- **Client Credentials**: M2M authentication where gateway is the resource server

### What's Implemented

| Component | Status | Notes |
|-----------|--------|-------|
| OAuth Manager | :white_check_mark: Full | Client credentials, password, auth code, refresh |
| PKCE Support (RFC 7636) | :white_check_mark: Full | Code challenge/verifier |
| Token Storage | :white_check_mark: Full | Encrypted, user-scoped |
| Dynamic Client Registration (RFC 7591) | :white_check_mark: Full | Auto-registration with AS |
| AS Metadata Discovery (RFC 8414) | :white_check_mark: Full | Well-known endpoints |
| Resource Parameter (RFC 8707) | :white_check_mark: Full | JWT access tokens |
| OAuth Router | :white_check_mark: Full | /oauth/authorize, /oauth/callback |

### What's Missing for Downstream Gateway OAuth

The gateway cannot act as an **OAuth client to downstream MCP servers** without manual intervention.

## Proposed Solution

### Phase 1: Gateway-Initiated OAuth for Downstream Servers

Add ability for the gateway to initiate and complete OAuth flows when registering remote MCP servers.

#### 1.1 New Gateway Registration with OAuth Config

```json
POST /gateways
{
  "name": "salesforce-mcp",
  "url": "https://api.salesforce.com/platform/mcp/v1-beta.2/sobject-all",
  "transport": "sse",
  "oauth_config": {
    "flow": "authorization_code",
    "client_id": "3MVG9KsVczVNcM8x...",
    "client_secret": "4720596669FAA788...",
    "authorization_endpoint": "https://login.salesforce.com/services/oauth2/authorize",
    "token_endpoint": "https://login.salesforce.com/services/oauth2/token",
    "scopes": ["api", "refresh_token"],
    "use_pkce": true
  }
}
```

#### 1.2 Automated Token Acquisition

When a gateway is registered with `oauth_config`:

1. **Client Credentials Flow** (for M2M): Gateway automatically fetches token
2. **Authorization Code Flow** (for user-delegated):
   - Gateway returns authorization URL
   - User completes consent in browser
   - Callback stores token in gateway's token storage
   - Gateway automatically uses stored token for requests

#### 1.3 New Endpoints

```
POST /gateways                           # Register with oauth_config
GET  /gateways/{id}/oauth/authorize      # Initiate auth code flow for downstream
POST /gateways/{id}/oauth/callback       # Handle downstream OAuth callback
GET  /gateways/{id}/oauth/token-status   # Check token validity
POST /gateways/{id}/oauth/refresh        # Force token refresh
DELETE /gateways/{id}/oauth/token        # Revoke stored token
```

### Phase 2: Service Account Support

Add non-user-scoped tokens for system/service accounts.

#### 2.1 New Model: `ServiceAccountToken`

```python
class ServiceAccountToken(Base):
    """Tokens for gateway-to-gateway communication (not user-scoped)"""
    __tablename__ = "service_account_tokens"

    id: Mapped[str] = mapped_column(primary_key=True)
    gateway_id: Mapped[str] = mapped_column(ForeignKey("gateways.id"))
    service_account_name: Mapped[str]  # e.g., "salesforce-integration"
    access_token: Mapped[str]  # Encrypted
    refresh_token: Mapped[Optional[str]]  # Encrypted
    token_type: Mapped[str] = mapped_column(default="Bearer")
    expires_at: Mapped[Optional[datetime]]
    scopes: Mapped[Optional[str]]
    created_at: Mapped[datetime]
    last_used_at: Mapped[Optional[datetime]]
```

#### 2.2 Service Account Configuration

```json
POST /gateways
{
  "name": "salesforce-mcp",
  "url": "https://api.salesforce.com/platform/mcp/v1-beta.2/sobject-all",
  "oauth_config": {
    "flow": "client_credentials",
    "client_id": "...",
    "client_secret": "...",
    "token_endpoint": "https://login.salesforce.com/services/oauth2/token",
    "service_account": "salesforce-system"
  }
}
```

### Phase 3: Provider-Specific Integrations

Pre-configured OAuth providers with sensible defaults.

#### 3.1 Provider Registry

```python
OAUTH_PROVIDERS = {
    "salesforce": {
        "authorization_endpoint": "https://login.salesforce.com/services/oauth2/authorize",
        "token_endpoint": "https://login.salesforce.com/services/oauth2/token",
        "default_scopes": ["api", "refresh_token"],
        "supports_pkce": True,
        "token_endpoint_auth_method": "client_secret_post"
    },
    "github": {
        "authorization_endpoint": "https://github.com/login/oauth/authorize",
        "token_endpoint": "https://github.com/login/oauth/access_token",
        "default_scopes": ["repo", "read:user"],
        "supports_pkce": False
    },
    # ... more providers
}
```

#### 3.2 Simplified Registration

```json
POST /gateways
{
  "name": "salesforce-mcp",
  "url": "https://api.salesforce.com/platform/mcp/v1-beta.2/sobject-all",
  "oauth_config": {
    "provider": "salesforce",
    "client_id": "...",
    "client_secret": "..."
  }
}
```

### Phase 4: Advanced Features

#### 4.1 Token Exchange (RFC 8693)

For federated scenarios where gateway needs to exchange tokens between providers.

#### 4.2 Device Authorization Grant (RFC 8628)

For headless/CLI scenarios where browser redirect isn't possible.

```json
{
  "oauth_config": {
    "flow": "device_code",
    "client_id": "...",
    "device_authorization_endpoint": "https://login.salesforce.com/services/oauth2/device/authorize"
  }
}
```

#### 4.3 Automatic Discovery

If the MCP server supports OAuth metadata discovery:

```json
POST /gateways
{
  "name": "salesforce-mcp",
  "url": "https://api.salesforce.com/platform/mcp/v1-beta.2/sobject-all",
  "oauth_config": {
    "discovery": true,
    "client_id": "...",
    "client_secret": "..."
  }
}
```

Gateway automatically fetches `/.well-known/oauth-authorization-server` to configure endpoints.

## Implementation Plan

### Milestone 1: Core Downstream OAuth (MVP)
- [ ] Extend `oauth_config` schema for downstream server credentials
- [ ] Add `DownstreamOAuthService` for gateway-as-client flows
- [ ] Implement client credentials flow for downstream gateways
- [ ] Add `/gateways/{id}/oauth/*` admin endpoints
- [ ] Automatic token injection in gateway requests
- [ ] Automatic token refresh on expiration

### Milestone 2: Authorization Code for Downstream
- [ ] Add authorization URL generation for downstream servers
- [ ] Implement callback handler for downstream OAuth
- [ ] Add PKCE support for downstream flows
- [ ] State management for downstream authorization

### Milestone 3: Service Accounts
- [ ] Add `ServiceAccountToken` model
- [ ] Implement service account token storage
- [ ] Add service account management endpoints
- [ ] Background token refresh for service accounts

### Milestone 4: Provider Integrations
- [ ] Create provider registry with defaults
- [ ] Add Salesforce provider configuration
- [ ] Add GitHub provider configuration
- [ ] Add generic OAuth 2.0 provider support

### Milestone 5: Advanced Features
- [ ] Device authorization grant (RFC 8628)
- [ ] Token exchange (RFC 8693)
- [ ] Automatic OAuth discovery
- [ ] Token revocation (RFC 7009)

## Files to Modify

### New Files
- `mcpgateway/services/downstream_oauth_service.py` - OAuth client for downstream servers
- `mcpgateway/services/oauth_provider_registry.py` - Pre-configured providers
- `mcpgateway/routers/gateway_oauth_router.py` - Admin endpoints for gateway OAuth

### Modified Files
- `mcpgateway/db.py` - Add `ServiceAccountToken` model
- `mcpgateway/schemas.py` - Extend `OAuthConfigSchema` for downstream config
- `mcpgateway/services/gateway_service.py` - Integrate downstream OAuth
- `mcpgateway/routers/gateway_router.py` - Add OAuth management routes

## Success Criteria

After implementation, registering an OAuth-protected MCP server should be a single API call:

```json
POST /gateways
{
  "name": "salesforce-mcp",
  "url": "https://api.salesforce.com/platform/mcp/v1-beta.2/sobject-all",
  "transport": "sse",
  "oauth_config": {
    "provider": "salesforce",
    "client_id": "3MVG9KsVczVNcM8x...",
    "client_secret": "4720596669FAA788..."
  }
}
```

The gateway should:
1. Automatically acquire tokens using client credentials (or initiate auth code flow)
2. Store tokens securely with encryption
3. Automatically refresh tokens before expiration
4. Inject `Authorization: Bearer <token>` header on all requests to the downstream server
5. Handle token errors gracefully with retry/refresh logic

## Related RFCs

- [RFC 6749](https://tools.ietf.org/html/rfc6749) - OAuth 2.0 Authorization Framework
- [RFC 7009](https://tools.ietf.org/html/rfc7009) - OAuth 2.0 Token Revocation
- [RFC 7591](https://tools.ietf.org/html/rfc7591) - OAuth 2.0 Dynamic Client Registration
- [RFC 7636](https://tools.ietf.org/html/rfc7636) - PKCE for OAuth Public Clients
- [RFC 8414](https://tools.ietf.org/html/rfc8414) - OAuth 2.0 Authorization Server Metadata
- [RFC 8628](https://tools.ietf.org/html/rfc8628) - OAuth 2.0 Device Authorization Grant
- [RFC 8693](https://tools.ietf.org/html/rfc8693) - OAuth 2.0 Token Exchange
- [RFC 8707](https://tools.ietf.org/html/rfc8707) - Resource Indicators for OAuth 2.0

## Labels

`enhancement`, `oauth`, `gateway`, `authentication`, `federation`
