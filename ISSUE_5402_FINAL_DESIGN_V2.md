# Issue #5402: Final Design - VirtualServer UUID Direct Vault Integration

## Overview

**Approach**: Context Forge uses the **virtual server UUID** (already present in every request) to lookup self-describing credential structs from vault. Credentials include complete metadata (secret value, auth type, header name, system identifier), eliminating all inference and supporting multi-system virtual servers.

**Key Innovation**: Vault credentials are stored as **self-describing structs** at path `{user_id}/{virtualServerUuid}`, containing everything needed to inject authentication without external configuration or tag matching.

---

## Architecture

### Core Insight

Virtual servers in Context Forge already have persistent UUIDs. The `mcpServerCredential` table in destiny-services already links `mcpServerUuid` → credentials. Instead of inventing new lookup keys (aliases, domains), use the UUID that already exists and naturally represents "this user's credentials for this virtual server."

### Credential Structure

**Single-System Virtual Server:**
```json
{
  "secretValue": "ghp_abc123def456",
  "authType": "PAT",
  "headerName": "X-GitHub-Token",
  "system": "github.com"
}
```

**Multi-System Virtual Server** (aggregates multiple backends):
```json
[
  {
    "secretValue": "ghp_abc123def456",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "jira_xyz789",
    "authType": "PAT",
    "headerName": "Authorization",
    "system": "jira.atlassian.com"
  },
  {
    "secretValue": "slack_token_abc",
    "authType": "OAUTH2",
    "headerName": "Authorization",
    "system": "slack.com"
  }
]
```

### Credential Struct Schema

```typescript
interface VaultCredential {
  secretValue: string;      // The actual secret (token, password, etc.)
  authType: AuthType;       // How to use the secret
  headerName: string;       // Which HTTP header to inject
  system: string;           // Domain/system identifier for routing
  metadata?: {              // Optional additional metadata
    expiresAt?: string;     // ISO 8601 timestamp
    scope?: string;         // OAuth2 scope
    tokenType?: string;     // Bearer, Basic, etc.
  };
}

enum AuthType {
  PAT = "PAT",              // Personal Access Token
  OAUTH2 = "OAUTH2",        // OAuth 2.0 Bearer token
  JWT = "JWT",              // JSON Web Token
  BASIC = "BASIC",          // HTTP Basic Auth (base64 encoded)
  APIKEY = "APIKEY",        // API Key
  CUSTOM = "CUSTOM"         // Custom auth scheme
}

type VaultCredentialResponse = VaultCredential | VaultCredential[];
```

---

## Request Flow

### End-to-End Example

**1. Agent sends request to CF:**
```http
POST /servers/{virtualServerUuid}/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "github-list-repos",
    "arguments": {
    "org": "myorg"
  }
}
```

**2. CF extracts context:**
```python
virtual_server_uuid = request.path_params["virtualServerUuid"]  # "vs-abc-123"
user_id = decode_jwt(request.headers["Authorization"])["sub"]   # "user@example.com"
vault_token = request.headers["X-Vault-Token"]                 # User's vault token
```

**3. CF calls vault-proxy:**
```http
POST /api/secret/v1/wrap/{user_id}/{virtualServerUuid}
Headers:
  X-Vault-Token: {cf_service_token}
Body:
{
  "userVaultToken": "{user_vault_token}"
}
```

**4. Vault-proxy returns self-describing struct:**
```json
{
  "secretValue": "ghp_abc123def456",
  "authType": "PAT",
  "headerName": "X-GitHub-Token",
  "system": "github.com"
}
```

**5. CF injects auth header based on struct metadata:**
```python
if credential.authType == "PAT":
    headers[credential.headerName] = credential.secretValue
elif credential.authType == "OAUTH2":
    headers[credential.headerName] = f"Bearer {credential.secretValue}"
elif credential.authType == "BASIC":
    headers[credential.headerName] = f"Basic {credential.secretValue}"
# ... etc
```

**6. CF forwards to backend MCP server:**
```http
POST https://api.github.com/mcp/tools/invoke
Headers:
  X-GitHub-Token: ghp_abc123def456
Body:
{
  "tool_name": "github-list-repos",
  "arguments": {
    "org": "myorg"
  }
}
```

---

## Multi-System Virtual Server Support

### Use Case: Aggregated Virtual Server

A virtual server that combines tools from multiple backends:
- GitHub for code repositories
- Jira for issue tracking
- Slack for notifications

**Virtual Server Configuration:**
```json
{
  "id": "vs-dev-tools-123",
  "name": "Developer Tools Suite",
  "backends": [
    {
      "system": "github.com",
      "gateway_id": "gw-github-001",
      "tools": ["list-repos", "create-issue", "get-pr"]
    },
    {
      "system": "jira.atlassian.com",
      "gateway_id": "gw-jira-001",
      "tools": ["list-issues", "create-ticket"]
    },
    {
      "system": "slack.com",
      "gateway_id": "gw-slack-001",
      "tools": ["send-message", "list-channels"]
    }
  ]
}
```

**Vault Credential (Array):**
```json
[
  {
    "secretValue": "ghp_github_token",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "jira_api_token",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.atlassian.com"
  },
  {
    "secretValue": "xoxb-slack-token",
    "authType": "OAUTH2",
    "headerName": "Authorization",
    "system": "slack.com"
  }
]
```

