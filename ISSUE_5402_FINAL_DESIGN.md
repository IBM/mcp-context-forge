# Issue #5402: Final Design - Stateless Direct Vault Integration

## Overview

**Approach**: Context Forge provides `required_domain` in gateway API response and uses it to directly lookup credentials in vault by domain. Agent only sends user identity (`vault_entity_id`) and authentication (`vault_token`). No agent configuration file needed, no database storage, completely stateless.

**Key Simplification**: Vault credentials are indexed by domain, eliminating the need for agents to maintain domain → credential_name mappings.

---

## Architecture

### Gateway Model Changes

**Add computed property `required_domain`:**

```python
# mcpgateway/db.py
from sqlalchemy.ext.hybrid import hybrid_property
from urllib.parse import urlparse

class Gateway(Base):
    __tablename__ = "gateways"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(767), nullable=False)
    # ... other existing fields ...
    
    @hybrid_property
    def required_domain(self) -> str:
        """Extract domain from URL for credential lookup.
        
        This domain is used by agents to match vault credentials.
        
        Examples:
            https://api.github.com/mcp/ → github.com
            https://github.ibm.com/mcp/ → github.ibm.com
            https://gitlab.company.com/ → gitlab.company.com
        """
        return self._extract_domain(self.url)
    
    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL, removing common prefixes."""
        hostname = urlparse(url).hostname or ""
        
        # Remove common prefixes
        for prefix in ['api.', 'www.']:
            if hostname.startswith(prefix):
                hostname = hostname[len(prefix):]
        
        return hostname
```

**Pydantic Schema:**

```python
# mcpgateway/schemas.py
class Gateway(BaseModel):
    """Gateway schema with required_domain computed field."""
    id: str
    name: str
    url: str
    description: Optional[str] = None
    transport: str
    required_domain: str  # Computed from URL
    # ... other fields ...
    
    class Config:
        from_attributes = True  # Allows reading from ORM model
```

---

## API Response Example

### Gateway List

```bash
GET /gateways

Response:
[
  {
    "id": "gateway-a",
    "name": "GitHub IBM MCP",
    "url": "https://github.ibm.com/mcp/",
    "required_domain": "github.ibm.com",  ← Agent uses this
    "transport": "SSE"
  },
  {
    "id": "gateway-b",
    "name": "GitLab Company MCP",
    "url": "https://gitlab.company.com/api/",
    "required_domain": "gitlab.company.com",
    "transport": "SSE"
  },
  {
    "id": "gateway-c",
    "name": "GitHub Public MCP",
    "url": "https://api.github.com/mcp/",
    "required_domain": "github.com",  ← Stripped "api." prefix
    "transport": "SSE"
  }
]
```

### Single Gateway

```bash
GET /gateways/gateway-a

Response:
{
  "id": "gateway-a",
  "name": "GitHub IBM MCP",
  "url": "https://github.ibm.com/mcp/",
  "required_domain": "github.ibm.com",
  "transport": "SSE",
  "description": "Access GitHub IBM repositories"
}
```

---

## Agent Implementation

### Agent Tool Invocation (Simplified - No Config File Needed)

```python
# agent/cf_client.py
async def invoke_tool(
    gateway_id: str,
    tool_name: str,
    arguments: dict,
    vault_entity_id: str,
    vault_token: str
):
    """Invoke tool via Context Forge gateway.
    
    Args:
        gateway_id: Gateway ID to use
        tool_name: Tool to invoke
        arguments: Tool arguments
        vault_entity_id: User's vault entity (email)
        vault_token: User's vault authentication token
    """
    # Build request - Context Forge will use gateway.required_domain
    # to lookup credentials in vault automatically
    request = {
        "gateway_id": gateway_id,
        "tool_name": tool_name,
        "arguments": arguments
    }
    
    # Send vault credentials via headers (more secure)
    headers = {
        "X-Vault-Token": vault_token,
        "X-Vault-Entity-Id": vault_entity_id
    }
    
    # Send to Context Forge
    return await http_post("/tools/invoke", request, headers=headers)
```

### Example Usage

```python
# Agent usage example
from agent import cf_client

# Invoke GitHub tool - no config file needed!
result = await cf_client.invoke_tool(
    gateway_id="gateway-a",
    tool_name="github-list-repos",
    arguments={"org": "myorg"},
    vault_entity_id="user@example.com",
    vault_token="vault_token_abc"
)

# Behind the scenes:
# 1. Agent sends vault credentials via headers (X-Vault-Token, X-Vault-Entity-Id)
# 2. Context Forge gets gateway → required_domain = "github.ibm.com"
# 3. Context Forge queries vault: resolve_credential_by_domain(
#        owner="user@example.com",
#        domain="github.ibm.com"
#    )
# 4. Vault returns credential for that user+domain
# 5. Context Forge injects auth header and forwards to MCP server
```

