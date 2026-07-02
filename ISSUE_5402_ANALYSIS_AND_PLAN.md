# Issue #5402: Vault Plugin Direct Integration - Analysis & Implementation Plan

## Executive Summary

**Goal**: Eliminate the fragile tag-based credential injection system by enabling the vault plugin to resolve credentials directly from vault-proxy per MCP server.

**Current State**: Credentials are resolved in the agent runtime, requiring manual coordination across three configuration points (token key naming, gateway tags, auth header tags).

**Target State**: The vault plugin calls vault-proxy directly using a `vault_credential_alias` field on each gateway, eliminating the dependency on tag-based matching and the `X-Vault-Tokens` header relay pattern.

---

## Problem Analysis

### The Fundamental Issue: Fragile Three-Way Coordination

The current system suffers from a **configuration coordination problem** that requires three separate string values to align perfectly:

#### 1. Agent Token Key Naming
```python
# In agent runtime - must follow convention
tokens = {
    "github.com:USER:PAT:x": "/path/to/credential"
    # ^^^^^^^^^ - this prefix must match gateway tag
}
```

#### 2. Gateway System Tag
```json
{
  "tags": [
    {"label": "system:github.com"}
    //               ^^^^^^^^^^^ - must match token key prefix
  ]
}
```

#### 3. Gateway Auth Header Tag
```json
{
  "tags": [
    {"label": "AUTH_HEADER:X-GitHub-Token"}
    //                     ^^^^^^^^^^^^^^ - must be correct header name
  ]
}
```

**The Problem**: These three values are:
- **Defined in different codebases** (agent vs. gateway config)
- **Have no validation relationship** (typos go undetected)
- **Use string parsing** (substring matching, prefix extraction)
- **Fail silently** (mismatch = no auth injected, tool proceeds unauthenticated)

### Why `vault_credential_alias` Solves This

The `vault_credential_alias` field **eliminates the coordination problem** by providing a direct reference:

```json
{
  "name": "GitHub MCP Server",
  "vault_credential_alias": "github-personal"
  // Direct vault reference - no parsing, no matching, no coordination
}
```

**How it works:**
1. **Gateway declares its credential need explicitly**: "I require vault credential `github-personal`"
2. **Vault plugin reads this field**: No tag parsing, no string matching
3. **Vault-proxy resolves credential**: Returns `{secretValue, authType, headerName}`
4. **Vault metadata is authoritative**: Vault tells us how to inject the credential

**Architectural benefits:**
- ✅ **Single source of truth**: Vault stores both credential and injection metadata
- ✅ **Explicit over implicit**: Direct reference, not convention-based matching
- ✅ **Fail-fast validation**: Missing alias = immediate error with credential name
- ✅ **No parsing logic**: Simple dictionary lookup by alias
- ✅ **Database-level validation**: Schema enforces max length, indexing, uniqueness

### Current Flow Issues (Detailed)

1. **Three coordination points** that can drift independently:
   - Token key naming in agent (e.g., `github.com:USER:PAT:x`)
   - Gateway `system:` tag (e.g., `system:github.com`)
   - Gateway `AUTH_HEADER:` tag (e.g., `AUTH_HEADER:X-GitHub-Token`)
   
   **Impact**: Any typo in any of these three strings causes silent authentication failure.

2. **Silent failure modes**:
   - Mismatched tags → tool calls proceed unauthenticated → HTTP 401 from MCP server → confusing user error
   - Missing `AUTH_HEADER` tag → wrong auth header used → HTTP 401 from MCP server
   - No clear error when credentials missing → users don't know what to fix
   
   **Root cause**: No validation that tags are correct until runtime, and even then failure is indirect.

3. **Security concerns**:
   - Agent runtime requires vault-proxy access (increases attack surface)
   - `X-Vault-Tokens` header passes multiple credentials (broader exposure if intercepted)
   - Credentials resolved upfront for all gateways (principle of least privilege violated)
   
   **With `vault_credential_alias`**: Agent doesn't need vault access, Context Forge resolves only the specific credential needed per gateway.

4. **Scalability issues**:
   - Manual coordination doesn't scale as MCP servers increase (3 config points × N servers)
   - No single source of truth for credential metadata (duplicated in tags and vault)
   - Documentation drift (README says one tag format, actual config uses another)
   
   **With `vault_credential_alias`**: One config point per gateway, vault is single source of truth.

### Current Flow Diagram

```
agent_langchain_mcp
    ↓
vault-proxy (wrap/unwrap)
    ↓
X-Vault-Tokens: {"github.com:USER:PAT:x": "ghp_abc"}
    ↓
Context Forge (vault plugin)
    ↓
Match token key → gateway "system:github.com" tag
Match AUTH_HEADER tag → "X-GitHub-Token"
    ↓
MCP Server (X-GitHub-Token: ghp_abc)
```

**Fragility**: Three string-matching operations that can silently fail.

---

## Proposed Solution

### New Flow Diagram

```
agent_langchain_mcp
    ↓
Context Forge (pass vault_token + user_name)
    ↓
Vault Plugin (tool_pre_invoke)
    ↓
Query gateway.vault_credential_alias
    ↓
Call vault-proxy wrap/unwrap for that alias
    ↓
{secretValue, authType, headerName} from vault
    ↓
Inject header based on vault metadata
    ↓
MCP Server (X-GitHub-Token: ghp_abc)
```

**Benefits**: Single source of truth (vault), no tag coordination, explicit errors.

---

## Implementation Plan

### Phase 1: Database Schema (Backward Compatible)

**File**: `mcpgateway/db.py`

#### Why This Field is Required: Architectural Justification

The `vault_credential_alias` field is the cornerstone of the direct integration approach. It serves as:

1. **Explicit Configuration**: Direct reference to vault credential, no convention-based parsing
2. **Single Source of Truth**: Vault stores both credential and injection metadata
3. **Validation Point**: Database schema enforces constraints, indexing enables fast lookup
4. **API Contract**: Field appears in Pydantic schemas, OpenAPI docs, admin UI

**Comparison:**

