# Issue #5402: Plugin Architecture - Separate Plugins Approach

## Overview

Instead of modifying the existing `vault` plugin with dual-mode logic and feature flags, we create a **separate new plugin** called `vault_direct` for direct vault integration using **domain-based credential lookup**.

**Key Design**: The plugin uses `gateway.required_domain` to lookup credentials in vault by domain, eliminating the need for agents to maintain credential name mappings.

## Why Separate Plugins?

### Benefits

✅ **Zero risk to existing deployments**
- Existing `vault` plugin remains completely untouched
- No chance of breaking tag-based credential resolution
- Existing gateways continue working without any changes

✅ **No feature flags needed**
- Routing is automatic based on request format (headers)
- No environment variables to coordinate across deployments
- No dual-mode complexity within a single plugin

✅ **Cleaner separation of concerns**
- Each plugin has single responsibility
- Easier to understand, test, and maintain
- Clear boundaries between legacy and new approaches

✅ **Simpler testing**
- Test each plugin independently
- No conditional logic based on feature flags
- Clear test scenarios for each plugin

✅ **Easier rollback**
- Disable `vault_direct` plugin → all requests use legacy
- Agent reverts to legacy request format → uses legacy plugin
- No deployment needed for rollback

✅ **Future deprecation path**
- Eventually remove `vault` plugin after full migration
- No refactoring needed - just delete the old plugin
- New plugin stays clean without legacy baggage

### Comparison with Dual-Mode Approach

| Aspect | Dual-Mode (Single Plugin) | Separate Plugins |
|--------|--------------------------|------------------|
| **Existing plugin modified?** | Yes (risky) | No (safe) |
| **Feature flags needed?** | Yes (coordination burden) | No (automatic routing) |
| **Code complexity** | High (if/else branches) | Low (dedicated plugins) |
| **Testing complexity** | High (combinations) | Low (isolated tests) |
| **Rollback** | Change flag (coordination) | Config change (per-gateway) |
| **Migration** | All-or-nothing per deployment | Per-gateway, gradual |
| **Deprecation** | Refactor to remove legacy code | Delete old plugin file |

---

## Architecture

### Plugin Files Structure

```
plugins/
├── vault/                          # EXISTING - UNCHANGED
│   ├── __init__.py
│   ├── vault_plugin.py            # Tag-based, X-Vault-Tokens header
│   └── README.md
│
├── vault_direct/                   # NEW
│   ├── __init__.py
│   ├── vault_direct_plugin.py     # Direct integration, domain-based lookup
│   ├── vault_client.py            # Shared vault-proxy client
│   └── README.md
│
└── config.yaml                     # Both plugins registered
```

**Note**: `vault_client.py` is shared utility, can be in either plugin directory or common location.

---

## Plugin Routing Logic

### Automatic Selection

The plugin framework automatically selects which vault plugin to invoke based on request format:

```python
def select_plugins_for_request(request, gateway: Gateway) -> List[str]:
    """Determine which plugins to invoke for this request."""
    plugins = []
    
    # Vault plugin selection - automatic routing based on request format
    if hasattr(request, 'vault_token') and hasattr(request, 'vault_entity_id'):
        # Request has vault_token + vault_entity_id → use vault_direct
        plugins.append("vault_direct")
    elif "X-Vault-Tokens" in request.headers:
        # Request has X-Vault-Tokens header → use vault (legacy)
        plugins.append("vault")
    
    # ... other plugin selections ...
    
    return plugins
```

**Key points:**
- If request has `vault_token` + `vault_entity_id` → use `vault_direct`
- If request has `X-Vault-Tokens` header → use `vault` (legacy)
- No gateway configuration needed - routing is based on request format
- Both plugins can coexist, selected per-request

### Request Flow