**Tool Invocation Flow:**
```python
async def invoke_tool(virtual_server_uuid, tool_name, arguments, user_id, vault_token):
    # 1. Fetch virtual server config
    vs_config = await db.get_virtual_server(virtual_server_uuid)
    
    # 2. Determine which backend this tool belongs to
    backend = vs_config.find_backend_for_tool(tool_name)  # Returns backend with system="github.com"
    
    # 3. Fetch credentials from vault
    credentials = await vault_client.resolve_credentials(
        user_id=user_id,
        virtual_server_uuid=virtual_server_uuid,
        vault_token=vault_token
    )
    # Returns array of credentials
    
    # 4. Match credential to backend by system field
    credential = next(
        (c for c in credentials if c["system"] == backend.system),
        None
    )
    
    if not credential:
        raise ValueError(
            f"No credential found for system '{backend.system}' in virtual server '{virtual_server_uuid}'"
        )
    
    # 5. Inject auth header based on credential metadata
    headers = inject_auth_header(credential)
    
    # 6. Forward to correct backend gateway
    return await forward_to_gateway(
        gateway_id=backend.gateway_id,
        tool_name=tool_name,
        arguments=arguments,
        headers=headers
    )
```

---

## Plugin Implementation

### vault_direct Plugin

**File**: `plugins/vault_direct/vault_direct_plugin.py`

```python
"""Vault direct integration plugin - VirtualServer UUID based.

This plugin resolves credentials from vault using the virtual server UUID
and injects authentication headers based on self-describing credential structs.

Supports:
- Single-system virtual servers (one credential)
- Multi-system virtual servers (array of credentials)
- All auth types: PAT, OAUTH2, JWT, BASIC, APIKEY, CUSTOM
- Rate limiting and audit logging
"""

from typing import Dict, List, Union, Optional
import logging
from datetime import datetime
from cpex.framework import (
    Plugin, 
    PluginContext, 
    ToolPreInvokePayload, 
    ToolPreInvokeResult,
    HttpHeaderPayload
)
from .vault_client import VaultProxyClient, VaultCredential, VaultNotFoundError
from mcpgateway.middleware.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class VaultDirect(Plugin):
    """Vault direct plugin - stateless UUID-based credential resolution."""
    
    def __init__(self, config):
        super().__init__(config)
        
        # Initialize vault-proxy client
        self._vault_client = VaultProxyClient(
            vault_url=config.vault_proxy_url,
            timeout=config.vault_proxy_timeout,
            verify_ssl=config.get("verify_ssl", True)
        )
        
        # Rate limiter: 20 requests per minute per user+virtualServer
        self._rate_limiter = RateLimiter(
            max_requests=20,
            window_seconds=60
        )
    
    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext
    ) -> ToolPreInvokeResult:
        """Resolve credentials by virtual server UUID and inject auth headers.
        
        Handles both single-system and multi-system virtual servers.
        """
        
        request = context.request
        virtual_server = context.virtual_server
        
        # 1. Extract authentication headers
        user_vault_token = request.headers.get("X-Vault-Token")
        user_id = self._extract_user_id(request)
        
        if not user_vault_token or not user_id:
            raise ValueError(
                "Vault authentication required. "
                "Ensure X-Vault-Token header and valid JWT are present."
            )
        
        # 2. Validate vault token format (fail fast)
        self._validate_vault_token(user_vault_token)
        
        # 3. Rate limiting (prevent brute force)
        rate_limit_key = f"{user_id}:{virtual_server.uuid}"
        if not self._rate_limiter.allow(rate_limit_key):
            logger.warning(
                "Rate limit exceeded for vault credential resolution",
                extra={
                    "user": user_id,
                    "virtual_server": virtual_server.uuid,
                    "virtual_server_name": virtual_server.name
                }
            )
            raise ValueError("Too many credential requests. Please try again later.")
        
        # 4. Audit log: attempt
        logger.info(
            "Vault credential resolution attempt",
            extra={
                "user": user_id,
                "virtual_server_uuid": virtual_server.uuid,
                "virtual_server_name": virtual_server.name,
                "tool_name": payload.tool_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # 5. Resolve credentials from vault by virtual server UUID
        try:
            credentials = await self._vault_client.resolve_credentials_by_uuid(
                user_id=user_id,
                virtual_server_uuid=virtual_server.uuid,
                user_vault_token=user_vault_token
            )
            
            # Audit log: success
            logger.info(
                "Vault credentials resolved successfully",
                extra={
                    "user": user_id,
                    "virtual_server_uuid": virtual_server.uuid,
                    "credential_count": len(credentials) if isinstance(credentials, list) else 1,
                    "systems": self._extract_systems(credentials)
                }
            )
            
        except VaultNotFoundError:
            # Audit log: failure
            logger.warning(
                "Vault credentials not found",
                extra={
                    "user": user_id,
                    "virtual_server_uuid": virtual_server.uuid,
                    "virtual_server_name": virtual_server.name
                }
            )
            # Generic error message (prevent enumeration)
            raise ValueError(
                f"No credentials found for virtual server '{virtual_server.name}'. "
                "Please configure credentials in vault-proxy."
            )
        
        # 6. Determine which backend system this tool targets
        backend_system = self._determine_backend_system(
            virtual_server=virtual_server,
            tool_name=payload.tool_name,
            credentials=credentials
        )
        
        # 7. Select credential for this backend system
        credential = self._select_credential_for_system(
            credentials=credentials,
            system=backend_system
        )
        
        if not credential:
            raise ValueError(
                f"No credential found for system '{backend_system}' in virtual server '{virtual_server.name}'"
            )
        
        # 8. Inject auth header based on credential metadata
        headers = self._inject_auth_header(payload.headers, credential)
        
        # 9. Return modified payload
        modified_payload = payload.model_copy(update={"headers": headers})
        
        logger.debug(
            "Auth header injected",
            extra={
                "auth_type": credential.auth_type,
                "header_name": credential.header_name,
                "system": credential.system
            }
        )
        
        return ToolPreInvokeResult(modified_payload=modified_payload)
    
    def _extract_user_id(self, request) -> Optional[str]:
        """Extract user ID from JWT token."""
        try:
            # Assuming JWT is validated by middleware and user is in request.state
            return getattr(request.state, "user_email", None)
        except Exception:
            return None
    
    def _validate_vault_token(self, token: str) -> None:
        """Validate vault token format before calling vault-proxy."""
        if not token or len(token) < 20:
            raise ValueError("Invalid vault token format")
        
        # Check for common vault token prefixes
        if not token.startswith(("hvs.", "s.", "root")):
            raise ValueError("Invalid vault token prefix")
    
    def _extract_systems(self, credentials: Union[VaultCredential, List[VaultCredential]]) -> List[str]:
        """Extract list of systems from credentials for logging."""
        if isinstance(credentials, list):
            return [c.system for c in credentials]
        return [credentials.system]
    
    def _determine_backend_system(
        self,
        virtual_server,
        tool_name: str,
        credentials: Union[VaultCredential, List[VaultCredential]]
    ) -> str:
        """Determine which backend system this tool belongs to.
        
        For single-system virtual servers, return the only system.
        For multi-system virtual servers, lookup which backend has this tool.
        """
        # Single-system case
        if not isinstance(credentials, list):
            return credentials.system
        
        # Multi-system case: lookup backend for this tool
        for backend in virtual_server.backends:
            if tool_name in backend.get("tools", []):
                return backend["system"]
        
        # Fallback: if tool not found in config, use first credential's system
        # (This handles dynamic tool discovery scenarios)
        logger.warning(
            "Tool not found in backend config, using first credential system",
            extra={
                "tool_name": tool_name,
                "virtual_server_uuid": virtual_server.uuid,
                "available_systems": [c.system for c in credentials]
            }
        )
        return credentials[0].system
    
    def _select_credential_for_system(
        self,
        credentials: Union[VaultCredential, List[VaultCredential]],
        system: str
    ) -> Optional[VaultCredential]:
        """Select credential matching the backend system.
        
        For single-system virtual servers, return the only credential.
        For multi-system virtual servers, match by system field.
        """
        # Single-system case
        if not isinstance(credentials, list):
            # Verify system matches (sanity check)
            if credentials.system == system:
                return credentials
            logger.warning(
                "System mismatch in single-credential case",
                extra={
                    "expected_system": system,
                    "credential_system": credentials.system
                }
            )
            return credentials  # Return anyway, might still work
        
        # Multi-system case: find matching credential
        return next(
            (c for c in credentials if c.system == system),
            None
        )
    
    def _inject_auth_header(
        self,
        existing_headers: Optional[HttpHeaderPayload],
        credential: VaultCredential
    ) -> HttpHeaderPayload:
        """Inject authentication header based on credential metadata.
        
        Uses the credential's authType and headerName to determine
        how to format and inject the secret value.
        """
        headers = dict(existing_headers.root) if existing_headers else {}
        
        # Normalize header name to lowercase for consistency
        header_name = credential.header_name.lower()
        
        # Inject based on auth type
        if credential.auth_type == "PAT":
            # Personal Access Token - use as-is in specified header
            headers[header_name] = credential.secret_value
            
        elif credential.auth_type == "OAUTH2":
            # OAuth2 - always use Bearer scheme
            headers[header_name] = f"Bearer {credential.secret_value}"
            
        elif credential.auth_type == "JWT":
            # JWT - use Bearer scheme
            headers[header_name] = f"Bearer {credential.secret_value}"
            
        elif credential.auth_type == "BASIC":
            # HTTP Basic Auth - secret_value should already be base64 encoded
            headers[header_name] = f"Basic {credential.secret_value}"
            
        elif credential.auth_type == "APIKEY":
            # API Key - use as-is in specified header (often X-API-Key)
            headers[header_name] = credential.secret_value
            
        elif credential.auth_type == "CUSTOM":
            # Custom auth scheme - use metadata.tokenType if available
            token_type = credential.metadata.get("tokenType", "Bearer")
            if token_type.lower() == "none":
                # No prefix, just the secret
                headers[header_name] = credential.secret_value
            else:
                headers[header_name] = f"{token_type} {credential.secret_value}"
        
        else:
            # Unknown auth type - default to Bearer
            logger.warning(
                "Unknown auth type, defaulting to Bearer",
                extra={
                    "auth_type": credential.auth_type,
                    "system": credential.system
                }
            )
            headers[header_name] = f"Bearer {credential.secret_value}"
        
        return HttpHeaderPayload(root=headers)
```