| Requirement | Tag-Based Approach | `vault_credential_alias` Approach |
|-------------|-------------------|-----------------------------------|
| Specify which credential to use | Parse `system:` tag prefix | Read `vault_credential_alias` field |
| Determine auth header name | Parse `AUTH_HEADER:` tag | Vault returns `headerName` metadata |
| Validation | Runtime string matching | Database schema + vault API |
| Error handling | Silent failure (no match) | Explicit error (404 from vault) |
| Configuration points | 2 tags per gateway | 1 field per gateway |
| Cross-system coordination | Agent + gateway tags must align | Gateway field → vault alias (direct) |

**Design decision:** Why a dedicated field instead of using tags?

- **Tags are unstructured**: Support arbitrary labels like `"env:prod"`, `"team:eng"` - not meant for credential references
- **Tags lack validation**: No schema enforcement, typos go undetected until runtime
- **Tags have no indexing**: Require full-table scan or JSON parsing for lookups
- **Tags mix concerns**: Same field used for filtering, categorization, AND credential references
- **Field is semantic**: Explicitly declares "this gateway needs this vault credential" - clear intent

Add new field to `Gateway` model:
```python
# Vault direct integration (Issue #5402)
# This field replaces tag-based credential matching with explicit vault reference.
# Architectural benefit: Single source of truth (vault) for both credential value
# and injection metadata (authType, headerName), eliminating three-way coordination
# between agent token keys, gateway system tags, and auth header tags.
vault_credential_alias: Mapped[Optional[str]] = mapped_column(
    String(255), 
    nullable=True,
    index=True,  # Enable fast lookup by credential alias
    comment="Vault credential alias for direct vault-proxy integration. When set, replaces tag-based system matching."
)
```

**Alembic Migration**: `mcpgateway/alembic/versions/YYYYMMDD_add_vault_credential_alias.py`

```python
"""add vault_credential_alias to gateways

Revision ID: <generated>
Revises: <current_head>
Create Date: 2026-07-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '<generated>'
down_revision = '<current_head>'  # MUST match output of `alembic heads`
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Add vault_credential_alias column to gateways table."""
    inspector = sa.inspect(op.get_bind())
    
    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "gateways" not in inspector.get_table_names():
        return
    
    # Skip if column already exists (idempotent)
    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "vault_credential_alias" in columns:
        return
    
    op.add_column(
        "gateways",
        sa.Column("vault_credential_alias", sa.String(255), nullable=True,
                  comment="Vault credential alias for direct vault-proxy integration")
    )
    
    # Optional: Add index for performance
    op.create_index(
        "ix_gateways_vault_credential_alias",
        "gateways",
        ["vault_credential_alias"],
        unique=False
    )

def downgrade() -> None:
    """Remove vault_credential_alias column from gateways table."""
    inspector = sa.inspect(op.get_bind())
    
    if "gateways" not in inspector.get_table_names():
        return
    
    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "vault_credential_alias" not in columns:
        return
    
    op.drop_index("ix_gateways_vault_credential_alias", table_name="gateways")
    op.drop_column("gateways", "vault_credential_alias")
```

**Pydantic Schemas**: `mcpgateway/schemas.py`

Add field to gateway schemas:
```python
class GatewayCreate(BaseModel):
    # ... existing fields ...
    vault_credential_alias: Optional[str] = Field(
        None,
        max_length=255,
        description="Vault credential alias for direct integration (replaces system: tags)"
    )

class GatewayUpdate(BaseModel):
    # ... existing fields ...
    vault_credential_alias: Optional[str] = Field(
        None,
        max_length=255,
        description="Vault credential alias for direct integration"
    )

class Gateway(BaseModel):
    # ... existing fields ...
    vault_credential_alias: Optional[str] = None
```

---

### Phase 2: Vault Proxy Client

**File**: `plugins/vault/vault_client.py` (NEW)

```python
# -*- coding: utf-8 -*-
"""Vault proxy client for direct credential resolution.

Location: ./plugins/vault/vault_client.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

from typing import Any, Dict, Optional
import httpx
from pydantic import BaseModel

class VaultCredential(BaseModel):
    """Vault credential with metadata."""
    secret_value: str
    auth_type: str  # "PAT", "OAUTH2", "JWT", "CUSTOM"
    header_name: Optional[str] = None  # e.g., "X-GitHub-Token" or None for Bearer

class VaultProxyError(Exception):
    """Base exception for vault proxy errors."""
    pass

class VaultNotFoundError(VaultProxyError):
    """Credential not found in vault."""
    pass

class VaultConnectionError(VaultProxyError):
    """Failed to connect to vault proxy."""
    pass

class VaultTimeoutError(VaultProxyError):
    """Vault proxy request timed out."""
    pass

class VaultProxyClient:
    """Client for vault-proxy wrap/unwrap operations."""
    
    def __init__(
        self,
        vault_url: str,
        timeout: float = 5.0,
        verify_ssl: bool = True
    ):
        """Initialize vault proxy client.
        
        Args:
            vault_url: Base URL of vault-proxy (e.g., "https://vault.internal")
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.vault_url = vault_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
    
    async def wrap_credential(
        self,
        owner: str,
        alias: str,
        vault_token: str
    ) -> str:
        """Wrap a credential (get wrapped token).
        
        Args:
            owner: Credential owner (user email or identifier)
            alias: Credential alias (e.g., "github-personal")
            vault_token: Vault authentication token
            
        Returns:
            Wrapped token string
            
        Raises:
            VaultNotFoundError: If credential not found
            VaultConnectionError: If connection fails
            VaultTimeoutError: If request times out
        """
        url = f"{self.vault_url}/api/secret/v1/wrap/{owner}/{alias}"
        headers = {"Authorization": f"Bearer {vault_token}"}
        
        try:
            async with httpx.AsyncClient(verify=self.verify_ssl, timeout=self.timeout) as client:
                response = await client.post(url, headers=headers)
                
                if response.status_code == 404:
                    raise VaultNotFoundError(
                        f"Credential not found: owner={owner}, alias={alias}"
                    )
                elif response.status_code == 401:
                    raise VaultProxyError("Vault authentication failed (invalid token)")
                elif response.status_code >= 500:
                    raise VaultConnectionError(
                        f"Vault proxy error: {response.status_code}"
                    )
                
                response.raise_for_status()
                data = response.json()
                return data.get("wrapped_token", "")
                
        except httpx.TimeoutException as e:
            raise VaultTimeoutError(f"Vault proxy timeout: {e}") from e
        except httpx.ConnectError as e:
            raise VaultConnectionError(f"Cannot connect to vault: {e}") from e
    
    async def unwrap_credential(
        self,
        wrapped_token: str,
        vault_token: str
    ) -> VaultCredential:
        """Unwrap a credential (resolve to plaintext with metadata).
        
        Args:
            wrapped_token: Wrapped token from wrap_credential
            vault_token: Vault authentication token
            
        Returns:
            VaultCredential with secret_value, auth_type, header_name
            
        Raises:
            VaultNotFoundError: If wrapped token invalid
            VaultConnectionError: If connection fails
            VaultTimeoutError: If request times out
        """
        url = f"{self.vault_url}/api/secret/v1/unwrap"
        headers = {
            "Authorization": f"Bearer {vault_token}",
            "Content-Type": "application/json"
        }
        payload = {"wrapped_token": wrapped_token}
        
        try:
            async with httpx.AsyncClient(verify=self.verify_ssl, timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
                
                if response.status_code == 404:
                    raise VaultNotFoundError("Invalid wrapped token")
                elif response.status_code == 401:
                    raise VaultProxyError("Vault authentication failed")
                elif response.status_code >= 500:
                    raise VaultConnectionError(
                        f"Vault proxy error: {response.status_code}"
                    )
                
                response.raise_for_status()
                data = response.json()
                
                return VaultCredential(
                    secret_value=data["secret_value"],
                    auth_type=data.get("auth_type", "PAT"),
                    header_name=data.get("header_name")
                )
                
        except httpx.TimeoutException as e:
            raise VaultTimeoutError(f"Vault proxy timeout: {e}") from e
        except httpx.ConnectError as e:
            raise VaultConnectionError(f"Cannot connect to vault: {e}") from e
    
    async def resolve_credential(
        self,
        owner: str,
        alias: str,
        vault_token: str
    ) -> VaultCredential:
        """One-step credential resolution (wrap + unwrap).
        
        Convenience method that combines wrap and unwrap operations.
        
        Args:
            owner: Credential owner
            alias: Credential alias
            vault_token: Vault authentication token
            
        Returns:
            VaultCredential with secret and metadata
            
        Raises:
            VaultNotFoundError: If credential not found
            VaultConnectionError: If connection fails
            VaultTimeoutError: If request times out
        """
        wrapped = await self.wrap_credential(owner, alias, vault_token)
        return await self.unwrap_credential(wrapped, vault_token)
```

