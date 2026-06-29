# Quick Start Guide - Test Streamable HTTP MCP Server

## Running the Server

### Start in Streamable HTTP mode (port 9020):

```bash
cd mcp-servers/python/test_streamable_http_server
make run-http
```

The server will start on `http://0.0.0.0:9020/mcp`

## Testing with ContextForge Reverse Proxy

### Architecture:
```
Gateway ←→ (WebSocket) ←→ Reverse Proxy ←→ (Streamable HTTP) ←→ MCP Server
```

### Step-by-Step Testing:

**Terminal 1 - Start the test MCP server:**
```bash
cd mcp-servers/python/test_streamable_http_server
make run-http
```

**Terminal 2 - Start the reverse proxy:**
```bash
python -m mcpgateway.reverse_proxy \
  --local-streamable-http http://localhost:9020/mcp \
  --gateway ws://localhost:4444 \
  --server-id test-streamable-server \
  --server-name "Test Streamable HTTP Server" \
  --server-description "Test server for streamable HTTP transport"
```

This connects:
- To your MCP server at `http://localhost:9020/mcp` via streamable HTTP
- To the gateway at `ws://localhost:4444` via WebSocket

**Terminal 3 - Test via gateway:**
```bash
# List tools through the gateway
curl -X POST http://localhost:4444/servers/test-streamable-server/mcp/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'

# Call the echo tool
curl -X POST http://localhost:4444/servers/test-streamable-server/mcp/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "echo",
      "arguments": {
        "message": "Hello through reverse proxy!"
      }
    }
  }'
```

## Available Tool

- **echo**: Echoes back the input message
  - Input: `message` (string)
  - Output: `{"success": true, "message": "...", "length": N}`

## Troubleshooting

### "No module named test_streamable_http_server"
- Use `make run-http` or `uv run python -m test_streamable_http_server --transport http --port 9020`

### Server won't start
- Check if port 9020 is already in use: `lsof -i :9020`
- Try a different port: `uv run python -m test_streamable_http_server --transport http --port 9021`

### Reverse proxy connection issues
- Ensure the MCP server is running first
- Check that the gateway is running on port 4444
- Verify the streamable HTTP URL includes `/mcp` path
- For HTTPS gateway, use `wss://` instead of `ws://`

### Gateway not found
- Make sure ContextForge gateway is running: `make dev` or `make serve`
- Check gateway logs for connection attempts