### Vault Client Implementation

**File**: `plugins/vault_direct/vault_client.py`

```python
"""Vault-proxy client for UUID-based credential resolution."""

import httpx
import logging
from typing import List, Union, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VaultCredential:
    """Self-describing vault credential with metadata."""
    
    secret_value: str
    auth_type: str  # PAT, OAUTH2, JWT, BASIC, APIKEY, CUSTOM
    header_name: str
    system: str
    metadata: dict = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: dict) -> "VaultCredential":
        """Create VaultCredential from API response."""
        return cls(
            secret_value=data["secretValue"],
            auth_type=data["authType"],
            header_name=data["headerName"],
            system=data["system"],
            metadata=data.get("metadata", {})
        )


class VaultProxyClient:
    """Client for vault-proxy API - UUID-based credential resolution."""
    
    def __init__(self, vault_url: str, timeout: float = 5.0, verify_ssl: bool = True):
        """Initialize vault-proxy client.
        
        Args:
            vault_url: Vault-proxy base URL (e.g., http://localhost:8080)
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.vault_url = vault_url.rstrip('/')
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            verify=verify_ssl
        )
    
    async def resolve_credentials_by_uuid(
        self,
        user_id: str,
        virtual_server_uuid: str,
        user_vault_token: str
    ) -> Union[VaultCredential, List[VaultCredential]]:
        """Resolve credentials from vault by virtual server UUID.
        
        Returns either a single VaultCredential (for single-system virtual servers)
        or a list of VaultCredentials (for multi-system virtual servers).
        
        Args:
            user_id: User's identity (email)
            virtual_server_uuid: Virtual server UUID
            user_vault_token: User's vault authentication token
            
        Returns:
            VaultCredential or List[VaultCredential] with complete metadata
            
        Raises:
            VaultNotFoundError: Credentials not found for this virtual server
            VaultConnectionError: Cannot connect to vault-proxy
            VaultAuthError: Invalid vault token
        """
        url = f"{self.vault_url}/api/secret/v1/by-uuid/{user_id}/{virtual_server_uuid}"
        
        headers = {
            "X-Vault-Token": user_vault_token,
            "Content-Type": "application/json"
        }
        
        try:
            response = await self._client.get(url, headers=headers)
            
            if response.status_code == 404:
                raise VaultNotFoundError(
                    f"No credentials found for virtual server '{virtual_server_uuid}' and user {user_id}"
                )
            elif response.status_code == 401:
                raise VaultAuthError("Invalid vault token")
            elif response.status_code != 200:
                raise VaultConnectionError(
                    f"Vault-proxy returned {response.status_code}: {response.text}"
                )
            
            data = response.json()
            
            # Handle both single credential and array of credentials
            if isinstance(data, list):
                return [VaultCredential.from_dict(item) for item in data]
            else:
                return VaultCredential.from_dict(data)
                
        except httpx.RequestError as e:
            raise VaultConnectionError(
                f"Cannot connect to vault-proxy at {self.vault_url}: {e}"
            )
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()


class VaultNotFoundError(Exception):
    """Credentials not found in vault."""
    pass


class VaultConnectionError(Exception):
    """Cannot connect to vault-proxy."""
    pass


class VaultAuthError(Exception):
    """Invalid vault authentication."""
    pass
```