---

## Context Forge vault_direct Plugin

### Vault Client Implementation

**File**: `plugins/vault_direct/vault_client.py`

```python
# plugins/vault_direct/vault_client.py
import httpx
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VaultCredential:
    """Vault credential with metadata."""
    secret_value: str
    auth_type: str  # PAT, OAUTH2, JWT, BASIC, CUSTOM
    header_name: Optional[str] = None


class VaultProxyClient:
    """Client for vault-proxy API - domain-based credential resolution."""
    
    def __init__(self, vault_url: str, timeout: float = 5.0):
        """Initialize vault-proxy client.
        
        Args:
            vault_url: Vault-proxy base URL (e.g., http://localhost:8080)
            timeout: Request timeout in seconds
        """
        self.vault_url = vault_url.rstrip('/')
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)
    
    async def resolve_credential_by_domain(
        self,
        owner: str,
        domain: str,
        vault_token: str
    ) -> VaultCredential:
        """Resolve credential from vault by domain.
        
        Args:
            owner: User's vault entity ID (email)
            domain: Domain to lookup (e.g., "github.com")
            vault_token: User's vault authentication token
            
        Returns:
            VaultCredential with secret value and metadata
            
        Raises:
            VaultNotFoundError: Credential not found for domain
            VaultConnectionError: Cannot connect to vault-proxy
            VaultAuthError: Invalid vault token
        """
        url = f"{self.vault_url}/api/v1/credentials/by-domain"
        
        headers = {
            "X-Vault-Token": vault_token,
            "Content-Type": "application/json"
        }
        
        payload = {
            "owner": owner,
            "domain": domain
        }
        
        try:
            response = await self._client.post(url, json=payload, headers=headers)
            
            if response.status_code == 404:
                raise VaultNotFoundError(
                    f"No credential found for domain '{domain}' and user {owner}"
                )
            elif response.status_code == 401:
                raise VaultAuthError("Invalid vault token")
            elif response.status_code != 200:
                raise VaultConnectionError(
                    f"Vault-proxy returned {response.status_code}: {response.text}"
                )
            
            data = response.json()
            
            return VaultCredential(
                secret_value=data["secretValue"],
                auth_type=data.get("authType", "PAT"),
                header_name=data.get("headerName")
            )
            
        except httpx.RequestError as e:
            raise VaultConnectionError(
                f"Cannot connect to vault-proxy at {self.vault_url}: {e}"
            )
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()


class VaultNotFoundError(Exception):
    """Credential not found in vault."""
    pass


class VaultConnectionError(Exception):
    """Cannot connect to vault-proxy."""
    pass


class VaultAuthError(Exception):
    """Invalid vault authentication."""
    pass
```

**Key Features**:
- Domain-based credential lookup via `/api/v1/credentials/by-domain` endpoint
- Async HTTP client with configurable timeout
- Structured error handling (not found, connection, auth errors)
- Returns credential with metadata (secret value, auth type, header name)
- Proper resource cleanup with `close()` method

---

### Plugin Implementation

