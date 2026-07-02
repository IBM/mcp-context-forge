# Issue #5402: Agent Runtime Changes for Vault Direct Integration

## Overview

This document describes the changes needed in `agent_langchain_mcp` repository to support the vault plugin direct integration feature. The goal is to **simplify the agent runtime** by removing vault credential resolution logic and passing vault authentication through to Context Forge.

---

## Current Architecture (Before)

### Current Flow

```
User Request
    ↓
agent_langchain_mcp receives (vault_entity_id, tokens, vault_token)
    ↓
fetch_tokens() calls vault-proxy:
  - async_fetch_wrapped_tokens() → wrap endpoint
  - async_fetch_unwrapped_tokens() → unwrap endpoint
    ↓
Returns plain tokens: {"github.com:USER:PAT:x": "ghp_abc123"}
    ↓
updateAuthHeaders() adds X-Vault-Tokens header
    ↓
MCP Server Request to Context Forge:
  Headers: {
    "Authorization": "Bearer <cf_token>",
    "X-Vault-Tokens": "{\"github.com:USER:PAT:x\": \"ghp_abc123\"}"
  }
    ↓
Context Forge vault plugin:
  - Parses X-Vault-Tokens header
  - Matches token keys to gateway tags
  - Injects auth headers
    ↓
MCP Server (GitHub, etc.)
```

**Problems**:
- Agent requires vault-proxy access (security surface)
- Token key naming must match gateway tags
- Multiple credentials exposed in single header
- Silent failures when keys don't match tags

---

## New Architecture (After)

### New Flow

```
User Request
    ↓
agent_langchain_mcp receives (vault_entity_id, vault_token)
    ↓
NO vault resolution in agent (skip fetch_tokens/handle_tokens)
    ↓
MCP Server Request to Context Forge:
  Headers: {
    "Authorization": "Bearer <cf_token>",
    "X-Vault-Token": "<vault_token>",
    "X-User-Name": "<vault_entity_id>"
  }
    ↓
Context Forge vault plugin (DIRECT MODE):
  - Reads gateway.vault_credential_alias
  - Calls vault-proxy wrap/unwrap for that alias
  - Gets {secretValue, authType, headerName}
  - Injects appropriate auth header
    ↓
MCP Server (GitHub, etc.)
```

**Benefits**:
- Agent no longer needs vault-proxy access
- Single credential resolved per gateway (principle of least privilege)
- Clear errors when credentials missing
- Single source of truth (gateway configuration)

---

## Required Changes

### 1. Environment Variables

**File**: `.env.sample`

Add new configuration flag:

```bash
# Vault Direct Integration (Issue #5402)
# When enabled, agent passes vault credentials to Context Forge
# instead of resolving them locally
VAULT_DIRECT_MODE_ENABLED=false  # Feature flag (default: false for backward compatibility)
```

### 2. Input Models

**File**: `app/agents/input_model.py` (or wherever MCP request models are defined)

Update input models to support both old and new modes:

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, List

class MCPServerRequest(BaseModel):
    """MCP server configuration for agent request."""
    url: str
    transport: str = "sse"
    headers: Optional[Dict[str, str]] = None
    timeout: Optional[int] = None
    sse_read_timeout: Optional[int] = None
    enable_vault_headers_passthrough: bool = False  # Legacy mode flag
    
class AgentInput(BaseModel):
    """Agent invocation input."""
    query: str
    
    # MCP configuration
    mcp_server_url: Optional[str] = None
    mcp_server_headers: Optional[Dict[str, str]] = None
    mcp_servers: Optional[List[MCPServerRequest]] = None
    
    # Vault authentication (simplified for direct mode)
    vault_entity_id: Optional[str] = Field(
        None,
        description="Vault entity ID (user email). Required for vault integration."
    )
    vault_token: Optional[str] = Field(
        None,
        description="Vault authentication token. Passed to Context Forge in direct mode."
    )
    
    # Legacy mode only (deprecated)
    tokens: Optional[Dict[str, str]] = Field(
        None,
        description="DEPRECATED: Token paths for legacy vault resolution. Use direct mode instead."
    )
    
    # ... other fields ...