---

### Phase 3: New Vault Direct Plugin (Separate from Legacy)

**ARCHITECTURAL DECISION**: Instead of modifying the existing vault plugin, create a **separate new plugin** for direct vault integration. This approach:
- ✅ Keeps existing vault plugin untouched (zero risk to current deployments)
- ✅ No feature flags needed (routing based on `vault_credential_alias` presence)
- ✅ Cleaner separation of concerns
- ✅ Easier testing and rollback

#### Plugin Routing Logic

**Automatic routing based on gateway configuration:**

```python
# In plugin framework or middleware
def select_vault_plugin(gateway):
    if gateway.vault_credential_alias:
        return "vault_direct"  # Use new direct integration plugin
    else:
        return "vault"          # Use existing tag-based plugin
```

**No configuration needed** - presence of `vault_credential_alias` field determines which plugin to use.

#### New Plugin: `vault_direct`

**File**: `plugins/vault_direct/vault_direct_plugin.py` (NEW)

**Config**:
```python
class VaultDirectConfig(BaseModel):
    """Configuration for vault_direct plugin."""
    vault_proxy_url: str = "http://localhost:8080"  # Vault proxy base URL
    vault_proxy_timeout: float = 5.0  # Request timeout in seconds
    verify_ssl: bool = True  # SSL verification
```

**Environment Variables** (add to `mcpgateway/config.py`):
```python
# Vault direct plugin settings
vault_proxy_url: str = Field(
    default="http://localhost:8080",
    description="Vault proxy base URL for direct integration"
)
vault_proxy_timeout: float = Field(
    default=5.0,
    description="Vault proxy request timeout in seconds"
)
```

**Plugin Implementation**:

