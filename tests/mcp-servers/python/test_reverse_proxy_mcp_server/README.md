# Test Reverse Proxy MCP Server

A test MCP server for testing reverse proxy multi-transport functionality with support for stdio, streamable HTTP, and SSE transports.

## Features

- **Multiple Transport Support**: stdio, HTTP, and SSE
- **Authentication Testing**: Header logging middleware to verify auth forwarding
- **Simple Tools**: Echo and server info tools for testing

## Installation

```bash
cd mcp-servers/python/test_reverse_proxy_mcp_server
uv pip install -e .
```

## Usage

### SSE Mode (for testing SSE reverse proxy)

```bash
python -m test_reverse_proxy_mcp_server --transport sse --port 9020
```

### Streamable HTTP Mode (for testing HTTP reverse proxy)

```bash
python -m test_reverse_proxy_mcp_server --transport http --port 9020
```

### Stdio Mode

```bash
python -m test_reverse_proxy_mcp_server
```

## Testing with ContextForge Reverse Proxy

### Testing SSE Transport

1. Start the server in SSE mode:
```bash
python -m test_reverse_proxy_mcp_server --transport sse --port 9020
```

2. Start the reverse proxy client with SSE adapter:
```bash
python -m mcpgateway.reverse_proxy_multi_transport.cli \
  --gateway-url ws://localhost:4444/reverse-proxy \
  --local-sse http://localhost:9020 \
  --session-id test-sse-session
```

3. Test the tools through the gateway.

### Testing Streamable HTTP Transport

1. Start the server in HTTP mode:
```bash
python -m test_reverse_proxy_mcp_server --transport http --port 9020
```

2. Start the reverse proxy client with HTTP adapter:
```bash
python -m mcpgateway.reverse_proxy_multi_transport.cli \
  --gateway-url ws://localhost:4444/reverse-proxy \
  --local-http http://localhost:9020 \
  --session-id test-http-session
```

3. Test the tools through the gateway.

## Available Tools

- `echo`: Echo back the input message
- `get_server_info`: Get information about the test server including supported transports

## Authentication Testing

The server includes a header logging middleware that logs all incoming HTTP headers (with sensitive values masked). This is useful for verifying that authentication headers are properly forwarded from the gateway through the reverse proxy to the MCP server.

When testing with authentication:
1. Configure authentication in the gateway
2. Check the server logs to verify headers are received
3. Look for masked Authorization headers in the logs

## Architecture

```
Client → Gateway → Reverse Proxy Client → Test MCP Server
                   (SSE/HTTP Adapter)     (SSE/HTTP Transport)
```

The reverse proxy client uses transport adapters (SSE or HTTP) to communicate with the test server, which runs in the corresponding transport mode.