```
┌─────────────────────────────────────────────────────────┐
│ Tool Invocation Request                                  │
└────────────────────────┬────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Plugin Framework                                         │
│                                                          │
│ Check request format:                                    │
│   - Has vault_token + vault_entity_id?                   │
│   - Has X-Vault-Tokens header?                           │
└────────────────────────┬────────────────────────────────┘
                         ↓
         ┌───────────────┴───────────────┐
         │                                │
         ↓                                ↓
┌────────────────┐              ┌────────────────┐
│ vault_token +  │              │ X-Vault-Tokens │
│ vault_entity_id│              │ header         │
│ present        │              │ present        │
└───────┬────────┘              └───────┬────────┘
        ↓                               ↓
┌────────────────┐              ┌────────────────┐
│ vault_direct   │              │ vault (legacy) │
│ plugin         │              │ plugin          │
└───────┬────────┘              └───────┬────────┘
        ↓                               ↓
┌────────────────┐              ┌────────────────┐
│ Use gateway.   │              │ Parse header   │
│ required_domain│              │ Match tags     │
│ for vault      │              │                │
│ lookup         │              │                │
└───────┬────────┘              └───────┬────────┘
        ↓                               ↓
┌────────────────┐              ┌────────────────┐
│ Call vault:    │              │ Inject header  │
│ resolve_by_    │              │ based on tags  │
│ domain()       │              │                │
└───────┬────────┘              └───────┬────────┘
        ↓                               ↓
┌─────────────────────────────────────────────────────────┐
│ Inject auth header → Forward to MCP server              │
└─────────────────────────────────────────────────────────┘
```

---

## Plugin Implementations

### Legacy Plugin: `vault`

**File**: `plugins/vault/vault_plugin.py`

**Status**: **UNCHANGED** - existing implementation stays as-is

**Behavior**:
- Activated when gateway has NO `vault_credential_alias`
- Processes `X-Vault-Tokens` header (JSON dict of credentials)
- Matches token keys to gateway `system:` tags
- Uses `AUTH_HEADER:` tags to determine header name
- Injects auth header based on tag matching

**Configuration**:
```yaml
vault:
  enabled: true
  config:
    system_tag_prefix: "system"
    vault_header_name: "X-Vault-Tokens"
    vault_handling: "raw"
    system_handling: "tag"
    auth_header_tag_prefix: "AUTH_HEADER"
```

**Example Gateway**:
```json
{
  "name": "GitHub MCP (Legacy)",
  "url": "https://api.github.com/mcp/",
  "tags": [
    {"label": "system:github.com"},
    {"label": "AUTH_HEADER:X-GitHub-Token"}
  ]
}
```

---

### New Plugin: `vault_direct`

**File**: `plugins/vault_direct/vault_direct_plugin.py`

**Status**: **NEW** - fresh implementation

**Behavior**:
- Activated when request has `vault_token` and `vault_entity_id` fields
- Uses `gateway.required_domain` (computed from gateway URL)
- Extracts `vault_token` and `vault_entity_id` from request
- Calls vault-proxy: `resolve_credential_by_domain(owner, domain, vault_token)`
- Receives credential + metadata: `{secretValue, authType, headerName}`
- Injects auth header based on vault metadata (not tags)

**Configuration**:
```yaml
vault_direct:
  enabled: true
  config:
    vault_proxy_url: "${VAULT_PROXY_URL}"
    vault_proxy_timeout: 5.0
    verify_ssl: true
```

**Example Gateway**:
```json
{
  "name": "GitHub MCP (Direct)",
  "url": "https://api.github.com/mcp/",
  "required_domain": "github.com"  // Computed from URL
}
```

**Example Request**:
```json
{
  "gateway_id": "gateway-123",
  "tool_name": "github-list-repos",
  "arguments": {"org": "myorg"},
  "vault_entity_id": "user@example.com",
  "vault_token": "vault_token_abc"
}
```

**Key Implementation Points**:

```python
class VaultDirect(Plugin):
    def __init__(self, config: PluginConfig):
        # Initialize vault-proxy client
        self._vault_client = VaultProxyClient(
            vault_url=config.vault_proxy_url,
            timeout=config.vault_proxy_timeout
        )
        # Initialize rate limiter
        self._rate_limiter = RateLimiter(
            max_requests=10,
            window_seconds=60
        )
    
    async def tool_pre_invoke(self, payload, context):
        # 1. Extract vault credentials from headers (secure)
        vault_token = context.request.headers.get("X-Vault-Token")
        vault_entity_id = context.request.headers.get("X-Vault-Entity-Id")
        
        if not vault_token or not vault_entity_id:
            raise ValueError(
                "Vault authentication required. "
                "Ensure X-Vault-Token and X-Vault-Entity-Id headers are present."
            )
        
        # 2. Validate token format (fail fast)
        self._validate_vault_token(vault_token)
        
        # 3. Get domain from gateway (computed property)
        domain = context.gateway.required_domain
        
        # 4. Rate limiting (prevent brute force)
        rate_limit_key = f"{vault_entity_id}:{domain}"
        if not self._rate_limiter.allow(rate_limit_key):
            raise ValueError("Too many requests. Please try again later.")
        
        # 5. Audit log: attempt
        logger.info(
            "Vault credential resolution attempt",
            extra={"user": vault_entity_id, "domain": domain}
        )
        
        # 6. Resolve credential from vault-proxy using domain
        try:
            credential = await self._vault_client.resolve_credential_by_domain(
                owner=vault_entity_id,
                domain=domain,
                vault_token=vault_token
            )
            
            # Audit log: success
            logger.info(
                "Vault credential resolved successfully",
                extra={"user": vault_entity_id, "domain": domain}
            )
            
        except VaultNotFoundError:
            # Audit log: failure
            logger.warning(
                "Vault credential not found",
                extra={"user": vault_entity_id, "domain": domain}
            )
            # Generic error message (prevent enumeration)
            raise ValueError(
                "Unable to authenticate request. "
                "Ensure valid credentials are configured in vault."
            )
        
        # 7. Inject auth header based on metadata
        self._inject_auth_header(payload.headers, credential)
        
        return modified_payload
    
    def _validate_vault_token(self, token: str) -> None:
        """Validate vault token format before calling vault-proxy."""
        if not token or len(token) < 20:
            raise ValueError("Invalid vault token format")
        if not token.startswith(("hvs.", "s.")):
            raise ValueError("Invalid vault token prefix")
```

---

## Migration Path

### Request-Based Migration

Because routing is based on request format, migration is **per-agent** with zero coordination:

**Step 1: Update agent to send new format**
```python
# Old format (legacy)
request = {
    "gateway_id": "gateway-123",
    "tool_name": "github-list-repos",
    "arguments": {"org": "myorg"}
}
headers = {"X-Vault-Tokens": '{"github.com:USER:PAT:x": "ghp_abc"}'}

# New format (vault_direct)
request = {
    "gateway_id": "gateway-123",
    "tool_name": "github-list-repos",
    "arguments": {"org": "myorg"},
    "vault_entity_id": "user@example.com",
    "vault_token": "vault_token_abc"
}
# No X-Vault-Tokens header needed
```

**Result**: That agent immediately uses `vault_direct` plugin

**Step 2: Test**
- Invoke tool via updated agent
- Verify credential resolved correctly
- Check logs for `vault_direct` plugin activity

**Step 3: Update vault credentials**
- Ensure credentials are indexed by domain in vault
- Example: domain="github.com" → credential for user

**Step 4: Repeat for other agents**
- One at a time, or in batches
- No deployment needed
- Each agent independent

### Rollback (Per Agent)

**Revert agent to old format**:
- Send `X-Vault-Tokens` header instead of `vault_token`/`vault_entity_id`
- Agent automatically uses legacy `vault` plugin

---

## Security Considerations

### 1. Vault Token Transmission

**Concern**: Vault tokens in request body may be logged in application logs or audit trails.

**Mitigation**:
```python
# Use HTTP headers instead of request body
# Agent sends:
headers = {
    "X-Vault-Token": "vault_token_abc",
    "X-Vault-Entity-Id": "user@example.com"
}

# Plugin extracts from headers (not logged by default)
vault_token = request.headers.get("X-Vault-Token")
vault_entity_id = request.headers.get("X-Vault-Entity-Id")
```

