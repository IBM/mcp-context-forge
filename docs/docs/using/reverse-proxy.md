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
│   Local MCP Server  │ stdio   │  Reverse Proxy   │   WS    │   Remote    │
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
export REVERSE_PROXY_GATEWAY=wss://gateway.example.com/reverse-proxy/ws
export REVERSE_PROXY_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret your-secret-key)

# Run the reverse proxy
mcp-reverse-proxy \
    --local-stdio "uvx mcp-server-git"
```

### 2. Command Line Options

```bash
mcp-reverse-proxy \
    --local-stdio "uvx mcp-server-filesystem --directory /path/to/files" \
    --gateway https://gateway.example.com \
    --token your-bearer-token \
    --reconnect-delay 2 \
    --max-retries 10 \
    --keepalive 2 \
    --log-level DEBUG
```

Options:

- `--local-stdio`: Command to run the local MCP server (required)
- `--gateway`: Remote gateway URL (or use REVERSE_PROXY_GATEWAY env var)
- `--token`: Bearer token for authentication (or use REVERSE_PROXY_TOKEN env var)
- `--reconnect-delay`: Initial reconnection delay in seconds (default: 1)
- `--max-retries`: Maximum reconnection attempts, 0=infinite (default: 0)
- `--keepalive`: Heartbeat interval in seconds (default: 2)
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
keepalive: 2
log_level: "INFO"
```

Run with configuration:

```bash
mcp-reverse-proxy --config reverse-proxy.yaml
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

# Install the maintained reverse-proxy client and local MCP server
RUN pip install mcp-reverse-proxy mcp-server-git

# Set environment
ENV REVERSE_PROXY_GATEWAY=wss://gateway.example.com/reverse-proxy/ws
ENV REVERSE_PROXY_TOKEN=your-token

# Run reverse proxy
CMD ["mcp-reverse-proxy", \
     "--local-stdio", "mcp-server-git"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  reverse-proxy-git:
    build: .
    environment:
      REVERSE_PROXY_GATEWAY: wss://gateway.example.com/reverse-proxy/ws
      REVERSE_PROXY_TOKEN: ${TOKEN}
    command: >
      mcp-reverse-proxy
      --local-stdio "mcp-server-git"
      --keepalive 2
      --log-level INFO
    restart: unless-stopped

  reverse-proxy-filesystem:
    build: .
    environment:
      REVERSE_PROXY_GATEWAY: wss://gateway.example.com/reverse-proxy/ws
      REVERSE_PROXY_TOKEN: ${TOKEN}
    volumes:

      - ./data:/data:ro
    command: >
      mcp-reverse-proxy
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
        image: your-registry/mcp-reverse-proxy:latest
        env:

        - name: REVERSE_PROXY_GATEWAY
          value: "wss://gateway.example.com/reverse-proxy/ws"

        - name: REVERSE_PROXY_TOKEN
          valueFrom:
            secretKeyRef:
              name: mcp-credentials
              key: token
        command:
        - mcp-reverse-proxy
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

```bash
# Required on the gateway
MCPGATEWAY_REVERSE_PROXY_ENABLED=true
```

### Multi-worker deployments

A single gateway worker can keep reverse-proxy session ownership in process. Deployments with two or more workers must enable the Redis-backed distributed relay so an MCP call handled by a non-owner worker can reach the worker that owns the client WebSocket:

```bash
MCPGATEWAY_REVERSE_PROXY_ENABLED=true
MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED=true
CACHE_TYPE=redis
REDIS_URL=redis://redis:6379/0
```

Distributed mode fails startup unless the reverse-proxy feature and Redis cache are both enabled. Redis stores short-lived owner generations, worker heartbeats, and signed request/response envelopes; the WebSocket remains local to its owner worker. If Redis becomes unavailable, cross-worker dispatch fails closed rather than guessing at ownership.

Set `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT` to the number of seconds a client may remain silent before its session is evicted and its catalog gateway becomes unreachable. The default is 90 seconds; `0` disables heartbeat eviction. Use a value appropriate for the client's keepalive interval and network jitter.

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
- WebSocket auth accepts bearer tokens from the `Authorization` header only (`?token=` query auth is not supported)
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
   mcp-reverse-proxy \
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
| `reverse-proxy relay unavailable` | Redis is unavailable in distributed mode | Restore Redis connectivity; requests fail closed until ownership is authoritative again |
| Gateway starts on one worker but calls fail on another | Distributed relay is disabled | Enable `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED` and configure Redis |

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
    gateway: "wss://gateway1.example.com/reverse-proxy/ws"

  - name: filesystem-server
    command: "uvx mcp-server-filesystem --directory /data"
    gateway: "wss://gateway2.example.com/reverse-proxy/ws"
```

### Load Balancing

Connect the same server to multiple gateways:

```bash
# Primary gateway
mcp-reverse-proxy \
    --local-stdio "uvx mcp-server-git" \
    --gateway wss://gateway1.example.com/reverse-proxy/ws &

# Backup gateway
mcp-reverse-proxy \
    --local-stdio "uvx mcp-server-git" \
    --gateway wss://gateway2.example.com/reverse-proxy/ws &
```

### Monitoring Integration

Export metrics for monitoring systems:

```python
# Custom monitoring wrapper
import asyncio
from mcp_reverse_proxy.client import ReverseProxyClient

class MonitoredReverseProxy(ReverseProxyClient):
    async def connect(self):
        # Export connection metric
        prometheus_client.Counter('reverse_proxy_connections_total').inc()
        await super().connect()
```

## Developer Resources

Working on the gateway-side service or the wire protocol? The [Reverse Proxy developer guide](../development/reverse-proxy.md) covers the internals, the unit test surface, and the live end-to-end harness. The harness runs the real client against a containerized multi-worker gateway:

```bash
RP_E2E_RUN_ID=my-run tests/live_gateway/reverse_proxy/run.sh
```

It is manually invoked and not part of `make test` or CI; see the developer guide for prerequisites and overrides.

## Related Documentation

- [ContextForge Documentation](../index.md)
- [MCP Protocol Specification](https://modelcontextprotocol.io)
- [Transport Protocols](../architecture/index.md)
- [Authentication Guide](../manage/securing.md)
