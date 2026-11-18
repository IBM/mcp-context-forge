---
name: mcp-helpers
description: Generate a gateway JWT, expose a stdio MCP server over HTTP/SSE with `mcpgateway.translate`, or register an MCP server in a local gateway.
---

# MCP Helpers

```bash
# Generate JWT token
python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret KEY

# Export for API calls
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret KEY)

# Expose stdio server via HTTP/SSE
python -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000
```

## Add an MCP Server

1. Start: `python -m mcpgateway.translate --stdio "server-command" --port 9000`
2. Register: `POST /gateways`
3. Create virtual server: `POST /servers`
4. Access via SSE/WebSocket endpoints
