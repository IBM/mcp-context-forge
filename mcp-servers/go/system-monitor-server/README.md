# 🖥️  System Monitor Server

> Author: Mihai Criveti
> A comprehensive system monitoring MCP server written in Go that provides real-time system metrics, process monitoring, health checking, and log analysis capabilities for LLM applications.

[![Go Version](https://img.shields.io/badge/go-1.23-blue)]()
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache%202.0-blue)]()

---

## Features

- **MCP Tools**: System metrics, process monitoring, health checks, log tailing, disk usage
- **Real-time Monitoring**: Live metrics via WebSocket/SSE
- **Alert System**: Configurable threshold-based alerts
- **Security Controls**: Path validation, file size limits, rate limiting, ReDoS protection
- Five transports: `stdio`, `http` (JSON-RPC 2.0), `sse`, `dual` (MCP + REST), and `rest` (REST API only)
- Cross-platform support: Linux, macOS, Windows
- Build-time version injection via `main.appVersion`
- Comprehensive test coverage with HTML reports
- Docker support with multi-stage builds

## Quick Start

```bash
git clone git@github.com:IBM/mcp-context-forge.git
cd mcp-context-forge/mcp-servers/go/system-monitor-server

# Build & run over stdio
make run

# HTTP JSON-RPC on port 8080
make run-http

# SSE endpoint on port 8080
make run-sse

# REST API on port 8080
make run-rest

# Dual mode (MCP + REST) on port 8080
make run-dual
```

## Installation

**Requires Go 1.23+.**

```bash
git clone git@github.com:IBM/mcp-context-forge.git
cd mcp-context-forge/mcp-servers/go/system-monitor-server
make install
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

## CLI Flags

| Flag              | Default   | Description                                       |
| ----------------- | --------- | ------------------------------------------------- |
| `-transport`      | `stdio`   | Options: `stdio`, `http`, `sse`, `dual`, `rest` |
| `-port`           | `8080`    | Port for HTTP/SSE/dual                  |
| `-log-level`      | `info`    | Logging level: `debug`, `info`, `warn`, `error` |
| `-config`         | `config.yaml` | Path to configuration file            |

## MCP Features

### Tools

The server provides six main MCP tools:

1. **get_system_metrics** - Returns current CPU, memory, disk, and network metrics
   - No parameters required

2. **list_processes** - Lists running processes with filtering and sorting
   - Parameters: `filter_by`, `filter_value`, `sort_by`, `limit`, `include_threads`

3. **monitor_process** - Monitors a specific process with alert thresholds
   - Parameters: `pid`, `process_name`, `duration`, `interval`, `cpu_threshold`, `memory_threshold`

4. **check_service_health** - Checks health of HTTP, TCP, or file-based services
   - Parameters: `services` (array), `timeout`
   - **SECURITY**: Command execution disabled (command injection risk)

5. **tail_logs** - Streams log file contents with filtering
   - Parameters: `file_path`, `lines`, `follow`, `filter`, `max_size`
   - **SECURITY**: Path validation with symlink resolution, ReDoS protection

6. **get_disk_usage** - Analyzes disk usage with detailed breakdowns
   - Parameters: `path`, `max_depth`, `min_size`, `sort_by`, `file_types`

### Configuration

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
  # SECURITY: Only absolute paths, no /tmp by default
  allowed_paths: ["/var/log"]

security:
  # SECURITY: Root path restricts ALL file access (chroot-like)
  # Set to "/opt/monitoring-root" for production
  root_path: ""  # Empty = no root restriction

  # SECURITY: Only absolute paths, no /tmp by default
  allowed_paths: ["/var/log"]
  max_file_size: 104857600  # 100MB
  rate_limit_rps: 10
  enable_audit_log: true
```

## API Endpoints

### MCP Endpoints
- **STDIO**: Standard input/output (default for Claude Desktop)
- **HTTP**: `/` (JSON-RPC 2.0 endpoint)
- **SSE**: `/sse` (events), `/messages` (messages)
- **DUAL**: `/sse` & `/messages` (SSE), `/http` (HTTP)
- **REST**: `/api/v1/*` (REST API only)

### Health & Version
```
GET /health
GET /version
```

## Security Features

### Root Directory Restriction (Chroot-like)
- **Configurable Root Path**: Set `security.root_path` to restrict all file access within a single directory
- **Defense in Depth**: When root_path is set, ALL file operations are confined to that directory tree
- **Production Recommended**: Configure a dedicated root like `/opt/monitoring-root` for production deployments
- **Layered Security**: Root restriction is enforced BEFORE allowed_paths checks

### Path Traversal Protection
- **Symlink Resolution**: Uses `filepath.EvalSymlinks()` to prevent path traversal via symlinks
- **Directory Boundary Checks**: Validates paths are within allowed directories
- **No /tmp Access**: Removed from default allowed paths (security hardening)

### Command Injection Prevention
- **Command Execution Disabled**: Health checker no longer allows arbitrary command execution
- **Alternative**: Use `list_processes` tool to check process status

### ReDoS Protection
- **Pattern Length Limits**: Maximum 1000 characters
- **Dangerous Quantifier Detection**: Blocks nested quantifiers like `(a+)+`
- **Regex Timeout Protection**: Prevents CPU exhaustion

### Memory Exhaustion Prevention
- **File Size Limits**: Enforced before reading files
- **Scanner Buffer Limits**: 10MB maximum per line
- **Rate Limiting**: Configurable requests per second

## Examples

### Get System Metrics
```bash
echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_system_metrics","arguments":{}},"id":1}' | ./system-monitor-server
```

### List Top CPU Processes
```bash
echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list_processes","arguments":{"sort_by":"cpu","limit":5}},"id":2}' | ./system-monitor-server
```

### Check Service Health
```bash
echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"check_service_health","arguments":{"services":[{"name":"ssh","type":"port","target":"localhost:22"}]}},"id":3}' | ./system-monitor-server
```

## Docker

```bash
make docker-build
make docker-run           # HTTP mode
make docker-run-sse       # SSE mode
```

## Development

| Task                 | Command                     |
| -------------------- | --------------------------- |
| Format & tidy        | `make fmt tidy`             |
| Lint & vet           | `make lint staticcheck vet` |
| Run pre-commit hooks | `make pre-commit`           |
| Run all checks       | `make check`                |

## Testing & Benchmarking

```bash
make test       # Unit tests (race detection)
make coverage   # HTML coverage report → dist/coverage.html
make bench      # Go benchmarks

# Test MCP tools
make test-mcp   # Test all MCP tools via stdio
```

## Cross-Compilation

```bash
# Build for specific OS/ARCH
GOOS=linux GOARCH=amd64 make release
GOOS=darwin GOARCH=arm64 make release
GOOS=windows GOARCH=amd64 make release
```

Binaries appear under `dist/<os>-<arch>/`.

## Troubleshooting

### Common Issues

1. **Permission Denied**: Ensure the server has appropriate permissions to access system resources
2. **File Access Denied**: Check that file paths are in the `allowed_paths` configuration
3. **Symlink Path Traversal**: Server resolves symlinks and validates against allowed paths
4. **ReDoS Attack**: Server blocks dangerous regex patterns with nested quantifiers

### Debug Mode

Run with debug logging:
```bash
./system-monitor-server -log-level=debug
```

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