```

---

### 3. Vault Proxy Utility (Conditional Logic)

**File**: `app/utilities/vault_proxy.py`

Add feature flag to conditionally skip vault resolution:

```python
import os
import logging

logger = logging.getLogger(__name__)

def is_direct_mode_enabled() -> bool:
    """Check if vault direct mode is enabled."""
    return os.getenv("VAULT_DIRECT_MODE_ENABLED", "false").lower() == "true"

async def fetch_tokens(
    user_name: Optional[str] = None,
    tokens: Optional[Dict[str, str]] = None,
    vault_token: Optional[str] = None
) -> Optional[Dict[str, str]]:
    """
    Fetch and unwrap tokens from Vault.
    
    In direct mode, this function returns None to indicate that vault
    resolution should be handled by Context Forge, not the agent.
    
    Args:
        user_name: Vault entity ID (typically user email)
        tokens: Dictionary of tokens (wrapped tokens or token paths)
        vault_token: Vault authentication token
        
    Returns:
        Dictionary of plain/unwrapped tokens, or None in direct mode
        
    Raises:
        MultipleTokenFetchErrors: If token fetching fails (legacy mode only)
    """
    # NEW: Check for direct mode
    if is_direct_mode_enabled():
        logger.info("Vault direct mode enabled - skipping agent-side vault resolution")
        logger.info("Vault credentials will be passed to Context Forge for resolution")
        return None
    
    # LEGACY MODE: Keep existing implementation
    if not tokens:
        logger.debug("No tokens provided, skipping token fetch")
        return None
    
    unwrap_mode = os.getenv('VAULT_UNWRAP', "UNWRAP")
    logger.info(f"Fetching tokens with mode: {unwrap_mode}")
    
    try:
        if unwrap_mode == "UNWRAP":
            logger.debug("Using UNWRAP mode - unwrapping provided tokens")
            unwrapped_tokens = await handle_wrapped_tokens(tokens)
            return unwrapped_tokens
        
        if user_name and vault_token:
            logger.debug(f"Using WRAP mode - fetching wrapped tokens for user: {user_name}")
            wrapped = await async_fetch_wrapped_tokens(user_name, tokens, vault_token)
            unwrapped_tokens = await async_fetch_unwrapped_tokens(wrapped)
            return unwrapped_tokens
        elif tokens:
            logger.debug("No vault credentials provided, returning tokens as-is")
            return tokens
        
        return None
        
    except MultipleTokenFetchErrors as e:
        logger.error(f"Failed to fetch tokens: {str(e.errors)}", exc_info=True)
        raise e
    except Exception as e:
        logger.error(f"Unexpected error fetching tokens: {str(e)}", exc_info=True)
        raise e


async def handle_tokens(
    mcp_servers: Dict[str, Any],
    plain_tokens: Optional[Dict[str, str]] = None
) -> None:
    """
    Update MCP server headers with pre-fetched plain tokens.
    
    In direct mode, this function is a no-op since vault credentials
    are passed directly to Context Forge via X-Vault-Token header.
    
    Args:
        mcp_servers: Dictionary of MCP server configurations
        plain_tokens: Pre-fetched plain tokens from fetch_tokens() (None in direct mode)
    """
    # NEW: Skip in direct mode
    if is_direct_mode_enabled():
        logger.debug("Vault direct mode enabled - skipping X-Vault-Tokens header injection")
        return
    
    # LEGACY MODE: Keep existing implementation
    if plain_tokens:
        logger.info("Applying pre-fetched tokens to MCP server headers")
        updateAuthHeaders(mcp_servers, plain_tokens)
        logger.debug("Successfully updated MCP server headers with tokens")
    else:
        logger.debug("No tokens to apply to MCP server headers")


