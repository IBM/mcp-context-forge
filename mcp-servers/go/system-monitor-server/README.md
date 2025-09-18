# System Monitor Server

A comprehensive system monitoring MCP (Model Context Protocol) server written in Go that provides real-time system metrics, process monitoring, health checking, and log analysis capabilities for LLM applications.

## Features

### 🔧 Core Monitoring Tools

- **System Metrics**: Real-time CPU, memory, disk, and network usage
- **Process Management**: List, filter, and monitor running processes
- **Health Checks**: HTTP, TCP port, command, and file-based service monitoring
- **Log Analysis**: Tail and filter log files with security controls
- **Disk Usage**: Analyze disk usage with detailed breakdowns

### 🚀 Advanced Capabilities

- **Real-time Streaming**: Live metrics via WebSocket/SSE
- **Alert System**: Configurable threshold-based alerts
- **Cross-platform Support**: Linux, macOS, Windows
- **Security Controls**: Path validation, file size limits, rate limiting
- **Multiple Transports**: STDIO, SSE, HTTP, DUAL, and REST API modes

## Quick Start

### Prerequisites

- Go 1.21 or later
- Git

### Installation

```bash
# Clone the repository
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge/mcp-servers/go/system-monitor-server

# Build the server
make build

# Run in stdio mode (for Claude Desktop)
./system-monitor-server

# Run in HTTP mode
./system-monitor-server -transport=http -port=8080
```

### Claude Desktop Integration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "system-monitor": {
      "command": "/path/to/system-monitor-server",
      "args": ["-log-level=error"]
    }
  }
}
```

## Available Tools

### 1. `get_system_metrics`

Retrieve current system resource usage including CPU, memory, disk, and network metrics.

**Example:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_system_metrics",
    "arguments": {}
  },
  "id": 1
}
```

**Response:**
```json
{
  "cpu": {
    "usage_percent": 15.2,
    "load_avg_1": 0.8,
    "load_avg_5": 1.2,
    "load_avg_15": 1.5,
    "num_cores": 8
  },
  "memory": {
    "total": 16777216000,
    "available": 8388608000,
    "used": 8388608000,
    "free": 4194304000,
    "usage_percent": 50.0
  },
  "disk": [...],
  "network": [...],
  "timestamp": "2025-01-15T10:30:00Z"
}
```

### 2. `list_processes`

List running processes with filtering and sorting options.

**Parameters:**
- `filter_by`: Filter by name, user, or pid
- `filter_value`: Value to filter by
- `sort_by`: Sort by cpu, memory, name, or pid
- `limit`: Maximum number of processes to return
- `include_threads`: Include thread count information

**Example:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "list_processes",
    "arguments": {
      "sort_by": "cpu",
      "limit": 10,
      "filter_by": "name",
      "filter_value": "python"
    }
  },
  "id": 2
}
```

### 3. `monitor_process`

Monitor a specific process for a given duration with alert thresholds.

**Parameters:**
- `pid`: Process ID to monitor
- `process_name`: Process name to monitor (alternative to PID)
- `duration`: Monitoring duration in seconds
- `interval`: Monitoring interval in seconds
- `cpu_threshold`: CPU usage threshold for alerts
- `memory_threshold`: Memory usage threshold for alerts
- `memory_rss_threshold`: Memory RSS threshold for alerts

**Example:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "monitor_process",
    "arguments": {
      "process_name": "nginx",
      "duration": 60,
      "interval": 5,
      "cpu_threshold": 80.0,
      "memory_threshold": 90.0
    }
  },
  "id": 3
}
```

### 4. `check_service_health`

Check health of system services and applications.

**Parameters:**
- `services`: JSON array of services to check
- `timeout`: Timeout in seconds for health checks

**Example:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "check_service_health",
    "arguments": {
      "services": [
        {
          "name": "web_server",
          "type": "http",
          "target": "http://localhost:8080/health"
        },
        {
          "name": "database",
          "type": "port",
          "target": "localhost:5432"
        }
      ],
      "timeout": 10
    }
  },
  "id": 4
}
```

### 5. `tail_logs`

Stream log file contents with filtering and security controls.

**Parameters:**
- `file_path`: Path to the log file to tail
- `lines`: Number of lines to tail
- `follow`: Follow the file for new lines
- `filter`: Regex filter for log lines
- `max_size`: Maximum file size to process

**Example:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "tail_logs",
    "arguments": {
      "file_path": "/var/log/nginx/access.log",
      "lines": 100,
      "filter": "ERROR|WARN",
      "follow": false
    }
  },
  "id": 5
}
```

