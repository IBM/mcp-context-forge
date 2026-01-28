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
| `STRUCTURED_LOGGING_DATABASE_ENABLED` | **Persist logs to database** | **`false`** | **`true`, `false`** |
| `AUDIT_TRAIL_ENABLED` | **Enable audit trail logging for compliance** | **`false`** | **`true`, `false`** |
| `SECURITY_LOGGING_ENABLED` | **Enable security event logging** | **`false`** | **`true`, `false`** |
| `SECURITY_LOGGING_LEVEL` | Security logging verbosity level | `failures_only` | `all`, `failures_only`, `high_severity` |

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

## 📋 Audit Trail Logging

Audit trail logging records all CRUD operations (create, read, update, delete) on resources for compliance purposes. **This is disabled by default for performance**.

### Configuration

```bash
# Audit trail logging - disabled by default for performance
AUDIT_TRAIL_ENABLED=false
```

### What Gets Logged

When enabled, all API operations are recorded in the `audit_trails` table:

- **Create** - New tools, servers, gateways, resources, prompts
- **Read** - View operations on any resource
- **Update** - Modifications with before/after values
- **Delete** - Deletions with snapshot of deleted data

### Use Cases

| Scenario | Recommendation |
|----------|----------------|
| Production compliance (SOC2, HIPAA, GDPR) | `AUDIT_TRAIL_ENABLED=true` |
| Load testing / benchmarking | `AUDIT_TRAIL_ENABLED=false` |
| Development / debugging | `AUDIT_TRAIL_ENABLED=false` |

!!! warning "Performance Impact"
    Enabling audit trails causes a **database write on every API request**. During load testing with 2000 concurrent users, this can generate ~1 million rows in a few hours, consuming 788+ MB of database space and causing PostgreSQL memory pressure. **Always disable for load testing.**

### Audit Trails Table

Query audit trails via the API: `GET /api/logs/audit-trails`

---

## 🔐 Security Event Logging

Security event logging records authentication attempts, authorization failures, and other security-relevant events to the database. **This is disabled by default for performance**.

### Configuration

```bash
# Security event logging - disabled by default for performance
SECURITY_LOGGING_ENABLED=false

# Security logging level controls what gets logged
SECURITY_LOGGING_LEVEL=failures_only  # all, failures_only, high_severity
```

### Logging Levels

| Level | Description | Use Case |
|-------|-------------|----------|
| `all` | Log all events including successful authentications | Debugging, compliance auditing (high DB load) |
| `failures_only` | Log only authentication/authorization failures | Production monitoring without excessive writes |
| `high_severity` | Log only high/critical severity events | Minimal logging for high-traffic environments |

!!! warning "Performance Impact"
    Setting `SECURITY_LOGGING_LEVEL=all` logs **every authenticated request** to the database. During load testing, this can generate 300+ database writes per second, causing significant performance degradation. Use `failures_only` or `high_severity` in production.

### Security Events Table

When enabled, events are stored in the `security_events` table:

- Authentication success/failure
- Authorization denials
- Rate limiting triggers
- Suspicious activity detection

Query security events via the API: `GET /api/logs/security-events`

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

## 🖥️ Admin UI Log Viewer

MCP Gateway includes a built-in log viewer in the Admin UI that provides real-time monitoring, filtering, and export capabilities without requiring direct file access.

### Enabling the Log Viewer

The log viewer is automatically available when the Admin UI is enabled:

```bash
# Enable Admin UI (includes log viewer)
MCPGATEWAY_UI_ENABLED=true

# Configure in-memory log buffer size (default: 1MB)
LOG_BUFFER_SIZE_MB=2  # Increase for more log history
```

### Features

#### Real-Time Monitoring
- **Live streaming** via Server-Sent Events (SSE)
- **Automatic updates** as new logs are generated
- **Visual indicators** with pulse animation for new entries
- **Color-coded severity levels**:
  - Debug: Gray
  - Info: Blue
  - Warning: Yellow
  - Error: Red
  - Critical: Purple

#### Filtering & Search
- **Filter by log level**: Debug, Info, Warning, Error, Critical
- **Filter by entity type**: Tool, Resource, Server, Gateway
- **Full-text search**: Search within log messages
- **Time range filtering**: Filter by date/time range
- **Request ID tracing**: Track logs for specific requests