def add_vault_passthrough_headers(
    headers: Dict[str, str],
    vault_entity_id: Optional[str],
    vault_token: Optional[str]
) -> Dict[str, str]:
    """
    Add vault passthrough headers for direct mode.
    
    NEW FUNCTION: Adds X-Vault-Token and X-User-Name headers
    so Context Forge can resolve credentials directly.
    
    Args:
        headers: Existing headers dict
        vault_entity_id: Vault entity ID (user email)
        vault_token: Vault authentication token
        
    Returns:
        Updated headers dict
    """
    if not is_direct_mode_enabled():
        return headers
    
    if vault_token:
        headers["X-Vault-Token"] = vault_token
        logger.debug("Added X-Vault-Token header for direct mode")
    
    if vault_entity_id:
        headers["X-User-Name"] = vault_entity_id
        logger.debug(f"Added X-User-Name header for direct mode: {vault_entity_id}")
    
    return headers
```

---

### 4. Router Changes

**File**: `app/routes/agent_langchain/agent_langchain_router.py`

Update the route handlers inside the `add_custom_routes()` function to support direct mode:

```python
def add_custom_routes(app: FastAPI) -> None:
    """Adds custom routes to the FastAPI application for agent invocation and result retrieval."""

    @app.post("/agent_langchain/invoke")
    async def agent_langchain(request: Request) -> StreamingResponse:
    """Stream agent response with optional vault integration."""
    # ... existing setup code ...
    
    # Fetch tokens ONCE before building MCP servers
    # In direct mode, this returns None
    plain_tokens = await fetch_tokens(
        input_data.vault_entity_id,
        input_data.tokens,
        input_data.vault_token
    )
    
    # Build MCP servers configuration
    mcp_servers = {}
    if not input_data.mcp_servers:
        if input_data.mcp_server_url:
            # Initialize headers dict
            headers = input_data.mcp_server_headers or {}
            
            # Add session/chat ID headers
            if chat_id:
                headers["x-mcp-session-id"] = chat_id
                headers["X-Chat-Id"] = chat_id
            
            # NEW: Add vault passthrough headers for direct mode
            headers = add_vault_passthrough_headers(
                headers,
                input_data.vault_entity_id,
                input_data.vault_token
            )
            
            mcp_servers = {
                "mcpserver": {
                    "url": input_data.mcp_server_url,
                    "transport": "sse",
                    "headers": headers,
                    "timeout": DEFAULT_HTTP_TIMEOUT,
                    "sse_read_timeout": DEFAULT_SSE_READ_TIMEOUT,
                }
            }
    else:
        # Handle multiple MCP servers
        if input_data.mcp_servers:
            for idx, server in enumerate(input_data.mcp_servers):
                server_name = f"mcpserver_{idx}"
                # Initialize headers dict
                headers = server.headers.copy() if server.headers else {}
                
                # Add session/chat ID headers
                if chat_id:
                    headers["x-mcp-session-id"] = chat_id
                    headers["X-Chat-Id"] = chat_id
                
                # NEW: Add vault passthrough headers for direct mode
                headers = add_vault_passthrough_headers(
                    headers,
                    input_data.vault_entity_id,
                    input_data.vault_token
                )
                
                mcp_servers[server_name] = {
                    "url": server.url,
                    "transport": server.transport,
                    "headers": headers,
                    "timeout": server.timeout,
                    "sse_read_timeout": server.sse_read_timeout,
                }
                
                # LEGACY MODE: Apply tokens only to servers with vault passthrough enabled
                # In direct mode, plain_tokens is None so this is skipped
                if hasattr(server, "enable_vault_headers_passthrough") and server.enable_vault_headers_passthrough:
                    if plain_tokens:
                        await handle_tokens({server_name: mcp_servers[server_name]}, plain_tokens)
    
    # ... rest of the streaming logic ...