**Implementation**:
- Vault credentials transmitted via HTTP headers
- Configure logging middleware to mask `X-Vault-Token` header
- Never log vault tokens in error messages or audit trails

### 2. Token Validation

**Concern**: Malformed or expired tokens cause unnecessary vault-proxy calls.

**Mitigation**:
```python
def validate_vault_token(token: str) -> None:
    """Validate vault token format before calling vault-proxy."""
    if not token or len(token) < 20:
        raise ValueError("Invalid vault token format")
    
    # Check for common token prefixes (vault-specific)
    if not token.startswith(("hvs.", "s.")):
        raise ValueError("Invalid vault token prefix")
```

**Implementation**:
- Add basic format validation in plugin
- Fail fast before making vault-proxy call
- Log validation failures separately from vault errors

### 3. Domain Spoofing Prevention

**Concern**: If gateway URL can be modified, attacker could change domain to access wrong credentials.

**Mitigation**:
- Require `gateways.update` permission for URL changes (admin only)
- Log all gateway URL modifications
- Consider making URL immutable after creation
- Validate URL format and domain extraction

### 4. Rate Limiting

**Concern**: Brute force attacks on vault credentials.

**Mitigation**:
```python
from mcpgateway.middleware.rate_limiter import RateLimiter

# Rate limit vault credential resolutions
rate_limiter = RateLimiter(
    key_func=lambda req: f"vault:{req.vault_entity_id}:{gateway.required_domain}",
    max_requests=10,  # 10 requests
    window_seconds=60  # per minute
)
```

**Implementation**:
- Rate limit per user+domain combination
- Default: 10 requests per minute per user+domain
- Return 429 Too Many Requests on limit exceeded
- Log rate limit violations for security monitoring

### 5. Credential Enumeration Prevention

**Concern**: Error messages reveal whether credential exists for domain.

**Mitigation**:
```python
# BAD - reveals credential existence
raise ValueError(f"Credential not found for domain '{domain}'")

# GOOD - generic error message
raise ValueError(
    "Unable to authenticate request. "
    "Ensure valid credentials are configured in vault."
)

# Log detailed error internally (not exposed to client)
logger.warning(
    "Vault credential not found",
    extra={"user": vault_entity_id, "domain": domain}
)
```

**Implementation**:
- Use generic error messages for client responses
- Log detailed errors internally for debugging
- Same error message for "not found" vs "vault unavailable"

### 6. Audit Trail

**Concern**: Cannot detect unauthorized access attempts without logging.

**Implementation**:
- Log all vault credential resolution attempts
- Include: user, domain, gateway, timestamp, success/failure
- Store in audit database (separate from application logs)
- Enable security monitoring and alerting
- Retain audit logs per compliance requirements

### Security Checklist

✅ **Vault tokens transmitted via HTTP headers** (not request body)
✅ **Token format validation** before vault-proxy calls
✅ **Gateway URL changes require admin privileges** and are logged
✅ **Rate limiting** per user+domain (10 req/min default)
✅ **Generic error messages** to prevent credential enumeration
✅ **Full audit trail** of all vault credential access

---

## Error Handling

### Legacy Plugin (`vault`)

**Silent failures** (existing behavior):
- Mismatched tags → proceeds unauthenticated → MCP server returns 401
- Error message: Generic "Unauthorized"

### New Plugin (`vault_direct`)

**Explicit failures** (improved):

```python
# Missing credential for domain
raise ValueError(
    f"No credential found in vault for domain '{domain}' and user {vault_entity_id}. "
    f"Create a credential in vault-proxy for domain '{domain}'."
)

# Vault unavailable
raise ValueError(
    f"Cannot connect to vault-proxy at {vault_url}: {error}"
)

# Missing request fields
raise ValueError(
    "vault_token and vault_entity_id required for vault direct integration. "
    "Ensure agent sends these fields in request body."
)
```

**Result**: Clear, actionable error messages