#### Export Capabilities
- **Export to JSON**: Download filtered logs as JSON file
- **Export to CSV**: Download filtered logs as CSV file
- **Download log files**: Direct access to rotated log files (if file logging enabled)

### Accessing the Log Viewer

1. Navigate to the Admin UI: `http://localhost:4444/admin`
2. Click the **"Logs"** tab in the navigation
3. Use the filter controls to refine your view:
   - Select entity type from dropdown
   - Choose minimum log level
   - Enter search terms
   - Set pagination options

### API Endpoints

The log viewer also exposes REST API endpoints for programmatic access:

```bash
# Get filtered logs
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/admin/logs?level=error&limit=50"

# Stream logs in real-time (SSE)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/admin/logs/stream"

# Export logs as JSON
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/admin/logs/export?format=json" \
  -o logs.json

# List available log files
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/admin/logs/file"
```

### Buffer Management

The log viewer uses an in-memory circular buffer with configurable size:

- **Default size**: 1MB (approximately 2000-5000 log entries)
- **Size-based eviction**: Oldest logs automatically removed when buffer is full
- **No persistence**: Buffer is cleared on server restart
- **Performance**: Minimal memory overhead with O(1) operations

### Configuration Options

| Variable              | Description                          | Default | Example |
| -------------------- | ------------------------------------ | ------- | ------- |
| `LOG_BUFFER_SIZE_MB` | In-memory buffer size for UI viewer | `1`     | `2`, `5`, `10` |

### Best Practices

1. **Adjust buffer size** based on your monitoring needs:
   - Development: 1-2MB is usually sufficient
   - Production: Consider 5-10MB for longer history

2. **Use filters** to focus on relevant logs:
   - Filter by error level during troubleshooting
   - Filter by entity when debugging specific components

3. **Export regularly** if you need to preserve logs:
   - The buffer is in-memory only and clears on restart
   - Export important logs to JSON/CSV for archival

4. **Combine with file logging** for persistence:
   - UI viewer for real-time monitoring
   - File logs for long-term storage and analysis

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

## 🗄️ Database Log Persistence

MCP Gateway can optionally persist structured logs to the database for advanced search, request tracing, and performance metrics. **This feature is disabled by default for performance reasons.**

### Enabling Database Logging

```bash
# Enable database persistence for logs
STRUCTURED_LOGGING_DATABASE_ENABLED=true
```

### Features When Enabled

When `STRUCTURED_LOGGING_DATABASE_ENABLED=true`, you get:

| Feature | API Endpoint | Description |
|---------|--------------|-------------|
| **Log Search** | `POST /api/logs/search` | Search logs by level, component, user, time range, correlation ID |
| **Request Tracing** | `GET /api/logs/trace/{correlation_id}` | View all logs, security events, and audit trails for a single request |
| **Performance Metrics** | `GET /api/logs/performance-metrics` | Aggregated p50/p95/p99 latencies, error rates by component |
| **Security Events** | `GET /api/logs/security-events` | Authentication failures, threat detection, security audit |
| **Audit Trails** | `GET /api/logs/audit-trails` | CRUD operations, data access compliance logging |

### Example: Search Logs via API

```bash
# Search for error logs in the last hour
curl -X POST "http://localhost:4444/api/logs/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "level": ["ERROR", "CRITICAL"],
    "limit": 50,
    "sort_order": "desc"
  }'

# Trace all logs for a specific request
curl "http://localhost:4444/api/logs/trace/abc-123-correlation-id" \
  -H "Authorization: Bearer $TOKEN"
```

### Performance Considerations

!!! warning "Performance Impact"
    When enabled, **each log entry triggers a synchronous database write**. This can significantly impact performance under high load.

**Recommendations:**

- **Disable in production** if you use an external log aggregator (ELK, Datadog, Splunk)
- **Enable for development** or low-traffic deployments where built-in search is useful
- **Consider external logging** for high-throughput production environments

### When to Enable vs Disable

| Scenario | Recommendation |
|----------|----------------|
| Development/testing | ✅ Enable - useful for debugging |
| Low-traffic production | ✅ Enable - built-in observability |
| High-traffic production | ❌ Disable - use external aggregator |
| Using ELK/Datadog/Splunk | ❌ Disable - redundant storage |
| Need request tracing | ✅ Enable - correlation ID tracing |
| Performance-critical | ❌ Disable - avoid DB I/O overhead |

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
