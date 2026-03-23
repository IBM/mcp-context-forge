# Unix Socket Transport

High-performance local IPC transport using length-prefixed protobuf messages.

## Performance

| Transport | Throughput | Use Case |
|-----------|------------|----------|
| MCP/HTTP | ~600 calls/sec | Remote plugins |
| gRPC | ~4,700 calls/sec | Remote/local plugins |
| **Unix Socket** | ~9,000 calls/sec | Local plugins only |

## Server Configuration

**Environment variables:**
```bash
PLUGINS_TRANSPORT=unix
PLUGINS_UNIX_SOCKET_PATH=/tmp/mcpgateway-plugins.sock
```

**YAML config:**
```yaml
unix_socket_server_settings:
  path: "/tmp/mcpgateway-plugins.sock"
```

**Start the server:**
```bash
PLUGINS_TRANSPORT=unix python -m mcpgateway.plugins.framework.external.unix.server.runtime
```

## Client Configuration

```yaml
plugins:
  - name: "MyPlugin"
    kind: "external"
    hooks: ["tool_pre_invoke"]
    unix_socket:
      path: "/tmp/mcpgateway-plugins.sock"
      timeout: 30.0            # Read timeout (seconds)
      reconnect_attempts: 3    # Retry count
      reconnect_delay: 0.1     # Base delay with exponential backoff
```

## Protocol

The Unix socket transport uses length-prefixed protobuf messages (the same protobuf schema as gRPC):

```
[4-byte big-endian length][protobuf payload]
```

Messages use the `plugin_service.proto` schema (e.g., `InvokeHookRequest`, `InvokeHookResponse`). This provides the performance benefits of protobuf serialization without the overhead of HTTP/2 framing that gRPC uses.

## When to Use

| Scenario | Recommended Transport |
|----------|----------------------|
| Local, same machine, max performance | Unix Socket |
| Local, need gRPC ecosystem (reflection, streaming) | gRPC + UDS |
| Remote plugins | gRPC or MCP/HTTP |
| Cross-platform (Windows) | MCP/HTTP or gRPC |

## Limitations

- Local only (no network support)
- No TLS (use file permissions for security)
- No built-in streaming (request/response only)
