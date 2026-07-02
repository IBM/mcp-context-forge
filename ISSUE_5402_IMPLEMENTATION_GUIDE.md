# Issue #5402: Implementation Guide - Files to Create and Update

## Overview

This guide lists all files that need to be **created** or **updated** in the mcp-context-forge repository to implement the VirtualServer UUID vault integration approach.

---

## 📁 Files to CREATE (New Files)

### 1. Plugin Files

#### `plugins/vault_direct/__init__.py`
```python
# -*- coding: utf-8 -*-
"""Location: ./plugins/vault_direct/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Vault Direct Plugin - VirtualServer UUID based credential resolution.
"""

from plugins.vault_direct.vault_direct_plugin import VaultDirect

__all__ = ["VaultDirect"]
```

#### `plugins/vault_direct/vault_client.py`
```python
# -*- coding: utf-8 -*-
"""Location: ./plugins/vault_direct/vault_client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Vault-proxy client for UUID-based credential resolution.

This module provides HTTP client for calling vault-proxy API to resolve
credentials by virtual server UUID. Supports both single-system and
multi-system virtual servers.
"""

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

#### `plugins/vault_direct/vault_direct_plugin.py`
**Location**: See ISSUE_5402_FINAL_DESIGN_V2.md lines 324-471 for full implementation

Key sections:
- Plugin class with `__init__` and `tool_pre_invoke` methods
- Vault token validation
- Rate limiting integration
- Credential resolution by UUID
- Backend system determination (for multi-system virtual servers)
- Credential selection by system field
- Auth header injection based on authType

#### `plugins/vault_direct/README.md`
```markdown
# Vault Direct Plugin

**Status**: Active  
**Version**: 1.0.0  
**Hook**: tool_pre_invoke

## Overview

Direct vault integration using virtual server UUID for credential resolution.
Replaces legacy tag-based credential matching with self-describing credential structs.

## Features

- ✅ VirtualServer UUID-based credential lookup
- ✅ Self-describing credentials (secretValue, authType, headerName, system)
- ✅ Multi-system virtual server support
- ✅ Rate limiting (20 req/min per user+virtualServer)
- ✅ Full audit trail
- ✅ Generic error messages (prevent credential enumeration)

## Configuration

```yaml
vault_direct:
  enabled: true
  config:
    vault_proxy_url: "${VAULT_PROXY_URL}"
    vault_proxy_timeout: 5.0
    verify_ssl: true
    rate_limit_max_requests: 20
    rate_limit_window_seconds: 60
```

## Usage

### Single-System Virtual Server

User stores credential in vault:
```bash
vault kv put secret/users/user@example.com/vs-github-abc123 \
  secretValue="ghp_abc123" \
  authType="PAT" \
  headerName="X-GitHub-Token" \
  system="github.com"
```

Agent sends request:
```http
POST /servers/vs-github-abc123/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "list-repos",
    "arguments": {"org": "myorg"}
  },
  "id": 1
}
```

### Multi-System Virtual Server

User stores credentials in vault (array):
```bash
cat > credentials.json <<EOF
[
  {
    "secretValue": "ghp_abc123",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "jira_xyz789",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.com"
  }
]
EOF

vault kv put secret/users/user@example.com/vs-dev-tools-xyz789 @credentials.json
```

## Supported Auth Types

- **PAT**: Personal Access Token (raw header injection)
- **OAUTH2**: OAuth 2.0 Bearer token
- **JWT**: JSON Web Token (Bearer scheme)
- **BASIC**: HTTP Basic Auth (base64 encoded)
- **APIKEY**: API Key (custom header)
- **CUSTOM**: Custom auth scheme (configurable token type)

## Error Handling

- Missing credentials: Generic error message + internal audit log
- Invalid vault token: 401 Unauthorized
- Rate limit exceeded: 429 Too Many Requests
- Vault unavailable: 503 Service Unavailable

## Migration

