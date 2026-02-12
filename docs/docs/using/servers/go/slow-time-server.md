# Go Slow Time Server

## Overview

The **slow-time-server** is a configurable-latency Go-based MCP server designed for timeout, resilience, and load testing. Modelled on the [fast-time-server](fast-time-server.md), it introduces artificial latency on every tool call and serves as a testing target for:

- **Gateway timeout enforcement** -- verify that per-tool `timeout_ms` overrides work correctly
- **Circuit breaker behaviour** -- trigger and observe circuit breaker state transitions
- **Session pool resilience** -- stress-test connection pools under slow-response conditions
- **Load testing** -- simulate realistic slow-tool scenarios with configurable latency distributions

**Key Highlights:**

- Configurable latency: fixed, uniform, normal, or exponential distributions
- 5 MCP tools with different latency profiles (instant, slow, timeout, flaky)
- Runtime reconfiguration via REST API
- Failure simulation with configurable rate and mode
- Invocation statistics with p50/p95/p99 percentiles
- Single static binary (~2 MiB), scratch Docker image

## Installation

### Using Docker Compose (Recommended)

The slow-time-server is included in the `testing` profile:

```bash
docker compose --profile testing up -d
```

This starts the server on port **8889** (mapped from container port 8081) and automatically registers it with the gateway.

### From Source

```bash
cd mcp-servers/go/slow-time-server
make build
./dist/slow-time-server -transport=dual -port=8081 -latency=5s
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SLOW_TIME_LATENCY` | `5s` | Default tool latency (docker-compose) |
| `SLOW_TIME_FAILURE_RATE` | `0.0` | Failure probability for flaky tool (docker-compose) |
| `DEFAULT_LATENCY` | `5s` | Default tool latency (direct) |
| `FAILURE_RATE` | `0.0` | Failure probability (direct) |
| `AUTH_TOKEN` | | Bearer token for authentication |

## Transport Modes

### 1. STDIO Mode (Default)
For desktop MCP clients:

```bash
./slow-time-server -transport=stdio -latency=5s
```

### 2. Dual Mode
Both MCP (SSE + Streamable HTTP) and REST API:

```bash
./slow-time-server -transport=dual -port=8081 -latency=5s
```

Endpoints:

- `/sse` -- MCP SSE events
- `/messages` -- MCP SSE messages
- `/http` -- MCP Streamable HTTP (JSON-RPC)
- `/api/v1/*` -- REST API endpoints
- `/health` -- Health check (always instant)

### 3. REST Mode
REST API only (no MCP protocol):

```bash
./slow-time-server -transport=rest -port=8081
```

## MCP Tools

### get_slow_time

Returns the current time with configurable delay. This is the primary tool for testing timeout behaviour.

**Parameters:**

- `timezone` (optional): IANA timezone name (default: "UTC")
- `delay_seconds` (optional): Override delay in seconds (default: server's configured latency)

**Example:**
```json
{
  "tool": "get_slow_time",
  "arguments": {
    "timezone": "America/New_York",
    "delay_seconds": 10
  }
}
```

### convert_slow_time

Converts time between timezones with delay.

**Parameters:**

- `time` (required): RFC3339 time string to convert
- `source_timezone` (required): Source IANA timezone
- `target_timezone` (required): Target IANA timezone
- `delay_seconds` (optional): Override delay in seconds

### get_instant_time

Returns the current time with zero delay. Useful as a baseline to compare against slow tools.

**Parameters:**

- `timezone` (optional): IANA timezone name (default: "UTC")

### get_timeout_time

Returns the current time after a 10-minute delay. Designed to always exceed any reasonable timeout, useful for testing that the gateway correctly enforces timeouts.

**Parameters:**

- `timezone` (optional): IANA timezone name (default: "UTC")

### get_flaky_time

Returns the current time but randomly fails based on the server's configured failure rate. Use this to test circuit breaker behaviour.

**Parameters:**

- `timezone` (optional): IANA timezone name (default: "UTC")

**Failure modes:**

- `timeout` -- Simulates a stuck request (context sleep for 10 minutes)
- `error` -- Returns an MCP error result
- `panic` -- Returns a panic-style error message

## MCP Resources

### latency://config

Current server latency configuration including distribution type, default latency, failure rate, and failure mode.

### latency://stats

Invocation statistics: total count, failure count, average latency, and p50/p95/p99 percentiles.

## MCP Prompts

### test_timeout

Generates step-by-step instructions for testing timeout behaviour.

**Parameters:**

- `delay_seconds` (optional): Delay to use in the test (default: "30")
- `timeout_seconds` (optional): Expected timeout threshold (default: "10")

## REST API

Available in `dual` and `rest` transport modes:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/time?timezone=X&delay=Y` | Get time with configurable delay |
| GET | `/api/v1/config` | Current latency configuration |
| POST | `/api/v1/config` | Runtime latency reconfiguration |
| GET | `/api/v1/stats` | Invocation statistics |
| GET | `/api/v1/test/echo?message=X` | Echo test (no delay) |
| GET | `/api/v1/docs` | Swagger UI |
| GET | `/api/v1/openapi.json` | OpenAPI specification |
| GET | `/health` | Health check (always instant) |
| GET | `/version` | Version info |

### Runtime Reconfiguration

Update latency settings at runtime without restarting:

```bash
curl -X POST http://localhost:8889/api/v1/config \
  -H "Content-Type: application/json" \
  -d '{
    "default_latency": "10s",
    "distribution": "normal",
    "mean_latency": "5s",
    "stddev_latency": "2s",
    "failure_rate": 0.1,
    "failure_mode": "error"
  }'
