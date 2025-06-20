# MCP Gateway Transport-Translation Bridge

The MCP Gateway Transport-Translation Bridge (`mcpgateway-translate`) is a versatile tool that enables bidirectional communication between different MCP transport protocols. It allows you to run any MCP stdio-based server or remote SSE/Streamable-HTTP endpoint over every other official transport through a single CLI command.

## Features

- **Transport Bridging**: Seamlessly translate between stdio, SSE, WebSocket, and Streamable-HTTP transports
- **Bidirectional Communication**: Full duplex message routing between input and output transports  
- **Security**: Token redaction, header allow-lists, CORS support, and OAuth2 Bearer authentication
- **Health Monitoring**: Built-in health endpoints for load balancer integration
- **Docker Support**: Lightweight container images with runtime variants (base, uvx, deno)
- **Production Ready**: Comprehensive error handling, logging, and observability features

## Quick Start

### Expose a stdio MCP server over SSE

```bash
# Run a local git server accessible via browser SSE
mcpgateway-translate --stdio "uvx mcp-server-git" --port 9000

# Access via: http://localhost:9000/sse
```

### Bridge remote SSE to local stdio

```bash
# Connect remote SSE endpoint to local command-line tools
mcpgateway-translate --sse "https://corp.example.com/mcp"

# Your local tools can now communicate via stdio
```

### Full configuration with CORS and health monitoring

```bash
mcpgateway-translate \
  --stdio "python -m mcp_server" \
  --port 8080 \
  --cors "https://app.example.com" "https://dev.example.com" \
  --healthEndpoint /health \
  --header "X-API-Key:secret123" \
  --logLevel debug
```

## Command Line Reference

### Input Transports (Mutually Exclusive)

- `--stdio "<command>"` - Run a stdio MCP server using the specified command
- `--sse "<url>"` - Connect to a remote SSE endpoint  
- `--streamableHttp "<url>"` - Connect to a remote Streamable HTTP endpoint

### Output Transport

- `--outputTransport <type>` - Specify output transport: `stdio`, `sse`, or `ws`
  - Auto-detected if not specified:
    - `stdio` input → `sse` output (for browser clients)
    - `sse`/`http` input → `stdio` output (for command-line tools)

### Server Configuration

- `--port <number>` - Port to listen on (default: 8000)
- `--baseUrl <url>` - Base URL for the server (auto-detected if not specified)
- `--ssePath <path>` - SSE endpoint path (default: `/sse`)
- `--messagePath <path>` - Message endpoint path (default: `/message`)

### Authentication & Headers

- `--header "<key>:<value>"` - HTTP header (can be used multiple times)
- `--oauth2Bearer <token>` - OAuth2 Bearer token for authentication

### Logging

- `--logLevel <level>` - Logging level: `debug`, `info`, `none` (default: `info`)

### CORS & Health

- `--cors [<origin>...]` - CORS allowed origins
- `--healthEndpoint <path>` - Health check endpoint path

## Use Cases

### 1. Browser Integration

Expose local stdio MCP servers to web applications:

```bash
# Start git server for browser access
mcpgateway-translate --stdio "uvx mcp-server-git" --port 9000 \
  --cors "https://myapp.com"

# Browser can connect to: http://localhost:9000/sse
```

### 2. Corporate Firewall Bypass

Bridge remote MCP servers to local command-line tools:

```bash
# Access corporate MCP server locally
mcpgateway-translate --sse "https://corp.example.com/mcp" \
  --header "Authorization:Bearer ${CORP_TOKEN}"

# Local tools communicate via stdio JSON-RPC
```

### 3. Load Balanced Deployment

Deploy with health checks and monitoring:

```bash
mcpgateway-translate --stdio "python -m my_mcp_server" \
  --port 8080 \
  --healthEndpoint /healthz \
  --cors "https://frontend.example.com"

# Load balancer can probe: http://server:8080/healthz  
```

### 4. Development & Testing

Quick protocol translation for testing:

```bash
# Test WebSocket client against stdio server
mcpgateway-translate --stdio "echo server" --outputTransport ws

# Connect WebSocket client to: ws://localhost:8000/ws
```