See `ISSUE_5402_MIGRATION_GUIDE.md` for migration from legacy vault plugin.

## Security

- Vault tokens transmitted via X-Vault-Token header (masked in logs)
- Rate limiting per user+virtualServer (prevent brute force)
- Full audit trail (all attempts logged)
- Generic error messages (prevent credential enumeration)
```

#### `plugins/vault_direct/plugin-manifest.yaml`
```yaml
name: vault_direct
version: 1.0.0
description: Direct vault integration using virtual server UUID
author: ContextForge Team
license: Apache-2.0

hooks:
  - tool_pre_invoke

config_schema:
  vault_proxy_url:
    type: string
    required: true
    description: Vault-proxy base URL
  
  vault_proxy_timeout:
    type: float
    default: 5.0
    description: Request timeout in seconds
  
  verify_ssl:
    type: boolean
    default: true
    description: Whether to verify SSL certificates
  
  rate_limit_max_requests:
    type: integer
    default: 20
    description: Max requests per window
  
  rate_limit_window_seconds:
    type: integer
    default: 60
    description: Rate limit window in seconds

dependencies:
  - httpx>=0.24.0
  - pydantic>=2.0.0
```

---

### 2. Test Files

#### `tests/unit/plugins/vault_direct/__init__.py`
```python
# Empty file for package
```

#### `tests/unit/plugins/vault_direct/test_vault_client.py`
**Key tests**:
- `test_resolve_single_credential()`
- `test_resolve_multiple_credentials()`
- `test_credential_not_found()`
- `test_invalid_vault_token()`
- `test_vault_connection_error()`

#### `tests/unit/plugins/vault_direct/test_vault_direct_plugin.py`
**Key tests**:
- `test_single_system_virtual_server()`
- `test_multi_system_virtual_server_github_tool()`
- `test_multi_system_virtual_server_jira_tool()`
- `test_auth_type_pat()`
- `test_auth_type_oauth2()`
- `test_auth_type_basic()`
- `test_auth_type_apikey()`
- `test_missing_credential_for_system()`
- `test_rate_limiting()`
- `test_vault_token_validation()`

See ISSUE_5402_FINAL_DESIGN_V2.md lines 823-936 for test implementation details

#### `tests/integration/test_vault_direct_flow.py`
**Key tests**:
- `test_end_to_end_single_system_virtual_server()`
- `test_end_to_end_multi_system_virtual_server()`
- `test_credential_not_found_error()`
- `test_rate_limit_exceeded()`

See ISSUE_5402_FINAL_DESIGN_V2.md lines 870-936 for test implementation details

---

### 3. Documentation Files

#### `docs/plugins/vault_direct.md`
```markdown
# Vault Direct Plugin

## Overview

The vault_direct plugin provides direct integration with vault-proxy for credential
resolution based on virtual server UUID. It replaces the legacy tag-based vault
plugin with a more robust, self-describing credential approach.

## Key Features

### 1. VirtualServer UUID Lookup

Credentials are stored at `{user_id}/{virtualServerUuid}` in vault, using the
virtual server UUID from the request path as the lookup key.

### 2. Self-Describing Credentials

Vault credentials include complete metadata:
- `secretValue`: The actual secret
- `authType`: How to use the secret (PAT, OAUTH2, JWT, BASIC, APIKEY, CUSTOM)
- `headerName`: Which HTTP header to inject
- `system`: Domain/system identifier for routing

### 3. Multi-System Support

A single virtual server can aggregate tools from multiple backend systems. The
plugin stores an array of credentials, each with a `system` field, and selects
the appropriate credential based on which backend the tool belongs to.

## Configuration

```yaml
vault_direct:
  enabled: true
  config:
    vault_proxy_url: "http://vault-proxy:8080"
    vault_proxy_timeout: 5.0
    verify_ssl: true
    rate_limit_max_requests: 20
    rate_limit_window_seconds: 60
```

## Request Flow

