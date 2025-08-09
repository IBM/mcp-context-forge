# Logging

MCP Gateway provides comprehensive file-based logging with automatic rotation, dual-format output (JSON for files, text for console), and centralized logging service integration. This guide shows how to configure log levels, formats, destinations, and file management.

---

## 🧾 Log Structure

MCP Gateway uses dual-format logging:

- **File logs**: Structured JSON format for machine processing and log aggregation
- **Console logs**: Human-readable text format for development and debugging

### JSON Format (File Output)
```json
{
  "asctime": "2025-01-09 17:30:15,123",
  "name": "mcpgateway.gateway_service",
  "levelname": "INFO",
  "message": "Registered gateway: peer-gateway-1"
}
```

#### HTTP Access Logs (JSON)
```json
{
  "asctime": "2025-01-09 17:30:22,456",
  "name": "uvicorn.access",
  "levelname": "INFO",
  "message": "127.0.0.1:43926 - \"GET /version HTTP/1.1\" 401"
}
```

### Text Format (Console Output)
```
2025-01-09 17:30:15,123 - mcpgateway.gateway_service - INFO - Registered gateway: peer-gateway-1
```

---

## 🔧 Configuring Logs

MCP Gateway provides flexible logging with **stdout/stderr by default** and **optional file logging**. You can control logging behavior using `.env` settings or environment variables:

| Variable                | Description                        | Default           | Example                     |
| ----------------------- | ---------------------------------- | ----------------- | --------------------------- |
| `LOG_LEVEL`             | Minimum log level                  | `INFO`            | `DEBUG`, `INFO`, `WARNING`  |
| `LOG_FORMAT`            | Console log format                 | `json`            | `json` or `text`            |
| `LOG_TO_FILE`           | **Enable file logging**            | **`false`**       | **`true`, `false`**         |
| `LOG_FILE`              | Log filename (when enabled)        | `null`            | `gateway.log`               |
| `LOG_FOLDER`            | Directory for log files            | `null`            | `/var/log/mcpgateway`       |
| `LOG_FILEMODE`          | File write mode                    | `a+`              | `a+` (append), `w` (overwrite) |
| `LOG_ROTATION_ENABLED`  | **Enable log file rotation**       | **`false`**       | **`true`, `false`**         |
| `LOG_MAX_SIZE_MB`       | Max file size before rotation (MB) | `1`               | `10`, `50`, `100`           |
| `LOG_BACKUP_COUNT`      | Number of backup files to keep     | `5`               | `3`, `10`, `0` (no backups) |

### Logging Behavior

- **Default**: Logs **only to stdout/stderr** with human-readable text format (recommended for containers)
- **File Logging**: When `LOG_TO_FILE=true`, logs to **both** file (JSON format) and console (text format)
- **Log Rotation**: When `LOG_ROTATION_ENABLED=true`, files rotate at `LOG_MAX_SIZE_MB` with `LOG_BACKUP_COUNT` backup files
- **No Rotation**: When `LOG_ROTATION_ENABLED=false`, files grow indefinitely (append mode)
- **Directory Creation**: Log folder is created automatically if it doesn't exist
- **Dual Output**: JSON logs to file, text logs to console simultaneously (when file logging enabled)

### Example Configurations

```bash
# Default: stdout/stderr only (recommended for containers)
LOG_LEVEL=INFO
# No additional config needed - logs to stdout/stderr only

# Optional: Enable file logging (no rotation)
LOG_TO_FILE=true
LOG_FOLDER=/var/log/mcpgateway
LOG_FILE=gateway.log
LOG_FILEMODE=a+

# Production with file rotation
LOG_TO_FILE=true
LOG_ROTATION_ENABLED=true
LOG_MAX_SIZE_MB=10
LOG_BACKUP_COUNT=7
LOG_FOLDER=/var/log/mcpgateway
LOG_FILE=gateway.log

# Development with file logging and rotation
LOG_TO_FILE=true
LOG_ROTATION_ENABLED=true
LOG_MAX_SIZE_MB=1
LOG_BACKUP_COUNT=3
LOG_LEVEL=DEBUG
LOG_FOLDER=./logs
LOG_FILE=debug.log
LOG_FORMAT=text
```

