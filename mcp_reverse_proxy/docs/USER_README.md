# MCP Reverse Proxy

Bridge MCP servers to remote gateways with multi-transport support.

## Overview

The MCP Reverse Proxy is a standalone component that enables you to connect local or remote MCP servers to a ContextForge gateway (or any compatible MCP gateway). It supports multiple transport protocols for both MCP server connections and gateway connections.

### Key Features

- **Multi-Transport Support**: Connect to MCP servers via stdio, HTTP/2 streaming, or SSE
- **WebSocket Gateway**: Persistent connection to remote gateways
- **Automatic Reconnection**: Built-in retry logic with exponential backoff
- **Health Monitoring**: Active health checks with automatic recovery
- **Flexible Configuration**: CLI arguments, environment variables, or config files
- **Production Ready**: Comprehensive error handling and logging

## Installation

### From PyPI (when published)

```bash
pip install mcp-reverse-proxy
```

### From Source

```bash
# Clone the repository
git clone https://github.com/your-org/contextforge.git
cd contextforge/mcp_reverse_proxy

# Clean any old installations
rm -rf .venv mcp_reverse_proxy.egg-info __pycache__

# Create fresh virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package (REQUIRED to get the mcp-reverse-proxy command)
pip install -e .
```

**Important Notes**:
- The package uses a **src/ layout** - all Python modules are in `src/mcp_reverse_proxy/`
- You **must** run `pip install -e .` to install the package and create the `mcp-reverse-proxy` command
- If you get `ModuleNotFoundError`, clean old installations: `rm -rf .venv mcp_reverse_proxy.egg-info src/mcp_reverse_proxy.egg-info` then reinstall
- The `.venv` directory name (with dot prefix) avoids Python import conflicts
- Using a virtual environment is strongly recommended to avoid conflicts with system packages
- Python 3.11+ is required (Python 3.14 is supported)

**Alternative: Run without installing**
```bash
# If you don't want to install, you can run directly as a module
python -m mcp_reverse_proxy.cli --config config.json
```

**Troubleshooting**

If you see `ModuleNotFoundError: No module named 'mcp_reverse_proxy'`:

```bash
# 1. Clean old installations
cd mcp_reverse_proxy
rm -rf .venv mcp_reverse_proxy.egg-info __pycache__ transports/__pycache__

# 2. Recreate venv and reinstall
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Verify installation
which mcp-reverse-proxy  # Should show path in .venv/bin/
mcp-reverse-proxy --help  # Should show help message
```

If you see `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate`:

```bash
# Option 1: Provide CA certificate file path (recommended for production)
# The --cert parameter is used for BOTH MCP server HTTPS/WSS and gateway WSS connections
mcp-reverse-proxy \
  --local-streamable-http https://mcp-server.example.com/mcp \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_TOKEN \
  --cert /path/to/ca-certificate.pem

# Option 2: Provide certificate inline in config file (JSON or YAML)
# The cert field accepts the full certificate chain as a string
{
  "gateway": "wss://gateway.example.com/reverse-proxy",
  "token": "YOUR_TOKEN",
  "cert": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
}

# Option 3: For development/testing only - disable SSL verification
# WARNING: Only use in trusted development environments
export PYTHONHTTPSVERIFY=0
mcp-reverse-proxy --local-streamable-http http://localhost:9020/mcp --gateway wss://gateway.example.com/reverse-proxy --token YOUR_TOKEN
```

**Certificate Format Notes**:
- The `--cert` option accepts either a file path OR inline certificate data
- When using inline certificates in config files, include the complete certificate chain
- Certificates must be in PEM format with proper `\n` line breaks
- For certificate chains, concatenate all certificates (root CA, intermediate CAs, server cert)
- The code uses Python's `ssl.create_default_context(cadata=cert)` which validates the chain

**Troubleshooting Certificate Issues**:

If you see `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain`:

**The package now automatically loads system CAs as fallback** when you provide a custom certificate. This should resolve most certificate chain issues. Simply ensure your config has the `cert` field with the full certificate chain.

1. **Verify Your Setup (Recommended First Step)**:
   ```bash
   # Your config.json should have the cert field with full chain
   # The package will now use both your custom cert AND system CAs
   mcp-reverse-proxy --config config.json
   ```

2. **If Still Failing - Disable SSL Verification (Development Only)**:
   ```bash
   # This won't work with the current code - see option 3 instead
   export PYTHONHTTPSVERIFY=0
   mcp-reverse-proxy --config config.json
   ```