1. Agent sends request with `X-Vault-Token` header
2. CF extracts `virtualServerUuid` from request path
3. CF calls vault-proxy: `GET /api/secret/v1/by-uuid/{user_id}/{virtualServerUuid}`
4. Vault returns credential or array of credentials
5. CF determines which backend system the tool belongs to
6. CF selects credential matching backend system
7. CF injects auth header based on credential metadata
8. CF forwards request to backend with authentication

## Auth Types

### PAT (Personal Access Token)
```json
{
  "authType": "PAT",
  "headerName": "X-GitHub-Token",
  "secretValue": "ghp_abc123"
}
```
Injected as: `X-GitHub-Token: ghp_abc123`

### OAUTH2
```json
{
  "authType": "OAUTH2",
  "headerName": "Authorization",
  "secretValue": "ya29.oauth2_token"
}
```
Injected as: `Authorization: Bearer ya29.oauth2_token`

### JWT
```json
{
  "authType": "JWT",
  "headerName": "Authorization",
  "secretValue": "eyJhbGc..."
}
```
Injected as: `Authorization: Bearer eyJhbGc...`

### BASIC
```json
{
  "authType": "BASIC",
  "headerName": "Authorization",
  "secretValue": "dXNlcjpwYXNzCg=="
}
```
Injected as: `Authorization: Basic dXNlcjpwYXNzCg==`

### APIKEY
```json
{
  "authType": "APIKEY",
  "headerName": "X-API-Key",
  "secretValue": "sk-api-key-123"
}
```
Injected as: `X-API-Key: sk-api-key-123`

### CUSTOM
```json
{
  "authType": "CUSTOM",
  "headerName": "X-Custom-Auth",
  "secretValue": "custom_token_value",
  "metadata": {
    "tokenType": "Bearer"
  }
}
```
Injected as: `X-Custom-Auth: Bearer custom_token_value`

## Security

### Rate Limiting
- 20 requests per minute per user+virtualServer
- Prevents brute force credential discovery
- Returns 429 Too Many Requests on limit exceeded

### Audit Trail
All credential resolution attempts are logged:
- User identity
- Virtual server UUID
- Tool name
- Timestamp
- Success/failure
- Auth type and system (no secret values)

### Generic Error Messages
Error messages do not reveal whether credentials exist:
- "No credentials found for virtual server" (not "for system X")
- Same error for not found vs vault unavailable
- Prevents credential enumeration attacks

### Vault Token Handling
- Transmitted via `X-Vault-Token` header (not request body)
- Masked in application logs
- Never logged in error messages
- Validated before vault-proxy call (fail fast)

## Multi-System Example

### Virtual Server Configuration
```json
{
  "id": "vs-dev-tools-abc123",
  "name": "Developer Tools Suite",
  "backends": [
    {
      "system": "github.com",
      "gateway_id": "gw-github-001",
      "tools": ["list-repos", "create-issue"]
    },
    {
      "system": "jira.com",
      "gateway_id": "gw-jira-001",
      "tools": ["list-issues", "create-ticket"]
    }
  ]
}
```

### Vault Credentials
```json
[
  {
    "secretValue": "ghp_github_token",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "dXNlcjpqaXJhX3Rva2VuCg==",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.com"
  }
]
```

### Tool Invocation
```bash
# Invoke GitHub tool via MCP protocol
POST /servers/vs-dev-tools-abc123/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "list-repos",
    "arguments": {"org": "myorg"}
  },
  "id": 1
}

# Plugin flow:
# 1. Fetches credentials by UUID → gets array of 2 credentials
# 2. Determines "list-repos" → backend.system = "github.com"
# 3. Selects credential where system == "github.com"
# 4. Injects X-GitHub-Token header
# 5. Forwards to gw-github-001
```

## Migration

To migrate from legacy vault plugin, see `ISSUE_5402_MIGRATION_GUIDE.md`.

## Troubleshooting

