# Reverse Proxy Architecture

This module implements an extensible reverse proxy for bridging MCP servers to remote gateways.

## Architecture

The reverse proxy uses a **transport abstraction pattern** following SOLID principles:

```
┌─────────────────────────────────────────────────────────────┐
│                    ReverseProxyClient                        │
│  (Orchestrates message routing and connection management)   │
└──────────────┬────────────────────────────┬─────────────────┘
               │                            │
               ▼                            ▼
    ┌──────────────────────┐    ┌──────────────────────┐
    │  McpServerTransport  │    │  GatewayTransport    │
    │   (Abstract Base)    │    │   (Abstract Base)    │
    └──────────┬───────────┘    └──────────┬───────────┘
               │                            │
       ┌───────┴────────┬─────────┐       │
       ▼                ▼         ▼       ▼
┌─────────────┐  ┌──────────┐ ┌────────┐ ┌──────────────┐
│StdioAdapter │  │Streamable│ │SSE     │ │WebSocket     │
│             │  │HttpAdapter│ │Adapter │ │Adapter       │
└─────────────┘  └──────────┘ └────────┘ └──────────────┘
```

### Components

#### Base Classes (`base.py`)

- **`McpServerTransport`**: Abstract base for MCP server connections
  - `StdioAdapter`: Connects via subprocess stdio
  - `StreamableHttpAdapter`: Connects via HTTP/2 streaming
  - `SseAdapter`: Connects via Server-Sent Events (SSE)

- **`GatewayTransport`**: Abstract base for gateway connections
  - `WebSocketAdapter`: Connects to gateway via WebSocket

#### Client (`client.py`)

- **`ReverseProxyClient`**: Orchestrates bidirectional message routing
  - Manages connection lifecycle
  - Handles registration and keepalive
  - Routes messages between transports
  - Implements automatic reconnection

#### CLI (`cli.py`)

- **Transport factory**: Creates transports based on CLI arguments
- **Argument parsing**: Handles configuration
- **Signal handling**: Graceful shutdown

## Usage

### Stdio Transport (Local MCP Server)

```bash
python -m mcpgateway.reverse_proxy.cli \
  --local-stdio "uvx mcp-server-git" \
  --gateway https://gateway.example.com \
  --token $TOKEN
```

### Streamable HTTP Transport (Remote MCP Server)

```bash
python -m mcpgateway.mcp_reverse_proxy.cli \
  --local-streamable-http http://mcp-server.local:8000/mcp \
  --gateway https://gateway.example.com \
  --token $TOKEN
```

### SSE Transport (Remote MCP Server)

```bash
python -m mcpgateway.mcp_reverse_proxy.cli \
  --local-sse http://mcp-server.local:9020/sse \
  --gateway https://gateway.example.com \
  --token $TOKEN
```

## Health Check Strategy

The reverse proxy implements a **two-layer health monitoring system** to ensure reliable operation:

### Layer 1: MCP Server Health Checks (Client-Side)

The reverse proxy client actively monitors the health of the local MCP server before sending heartbeats to the gateway:

**MCP-Based Heartbeat Strategy:**
1. Before each heartbeat interval (default: 30s), the client sends a `tools/list` request to the MCP server
2. If the MCP server responds within the timeout (default: 5s), the client sends a heartbeat to the gateway
3. Client heartbeat interval (30s) is set to be less than gateway health check interval (60s) to ensure at least 2 heartbeats per check cycle
3. If the MCP server fails to respond, the client **skips the heartbeat** (gateway will detect timeout)
4. During MCP server outages, the client continues probing with a shorter retry interval (default: 10s)
5. When the MCP server recovers, the client automatically reconnects to the gateway

**Why `tools/list`?**
- Universal MCP method supported by all compliant servers
- Lightweight operation with minimal overhead
- Validates both connectivity and protocol compliance

**Configuration:**
```bash
python -m mcpgateway.mcp_reverse_proxy.cli \
  --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --keepalive 30 \
  --mcp-health-check-timeout 5.0 \
  --mcp-health-check-retry-interval 10.0
```

### Layer 2: Gateway Health Monitoring (Server-Side)

The gateway tracks reverse proxy session health through heartbeat monitoring:

**Heartbeat Timeout Detection:**
1. Gateway expects heartbeats every 30 seconds (configurable via `MCPGATEWAY_REVERSE_PROXY_HEALTH_CHECK_INTERVAL`)
2. Background task checks session staleness every 30 seconds
3. If no heartbeat received within 90 seconds (configurable via `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT`), session is marked stale
4. After 3 consecutive failures (configurable via `MCPGATEWAY_REVERSE_PROXY_FAILURE_THRESHOLD`), gateway marks server as unreachable
5. Gateway updates database `reachable` property and closes WebSocket connection

