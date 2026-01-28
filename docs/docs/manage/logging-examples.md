# Logging Examples for MCP Gateway

This document provides practical examples of using the logging features in MCP Gateway.

!!! tip "Complete Configuration"
    For production deployments, copy `.env.example` to `.env` and configure all settings including multitenancy:
    ```bash
    cp .env.example .env
    # Edit .env to set PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD, etc.
    mcpgateway --host 0.0.0.0 --port 4444
    ```

## Quick Start Examples

### 1. Default Setup (Recommended)
```bash
# Default: logs only to stdout/stderr (great for containers)
export LOG_LEVEL=INFO
mcpgateway --host 0.0.0.0 --port 4444
# Logs appear in console only - no files created
```

### 2. Development with File Logging (No Rotation)
```bash
# Enable file logging for development without rotation
export LOG_TO_FILE=true
export LOG_LEVEL=DEBUG
export LOG_FOLDER=./dev-logs
export LOG_FILE=debug.log
mcpgateway --host 0.0.0.0 --port 4444
# Logs to both console (text format) AND ./dev-logs/debug.log (JSON format, grows indefinitely)
```

### 3. Development with File Rotation
```bash
# Enable file logging with small rotation for development
export LOG_TO_FILE=true
export LOG_ROTATION_ENABLED=true
export LOG_MAX_SIZE_MB=1
export LOG_BACKUP_COUNT=3
export LOG_LEVEL=DEBUG
export LOG_FOLDER=./dev-logs
export LOG_FILE=debug.log
mcpgateway --host 0.0.0.0 --port 4444
# Logs rotate at 1MB with 3 backup files kept (console: text, files: JSON)
```

### 4. Production with File Logging (No Rotation)
```bash
# Production logging with JSON format, no rotation (managed externally)
export LOG_TO_FILE=true
export LOG_LEVEL=INFO
export LOG_FOLDER=/var/log/mcpgateway
export LOG_FILE=gateway.log
export LOG_FILEMODE=a+
mcpgateway --host 0.0.0.0 --port 4444
# Logs to both console AND /var/log/mcpgateway/gateway.log
```

### 5. Production with File Rotation
```bash
# Production logging with automatic rotation
export LOG_TO_FILE=true
export LOG_ROTATION_ENABLED=true
export LOG_MAX_SIZE_MB=50
export LOG_BACKUP_COUNT=7
export LOG_LEVEL=INFO
export LOG_FOLDER=/var/log/mcpgateway
export LOG_FILE=gateway.log
mcpgateway --host 0.0.0.0 --port 4444
# Files rotate at 50MB with 7 backup files (weekly retention)
```

### 6. Monitoring Specific Components (requires file logging)
```bash
# First enable file logging
export LOG_TO_FILE=true
export LOG_FILE=mcpgateway.log
export LOG_FOLDER=logs

# Then monitor tool service activities
tail -f logs/mcpgateway.log | grep "tool_service"

# Watch for errors across all services
tail -f logs/mcpgateway.log | grep "ERROR\|WARNING"

# Pretty-print JSON logs
tail -f logs/mcpgateway.log | jq '.'
```

## Configuration Examples

### .env File Configuration
```env
# Default: stdout/stderr only
LOG_LEVEL=INFO
LOG_FORMAT=json

# Optional: Enable file logging (no rotation)
LOG_TO_FILE=true
LOG_FILE=mcpgateway.log
LOG_FOLDER=logs
LOG_FILEMODE=a+

# Optional: Enable file logging with rotation
LOG_TO_FILE=true
LOG_ROTATION_ENABLED=true
LOG_MAX_SIZE_MB=10
LOG_BACKUP_COUNT=5
LOG_FILE=mcpgateway.log
LOG_FOLDER=logs
```

