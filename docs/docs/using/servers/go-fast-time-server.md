# Go Fast Time Server

## Overview

The **fast-time-server** is a high-performance Go-based MCP server that provides time-related tools for LLM applications. It offers multiple transport modes including stdio, HTTP, SSE, dual (MCP + REST), and REST-only modes, making it versatile for various integration scenarios.

## Features

- **Multiple Transport Modes**: stdio, HTTP (JSON-RPC), SSE, dual (MCP + REST), and REST API
- **Comprehensive Time Operations**: Get system time, convert between timezones
- **MCP Resources**: Timezone data, world times, format examples, business hours
- **MCP Prompts**: Time comparisons, meeting scheduling, detailed conversions
- **REST API**: Traditional HTTP endpoints alongside MCP protocol
- **OpenAPI Documentation**: Interactive Swagger UI and OpenAPI 3.0 specification
- **CORS Support**: Enabled for browser-based testing
- **Authentication**: Optional Bearer token authentication
- **Lightweight**: Single static binary (~2 MiB)
- **High Performance**: Sub-millisecond response times

## Installation

### From Source

```bash
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-servers/go/fast-time-server
make build
```

### Using Go Install

```bash
go install github.com/IBM/mcp-context-forge/mcp-servers/go/fast-time-server@latest
```

## Transport Modes

### 1. STDIO Mode (Default)
For desktop clients like Claude Desktop:

```bash
./fast-time-server
# or with specific log level
./fast-time-server -transport=stdio -log-level=error
```

### 2. HTTP Mode
JSON-RPC 2.0 over HTTP:

```bash
./fast-time-server -transport=http -port=8080
```

### 3. SSE Mode
Server-Sent Events for web clients:

```bash
./fast-time-server -transport=sse -port=8080
```

### 4. Dual Mode
Both MCP (SSE/HTTP) and REST API:

```bash
./fast-time-server -transport=dual -port=8080
```

Endpoints:
- `/sse` - MCP SSE events
- `/messages` - MCP SSE messages
- `/http` - MCP HTTP (JSON-RPC)
- `/api/v1/*` - REST API endpoints
- `/api/v1/docs` - Interactive API documentation

### 5. REST Mode
REST API only (no MCP protocol):

```bash
./fast-time-server -transport=rest -port=8080
```

## MCP Tools

### get_system_time
Returns the current time in a specified timezone.

**Parameters:**
- `timezone` (optional): IANA timezone name (default: "UTC")

**Example:**
```json
{
  "tool": "get_system_time",
  "arguments": {
    "timezone": "America/New_York"
  }
}
```

### convert_time
Converts time between different timezones.

**Parameters:**
- `time` (required): Time to convert (RFC3339 or common formats)
- `source_timezone` (required): Source IANA timezone
- `target_timezone` (required): Target IANA timezone

**Example:**
```json
{
  "tool": "convert_time",
  "arguments": {
    "time": "2025-01-10T10:00:00Z",
    "source_timezone": "UTC",
    "target_timezone": "Asia/Tokyo"
  }
}
```

## MCP Resources

The server provides four MCP resources that can be accessed through the MCP protocol:

### timezone://info
Comprehensive timezone information including offsets, DST status, major cities, and population data.

**Example Response:**
```json
{
  "timezones": [
    {
      "id": "America/New_York",
      "name": "Eastern Time",
      "offset": "-05:00",
      "dst": true,
      "abbreviation": "EST/EDT",
      "major_cities": ["New York", "Toronto", "Montreal"],
      "population": 141000000
    }
  ],
  "timezone_groups": {
    "us_timezones": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"]
  }
}
```

### time://current/world
Current time in major cities around the world, updated in real-time.

**Example Response:**
```json
{
  "last_updated": "2025-01-10T16:30:00Z",
  "times": {
    "New York": "2025-01-10 11:30:00 EST",
    "London": "2025-01-10 16:30:00 GMT",
    "Tokyo": "2025-01-11 01:30:00 JST"
  }
}
```

### time://formats
Examples of supported time formats for parsing and display.

**Example Response:**
```json
{
  "input_formats": [
    "2006-01-02 15:04:05",
    "2006-01-02T15:04:05Z",
    "2006-01-02T15:04:05-07:00"
  ],
  "output_formats": {
    "iso8601": "2006-01-02T15:04:05Z07:00",
    "rfc3339": "2006-01-02T15:04:05Z"
  }
}
```

### time://business-hours
Standard business hours across different regions.

**Example Response:**
```json
{
  "regions": {
    "north_america": {
      "standard_hours": "9:00 AM - 5:00 PM",
      "lunch_break": "12:00 PM - 1:00 PM",
      "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    }
  }
}
```

## MCP Prompts

The server provides three prompt templates for common time-related tasks:

### compare_timezones
Compare current times across multiple time zones.

**Arguments:**
- `timezones` (required): Comma-separated list of timezone IDs
- `reference_time` (optional): Reference time (defaults to now)

