# Slow Time Server (Rust)

Configurable-latency MCP test server for timeout, resilience, circuit-breaker,
session-pool, and load-testing scenarios.

This is the Rust counterpart for the Go `mcp-servers/go/slow-time-server`.
It is intentionally a test utility, not a production MCP server.

## Tools

| Tool | Description |
| ---- | ----------- |
| `get_slow_time` | Returns current time after configured or requested delay. |
| `convert_slow_time` | Converts a timestamp between timezones after a delay. |
| `get_instant_time` | Returns current time without artificial delay. |
| `get_timeout_time` | Sleeps for the maximum delay to exercise gateway timeout handling. |
| `get_flaky_time` | Returns a simulated failure according to `FAILURE_RATE`. |

## Run

```bash
make run
```

The server listens on `0.0.0.0:8081` by default and exposes MCP Streamable HTTP
at `/mcp`.

## Configuration

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `BIND_ADDRESS` | `0.0.0.0:8081` | Bind address. |
| `DEFAULT_LATENCY` | `5s` | Default delay for slow tools. Supports `ms`, `s`, and `m`. |
| `FAILURE_RATE` | `0.0` | Failure probability for `get_flaky_time`, from `0.0` to `1.0`. |
| `RUST_LOG` | `info` | Logging level. |

Delays are capped at 10 minutes to preserve resilience-test behavior without
allowing unbounded sleeps.

## HTTP Endpoints

| Endpoint | Description |
| -------- | ----------- |
| `POST /mcp` | MCP JSON-RPC endpoint. |
| `GET /health` | Instant health check. |
| `GET /version` | Version metadata. |
| `GET /api/v1/time?timezone=UTC&delay=250ms` | REST time helper with delay. |
| `GET /api/v1/config` | Current latency configuration. |
| `GET /api/v1/stats` | Request and failure counters. |

## Examples

```bash
curl -s http://localhost:8081/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

```bash
curl -s http://localhost:8081/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_slow_time","arguments":{"timezone":"UTC","delay_ms":100}}}'
```

## Validation

```bash
make test
make clippy
```