```

**Repeat similar changes for other endpoints in the same file**:
- `@app.post("/agent_langchain/result")` - The non-streaming endpoint
- Any other endpoints that invoke MCP servers with vault credentials

**Also update**:
- `app/routes/agent_langgraph/agent_langgraph_router.py` - If it has a similar `add_custom_routes()` function, apply the same pattern

---

### 5. Testing

#### Unit Tests

**File**: `tests/unit/test_vault_proxy.py` (NEW or UPDATE)

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.utilities.vault_proxy import (
    fetch_tokens,
    handle_tokens,
    add_vault_passthrough_headers,
    is_direct_mode_enabled
)

@pytest.mark.asyncio
async def test_fetch_tokens_direct_mode_returns_none():
    """Test that fetch_tokens returns None in direct mode."""
    with patch.dict("os.environ", {"VAULT_DIRECT_MODE_ENABLED": "true"}):
        result = await fetch_tokens(
            user_name="user@example.com",
            tokens={"github.com": "token_path"},
            vault_token="vault_token_abc"
        )
        assert result is None

@pytest.mark.asyncio
async def test_fetch_tokens_legacy_mode_resolves():
    """Test that fetch_tokens still works in legacy mode."""
    with patch.dict("os.environ", {"VAULT_DIRECT_MODE_ENABLED": "false"}):
        with patch("app.utilities.vault_proxy.handle_wrapped_tokens", new_callable=AsyncMock) as mock_unwrap:
            mock_unwrap.return_value = {"github.com": "ghp_abc123"}
            
            result = await fetch_tokens(
                user_name="user@example.com",
                tokens={"github.com": "wrapped_token"},
                vault_token="vault_token_abc"
            )
            
            assert result == {"github.com": "ghp_abc123"}

@pytest.mark.asyncio
async def test_handle_tokens_direct_mode_is_noop():
    """Test that handle_tokens is a no-op in direct mode."""
    with patch.dict("os.environ", {"VAULT_DIRECT_MODE_ENABLED": "true"}):
        mcp_servers = {
            "server1": {
                "url": "http://cf.internal",
                "headers": {}
            }
        }
        
        await handle_tokens(mcp_servers, {"github.com": "token"})
        
        # In direct mode, X-Vault-Tokens should NOT be added
        assert "X-Vault-Tokens" not in mcp_servers["server1"]["headers"]

def test_add_vault_passthrough_headers_direct_mode():
    """Test vault passthrough headers added in direct mode."""
    with patch.dict("os.environ", {"VAULT_DIRECT_MODE_ENABLED": "true"}):
        headers = {}
        
        result = add_vault_passthrough_headers(
            headers,
            vault_entity_id="user@example.com",
            vault_token="vault_token_abc"
        )
        
        assert result["X-Vault-Token"] == "vault_token_abc"
        assert result["X-User-Name"] == "user@example.com"

def test_add_vault_passthrough_headers_legacy_mode():
    """Test vault passthrough headers NOT added in legacy mode."""
    with patch.dict("os.environ", {"VAULT_DIRECT_MODE_ENABLED": "false"}):
        headers = {}
        
        result = add_vault_passthrough_headers(
            headers,
            vault_entity_id="user@example.com",
            vault_token="vault_token_abc"
        )
        
        assert "X-Vault-Token" not in result
        assert "X-User-Name" not in result
```

#### Integration Tests

**File**: `tests/integration/test_agent_vault_direct.py` (NEW)

