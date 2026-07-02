# Issue #5402: Agent Code Change Locations

This document provides exact file locations and line numbers for implementing vault direct mode in `agent_langchain_mcp`.

---

## File Structure

```
agent_langchain_mcp/
├── app/
│   ├── routes/
│   │   ├── agent_langchain/
│   │   │   └── agent_langchain_router.py   ← Main changes here
│   │   └── agent_langgraph/
│   │       └── agent_langgraph_router.py   ← Similar changes
│   └── utilities/
│       └── vault_proxy.py                  ← Core vault logic changes
├── tests/
│   ├── unit/
│   │   └── test_vault_proxy.py            ← New unit tests
│   └── integration/
│       └── test_agent_vault_direct.py     ← New integration tests
└── .env.sample                             ← Add feature flag

```

---

## 1. Environment Configuration

### File: `.env.sample`

**Location**: Root directory

**Add these lines**:
```bash
# Vault Direct Integration (Issue #5402)
# When enabled, agent passes vault credentials to Context Forge
# instead of resolving them locally
VAULT_DIRECT_MODE_ENABLED=false  # Feature flag (default: false for backward compatibility)
```

---

## 2. Vault Proxy Utility

### File: `app/utilities/vault_proxy.py`

**Current structure**: Functions defined at ~line 20-344

**Changes needed**:

#### A. Add feature flag check function (insert at ~line 20, after imports)

```python
def is_direct_mode_enabled() -> bool:
    """Check if vault direct mode is enabled."""
    return os.getenv("VAULT_DIRECT_MODE_ENABLED", "false").lower() == "true"
```

#### B. Update `fetch_tokens()` function (~line 242)

**Current signature**:
```python
async def fetch_tokens(
    user_name: Optional[str] = None,
    tokens: Optional[Dict[str, str]] = None,
    vault_token: Optional[str] = None
) -> Optional[Dict[str, str]]:
```

**Add at the beginning of the function** (after docstring, ~line 275):
```python
    # NEW: Check for direct mode
    if is_direct_mode_enabled():
        logger.info("Vault direct mode enabled - skipping agent-side vault resolution")
        logger.info("Vault credentials will be passed to Context Forge for resolution")
        return None
    
    # LEGACY MODE: Keep existing implementation below...
```

#### C. Update `handle_tokens()` function (~line 312)

**Current signature**:
```python
async def handle_tokens(
    mcp_servers: Dict[str, Any],
    plain_tokens: Optional[Dict[str, str]] = None
) -> None:
```

**Add at the beginning of the function** (after docstring, ~line 336):
```python
    # NEW: Skip in direct mode
    if is_direct_mode_enabled():
        logger.debug("Vault direct mode enabled - skipping X-Vault-Tokens header injection")
        return
    
    # LEGACY MODE: Keep existing implementation below...
```

#### D. Add new function for passthrough headers (insert at ~line 344, end of file)

```python
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

## 3. Agent LangChain Router

### File: `app/routes/agent_langchain/agent_langchain_router.py`

**Structure**: Routes are defined inside `add_custom_routes(app: FastAPI)` function starting at ~line 541

#### Location 1: `/agent_langchain/invoke` endpoint (~line 544-688)

**Find this section** (~line 605):
```python
        # Fetch tokens ONCE before building MCP servers
        plain_tokens = await fetch_tokens(
            input_data.vault_entity_id,
            input_data.tokens,
            input_data.vault_token
        )
```

**Then find the MCP server building section** (~line 612-655):

**Current code** (~line 616):
```python
            if input_data.mcp_server_url:
                # Initialize headers dict if not provided
                headers = input_data.mcp_server_headers or {}
                # Add x-mcp-session-id, X-Chat-Id headers if chat_id is provided
                if chat_id:
                    headers["x-mcp-session-id"] = chat_id
                    headers["X-Chat-Id"] = chat_id
                    log.info(f"Added x-mcp-session-id, X-Chat-Id headers: {chat_id}")
```

**Add NEW code after the chat_id headers** (~line 622):
```python
                # NEW: Add vault passthrough headers for direct mode
                headers = add_vault_passthrough_headers(
                    headers,
                    input_data.vault_entity_id,
                    input_data.vault_token
                )
```

**Also add import at top of file** (~line 40):
```python
from app.utilities.vault_proxy import fetch_tokens, handle_tokens, add_vault_passthrough_headers
```

**And for multiple MCP servers** (~line 634-654):

**Current code** (~line 638):
```python
                for idx, server in enumerate(input_data.mcp_servers):
                    server_name = f"mcpserver_{idx}"
                    # Initialize headers dict if not provided
                    headers = server.headers.copy() if server.headers else {}
                    # Add x-mcp-session-id, X-Chat-Id headers if chat_id is provided
                    if chat_id:
                        headers["x-mcp-session-id"] = chat_id
                        headers["X-Chat-Id"] = chat_id
                        log.info(f"Added x-mcp-session-id, X-Chat-Id headers to {server_name}: {chat_id}")
```

**Add NEW code after the chat_id headers** (~line 643):
```python
                    # NEW: Add vault passthrough headers for direct mode
                    headers = add_vault_passthrough_headers(
                        headers,
                        input_data.vault_entity_id,
                        input_data.vault_token
                    )
