# 🦫 Fast Time Server

> Author: Mihai Criveti
> A minimal Go service that streams or returns the current UTC time over **stdio**, **HTTP/JSON-RPC**, or **Server-Sent Events (SSE)**.

[![Go Version](https://img.shields.io/badge/go-1.23-1.27-blue)]()
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache%202.0-blue)]()

---

## Features

- **MCP Tools**: `get_system_time` and `convert_time` for timezone operations
- **MCP Resources**: Timezone information, world times, format examples, business hours
- **MCP Prompts**: Time comparisons, meeting scheduling, detailed conversions
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

## MCP Features

### Tools

The server provides two main MCP tools:

1. **get_system_time** - Returns the current time in any IANA timezone
   - Parameter: `timezone` (optional, defaults to UTC)

2. **convert_time** - Converts time between different timezones
   - Parameters: `time`, `source_timezone`, `target_timezone` (all required)

### Resources

The server exposes four MCP resources:

1. **timezone://info** - Comprehensive timezone information
   - Includes offset, DST status, major cities, and population data

2. **time://current/world** - Current time in major cities
   - Real-time updates for global cities

3. **time://formats** - Time format examples
   - Input/output format specifications and examples

4. **time://business-hours** - Business hours by region
   - Working hours, lunch breaks, and holidays for different regions

### Prompts

Three prompt templates are available:

1. **compare_timezones** - Compare times across multiple zones
   - Arguments: `timezones` (required), `reference_time` (optional)

2. **schedule_meeting** - Find optimal meeting times
   - Arguments: `participants` (required), `duration` (required),
     `preferred_hours` (optional), `date_range` (optional)

3. **convert_time_detailed** - Convert with context
   - Arguments: `time`, `from_timezone`, `to_timezones` (all required),
     `include_context` (optional)

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

#### MCP Resources
**GET** `/api/v1/resources` - List all available MCP resources
**GET** `/api/v1/resources/{uri}` - Get specific resource content

Available resource URIs:
- `timezone-info` - Comprehensive timezone information
- `current-world` - Current world times
- `time-formats` - Time format examples
- `business-hours` - Business hours by region

```bash
curl http://localhost:8080/api/v1/resources/timezone-info
```

#### MCP Prompts
**GET** `/api/v1/prompts` - List all available MCP prompts
**POST** `/api/v1/prompts/{name}/execute` - Execute a prompt with arguments

Available prompts:
- `compare_timezones` - Compare times across zones
- `schedule_meeting` - Find optimal meeting times
- `convert_time_detailed` - Convert with context

```bash
curl -X POST http://localhost:8080/api/v1/prompts/compare_timezones/execute \
  -H "Content-Type: application/json" \
  -d '{"timezones":"UTC,America/New_York,Asia/Tokyo"}'
```

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