### Error: "No credentials found for virtual server"
**Cause**: User hasn't created credential in vault  
**Solution**: Create credential at `secret/users/{user_email}/{virtual_server_uuid}`

### Error: "Invalid vault token"
**Cause**: X-Vault-Token header missing or invalid  
**Solution**: User re-authenticates to get new vault token

### Error: "No credential found for system 'X'"
**Cause**: Multi-system virtual server, but credential missing for system X  
**Solution**: User creates credential for missing system

### Error: "Too many credential requests"
**Cause**: Rate limit exceeded (>20 req/min)  
**Solution**: Wait or contact admin to increase rate limit

## Related

- Legacy vault plugin: `plugins/vault/`
- Migration guide: `ISSUE_5402_MIGRATION_GUIDE.md`
- Architecture design: `ISSUE_5402_FINAL_DESIGN_V2.md`
```

---

## 📝 Files to UPDATE (Existing Files)

### 1. Plugin Configuration

#### `plugins/config.yaml`
**Location**: `/Users/rakhidutta/mcp-context-forge/plugins/config.yaml`

**Changes**:
```yaml
# ADD this section (keep existing vault plugin for backward compatibility)

vault_direct:
  enabled: true
  config:
    vault_proxy_url: "${VAULT_PROXY_URL:-http://localhost:8080}"
    vault_proxy_timeout: 5.0
    verify_ssl: true
    rate_limit_max_requests: 20
    rate_limit_window_seconds: 60
    audit_log_enabled: true
    mask_secrets_in_logs: true
```

**Note**: Keep the existing `vault:` section unchanged during migration period.

---

### 2. Database Models (Optional - No Changes Needed)

#### `mcpgateway/db.py`
**Location**: `/Users/rakhidutta/mcp-context-forge/mcpgateway/db.py`

**Changes**: **NONE REQUIRED**

The VirtualServer UUID approach deliberately avoids database schema changes.
Virtual server UUID already exists in the database model.

**Optional Enhancement** (if you want to add computed property for documentation):
```python
# In Gateway or VirtualServer model class (if exists)

@property
def required_domain(self) -> str:
    """Extract domain from URL for documentation purposes.
    
    Note: This is NOT used by vault_direct plugin (uses UUID instead).
    Kept for API documentation and backward compatibility.
    """
    from urllib.parse import urlparse
    hostname = urlparse(self.url).hostname or ""
    for prefix in ['api.', 'www.']:
        if hostname.startswith(prefix):
            hostname = hostname[len(prefix):]
    return hostname
```

---

### 3. API Schemas (Optional)

#### `mcpgateway/schemas.py`
**Location**: `/Users/rakhidutta/mcp-context-forge/mcpgateway/schemas.py`

**Changes**: **NONE REQUIRED**

Virtual server UUID is already in schemas. No new fields needed.

**Optional Enhancement** (if you want to document in API response):
```python
# In VirtualServer schema (if exists)

class VirtualServer(BaseModel):
    """Virtual server schema."""
    id: str  # UUID - used by vault_direct plugin
    name: str
    url: str
    description: Optional[str] = None
    backends: Optional[List[Backend]] = None
    # ... other fields ...
    
    class Config:
        from_attributes = True