```python
# plugins/vault_direct/vault_direct_plugin.py
from typing import Dict, Any
import logging
from cpex.framework import Plugin, PluginContext, ToolPreInvokePayload, ToolPreInvokeResult
from plugins.vault.vault_client import VaultProxyClient

logger = logging.getLogger(__name__)


class VaultDirect(Plugin):
    """Vault direct plugin - stateless domain-based credential resolution.
    
    Uses gateway.required_domain to lookup credentials in vault by domain.
    No agent configuration needed, completely stateless.
    Includes security measures: token validation, rate limiting, audit logging.
    """
    
    def __init__(self, config):
        super().__init__(config)
        self._vault_client = VaultProxyClient(
            vault_url=config.vault_proxy_url,
            timeout=config.vault_proxy_timeout
        )
        self._rate_limiter = RateLimiter(
            max_requests=10,
            window_seconds=60
        )
    
    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext
    ) -> ToolPreInvokeResult:
        """Resolve credential by domain and inject auth header."""
        
        gateway = context.gateway
        request = context.request
        
        # 1. Extract vault credentials from headers (not request body)
        vault_token = request.headers.get("X-Vault-Token")
        vault_entity_id = request.headers.get("X-Vault-Entity-Id")
        
        if not vault_token or not vault_entity_id:
            raise ValueError(
                "Vault authentication required. "
                "Ensure X-Vault-Token and X-Vault-Entity-Id headers are present."
            )
        
        # 2. Validate token format (fail fast)
        self._validate_vault_token(vault_token)
        
        # 3. Get domain from gateway
        domain = gateway.required_domain
        
        # 4. Rate limiting (prevent brute force)
        rate_limit_key = f"{vault_entity_id}:{domain}"
        if not self._rate_limiter.allow(rate_limit_key):
            logger.warning(
                "Rate limit exceeded for vault credential resolution",
                extra={"user": vault_entity_id, "domain": domain}
            )
            raise ValueError("Too many requests. Please try again later.")
        
        # 5. Audit log: attempt
        logger.info(
            "Vault credential resolution attempt",
            extra={
                "user": vault_entity_id,
                "domain": domain,
                "gateway_id": gateway.id,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # 6. Resolve from vault using domain directly
        try:
            credential = await self._vault_client.resolve_credential_by_domain(
                owner=vault_entity_id,
                domain=domain,
                vault_token=vault_token
            )
            
            # Audit log: success
            logger.info(
                "Vault credential resolved successfully",
                extra={
                    "user": vault_entity_id,
                    "domain": domain,
                    "auth_type": credential.auth_type
                }
            )
            
        except VaultNotFoundError:
            # Audit log: failure
            logger.warning(
                "Vault credential not found",
                extra={
                    "user": vault_entity_id,
                    "domain": domain,
                    "gateway_id": gateway.id
                }
            )
            # Generic error message (prevent enumeration)
            raise ValueError(
                "Unable to authenticate request. "
                "Ensure valid credentials are configured in vault."
            )
        
        # 7. Inject auth header based on credential metadata
        headers = self._build_headers(payload, credential)
        
        # 8. Return modified payload
        modified_payload = payload.model_copy(update={"headers": headers})
        return ToolPreInvokeResult(modified_payload=modified_payload)
    
    def _validate_vault_token(self, token: str) -> None:
        """Validate vault token format before calling vault-proxy."""
        if not token or len(token) < 20:
            raise ValueError("Invalid vault token format")
        
        # Check for common vault token prefixes
        if not token.startswith(("hvs.", "s.")):
            raise ValueError("Invalid vault token prefix")
    
    def _build_headers(self, payload, credential):
        """Build headers with injected authentication."""
        headers = dict(payload.headers.root) if payload.headers else {}
        
        # Inject based on auth type
        if credential.auth_type == "PAT":
            if credential.header_name:
                headers[credential.header_name.lower()] = credential.secret_value
            else:
                headers["authorization"] = f"Bearer {credential.secret_value}"
        elif credential.auth_type in ["OAUTH2", "JWT"]:
            headers["authorization"] = f"Bearer {credential.secret_value}"
        elif credential.auth_type == "BASIC":
            headers["authorization"] = f"Basic {credential.secret_value}"
        else:
            # Custom or unknown - use header name or default to Bearer
            if credential.header_name:
                headers[credential.header_name.lower()] = credential.secret_value
            else:
                headers["authorization"] = f"Bearer {credential.secret_value}"
        
        return HttpHeaderPayload(root=headers)
```

---

## Plugin Routing Logic

### Automatic Selection Based on Request Headers

```python
# mcpgateway/middleware/plugin_router.py
def select_vault_plugin(request) -> str:
    """Select which vault plugin to use based on request headers.
    
    Returns:
        Plugin name: "vault_direct" or "vault" (legacy)
    """
    # New format: has X-Vault-Token and X-Vault-Entity-Id headers
    if "X-Vault-Token" in request.headers and "X-Vault-Entity-Id" in request.headers:
        return "vault_direct"
    
    # Legacy format: has X-Vault-Tokens header
    if "X-Vault-Tokens" in request.headers:
        return "vault"
    
    # No vault plugin needed
    return None
```

---

## Complete Request Flow

### Example: User1 invokes GitHub tool

**Step 1: Agent sends request (no config file needed)**
```json
POST /tools/invoke
{
  "gateway_id": "gateway-a",
  "tool_name": "github-list-repos",
  "arguments": {"org": "myorg"},
  "vault_entity_id": "user1@example.com",
  "vault_token": "vault_token_abc"
  // No 'tokens' field - Context Forge uses gateway.required_domain
}
```

**Step 2: Context Forge processes**
```python
# Plugin router selects vault_direct (has vault_token + vault_entity_id)
plugin = "vault_direct"

# vault_direct plugin:
domain = gateway.required_domain  # "github.ibm.com"

# Resolve from vault using domain directly
credential = vault_client.resolve_credential_by_domain(
    owner="user1@example.com",
    domain="github.ibm.com",
    vault_token="vault_token_abc"
)
# Returns: {secretValue: "ghp_user1_token", authType: "PAT", headerName: "X-GitHub-Token"}

# Inject header
headers["X-GitHub-Token"] = "ghp_user1_token"

# Forward to MCP server with injected auth
```