```

#### Location 2: `/agent_langchain/result` endpoint (~line 690-end)

**Apply the exact same pattern** to the non-streaming endpoint around line ~757-806.

Find the section where headers are built and add the `add_vault_passthrough_headers()` call.

---

## 4. Agent LangGraph Router (if exists)

### File: `app/routes/agent_langgraph/agent_langgraph_router.py`

**Similar structure** to agent_langchain_router.py.

**Search for**:
- `fetch_tokens()` calls (likely around line ~2016, ~2136)
- MCP server header building sections
- Apply the same pattern as above

---

## 5. Testing Files

### File: `tests/unit/test_vault_proxy.py` (NEW or UPDATE)

**Create this file** if it doesn't exist, or add new test cases:

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.utilities.vault_proxy import (
    fetch_tokens,
    handle_tokens,
    add_vault_passthrough_headers,
    is_direct_mode_enabled
)

# Add test cases as documented in ISSUE_5402_AGENT_CHANGES.md
```

### File: `tests/integration/test_agent_vault_direct.py` (NEW)

**Create this file** with integration tests as documented.

---

## Quick Reference: What Changes Where

| File | Function/Section | Change Type | Line ~ |
|------|------------------|-------------|--------|
| `.env.sample` | Environment vars | Add flag | N/A |
| `vault_proxy.py` | Top of file | Add `is_direct_mode_enabled()` | ~20 |
| `vault_proxy.py` | `fetch_tokens()` | Add early return for direct mode | ~275 |
| `vault_proxy.py` | `handle_tokens()` | Add early return for direct mode | ~336 |
| `vault_proxy.py` | End of file | Add `add_vault_passthrough_headers()` | ~344 |
| `agent_langchain_router.py` | Import section | Add import | ~40 |
| `agent_langchain_router.py` | `/invoke` single server | Add passthrough headers | ~622 |
| `agent_langchain_router.py` | `/invoke` multi-server | Add passthrough headers | ~643 |
| `agent_langchain_router.py` | `/result` endpoint | Add passthrough headers | ~757-806 |
| `agent_langgraph_router.py` | Similar sections | Add passthrough headers | TBD |

---

## Validation Checklist

After making changes, verify:

- [ ] Import added: `from app.utilities.vault_proxy import fetch_tokens, handle_tokens, add_vault_passthrough_headers`
- [ ] `is_direct_mode_enabled()` function exists in `vault_proxy.py`
- [ ] `fetch_tokens()` has early return for direct mode
- [ ] `handle_tokens()` has early return for direct mode
- [ ] `add_vault_passthrough_headers()` function exists
- [ ] All MCP server header sections call `add_vault_passthrough_headers()`
- [ ] Feature flag `VAULT_DIRECT_MODE_ENABLED` in `.env.sample`
- [ ] Unit tests added for all new functions
- [ ] Integration tests added for end-to-end flow

---

## Testing the Changes

### 1. Test Direct Mode

```bash
# Set environment variable
export VAULT_DIRECT_MODE_ENABLED=true

# Run agent
python -m app.server

# Send request (verify X-Vault-Token and X-User-Name headers sent to Context Forge)
```

### 2. Test Legacy Mode (Default)

```bash
# Unset or set to false
export VAULT_DIRECT_MODE_ENABLED=false

# Run agent
python -m app.server

# Send request (verify X-Vault-Tokens header sent, old behavior)
```

### 3. Run Tests

```bash
# Unit tests
pytest tests/unit/test_vault_proxy.py -v

# Integration tests
pytest tests/integration/test_agent_vault_direct.py -v

# All tests
pytest tests/ -v
```

---

## Common Pitfalls to Avoid

1. ❌ **Don't forget the import**: `add_vault_passthrough_headers` must be imported
2. ❌ **Don't skip multi-server case**: There are TWO places to add passthrough headers (single + multi)
3. ❌ **Don't modify function signatures**: Only add code inside existing functions
4. ❌ **Don't break legacy mode**: Always check `is_direct_mode_enabled()` before direct mode logic
5. ❌ **Don't forget `/result` endpoint**: Both streaming and non-streaming endpoints need updates

---

## Diff Summary

**Files Modified**: 2
- `app/utilities/vault_proxy.py` (~20 lines added)
- `app/routes/agent_langchain/agent_langchain_router.py` (~10 lines added)

**Files Created**: 2-3
- `tests/unit/test_vault_proxy.py` (or updated)
- `tests/integration/test_agent_vault_direct.py`
- `.env.sample` (1 line added)

**Total Lines Changed**: ~50-60 lines

**Backward Compatible**: ✅ Yes (feature flag defaults to OFF)

---

## Example: Before/After Code

### Before (Current)

```python
# app/routes/agent_langchain/agent_langchain_router.py (~line 616)

if input_data.mcp_server_url:
    headers = input_data.mcp_server_headers or {}
    if chat_id:
        headers["x-mcp-session-id"] = chat_id
        headers["X-Chat-Id"] = chat_id
    
    mcp_servers = {
        "mcpserver": {
            "url": input_data.mcp_server_url,
            "transport": "sse",
            "headers": headers,
            # ...
        }
    }
```

### After (With Direct Mode Support)

```python
# app/routes/agent_langchain/agent_langchain_router.py (~line 616)

if input_data.mcp_server_url:
    headers = input_data.mcp_server_headers or {}
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
            # ...
        }
    }
```

**Only 5 lines added!**

---

## Need Help?

- Refer to: [ISSUE_5402_AGENT_CHANGES.md](./ISSUE_5402_AGENT_CHANGES.md) for detailed explanation
- Check: [ISSUE_5402_CHECKLIST.md](./ISSUE_5402_CHECKLIST.md) for step-by-step tasks
- See: [ISSUE_5402_ARCHITECTURE.md](./ISSUE_5402_ARCHITECTURE.md) for flow diagrams

---

**Ready to implement? Follow this guide and the checklist side-by-side!**