---

## Security Considerations

### 1. Vault Token Transmission

**Implementation**:
```python
# User vault token transmitted via HTTP header (not request body)
headers = {
    "X-Vault-Token": user_vault_token  # Masked in logs
}

# Configure logging middleware to redact vault tokens
SENSITIVE_HEADERS = [
    "X-Vault-Token",
    "Authorization",
    "X-GitHub-Token",
    # ... other auth headers
]
```

### 2. Service-to-Vault Authentication

CF uses its own service-level vault token to call vault-proxy:

```python
# CF service token (AppRole or static token)
# - Read-only policy for user-scoped secrets
# - Cannot modify or delete credentials
# - Scoped to specific path prefix

# Vault policy example:
path "secret/data/users/*/vs-*" {
  capabilities = ["read"]
}
```

### 3. User Identity Verification

```python
# JWT validation happens in middleware before plugin runs
# Plugin trusts request.state.user_email (already validated)

def extract_user_id(request) -> str:
    """Extract validated user ID from request state."""
    user_email = getattr(request.state, "user_email", None)
    if not user_email:
        raise ValueError("User identity not found in request")
    return user_email
```

### 4. Rate Limiting

```python
# Per user + virtual server
rate_limiter = RateLimiter(
    max_requests=20,       # 20 requests
    window_seconds=60,     # per minute
    key_func=lambda req: f"{req.state.user_email}:{req.virtual_server_uuid}"
)

# Response: 429 Too Many Requests
# Headers:
#   Retry-After: 45  (seconds)
#   X-RateLimit-Limit: 20
#   X-RateLimit-Remaining: 0
#   X-RateLimit-Reset: 1719876543 (Unix timestamp)
```

### 5. Credential Enumeration Prevention

```python
# BAD - reveals whether credential exists
raise ValueError(f"No credential for virtual server '{uuid}'")

# GOOD - generic error message
raise ValueError(
    f"No credentials found for virtual server '{vs_name}'. "
    "Please configure credentials in vault-proxy."
)

# Detailed logging (internal only, not exposed to client)
logger.warning(
    "Vault credentials not found",
    extra={
        "user": user_id,
        "virtual_server_uuid": uuid,
        "virtual_server_name": vs_name
    }
)
```

### 6. Audit Trail

```python
# Log all credential resolution attempts
logger.info(
    "Vault credential resolution attempt",
    extra={
        "user": user_id,
        "virtual_server_uuid": vs_uuid,
        "virtual_server_name": vs_name,
        "tool_name": tool_name,
        "timestamp": datetime.utcnow().isoformat(),
        "ip_address": request.client.host
    }
)

# Log success with metadata (no secret values)
logger.info(
    "Vault credentials resolved successfully",
    extra={
        "user": user_id,
        "virtual_server_uuid": vs_uuid,
        "credential_count": len(credentials),
        "systems": [c.system for c in credentials],
        "auth_types": [c.auth_type for c in credentials]
    }
)

# Log failures
logger.warning(
    "Vault credentials not found",
    extra={
        "user": user_id,
        "virtual_server_uuid": vs_uuid,
        "virtual_server_name": vs_name
    }
)
```

### Security Checklist

✅ **User vault tokens via HTTP headers** (masked in logs)  
✅ **CF service token with read-only vault policy**  
✅ **User identity from validated JWT** (not client-provided)  
✅ **Rate limiting** per user + virtual server (20 req/min)  
✅ **Generic error messages** (no credential enumeration)  
✅ **Full audit trail** (all attempts, success/failure)  
✅ **No secret values in logs** (only metadata)  
✅ **No X-Vault-Tokens header** (no plain secrets in transit)

---

## Error Handling

### User-Facing Errors

