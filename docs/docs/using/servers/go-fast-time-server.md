# 🦫 Fast Time Server

`fast-time-server` is a lightweight, high-performance Go service that provides **current time lookup** across different timezones via multiple transport protocols. Built specifically for **MCP (Model Context Protocol)** integration, it supports stdio, HTTP, SSE, and dual transport modes.

> Perfect for time-sensitive applications requiring fast, reliable timezone conversions
> with **sub-millisecond response times** and multiple client interface options.

### Docker Gateway Integration

#### Running fast-time-server for Gateway Registration

```bash
# 1️⃣ Start fast-time-server in SSE mode for direct gateway registration
docker run --rm -d --name fast-time-server \
  -p 8888:8080 \
  ghcr.io/ibm/fast-time-server:latest \
  -transport=sse -listen=0.0.0.0 -port=8080 -log-level=debug

# 2️⃣ Register with gateway (gateway running on host)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"docker_fast_time","url":"http://host.docker.internal:8888/sse"}' \
     http://localhost:4444/gateways
```

#### Docker Compose Setup

Create `docker-compose.yml` for integrated testing:

```yaml
version: '3.8'
services:
  mcpgateway:
    image: ghcr.io/ibm/mcp-context-forge:latest
    ports:
      - "4444:4444"
    environment:
      BASIC_AUTH_PASSWORD: pass
      JWT_SECRET_KEY: my-test-key
    command: mcpgateway --host 0.0.0.0 --port 4444

  fast-time-server:
    image: ghcr.io/ibm/fast-time-server:latest
    ports:
      - "8888:8080"
    command: ["-transport=sse", "-listen=0.0.0.0", "-port=8080", "-log-level=debug"]
    depends_on:
      - mcpgateway

  wrapper-test:
    image: ghcr.io/ibm/mcp-context-forge:latest
    environment:
      MCP_AUTH_TOKEN: "${MCPGATEWAY_BEARER_TOKEN}"
      MCP_SERVER_CATALOG_URLS: "http://mcpgateway:4444/servers/UUID_OF_SERVER_1"
      MCP_WRAPPER_LOG_LEVEL: DEBUG
    command: python3 -m mcpgateway.wrapper
    depends_on:
      - mcpgateway
      - fast-time-server
    stdin_open: true
    tty: true
```

Run the complete stack:

```bash
# Generate token
export MCPGATEWAY_BEARER_TOKEN=$(docker run --rm ghcr.io/ibm/mcp-context-forge:latest \
  python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 10080 --secret my-test-key)

# Start services
docker-compose up -d mcpgateway fast-time-server

# Register fast-time-server
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"docker_time","url":"http://fast-time-server:8080/sse"}' \
     http://localhost:4444/gateways

# Test wrapper
docker-compose run wrapper-test
```

### Container Networking Notes

!!! tip "Docker Networking"
    - Use `host.docker.internal` when gateway runs on host and server in container
    - Use service names when both run in same Docker Compose network
    - Map ports consistently: `-p 8888:8080` maps host port 8888 to container port 8080

---

## 🔑 Key Features

* **⚡ Ultra-fast** - Written in Go for minimal latency and high throughput
* **🌍 Timezone-aware** - IANA timezone support with DST handling
* **🚀 Multiple transports** - stdio, HTTP, SSE, and dual-mode support
* **🔐 Secure** - Bearer token authentication for SSE endpoints
* **📊 Production-ready** - Built-in benchmarking, logging, and health checks
* **🐳 Docker-native** - Pre-built container images available

---

## 🚀 Quick Start

### Docker (Recommended)

Run with dual transport mode (HTTP + SSE on port 8080):

```bash
docker run --rm -it -p 8888:8080 \
  ghcr.io/ibm/fast-time-server:latest \
  -transport=dual -log-level=debug
```

!!! tip "Port Mapping"
    The example maps host port `8888` to container port `8080`. Adjust as needed for your environment.

### Alternative Transport Modes

