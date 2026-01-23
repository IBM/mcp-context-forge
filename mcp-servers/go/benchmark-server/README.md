# Benchmark MCP Server

> Author: Mihai Criveti

A configurable MCP (Model Context Protocol) server written in Go for benchmarking and load testing. This server can dynamically generate an arbitrary number of tools, resources, and prompts to help you test MCP gateway performance, client behavior, and scalability.

## Features

- **Configurable Scale**: Generate from 1 to 10,000+ tools, resources, and prompts
- **Multiple Transports**: Supports stdio, SSE, and HTTP transports
- **Multi-Server Mode**: Spawn multiple server instances on sequential ports for pagination testing
- **Adjustable Payloads**: Configure response payload sizes for different test scenarios
- **Authentication**: Optional Bearer token authentication for SSE/HTTP
- **Graceful Shutdown**: Proper signal handling (Ctrl+C) with connection draining
- **Fast Performance**: Written in Go for minimal overhead and maximum throughput
- **Standards Compliant**: Fully implements MCP 1.0 specification

## Quick Start

### Build

```bash
make build
```

### Run with Default Settings (100 items each)

```bash
make run
```

### Run with Custom Configuration

```bash
# Small test (10 items each)
./dist/benchmark-server -tools=10 -resources=10 -prompts=10

# Medium test (100 items)
./dist/benchmark-server -tools=100 -resources=100 -prompts=100

# Large test (1000 items)
./dist/benchmark-server -tools=1000 -resources=1000 -prompts=1000

# Extra large test (10000 items)
./dist/benchmark-server -tools=10000 -resources=10000 -prompts=10000

# Custom payload size
./dist/benchmark-server -tools=500 -payload-size=5000
```

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `-transport` | `stdio` | Transport type: `stdio`, `sse`, or `http` |
| `-server-count` | `1` | Number of servers to spawn (for multi-server testing) |
| `-start-port` | `8080` | Starting port for multi-server mode |
| `-tools` | `100` | Number of tools to generate |
| `-resources` | `100` | Number of resources to generate |
| `-prompts` | `100` | Number of prompts to generate |
| `-tool-size` | `1000` | Size of tool response payload in bytes |
| `-resource-size` | `1000` | Size of resource response payload in bytes |
| `-prompt-size` | `1000` | Size of prompt response payload in bytes |
| `-port` | `8080` | TCP port for SSE/HTTP transport (single server mode) |
| `-listen` | `0.0.0.0` | Listen interface for SSE/HTTP |
| `-addr` | - | Full listen address (overrides `-listen`/`-port`) |
| `-public-url` | - | External base URL for SSE clients |
| `-auth-token` | - | Bearer token for authentication |
| `-log-level` | `info` | Logging level: `debug`, `info`, `warn`, `error`, `none` |

## Usage Examples

### STDIO Transport (Claude Desktop)

```bash
# Basic stdio with default settings
./dist/benchmark-server

# With custom scale
./dist/benchmark-server -tools=1000 -resources=500 -prompts=200

# Custom payload sizes per type
./dist/benchmark-server -tools=100 -tool-size=5000 -resource-size=10000 -prompt-size=2000

# Silent mode for production
./dist/benchmark-server -log-level=none -tools=5000
```

### SSE Transport (Web Clients)

```bash
# Basic SSE server
./dist/benchmark-server -transport=sse -port=8080

# With authentication
./dist/benchmark-server -transport=sse -port=8080 -auth-token=secret123

# Public-facing server
./dist/benchmark-server -transport=sse -listen=0.0.0.0 -port=8080 \
  -public-url=https://benchmark.example.com
```

### Multi-Server Mode (Pagination Testing)

```bash
# Spawn 10 identical SSE servers on ports 8080-8089
./dist/benchmark-server -transport=sse -server-count=10 -start-port=8080 -tools=100

# Spawn 5 HTTP servers on ports 9000-9004
./dist/benchmark-server -transport=http -server-count=5 -start-port=9000

# Large scale: 20 servers with 1000 tools each
./dist/benchmark-server -transport=sse -server-count=20 -start-port=8080 \
  -tools=1000 -resources=500 -prompts=200

# Shutdown all servers gracefully with Ctrl+C
# Each server will complete in-flight requests before stopping
```

**Use Cases:**
- Test MCP gateway pagination when listing servers
- Simulate federated MCP deployments
- Load balancing across multiple backend servers
- High availability testing

**Note:** Multi-server mode is only available for `sse` and `http` transports. The `stdio` transport does not support multi-server mode.

### HTTP Transport (REST-like)

```bash
# Basic HTTP server
./dist/benchmark-server -transport=http -port=9090

# With custom configuration
./dist/benchmark-server -transport=http -port=9090 \
  -tools=1000 -payload-size=2000 -auth-token=test123
```

