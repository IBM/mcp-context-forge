---
title: Fix Plugin Context Sharing for /mcp Endpoints
date: 2026-03-27
issue: #3879
status: approved
---

# Fix Plugin Context Sharing for /mcp Endpoints

## Problem Statement

Plugin context stored in `HTTP_PRE_REQUEST` hooks is not accessible in `TOOL_PRE_INVOKE` hooks when tools are invoked via the `/mcp` endpoint. This breaks custom authorization plugins and any other plugins that need to maintain state across hook types.

### Observed Behavior

When a plugin stores data in its context during the `HTTP_PRE_REQUEST` hook and then tries to access that data in the `TOOL_PRE_INVOKE` hook for `/mcp` endpoints, the context is always empty.

### Root Cause

At `streamablehttp_transport.py:1334`, the `call_tool` function invokes `tool_service.invoke_tool()` without extracting or passing the plugin contexts from `request.state`. The contexts are stored there by `HttpAuthMiddleware` but never retrieved for the `/mcp` code path.

This was already fixed for `/rpc` endpoints in PR #1514 (issue #1495), but the `/mcp` endpoint uses a different code path through the streamable HTTP transport that was not updated.

## Solution Design

### Architectural Overview

Apply the same pattern from PR #1514 to the streamable HTTP transport's `call_tool` function:

1. Extract `plugin_context_table` and `plugin_global_context` from `request.state`
2. Pass these contexts to `tool_service.invoke_tool()`

This ensures plugin context flows through the entire request lifecycle:
```
HTTP_PRE_REQUEST (middleware)
  → request.state.plugin_context_table
  → call_tool (transport)
  → tool_service.invoke_tool()
  → TOOL_PRE_INVOKE hook (receives context)
```

### Implementation Details

**File: `mcpgateway/transports/streamablehttp_transport.py`**

**Location:** Inside the `call_tool` async function, after line 1330 (after the session affinity block, before the `try` block at line 1331)

**Changes:**

1. Extract plugin contexts from request state:
```python
# Get plugin contexts from request.state for cross-hook sharing
plugin_context_table = None
plugin_global_context = None
try:
    ctx = mcp_app.request_context
    if ctx and ctx.request:
        plugin_context_table = getattr(ctx.request.state, "plugin_context_table", None)
        plugin_global_context = getattr(ctx.request.state, "plugin_global_context", None)
except LookupError:
    # No active request context
    pass
```

2. Pass contexts to `tool_service.invoke_tool()` call (around line 1334):
```python
result = await tool_service.invoke_tool(
    db=db,
    name=name,
    arguments=arguments,
    request_headers=request_headers,
    app_user_email=app_user_email,
    user_email=user_email,
    token_teams=token_teams,
    server_id=server_id,
    meta_data=meta_data,
    plugin_context_table=plugin_context_table,     # NEW
    plugin_global_context=plugin_global_context,   # NEW
)
```

**Why this location:**
- After session affinity handling (which might forward to another worker)
- Before the actual tool invocation
- Matches the pattern used in `/rpc` endpoints in `main.py`

**Why this approach:**
- Minimal changes - only touches the specific code path that's broken
- Consistent with existing fix in PR #1514
- Uses the same `request.state` pattern established throughout the codebase
- No changes to function signatures (parameters already exist)

### Error Handling

The extraction is wrapped in a try-except to handle cases where:
- No request context is active (e.g., in tests)
- Request state is not available
- Context attributes don't exist

In all error cases, contexts remain `None`, which is the existing default behavior. The `tool_service.invoke_tool()` method already handles `None` context values gracefully.

## Testing Strategy

### Manual Testing

1. **Setup:** Create a test plugin that stores data in `HTTP_PRE_REQUEST` and reads it in `TOOL_PRE_INVOKE`
2. **Test Case:** Invoke a tool via `/mcp` endpoint (SSE or WebSocket)
3. **Expected:** Plugin should successfully read the context data without errors
4. **Verification:** Check logs for context data flow, no ValueError about missing context

### Integration Test

Create a test similar to `tests/integration/test_cross_hook_context_sharing.py::test_http_to_tool_context_sharing` but using the `/mcp` endpoint instead of `/rpc`.

**Test structure:**
```python
async def test_mcp_endpoint_plugin_context_sharing():
    """Test context sharing from HTTP_PRE_REQUEST to TOOL_PRE_INVOKE via /mcp endpoint."""
    # 1. Enable plugin with cross-hook context tracking
    # 2. Make request to /mcp endpoint (SSE) with tool call
    # 3. Verify plugin receives context in TOOL_PRE_INVOKE
    # 4. Assert no 500 error from missing context
```

### Regression Prevention

The existing integration tests in `test_cross_hook_context_sharing.py` cover the `/rpc` path and should continue to pass. Adding the `/mcp` test ensures both paths are covered.

## Scope and Limitations

### In Scope
- Fix plugin context passing for tool invocations via `/mcp` endpoint
- Ensure consistency with `/rpc` endpoint behavior

### Out of Scope
- Resource and prompt operations via `/mcp` (not reported as broken)
- Other transports (stdio, websocket non-streamable)
- Changes to plugin framework itself
- Performance optimization

### Future Considerations

If similar issues are discovered for resources or prompts accessed through `/mcp`, the same pattern can be applied to those operations. The fix is intentionally scoped to the reported issue to minimize risk.

## Dependencies

**No new dependencies.** This fix uses existing infrastructure:
- `request.state` pattern (established in PR #1514)
- `mcp_app.request_context` (existing context access)
- `tool_service.invoke_tool()` parameters (already accept plugin contexts)

## Rollout Plan

1. Implement the fix in `streamablehttp_transport.py`
2. Add integration test for `/mcp` endpoint context sharing
3. Run full test suite to verify no regressions
4. Manual testing with a custom plugin
5. Commit with reference to issue #3879
6. No feature flag needed - this is a bug fix restoring expected behavior

## Success Criteria

- [ ] Plugin context from `HTTP_PRE_REQUEST` is accessible in `TOOL_PRE_INVOKE` for `/mcp` tool calls
- [ ] Integration test passes for `/mcp` endpoint
- [ ] Existing `/rpc` tests continue to pass
- [ ] No errors in logs about missing context
- [ ] Custom authorization plugin works as expected

## References

- **Issue:** #3879 - Plugin context is not shared between HTTP_PRE_REQUEST and TOOL_PRE_INVOKE
- **Related Issue:** #1495 - Original issue for `/rpc` endpoints
- **Related PR:** #1514 - Fix that addressed `/rpc` endpoints
- **Code References:**
  - `mcpgateway/transports/streamablehttp_transport.py:1334` - Missing context passing
  - `mcpgateway/services/tool_service.py:3823` - Service expects `local_contexts` parameter
  - `mcpgateway/main.py:5521-5522` - Pattern for extracting contexts from request.state