### Docker/Container Configuration
```yaml
# docker-compose.yml
services:
  mcpgateway:
    image: ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
    environment:

      - LOG_LEVEL=INFO
      # Default: logs to stdout/stderr only (recommended for containers)
      # Optional: Enable file logging (no rotation)
      # - LOG_TO_FILE=true
      # - LOG_FOLDER=/app/logs
      # - LOG_FILE=gateway.log
      # Optional: Enable file logging with rotation
      # - LOG_TO_FILE=true
      # - LOG_ROTATION_ENABLED=true
      # - LOG_MAX_SIZE_MB=10
      # - LOG_BACKUP_COUNT=3
      # - LOG_FOLDER=/app/logs
      # - LOG_FILE=gateway.log
    # volumes:
    #   - ./logs:/app/logs  # Only needed if LOG_TO_FILE=true
```

### Kubernetes Configuration
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcpgateway
spec:
  template:
    spec:
      containers:

      - name: mcpgateway
        env:

        - name: LOG_LEVEL
          value: "INFO"
        # Default: logs to stdout/stderr (recommended for Kubernetes)
        # Optional: Enable file logging (no rotation)
        # - name: LOG_TO_FILE
        #   value: "true"
        # - name: LOG_FOLDER
        #   value: "/var/log/mcpgateway"
        # - name: LOG_FILE
        #   value: "gateway.log"
        # Optional: Enable file logging with rotation
        # - name: LOG_TO_FILE
        #   value: "true"
        # - name: LOG_ROTATION_ENABLED
        #   value: "true"
        # - name: LOG_MAX_SIZE_MB
        #   value: "20"
        # - name: LOG_BACKUP_COUNT
        #   value: "5"
        # - name: LOG_FOLDER
        #   value: "/var/log/mcpgateway"
        # - name: LOG_FILE
        #   value: "gateway.log"
        # volumeMounts:  # Only needed if LOG_TO_FILE=true
        # - name: log-storage
        #   mountPath: /var/log/mcpgateway
```

## Log Analysis Examples

**Note**: The following examples require file logging to be enabled with `LOG_TO_FILE=true`. For stdout/stderr logs, use standard shell redirection and pipes instead.

### 1. Finding Errors and Issues
```bash
# Find all errors
grep "ERROR" logs/mcpgateway.log

# Find warnings and errors
grep -E "ERROR|WARNING" logs/mcpgateway.log

# Get context around errors (5 lines before and after)
grep -B5 -A5 "ERROR" logs/mcpgateway.log
```

### 2. Monitoring Service Activity
```bash
# Gateway service activity
grep "gateway_service" logs/mcpgateway.log | tail -20

# Tool invocations
grep "tool_service.*invoke" logs/mcpgateway.log

# Federation activity
grep "federation" logs/mcpgateway.log
```

### 3. Performance Analysis
```bash
# Look for slow operations (if duration logging is enabled)
grep "duration" logs/mcpgateway.log | sort -k5 -nr

# Database operations
grep "database" logs/mcpgateway.log

# HTTP request/response logs
grep -E "HTTP|request" logs/mcpgateway.log
```

## Log Format Examples

### JSON Format (File Output)
```json
{
  "asctime": "2025-01-09 17:30:15,123",
  "name": "mcpgateway.gateway_service",
  "levelname": "INFO",
  "message": "Gateway peer-gateway-1 registered successfully",
  "funcName": "register_gateway",
  "lineno": 245,
  "module": "gateway_service",
  "pathname": "/app/mcpgateway/services/gateway_service.py"
}
```

### Text Format (Console Output)
```
2025-01-09 17:30:15,123 - mcpgateway.gateway_service - INFO - Gateway peer-gateway-1 registered successfully
2025-01-09 17:30:16,456 - mcpgateway.tool_service - DEBUG - Tool 'get_weather' invoked with args: {'location': 'New York'}
2025-01-09 17:30:17,789 - mcpgateway.admin - WARNING - Authentication failed for user: anonymous
```

## Integration Examples

### 1. ELK Stack Integration
```bash
# Configure Filebeat to ship logs
# filebeat.yml
filebeat.inputs:

- type: log
  paths:

    - /var/log/mcpgateway/*.log
  json.keys_under_root: true
  json.add_error_key: true
```

### 2. Datadog Integration
```bash
# Configure Datadog agent
# datadog.yaml
logs_config:
  logs_dd_url: intake.logs.datadoghq.com:10516

logs:

  - type: file
    path: "/var/log/mcpgateway/*.log"
    service: mcpgateway
    source: python
    sourcecategory: mcp
```

### 3. Prometheus/Grafana Monitoring
```bash
# Use log-based metrics with promtail
# promtail-config.yml
scrape_configs:

- job_name: mcpgateway
  static_configs:

  - targets:
    - localhost
    labels:
      job: mcpgateway
      __path__: /var/log/mcpgateway/*.log
```

## Troubleshooting Examples

### Common Issues and Solutions

1. **Log files not rotating**
   ```bash
   # Check if rotation is enabled
   echo "LOG_ROTATION_ENABLED: $LOG_ROTATION_ENABLED"
   echo "LOG_MAX_SIZE_MB: $LOG_MAX_SIZE_MB"
   echo "LOG_BACKUP_COUNT: $LOG_BACKUP_COUNT"

   # Check file permissions and available disk space
   ls -la logs/
   df -h

   # Check current file size (should be under LOG_MAX_SIZE_MB)
   ls -lh logs/mcpgateway.log
   ```

2. **Missing log directory**
   ```bash
   # The directory is created automatically, but check permissions
   mkdir -p logs
   chmod 755 logs
   ```

3. **Too many log files (with rotation disabled)**
   ```bash
   # Clean up old rotated logs beyond LOG_BACKUP_COUNT
   # For LOG_BACKUP_COUNT=5, remove .log.6 and higher
   find logs/ -name "*.log.[6-9]" -delete
   find logs/ -name "*.log.1[0-9]" -delete
   ```

4. **Files not rotating despite size limit**
   ```bash
   # Check if rotation is properly enabled
   grep -i "rotation" logs/mcpgateway.log | tail -5

   # Force check file size vs limit
   actual_size=$(stat -c%s logs/mcpgateway.log)
   limit_bytes=$((LOG_MAX_SIZE_MB * 1024 * 1024))
   echo "Actual: $actual_size bytes, Limit: $limit_bytes bytes"
   ```

5. **Rotation happening too frequently**
   ```bash
   # Increase LOG_MAX_SIZE_MB if files rotate too often
   export LOG_MAX_SIZE_MB=50  # Increase from default 1MB to 50MB

   # Or disable rotation for external log management
   export LOG_ROTATION_ENABLED=false
   ```

6. **JSON parsing errors**
   ```bash
   # Validate JSON format
   cat logs/mcpgateway.log | jq empty

   # Show only invalid JSON lines
   cat logs/mcpgateway.log | while read line; do
     echo "$line" | jq empty 2>/dev/null || echo "Invalid: $line"
   done
   ```

## Best Practices

1. **Production Logging**
   - Use `INFO` level for production
   - Enable JSON format for log aggregation
   - Configure log rotation based on expected volume:
     - High traffic: `LOG_MAX_SIZE_MB=50`, `LOG_BACKUP_COUNT=7`
     - Medium traffic: `LOG_MAX_SIZE_MB=10`, `LOG_BACKUP_COUNT=5`
     - Low traffic: Consider disabling rotation
   - Monitor disk space usage

2. **Development Logging**
   - Use `DEBUG` level for detailed troubleshooting
   - Use text format for human readability
   - Enable rotation with small files: `LOG_MAX_SIZE_MB=1`, `LOG_BACKUP_COUNT=3`
   - Keep log files local for quick access

3. **Security Considerations**
   - Ensure log files don't contain sensitive data
   - Protect log directories with proper permissions
   - Rotate logs regularly to prevent disk filling

4. **Performance Considerations**
   - Avoid excessive DEBUG logging in production
   - Monitor log I/O performance
   - Use appropriate log levels for different components
