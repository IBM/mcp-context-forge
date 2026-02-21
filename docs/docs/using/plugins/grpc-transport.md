# gRPC Transport for External Plugins

This guide covers how to run external plugins using gRPC transport and configure the gateway to connect to them. gRPC provides significantly higher performance than the default MCP/HTTP transport.

## Performance Comparison

| Transport | Throughput | Use Case |
|-----------|------------|----------|
| MCP/HTTP | ~600 calls/sec | Default, broad compatibility |
| MCP/STDIO | ~600 calls/sec | Subprocess-based plugins |
| gRPC | ~4,700 calls/sec | High-performance remote plugins |
| Unix Socket | ~9,000 calls/sec | High-performance local IPC |

gRPC provides approximately **8x better performance** than MCP/HTTP transport due to:
- Binary protocol (Protocol Buffers) vs JSON
- HTTP/2 multiplexing and header compression
- Persistent connections with lower overhead
- Explicit message schemas reducing serialization costs

## Architecture Overview

```
┌─────────────────────┐           gRPC            ┌─────────────────────┐
│   ContextForge       │◄────────────────────────►│  External Plugin    │
│   (Client)          │      (HTTP/2 + Proto)     │  Server (gRPC)      │
│                     │                           │                     │
│  GrpcExternalPlugin │                           │  GrpcPluginServicer │
│        ▼            │                           │        ▼            │
│  grpc.aio.Channel   │                           │  ExternalPluginServer│
└─────────────────────┘                           └─────────────────────┘
```

## Quick Start

### 1. Install gRPC Dependencies

For the plugin server:
```bash
# In your external plugin directory
pip install ".[grpc]"

# Or using make target
make install-grpc
```

For the gateway (if not already installed):
```bash
pip install "mcp-contextforge-gateway[grpc]"
```

### 2. Start the gRPC Plugin Server

```bash
# Set the plugin config path
export PLUGINS_CONFIG_PATH=./resources/plugins/config.yaml

# Start the gRPC server (default port: 50051)
python -m mcpgateway.plugins.framework.external.grpc.server.runtime

# Or with custom port
python -m mcpgateway.plugins.framework.external.grpc.server.runtime --port 50052

# Or with Unix domain socket (highest local performance)
PLUGINS_GRPC_SERVER_UDS=/var/run/grpc-plugin.sock \
  python -m mcpgateway.plugins.framework.external.grpc.server.runtime
```

Using the convenience script (if using plugin templates):
```bash
PLUGINS_TRANSPORT=grpc ./run-server.sh
```

### 3. Configure the Gateway Client

In your gateway's `plugins/config.yaml`:

```yaml
plugins:
  # TCP connection
  - name: "MyGrpcPlugin"
    kind: "external"
    hooks: ["tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 50
    grpc:
      target: "localhost:50051"

  # Unix domain socket connection (for local high-performance)
  - name: "MyLocalGrpcPlugin"
    kind: "external"
    hooks: ["tool_pre_invoke"]
    mode: "enforce"
    priority: 50
    grpc:
      uds: /var/run/grpc-plugin.sock
```

## Server Configuration

### Plugin Server Configuration File

The plugin server reads its configuration from a YAML file. Configure the gRPC server settings in the same file:

```yaml
# resources/plugins/config.yaml (on the plugin server)
plugins:
  - name: "PIIFilterPlugin"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    hooks: ["tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 50
    config:
      detect_ssn: true
      detect_credit_card: true

# gRPC server settings (TCP)
grpc_server_settings:
  host: "0.0.0.0"
  port: 50051
  # tls:                                    # Uncomment for TLS/mTLS
  #   certfile: /path/to/server.pem
  #   keyfile: /path/to/server-key.pem
  #   ca_bundle: /path/to/ca.pem           # Required for mTLS
  #   client_auth: "require"               # none, optional, require

# OR use Unix domain socket (alternative to TCP, higher performance for local)
# grpc_server_settings:
#   uds: /var/run/grpc-plugin.sock
```

### Environment Variables (Server)