---

## Observability

### Metrics to Track

```python
# Legacy plugin
vault.legacy.calls                    # Counter
vault.legacy.errors                   # Counter
vault.legacy.tag_matches              # Counter
vault.legacy.tag_mismatches           # Counter

# New plugin
vault.direct.calls                    # Counter
vault.direct.errors                   # Counter
vault.direct.vault_latency            # Histogram
vault.direct.credentials_resolved     # Counter
vault.direct.credentials_not_found    # Counter
```

### Logs

**Legacy plugin**:
```
[INFO] vault plugin: Processing request for gateway github-mcp
[DEBUG] vault plugin: Matched token key github.com:USER:PAT:x to tag system:github.com
[DEBUG] vault plugin: Injecting header X-GitHub-Token from AUTH_HEADER tag
```

**New plugin**:
```
[INFO] vault_direct plugin: Resolving credential for domain github.com, user user@example.com
[DEBUG] vault_direct plugin: Vault returned auth_type=PAT, header_name=X-GitHub-Token
[INFO] vault_direct plugin: Injected auth header X-GitHub-Token
```

**Routing**:
```
[DEBUG] plugin_router: Request has vault_token + vault_entity_id → using vault_direct
[DEBUG] plugin_router: Request has X-Vault-Tokens header → using vault (legacy)
```

---

## Configuration Examples

### Both Plugins Enabled

**File**: `plugins/config.yaml`

```yaml
# Legacy vault plugin (tag-based)
vault:
  enabled: true
  config:
    system_tag_prefix: "system"
    vault_header_name: "X-Vault-Tokens"
    vault_handling: "raw"
    system_handling: "tag"
    auth_header_tag_prefix: "AUTH_HEADER"

# New vault_direct plugin (direct integration)
vault_direct:
  enabled: true
  config:
    vault_proxy_url: "http://localhost:8080"
    vault_proxy_timeout: 5.0
    verify_ssl: true
```

### Environment Variables

**File**: `.env`

```bash
# Vault proxy configuration (for vault_direct plugin)
VAULT_PROXY_URL=http://localhost:8080
VAULT_PROXY_TIMEOUT=5.0

# No feature flags needed!
```

### Gateway Examples

**Legacy gateway** (uses `vault` plugin):
```json
{
  "id": "gw-001",
  "name": "GitHub MCP (Legacy)",
  "url": "https://api.github.com/mcp/",
  "tags": [
    {"label": "system:github.com"},
    {"label": "AUTH_HEADER:X-GitHub-Token"}
  ]
}
```

**Direct gateway** (uses `vault_direct` plugin when request has vault_token):
```json
{
  "id": "gw-002",
  "name": "GitHub MCP (Direct)",
  "url": "https://api.github.com/mcp/",
  "required_domain": "github.com"  // Computed from URL
}
```

**Both can coexist** in the same deployment. Plugin selection is based on request format, not gateway configuration.

---

## Testing Strategy

### Unit Tests

**Legacy plugin** (`tests/unit/plugins/vault/test_vault_plugin.py`):
- **UNCHANGED** - existing tests remain as-is
- Tests tag-based matching logic
- Tests X-Vault-Tokens header parsing

**New plugin** (`tests/unit/plugins/vault_direct/test_vault_direct_plugin.py`):
- Test vault-proxy client (wrap, unwrap, resolve)
- Test credential resolution (PAT, OAuth2, JWT, Custom)
- Test error handling (not found, timeout, connection)
- Test auth header injection based on metadata

**Routing** (`tests/unit/test_plugin_routing.py`):
- Test automatic plugin selection based on request format
- Request with `vault_token` + `vault_entity_id` → `vault_direct`
- Request with `X-Vault-Tokens` header → `vault`

### Integration Tests

**Legacy path** (`tests/integration/test_vault_legacy.py`):
- **UNCHANGED** - existing tests remain
- End-to-end with tag-based gateways