2. **Proper Fix - Use System CA Bundle**:
   ```bash
   # Extract cert from config to file
   python3 mcp_reverse_proxy/fix_ssl_cert.py config.json
   
   # This creates ca-bundle.pem - now use it
   mcp-reverse-proxy --cert ca-bundle.pem --config config.json
   ```

3. **Alternative - Load System Certificates**:
   The issue is that Python's SSL context doesn't trust the self-signed root CA. You can:
   - Add the root CA to your system's trust store (macOS: Keychain Access, Linux: `/etc/ssl/certs/`)
   - Or use `--cert` with the full certificate chain from your config

**Common Issues**:
- Certificate chain incomplete (missing root or intermediate CAs)
- Line breaks not properly escaped as `\n` in JSON
- Certificate expired or not yet valid
- Hostname mismatch between cert and gateway URL

**Verify Certificate**:
```bash
# Extract and test certificate
python3 mcp_reverse_proxy/fix_ssl_cert.py config.json

# Verify with OpenSSL
openssl verify -CAfile ca-bundle.pem ca-bundle.pem
```

### Development Installation

```bash
# Install with development dependencies
pip install -e ".[dev]"
```

## HTTPS/SSL Support

The reverse proxy **fully supports HTTPS** for both MCP server connections and gateway connections.

### Supported Protocols

- **MCP Server Connections**: `http://`, `https://` (for SSE and Streamable HTTP transports)
- **Gateway Connections**: `ws://`, `wss://` (WebSocket)

### Certificate Configuration

You have three options for configuring SSL certificates:

#### Option 1: Single Certificate (Simple)
Use `--cert` for both MCP server and gateway connections when they share the same CA:

```bash
mcp-reverse-proxy \
  --local-streamable-http https://mcp-server.example.com/mcp \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_TOKEN \
  --cert /path/to/shared-ca.pem
```

#### Option 2: Separate Certificates (Recommended for Different CAs)
Use `--mcp-cert` and `--gateway-cert` when MCP server and gateway use different CAs:

```bash
mcp-reverse-proxy \
  --local-streamable-http https://mcp-server.example.com/mcp \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_TOKEN \
  --mcp-cert /path/to/mcp-ca.pem \
  --gateway-cert /path/to/gateway-ca.pem
```

#### Option 3: Mixed Configuration
Use `--cert` as fallback with specific override:

```bash
# Use shared cert for gateway, but specific cert for MCP server
mcp-reverse-proxy \
  --local-sse https://mcp-server.example.com/sse \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_TOKEN \
  --cert /path/to/gateway-ca.pem \
  --mcp-cert /path/to/mcp-ca.pem
```

### Certificate Precedence

- `--mcp-cert` takes precedence over `--cert` for MCP server connections
- `--gateway-cert` takes precedence over `--cert` for gateway connections
- If only `--cert` is provided, it's used for both connections (backward compatible)

### Self-Signed Certificates

When no certificate is provided for a connection, SSL verification is **disabled** (insecure, for development only):
- Hostname verification: disabled
- Certificate verification: disabled

**⚠️ Warning**: Only use this in trusted development environments. Always provide CA certificates for production deployments.

### Certificate Bundle Format

For multiple CAs in a single file, concatenate certificates in PEM format:

```bash
cat root-ca.pem intermediate-ca.pem > ca-bundle.pem
mcp-reverse-proxy --cert ca-bundle.pem ...
```

## Quick Start

### Basic Usage - Stdio Transport

Connect a local MCP server (running via stdio) to a remote gateway:

```bash
mcp-reverse-proxy \
  --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_AUTH_TOKEN
```

### HTTP/2 Streaming Transport

Connect to an MCP server running on HTTP:

```bash
mcp-reverse-proxy \
  --local-streamable-http http://localhost:8000/mcp \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_AUTH_TOKEN
```

Connect to an MCP server running on HTTPS:

```bash
mcp-reverse-proxy \
  --local-streamable-http https://mcp-server.example.com/mcp \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_AUTH_TOKEN \
  --cert /path/to/ca-certificate.pem
```

### SSE Transport

Connect to an MCP server using Server-Sent Events (HTTP):

```bash
mcp-reverse-proxy \
  --local-sse http://localhost:9020/sse \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_AUTH_TOKEN
```

Connect to an MCP server using Server-Sent Events (HTTPS):

