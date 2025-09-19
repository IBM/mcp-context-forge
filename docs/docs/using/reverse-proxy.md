# MCP Reverse Proxy

The MCP Reverse Proxy enables local MCP servers to be accessible through remote gateways without requiring inbound network access. This is similar to SSH reverse tunneling or ngrok, but specifically designed for the MCP protocol.

## Overview

The reverse proxy establishes an outbound connection from a local environment to a remote gateway, then tunnels all MCP protocol messages through this persistent connection. This allows:

- **Firewall traversal**: Share MCP servers without opening inbound ports
- **NAT bypass**: Work seamlessly behind corporate or home NATs
- **Edge deployments**: Connect edge servers to central management
- **Development testing**: Test local servers with cloud-hosted gateways

## Architecture

```
┌─────────────────────┐         ┌──────────────────┐         ┌─────────────┐
│   Local MCP Server  │ stdio   │  Reverse Proxy   │ WS/SSE  │   Remote    │
│  (uvx mcp-server)   │ <-----> │     Client       │ <-----> │   Gateway   │
└─────────────────────┘         └──────────────────┘         └─────────────┘
                                                                     ↑
                                                                     │
                                                              ┌──────┴──────┐
                                                              │ MCP Clients │
                                                              └─────────────┘
```

## Quick Start

### 1. Basic Usage

Connect a local MCP server to a remote gateway:

```bash
# Set gateway URL and authentication
export REVERSE_PROXY_GATEWAY=https://gateway.example.com
export REVERSE_PROXY_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin --exp 10080 --secret your-secret-key)

# Run the reverse proxy
python3 -m mcpgateway.reverse_proxy \
    --local-stdio "uvx mcp-server-git"
```

### 2. Command Line Options

```bash
python3 -m mcpgateway.reverse_proxy \
    --local-stdio "uvx mcp-server-filesystem --directory /path/to/files" \
    --gateway https://gateway.example.com \
    --token your-bearer-token \
    --reconnect-delay 2 \
    --max-retries 10 \
    --keepalive 30 \
    --log-level DEBUG
```

Options:
- `--local-stdio`: Command to run the local MCP server (required)
- `--gateway`: Remote gateway URL (or use REVERSE_PROXY_GATEWAY env var)
- `--token`: Bearer token for authentication (or use REVERSE_PROXY_TOKEN env var)
- `--reconnect-delay`: Initial reconnection delay in seconds (default: 1)
- `--max-retries`: Maximum reconnection attempts, 0=infinite (default: 0)
- `--keepalive`: Heartbeat interval in seconds (default: 30)
- `--log-level`: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `--verbose`: Enable verbose logging (same as --log-level DEBUG)
- `--config`: Configuration file (YAML or JSON)

### 3. Configuration File

Create a `reverse-proxy.yaml`:

```yaml
# reverse-proxy.yaml
local_stdio: "uvx mcp-server-git"
gateway: "https://gateway.example.com"
token: "your-bearer-token"
reconnect_delay: 2
max_retries: 0
keepalive: 30
log_level: "INFO"
```

Run with configuration:

```bash
python3 -m mcpgateway.reverse_proxy --config reverse-proxy.yaml
```

## Environment Variables

- `REVERSE_PROXY_GATEWAY`: Remote gateway URL
- `REVERSE_PROXY_TOKEN`: Bearer token for authentication
- `REVERSE_PROXY_RECONNECT_DELAY`: Initial reconnection delay (seconds)
- `REVERSE_PROXY_MAX_RETRIES`: Maximum reconnection attempts (0=infinite)
- `REVERSE_PROXY_LOG_LEVEL`: Python log level

## Docker Deployment

### Single Container

```dockerfile
FROM python:3.11-slim

# Install MCP gateway and server
RUN pip install mcp-gateway mcp-server-git

# Set environment
ENV REVERSE_PROXY_GATEWAY=https://gateway.example.com
ENV REVERSE_PROXY_TOKEN=your-token

# Run reverse proxy
CMD ["python", "-m", "mcpgateway.reverse_proxy", \
     "--local-stdio", "mcp-server-git"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  reverse-proxy-git:
    image: mcp-gateway:latest
    environment:
      REVERSE_PROXY_GATEWAY: https://gateway.example.com
      REVERSE_PROXY_TOKEN: ${TOKEN}
    command: >
      python -m mcpgateway.reverse_proxy
      --local-stdio "mcp-server-git"
      --keepalive 30
      --log-level INFO
    restart: unless-stopped

  reverse-proxy-filesystem:
    image: mcp-gateway:latest
    environment:
      REVERSE_PROXY_GATEWAY: https://gateway.example.com
      REVERSE_PROXY_TOKEN: ${TOKEN}
    volumes:
      - ./data:/data:ro
    command: >
      python -m mcpgateway.reverse_proxy
      --local-stdio "mcp-server-filesystem --directory /data"
    restart: unless-stopped
```

## Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-reverse-proxy
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-reverse-proxy
  template:
    metadata:
      labels:
        app: mcp-reverse-proxy
    spec:
      containers:
      - name: reverse-proxy
        image: mcp-gateway:latest
        env:
        - name: REVERSE_PROXY_GATEWAY
          value: "https://gateway.example.com"
        - name: REVERSE_PROXY_TOKEN
          valueFrom:
            secretKeyRef:
              name: mcp-credentials
              key: token
        command:
        - python
        - -m
        - mcpgateway.reverse_proxy
        args:
        - --local-stdio
        - "mcp-server-git"
        - --keepalive
        - "30"
        resources:
          limits:
            memory: "256Mi"
            cpu: "100m"
```

## Gateway-Side Configuration

The remote gateway must have the reverse proxy endpoints enabled:

### 1. WebSocket Endpoint

The gateway exposes `/reverse-proxy/ws` for WebSocket connections:

```python
# Gateway receives connections at:
wss://gateway.example.com/reverse-proxy/ws
```

### 2. Session Management

View active reverse proxy sessions:

```bash
# List all sessions
curl -H "Authorization: Bearer $TOKEN" \
     https://gateway.example.com/reverse-proxy/sessions

# Disconnect a session
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
     https://gateway.example.com/reverse-proxy/sessions/{session_id}
```

### 3. Virtual Server Registration

Reverse-proxied servers automatically appear in the gateway's server catalog and can be accessed like any other MCP server.

## Security Considerations

### Authentication

- Always use authentication tokens in production
- Tokens should have appropriate expiration times
- Consider using mutual TLS for additional security

### Network Security

- The reverse proxy only requires outbound HTTPS/WSS
- No inbound firewall rules needed
- All traffic is encrypted via TLS

### Best Practices

1. **Use specific tokens per deployment**
   ```bash
   # Generate deployment-specific token
   python3 -m mcpgateway.utils.create_jwt_token \
       --username edge-server-01 \
       --exp 10080 \
       --secret $JWT_SECRET
   ```

2. **Monitor connection health**
   - Check gateway logs for connection events
   - Monitor reconnection attempts
   - Set up alerts for persistent failures

3. **Resource limits**
   - Set appropriate memory/CPU limits in containers
   - Configure max message sizes
   - Implement rate limiting on the gateway

## Troubleshooting

### Connection Issues

1. **Check connectivity**:
   ```bash
   # Test gateway reachability
   curl -I https://gateway.example.com/healthz
   ```

2. **Verify authentication**:
   ```bash
   # Test token validity
   curl -H "Authorization: Bearer $TOKEN" \
        https://gateway.example.com/reverse-proxy/sessions
   ```

3. **Enable debug logging**:
   ```bash
   python3 -m mcpgateway.reverse_proxy \
       --local-stdio "uvx mcp-server-git" \
       --log-level DEBUG
   ```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Connection refused` | Gateway unreachable | Check gateway URL and network |
| `401 Unauthorized` | Invalid token | Regenerate token with correct secret |
| `WebSocket connection failed` | Firewall blocking WSS | Check outbound port 443 |
| `Subprocess not running` | Local server crashed | Check server command and logs |
| `Max retries exceeded` | Persistent network issue | Check network stability |

### Performance Tuning

1. **Adjust keepalive interval**:
   ```bash
   # Shorter interval for unstable networks
   --keepalive 15

   # Longer interval for stable networks
   --keepalive 60
   ```

2. **Configure reconnection strategy**:
   ```bash
   # Quick reconnect with limited retries
   --reconnect-delay 0.5 --max-retries 20

   # Slow reconnect with infinite retries
   --reconnect-delay 5 --max-retries 0
   ```

## Advanced Usage

### Multiple Local Servers

Run multiple reverse proxies for different servers:

```yaml
# multi-server.yaml
servers:
  - name: git-server
    command: "uvx mcp-server-git"
    gateway: "https://gateway1.example.com"

  - name: filesystem-server
    command: "uvx mcp-server-filesystem --directory /data"
    gateway: "https://gateway2.example.com"
```

### Load Balancing

Connect the same server to multiple gateways:

```bash
# Primary gateway
python3 -m mcpgateway.reverse_proxy \
    --local-stdio "uvx mcp-server-git" \
    --gateway https://gateway1.example.com &

# Backup gateway
python3 -m mcpgateway.reverse_proxy \
    --local-stdio "uvx mcp-server-git" \
    --gateway https://gateway2.example.com &
```

### Monitoring Integration

Export metrics for monitoring systems:

```python
# Custom monitoring wrapper
import asyncio
from mcpgateway.reverse_proxy import ReverseProxyClient

class MonitoredReverseProxy(ReverseProxyClient):
    async def connect(self):
        # Export connection metric
        prometheus_client.Counter('reverse_proxy_connections_total').inc()
        await super().connect()
```

## Related Documentation

- [MCP Gateway Documentation](../index.md)
- [MCP Protocol Specification](https://modelcontextprotocol.io)
- [Transport Protocols](../architecture/index.md)
- [Authentication Guide](../manage/securing.md)