```python
# -*- coding: utf-8 -*-
"""Vault direct plugin for direct vault-proxy credential resolution.

Location: ./plugins/vault_direct/vault_direct_plugin.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

from typing import Any, Dict, Optional
import logging
from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    HttpHeaderPayload
)
from pydantic import BaseModel, Field

from plugins.vault.vault_client import (
    VaultProxyClient,
    VaultCredential,
    VaultNotFoundError,
    VaultConnectionError,
    VaultTimeoutError
)

logger = logging.getLogger(__name__)


class VaultDirectConfig(BaseModel):
    """Configuration for vault_direct plugin."""
    vault_proxy_url: str = Field(
        default="http://localhost:8080",
        description="Vault proxy base URL"
    )
    vault_proxy_timeout: float = Field(
        default=5.0,
        description="Request timeout in seconds"
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates"
    )


class VaultDirect(Plugin):
    """Vault direct integration plugin.
    
    This plugin resolves credentials directly from vault-proxy using the
    gateway's vault_credential_alias field. It does NOT use tag-based matching.
    
    Flow:
    1. Read gateway.vault_credential_alias (e.g., "github-personal")
    2. Extract vault_token and user_name from request headers
    3. Call vault-proxy: resolve_credential(owner, alias, vault_token)
    4. Inject auth header based on vault metadata (authType, headerName)
    """
    
    def __init__(self, config: PluginConfig):
        super().__init__(config)
        try:
            self._config = VaultDirectConfig.model_validate(
                self._config.config or {}
            )
        except Exception:
            self._config = VaultDirectConfig()
        
        # Initialize vault proxy client
        self._vault_client = VaultProxyClient(
            vault_url=self._config.vault_proxy_url,
            timeout=self._config.vault_proxy_timeout,
            verify_ssl=self._config.verify_ssl
        )
        
        logger.info(
            "VaultDirect plugin initialized: url=%s, timeout=%s",
            self._config.vault_proxy_url,
            self._config.vault_proxy_timeout
        )
    
    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext
    ) -> ToolPreInvokeResult:
        """Resolve credential from vault and inject auth header."""
        
        # Extract gateway metadata
        gateway_metadata = context.global_context.metadata.get("gateway", {})
        vault_alias = gateway_metadata.get("vault_credential_alias")
        
        if not vault_alias:
            # This should not happen if routing is correct
            logger.warning(
                "VaultDirect plugin invoked but vault_credential_alias missing"
            )
            return ToolPreInvokeResult(modified_payload=None)
        
        logger.debug("Resolving credential for alias: %s", vault_alias)
        
        # Extract vault credentials from request context
        vault_token = context.global_context.metadata.get("vault_token")
        user_name = context.global_context.metadata.get("user_name")
        
        if not vault_token:
            logger.error("vault_token not provided in request")
            raise ValueError(
                "vault_token required for vault direct integration. "
                "Ensure agent passes X-Vault-Token header."
            )
        
        if not user_name:
            logger.error("user_name not provided in request")
            raise ValueError(
                "user_name required for vault direct integration. "
                "Ensure agent passes X-User-Name header."
            )
        
        # Resolve credential from vault-proxy
        try:
            credential = await self._vault_client.resolve_credential(
                owner=user_name,
                alias=vault_alias,
                vault_token=vault_token
            )
            logger.info(
                "Resolved credential: alias=%s, auth_type=%s, user=%s",
                vault_alias,
                credential.auth_type,
                user_name
            )
        except VaultNotFoundError:
            logger.error(
                "Credential not found: alias=%s, user=%s",
                vault_alias,
                user_name
            )
            raise ValueError(
                f"Credential '{vault_alias}' not found for user {user_name}. "
                f"Ensure credential exists in vault-proxy."
            )
        except VaultConnectionError as e:
            logger.error("Vault proxy connection error: %s", e)
            raise ValueError(f"Cannot connect to vault-proxy: {e}")
        except VaultTimeoutError as e:
            logger.error("Vault proxy timeout: %s", e)
            raise ValueError(f"Vault-proxy request timeout: {e}")
        
        # Inject credential based on auth type
        headers: dict[str, str] = (
            {k.lower(): v for k, v in payload.headers.root.items()}
            if payload.headers
            else {}
        )
        
        self._inject_auth_header(headers, credential)
        
        # Return modified payload
        modified_payload = payload.model_copy(
            update={"headers": HttpHeaderPayload(root=headers)}
        )
        return ToolPreInvokeResult(modified_payload=modified_payload)
    
    def _inject_auth_header(
        self,
        headers: dict[str, str],
        credential: VaultCredential
    ) -> None:
        """Inject authentication header based on credential type and metadata."""
        
        if credential.auth_type == "PAT":
            # Personal Access Token - use custom header if specified
            if credential.header_name:
                headers[credential.header_name.lower()] = credential.secret_value
                logger.debug("Injected PAT as %s", credential.header_name)
            else:
                headers["authorization"] = f"Bearer {credential.secret_value}"
                logger.debug("Injected PAT as Bearer token")
        
        elif credential.auth_type == "OAUTH2":
            # OAuth2 token - always Bearer
            headers["authorization"] = f"Bearer {credential.secret_value}"
            logger.debug("Injected OAuth2 Bearer token")
        
        elif credential.auth_type == "JWT":
            # JWT token - always Bearer
            headers["authorization"] = f"Bearer {credential.secret_value}"
            logger.debug("Injected JWT Bearer token")
        
        elif credential.auth_type == "BASIC":
            # Basic auth - value should be base64-encoded "user:pass"
            headers["authorization"] = f"Basic {credential.secret_value}"
            logger.debug("Injected Basic auth")
        
        elif credential.auth_type == "CUSTOM":
            # Custom auth - use header name from vault metadata
            if credential.header_name:
                headers[credential.header_name.lower()] = credential.secret_value
                logger.debug("Injected custom auth as %s", credential.header_name)
            else:
                # Fallback to Bearer if no header specified
                headers["authorization"] = f"Bearer {credential.secret_value}"
                logger.warning(
                    "CUSTOM auth type without header_name, falling back to Bearer"
                )
        
        else:
            # Unknown type - fallback to Bearer
            headers["authorization"] = f"Bearer {credential.secret_value}"
            logger.warning(
                "Unknown auth_type '%s', falling back to Bearer",
                credential.auth_type
            )
```

#### Plugin Registration

**File**: `plugins/vault_direct/__init__.py` (NEW)

```python
"""Vault direct integration plugin."""
from plugins.vault_direct.vault_direct_plugin import VaultDirect

__all__ = ["VaultDirect"]
```

**File**: `plugins/config.yaml`

```yaml
# Existing vault plugin (tag-based) - UNCHANGED
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
    vault_proxy_url: "${VAULT_PROXY_URL}"
    vault_proxy_timeout: 5.0
    verify_ssl: true
```

#### Routing Implementation

**File**: `mcpgateway/services/tool_service.py` or plugin middleware

```python
def select_plugins_for_gateway(gateway: Gateway) -> List[str]:
    """Determine which plugins to invoke for a gateway."""
    plugins = []
    
    # Vault plugin selection based on gateway configuration
    if gateway.vault_credential_alias:
        # Gateway has direct vault integration configured
        plugins.append("vault_direct")
    else:
        # Gateway uses legacy tag-based vault (or no vault)
        # Check if gateway has vault-related tags
        if any(tag.label.startswith("system:") for tag in gateway.tags):
            plugins.append("vault")
    
    # ... other plugin logic ...
    
    return plugins
```

---

### Phase 4: Gateway Service Updates

**File**: `mcpgateway/services/gateway_service.py`

Ensure CRUD operations handle the new `vault_credential_alias` field:

```python
class GatewayService:
    
    async def create_gateway(self, db: Session, gateway: GatewayCreate) -> Gateway:
        """Create gateway with vault_credential_alias support."""
        # ... existing logic ...
        db_gateway = Gateway(
            # ... existing fields ...
            vault_credential_alias=gateway.vault_credential_alias,
        )
        # ... rest of creation ...
    
    async def update_gateway(self, db: Session, gateway_id: str, gateway: GatewayUpdate) -> Gateway:
        """Update gateway with vault_credential_alias support."""
        # ... existing logic ...
        if gateway.vault_credential_alias is not None:
            db_gateway.vault_credential_alias = gateway.vault_credential_alias
        # ... rest of update ...
```