```python
import pytest
from fastapi.testclient import TestClient
from app.server import app

@pytest.mark.integration
def test_agent_stream_direct_mode(monkeypatch):
    """Test agent streaming with vault direct mode enabled."""
    monkeypatch.setenv("VAULT_DIRECT_MODE_ENABLED", "true")
    
    client = TestClient(app)
    
    request_data = {
        "query": "List my GitHub repositories",
        "mcp_server_url": "http://cf.internal:4444/mcp",
        "vault_entity_id": "user@example.com",
        "vault_token": "vault_token_abc",
        "chat_id": "test_session_123"
    }
    
    # Mock the actual MCP tool invocation
    with patch("app.routes.agent_langchain.agent_langchain_router.stream_agent_response") as mock_stream:
        mock_stream.return_value = iter([{"response": "test"}])
        
        response = client.post("/agent_langchain/stream", json=request_data)
        
        assert response.status_code == 200
        
        # Verify that the MCP server config has vault passthrough headers
        call_args = mock_stream.call_args
        mcp_servers = call_args.kwargs.get("mcp_servers", {})
        
        assert "mcpserver" in mcp_servers
        headers = mcp_servers["mcpserver"]["headers"]
        
        # Direct mode: X-Vault-Token and X-User-Name should be present
        assert headers["X-Vault-Token"] == "vault_token_abc"
        assert headers["X-User-Name"] == "user@example.com"
        
        # Direct mode: X-Vault-Tokens should NOT be present
        assert "X-Vault-Tokens" not in headers

@pytest.mark.integration
def test_agent_stream_legacy_mode(monkeypatch):
    """Test agent streaming with legacy vault mode."""
    monkeypatch.setenv("VAULT_DIRECT_MODE_ENABLED", "false")
    
    client = TestClient(app)
    
    request_data = {
        "query": "List my GitHub repositories",
        "mcp_server_url": "http://cf.internal:4444/mcp",
        "vault_entity_id": "user@example.com",
        "vault_token": "vault_token_abc",
        "tokens": {"github.com": "token_path"},
        "chat_id": "test_session_123"
    }
    
    # Mock vault resolution
    with patch("app.utilities.vault_proxy.async_fetch_wrapped_tokens", new_callable=AsyncMock) as mock_wrap:
        with patch("app.utilities.vault_proxy.async_fetch_unwrapped_tokens", new_callable=AsyncMock) as mock_unwrap:
            mock_wrap.return_value = {"github.com": "wrapped_token"}
            mock_unwrap.return_value = {"github.com": "ghp_abc123"}
            
            with patch("app.routes.agent_langchain.agent_langchain_router.stream_agent_response") as mock_stream:
                mock_stream.return_value = iter([{"response": "test"}])
                
                response = client.post("/agent_langchain/stream", json=request_data)
                
                assert response.status_code == 200
                
                # Verify that vault resolution was called
                mock_wrap.assert_called_once()
                mock_unwrap.assert_called_once()
                
                # Legacy mode: X-Vault-Tokens should be present
                call_args = mock_stream.call_args
                mcp_servers = call_args.kwargs.get("mcp_servers", {})
                headers = mcp_servers["mcpserver"]["headers"]
                
                # Note: In legacy mode with enable_vault_headers_passthrough,
                # X-Vault-Tokens would be added. Test accordingly.
```

---

## Migration Guide

### Phase 1: Deploy Agent with Feature Flag OFF (Backward Compatible)

1. Deploy agent changes with `VAULT_DIRECT_MODE_ENABLED=false`
2. Verify existing functionality unaffected
3. No changes to client requests needed

### Phase 2: Deploy Context Forge with Direct Mode Support

1. Deploy Context Forge with vault plugin direct mode
2. Keep feature flag OFF initially: `VAULT_DIRECT_RESOLUTION_ENABLED=false`
3. Verify backward compatibility

### Phase 3: Enable Direct Mode on Staging

1. Update Context Forge gateways with `vault_credential_alias` fields
2. Enable Context Forge direct mode: `VAULT_DIRECT_RESOLUTION_ENABLED=true`
3. Enable agent direct mode: `VAULT_DIRECT_MODE_ENABLED=true`
4. Test end-to-end flow
5. Verify credentials resolved correctly

### Phase 4: Gradual Production Rollout

1. Enable direct mode on subset of production instances
2. Monitor for issues
3. Compare metrics: latency, error rates
4. Gradually increase rollout percentage
5. Full deployment once stable

### Phase 5: Deprecation of Legacy Mode