You can also configure the server via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGINS_CONFIG_PATH` | `./resources/plugins/config.yaml` | Path to plugin configuration file |
| `PLUGINS_GRPC_SERVER_HOST` | `0.0.0.0` | Server bind address |
| `PLUGINS_GRPC_SERVER_PORT` | `50051` | Server bind port |
| `PLUGINS_GRPC_SERVER_UDS` | - | Unix domain socket path (alternative to host:port) |
| `PLUGINS_GRPC_SERVER_SSL_ENABLED` | `false` | Enable TLS/mTLS (not supported with UDS) |
| `PLUGINS_GRPC_SERVER_SSL_CERTFILE` | - | Path to server certificate |
| `PLUGINS_GRPC_SERVER_SSL_KEYFILE` | - | Path to server private key |
| `PLUGINS_GRPC_SERVER_SSL_CA_CERTS` | - | Path to CA bundle (enables mTLS) |
| `PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH` | `require` | Client auth mode (none/optional/require) |

### Server Command Line Options

```bash
python -m mcpgateway.plugins.framework.external.grpc.server.runtime \
    --config plugins/config.yaml \
    --host 0.0.0.0 \
    --port 50051 \
    --log-level INFO \
    --tls  # Enable TLS (configure certs via env vars)
```

## Gateway Client Configuration

### YAML Configuration

Configure external plugins to use gRPC in the gateway's plugin configuration:

```yaml
plugins:
  # gRPC external plugin
  - name: "HighPerformanceFilter"
    kind: "external"
    hooks: ["tool_pre_invoke", "prompt_pre_fetch"]
    mode: "enforce"
    priority: 10
    grpc:
      target: "plugin-server:50051"
      # tls:                                # Uncomment for TLS/mTLS
      #   verify: true
      #   ca_bundle: /path/to/ca.pem
      #   certfile: /path/to/client.pem    # For mTLS
      #   keyfile: /path/to/client-key.pem # For mTLS

  # MCP external plugin (for comparison)
  - name: "LegacyPlugin"
    kind: "external"
    hooks: ["tool_post_invoke"]
    mode: "permissive"
    priority: 100
    mcp:
      proto: STREAMABLEHTTP
      url: http://localhost:8000/mcp
```

### Environment Variables (Client)

Client-side TLS can be configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGINS_GRPC_CLIENT_MTLS_VERIFY` | `true` | Verify server certificate |
| `PLUGINS_GRPC_CLIENT_MTLS_CA_BUNDLE` | - | Path to CA bundle |
| `PLUGINS_GRPC_CLIENT_MTLS_CERTFILE` | - | Path to client certificate (mTLS) |
| `PLUGINS_GRPC_CLIENT_MTLS_KEYFILE` | - | Path to client private key (mTLS) |
| `PLUGINS_GRPC_CLIENT_MTLS_KEYFILE_PASSWORD` | - | Password for encrypted private key |

## Unix Domain Socket Configuration

For local deployments where both the gateway and plugin server run on the same machine, Unix domain sockets provide the best performance by avoiding TCP overhead.

### Server Configuration (UDS)

```yaml
grpc_server_settings:
  uds: /var/run/grpc-plugin.sock
```

Or via environment variable:
```bash
export PLUGINS_GRPC_SERVER_UDS=/var/run/grpc-plugin.sock
```

### Client Configuration (UDS)

```yaml
plugins:
  - name: "LocalGrpcPlugin"
    kind: "external"
    hooks: ["tool_pre_invoke"]
    mode: "enforce"
    priority: 50
    grpc:
      uds: /var/run/grpc-plugin.sock
```

### Important Notes for UDS

- **TLS is not supported** with Unix domain sockets (communication is local and inherently secure)
- **File permissions** on the socket control access - ensure appropriate permissions on the socket directory
- **Cannot use both** `target` and `uds` - choose one or the other
- **Performance**: UDS eliminates TCP handshake overhead, providing lower latency for local IPC

## TLS/mTLS Configuration

### TLS Only (Server Certificate Verification)

**Server configuration:**
```yaml
grpc_server_settings:
  host: "0.0.0.0"
  port: 50051
  tls:
    certfile: /certs/server.pem
    keyfile: /certs/server-key.pem
    client_auth: "none"  # Don't require client certificates
```

**Client configuration:**
```yaml
grpc:
  target: "plugin-server:50051"
  tls:
    verify: true
    ca_bundle: /certs/ca.pem
```

### mTLS (Mutual TLS)

**Server configuration:**
```yaml
grpc_server_settings:
  host: "0.0.0.0"
  port: 50051
  tls:
    certfile: /certs/server.pem
    keyfile: /certs/server-key.pem
    ca_bundle: /certs/ca.pem      # Verify client certs against this CA
    client_auth: "require"         # Require client certificates
```

**Client configuration:**
```yaml
grpc:
  target: "plugin-server:50051"
  tls:
    verify: true
    ca_bundle: /certs/ca.pem
    certfile: /certs/client.pem    # Client certificate for mTLS
    keyfile: /certs/client-key.pem
```

### Client Auth Modes

| Mode | Description |
|------|-------------|
| `none` | Standard TLS, no client certificate required |
| `optional` | Client certificate validated if provided |
| `require` | Client certificate required (full mTLS) |