**Automatic Recovery:**
- When MCP server recovers, client reconnects to gateway
- Gateway receives heartbeat and marks server as reachable again
- No manual intervention required

### Health Check Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     Normal Operation                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Client checks MCP server health (tools/list)                │
│     └─> MCP server responds ✓                                   │
│                                                                  │
│  2. Client sends heartbeat to gateway                           │
│     └─> Gateway receives heartbeat ✓                            │
│                                                                  │
│  3. Gateway marks session as healthy                            │
│     └─> Database: reachable = true                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     MCP Server Failure                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Client checks MCP server health (tools/list)                │
│     └─> MCP server timeout ✗                                    │
│                                                                  │
│  2. Client SKIPS heartbeat to gateway                           │
│     └─> Gateway detects missing heartbeat                       │
│                                                                  │
│  3. Gateway increments failure counter                          │
│     └─> After 3 failures: reachable = false                     │
│                                                                  │
│  4. Client continues probing MCP server (10s interval)          │
│     └─> Waiting for recovery...                                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     Automatic Recovery                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. MCP server comes back online                                │
│     └─> Client detects via health check ✓                       │
│                                                                  │
│  2. Client reconnects to gateway                                │
│     └─> Sends registration + heartbeat                          │
│                                                                  │
│  3. Gateway marks session as healthy                            │
│     └─> Database: reachable = true                              │
│                                                                  │
│  4. Normal operation resumes                                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Benefits

✅ **Fail-Fast Detection**: Gateway quickly detects MCP server outages via missing heartbeats
✅ **Self-Healing**: Automatic recovery when MCP server comes back online
✅ **No False Positives**: Only sends heartbeats when MCP server is actually healthy
✅ **Configurable**: All timeouts and intervals can be tuned for your environment
✅ **Production-Ready**: Comprehensive error handling and logging

### Configuration Reference

**Client-Side (Reverse Proxy):**
- `--keepalive`: Heartbeat interval in seconds (default: 30)
- `--mcp-health-check-timeout`: MCP health check timeout in seconds (default: 5.0)
- `--mcp-health-check-retry-interval`: Retry interval during MCP outage in seconds (default: 10.0)

**Server-Side (Gateway):**
- `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT`: Max time without heartbeat before marking stale (default: 90s)
- `MCPGATEWAY_REVERSE_PROXY_HEALTH_CHECK_INTERVAL`: How often to check session health (default: 60s)
- `MCPGATEWAY_REVERSE_PROXY_FAILURE_THRESHOLD`: Consecutive failures before marking unreachable (default: 3)

## Key Features

### SOLID Principles

- **Single Responsibility**: Each transport handles one protocol
- **Open/Closed**: New transports can be added without modifying existing code
- **Liskov Substitution**: All transports are interchangeable via interfaces
- **Interface Segregation**: Separate interfaces for MCP server vs gateway
- **Dependency Inversion**: Client depends on abstractions, not implementations

### Extensibility

Adding a new MCP server transport:

1. Create adapter class inheriting from `McpServerTransport`
2. Implement required methods: `start()`, `stop()`, `send()`, `add_message_handler()`
3. Add to transport factory in `cli.py`

### Configuration

- **Environment variables**: `REVERSE_PROXY_GATEWAY`, `REVERSE_PROXY_TOKEN`
- **CLI arguments**: See `--help` for full list
- **Automatic reconnection**: Configurable backoff and retry limits

## Transport Details

### Stdio Adapter

- Spawns subprocess with stdin/stdout pipes
- Line-based JSON-RPC message protocol
- Automatic process cleanup on shutdown

### Streamable HTTP Adapter

- HTTP/2 streaming for bidirectional communication
- Inline responses for request/response pattern
- POST for sending messages to server
- Supports both HTTP and HTTPS
- Optional SSL certificate verification

### SSE Adapter

- Server-Sent Events (SSE) for server-to-client streaming
- HTTP POST for client-to-server messages
- Automatic endpoint discovery from SSE stream
- Session management via headers
- Supports both HTTP and HTTPS
- Optional SSL certificate verification

### WebSocket Adapter

- Persistent WebSocket connection to gateway
- Automatic ping/pong keepalive
- SSL/TLS support with optional certificate verification
- Graceful reconnection on disconnect

## Message Flow

```
MCP Server → McpServerTransport → ReverseProxyClient → GatewayTransport → Gateway
                                         ↓
                                  Message Routing
                                  - Registration
                                  - Heartbeat
                                  - Request/Response
                                  - Notifications
```

## Error Handling

- Transport-level errors trigger reconnection
- Configurable retry limits and backoff delays
- Graceful shutdown on SIGINT/SIGTERM
- Automatic cleanup of resources

## Future Enhancements

- Additional gateway transports (HTTP, gRPC)
- Metrics and observability
- Connection pooling
- Load balancing across multiple MCP servers