**Step 3: MCP server receives authenticated request**
```
X-GitHub-Token: ghp_user1_token
```

---

## Different Users, Same Gateway

### Three users accessing the same gateway

**All three send identical request format:**

```json
// User1
{
  "gateway_id": "gateway-a",
  "vault_entity_id": "user1@example.com",
  "vault_token": "user1_vault_token"
}

// User2
{
  "gateway_id": "gateway-a",
  "vault_entity_id": "user2@example.com",
  "vault_token": "user2_vault_token"
}

// User3
{
  "gateway_id": "gateway-a",
  "vault_entity_id": "user3@example.com",
  "vault_token": "user3_vault_token"
}
```

**Context Forge resolves using domain:**
- User1: `resolve_credential_by_domain(owner="user1@example.com", domain="github.ibm.com")` → User1's token
- User2: `resolve_credential_by_domain(owner="user2@example.com", domain="github.ibm.com")` → User2's token
- User3: `resolve_credential_by_domain(owner="user3@example.com", domain="github.ibm.com")` → User3's token

**No agent configuration needed! Vault manages the domain → credential mapping per user.**

---

## Security Considerations

### 1. Vault Token Transmission

**Concern**: Vault tokens in request body may be logged in application logs or audit trails.

**Mitigation**:
```python
# Use HTTP header instead of request body
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
- Move `vault_token` and `vault_entity_id` from request body to HTTP headers
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
```python
# Gateway URL changes require admin privileges
@require_permission("gateways.update")
async def update_gateway(gateway_id: str, updates: dict):
    """Only admins can modify gateway URLs."""
    if "url" in updates:
        # Log URL changes for audit
        logger.warning(
            "Gateway URL changed",
            extra={
                "gateway_id": gateway_id,
                "old_url": gateway.url,
                "new_url": updates["url"],
                "user": current_user.email
            }
        )
    # ... update gateway ...
```

**Implementation**:
- Require `gateways.update` permission for URL changes
- Log all gateway URL modifications
- Consider making URL immutable after creation (require delete/recreate)
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

@rate_limiter.limit
async def resolve_credential_by_domain(owner, domain, vault_token):
    """Rate-limited vault credential resolution."""
    # ... vault lookup ...
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
    extra={
        "user": vault_entity_id,
        "domain": domain,
        "gateway_id": gateway.id
    }
)
```

**Implementation**:
- Use generic error messages for client responses
- Log detailed errors internally for debugging
- Same error message for "not found" vs "vault unavailable"
- Prevent timing attacks (constant-time error responses)

### 6. Audit Trail

**Concern**: Cannot detect unauthorized access attempts without logging.

**Mitigation**:
```python
async def resolve_credential_by_domain(owner, domain, vault_token):
    """Resolve credential with full audit logging."""
    
    # Log attempt
    logger.info(
        "Vault credential resolution attempt",
        extra={
            "user": owner,
            "domain": domain,
            "gateway_id": gateway.id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    
    try:
        credential = await vault_client.resolve_credential_by_domain(
            owner=owner,
            domain=domain,
            vault_token=vault_token
        )
        
        # Log success
        logger.info(
            "Vault credential resolved successfully",
            extra={
                "user": owner,
                "domain": domain,
                "auth_type": credential.auth_type
            }
        )
        
        return credential
        
    except VaultNotFoundError:
        # Log failure
        logger.warning(
            "Vault credential not found",
            extra={
                "user": owner,
                "domain": domain,
                "gateway_id": gateway.id
            }
        )
        raise
```

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

### Credential not found in vault

```python
# User doesn't have credential for this domain in vault
{
  "vault_entity_id": "user@example.com",
  "vault_token": "vault_token_abc"
}

# Error response
{
  "error": "No credential found in vault for domain 'github.ibm.com' and user user@example.com",
  "gateway": "GitHub IBM MCP",
  "required_domain": "github.ibm.com",
  "help": "Create a credential in vault-proxy for domain 'github.ibm.com'"
}
```

### Vault unavailable

```python
{
  "error": "Cannot connect to vault-proxy",
  "vault_url": "http://vault.internal:8080",
  "help": "Check vault-proxy is running and accessible"
}
```

---

## Testing

### Unit Tests

