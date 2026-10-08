# 🎯 MCP Servers

ContextForge federates MCP servers regardless of where they run or who builds them: register any reachable MCP server as a gateway, and its tools, prompts, and resources become available through your virtual servers.

This section collects setup and integration guides for specific servers:

- **External Servers** — third-party hosted MCP servers (Box, GitHub, monday.com, Notion, and others)
- **IBM Servers** — IBM MCP servers (Instana)
- **Hashicorp Servers** — HashiCorp MCP servers (Terraform)

## Registering a server

```bash
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"example_server","url":"http://localhost:9000/sse"}' \
     http://localhost:4444/gateways
```

## Resources

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [mcpgateway.translate Bridge](../mcpgateway-translate.md) - stdio ↔ SSE/Streamable HTTP bridge
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector) - Interactive protocol debugging
