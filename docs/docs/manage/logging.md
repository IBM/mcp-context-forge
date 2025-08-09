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
  "message": "Registered gateway: peer-gateway-1",
  "funcName": "register_gateway",
  "lineno": 245
}
```

### Text Format (Console Output)
```
2025-01-09 17:30:15,123 - mcpgateway.gateway_service - INFO - Registered gateway: peer-gateway-1
```

---

## 🔧 Configuring Logs

You can control logging behavior using `.env` settings or environment variables:

| Variable       | Description                    | Default           | Example                     |
| -------------- | ------------------------------ | ----------------- | --------------------------- |
| `LOG_LEVEL`    | Minimum log level              | `INFO`            | `DEBUG`, `INFO`, `WARNING`  |
| `LOG_FORMAT`   | Console log format             | `json`            | `json` or `text`            |
| `LOG_FILE`     | Log filename                   | `mcpgateway.log`  | `gateway.log`               |
| `LOG_FOLDER`   | Directory for log files        | `logs`            | `/var/log/mcpgateway`       |
| `LOG_FILEMODE` | File write mode                | `a+`              | `a+` (append), `w` (overwrite) |

### File Management Features

- **Automatic Rotation**: Log files rotate when they reach 1MB
- **Backup Retention**: 5 backup files are kept (`.log.1`, `.log.2`, etc.)
- **Directory Creation**: Log folder is created automatically if it doesn't exist
- **Dual Output**: JSON logs to file, text logs to console simultaneously

### Example Configuration

```bash
# Production logging
LOG_LEVEL=INFO
LOG_FOLDER=/var/log/mcpgateway
LOG_FILE=gateway.log
LOG_FILEMODE=a+

# Development logging
LOG_LEVEL=DEBUG
LOG_FOLDER=./logs
LOG_FILE=debug.log
LOG_FORMAT=text
```

---

## 📂 Log File Management

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

Files automatically rotate based on size:

```
logs/
├── mcpgateway.log      (current, active log)
├── mcpgateway.log.1    (most recent backup)
├── mcpgateway.log.2    (second backup)
├── mcpgateway.log.3    (third backup)
├── mcpgateway.log.4    (fourth backup)
└── mcpgateway.log.5    (oldest backup)
```

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

- **Detailed Request Traces**: HTTP request/response logging
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