---

## 📂 Log File Management

**Note**: This section applies only when file logging is enabled with `LOG_TO_FILE=true`. By default, MCP Gateway logs only to stdout/stderr.

### Viewing Log Files

```bash
# View current log file
cat logs/mcpgateway.log

# Follow log file in real-time
tail -f logs/mcpgateway.log

# View with JSON formatting (requires jq)
tail -f logs/mcpgateway.log | jq '.'

# Search logs for specific patterns
grep "ERROR" logs/mcpgateway.log
grep "gateway_service" logs/*.log
```

### Log Rotation

**Log rotation is optional** and only applies when both file logging and rotation are enabled:

- `LOG_TO_FILE=true` - Enable file logging
- `LOG_ROTATION_ENABLED=true` - Enable rotation

When enabled, files automatically rotate based on the configured size limit (`LOG_MAX_SIZE_MB`):

```
logs/
├── mcpgateway.log      (current, active log)
├── mcpgateway.log.1    (most recent backup)
├── mcpgateway.log.2    (second backup)
├── mcpgateway.log.3    (third backup)
└── ...                 (up to LOG_BACKUP_COUNT backups)
```

**Configuration Options:**
- `LOG_MAX_SIZE_MB=10` - Rotate when file reaches 10MB
- `LOG_BACKUP_COUNT=3` - Keep 3 backup files (plus current file = 4 total)
- `LOG_BACKUP_COUNT=0` - No backup files (only current file kept)

**Without Rotation:**
- When `LOG_ROTATION_ENABLED=false`, files grow indefinitely
- Use external log management tools for cleanup if needed

### Cleanup and Maintenance

```bash
# Archive old logs (optional)
tar -czf mcpgateway-logs-$(date +%Y%m%d).tar.gz logs/mcpgateway.log.*

# Clear all log files (be careful!)
rm logs/mcpgateway.log*

# Check log file sizes
du -sh logs/*
```

---

## 📡 Streaming Logs (Containers)

```bash
docker logs -f mcpgateway
# or with Podman
podman logs -f mcpgateway
```

---

## 📤 Shipping Logs to External Services

MCP Gateway can write to stdout or a file. To forward logs to services like:

* **ELK (Elastic Stack)**
* **LogDNA / IBM Log Analysis**
* **Datadog**
* **Fluentd / Loki**

You can:

* Mount log files to a sidecar container
* Use a logging agent (e.g., Filebeat)
* Pipe logs to syslog-compatible services

---

## 🧪 Debug Mode

For development and troubleshooting, enable verbose logging:

```env
# Enable debug logging
LOG_LEVEL=DEBUG
LOG_FORMAT=text
LOG_FOLDER=./debug-logs
LOG_FILE=debug.log
DEBUG=true
```

### Debug Features

- **HTTP Access Logs**: All HTTP requests with IP, method, path, status code (via `uvicorn.access`)
- **HTTP Error Logs**: Server errors, invalid requests (via `uvicorn.error`)
- **Internal Service Logs**: Database queries, cache operations, federation
- **Transport Layer Logs**: WebSocket, SSE, and stdio communication
- **Plugin System Logs**: Hook execution and plugin lifecycle events

### Useful Debug Commands

```bash
# Start with debug logging
LOG_LEVEL=DEBUG mcpgateway --host 0.0.0.0 --port 4444

# Debug specific components
grep "gateway_service" logs/mcpgateway.log | tail -20
grep "ERROR\|WARNING" logs/mcpgateway.log

# Monitor in real-time during development
tail -f logs/mcpgateway.log | grep "tool_service"
```

---