```bash
mcp-reverse-proxy \
  --local-sse https://mcp-server.example.com/sse \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token YOUR_AUTH_TOKEN \
  --cert /path/to/ca-certificate.pem
```

## Configuration

### Environment Variables

Set these environment variables to avoid passing them on the command line:

```bash
export REVERSE_PROXY_GATEWAY="wss://gateway.example.com/reverse-proxy"
export REVERSE_PROXY_TOKEN="your-auth-token"
```

Then run:

```bash
mcp-reverse-proxy --local-stdio "uvx mcp-server-git"
```

### Configuration File

Create a YAML or JSON configuration file:

**config.yaml:**
```yaml
local-stdio: "uvx mcp-server-git"
gateway: "wss://gateway.example.com/reverse-proxy"
token: "your-auth-token"
server-name: "My Git Server"
server-description: "Git repository access"
keepalive: 30
reconnect-delay: 2.0
max-retries: 0
log-level: "INFO"
```

**config.json:**
```json
{
  "local-stdio": "uvx mcp-server-git",
  "gateway": "wss://gateway.example.com/reverse-proxy",
  "token": "your-auth-token",
  "server-name": "My Git Server",
  "server-description": "Git repository access",
  "keepalive": 30,
  "reconnect-delay": 2.0,
  "max-retries": 0,
  "log-level": "INFO"
}
```

Use the config file:

```bash
# With YAML config
mcp-reverse-proxy --config config.yaml

# With JSON config
mcp-reverse-proxy --config config.json
```

**Tip**: Configuration files are useful for:
- Managing multiple proxy instances with different settings
- Version controlling your proxy configurations
- Avoiding long command lines with many arguments

## Command Line Options

### MCP Server Transport

Choose **one** of these options:

- `--local-stdio COMMAND` - Run MCP server as subprocess (e.g., `"uvx mcp-server-git"`)
- `--local-streamable-http URL` - Connect to HTTP/2 streaming endpoint (e.g., `http://localhost:8000/mcp`)
- `--local-sse URL` - Connect to SSE endpoint (e.g., `http://localhost:9020/sse`)

### Gateway Connection

- `--gateway URL` - Gateway WebSocket URL (or use `REVERSE_PROXY_GATEWAY` env var)
- `--token TOKEN` - Bearer token for authentication (or use `REVERSE_PROXY_TOKEN` env var)
- `--server-id ID` - Session identifier (auto-generated if not provided)
- `--server-name NAME` - Server name for registration
- `--server-description DESC` - Server description for registration
- `--cert PATH` - CA certificate for SSL verification (used for both MCP and gateway if specific certs not provided)
- `--mcp-cert PATH` - CA certificate specifically for MCP server HTTPS connections (overrides --cert)
- `--gateway-cert PATH` - CA certificate specifically for gateway WSS connections (overrides --cert)

### Connection Options

- `--reconnect-delay SECONDS` - Initial reconnection delay (default: 1.0)
- `--max-retries COUNT` - Maximum reconnection attempts, 0=infinite (default: 0)
- `--keepalive SECONDS` - Heartbeat interval (default: 2)
- `--mcp-health-check-timeout SECONDS` - MCP health check timeout (default: 5.0)
- `--mcp-health-check-retry-interval SECONDS` - Retry interval during MCP outage (default: 10.0)

### Logging

- `--log-level LEVEL` - Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
- `--verbose` - Enable verbose logging (same as `--log-level DEBUG`)

Set `LOG_FORMAT=json` environment variable for JSON-formatted logs.

### Configuration File

- `--config PATH` - Load configuration from YAML or JSON file

## Health Monitoring

The reverse proxy implements a two-layer health monitoring system:

### Layer 1: MCP Server Health Checks

Before sending heartbeats to the gateway, the proxy actively checks if the MCP server is healthy by sending a `tools/list` request:

- ✅ **MCP responds** → Proxy sends heartbeat to gateway
- ❌ **MCP timeout** → Proxy skips heartbeat (gateway detects missing heartbeat)
- 🔄 **During outage** → Proxy continues probing with shorter retry interval
- ✅ **MCP recovers** → Proxy automatically reconnects to gateway

### Layer 2: Gateway Health Monitoring

The gateway tracks reverse proxy sessions through heartbeat monitoring:

- Expects heartbeats every 30 seconds (configurable)
- Marks session as stale after 90 seconds without heartbeat (configurable)
- After 3 consecutive failures, marks server as unreachable (configurable)
- Automatically recovers when heartbeats resume

## Examples