```python
# Missing vault token
{
  "error": "Vault authentication required",
  "code": "VAULT_AUTH_REQUIRED",
  "message": "Ensure X-Vault-Token header and valid JWT are present.",
  "status": 401
}

# Credentials not found
{
  "error": "Credentials not configured",
  "code": "VAULT_CREDENTIALS_NOT_FOUND",
  "message": "No credentials found for virtual server 'Developer Tools Suite'. Please configure credentials in vault-proxy.",
  "virtual_server_uuid": "vs-dev-tools-123",
  "status": 404
}

# No credential for backend system (multi-system case)
{
  "error": "Missing system credential",
  "code": "VAULT_SYSTEM_CREDENTIAL_NOT_FOUND",
  "message": "No credential found for system 'jira.atlassian.com' in virtual server 'Developer Tools Suite'",
  "virtual_server_uuid": "vs-dev-tools-123",
  "required_system": "jira.atlassian.com",
  "available_systems": ["github.com", "slack.com"],
  "status": 404
}

# Rate limit exceeded
{
  "error": "Rate limit exceeded",
  "code": "RATE_LIMIT_EXCEEDED",
  "message": "Too many credential requests. Please try again later.",
  "retry_after": 45,
  "status": 429
}

# Vault connection error
{
  "error": "Vault unavailable",
  "code": "VAULT_CONNECTION_ERROR",
  "message": "Cannot connect to vault-proxy. Please try again later.",
  "status": 503
}
```

### Internal Logging

```python
# Missing credential for backend (multi-system case)
logger.error(
    "No credential found for backend system",
    extra={
        "user": "user@example.com",
        "virtual_server_uuid": "vs-dev-tools-123",
        "tool_name": "list-issues",
        "required_system": "jira.atlassian.com",
        "available_systems": ["github.com", "slack.com"],
        "credential_count": 2
    }
)

# Tool not found in backend config (dynamic tool discovery)
logger.warning(
    "Tool not found in backend config, using first credential system",
    extra={
        "tool_name": "unknown-tool",
        "virtual_server_uuid": "vs-dev-tools-123",
        "available_systems": ["github.com", "jira.atlassian.com"],
        "fallback_system": "github.com"
    }
)
```

---

## Testing Strategy

### Unit Tests

**File**: `tests/unit/plugins/vault_direct/test_vault_direct_plugin.py`

```python
import pytest
from unittest.mock import Mock, patch, AsyncMock
from plugins.vault_direct.vault_direct_plugin import VaultDirect
from plugins.vault_direct.vault_client import VaultCredential


@pytest.fixture
def plugin():
    config = Mock(
        vault_proxy_url="http://vault:8080",
        vault_proxy_timeout=5.0,
        verify_ssl=True
    )
    return VaultDirect(config)


@pytest.fixture
def single_system_credential():
    """Single-system virtual server credential."""
    return VaultCredential(
        secret_value="ghp_abc123",
        auth_type="PAT",
        header_name="X-GitHub-Token",
        system="github.com"
    )


@pytest.fixture
def multi_system_credentials():
    """Multi-system virtual server credentials."""
    return [
        VaultCredential(
            secret_value="ghp_abc123",
            auth_type="PAT",
            header_name="X-GitHub-Token",
            system="github.com"
        ),
        VaultCredential(
            secret_value="jira_xyz789",
            auth_type="BASIC",
            header_name="Authorization",
            system="jira.atlassian.com"
        )
    ]


async def test_single_system_virtual_server(plugin, single_system_credential):
    """Test credential resolution for single-system virtual server."""
    # Setup
    payload = Mock(tool_name="list-repos", headers=None)
    context = Mock(
        request=Mock(
            headers={"X-Vault-Token": "hvs.test_token"},
            state=Mock(user_email="user@example.com")
        ),
        virtual_server=Mock(
            uuid="vs-github-123",
            name="GitHub MCP",
            backends=[{"system": "github.com", "tools": ["list-repos"]}]
        )
    )
    
    # Mock vault client
    with patch.object(plugin._vault_client, 'resolve_credentials_by_uuid', 
                     new=AsyncMock(return_value=single_system_credential)):
        result = await plugin.tool_pre_invoke(payload, context)
    
    # Verify auth header injected correctly
    assert result.modified_payload.headers.root["x-github-token"] == "ghp_abc123"


async def test_multi_system_virtual_server_github_tool(plugin, multi_system_credentials):
    """Test credential selection for GitHub tool in multi-system virtual server."""
    # Setup
    payload = Mock(tool_name="list-repos", headers=None)
    context = Mock(
        request=Mock(
            headers={"X-Vault-Token": "hvs.test_token"},
            state=Mock(user_email="user@example.com")
        ),
        virtual_server=Mock(
            uuid="vs-dev-tools-123",
            name="Developer Tools",
            backends=[
                {"system": "github.com", "tools": ["list-repos", "create-issue"]},
                {"system": "jira.atlassian.com", "tools": ["list-issues"]}
            ]
        )
    )
    
    # Mock vault client
    with patch.object(plugin._vault_client, 'resolve_credentials_by_uuid',
                     new=AsyncMock(return_value=multi_system_credentials)):
        result = await plugin.tool_pre_invoke(payload, context)
    
    # Verify correct credential selected (GitHub)
    assert result.modified_payload.headers.root["x-github-token"] == "ghp_abc123"
    # Verify Jira credential NOT injected
    assert "authorization" not in result.modified_payload.headers.root


async def test_multi_system_virtual_server_jira_tool(plugin, multi_system_credentials):
    """Test credential selection for Jira tool in multi-system virtual server."""
    # Setup
    payload = Mock(tool_name="list-issues", headers=None)
    context = Mock(
        request=Mock(
            headers={"X-Vault-Token": "hvs.test_token"},
            state=Mock(user_email="user@example.com")
        ),
        virtual_server=Mock(
            uuid="vs-dev-tools-123",
            name="Developer Tools",
            backends=[
                {"system": "github.com", "tools": ["list-repos"]},
                {"system": "jira.atlassian.com", "tools": ["list-issues"]}
            ]
        )
    )
    
    # Mock vault client
    with patch.object(plugin._vault_client, 'resolve_credentials_by_uuid',
                     new=AsyncMock(return_value=multi_system_credentials)):
        result = await plugin.tool_pre_invoke(payload, context)
    
    # Verify correct credential selected (Jira with Basic auth)
    assert result.modified_payload.headers.root["authorization"] == "Basic jira_xyz789"


async def test_auth_type_oauth2(plugin):
    """Test OAuth2 auth type formatting."""
    credential = VaultCredential(
        secret_value="ya29.oauth2_token",
        auth_type="OAUTH2",
        header_name="Authorization",
        system="google.com"
    )
    
    payload = Mock(headers=None)
    headers = plugin._inject_auth_header(payload.headers, credential)
    
    assert headers.root["authorization"] == "Bearer ya29.oauth2_token"


async def test_auth_type_apikey(plugin):
    """Test API Key auth type formatting."""
    credential = VaultCredential(
        secret_value="sk-api-key-123",
        auth_type="APIKEY",
        header_name="X-API-Key",
        system="openai.com"
    )
    
    payload = Mock(headers=None)
    headers = plugin._inject_auth_header(payload.headers, credential)
    
    assert headers.root["x-api-key"] == "sk-api-key-123"


async def test_missing_credential_for_system(plugin, multi_system_credentials):
    """Test error when no credential found for required system."""
    # Setup: tool requires slack.com but credentials only have github.com + jira
    payload = Mock(tool_name="send-message", headers=None)
    context = Mock(
        request=Mock(
            headers={"X-Vault-Token": "hvs.test_token"},
            state=Mock(user_email="user@example.com")
        ),
        virtual_server=Mock(
            uuid="vs-dev-tools-123",
            name="Developer Tools",
            backends=[
                {"system": "github.com", "tools": ["list-repos"]},
                {"system": "jira.atlassian.com", "tools": ["list-issues"]},
                {"system": "slack.com", "tools": ["send-message"]}  # No credential for this
            ]
        )
    )
    
    # Mock vault client
    with patch.object(plugin._vault_client, 'resolve_credentials_by_uuid',
                     new=AsyncMock(return_value=multi_system_credentials)):
        with pytest.raises(ValueError, match="No credential found for system 'slack.com'"):
            await plugin.tool_pre_invoke(payload, context)


async def test_rate_limiting(plugin, single_system_credential):
    """Test rate limiting kicks in after threshold."""
    payload = Mock(tool_name="list-repos", headers=None)
    context = Mock(
        request=Mock(
            headers={"X-Vault-Token": "hvs.test_token"},
            state=Mock(user_email="user@example.com")
        ),
        virtual_server=Mock(
            uuid="vs-github-123",
            name="GitHub MCP",
            backends=[{"system": "github.com", "tools": ["list-repos"]}]
        )
    )
    
    # Mock vault client
    with patch.object(plugin._vault_client, 'resolve_credentials_by_uuid',
                     new=AsyncMock(return_value=single_system_credential)):
        # Mock rate limiter to reject
        with patch.object(plugin._rate_limiter, 'allow', return_value=False):
            with pytest.raises(ValueError, match="Too many credential requests"):
                await plugin.tool_pre_invoke(payload, context)
```

