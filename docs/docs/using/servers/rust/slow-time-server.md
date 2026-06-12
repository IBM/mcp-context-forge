# Rust Slow Time Server

## Overview

The **slow-time-server** is a Rust MCP test fixture for timeout, retry,
circuit-breaker, session-pool, and load-testing scenarios. It replaces the
previous Go slow-time-server implementation.

This server is intentionally a test utility. Do not expose it outside a trusted
test network.

## Transport

The Rust server exposes MCP JSON-RPC over Streamable HTTP:

- `POST /mcp` - canonical MCP endpoint
- `POST /` - compatibility alias for MCP JSON-RPC requests

SSE and the old Go HTTP endpoint are not available in the Rust implementation.
Use `/mcp` instead of the old `/http` endpoint.

## Tools

| Tool | Description |
| ---- | ----------- |
| `get_slow_time` | Returns current time after configured or requested delay. |
| `convert_slow_time` | Converts a timestamp between timezones after a delay. |
| `get_instant_time` | Returns current time without artificial delay. |
| `get_timeout_time` | Sleeps for the maximum delay to exercise timeout handling. |
| `get_flaky_time` | Returns a simulated failure according to `FAILURE_RATE`. |

`get_slow_time` and `convert_slow_time` accept both `delay_ms` and
`delay_seconds`. `delay_ms` takes precedence when both are provided. Delays are
capped at 10 minutes.

## HTTP Endpoints

| Endpoint | Description |
| -------- | ----------- |
| `POST /mcp` | MCP JSON-RPC endpoint. |
| `POST /` | MCP JSON-RPC alias. |
| `GET /health` | Instant health check. |
| `GET /version` | Version metadata. |
| `GET /api/v1/time?timezone=UTC&delay=250ms` | REST time helper with delay. |
| `GET /api/v1/config` | Current latency configuration. |
| `GET /api/v1/stats` | Request and failure counters. |
| `GET /api/v1/test/echo?message=hello` | Echo helper for connectivity tests. |

## Configuration

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `BIND_ADDRESS` | `0.0.0.0:8081` | Bind address. |
| `DEFAULT_LATENCY` | `5s` | Default delay for slow tools. Supports `ms`, `s`, and `m`. |
| `FAILURE_RATE` | `0.0` | Failure probability for `get_flaky_time`, from `0.0` to `1.0`. |
| `RUST_LOG` | `info` | Logging level. |

## Run

```bash
cd mcp-servers/rust/slow-time-server
make run
```

The repository resilience profile exposes the server on port `8889`:

```bash
make resilience-up
curl -s http://localhost:8889/health
```

## MCP Examples

List tools:

```bash
curl -s http://localhost:8081/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Call the slow time tool with millisecond delay:

```bash
curl -s http://localhost:8081/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get_slow_time",
      "arguments": {"timezone": "UTC", "delay_ms": 100}
    }
  }'
```

Call the slow time tool with second delay:

```bash
curl -s http://localhost:8081/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get_slow_time",
      "arguments": {"timezone": "UTC", "delay_seconds": 0.25}
    }
  }'
```

## Migration From Go

This is a full replacement for the Go slow-time-server.

Removed Go endpoints and modes:

- `/sse`
- `/messages`
- `/http`
- `/api/v1/docs`
- `/api/v1/openapi.json`
- stdio, SSE, dual, and REST-only transport modes

Current Rust replacements:

- Use `POST /mcp` for MCP JSON-RPC.
- Use `/health` for container and compose health checks.
- Use `/api/v1/time`, `/api/v1/config`, and `/api/v1/stats` for REST test helpers.
- Build containers with `mcp-servers/rust/slow-time-server/Containerfile`.

The old Go binary health-check flags are removed. Container health checks now
call `curl -sf http://localhost:8081/health`, so the runtime image includes
`curl`.

## Validation

```bash
cargo fmt --check -p slow-time-server
cargo test -p slow-time-server
cargo clippy -p slow-time-server -- -D warnings
```
