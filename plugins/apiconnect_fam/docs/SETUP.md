# API Connect FAM Plugin - Setup Guide

## Quick Setup

### 1. Enable Plugins in Environment

Edit your `.env` file:

```bash
# Enable plugin system
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml

# Set log level to see plugin output
LOG_LEVEL=INFO
```

### 2. Enable the Plugin

The plugin is already configured in `plugins/config.yaml`. To enable it, change the mode from `permissive` to `enforce` or leave it as `permissive` (it will still run):

```yaml
plugins:
  - name: "APIConnectFAM"
    kind: "plugins.apiconnect_fam.apiconnect_fam.APIConnectFAMPlugin"
    mode: "permissive"  # Plugin will run
    priority: 1000
    config:
      interval_seconds: 60  # Adjust logging frequency
      log_details: true     # Set to false for summary only
```

### 3. Start the Server

```bash
# Activate virtual environment
source /Users/shankarn/.venv/mcpgateway/bin/activate

# Start development server
make dev
```

### 4. Verify Plugin is Running

Check the logs for initialization message:

```
INFO: Initializing APIConnectFAMPlugin with interval=60s
```

After the configured interval (default 60 seconds), you should see:

```
INFO: Virtual Servers Summary: Total=X, Enabled=Y, Disabled=Z
```

## Configuration Options

### interval_seconds

How often to log server information (in seconds):

```yaml
config:
  interval_seconds: 30  # Log every 30 seconds
```

### log_details

Whether to include detailed information for each server:

```yaml
config:
  log_details: false  # Only log summary counts
```

Or:

```yaml
config:
  log_details: true  # Log full details for each server
```

## Testing

### Create Test Servers

Use the Admin UI or API to create some virtual servers:

```bash
# Generate auth token
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 0 \
  --secret my-test-key-but-now-longer-than-32-bytes)

# Create a test server
curl -X POST http://localhost:8000/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Server",
    "description": "Test virtual server for monitoring",
    "enabled": true,
    "tags": ["test", "monitoring"]
  }'
```

### Watch the Logs

```bash
# Follow the logs to see periodic updates
tail -f mcpgateway.log

# Or if running in terminal
make dev  # Watch console output
```

## Troubleshooting

### Plugin Not Loading

1. Check that `PLUGINS_ENABLED=true` in `.env`
2. Verify `PLUGINS_CONFIG_FILE=plugins/config.yaml`
3. Check for syntax errors in `plugins/config.yaml`
4. Look for error messages in logs

### No Log Output

1. Ensure `LOG_LEVEL=INFO` or `LOG_LEVEL=DEBUG` in `.env`
2. Check that the plugin mode is not `disabled`
3. Wait for the configured interval to pass
4. Verify the plugin initialized successfully

### Database Errors

1. Ensure database is properly initialized: `cd mcpgateway && alembic upgrade head`
2. Check database connection in `.env`: `DATABASE_URL`
3. Verify database file exists (for SQLite): `ls -la mcp.db`

## Customization

### Change Logging Format

Edit `plugins/apiconnect_fam/apiconnect_fam.py` to customize the log output format in the `_log_servers()` method.

### Add Metrics

Extend the plugin to export metrics to Prometheus, StatsD, or other monitoring systems by adding code in the `_log_servers()` method.

### Filter Servers

Add filtering logic to only log specific servers based on tags, status, or other criteria.

## Uninstalling

To disable the plugin:

1. Set `mode: "disabled"` in `plugins/config.yaml`, or
2. Remove the plugin entry from `plugins/config.yaml`, or
3. Set `PLUGINS_ENABLED=false` in `.env` (disables all plugins)