### Integration Tests

**File**: `tests/integration/test_vault_direct_flow.py`

```python
import pytest
from fastapi.testclient import TestClient
from mcpgateway.main import app


@pytest.fixture
def mock_vault_server():
    """Mock vault-proxy server with UUID-based credential storage."""
    vault_data = {
        ("user@example.com", "vs-github-123"): {
            "secretValue": "ghp_test_token",
            "authType": "PAT",
            "headerName": "X-GitHub-Token",
            "system": "github.com"
        },
        ("user@example.com", "vs-dev-tools-123"): [
            {
                "secretValue": "ghp_test_token",
                "authType": "PAT",
                "headerName": "X-GitHub-Token",
                "system": "github.com"
            },
            {
                "secretValue": "amlyYTp0ZXN0",  # base64: jira:test
                "authType": "BASIC",
                "headerName": "Authorization",
                "system": "jira.atlassian.com"
            }
        ]
    }
    
    # Start mock server
    # ... implementation ...
    
    return vault_data


async def test_end_to_end_single_system_virtual_server(client, mock_vault_server, mock_mcp_server):
    """Test complete flow for single-system virtual server."""
    
    # 1. Create virtual server
    vs_response = await client.post("/api/v1/admin/virtual-servers", json={
        "name": "GitHub MCP",
        "backends": [
            {
                "system": "github.com",
                "gateway_id": "gw-github-001",
                "tools": ["list-repos", "create-issue"]
            }
        ]
    })
    vs_uuid = vs_response.json()["id"]
    
    # 2. Invoke tool
    response = await client.post(
        f"/servers/{vs_uuid}/mcp",
        headers={
            "Authorization": "Bearer user_jwt_token",
            "X-Vault-Token": "hvs.test_token"
        },
        json={
            "tool_name": "list-repos",
            "arguments": {"org": "myorg"}
        }
    )
    
    assert response.status_code == 200
    
    # 3. Verify auth header was injected correctly to backend
    backend_request = mock_mcp_server.get_last_request()
    assert backend_request.headers["X-GitHub-Token"] == "ghp_test_token"


async def test_end_to_end_multi_system_virtual_server(client, mock_vault_server, mock_mcp_server):
    """Test complete flow for multi-system virtual server."""
    
    # 1. Create multi-system virtual server
    vs_response = await client.post("/api/v1/admin/virtual-servers", json={
        "name": "Developer Tools",
        "backends": [
            {
                "system": "github.com",
                "gateway_id": "gw-github-001",
                "tools": ["list-repos"]
            },
            {
                "system": "jira.atlassian.com",
                "gateway_id": "gw-jira-001",
                "tools": ["list-issues"]
            }
        ]
    })
    vs_uuid = vs_response.json()["id"]
    
    # 2. Invoke GitHub tool
    github_response = await client.post(
        f"/servers/{vs_uuid}/mcp",
        headers={
            "Authorization": "Bearer user_jwt_token",
            "X-Vault-Token": "hvs.test_token"
        },
        json={
            "tool_name": "list-repos",
            "arguments": {"org": "myorg"}
        }
    )
    assert github_response.status_code == 200
    
    # Verify GitHub credential used
    github_request = mock_mcp_server.get_last_request("gw-github-001")
    assert github_request.headers["X-GitHub-Token"] == "ghp_test_token"
    
    # 3. Invoke Jira tool
    jira_response = await client.post(
        f"/servers/{vs_uuid}/mcp",
        headers={
            "Authorization": "Bearer user_jwt_token",
            "X-Vault-Token": "hvs.test_token"
        },
        json={
            "tool_name": "list-issues",
            "arguments": {"project": "PROJ"}
        }
    )
    assert jira_response.status_code == 200
    
    # Verify Jira credential used (Basic auth)
    jira_request = mock_mcp_server.get_last_request("gw-jira-001")
    assert jira_request.headers["Authorization"] == "Basic amlyYTp0ZXN0"
```