### Example 1: Local Git Server

```bash
mcp-reverse-proxy \
  --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --server-name "Git Server" \
  --server-description "Access to local git repositories"
```

### Example 2: Remote HTTPS Server with Shared Certificate

```bash
# Single certificate for both MCP server and gateway
mcp-reverse-proxy \
  --local-streamable-http https://mcp-server.internal:8000/mcp \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --cert /path/to/shared-ca.pem \
  --keepalive 30 \
  --mcp-health-check-timeout 10.0 \
  --mcp-health-check-retry-interval 15.0
```

### Example 3: SSE Server with Separate Certificates

```bash
# Different certificates for MCP server and gateway
mcp-reverse-proxy \
  --local-sse https://mcp-server.internal:9020/sse \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --mcp-cert /path/to/mcp-ca.pem \
  --gateway-cert /path/to/gateway-ca.pem
```

### Example 4: Using Configuration File

```bash
# Create config file
cat > reverse-proxy-config.yaml <<EOF
local-stdio: "uvx mcp-server-filesystem --allowed-directory /home/user/projects"
gateway: "wss://gateway.example.com/reverse-proxy"
token: "your-token-here"
server-name: "Filesystem Server"
server-description: "Access to project files"
keepalive: 30
log-level: "INFO"
EOF

# Run with config
mcp-reverse-proxy --config reverse-proxy-config.yaml
```

### Example 5: JSON Logging for Production

```bash
export LOG_FORMAT=json
mcp-reverse-proxy \
  --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --log-level INFO
```

## Running as a Service

### systemd Service (Linux)

Create `/etc/systemd/system/mcp-reverse-proxy.service`:

```ini
[Unit]
Description=MCP Reverse Proxy
After=network.target

[Service]
Type=simple
User=mcp
WorkingDirectory=/opt/mcp-reverse-proxy
Environment="REVERSE_PROXY_GATEWAY=wss://gateway.example.com/reverse-proxy"
Environment="REVERSE_PROXY_TOKEN=your-token-here"
Environment="LOG_FORMAT=json"
ExecStart=/usr/local/bin/mcp-reverse-proxy --local-stdio "uvx mcp-server-git" --log-level INFO
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp-reverse-proxy
sudo systemctl start mcp-reverse-proxy
sudo systemctl status mcp-reverse-proxy
```

### Docker Container

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install the reverse proxy
COPY . .
RUN pip install --no-cache-dir .

# Set environment variables
ENV REVERSE_PROXY_GATEWAY=""
ENV REVERSE_PROXY_TOKEN=""
ENV LOG_FORMAT=json

# Run the proxy
ENTRYPOINT ["mcp-reverse-proxy"]
CMD ["--local-stdio", "uvx mcp-server-git"]
```

Build and run:

```bash
docker build -t mcp-reverse-proxy .
docker run -d \
  --name mcp-proxy \
  -e REVERSE_PROXY_GATEWAY="wss://gateway.example.com/reverse-proxy" \
  -e REVERSE_PROXY_TOKEN="your-token" \
  mcp-reverse-proxy
```

## Troubleshooting

### Connection Issues

**Problem**: Cannot connect to gateway

```bash
# Check gateway URL is correct
curl -I https://gateway.example.com

# Test with verbose logging
mcp-reverse-proxy --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --verbose
```

**Problem**: SSL certificate verification fails

```bash
# Use custom CA certificate
mcp-reverse-proxy --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --cert /path/to/ca-cert.pem
```

### MCP Server Issues

**Problem**: MCP server not responding

```bash
# Test MCP server directly
uvx mcp-server-git

# Increase health check timeout
mcp-reverse-proxy --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --mcp-health-check-timeout 10.0
```

### Logging

Enable debug logging to see detailed information:

```bash
mcp-reverse-proxy --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --log-level DEBUG
```

Or use JSON logging for structured logs:

```bash
export LOG_FORMAT=json
mcp-reverse-proxy --local-stdio "uvx mcp-server-git" \
  --gateway wss://gateway.example.com/reverse-proxy \
  --token $TOKEN \
  --log-level INFO
```

## Architecture

The reverse proxy uses a transport abstraction pattern:

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

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=mcp_reverse_proxy --cov-report=html
```

### Code Quality

```bash
# Format code
black .

# Lint code
ruff check .

# Type check
mypy .
```

## License

Apache-2.0

## Contributing

Contributions are welcome! Please see the main ContextForge repository for contribution guidelines.