## Docker Usage

### Basic Usage

```bash
# Run with Docker
docker run -p 8000:8000 ghcr.io/ibm/mcp-context-forge-translate:latest \
  --stdio "uvx mcp-server-git" --port 8000
```

### UVX Variant (with Node.js/npm support)

```bash
# Use uvx variant for Node.js-based MCP servers
docker run -p 8000:8000 ghcr.io/ibm/mcp-context-forge-translate:latest-uvx \
  --stdio "uvx @modelcontextprotocol/server-filesystem" --port 8000
```

### Deno Variant

```bash
# Use deno variant for Deno-based MCP servers  
docker run -p 8000:8000 ghcr.io/ibm/mcp-context-forge-translate:latest-deno \
  --stdio "deno run -A https://example.com/mcp-server.ts" --port 8000
```

### Docker Compose

```yaml
version: '3.8'
services:
  mcp-bridge:
    image: ghcr.io/ibm/mcp-context-forge-translate:latest
    ports:
      - "8000:8000"
    command: >
      --stdio "uvx mcp-server-git"
      --port 8000
      --healthEndpoint /health
      --cors "https://app.example.com"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## Environment Variables

All CLI flags can be configured via environment variables:

- `MCP_TRANSLATE_LOG_LEVEL` - Logging level (default: "info")
- `MCP_TOOL_CALL_TIMEOUT` - Tool call timeout in seconds (default: 90)

## API Endpoints

When running in server mode (SSE/WebSocket output), the bridge exposes:

### SSE Endpoint
- `GET {ssePath}` - Server-Sent Events stream (default: `/sse`)
- Returns endpoint URL and message stream

### Message Endpoint  
- `POST {messagePath}` - Send JSON-RPC messages (default: `/message`)
- Content-Type: `application/json`

### WebSocket Endpoint
- `WS /ws` - WebSocket connection for bidirectional communication

### Health Endpoint
- `GET {healthEndpoint}` - Health check (if configured)
- Returns: `ok` with 200 status

## Security Considerations

### Token Redaction
- OAuth2 Bearer tokens are automatically redacted from logs
- Use `--logLevel none` in production for sensitive environments

### CORS Configuration
- Always specify trusted origins with `--cors`
- Avoid wildcard origins (`*`) in production

### Header Allow-list
- Only explicitly specified headers are forwarded
- Sensitive headers are filtered by default

### HTTPS Verification
- Remote HTTPS endpoints are verified by default
- Certificate validation follows system settings

## Troubleshooting

### Common Issues

**Connection refused errors:**
```bash
# Check if the target server is running and accessible
curl -v http://localhost:8000/health

# Verify network connectivity for remote endpoints
curl -v https://remote.example.com/mcp
```

**CORS errors in browser:**
```bash
# Add your domain to CORS origins
mcpgateway-translate --stdio "server" --cors "https://yourdomain.com"
```

**Authentication failures:**
```bash
# Verify token format and permissions
mcpgateway-translate --sse "https://api.com/mcp" \
  --oauth2Bearer "your-token-here" --logLevel debug
```

### Debug Mode

Enable verbose logging for troubleshooting:

```bash
mcpgateway-translate --stdio "server" --logLevel debug
```

### Log Analysis

Check logs for common patterns:
- `Transport not connected` - Connection issues
- `Invalid JSON` - Message format problems  
- `Authentication failed` - Token/credential issues
- `CORS violation` - Browser security restrictions

## Performance Tuning

### Connection Pooling
- HTTP clients use connection pooling automatically
- Adjust `MCP_TOOL_CALL_TIMEOUT` for long-running operations

### Memory Usage
- Monitor memory usage with stdio servers that have large output
- Consider using streaming responses for large datasets

### Latency Optimization
- Use `--port` close to your application port range
- Enable HTTP/2 for better multiplexing (automatic)

## Contributing

To contribute to the translate bridge:

1. Run tests: `pytest tests/unit/mcpgateway/translate/`
2. Check linting: `ruff check mcpgateway/translate/`
3. Test Docker builds: `docker build -f docker/translate.Dockerfile .`

## License

Apache 2.0 - See LICENSE file for details.