---

## Plugin Configuration

**File**: `plugins/config.yaml`

```yaml
# Vault Direct Plugin - VirtualServer UUID based
vault_direct:
  enabled: true
  config:
    # Vault-proxy connection
    vault_proxy_url: "${VAULT_PROXY_URL}"
    vault_proxy_timeout: 5.0
    verify_ssl: true
    
    # Rate limiting (per user + virtual server)
    rate_limit_max_requests: 20
    rate_limit_window_seconds: 60
    
    # Logging
    audit_log_enabled: true
    mask_secrets_in_logs: true
```

**Environment Variables** (`.env`):

```bash
# Vault-proxy configuration
VAULT_PROXY_URL=http://vault-proxy:8080

# Plugin enabled
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml
```

---

## Migration Path

### Phase 1: Vault-Proxy Changes (Parallel Work)

**Vault-proxy team implements:**

1. **New API endpoint**: `GET /api/secret/v1/by-uuid/{user_id}/{virtualServerUuid}`
2. **Credential storage format**: Self-describing struct with metadata
3. **Multi-system support**: Return array when multiple credentials configured

**Vault credential examples:**

```bash
# Single-system virtual server
vault kv put secret/users/user@example.com/vs-github-123 \
  secretValue="ghp_abc123def456" \
  authType="PAT" \
  headerName="X-GitHub-Token" \
  system="github.com"

# Multi-system virtual server (JSON file)
vault kv put secret/users/user@example.com/vs-dev-tools-123 @credentials.json

# credentials.json:
[
  {
    "secretValue": "ghp_abc123def456",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "amlyYTp0ZXN0Cg==",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.atlassian.com"
  }
]
```

### Phase 2: Context Forge Changes

1. **Add vault_direct plugin** (new plugin, no changes to existing vault plugin)
2. **Plugin routing logic** - detect X-Vault-Token header to use vault_direct
3. **Add virtual_server to plugin context** (if not already present)
4. **Update tests**

### Phase 3: Agent Changes

**Remove**:
- Agent-side vault credential resolution
- X-Vault-Tokens header construction
- Agent config file for credential mapping

**Keep**:
- User vault token pass-through
- User identity from JWT

### Phase 4: Gradual Rollout

```bash
# Week 1: Deploy vault-proxy changes (staging)
# Week 2: Deploy CF vault_direct plugin (staging)
# Week 3: Update one agent to use new flow (staging)
# Week 4: Validate end-to-end (staging)
# Week 5: Production rollout (gradual, per team)
```

### Phase 5: Legacy Plugin Deprecation

After all agents migrated (6+ months):

1. Mark legacy vault plugin as deprecated
2. Set deprecation timeline (6 months notice)
3. Remove legacy plugin
4. Clean up X-Vault-Tokens header handling

---

## Benefits of This Design

### Technical Benefits

✅ **Uses existing infrastructure** - Virtual server UUIDs already exist  
✅ **Self-describing credentials** - No inference, all metadata included  
✅ **Multi-system support** - Native support for aggregated virtual servers  
✅ **Zero agent configuration** - No config files needed  
✅ **Zero database changes** - No new columns or tables  
✅ **Stateless** - UUID computed from request, credentials from vault  
✅ **Single source of truth** - Vault contains complete credential definition  
✅ **Extensible** - New auth types just add to enum, no code changes  

### Operational Benefits

✅ **Simpler onboarding** - Users just create credentials in vault  
✅ **Clearer errors** - Self-describing structs enable specific error messages  
✅ **Easier debugging** - UUID lookup path is deterministic  
✅ **Better audit trail** - Log includes virtual server name + UUID  
✅ **Scalable** - O(1) config per virtual server (just the UUID)  
✅ **No coordination** - Agent, CF, and vault work independently  

### Security Benefits

✅ **No plain secrets in transit** - User vault token, not resolved secrets  
✅ **Credential scope control** - Per-user, per-virtual-server granularity  
✅ **Audit trail** - All credential access logged with context  
✅ **Rate limiting** - Prevent brute force credential discovery  
✅ **Generic errors** - No credential enumeration via error messages  

---

## API Examples

### Single-System Virtual Server

**Create Virtual Server:**
```bash
POST /api/v1/admin/virtual-servers
{
  "name": "GitHub MCP",
  "backends": [
    {
      "system": "github.com",
      "gateway_id": "gw-github-001",
      "tools": ["list-repos", "create-issue", "get-pr"]
    }
  ]
}

Response:
{
  "id": "vs-github-abc123",
  "name": "GitHub MCP",
  "backends": [...]
}
```