=== "HTTP Only"

    ```bash
    docker run --rm -p 8080:8080 \
      ghcr.io/ibm/fast-time-server:latest \
      -transport=http -addr=0.0.0.0:8080
    ```

=== "SSE Only"

    ```bash
    docker run --rm -p 8080:8080 \
      ghcr.io/ibm/fast-time-server:latest \
      -transport=sse -listen=0.0.0.0 -port=8080
    ```

=== "SSE with Auth"

    ```bash
    docker run --rm -p 8080:8080 \
      -e AUTH_TOKEN=your-secret-token \
      ghcr.io/ibm/fast-time-server:latest \
      -transport=sse -listen=0.0.0.0 -port=8080 -auth-token=your-secret-token
    ```

=== "STDIO (MCP Default)"

    ```bash
    docker run --rm -i \
      ghcr.io/ibm/fast-time-server:latest \
      -transport=stdio
    ```

---

## 🛠 Building from Source

### Prerequisites

- **Go 1.21+** installed
- **Git** for cloning the repository
- **Make** for build automation

### Clone and Build

```bash
# Clone the MCP servers repository
git clone https://github.com/IBM/mcp-context-forge
cd mcp-servers/go/fast-time-server

# Install dependencies and build
make tidy
make build

# Binary will be in ./dist/fast-time-server
```

### Development Commands

=== "Build & Test"

    ```bash
    make build          # Build binary into ./dist
    make test           # Run unit tests with race detection
    make coverage       # Generate HTML coverage report
    make install        # Install to GOPATH/bin
    ```

=== "Code Quality"

    ```bash
    make fmt            # Format code (gofmt + goimports)
    make vet            # Run go vet
    make lint           # Run golangci-lint
    make staticcheck    # Run staticcheck
    make pre-commit     # Run all pre-commit hooks
    ```

=== "Cross-Compilation"

    ```bash
    # Build for different platforms
    GOOS=linux GOARCH=amd64 make release
    GOOS=darwin GOARCH=arm64 make release
    GOOS=windows GOARCH=amd64 make release
    ```

---

## 🏃 Running Locally

### Local Development

```bash
# Quick run with stdio transport
make run

# Run specific transport modes
make run-http    # HTTP on :8080
make run-sse     # SSE on :8080
make run-dual    # Both HTTP & SSE on :8080
```

### Manual Execution

```bash
# After building with make build
./dist/fast-time-server -transport=dual -port=8080 -log-level=info
```

---

## 🐳 Docker Development

### Build Your Own Image

```bash
make docker-build
```

### Development Containers

=== "HTTP Development"

    ```bash
    make docker-run
    # Runs HTTP transport on localhost:8080
    ```

=== "SSE Development"

    ```bash
    make docker-run-sse
    # Runs SSE transport on localhost:8080
    ```

=== "Authenticated SSE"

    ```bash
    make docker-run-sse-auth TOKEN=my-dev-token
    # Runs SSE with Bearer token authentication
    ```

---

## ⚙️ Configuration Options

| Flag | Description | Default | Example |
|------|-------------|---------|---------|
| `-transport` | Transport mode: `stdio`, `http`, `sse`, `dual` | `stdio` | `-transport=dual` |
| `-addr` | HTTP bind address | `:8080` | `-addr=0.0.0.0:8080` |
| `-listen` | SSE listen address | `localhost` | `-listen=0.0.0.0` |
| `-port` | Port for SSE/dual mode | `8080` | `-port=9000` |
| `-auth-token` | Bearer token for SSE authentication | - | `-auth-token=secret123` |
| `-log-level` | Logging level: `debug`, `info`, `warn`, `error` | `info` | `-log-level=debug` |

---

## 📡 API Endpoints

### HTTP Transport (`-transport=http` or `-transport=dual`)

**POST** `/http` - JSON-RPC endpoint

```bash
curl -X POST http://localhost:8080/http \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "get_system_time",
    "params": {
      "timezone": "Europe/Dublin"
    }
  }'
```

### SSE Transport (`-transport=sse` or `-transport=dual`)

**GET** `/sse` - Server-Sent Events stream
**POST** `/messages` - Send JSON-RPC messages