## Integration Examples

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "benchmark": {
      "command": "/path/to/benchmark-server",
      "args": ["-tools=1000", "-resources=500", "-prompts=200"]
    }
  }
}
```

### Testing with curl

```bash
# Test HTTP transport
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Test with authentication
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer secret123" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Call a specific tool
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"benchmark_tool_0","arguments":{"param1":"test"}},"id":2}'
```

### SSE Client Example

```bash
# Connect to SSE endpoint (streams events)
curl -N http://localhost:8080/sse

# Send messages (in another terminal)
curl -X POST http://localhost:8080/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

## Makefile Targets

```bash
make help         # Show all available targets
make tidy         # Download and tidy dependencies
make fmt          # Format Go code
make test         # Run tests
make build        # Build the binary
make run          # Build and run with defaults
make run-small    # Run with 10 items each
make run-medium   # Run with 100 items each
make run-large    # Run with 1000 items each
make run-xlarge   # Run with 10000 items each
make run-sse      # Run with SSE transport
make run-http     # Run with HTTP transport
make clean        # Remove build artifacts
```

## Benchmarking Scenarios

### Gateway Performance Testing

Test how many tools/resources your MCP gateway can handle:

```bash
# Start with moderate load
./dist/benchmark-server -tools=1000 -resources=1000 -prompts=500

# Increase to stress test
./dist/benchmark-server -tools=10000 -resources=10000 -prompts=5000
```

### Payload Size Testing

Test gateway behavior with different payload sizes:

```bash
# Small payloads (1KB each)
./dist/benchmark-server -tools=100 -tool-size=1000 -resource-size=1000 -prompt-size=1000

# Medium payloads (10KB each)
./dist/benchmark-server -tools=100 -tool-size=10000 -resource-size=10000 -prompt-size=10000

# Large payloads (100KB each)
./dist/benchmark-server -tools=100 -tool-size=100000 -resource-size=100000 -prompt-size=100000

# Mixed sizes: Large tools, small resources
./dist/benchmark-server -tools=100 -tool-size=50000 -resources=100 -resource-size=500 -prompts=50 -prompt-size=2000
```

### Client Discovery Testing

Test how clients handle large tool listings:

```bash
# Maximum scale test
./dist/benchmark-server -tools=50000 -resources=50000 -prompts=10000
```

## API Response Format

### Tool Response

```json
{
  "tool": "benchmark_tool_0",
  "timestamp": "2025-10-11T12:34:56Z",
  "arguments": {
    "param1": "value1",
    "param2": "value2"
  },
  "data": "Response from benchmark_tool_0. This is benchmark data..."
}
```

### Resource Response

```json
{
  "resource": "benchmark_resource_0",
  "timestamp": "2025-10-11T12:34:56Z",
  "data": "Response from benchmark_resource_0. This is benchmark data..."
}
```

### Prompt Response

```
Prompt: benchmark_prompt_0

Timestamp: 2025-10-11T12:34:56Z

Arguments:
  - arg1: value1
  - arg2: value2

Response from benchmark_prompt_0. This is benchmark data...
```

## Environment Variables

- `AUTH_TOKEN`: Bearer token for authentication (overrides `-auth-token` flag)

## Health and Version Endpoints

When running in SSE or HTTP mode, the following endpoints are available:

- `/health`: Returns server health status and uptime
- `/version`: Returns server name, version, and MCP protocol version

Example:

```bash
curl http://localhost:8080/health
# {"status":"healthy","uptime_seconds":123}

curl http://localhost:8080/version
# {"name":"benchmark-server","version":"1.0.0","mcp_version":"1.0"}
```

## Docker

### Build Docker Image

```bash
docker build -t benchmark-server .
```

### Run with Docker

```bash
# STDIO mode (not useful in Docker)
docker run -it benchmark-server

# SSE mode
docker run -p 8080:8080 benchmark-server \
  -transport=sse -port=8080 -tools=1000

# HTTP mode with custom configuration
docker run -p 9090:9090 benchmark-server \
  -transport=http -port=9090 \
  -tools=5000 -resources=2000 -prompts=1000 \
  -payload-size=2000
```

## Performance Considerations

### Memory Usage

Each item (tool/resource/prompt) consumes minimal memory. Approximate memory usage:

- 1,000 items: ~10MB
- 10,000 items: ~50MB
- 100,000 items: ~300MB

### Response Times

With default payload size (1KB):

- Tool listing: <10ms for 1,000 items, <100ms for 10,000 items
- Tool invocation: <5ms per call
- Resource access: <5ms per call
- Prompt generation: <5ms per call

### Scalability

The server can handle:

- Up to 100,000 tools/resources/prompts
- Concurrent requests limited only by system resources
- Payload sizes from 1 byte to 10MB+

## License

Apache-2.0

## Contributing

This is a benchmarking tool for the MCP Context Forge project. Contributions are welcome!