```

## Latency Distributions

The server supports four latency distribution models:

| Distribution | Flags | Description |
|-------------|-------|-------------|
| `fixed` | `-latency=5s` | Every request has identical delay |
| `uniform` | `-latency-min=1s -latency-max=10s` | Random delay between min and max |
| `normal` | `-latency-mean=5s -latency-stddev=2s` | Bell curve around mean |
| `exponential` | `-latency-mean=5s` | Exponential distribution (models real network jitter) |

```bash
# Fixed 5s latency
./slow-time-server -transport=dual -port=8081 -latency=5s

# Uniform between 1-10s
./slow-time-server -transport=dual -port=8081 \
  -latency-distribution=uniform -latency-min=1s -latency-max=10s

# Normal distribution (realistic)
./slow-time-server -transport=dual -port=8081 \
  -latency-distribution=normal -latency-mean=5s -latency-stddev=3s

# Exponential (models network jitter)
./slow-time-server -transport=dual -port=8081 \
  -latency-distribution=exponential -latency-mean=5s
```

## Testing Scenarios

### Timeout Testing

Verify the gateway enforces per-tool timeouts:

```bash
# Start with 5s latency (exceeds typical 3s gateway timeout)
./slow-time-server -transport=dual -port=8081 -latency=5s

# Register with gateway, then set a per-tool timeout override
curl -X PATCH http://localhost:4444/tools/<get_slow_time_tool_id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timeout_ms": 3000}'

# Calls to get_slow_time should now return ToolTimeoutError after 3s
```

### Circuit Breaker Testing

Trigger circuit breaker transitions with a high failure rate:

```bash
# 30% failure rate with error mode
./slow-time-server -transport=dual -port=8081 \
  -latency=2s -failure-rate=0.3 -failure-mode=error -seed=42

# Call get_flaky_time repeatedly to observe circuit breaker opening
```

### Load Testing with Locust

A Locust test file is provided at `tests/loadtest/locustfile_slow_time_server.py` with four user classes:

| User Class | Weight | Description |
|-----------|--------|-------------|
| `SlowTimeUser` | 10 | Normal slow-time requests via REST API |
| `TimeoutStormUser` | 1 | All requests use 120s delay (timeout stress) |
| `MixedLatencyUser` | 5 | Mix of instant, slow, and extreme-delay |
| `CircuitBreakerUser` | 2 | Rapid flaky requests for circuit breaker |

```bash
# Via docker compose (testing profile includes Locust)
docker compose --profile testing up -d

# Or run directly
locust -f tests/loadtest/locustfile_slow_time_server.py \
  --host=http://localhost:8889 \
  --users=10 --spawn-rate=2 --run-time=120s --headless
```

## Docker

```bash
# Build
cd mcp-servers/go/slow-time-server
make docker-build

# Run with default 5s latency
docker run --rm -p 8081:8081 slow-time-server:latest

# Run with custom latency and failure rate
docker run --rm -p 8081:8081 \
  -e DEFAULT_LATENCY=30s \
  -e FAILURE_RATE=0.3 \
  slow-time-server:latest
```

## Gateway Registration

```bash
# Register via gateway API
curl -X POST http://localhost:4444/gateways \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "slow_time",
    "url": "http://slow-time-server:8081/http",
    "transport": "STREAMABLEHTTP"
  }'

# Override timeout for the guaranteed-timeout tool
curl -X PATCH http://localhost:4444/tools/<get_timeout_time_id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timeout_ms": 5000}'
```

## Related Resources

- [Fast Time Server](fast-time-server.md) -- The baseline fast-response counterpart
- [Performance Testing](../../../testing/performance.md) -- Load testing guide
- [Source code](https://github.com/IBM/mcp-context-forge/tree/main/mcp-servers/go/slow-time-server)
