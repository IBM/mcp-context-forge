# 🦫 Fast Time Server

> Author: Mihai Criveti
> A minimal Go service that streams or returns the current UTC time over **stdio**, **HTTP/JSON-RPC**, or **Server-Sent Events (SSE)**.

[![Go Version](https://img.shields.io/badge/go-1.23-1.27-blue)]()
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache%202.0-blue)]()

---

## Features

- Five transports: `stdio`, `http` (JSON-RPC 2.0), `sse`, `dual` (MCP + REST), and `rest` (REST API only)
- REST API with OpenAPI documentation for direct HTTP access
- Single static binary (~2 MiB)
- Build-time version & date via `main.appVersion`, `main.buildDate`
- Cross-platform builds via `make cross`
- Dockerfile for lightweight container
- Linting (`golangci-lint`, `staticcheck`) and pre-commit support
- Unit tests with HTML coverage & Go benchmarks
- **Load testing support** using `hey`

## Quick Start

```bash
git clone git@github.com:IBM/mcp-context-forge.git
cd mcp-servers/go/fast-time-server

# Build & run over stdio
make run

# HTTP JSON-RPC on port 8080
make run-http

# SSE endpoint on port 8080
make run-sse

# REST API on port 8080
./fast-time-server -transport=rest

# Dual mode (MCP + REST) on port 8080
./fast-time-server -transport=dual
```

## Installation

**Requires Go 1.23+.**

```bash
git clone git@github.com:IBM/mcp-context-forge.git
go install mcp-servers/go/fast-time-server
```

Also available as releases.

## CLI Flags

| Flag              | Default   | Description                                       |
| ----------------- | --------- | ------------------------------------------------- |
| `-transport`      | `stdio`   | Options: `stdio`, `http`, `sse`, `dual`, `rest` |
| `-addr`/`-listen` | `0.0.0.0` | Bind address for HTTP/SSE               |
| `-port`           | `8080`    | Port for HTTP/SSE/dual                  |
| `-auth-token`     | *(empty)* | Bearer token for SSE authentication     |

## API Reference

### REST API Endpoints

When using `rest` or `dual` transport modes, the following REST endpoints are available:

#### Get System Time
**GET** `/api/v1/time?timezone={timezone}`
**GET** `/api/v1/time/{timezone}`

Returns the current time in the specified timezone (default: UTC).

```bash
curl http://localhost:8080/api/v1/time?timezone=America/New_York
```

Response:
```json
{
  "time": "2025-01-10T11:30:00-05:00",
  "timezone": "America/New_York",
  "unix": 1736522400,
  "utc": "2025-01-10T16:30:00Z"
}
```

#### Convert Time
**POST** `/api/v1/convert`

Converts time between different timezones.

```bash
curl -X POST http://localhost:8080/api/v1/convert \
  -H "Content-Type: application/json" \
  -d '{"time":"2025-01-10T10:00:00Z","from_timezone":"UTC","to_timezone":"Asia/Tokyo"}'
```

Response:
```json
{
  "original_time": "2025-01-10T10:00:00Z",
  "from_timezone": "UTC",
  "converted_time": "2025-01-10T19:00:00+09:00",
  "to_timezone": "Asia/Tokyo",
  "unix": 1736503200
}
```

#### List Timezones
**GET** `/api/v1/timezones?filter={filter}`

Returns a list of available IANA timezones.

```bash
curl http://localhost:8080/api/v1/timezones?filter=Europe
```

#### Timezone Info
**GET** `/api/v1/timezones/{timezone}/info`

Returns detailed information about a specific timezone.

```bash
curl http://localhost:8080/api/v1/timezones/Asia/Tokyo/info
```

#### Batch Convert
**POST** `/api/v1/convert/batch`

Convert multiple times in a single request.

#### Test Endpoints
- **GET** `/api/v1/test/echo` - Echo test endpoint
- **POST** `/api/v1/test/validate` - Validate JSON input
- **GET** `/api/v1/test/performance` - Performance metrics

#### API Documentation
- **GET** `/api/v1/docs` - Interactive Swagger UI documentation
- **GET** `/api/v1/openapi.json` - OpenAPI specification

### HTTP (JSON-RPC 2.0)

**POST** `/http`

Request:

```json
{"jsonrpc":"2.0","method":"Time.Now","id":1}
```

Response:

```json
{"jsonrpc":"2.0","result":"2025-06-21T12:34:56Z","id":1}
```

### SSE

**GET** `/sse` (optional header: `Authorization: Bearer <token>`)

Outputs UTC timestamps every second:

```
data: 2025-06-21T12:34:56Z
```

## Load Testing

Install the popular HTTP load tester **hey**:

```bash
brew install hey            # macOS
wget https://hey-release... # Linux prebuilt binary
```

Run a quick load test:

```bash
# 500 requests total, 50 concurrent, HTTP transport
hey -n 500 -c 50 http://localhost:8080/http
```

Generate detailed CSV output for analysis:

```bash
hey -n 1000 -c 100 -o csv http://localhost:8080/http > results.csv
```

## Docker

```bash
make docker-build
make docker-run           # HTTP mode
```

## Cross-Compilation

```bash
make cross
```

Binaries appear under `dist/fast-time-server-<os>-<arch>`.

## Development

| Task                 | Command                     |
| -------------------- | --------------------------- |
| Format & tidy        | `make fmt tidy`             |
| Lint & vet           | `make lint staticcheck vet` |
| Run pre-commit hooks | `make pre-commit`           |

## Testing & Benchmarking

```bash
make test       # Unit tests (race detection)
make coverage   # HTML coverage report
make bench      # Go benchmarks
```