```

---

### 4. Plugin Router/Middleware (New Logic Needed)

#### Create: `mcpgateway/middleware/plugin_router.py`
**Location**: `/Users/rakhidutta/mcp-context-forge/mcpgateway/middleware/plugin_router.py`

```python
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/plugin_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Plugin routing logic - determines which plugins to invoke for a request.
"""

from typing import List, Optional
from fastapi import Request


def select_vault_plugin(request: Request) -> Optional[str]:
    """Select which vault plugin to use based on request headers.
    
    Returns:
        "vault_direct" - New UUID-based approach (X-Vault-Token header)
        "vault" - Legacy tag-based approach (X-Vault-Tokens header)
        None - No vault plugin needed
    """
    # New format: has X-Vault-Token header (user's vault token)
    if "X-Vault-Token" in request.headers or "x-vault-token" in request.headers:
        return "vault_direct"
    
    # Legacy format: has X-Vault-Tokens header (resolved credentials)
    elif "X-Vault-Tokens" in request.headers or "x-vault-tokens" in request.headers:
        return "vault"
    
    # No vault plugin needed
    return None


def get_plugins_for_request(request: Request) -> List[str]:
    """Determine which plugins should be invoked for this request.
    
    Returns:
        List of plugin names to invoke
    """
    plugins = []
    
    # Vault plugin selection
    vault_plugin = select_vault_plugin(request)
    if vault_plugin:
        plugins.append(vault_plugin)
    
    # Add other plugin selections here
    # ... (existing plugin routing logic)
    
    return plugins
```

**Integration Point**: This middleware needs to be called during request processing to determine which vault plugin to use.

---

### 5. Environment Variables

#### `.env.example`
**Location**: `/Users/rakhidutta/mcp-context-forge/.env.example`

**Add**:
```bash
# Vault Direct Plugin Configuration
VAULT_PROXY_URL=http://localhost:8080
VAULT_PROXY_TIMEOUT=5.0
```

#### `.env`
**Location**: `/Users/rakhidutta/mcp-context-forge/.env` (if exists)

**Add** (for local development):
```bash
VAULT_PROXY_URL=http://localhost:8080
```

---

### 6. Requirements

#### `plugins/requirements.txt`
**Location**: `/Users/rakhidutta/mcp-context-forge/plugins/requirements.txt`

**Add** (if not already present):
```
httpx>=0.24.0
```

---

### 7. Documentation

#### `plugins/README.md`
**Location**: `/Users/rakhidutta/mcp-context-forge/plugins/README.md`

**Add section**:
```markdown
## Vault Direct Plugin

Direct vault integration using virtual server UUID for credential resolution.

- **Directory**: `vault_direct/`
- **Status**: Active
- **Hook**: tool_pre_invoke
- **Purpose**: Replace legacy tag-based credential matching with self-describing credential structs
- **Documentation**: See `vault_direct/README.md`

### Key Features

- VirtualServer UUID-based credential lookup
- Self-describing credentials (secretValue, authType, headerName, system)
- Multi-system virtual server support
- Rate limiting and audit trail
- Generic error messages (prevent credential enumeration)

### Migration

For migration from legacy vault plugin, see `ISSUE_5402_MIGRATION_GUIDE.md`.
```

---

### 8. Legacy Vault Plugin (Mark as Deprecated)

#### `plugins/vault/README.md`
**Location**: `/Users/rakhidutta/mcp-context-forge/plugins/vault/README.md`

**Add at the top**:
```markdown
# Vault Plugin (Legacy - DEPRECATED)

⚠️ **DEPRECATED**: This plugin uses tag-based credential matching and is deprecated
in favor of the `vault_direct` plugin which provides direct vault-proxy integration.

**Migration**: Follow the migration guide at `ISSUE_5402_MIGRATION_GUIDE.md`

**Support timeline**:
- Deprecated: 2026-08-01
- Removal: 2027-02-01 (6 months notice)

**Why migrate**:
- ✅ Self-describing credentials (no tag matching)
- ✅ Multi-system virtual server support
- ✅ Better error messages
- ✅ Simpler configuration (no agent config file)

---

# Original README (Legacy)

[Keep existing content below...]
```

#### `plugins/vault/vault_plugin.py`
**Location**: `/Users/rakhidutta/mcp-context-forge/plugins/vault/vault_plugin.py`

**Add deprecation warning in `__init__` method**:
```python
def __init__(self, config: PluginConfig):
    super().__init__(config)
    
    # Log deprecation warning
    logger.warning(
        "Legacy vault plugin is DEPRECATED and will be removed on 2027-02-01. "
        "Please migrate to vault_direct plugin. "
        "See: ISSUE_5402_MIGRATION_GUIDE.md"
    )
    
    # ... rest of existing __init__ code ...
```

---

## 📋 Summary Checklist

### Files to CREATE ✅

#### Plugin Implementation
- [ ] `plugins/vault_direct/__init__.py`
- [ ] `plugins/vault_direct/vault_client.py`
- [ ] `plugins/vault_direct/vault_direct_plugin.py`
- [ ] `plugins/vault_direct/README.md`
- [ ] `plugins/vault_direct/plugin-manifest.yaml`

#### Tests
- [ ] `tests/unit/plugins/vault_direct/__init__.py`
- [ ] `tests/unit/plugins/vault_direct/test_vault_client.py`
- [ ] `tests/unit/plugins/vault_direct/test_vault_direct_plugin.py`
- [ ] `tests/integration/test_vault_direct_flow.py`

#### Middleware
- [ ] `mcpgateway/middleware/plugin_router.py` (if doesn't exist)

#### Documentation
- [ ] `docs/plugins/vault_direct.md`
- [ ] `ISSUE_5402_IMPLEMENTATION_GUIDE.md` (this file)

### Files to UPDATE ✅

#### Configuration
- [ ] `plugins/config.yaml` - Add vault_direct section
- [ ] `.env.example` - Add VAULT_PROXY_URL
- [ ] `.env` - Add VAULT_PROXY_URL (local dev)
- [ ] `plugins/requirements.txt` - Add httpx dependency

#### Documentation
- [ ] `plugins/README.md` - Add vault_direct section
- [ ] `plugins/vault/README.md` - Add deprecation notice
- [ ] `plugins/vault/vault_plugin.py` - Add deprecation warning log

#### Database/Schema (Optional - NOT Required)
- [ ] `mcpgateway/db.py` - **NO CHANGES NEEDED** (optional: add computed property for docs)
- [ ] `mcpgateway/schemas.py` - **NO CHANGES NEEDED**

---

## 🚀 Implementation Order

### Phase 1: Core Plugin (Week 1)
1. Create `vault_client.py` (vault-proxy HTTP client)
2. Create `vault_direct_plugin.py` (main plugin logic)
3. Create `__init__.py` and `plugin-manifest.yaml`
4. Update `plugins/config.yaml` (add vault_direct section)

### Phase 2: Testing (Week 2)
1. Create unit tests for `vault_client.py`
2. Create unit tests for `vault_direct_plugin.py`
3. Create integration tests
4. Run tests: `pytest tests/unit/plugins/vault_direct/`

### Phase 3: Middleware Integration (Week 3)
1. Create or update `plugin_router.py`
2. Integrate plugin routing into request processing
3. Test both legacy and new plugin coexistence

### Phase 4: Documentation (Week 4)
1. Create `plugins/vault_direct/README.md`
2. Create `docs/plugins/vault_direct.md`
3. Update `plugins/README.md`
4. Add deprecation notice to legacy vault plugin

### Phase 5: Deployment (Week 5+)
1. Deploy to staging
2. Test end-to-end with real vault-proxy
3. Monitor logs and metrics
4. Deploy to production
5. Follow migration guide for gradual rollout

---

## 🔗 Related Documents

1. **ISSUE_5402_FINAL_DESIGN_V2.md** - Complete technical design
2. **ISSUE_5402_APPROACH_COMPARISON_V2.md** - Why UUID approach was chosen
3. **ISSUE_5402_SUMMARY_V2.md** - Executive summary
4. **ISSUE_5402_MIGRATION_GUIDE.md** - Step-by-step migration guide

---

## ❓ Questions or Issues?

- GitHub Issue: #5402
- Slack: #vault-migration
- Architect: madhav165
- Documentation: See related documents above

---

**Last Updated**: 2026-07-02  
**Status**: Ready for implementation  
**Approach**: VirtualServer UUID with self-describing credentials