**Configure Vault Credential (User does this in vault-proxy):**
```bash
# User stores credential in vault
vault kv put secret/users/user@example.com/vs-github-abc123 \
  secretValue="ghp_abc123def456" \
  authType="PAT" \
  headerName="X-GitHub-Token" \
  system="github.com"
```

**Invoke Tool:**
```bash
POST /servers/vs-github-abc123/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "tool_name": "list-repos",
  "arguments": {
    "org": "myorg"
  }
}

Response:
{
  "result": {
    "repositories": [...]
  }
}
```

### Multi-System Virtual Server

**Create Virtual Server:**
```bash
POST /api/v1/admin/virtual-servers
{
  "name": "Developer Tools Suite",
  "description": "Aggregated access to GitHub, Jira, and Slack",
  "backends": [
    {
      "system": "github.com",
      "gateway_id": "gw-github-001",
      "tools": ["list-repos", "create-issue"]
    },
    {
      "system": "jira.atlassian.com",
      "gateway_id": "gw-jira-001",
      "tools": ["list-issues", "create-ticket"]
    },
    {
      "system": "slack.com",
      "gateway_id": "gw-slack-001",
      "tools": ["send-message", "list-channels"]
    }
  ]
}

Response:
{
  "id": "vs-dev-tools-xyz789",
  "name": "Developer Tools Suite",
  "backends": [...]
}
```

**Configure Vault Credentials (Array):**
```bash
# Create credentials.json
cat > credentials.json <<EOF
[
  {
    "secretValue": "ghp_github_token_xyz",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "dXNlcjpqaXJhX3Rva2VuCg==",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.atlassian.com"
  },
  {
    "secretValue": "xoxb-slack-token-abc",
    "authType": "OAUTH2",
    "headerName": "Authorization",
    "system": "slack.com"
  }
]
EOF

# Store in vault
vault kv put secret/users/user@example.com/vs-dev-tools-xyz789 @credentials.json
```

**Invoke GitHub Tool:**
```bash
POST /servers/vs-dev-tools-xyz789/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "tool_name": "list-repos",
  "arguments": {"org": "myorg"}
}

# CF automatically:
# 1. Looks up credentials by vs-dev-tools-xyz789
# 2. Gets array of 3 credentials
# 3. Determines tool "list-repos" belongs to github.com backend
# 4. Selects GitHub credential from array
# 5. Injects X-GitHub-Token header
# 6. Forwards to gw-github-001
```

**Invoke Jira Tool:**
```bash
POST /servers/vs-dev-tools-xyz789/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "tool_name": "list-issues",
  "arguments": {"project": "PROJ"}
}

# CF automatically:
# 1. Same credential lookup (cached)
# 2. Determines tool "list-issues" belongs to jira.atlassian.com backend
# 3. Selects Jira credential from array
# 4. Injects Authorization: Basic header
# 5. Forwards to gw-jira-001
```

---

## Comparison with Previous Approaches

| Aspect | Tag-Based (Legacy) | Domain-Based | **VirtualServer UUID** |
|--------|-------------------|--------------|----------------------|
| **Lookup Key** | Gateway tags | Domain from URL | Virtual server UUID |
| **Credential Format** | Plain string | Plain string | **Self-describing struct** |
| **Auth Metadata** | Tags (AUTH_HEADER) | Inferred | **Included in struct** |
| **Multi-System** | ❌ Complex | ❌ Can't handle | ✅ **Native support** |
| **Agent Config** | ❌ Required | ✅ Not needed | ✅ Not needed |
| **DB Changes** | None | None | None |
| **Silent Failures** | ❌ Yes (tag mismatch) | ⚠️ Possible | ✅ Explicit errors |
| **Vault Organization** | By custom names | By domain | **By virtual server UUID** |
| **Scalability** | ⚠️ Tag maintenance | ✅ Good | ✅ **Excellent** |
| **Debugging** | ❌ Hard (3 configs) | ⚠️ Medium | ✅ **Easy (UUID path)** |
| **Industry Standard** | ❌ Custom | ✅ Domain-based | ✅ **Resource-based** |

**Winner**: VirtualServer UUID approach handles all scenarios, including multi-system virtual servers that the other approaches cannot.

---

## Summary

**Key Design Decisions:**

1. **Virtual server UUID as lookup key** - Already exists, natural identity
2. **Self-describing credential structs** - Include all metadata (authType, headerName, system)
3. **Array support for multi-system** - Single virtual server, multiple backend systems
4. **System field for routing** - Plugin matches credential to backend by system
5. **Zero database changes** - UUID already in request path
6. **Zero agent configuration** - Just pass user identity and vault token

**Request Flow:**
```
User → Agent → CF (extracts virtualServerUuid from path)
            ↓
      Vault lookup: {user_id}/{virtualServerUuid}
            ↓
      Returns: struct or array of structs
            ↓
      CF matches credential to backend by system field
            ↓
      CF injects auth header per authType
            ↓
      Backend MCP server
```

**Vault Storage:**
```
secret/
└── users/
    └── user@example.com/
        ├── vs-github-abc123          # Single credential
        │   ├── secretValue: "ghp_..."
        │   ├── authType: "PAT"
        │   ├── headerName: "X-GitHub-Token"
        │   └── system: "github.com"
        └── vs-dev-tools-xyz789        # Array of credentials
            ├── [0]
            │   ├── secretValue: "ghp_..."
            │   ├── authType: "PAT"
            │   ├── headerName: "X-GitHub-Token"
            │   └── system: "github.com"
            ├── [1]
            │   ├── secretValue: "jira_..."
            │   ├── authType: "BASIC"
            │   ├── headerName: "Authorization"
            │   └── system: "jira.atlassian.com"
            └── [2]
                ├── secretValue: "xoxb-..."
                ├── authType: "OAUTH2"
                ├── headerName: "Authorization"
                └── system: "slack.com"
```

This design is production-ready, handles all use cases (including multi-system virtual servers), and aligns with existing infrastructure.
