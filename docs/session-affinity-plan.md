# Plan: Bidirectional x-mcp-session-id Mapping via broadcast() → mcp_session_pool

## Problem Summary

The current implementation lacks proper session affinity between downstream SSE sessions and upstream MCP server sessions. The `mcp_session_pool` has only a placeholder for `x-mcp-session-id` usage.

**Current Flow:**
```
/rpc endpoint receives request with x-mcp-session-id header
  → broadcast(session_id, message) [knows session_id but doesn't link to pool]
  → respond() picks up message
  → generate_response() → HTTP /rpc
  → invoke_tool() → pool.acquire() [tries to use x-mcp-session-id but mapping not pre-set]
```

**What's Missing:**
- `broadcast()` should **pre-register** the session mapping in `mcp_session_pool`
- The message contains tool name → can lookup `tool.gateway` → get url, gateway_id, transport_type
- `acquire()` should then use this pre-registered mapping for session affinity

## Solution Overview

### Key Insight
`broadcast()` receives the RPC message which contains:
- `method`: e.g., "tools/call"
- `params.name`: tool name

From tool name → lookup tool → get `tool.gateway` → extract:
- `gateway.url`
- `gateway.id` (gateway_id)
- `gateway.transport_type`

This gives `broadcast()` everything needed to **pre-register** the mapping in `mcp_session_pool`.

### Flow After Fix
```
/rpc receives request with x-mcp-session-id
  → broadcast(session_id, message)
     → parse message to get tool name
     → lookup tool.gateway → get url, gateway_id, transport_type
     → mcp_session_pool.register_session_mapping(session_id, url, gateway_id, transport_type)
  → respond() → generate_response() → /rpc → invoke_tool()
  → pool.acquire(headers with x-mcp-session-id)
     → lookup pre-registered mapping
     → use mapped pool_key for session affinity
```

## Files to Modify

### 1. `mcpgateway/cache/session_registry.py`

**Modify `broadcast()` (~line 676) to pre-register session mapping:**
```python
async def broadcast(self, session_id: str, message: Dict[str, Any]) -> None:
    """Broadcast a message to a session."""

    # NEW: Pre-register session mapping for session affinity
    if settings.mcpgateway_session_affinity_enabled:
        await self._register_session_mapping(session_id, message)

    # ... existing broadcast logic ...
```

**Add new helper method `_register_session_mapping()`:**
```python
async def _register_session_mapping(self, session_id: str, message: Dict[str, Any]) -> None:
    """Pre-register session mapping in mcp_session_pool for session affinity.

    Parses the message to extract tool name, looks up tool.gateway,
    and registers mapping: (session_id, url, transport_type, gateway_id) → pool_key
    """
    try:
        method = message.get("method", "")
        params = message.get("params", {})

        if method == "tools/call":
            tool_name = params.get("name")
            if not tool_name:
                return

            # Look up tool and gateway
            from mcpgateway.services.tool_service import tool_service
            tool = await tool_service.get_tool_by_name(tool_name)  # Need to add/use existing method
            if not tool or not tool.gateway:
                return

            gateway = tool.gateway
            url = gateway.url
            gateway_id = str(gateway.id)
            transport_type = gateway.transport_type or "streamablehttp"

            # Register in mcp_session_pool
            from mcpgateway.services.mcp_session_pool import get_mcp_session_pool
            pool = get_mcp_session_pool()
            await pool.register_session_mapping(session_id, url, gateway_id, transport_type)

    except Exception as e:
        logger.debug(f"Failed to pre-register session mapping: {e}")
```

### 2. `mcpgateway/services/mcp_session_pool.py`

**Add new data structures (~line 250, in `__init__`):**
```python
# Pre-registered session mappings for session affinity
# Key: (mcp_session_id, url, transport_type, gateway_id) → pool_key
MappingKey = Tuple[str, str, str, str]
self._mcp_session_mapping: Dict[MappingKey, PoolKey] = {}
self._mcp_session_mapping_lock = asyncio.Lock()
```