**File**: `mcpgateway/routers/gateway.py`

API endpoints automatically pick up the new field via Pydantic schemas.

---

### Phase 5: Agent Runtime Simplification

**Repository**: `agent_langchain_mcp` (external)

**Changes**:
1. Remove vault-proxy wrap/unwrap calls
2. Pass `vault_token` and `user_name` as headers (or standard method)
3. Remove `X-Vault-Tokens` header construction

**Before**:
```python
# Agent resolves credentials
vault_tokens = {}
for alias in required_aliases:
    secret = vault_client.wrap_unwrap(owner, alias)
    vault_tokens[f"{system}:USER:PAT:x"] = secret

headers = {
    "X-Vault-Tokens": json.dumps(vault_tokens),
    "Authorization": f"Bearer {cf_token}"
}
```

**After**:
```python
# Agent passes vault token through
headers = {
    "X-Vault-Token": vault_token,  # Or in Authorization if CF token not needed
    "X-User-Name": user_name,
    "Authorization": f"Bearer {cf_token}"
}
```

**Note**: This is a coordination change with the agent team. Document migration path.

---

## Configuration (No Feature Flags)

### Environment Variables

Add to `.env.example` and `mcpgateway/config.py`:

```bash
# Vault Direct Plugin - Direct Integration (Issue #5402)
VAULT_PROXY_URL=http://localhost:8080  # Vault proxy base URL
VAULT_PROXY_TIMEOUT=5.0                # Request timeout in seconds
```

**No feature flag needed** - routing is automatic based on `vault_credential_alias` presence.

### Plugin Configuration

Update `plugins/config.yaml`:

```yaml
# Existing vault plugin (tag-based) - UNCHANGED
vault:
  enabled: true
  config:
    system_tag_prefix: "system"
    vault_header_name: "X-Vault-Tokens"
    vault_handling: "raw"
    system_handling: "tag"
    auth_header_tag_prefix: "AUTH_HEADER"

# New vault_direct plugin (direct integration) - NEW
vault_direct:
  enabled: true
  config:
    vault_proxy_url: "${VAULT_PROXY_URL}"
    vault_proxy_timeout: 5.0
    verify_ssl: true
```

### Automatic Routing

**No configuration needed for routing** - the system automatically selects the correct plugin:

```python
# Automatic plugin selection
if gateway.vault_credential_alias:
    use_plugin("vault_direct")  # Direct integration
else:
    use_plugin("vault")          # Legacy tag-based
```

---

## Testing Strategy

### Unit Tests

**File**: `tests/unit/mcpgateway/plugins/plugins/vault/test_vault_client.py` (NEW)

```python
import pytest
from plugins.vault.vault_client import (
    VaultProxyClient,
    VaultCredential,
    VaultNotFoundError,
    VaultConnectionError,
    VaultTimeoutError
)

@pytest.mark.asyncio
async def test_wrap_credential_success(httpx_mock):
    """Test successful credential wrapping."""
    httpx_mock.add_response(
        url="http://vault/api/secret/v1/wrap/user@example.com/github-token",
        json={"wrapped_token": "wrapped_abc123"}
    )
    
    client = VaultProxyClient("http://vault")
    wrapped = await client.wrap_credential("user@example.com", "github-token", "vault_token")
    
    assert wrapped == "wrapped_abc123"

@pytest.mark.asyncio
async def test_wrap_credential_not_found(httpx_mock):
    """Test credential not found error."""
    httpx_mock.add_response(
        url="http://vault/api/secret/v1/wrap/user@example.com/missing",
        status_code=404
    )
    
    client = VaultProxyClient("http://vault")
    
    with pytest.raises(VaultNotFoundError, match="Credential not found"):
        await client.wrap_credential("user@example.com", "missing", "vault_token")

@pytest.mark.asyncio
async def test_unwrap_credential_pat_with_header(httpx_mock):
    """Test unwrapping PAT with custom header."""
    httpx_mock.add_response(
        url="http://vault/api/secret/v1/unwrap",
        json={
            "secret_value": "ghp_abc123",
            "auth_type": "PAT",
            "header_name": "X-GitHub-Token"
        }
    )
    
    client = VaultProxyClient("http://vault")
    cred = await client.unwrap_credential("wrapped_token", "vault_token")
    
    assert cred.secret_value == "ghp_abc123"
    assert cred.auth_type == "PAT"
    assert cred.header_name == "X-GitHub-Token"

@pytest.mark.asyncio
async def test_unwrap_credential_oauth2(httpx_mock):
    """Test unwrapping OAuth2 token."""
    httpx_mock.add_response(
        url="http://vault/api/secret/v1/unwrap",
        json={
            "secret_value": "ya29.abc123",
            "auth_type": "OAUTH2"
        }
    )
    
    client = VaultProxyClient("http://vault")
    cred = await client.unwrap_credential("wrapped_token", "vault_token")
    
    assert cred.secret_value == "ya29.abc123"
    assert cred.auth_type == "OAUTH2"
    assert cred.header_name is None

@pytest.mark.asyncio
async def test_resolve_credential_end_to_end(httpx_mock):
    """Test full wrap + unwrap flow."""
    httpx_mock.add_response(
        url="http://vault/api/secret/v1/wrap/user@example.com/github-token",
        json={"wrapped_token": "wrapped_abc"}
    )
    httpx_mock.add_response(
        url="http://vault/api/secret/v1/unwrap",
        json={
            "secret_value": "ghp_abc123",
            "auth_type": "PAT",
            "header_name": "X-GitHub-Token"
        }
    )
    
    client = VaultProxyClient("http://vault")
    cred = await client.resolve_credential("user@example.com", "github-token", "vault_token")
    
    assert cred.secret_value == "ghp_abc123"
    assert cred.auth_type == "PAT"
    assert cred.header_name == "X-GitHub-Token"

@pytest.mark.asyncio
async def test_connection_error(httpx_mock):
    """Test vault connection failure."""
    import httpx
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
    
    client = VaultProxyClient("http://vault")
    
    with pytest.raises(VaultConnectionError, match="Cannot connect to vault"):
        await client.wrap_credential("user@example.com", "token", "vault_token")

@pytest.mark.asyncio
async def test_timeout_error(httpx_mock):
    """Test vault request timeout."""
    import httpx
    httpx_mock.add_exception(httpx.TimeoutException("Request timed out"))
    
    client = VaultProxyClient("http://vault")
    
    with pytest.raises(VaultTimeoutError, match="Vault proxy timeout"):
        await client.wrap_credential("user@example.com", "token", "vault_token")
```

