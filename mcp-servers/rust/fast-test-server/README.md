# Fast Test Server (Rust)

Ultra-fast MCP server written in Rust for performance testing and benchmarking. Uses the official [Rust MCP SDK](https://github.com/modelcontextprotocol/rust-sdk).

## Features

- **Blazing fast**: Native Rust performance with zero-copy where possible
- **Streamable HTTP**: Modern HTTP transport with streaming support
- **Minimal overhead**: No auth, no database, pure compute
- **Three tools**:
  - `echo` - Echoes back the provided message
  - `get_system_time` - Returns current time in specified timezone
  - `get_stats` - Returns server statistics

## Quick Start

```bash
# Build and run
make run

# Or release build for benchmarking
make run-release
```

Server starts at `http://localhost:9080/mcp`

## Testing

```bash
# List available tools
make test-tools

# Test echo
make test-echo

# Test time
make test-time
```

Or with curl:

```bash
# Initialize (optional for stateless requests)
curl -X POST http://localhost:9080/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"clientInfo":{"name":"test","version":"1.0"}},"id":1}'

# List tools
curl -X POST http://localhost:9080/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Call echo tool
curl -X POST http://localhost:9080/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"echo","arguments":{"message":"Hello!"}},"id":1}'

# Call get_system_time tool
curl -X POST http://localhost:9080/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_system_time","arguments":{"timezone":"America/New_York"}},"id":1}'
```

## Benchmarking

The server includes REST API endpoints that bypass MCP session overhead for accurate benchmarking:

```bash
# Install hey
go install github.com/rakyll/hey@latest

# Run full benchmark (1M requests, 200 concurrent)
make bench

# Quick benchmark (100K requests)
make bench-quick

# Individual endpoints
make bench-echo   # POST /api/echo
make bench-time   # GET /api/time
```

### Benchmark Results (REST API with hey)

On a typical development machine:

| Endpoint | Requests/sec | Latency p99 |
|----------|-------------|-------------|
| `/api/echo` | ~175,000 | 6ms |
| `/api/time` | ~181,000 | 6ms |

## Locust Load Testing (MCP Protocol)

For proper MCP protocol testing with session management, use Locust:

```bash
# Install locust
pip install locust

# Start the server
make run-release

# In another terminal - Web UI (recommended)
make locust-ui
# Open http://localhost:8089, select user classes

# Headless test (100 users, 60s)
make locust

# Stress test (500 users, 120s)
make locust-stress

# Compare MCP vs REST performance
make locust-compare
```

### User Classes

| Class | Weight | Description |
|-------|--------|-------------|
| `RustMCPUser` | 10 | MCP protocol via Streamable HTTP |
| `RustMCPStressUser` | 1 | High-frequency MCP stress test |
| `RustRESTUser` | 5 | REST API baseline comparison |

## Docker

```bash
# Build image
make docker-build

# Run container
make docker-run
```

## Endpoints

### REST API (for benchmarking)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/echo` | POST | Echo `{"message":"..."}` - pure performance test |
| `/api/time` | GET | Get time, optional `?tz=America/New_York` |
| `/health` | GET | Health check |
| `/version` | GET | Version info |

### MCP Protocol

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | POST | MCP JSON-RPC (requires session management) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BIND_ADDRESS` | `0.0.0.0:9080` | Address to bind to |
| `RUST_LOG` | `info` | Log level (trace, debug, info, warn, error) |

## Supported Timezones

The `get_system_time` tool supports:

- UTC, GMT
- IANA timezone names (e.g., `America/New_York`, `Europe/London`, `Asia/Tokyo`)
- Fixed offsets (e.g., `+05:30`, `-08:00`)

## Comparison with Go Server

This server is designed to be compared with the Go `fast-time-server` for benchmarking purposes. Both implement similar functionality with the same transport (streamable HTTP).

## License

Apache-2.0