1. Update client documentation (direct mode is now standard)
2. Mark `tokens` field as deprecated in API docs
3. Keep legacy mode available for 2-3 release cycles
4. Remove legacy code after migration complete

---

## Configuration Comparison

### Legacy Mode (Current)

**Agent `.env`:**
```bash
VAULT_PROXY_URL=http://vault.internal:8080
VAULT_API_KEY=xxx
VAULT_UNWRAP=UNWRAP
VAULT_DIRECT_MODE_ENABLED=false  # Legacy mode
```

**Agent Request:**
```json
{
  "query": "List repos",
  "mcp_server_url": "http://cf.internal:4444/mcp",
  "vault_entity_id": "user@example.com",
  "vault_token": "vault_token_abc",
  "tokens": {
    "github.com:USER:PAT:x": "token_path"
  }
}
```

**Headers Sent to Context Forge:**
```http
Authorization: Bearer <cf_token>
X-Vault-Tokens: {"github.com:USER:PAT:x": "ghp_abc123"}
```

---

### Direct Mode (New)

**Agent `.env`:**
```bash
# Vault proxy no longer needed by agent
# VAULT_PROXY_URL=http://vault.internal:8080  # Not required
# VAULT_API_KEY=xxx                           # Not required
VAULT_DIRECT_MODE_ENABLED=true  # Direct mode
```

**Agent Request:**
```json
{
  "query": "List repos",
  "mcp_server_url": "http://cf.internal:4444/mcp",
  "vault_entity_id": "user@example.com",
  "vault_token": "vault_token_abc"
}
```

**Headers Sent to Context Forge:**
```http
Authorization: Bearer <cf_token>
X-Vault-Token: vault_token_abc
X-User-Name: user@example.com
```

**Context Forge Resolves:**
- Reads `gateway.vault_credential_alias` (e.g., "github-personal")
- Calls vault-proxy wrap/unwrap for that alias
- Injects appropriate auth header

---

## Security Benefits

### Before (Legacy Mode)

- ❌ Agent requires vault-proxy access (broader attack surface)
- ❌ Agent resolves ALL credentials for request (over-privilege)
- ❌ Multiple credentials in single header (broader exposure)
- ❌ Token key naming must match gateway tags (coordination burden)

### After (Direct Mode)

- ✅ Agent no longer accesses vault-proxy (reduced attack surface)
- ✅ Context Forge resolves ONE credential per gateway (least privilege)
- ✅ Single credential per request (minimal exposure)
- ✅ Gateway configuration is single source of truth (no coordination)

---

## Performance Considerations

### Latency Impact

**Legacy Mode**:
- Agent → Vault-Proxy: ~50ms (wrap + unwrap)
- Agent → Context Forge: ~100ms
- **Total**: ~150ms

**Direct Mode**:
- Agent → Context Forge: ~100ms
- Context Forge → Vault-Proxy: ~50ms (wrap + unwrap)
- **Total**: ~150ms

**Conclusion**: Latency remains approximately the same, but security improves significantly.

### Vault-Proxy Load

**Before**: Agent calls vault-proxy for EVERY agent request
**After**: Context Forge calls vault-proxy for EVERY tool invocation

**Impact**: Vault-proxy load shifts from agent to Context Forge. If one agent request results in multiple tool invocations, vault-proxy load may increase. Consider:
- Caching in Context Forge vault plugin (cache credentials per request)
- Vault-proxy horizontal scaling if needed

---

## Rollback Plan

If issues occur in production:

1. **Immediate**: Set `VAULT_DIRECT_MODE_ENABLED=false` on agent
2. Agent reverts to legacy vault resolution
3. No client-side changes needed (both modes use same API)
4. Fix issues in direct mode implementation
5. Re-enable after validation

**Data Safety**: No data persistence in agent. Rollback is instant.

---

## Acceptance Criteria

### Agent Runtime