**File**: `tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin_direct.py` (NEW)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from plugins.vault.vault_plugin import Vault, VaultConfig
from plugins.vault.vault_client import VaultCredential, VaultNotFoundError
from cpex.framework import (
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    HttpHeaderPayload
)

@pytest.fixture
def direct_mode_config():
    """Vault plugin config with direct mode enabled."""
    return PluginConfig(
        id="vault",
        name="vault",
        enabled=True,
        config={
            "direct_mode_enabled": True,
            "vault_proxy_url": "http://vault.internal",
            "vault_proxy_timeout": 5.0
        }
    )

@pytest.fixture
def plugin_context():
    """Mock plugin context with vault credentials."""
    context = MagicMock(spec=PluginContext)
    context.global_context.metadata = {
        "gateway": {
            "vault_credential_alias": "github-personal"
        },
        "vault_token": "vault_token_abc",
        "user_name": "user@example.com"
    }
    context.global_context.server_id = "gateway_123"
    return context

@pytest.mark.asyncio
async def test_direct_mode_pat_with_custom_header(direct_mode_config, plugin_context):
    """Test direct mode with PAT and custom header."""
    plugin = Vault(direct_mode_config)
    
    # Mock vault client response
    mock_credential = VaultCredential(
        secret_value="ghp_abc123",
        auth_type="PAT",
        header_name="X-GitHub-Token"
    )
    
    with patch.object(plugin._vault_client, "resolve_credential", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = mock_credential
        
        payload = ToolPreInvokePayload(
            name="list-repos",
            arguments={},
            headers=HttpHeaderPayload(root={})
        )
        
        result = await plugin.tool_pre_invoke(payload, plugin_context)
        
        # Verify vault client called correctly
        mock_resolve.assert_called_once_with(
            owner="user@example.com",
            alias="github-personal",
            vault_token="vault_token_abc"
        )
        
        # Verify header injected correctly
        assert result.modified_payload is not None
        headers = result.modified_payload.headers.root
        assert headers["x-github-token"] == "ghp_abc123"
        assert "authorization" not in headers

@pytest.mark.asyncio
async def test_direct_mode_pat_without_custom_header(direct_mode_config, plugin_context):
    """Test direct mode with PAT but no custom header (fallback to Bearer)."""
    plugin = Vault(direct_mode_config)
    
    mock_credential = VaultCredential(
        secret_value="ghp_abc123",
        auth_type="PAT",
        header_name=None  # No custom header
    )
    
    with patch.object(plugin._vault_client, "resolve_credential", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = mock_credential
        
        payload = ToolPreInvokePayload(
            name="list-repos",
            arguments={},
            headers=HttpHeaderPayload(root={})
        )
        
        result = await plugin.tool_pre_invoke(payload, plugin_context)
        
        # Verify fallback to Bearer token
        assert result.modified_payload is not None
        headers = result.modified_payload.headers.root
        assert headers["authorization"] == "Bearer ghp_abc123"

@pytest.mark.asyncio
async def test_direct_mode_oauth2(direct_mode_config, plugin_context):
    """Test direct mode with OAuth2 token."""
    plugin = Vault(direct_mode_config)
    
    mock_credential = VaultCredential(
        secret_value="ya29.oauth_token",
        auth_type="OAUTH2",
        header_name=None
    )
    
    with patch.object(plugin._vault_client, "resolve_credential", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = mock_credential
        
        payload = ToolPreInvokePayload(
            name="list-repos",
            arguments={},
            headers=HttpHeaderPayload(root={})
        )
        
        result = await plugin.tool_pre_invoke(payload, plugin_context)
        
        # Verify OAuth2 Bearer token
        assert result.modified_payload is not None
        headers = result.modified_payload.headers.root
        assert headers["authorization"] == "Bearer ya29.oauth_token"

@pytest.mark.asyncio
async def test_direct_mode_credential_not_found(direct_mode_config, plugin_context):
    """Test direct mode when credential not found in vault."""
    plugin = Vault(direct_mode_config)
    
    with patch.object(plugin._vault_client, "resolve_credential", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = VaultNotFoundError("Credential not found")
        
        payload = ToolPreInvokePayload(
            name="list-repos",
            arguments={},
            headers=HttpHeaderPayload(root={})
        )
        
        with pytest.raises(ValueError, match="Credential not found"):
            await plugin.tool_pre_invoke(payload, plugin_context)

@pytest.mark.asyncio
async def test_direct_mode_missing_vault_token(direct_mode_config):
    """Test direct mode fails when vault_token not provided."""
    plugin = Vault(direct_mode_config)
    
    # Context missing vault_token
    context = MagicMock(spec=PluginContext)
    context.global_context.metadata = {
        "gateway": {"vault_credential_alias": "github-personal"},
        "user_name": "user@example.com"
        # vault_token missing
    }
    
    payload = ToolPreInvokePayload(
        name="list-repos",
        arguments={},
        headers=HttpHeaderPayload(root={})
    )
    
    with pytest.raises(ValueError, match="vault_token required"):
        await plugin.tool_pre_invoke(payload, context)

@pytest.mark.asyncio
async def test_direct_mode_missing_user_name(direct_mode_config):
    """Test direct mode fails when user_name not provided."""
    plugin = Vault(direct_mode_config)
    
    # Context missing user_name
    context = MagicMock(spec=PluginContext)
    context.global_context.metadata = {
        "gateway": {"vault_credential_alias": "github-personal"},
        "vault_token": "vault_token_abc"
        # user_name missing
    }
    
    payload = ToolPreInvokePayload(
        name="list-repos",
        arguments={},
        headers=HttpHeaderPayload(root={})
    )
    
    with pytest.raises(ValueError, match="user_name required"):
        await plugin.tool_pre_invoke(payload, context)
```

### Integration Tests

**File**: `tests/integration/test_vault_direct_integration.py` (NEW)

```python
import pytest
from fastapi.testclient import TestClient
from mcpgateway.main import app
from mcpgateway.db import SessionLocal
from tests.conftest import create_test_gateway, create_test_tool

@pytest.fixture
def vault_mock_server(httpx_mock):
    """Mock vault-proxy server."""
    # Mock wrap endpoint
    httpx_mock.add_response(
        url="http://vault.internal/api/secret/v1/wrap/user@example.com/github-token",
        json={"wrapped_token": "wrapped_abc"}
    )
    
    # Mock unwrap endpoint
    httpx_mock.add_response(
        url="http://vault.internal/api/secret/v1/unwrap",
        json={
            "secret_value": "ghp_integration_test",
            "auth_type": "PAT",
            "header_name": "X-GitHub-Token"
        }
    )

@pytest.mark.integration
def test_end_to_end_direct_vault(vault_mock_server):
    """Test complete flow: gateway creation → tool invocation → vault resolution."""
    client = TestClient(app)
    db = SessionLocal()
    
    try:
        # 1. Create gateway with vault_credential_alias
        gateway_data = {
            "name": "GitHub MCP",
            "url": "https://api.github.com/mcp/",
            "vault_credential_alias": "github-token",
            "transport": "SSE"
        }
        
        response = client.post("/gateways", json=gateway_data, headers={"Authorization": "Bearer test_token"})
        assert response.status_code == 201
        gateway = response.json()
        gateway_id = gateway["id"]
        
        # 2. Invoke tool with vault credentials
        tool_data = {
            "tool_name": "github-list-repos",
            "arguments": {"org": "myorg"}
        }
        
        headers = {
            "Authorization": "Bearer test_token",
            "X-Vault-Token": "vault_token_abc",
            "X-User-Name": "user@example.com"
        }
        
        # Mock the actual MCP tool invocation
        with patch("mcpgateway.services.tool_service.invoke_mcp_tool") as mock_invoke:
            mock_invoke.return_value = {"repos": []}
            
            response = client.post("/tools/invoke", json=tool_data, headers=headers)
            
            # 3. Verify vault resolution occurred and correct header sent
            assert response.status_code == 200
            
            # Verify the MCP tool was called with the resolved credential
            call_args = mock_invoke.call_args
            headers_sent = call_args[1]["headers"]
            assert "x-github-token" in headers_sent
            assert headers_sent["x-github-token"] == "ghp_integration_test"
    
    finally:
        db.close()
```

### Manual Testing Steps

#### 1. Setup

```bash
# Enable direct mode
export VAULT_DIRECT_RESOLUTION_ENABLED=true
export VAULT_PROXY_URL=http://localhost:8080

# Start services
make dev  # Start Context Forge
# Start vault-proxy separately

# Generate token
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret KEY)
```

#### 2. Create Gateway with Vault Alias

```bash
curl -X POST http://localhost:4444/gateways \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GitHub MCP Server",
    "url": "https://api.github.com/mcp/",
    "description": "GitHub MCP with direct vault integration",
    "transport": "SSE",
    "vault_credential_alias": "github-personal"
  }'
```

**Expected**: Gateway created with `vault_credential_alias` field populated.

#### 3. Store Credential in Vault

```bash
# Use vault-proxy UI or API to store credential
# alias: github-personal
# owner: user@example.com
# secret: ghp_YOUR_TOKEN
# auth_type: PAT
# header_name: X-GitHub-Token
```

#### 4. Invoke Tool (Direct Mode)

```bash
curl -X POST http://localhost:4444/tools/invoke \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "X-User-Name: user@example.com" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "github-list-repos",
    "arguments": {"org": "myorg"}
  }'
```

**Expected**: 
- Tool invoked successfully
- GitHub API receives `X-GitHub-Token: ghp_YOUR_TOKEN`
- No `X-Vault-Tokens` header in request

#### 5. Test Error Cases

**Missing Credential**:
```bash
curl -X POST http://localhost:4444/tools/invoke \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "X-User-Name: user@example.com" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "gitlab-list-projects",
    "arguments": {}
  }'
