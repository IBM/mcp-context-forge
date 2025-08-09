# Logging Examples for MCP Gateway

This document provides practical examples of using the new logging features in MCP Gateway.

## Quick Start Examples

### 1. Basic Development Setup
```bash
# Enable debug logging for development
export LOG_LEVEL=DEBUG
export LOG_FORMAT=text
export LOG_FOLDER=./dev-logs
mcpgateway --host 0.0.0.0 --port 4444
```

### 2. Production Configuration
```bash
# Production logging with JSON format
export LOG_LEVEL=INFO
export LOG_FOLDER=/var/log/mcpgateway
export LOG_FILE=gateway.log  
export LOG_FILEMODE=a+
mcpgateway --host 0.0.0.0 --port 4444
```

### 3. Monitoring Specific Components
```bash
# Monitor tool service activities
tail -f logs/mcpgateway.log | grep "tool_service"

# Watch for errors across all services
tail -f logs/mcpgateway.log | grep "ERROR\|WARNING"

# Pretty-print JSON logs
tail -f logs/mcpgateway.log | jq '.'
```

## Configuration Examples

### .env File Configuration
```env
# Complete logging configuration
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_FILE=mcpgateway.log
LOG_FOLDER=logs
LOG_FILEMODE=a+
```

### Docker/Container Configuration
```yaml
# docker-compose.yml
services:
  mcpgateway:
    image: ghcr.io/ibm/mcp-context-forge:latest
    environment:
      - LOG_LEVEL=INFO
      - LOG_FOLDER=/app/logs  
      - LOG_FILE=gateway.log
    volumes:
      - ./logs:/app/logs
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
        - name: LOG_FOLDER
          value: "/var/log/mcpgateway"
        - name: LOG_FILE
          value: "gateway.log"
        volumeMounts:
        - name: log-storage
          mountPath: /var/log/mcpgateway
```

## Log Analysis Examples

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
   # Check file permissions and available disk space
   ls -la logs/
   df -h
   ```

2. **Missing log directory**
   ```bash
   # The directory is created automatically, but check permissions
   mkdir -p logs
   chmod 755 logs
   ```

3. **Too many log files**
   ```bash  
   # Clean up old rotated logs
   find logs/ -name "*.log.[6-9]" -delete
   find logs/ -name "*.log.1[0-9]" -delete
   ```

4. **JSON parsing errors**
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
   - Configure proper log rotation
   - Monitor disk space usage

2. **Development Logging**
   - Use `DEBUG` level for detailed troubleshooting
   - Use text format for human readability
   - Keep log files local for quick access

3. **Security Considerations**
   - Ensure log files don't contain sensitive data
   - Protect log directories with proper permissions
   - Rotate logs regularly to prevent disk filling

4. **Performance Considerations**
   - Avoid excessive DEBUG logging in production
   - Monitor log I/O performance
   - Use appropriate log levels for different components