### Generating Certificates

Use the gateway's certificate generation tools:

```bash
# Generate complete mTLS infrastructure
make certs-mcp-all

# Or generate individual components
make certs-mcp-ca                          # Generate CA
make certs-mcp-gateway                     # Generate gateway client cert
make certs-mcp-plugin PLUGIN_NAME=MyPlugin # Generate plugin server cert
```

## Container Deployment

### Building with gRPC Support

```bash
# Build container with gRPC support
make build-grpc

# Or using docker directly
docker build --build-arg INSTALL_GRPC=true -t my-plugin .
```

### Docker Compose Example

```yaml
version: '3.8'

services:
  gateway:
    image: mcpgateway:latest
    ports:
      - "4444:4444"
    environment:
      - PLUGINS_ENABLED=true
      - PLUGIN_CONFIG_FILE=/app/plugins/config.yaml
    volumes:
      - ./plugins/config.yaml:/app/plugins/config.yaml
      - ./certs:/app/certs

  grpc-plugin:
    image: my-plugin:latest
    ports:
      - "50051:50051"
    environment:
      - PLUGINS_TRANSPORT=grpc
      - PLUGINS_CONFIG_PATH=/app/resources/plugins/config.yaml
      - PLUGINS_GRPC_SERVER_HOST=0.0.0.0
      - PLUGINS_GRPC_SERVER_PORT=50051
    volumes:
      - ./resources:/app/resources
      - ./certs:/app/certs
```

## Health Checks

The gRPC server implements the standard gRPC Health Checking Protocol:

```bash
# Using grpcurl
grpcurl -plaintext localhost:50051 grpc.health.v1.Health/Check

# With TLS
grpcurl -cacert ca.pem localhost:50051 grpc.health.v1.Health/Check
```

## Switching Between Transports

You can run the same plugin server with different transports:

```bash
# MCP/HTTP (default)
PLUGINS_TRANSPORT=http ./run-server.sh

# gRPC
PLUGINS_TRANSPORT=grpc ./run-server.sh

# Unix socket (highest performance for local deployment)
PLUGINS_TRANSPORT=unix ./run-server.sh
```

## Troubleshooting

### Connection Refused

1. Verify the server is running: `lsof -i :50051`
2. Check the server host binding (use `0.0.0.0` for all interfaces)
3. Verify firewall rules allow the port

### TLS Handshake Failed

1. Verify certificate paths are correct
2. Check certificate expiration: `openssl x509 -in cert.pem -noout -dates`
3. Ensure CA bundle matches between client and server
4. For mTLS, verify client certificates are properly configured

### Plugin Not Discovered

1. Check server logs for plugin loading errors
2. Verify the `PLUGINS_CONFIG_PATH` points to correct config file
3. Ensure plugin class paths are correct in the configuration

### Performance Not as Expected

1. Verify gRPC transport is actually being used (check logs)
2. Ensure persistent connections are being reused
3. Check network latency between gateway and plugin server
4. Consider Unix socket transport for local deployments

## Example: End-to-End Setup

### 1. Create Plugin Server Configuration

```yaml
# plugin-server/resources/plugins/config.yaml
plugins:
  - name: "SecurityFilterPlugin"
    kind: "plugins.security.filter.SecurityFilterPlugin"
    hooks: ["tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 10
    config:
      block_dangerous_ops: true

grpc_server_settings:
  host: "0.0.0.0"
  port: 50051
```

### 2. Start the Plugin Server

```bash
cd plugin-server
pip install -e ".[grpc]"
PLUGINS_CONFIG_PATH=./resources/plugins/config.yaml \
  python -m mcpgateway.plugins.framework.external.grpc.server.runtime
```

### 3. Configure Gateway

```yaml
# gateway/plugins/config.yaml
plugins:
  - name: "SecurityFilterPlugin"
    kind: "external"
    hooks: ["tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 10
    grpc:
      target: "localhost:50051"
```

### 4. Start Gateway

```bash
cd gateway
PLUGINS_ENABLED=true \
  PLUGIN_CONFIG_FILE=plugins/config.yaml \
  make dev
```

### 5. Verify Connection

Check gateway logs for:
```
INFO - Loaded external plugin 'SecurityFilterPlugin' via gRPC transport
INFO - Connected to gRPC plugin server at localhost:50051
```

## See Also

- [External Plugin mTLS Setup Guide](./mtls.md) - Detailed mTLS configuration for MCP transport
- [Plugin Framework Guide](./index.md) - Overview of the plugin system
- [Plugin Lifecycle Guide](./lifecycle.md) - Building and deploying external plugins
- [Available Plugins](./plugins.md) - Catalog of available plugins
