# MCP Reverse Proxy Tests

This directory contains unit tests for the `mcp_reverse_proxy` package.

## Test Organization

The tests were moved from `tests/unit/mcpgateway/test_mcp_reverse_proxy_*` to this location because `mcp_reverse_proxy` is a standalone package, not a submodule of `mcpgateway`.

## Test Files

- `test_mcp_reverse_proxy_base.py` - Tests for base transport classes
- `test_mcp_reverse_proxy_cli.py` - Tests for CLI module
- `test_mcp_reverse_proxy_client.py` - Tests for reverse proxy client
- `test_mcp_reverse_proxy_sse_adapter.py` - Tests for SSE transport adapter
- `test_mcp_reverse_proxy_stdio_adapter.py` - Tests for stdio transport adapter
- `test_mcp_reverse_proxy_streamablehttp_adapter.py` - Tests for streamable HTTP transport adapter
- `test_mcp_reverse_proxy_websocket_adapter.py` - Tests for WebSocket transport adapter

## Running Tests

From the repository root:
```bash
pytest mcp_reverse_proxy/tests/
```

From the mcp_reverse_proxy directory:
```bash
pytest tests/
```

## Import Changes

All imports have been updated from:
```python
from mcpgateway.mcp_reverse_proxy.* import ...
```

To:
```python
from mcp_reverse_proxy.* import ...
```

This reflects the correct package structure where `mcp_reverse_proxy` is a standalone package.