```

**Expected**: Clear error message "Credential not found: gitlab-personal for user user@example.com"

**Vault Unavailable**:
```bash
# Stop vault-proxy
# Retry tool invocation
```

**Expected**: Error "Vault proxy unavailable: Cannot connect to vault"

#### 6. Test Legacy Mode (Backward Compatibility)

```bash
# Disable direct mode
export VAULT_DIRECT_RESOLUTION_ENABLED=false

# Create gateway WITHOUT vault_credential_alias (uses tags)
curl -X POST http://localhost:4444/gateways \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Legacy GitHub",
    "url": "https://api.github.com/mcp/",
    "tags": [
      {"label": "system:github.com"},
      {"label": "AUTH_HEADER:X-GitHub-Token"}
    ]
  }'

# Invoke with X-Vault-Tokens header (old way)
curl -X POST http://localhost:4444/tools/invoke \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H 'X-Vault-Tokens: {"github.com:USER:PAT:x": "ghp_legacy_token"}' \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "legacy-github-list-repos",
    "arguments": {"org": "myorg"}
  }'
```

**Expected**: Legacy tag-based matching still works.

---

## Migration Guide

### For Platform Operators

#### Step 1: Feature Flag Rollout

1. Deploy new Context Forge version with feature flag OFF
2. Verify existing deployments unaffected (backward compatibility)
3. Enable feature flag: `VAULT_DIRECT_RESOLUTION_ENABLED=true`

#### Step 2: Gateway Migration

For each MCP server:

**Before (tag-based)**:
```json
{
  "name": "GitHub MCP",
  "url": "https://api.github.com/mcp/",
  "tags": [
    {"label": "system:github.com"},
    {"label": "AUTH_HEADER:X-GitHub-Token"}
  ]
}
```

**After (direct mode)**:
```json
{
  "name": "GitHub MCP",
  "url": "https://api.github.com/mcp/",
  "vault_credential_alias": "github-personal",
  "tags": []  // Tags no longer needed for vault
}
```

#### Step 3: Credential Storage

Ensure credentials in vault have metadata:
- `auth_type`: PAT, OAUTH2, JWT, or CUSTOM
- `header_name`: Custom header (optional, for PAT/CUSTOM)

#### Step 4: Agent Runtime Update

Coordinate with agent team to update `agent_langchain_mcp`:
- Remove vault-proxy wrap/unwrap calls
- Pass `vault_token` and `user_name` as headers
- Remove `X-Vault-Tokens` construction

#### Step 5: Validation

1. Test tool invocations in direct mode
2. Verify credentials resolved correctly
3. Check error messages for missing credentials
4. Monitor vault-proxy metrics for increased load

---

## Rollback Plan

If issues found in production:

1. **Immediate**: Set `VAULT_DIRECT_RESOLUTION_ENABLED=false`
2. System reverts to legacy tag-based mode
3. No data loss (both modes coexist)
4. Fix issues in direct mode implementation
5. Re-enable feature flag after validation

**Data Safety**: The `vault_credential_alias` field is additive (nullable). Rollback doesn't require schema migration.

---

## Success Metrics

### Functional Metrics

- ✅ Direct mode resolves credentials for all auth types (PAT, OAuth2, JWT, Custom)
- ✅ Error messages clear when credentials missing
- ✅ Legacy tag-based mode continues to work
- ✅ Zero silent failures (all errors explicit)

### Performance Metrics

- Vault-proxy latency: <100ms p95 for wrap/unwrap
- Tool invocation latency increase: <50ms p95 (vault call overhead)
- Agent runtime: No vault-proxy calls (reduced security surface)

### Operational Metrics

- Configuration drift incidents: 0 (single source of truth)
- Support tickets re: credential issues: -50% (clear errors)
- Time to add new MCP server: -60% (no tag coordination)

---

## Documentation Updates

### Files to Update

1. **`plugins/vault/README.md`**
   - Add "Direct Mode" section
   - Update configuration examples
   - Add migration guide

2. **`docs/plugins/vault.md`** (if exists)
   - Document new workflow
   - Add architecture diagrams
   - Link to migration guide

3. **`README.md`** (if vault mentioned)
   - Update overview to mention direct integration

4. **`CHANGELOG.md`**
   - Add entry for Issue #5402 feature

### New Documents

1. **`docs/vault-direct-migration.md`**
   - Step-by-step migration guide
   - Before/after comparisons
   - Troubleshooting common issues

2. **`docs/vault-architecture.md`**
   - Architecture diagrams
   - Sequence diagrams (direct vs legacy)
   - Decision flowchart

---

## Timeline Estimate

| Phase | Tasks | Estimate |
|-------|-------|----------|
| **Phase 1** | Database schema + migration | 2-3 hours |
| **Phase 2** | Vault client implementation | 4-6 hours |
| **Phase 3** | Plugin refactoring (dual mode) | 6-8 hours |
| **Phase 4** | Gateway service updates | 2-3 hours |
| **Phase 5** | Agent runtime coordination | 4-6 hours |
| **Testing** | Unit + integration + manual | 8-10 hours |
| **Documentation** | README, guides, diagrams | 4-6 hours |
| **Code Review** | PR reviews, iterations | 4-6 hours |
| **Total** | | **34-48 hours (5-6 days)** |

**Parallel Work Opportunities**:
- Phase 1-4 can be done independently
- Phase 5 (agent runtime) can be done by separate team
- Testing can overlap with development

---

## Questions & Decisions

### Open Questions

1. **Vault metadata format**: Does vault-proxy already return `{secret_value, auth_type, header_name}`? Or do we need to request this feature?

2. **Context passing**: What's the preferred method to pass `vault_token` and `user_name` from agent to Context Forge?
   - Option A: Request headers (`X-Vault-Token`, `X-User-Name`)
   - Option B: Auth context metadata
   - Option C: JWT claims

3. **Error handling**: Should missing credentials return 401 Unauthorized or 400 Bad Request?

4. **Caching**: Should we cache vault resolutions per request? (Avoid duplicate calls for same credential)

5. **Observability**: What metrics/traces should we emit for vault operations?

### Decisions Needed

- [ ] Approve dual-mode approach (direct + legacy coexist)
- [ ] Approve feature flag name and default (OFF initially)
- [ ] Approve vault client interface design
- [ ] Approve migration timeline and coordination with agent team
- [ ] Approve rollback strategy

---

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Vault-proxy unavailable | Tools fail | Medium | Timeout + clear error + fallback to legacy |
| Performance degradation | Slower requests | Low | Cache + monitoring + timeout tuning |
| Migration coordination | Agent/CF mismatch | Medium | Dual-mode support + phased rollout |
| Breaking changes | Existing deployments fail | Low | Feature flag OFF by default + backward compat |
| Credential metadata missing | Wrong auth header | Medium | Fallback to Bearer + document requirements |

---

## Appendix: Vault-Proxy API Reference

### Wrap Endpoint

```http
POST /api/secret/v1/wrap/{owner}/{alias}
Authorization: Bearer {vault_token}
```

**Response**:
```json
{
  "wrapped_token": "wrapped_abc123"
}
```

### Unwrap Endpoint

```http
POST /api/secret/v1/unwrap
Authorization: Bearer {vault_token}
Content-Type: application/json

{
  "wrapped_token": "wrapped_abc123"
}
```

**Response**:
```json
{
  "secret_value": "ghp_abc123",
  "auth_type": "PAT",
  "header_name": "X-GitHub-Token"
}
```

### Error Responses

- `404 Not Found`: Credential not found
- `401 Unauthorized`: Invalid vault token
- `500 Server Error`: Vault internal error

---

## Conclusion

This implementation plan provides a **complete, backward-compatible solution** to Issue #5402 by:

1. ✅ Eliminating tag-based credential matching
2. ✅ Providing clear error messages for missing credentials
3. ✅ Reducing security surface (agent no longer needs vault access)
4. ✅ Maintaining backward compatibility via dual-mode support
5. ✅ Enabling phased rollout with feature flag

The dual-mode approach ensures **zero risk to existing deployments** while providing a migration path to the more robust direct integration pattern.

**Recommended Next Steps**:
1. Review and approve this plan
2. Answer open questions above
3. Create implementation tasks
4. Begin Phase 1 (database schema) as it's non-breaking
5. Coordinate with agent team on Phase 5 timeline
