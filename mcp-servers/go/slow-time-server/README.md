# Slow Time Server

A configurable-latency MCP server for timeout, resilience, and load testing. Modelled on `fast-time-server`, it introduces artificial latency on every tool call to serve as a testing target for gateway timeout enforcement, circuit breaker behaviour, session pool resilience, and load testing.

## Tools

| Tool | Description | Latency |
|------|-------------|---------|
| `get_slow_time` | Get current time with configurable delay | Server default or `delay_seconds` override |
| `convert_slow_time` | Convert time between timezones with delay | Server default or `delay_seconds` override |
| `get_instant_time` | Get current time with zero delay | Always 0ms (baseline) |
| `get_timeout_time` | Get current time with extreme delay | Always 10 minutes |
| `get_flaky_time` | Get current time with random failures | Fails based on `-failure-rate` |

## Resources

| URI | Description |
|-----|-------------|
| `latency://config` | Current server latency configuration |
| `latency://stats` | Invocation count, avg/p50/p95/p99 latency, failure count |

## Prompts

| Name | Description |
|------|-------------|
| `test_timeout` | Generates instructions for testing timeout behaviour |

## Quick Start

```bash
# Build
make build

# Run with 5s default latency (dual mode: SSE + HTTP)
./dist/slow-time-server -transport=dual -port=8081 -latency=5s

# Run with environment variables
DEFAULT_LATENCY=30s FAILURE_RATE=0.1 ./dist/slow-time-server -transport=dual -port=8081
```

## Server Flags

```
Usage: slow-time-server [flags]

Flags:
  -transport string     Transport: stdio, http, sse, dual, rest (default "stdio")
  -addr string          Full listen address (host:port) - overrides -listen/-port
  -listen string        Listen interface (default "0.0.0.0")
  -port int             Port (default 8081)
  -auth-token string    Bearer auth token
  -log-level string     Log level: debug, info, warn, error, none (default "info")

Latency Configuration:
  -latency duration              Default tool latency (default 5s)
  -latency-distribution string   Distribution: fixed, uniform, normal, exponential (default "fixed")
  -latency-min duration          Min latency for uniform distribution (default 1s)
  -latency-max duration          Max latency for uniform distribution (default 10s)
  -latency-mean duration         Mean for normal/exponential distribution (default 5s)
  -latency-stddev duration       Stddev for normal distribution (default 2s)

Failure Simulation:
  -failure-rate float    Probability of failure for flaky tool (0.0-1.0, default 0.0)
  -failure-mode string   Failure type: timeout, error, panic (default "timeout")
  -seed int              Random seed for reproducibility (default: time-based)

Environment Variables:
  DEFAULT_LATENCY   Override -latency (e.g., "5s", "30s", "2m")
  FAILURE_RATE      Override -failure-rate
  AUTH_TOKEN        Override -auth-token
```

## Configuration Examples

### Timeout testing (5s latency, gateway timeout at 3s)

```bash
./slow-time-server -transport=dual -port=8081 -latency=5s
```

### Circuit breaker testing (30% failure rate)

```bash
./slow-time-server -transport=dual -port=8081 \
  -latency=2s -failure-rate=0.3 -failure-mode=error -seed=42
```

### Normal distribution (realistic latency)

```bash
./slow-time-server -transport=dual -port=8081 \
  -latency-distribution=normal -latency-mean=5s -latency-stddev=3s
```

## REST API

Available in `dual` and `rest` transport modes:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/time?timezone=X&delay=Y` | Get time with delay |
| GET | `/api/v1/config` | Current latency configuration |
| POST | `/api/v1/config` | Runtime latency reconfiguration |
| GET | `/api/v1/stats` | Invocation statistics |
| GET | `/api/v1/test/echo` | Echo test (no delay) |
| GET | `/api/v1/docs` | Swagger UI |
| GET | `/api/v1/openapi.json` | OpenAPI specification |
| GET | `/health` | Health check (always instant) |
| GET | `/version` | Version info |

## Docker

```bash
# Build
make docker-build

# Run with default 5s latency
docker run --rm -p 8081:8081 slow-time-server:latest

# Run with 30s latency
docker run --rm -p 8081:8081 -e DEFAULT_LATENCY=30s slow-time-server:latest

# Run with failure simulation
docker run --rm -p 8081:8081 \
  -e DEFAULT_LATENCY=5s \
  -e FAILURE_RATE=0.3 \
  slow-time-server:latest
```

## Testing

```bash
make test          # Unit tests with race detection
make coverage      # HTML coverage report
make vet           # Go vet
make lint          # golangci-lint
make staticcheck   # staticcheck
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