**Add new method `register_session_mapping()`:**
```python
async def register_session_mapping(
    self,
    mcp_session_id: str,
    url: str,
    gateway_id: str,
    transport_type: str
) -> None:
    """Pre-register session mapping for session affinity.

    Called by broadcast() to set up mapping BEFORE acquire() is called.
    This ensures acquire() can find the correct pool key for session affinity.
    """
    if not settings.mcpgateway_session_affinity_enabled:
        return

    mapping_key = (mcp_session_id, url, transport_type, gateway_id)

    # Compute what the pool_key will be for this session
    # Use mcp_session_id as the identity basis for affinity
    identity_hash = hashlib.sha256(mcp_session_id.encode()).hexdigest()
    pool_key = ("anonymous", url, identity_hash, transport_type, gateway_id)

    async with self._mcp_session_mapping_lock:
        self._mcp_session_mapping[mapping_key] = pool_key
        logger.debug(f"Session affinity pre-registered: {mcp_session_id[:8]}... → {url}")
```

**Modify `acquire()` (~line 455) to use pre-registered mapping:**
```python
async def acquire(self, url, headers, transport_type, ...):
    headers_lower = {k.lower(): v for k, v in (headers or {}).items()}
    mcp_session_id = headers_lower.get("x-mcp-session-id")

    pool_key = None

    # Check pre-registered mapping first (set by broadcast)
    if settings.mcpgateway_session_affinity_enabled and mcp_session_id:
        mapping_key = (mcp_session_id, url, transport_type.value, gateway_id or "")
        async with self._mcp_session_mapping_lock:
            pool_key = self._mcp_session_mapping.get(mapping_key)
            if pool_key:
                logger.debug(f"Session affinity hit (pre-registered): {mcp_session_id[:8]}...")

    # Fallback to normal pool key computation
    if pool_key is None:
        user_id = user_identity or "anonymous"
        pool_key = self._make_pool_key(url, headers, transport_type, user_id, gateway_id)

    # ... existing acquire logic using pool_key ...
```

### 3. `mcpgateway/services/tool_service.py` (fallback)

**Still preserve x-mcp-session-id header for cases where broadcast didn't pre-register:**

**Location 1: line ~2756, Location 2: line ~2884:**
```python
# Preserve x-mcp-session-id for upstream session affinity (fallback)
if request_headers:
    mcp_session_id = request_headers.get("x-mcp-session-id") or request_headers.get("X-Mcp-Session-Id")
    if mcp_session_id:
        headers["x-mcp-session-id"] = mcp_session_id
```

## Verification

1. **Enable Session Affinity:**
   ```bash
   export MCPGATEWAY_SESSION_AFFINITY_ENABLED=true
   make dev
   ```

2. **Connect via SSE and make tool calls:**
   - On broadcast: Log should show `"Session affinity pre-registered: {id[:8]}... → {url}"`
   - On acquire: Log should show `"Session affinity hit (pre-registered): {id[:8]}..."`
   - Subsequent calls should show "Pool hit" (not "Pool miss")

3. **Verify session affinity flow:**
   - Same downstream session ID + same upstream gateway = same upstream session
   - JWT token rotation should NOT break affinity (different jti values still route to same upstream)

4. **Test different paths:**
   - SSE path: Client → broadcast() → respond() → /rpc → invoke_tool()
   - Direct HTTP path: POST /rpc → invoke_tool() (should still work via fallback)

5. **Run tests:**
   ```bash
   make test
   ```

## Summary

The key change is moving session mapping registration **earlier** in the flow:
- **Before**: acquire() tried to use x-mcp-session-id but mapping wasn't set up
- **After**: broadcast() pre-registers the mapping, acquire() just looks it up

This ensures session affinity is established before the tool invocation even begins.