**Direct path** (`tests/integration/test_vault_direct.py`):
- End-to-end with requests containing `vault_token` + `vault_entity_id`
- Mock vault-proxy responses for domain-based lookup
- Verify correct plugin invoked
- Verify correct headers passed to MCP server

**Mixed deployment** (`tests/integration/test_mixed_vault.py`):
- Send legacy request (X-Vault-Tokens header) to gateway
- Send direct request (vault_token + vault_entity_id) to same gateway
- Verify each uses correct plugin based on request format
- Verify no interference between plugins

---

## Deployment

### Phase 1: Deploy New Plugin

```bash
# 1. Add vault_direct plugin code
git checkout -b feat_5402-vault-direct
# ... add plugin files ...
git commit -m "feat: add vault_direct plugin for direct vault integration"

# 2. Deploy to staging
make deploy-staging

# 3. Verify both plugins loaded
curl http://staging:4444/plugins | jq '.[] | select(.id | contains("vault"))'
# Should see: vault (enabled), vault_direct (enabled)
```

**Verification**:
```bash
# Existing gateways still work (use legacy plugin)
curl -X POST http://staging:4444/tools/invoke \
  -H "X-Vault-Tokens: {\"github.com:USER:PAT:x\": \"ghp_abc\"}" \
  -d '{"tool_name": "github-list-repos", ...}'

# Should succeed (legacy path)
```

### Phase 2: Test Direct Integration

```bash
# 1. Create test gateway (no special config needed)
curl -X POST http://staging:4444/gateways \
  -d '{
    "name": "GitHub Test Direct",
    "url": "https://api.github.com/mcp/"
  }'

# 2. Invoke tool with new request format
curl -X POST http://staging:4444/tools/invoke \
  -d '{
    "gateway_id": "gateway-123",
    "tool_name": "github-list-repos",
    "arguments": {"org": "myorg"},
    "vault_entity_id": "user@example.com",
    "vault_token": "vault_token_abc"
  }'

# Should succeed (direct path)
```

### Phase 3: Gradual Agent Migration

```bash
# Update agents one at a time
for agent in $(get_agent_list); do
  echo "Migrating agent $agent"
  
  # Update agent to send new request format
  update_agent_config $agent
  
  # Test
  test_agent $agent
  
  # Monitor for errors
  sleep 60
done
```

---

## Deprecation Path

### Timeline

| Phase | Timeline | Action |
|-------|----------|--------|
| **Phase 1** | Week 1-2 | Deploy new `vault_direct` plugin |
| **Phase 2** | Week 3-4 | Test on staging |
| **Phase 3** | Month 2-3 | Gradual production migration |
| **Phase 4** | Month 4-6 | Encourage full migration |
| **Phase 5** | Month 6+ | Mark legacy plugin as deprecated |
| **Phase 6** | Month 12+ | Remove legacy plugin |

### Deprecation Notice

**Documentation** (`plugins/vault/README.md`):
```markdown
# Vault Plugin (Legacy - Deprecated)

⚠️ **DEPRECATED**: This plugin uses tag-based credential matching and is deprecated
in favor of the `vault_direct` plugin which provides direct vault-proxy integration.

**Migration**: Add `vault_credential_alias` field to your gateways to use the new plugin.

**Support timeline**:
- Deprecated: 2026-07
- Removal: 2027-01 (6 months)
```

### Final Removal

After all gateways migrated:

```bash
# 1. Disable legacy plugin
# plugins/config.yaml
vault:
  enabled: false  # Disable

# 2. Monitor for errors (should be none)

# 3. Remove plugin files
git rm -r plugins/vault/
git commit -m "chore: remove deprecated vault plugin"
```

---

## Summary

The **separate plugins approach** provides:

✅ **Zero risk** - existing plugin untouched  
✅ **No feature flags** - automatic routing  
✅ **Simple rollback** - per-gateway config change  
✅ **Clean separation** - single responsibility per plugin  
✅ **Easy testing** - isolated test suites  
✅ **Gradual migration** - gateway-by-gateway  
✅ **Future-proof** - clean removal path  

This is the **recommended approach** for Issue #5402.