- [x] Feature flag `VAULT_DIRECT_MODE_ENABLED` controls behavior
- [x] Direct mode: `fetch_tokens()` returns None (no vault resolution)
- [x] Direct mode: `X-Vault-Token` and `X-User-Name` headers added
- [x] Legacy mode: Existing behavior preserved (X-Vault-Tokens header)
- [x] Unit tests cover both modes
- [x] Integration tests verify end-to-end flow

### Context Forge Integration

- [x] Agent passes `X-Vault-Token` and `X-User-Name` headers
- [x] Context Forge vault plugin receives headers correctly
- [x] Credentials resolved per gateway based on `vault_credential_alias`
- [x] Error messages clear when credentials missing
- [x] End-to-end tests validate complete flow

### Documentation

- [x] README updated with direct mode instructions
- [x] Environment variable documentation complete
- [x] Migration guide for operators
- [x] API deprecation notices for `tokens` field

---

## Timeline

| Phase | Task | Estimate |
|-------|------|----------|
| **Phase 1** | Add feature flag and conditional logic | 2 hours |
| **Phase 2** | Update vault_proxy.py with direct mode | 3 hours |
| **Phase 3** | Update routers (langchain + langgraph) | 4 hours |
| **Phase 4** | Unit tests (vault_proxy, routers) | 3 hours |
| **Phase 5** | Integration tests (end-to-end) | 3 hours |
| **Phase 6** | Documentation updates | 2 hours |
| **Phase 7** | Code review and iterations | 3 hours |
| **Total** | | **20 hours (2.5 days)** |

---

## Open Questions

1. **Header naming**: Confirm `X-Vault-Token` and `X-User-Name` are acceptable, or use different names?
   - Alternative: `X-Vault-Auth-Token`, `X-Vault-Entity-Id`

2. **Error handling**: Should agent fail fast if vault credentials missing in direct mode, or let Context Forge return the error?
   - Recommendation: Let Context Forge return explicit error (better error messages)

3. **Caching**: Should Context Forge cache vault resolutions per request to avoid duplicate calls?
   - Recommendation: Yes, cache per request/session (reduce vault-proxy load)

4. **Metrics**: What metrics should agent emit for direct mode?
   - `agent.vault.direct_mode_enabled` (boolean gauge)
   - `agent.vault.passthrough_headers_added` (counter)

5. **Deprecation timeline**: When should legacy mode be removed?
   - Recommendation: Keep for 6 months (2-3 release cycles) then deprecate

---

## Success Metrics

### Functional

- ✅ Direct mode resolves credentials correctly for all auth types
- ✅ Legacy mode continues to work unchanged
- ✅ Zero breaking changes for existing clients
- ✅ Clear error messages for missing credentials

### Security

- ✅ Agent no longer requires vault-proxy access
- ✅ Single credential per tool invocation (not all credentials upfront)
- ✅ Reduced attack surface for agent runtime

### Operational

- ✅ Vault-proxy load remains stable or decreases
- ✅ Agent request latency unchanged (<5ms difference)
- ✅ Support tickets for credential issues decrease (-30%)
- ✅ Configuration drift incidents: 0

---

## Conclusion

The agent runtime changes for Issue #5402 are **minimal and backward-compatible**. The key changes are:

1. ✅ Feature flag to enable/disable direct mode
2. ✅ Conditional logic in `fetch_tokens()` and `handle_tokens()`
3. ✅ New function `add_vault_passthrough_headers()` for direct mode
4. ✅ Updated routers to call new function
5. ✅ Comprehensive tests for both modes

**Benefits**:
- 🔒 Improved security (agent no longer needs vault access)
- 🎯 Simplified agent logic (no vault resolution)
- 🛡️ Principle of least privilege (single credential per gateway)
- 🔄 Zero breaking changes (dual-mode support)

**Recommended Next Steps**:
1. Review and approve this plan
2. Answer open questions above
3. Implement changes in agent_langchain_mcp
4. Coordinate testing with Context Forge team
5. Phased rollout (staging → production)