### 6. `get_disk_usage`

Analyze disk usage with detailed breakdowns and filtering.

**Parameters:**
- `path`: Path to analyze
- `max_depth`: Maximum directory depth to analyze
- `min_size`: Minimum file size to include
- `sort_by`: Sort results by size, name, or modified
- `file_types`: Filter by file extensions

**Example:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_disk_usage",
    "arguments": {
      "path": "/var/log",
      "max_depth": 2,
      "min_size": 1024,
      "sort_by": "size",
      "file_types": ["log", "txt"]
    }
  },
  "id": 6
}
```

## Transport Modes

### STDIO (Default)
For desktop clients like Claude Desktop:
```bash
./system-monitor-server
```

### SSE (Server-Sent Events)
For web-based MCP clients:
```bash
./system-monitor-server -transport=sse -port=8080
```

### HTTP
For REST-style access:
```bash
./system-monitor-server -transport=http -port=8080
```

### DUAL
Both SSE and HTTP on the same port:
```bash
./system-monitor-server -transport=dual -port=8080
```

### REST API
Direct HTTP REST endpoints:
```bash
./system-monitor-server -transport=rest -port=8080
```

## Configuration

The server can be configured via `config.yaml`:

```yaml
monitoring:
  update_interval: "5s"
  history_retention: "24h"
  max_processes: 1000

alerts:
  cpu_threshold: 80.0
  memory_threshold: 85.0
  disk_threshold: 90.0
  enabled: true

health_checks:
  - name: "web_server"
    type: "http"
    target: "http://localhost:8080/health"
    interval: "30s"

log_monitoring:
  max_file_size: "100MB"
  max_tail_lines: 1000
  allowed_paths: ["/var/log", "/tmp", "./logs"]

security:
  allowed_paths: ["/var/log", "/tmp", "./logs"]
  max_file_size: 104857600
  rate_limit_rps: 10
  enable_audit_log: true
```

## Security Features

- **Path Validation**: Only allows access to configured directories
- **File Size Limits**: Prevents processing of oversized files
- **Rate Limiting**: Configurable request rate limiting
- **Audit Logging**: Optional audit trail for administrative actions
- **Authentication**: Optional Bearer token authentication for HTTP/SSE

## Development

### Building

```bash
# Build the binary
make build

# Run tests
make test

# Run linters
make lint

# Format code
make fmt

# Run all checks
make check
```

### Testing

```bash
# Run unit tests
go test ./...

# Run with coverage
go test -cover ./...

# Run benchmarks
go test -bench=. ./...

# Run example commands
make examples
```

### Docker

```bash
# Build Docker image
make docker

# Run in container
docker run -p 8080:8080 system-monitor-server:latest -transport=http
```

## API Endpoints

### Health Check
```
GET /health
```

### Version Info
```
GET /version
```

### MCP Endpoints
- **SSE**: `/sse` (events), `/messages` (messages)
- **HTTP**: `/` (single endpoint)
- **DUAL**: `/sse` & `/messages` (SSE), `/http` (HTTP)
- **REST**: `/api/v1/*` (REST API only)

## Examples

### Get System Metrics
```bash
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_system_metrics","arguments":{}},"id":1}'
```

### List Top CPU Processes
```bash
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list_processes","arguments":{"sort_by":"cpu","limit":5}},"id":2}'
```

### Monitor a Process
```bash
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"monitor_process","arguments":{"process_name":"nginx","duration":30,"interval":5}},"id":3}'
```

## Troubleshooting

### Common Issues

1. **Permission Denied**: Ensure the server has appropriate permissions to access system resources
2. **File Access Denied**: Check that file paths are in the allowed directories list
3. **High CPU Usage**: Adjust monitoring intervals and limits in configuration
4. **Memory Issues**: Reduce max_processes and history_retention settings

### Debug Mode

Run with debug logging:
```bash
./system-monitor-server -log-level=debug
```

### Logs

Check server logs for detailed error information and debugging output.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run `make check`
6. Submit a pull request

## License

Apache-2.0 License - see LICENSE file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues)
- **Discussions**: [GitHub Discussions](https://github.com/IBM/mcp-context-forge/discussions)
- **Documentation**: [Project Wiki](https://github.com/IBM/mcp-context-forge/wiki)