**Example:**
```json
{
  "prompt": "compare_timezones",
  "arguments": {
    "timezones": "UTC,America/New_York,Asia/Tokyo"
  }
}
```

### schedule_meeting
Find optimal meeting time across multiple time zones.

**Arguments:**
- `participants` (required): Comma-separated list of participant locations/timezones
- `duration` (required): Meeting duration in minutes
- `preferred_hours` (optional): Preferred time range (default: "9 AM - 5 PM")
- `date_range` (optional): Date range to consider (default: "next 7 days")

**Example:**
```json
{
  "prompt": "schedule_meeting",
  "arguments": {
    "participants": "New York,London,Tokyo",
    "duration": "60",
    "preferred_hours": "9 AM - 5 PM"
  }
}
```

### convert_time_detailed
Convert time with detailed context.

**Arguments:**
- `time` (required): Time to convert
- `from_timezone` (required): Source timezone
- `to_timezones` (required): Comma-separated list of target timezones
- `include_context` (optional): Include contextual information (true/false)

**Example:**
```json
{
  "prompt": "convert_time_detailed",
  "arguments": {
    "time": "2025-01-10T10:00:00Z",
    "from_timezone": "UTC",
    "to_timezones": "America/New_York,Europe/London,Asia/Tokyo",
    "include_context": "true"
  }
}
```

## REST API Endpoints

When using `rest` or `dual` transport modes, the following REST endpoints are available:

### Get System Time
```bash
# With query parameter
curl http://localhost:8080/api/v1/time?timezone=America/New_York

# With path parameter
curl http://localhost:8080/api/v1/time/Europe/London
```

**Response:**
```json
{
  "time": "2025-01-10T11:30:00-05:00",
  "timezone": "America/New_York",
  "unix": 1736522400,
  "utc": "2025-01-10T16:30:00Z"
}
```

### Convert Time
```bash
curl -X POST http://localhost:8080/api/v1/convert \
  -H "Content-Type: application/json" \
  -d '{
    "time": "2025-01-10T10:00:00Z",
    "from_timezone": "UTC",
    "to_timezone": "Asia/Tokyo"
  }'
```

**Response:**
```json
{
  "original_time": "2025-01-10T10:00:00Z",
  "from_timezone": "UTC",
  "converted_time": "2025-01-10T19:00:00+09:00",
  "to_timezone": "Asia/Tokyo",
  "unix": 1736503200
}
```

### Batch Convert
```bash
curl -X POST http://localhost:8080/api/v1/convert/batch \
  -H "Content-Type: application/json" \
  -d '{
    "conversions": [
      {
        "time": "2025-01-10T10:00:00Z",
        "from_timezone": "UTC",
        "to_timezone": "America/New_York"
      },
      {
        "time": "2025-01-10T10:00:00Z",
        "from_timezone": "UTC",
        "to_timezone": "Europe/Paris"
      }
    ]
  }'
```

### List Timezones
```bash
# All timezones
curl http://localhost:8080/api/v1/timezones

# Filtered timezones
curl http://localhost:8080/api/v1/timezones?filter=Europe
```

### Timezone Info
```bash
curl http://localhost:8080/api/v1/timezones/Asia/Tokyo/info
```

**Response:**
```json
{
  "name": "Asia/Tokyo",
  "offset": "+09:00",
  "current_time": "2025-01-10T19:00:00+09:00",
  "is_dst": false,
  "abbreviation": "JST"
}
```

### MCP Resources via REST

```bash
# List all resources
curl http://localhost:8080/api/v1/resources

# Get specific resource
curl http://localhost:8080/api/v1/resources/timezone-info
curl http://localhost:8080/api/v1/resources/current-world
curl http://localhost:8080/api/v1/resources/time-formats
curl http://localhost:8080/api/v1/resources/business-hours
```

### MCP Prompts via REST

```bash
# List all prompts
curl http://localhost:8080/api/v1/prompts

# Execute a prompt
curl -X POST http://localhost:8080/api/v1/prompts/compare_timezones/execute \
  -H "Content-Type: application/json" \
  -d '{"timezones": "UTC,America/New_York,Asia/Tokyo"}'

curl -X POST http://localhost:8080/api/v1/prompts/schedule_meeting/execute \
  -H "Content-Type: application/json" \
  -d '{"participants": "New York,London,Tokyo", "duration": "60"}'
```

### Test Endpoints
```bash
# Echo test
curl http://localhost:8080/api/v1/test/echo?message=Hello

# Validate JSON
curl -X POST http://localhost:8080/api/v1/test/validate \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# Performance metrics
curl http://localhost:8080/api/v1/test/performance
```

### API Documentation
- **OpenAPI Spec**: `http://localhost:8080/api/v1/openapi.json`
- **Swagger UI**: `http://localhost:8080/api/v1/docs`

## Configuration

### Command-Line Flags

