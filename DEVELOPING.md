## Development Testing with MCP Inspector

```
export MCP_GATEWAY_BASE_URL=http://localhost:4444
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1
export MCP_AUTH_USER=admin
export MCP_AUTH_PASS=changeme


npx @modelcontextprotocol/inspector # SSE
npx @modelcontextprotocol/inspector uv --directory "/home/cmihai/mcpgateway-wrapper" run mcpgateway-wrapper # wrapper
```

🔍 MCP Inspector is up and running at http://localhost:5173 🚀


## SuperGateway

Supergateway runs a MCP stdio-based servers over SSE (Server-Sent Events) with one command. This is useful for remote access, debugging, or connecting to SSE-based clients when your MCP server only speaks stdio.

`npx -y supergateway --stdio "uvx run mcp-server-git"``
or
```
pip install uvenv
npx -y supergateway --stdio "uvenv run mcp-server-git"
```

SSE endpoint: GET http://localhost:8000/sse
POST messages: POST http://localhost:8000/message