```bash
# Connect to SSE stream
curl -N http://localhost:8080/sse

# Send message (in another terminal)
curl -X POST http://localhost:8080/messages \
  -H "Content-Type: application/json" \
  -d '{"method":"get_system_time","params":{"timezone":"UTC"}}'
```

### STDIO Transport (`-transport=stdio`)

Standard MCP JSON-RPC over stdin/stdout:

```json
{"jsonrpc":"2.0","id":1,"method":"get_system_time","params":{"timezone":"America/New_York"}}
```

---

## 🧪 Testing & Benchmarking

### Unit Tests

```bash
make test           # Run all tests
make coverage       # Generate coverage report
```

### Load Testing

Start the server in dual mode:

```bash
make run-dual
```

Run benchmark (requires [hey](https://github.com/rakyll/hey)):

```bash
make bench
# Runs 100,000 requests with 100 concurrent connections
```

### Manual Performance Test

```bash
# Create a test payload
echo '{"jsonrpc":"2.0","id":1,"method":"get_system_time","params":{"timezone":"UTC"}}' > payload.json

# Run load test
hey -m POST -T 'application/json' -D payload.json -n 10000 -c 50 http://localhost:8080/http
```

---

## 🌐 MCP Gateway Integration

### Registering with MCP Gateway

The fast-time-server can be registered with an MCP Gateway to expose its tools through the gateway's federated API.

#### Method 1: Using Supergateway (Recommended)

```bash
# 1️⃣ Start the Gateway (if not already running)
pip install mcp-contextforge-gateway
BASIC_AUTH_PASSWORD=pass JWT_SECRET_KEY=my-test-key \
  mcpgateway --host 0.0.0.0 --port 4444 &

# 2️⃣ Expose fast-time-server via supergateway
pip install uv
npx -y supergateway --stdio "./dist/fast-time-server -transport=stdio" --port 8002 &

# 3️⃣ Register with the gateway
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin --exp 10080 --secret my-test-key)

curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"fast_time","url":"http://localhost:8002/sse"}' \
     http://localhost:4444/gateways

# 4️⃣ Create a virtual server with the time tools
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"time_server","description":"Fast time tools","associatedTools":["1","2"]}' \
     http://localhost:4444/servers
```

#### Method 2: Direct SSE Registration

```bash
# 1️⃣ Start fast-time-server in SSE mode
./dist/fast-time-server -transport=sse -port=8003

# 2️⃣ Register directly with the gateway
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"fast_time_direct","url":"http://localhost:8003/sse"}' \
     http://localhost:4444/gateways
```

### Testing with mcpgateway.wrapper

The `mcpgateway.wrapper` bridges gateway tools to stdio, perfect for testing and MCP client integration:

```bash
# 1️⃣ Set up environment variables
export MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN
export MCP_SERVER_CATALOG_URLS='http://localhost:4444/servers/UUID_OF_SERVER_1'
export MCP_TOOL_CALL_TIMEOUT=120
export MCP_WRAPPER_LOG_LEVEL=DEBUG

# 2️⃣ Start the wrapper (manual testing)
python3 -m mcpgateway.wrapper

# 3️⃣ Test MCP protocol manually
# Initialize
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | python3 -m mcpgateway.wrapper

# List tools
echo '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python3 -m mcpgateway.wrapper

# Call get_system_time
echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_system_time","arguments":{"timezone":"Europe/Dublin"}}}' | python3 -m mcpgateway.wrapper
```

### Testing with mcpgateway.translate

Use `mcpgateway.translate` to bridge stdio servers to SSE endpoints:

```bash
# 1️⃣ Bridge fast-time-server (stdio) to SSE on port 9000
python3 -m mcpgateway.translate \
  --stdio "./dist/fast-time-server -transport=stdio" \
  --port 9000

# 2️⃣ In another terminal, connect to the SSE stream
curl -N http://localhost:9000/sse

# 3️⃣ Send test requests (in a third terminal)
# Initialize
curl -X POST http://localhost:9000/message \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# List tools
curl -X POST http://localhost:9000/message \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# Call get_system_time
curl -X POST http://localhost:9000/message \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_system_time","arguments":{"timezone":"Asia/Tokyo"}}}'
```

### MCP Inspector Integration

Test your gateway setup with MCP Inspector:

```bash
# 1️⃣ Direct fast-time-server inspection
npx @modelcontextprotocol/inspector ./dist/fast-time-server

# 2️⃣ Inspect via gateway wrapper
npx @modelcontextprotocol/inspector python3 -m mcpgateway.wrapper
# Environment: MCP_AUTH_TOKEN, MCP_SERVER_CATALOG_URLS

# 3️⃣ Inspect SSE endpoint directly
npx @modelcontextprotocol/inspector
# Transport: SSE
# URL: http://localhost:4444/servers/UUID_OF_SERVER_1/sse
# Header: Authorization
# Value: Bearer <your-token>
```

---

## 🔌 MCP Client Integration

### Claude Desktop

Add to your `claude_desktop_config.json`:

=== "Direct Integration"

    ```json
    {
      "mcpServers": {
        "fast-time-server": {
          "command": "/path/to/fast-time-server",
          "args": ["-transport=stdio"],
          "env": {}
        }
      }
    }
    ```

=== "Via Gateway Wrapper"

    ```json
    {
      "mcpServers": {
        "gateway-time": {
          "command": "python3",
          "args": ["-m", "mcpgateway.wrapper"],
          "env": {
            "MCP_AUTH_TOKEN": "<your-bearer-token>",
            "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/UUID_OF_SERVER_1"
          }
        }
      }
    }
    ```

=== "Docker with MCP Client"

    ```json
    {
      "mcpServers": {
        "fast-time-server": {
          "command": "docker",
          "args": [
            "run", "--rm", "-i",
            "ghcr.io/ibm/fast-time-server:latest",
            "-transport=stdio"
          ]
        }
      }
    }
    ```

### Continue/Cline Integration

For VS Code extensions:

```json
{
  "mcpServers": {
    "fast-time-server": {
      "command": "/path/to/fast-time-server",
      "args": ["-transport=stdio", "-log-level=info"],
      "env": {}
    }
  }
}
```

### Gateway Workflow Examples

#### Complete End-to-End Test

```bash
# 1️⃣ Start Gateway
BASIC_AUTH_PASSWORD=pass JWT_SECRET_KEY=my-test-key mcpgateway --host 0.0.0.0 --port 4444 &

# 2️⃣ Start fast-time-server via supergateway
npx -y supergateway --stdio "./dist/fast-time-server -transport=stdio" --port 8002 &

# 3️⃣ Generate token and register
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 10080 --secret my-test-key)

curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"fast_time","url":"http://localhost:8002/sse"}' \
     http://localhost:4444/gateways

# 4️⃣ Verify tools are available
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/tools | jq

# 5️⃣ Create virtual server
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"time_server","description":"Fast time tools","associatedTools":["1"]}' \
     http://localhost:4444/servers

# 6️⃣ Test via wrapper
export MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN
export MCP_SERVER_CATALOG_URLS='http://localhost:4444/servers/UUID_OF_SERVER_1'
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_system_time","arguments":{"timezone":"UTC"}}}' | python3 -m mcpgateway.wrapper
```

#### Expected Gateway Responses

When testing with the wrapper, you should see responses like:

```json
// Tool listing response
{
  "jsonrpc":"2.0","id":2,
  "result":{
    "tools":[
      {
        "name":"get_system_time",
        "description":"Get current time in a specific timezone",
        "inputSchema":{
          "type":"object",
          "properties":{
            "timezone":{
              "type":"string",
              "description":"IANA timezone name (e.g., 'America/New_York', 'Europe/London')"
            }
          },
          "required":["timezone"]
        }
      }
    ]
  }
}

// Tool execution response
{
  "jsonrpc":"2.0","id":3,
  "result":{
    "content":[
      {
        "type":"text",
        "text":"{\"timezone\":\"UTC\",\"datetime\":\"2025-07-08T21:30:15Z\",\"is_dst\":false}"
      }
    ],
    "isError":false
  }
}
```

---

## 💡 Usage Examples

### Get Current Time

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "get_system_time",
  "params": {
    "timezone": "Europe/Dublin"
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"timezone\":\"Europe/Dublin\",\"datetime\":\"2025-07-08T22:30:15+01:00\",\"is_dst\":true}"
      }
    ],
    "isError": false
  }
}
```

### Common Timezones

| Region | Timezone | Example |
|--------|----------|---------|
| 🇺🇸 US East | `America/New_York` | `2025-07-08T17:30:15-04:00` |
| 🇺🇸 US West | `America/Los_Angeles` | `2025-07-08T14:30:15-07:00` |
| 🇬🇧 UK | `Europe/London` | `2025-07-08T22:30:15+01:00` |
| 🇮🇪 Ireland | `Europe/Dublin` | `2025-07-08T22:30:15+01:00` |
| 🇯🇵 Japan | `Asia/Tokyo` | `2025-07-09T06:30:15+09:00` |
| 🌍 UTC | `UTC` | `2025-07-08T21:30:15Z` |

---

## 🧹 Maintenance

### Cleanup

```bash
make clean          # Remove build artifacts
docker system prune # Clean up Docker images/containers
```

### Updates

```bash
git pull            # Update source code
make tools          # Update Go tools (golangci-lint, staticcheck)
make tidy           # Update Go dependencies
```

---

## 🚨 Troubleshooting

### Common Issues

!!! warning "Port Already in Use"
    ```bash
    Error: bind: address already in use
    ```
    **Solution:** Change the port with `-port=9000` or kill the existing process.

!!! warning "Docker Permission Denied"
    ```bash
    docker: permission denied
    ```
    **Solution:** Add your user to the docker group or use `sudo`.

!!! warning "SSE Authentication Failed"
    ```bash
    401 Unauthorized
    ```
    **Solution:** Ensure you're passing the correct `-auth-token` and including `Authorization: Bearer <token>` in requests.

### Debug Mode

Enable verbose logging:

```bash
./fast-time-server -transport=dual -log-level=debug
```

### Gateway Integration Issues

!!! warning "Gateway Registration Failed"
    ```bash
    Error: Connection refused to http://localhost:4444
    ```
    **Solution:** Ensure the MCP Gateway is running on the correct port and check firewall settings.

!!! warning "Wrapper Authentication Failed"
    ```bash
    HTTP 401: Unauthorized
    ```
    **Solution:** Verify your `MCP_AUTH_TOKEN` is valid and not expired:
    ```bash
    curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" http://localhost:4444/version
    ```

!!! warning "No Tools Available in Wrapper"
    ```bash
    {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}
    ```
    **Solution:** Check that:
    1. fast-time-server is registered with the gateway
    2. A virtual server exists with associated tools
    3. `MCP_SERVER_CATALOG_URLS` points to the correct server ID

!!! warning "Supergateway Not Found"
    ```bash
    npx: command not found
    ```
    **Solution:** Install Node.js and npm:
    ```bash
    # Ubuntu/Debian
    sudo apt install nodejs npm

    # macOS
    brew install node
    ```

!!! warning "mcpgateway.translate Connection Issues"
    ```bash
    Error: Process terminated unexpectedly
    ```
    **Solution:** Check that the stdio command is correct and the binary exists:
    ```bash
    # Test the command directly first
    ./dist/fast-time-server -transport=stdio
    ```

### Testing Connectivity

Verify each component is working:

```bash
# 1. Test fast-time-server directly
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ./dist/fast-time-server -transport=stdio | jq

# 2. Test gateway API
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/health

# 3. Test wrapper connectivity
export MCP_WRAPPER_LOG_LEVEL=DEBUG
python3 -m mcpgateway.wrapper
```

---

## 📚 Further Reading

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [IANA Time Zone Database](https://www.iana.org/time-zones)
- [Go Time Package Documentation](https://pkg.go.dev/time)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)