| Flag | Default | Description |
|------|---------|-------------|
| `-transport` | `stdio` | Transport mode: stdio, http, sse, dual, rest |
| `-port` | `8080` | TCP port for HTTP/SSE/REST |
| `-listen` | `0.0.0.0` | Listen interface |
| `-addr` | *(empty)* | Full address (overrides -listen/-port) |
| `-auth-token` | *(empty)* | Bearer token for authentication |
| `-log-level` | `info` | Log level: debug, info, warn, error, none |
| `-public-url` | *(empty)* | External base URL for SSE clients |

### Environment Variables

- `AUTH_TOKEN`: Bearer token for authentication (overrides `-auth-token` flag)

## Authentication

When authentication is enabled, include the Bearer token in requests:

```bash
# Set token
export TOKEN="your-secret-token"

# Start server with authentication
./fast-time-server -transport=rest -auth-token=$TOKEN

# Make authenticated requests
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/v1/time
```

## Claude Desktop Configuration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fast-time": {
      "command": "/path/to/fast-time-server",
      "args": ["-log-level=error"]
    }
  }
}
```

## MCP Gateway Integration

The fast-time-server can be registered with MCP Gateway for federation:

```bash
# Start the server in dual mode
./fast-time-server -transport=dual -port=8080

# Register with MCP Gateway
curl -X POST http://gateway:4444/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "fast-time-server",
    "url": "http://localhost:8080",
    "transport": "sse"
  }'
```

## Development

### Building from Source

```bash
# Build binary
make build

# Run tests
make test

# Generate coverage report
make coverage

# Run linters
make lint staticcheck

# Build for multiple platforms
make cross
```

### Running Different Modes

```bash
# Development with hot reload
make run

# HTTP mode
make run-http

# SSE mode
make run-sse

# Dual mode
make run-dual

# REST mode
make run-rest
```

### Docker Support

```bash
# Build Docker image
make docker-build

# Run in Docker
make docker-run

# Run with authentication
make docker-run-sse-auth TOKEN=mysecret
```

## Performance

The fast-time-server is optimized for high performance:

- **Response Time**: < 1ms for simple queries
- **Throughput**: > 10,000 requests/second
- **Memory Usage**: < 10 MB
- **CPU Usage**: Minimal, single-threaded design
- **Startup Time**: < 100ms

### Benchmarking

```bash
# Install hey (HTTP load tester)
go install github.com/rakyll/hey@latest

# Run benchmark
hey -n 10000 -c 100 http://localhost:8080/api/v1/time
```

## Error Handling

The REST API returns consistent error responses:

```json
{
  "error": "Bad Request",
  "message": "Invalid timezone: Invalid/Zone",
  "code": 400
}
```

Common HTTP status codes:
- `200 OK`: Successful request
- `400 Bad Request`: Invalid parameters
- `401 Unauthorized`: Missing or invalid authentication
- `405 Method Not Allowed`: Wrong HTTP method
- `500 Internal Server Error`: Server error

## CORS Support

CORS is enabled for REST endpoints, allowing browser-based testing:

```javascript
fetch('http://localhost:8080/api/v1/time?timezone=UTC')
  .then(response => response.json())
  .then(data => console.log(data));
```

## Troubleshooting

### Server won't start
- Check if the port is already in use: `lsof -i :8080`
- Verify the binary has execute permissions: `chmod +x fast-time-server`

### Authentication errors
- Ensure the Bearer token is correctly formatted: `Bearer <token>`
- Check that the token matches between server and client
- Health and version endpoints bypass authentication

### Timezone errors
- Use valid IANA timezone names (e.g., "America/New_York", not "EST")
- Check available timezones: `curl http://localhost:8080/api/v1/timezones`

### Performance issues
- Use `-log-level=error` or `-log-level=none` to reduce logging overhead
- Consider using the compiled binary instead of `go run`
- Enable caching in your HTTP client for repeated requests

## Examples

### Time Zone Conversion Script
```bash
#!/bin/bash
# Convert meeting time to multiple timezones

TIME="2025-01-15T14:00:00Z"
ZONES=("America/New_York" "Europe/London" "Asia/Tokyo")

for zone in "${ZONES[@]}"; do
  result=$(curl -s -X POST http://localhost:8080/api/v1/convert \
    -H "Content-Type: application/json" \
    -d "{
      \"time\": \"$TIME\",
      \"from_timezone\": \"UTC\",
      \"to_timezone\": \"$zone\"
    }" | jq -r '.converted_time')

  echo "$zone: $result"
done
```

### Python Client Example
```python
import requests
import json

# Get current time in Tokyo
response = requests.get('http://localhost:8080/api/v1/time/Asia/Tokyo')
data = response.json()
print(f"Current time in Tokyo: {data['time']}")

# Convert time
conversion = {
    "time": "2025-01-15T10:00:00Z",
    "from_timezone": "UTC",
    "to_timezone": "America/New_York"
}
response = requests.post(
    'http://localhost:8080/api/v1/convert',
    json=conversion
)
result = response.json()
print(f"Converted time: {result['converted_time']}")
```

## Related Resources

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [MCP Gateway Documentation](../gateway/index.md)
- [Go MCP SDK](https://github.com/mark3labs/mcp-go)
- [Time Zone Database](https://www.iana.org/time-zones)