```python
# tests/unit/test_vault_direct_plugin.py
def test_domain_extraction_from_gateway():
    """Test domain extraction from gateway URL."""
    gateway = Gateway(url="https://github.ibm.com/mcp/")
    
    assert gateway.required_domain == "github.ibm.com"


def test_domain_extraction_strips_api_prefix():
    """Test that api. prefix is stripped."""
    gateway = Gateway(url="https://api.github.com/mcp/")
    
    assert gateway.required_domain == "github.com"


def test_vault_lookup_by_domain():
    """Test vault credential lookup by domain."""
    plugin = VaultDirect()
    gateway = Gateway(url="https://github.ibm.com/mcp/")
    request = Request(
        vault_entity_id="user@example.com",
        vault_token="vault_token_abc"
    )
    
    # Mock vault client
    with patch.object(plugin._vault_client, 'resolve_credential_by_domain') as mock_resolve:
        mock_resolve.return_value = Credential(
            secret_value="ghp_test_token",
            auth_type="PAT",
            header_name="X-GitHub-Token"
        )
        
        result = await plugin.tool_pre_invoke(payload, context)
        
        # Verify vault was called with domain
        mock_resolve.assert_called_once_with(
            owner="user@example.com",
            domain="github.ibm.com",
            vault_token="vault_token_abc"
        )
```

### Integration Tests

```python
# tests/integration/test_vault_direct_flow.py
async def test_end_to_end_vault_direct():
    """Test complete flow with vault-proxy mock."""
    # Mock vault-proxy with domain-based credential
    mock_vault.add_credential_by_domain(
        owner="user@example.com",
        domain="github.com",
        secret="ghp_test_token",
        auth_type="PAT",
        header_name="X-GitHub-Token"
    )
    
    # Create gateway
    gateway = await create_gateway({
        "name": "GitHub Test",
        "url": "https://github.com/mcp/"
    })
    
    # Invoke tool with vault_direct (no tokens field)
    response = await client.post("/tools/invoke", json={
        "gateway_id": gateway.id,
        "tool_name": "list-repos",
        "vault_entity_id": "user@example.com",
        "vault_token": "vault_token"
    })
    
    assert response.status_code == 200
    # Verify auth header was injected
    assert mock_mcp_server.last_request_headers["X-GitHub-Token"] == "ghp_test_token"
```

---

## Benefits of This Design

✅ **No database schema changes** - Gateway model adds computed property only
✅ **No storage overhead** - Completely stateless
✅ **Zero agent configuration** - No config files needed
✅ **Simpler agent code** - Just send user identity and vault token
✅ **Better security** - Credential names not exposed in requests
✅ **Standardized approach** - Vault manages domain → credential mapping
✅ **Clear API contract** - Gateway response includes `required_domain`
✅ **Backward compatible** - Legacy plugin untouched
✅ **Easy testing** - Stateless logic, no database mocking needed
✅ **Easier onboarding** - Users just need vault credentials, no agent setup

---

## Migration Path

### For Existing Deployments

1. **Deploy Context Forge changes** (add `required_domain` property and domain-based vault lookup)
2. **Verify gateway API** includes `required_domain` in responses
3. **Update vault-proxy** to support `resolve_credential_by_domain` API
4. **Update agent** to use new format (send only `vault_entity_id` and `vault_token`)
5. **No database migration needed** - no schema changes

### For Users

1. **Create vault credentials** indexed by domain (e.g., domain: "github.com")
2. **Update agent** to remove config file (if using old approach)
3. **Start using** - works immediately with zero configuration

---

## Summary

**Key Design Points:**

- **Context Forge**: Adds `required_domain` computed property to Gateway
- **Agent**: No configuration needed - just sends user identity and vault token
- **Request**: Agent sends `vault_entity_id` and `vault_token` (no `tokens` field)
- **Plugin**: Uses `gateway.required_domain` to lookup credentials in vault by domain
- **Vault**: Manages domain → credential mapping per user
- **Stateless**: No database storage, no agent config files

**Example Flow:**
```
Gateway URL: https://github.ibm.com/mcp/
  ↓ (Context Forge computes)
required_domain: "github.ibm.com"
  ↓ (Plugin uses for vault lookup)
Vault lookup: resolve_credential_by_domain(
    owner="user@example.com",
    domain="github.ibm.com"
)
  ↓ (Vault returns credential)
Inject auth header and forward to MCP server
```

**Vault Credential Storage:**
```
User: user@example.com
  Credentials:
    - domain: github.ibm.com → token: ghp_xxx
    - domain: gitlab.company.com → token: glpat_yyy
    - domain: jira.company.com → token: jira_zzz
```

This is the complete design for Issue #5402 - **Option B: Domain-based vault lookup with zero agent configuration!**
