# Enable Request Payload Logging in ContextForge

This guide shows how to enable request payload logging to debug and validate tool registration requests and other API calls.

## Quick Setup

To enable request payload logging, set these environment variables:

```bash
# Enable request logging
LOG_REQUESTS=true

# Set log level to INFO or DEBUG to see request payloads
LOG_LEVEL=INFO

# Optional: Enable file logging to persist logs
LOG_TO_FILE=true
LOG_FILE=mcpgateway.log
LOG_FOLDER=logs
LOG_FILEMODE=a+
```

## Configuration Options

### Required Settings

- `LOG_REQUESTS=true` - Enables the request logging middleware
- `LOG_LEVEL=INFO` - Ensures request logs are visible (INFO or DEBUG)

### Optional Settings

- `LOG_TO_FILE=true` - Saves logs to file (default: console only)
- `LOG_FILE=mcpgateway.log` - Log file name
- `LOG_FOLDER=logs` - Log folder path
- `LOG_FILEMODE=a+` - File mode (append)
- `LOG_MAX_SIZE_MB=1` - Maximum request body size to log (in MB)

## Example .env Configuration

```env
# Request Logging
LOG_REQUESTS=true
LOG_LEVEL=INFO

# File Logging (optional)
LOG_TO_FILE=true
LOG_FILE=mcpgateway.log
LOG_FOLDER=logs
LOG_FILEMODE=a+
LOG_MAX_SIZE_MB=4

# Other settings
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
PLATFORM_ADMIN_EMAIL=admin@example.com
PLATFORM_ADMIN_PASSWORD=changeme
PLATFORM_ADMIN_FULL_NAME="Platform Administrator"
```

## What Gets Logged

When enabled, you'll see detailed request information including:

- HTTP method and path
- Query parameters
- Request headers (with sensitive data masked)
- Request body/payload (with sensitive fields masked)
- Truncation notice if body exceeds size limit

### Example Log Output

```
📩 Incoming request: POST /tools
Query params: {}
Headers: {'host': 'localhost:4444', 'content-type': 'application/json', 'authorization': '******'}
Body: {
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_system_time",
    "arguments": {
      "timezone": "Europe/Dublin"
    }
  },
  "id": 1758624387514
}
```

## Security Features

The logging middleware automatically masks sensitive information:

- **Headers**: Authorization, authentication tokens
- **Body fields**: password, secret, token, apikey, access_token, refresh_token, client_secret
- **Large payloads**: Truncated with notice if they exceed the size limit

## Troubleshooting

### No Request Logs Appearing

1. Check that `LOG_REQUESTS=true` is set
2. Verify `LOG_LEVEL` is set to `INFO` or `DEBUG`
3. Restart the gateway after changing configuration

### Logs Not Saved to File

1. Ensure `LOG_TO_FILE=true` is set
2. Check that the log folder exists and is writable
3. Verify `LOG_FILE` and `LOG_FOLDER` paths are correct

### Request Bodies Truncated

- Increase `LOG_MAX_SIZE_MB` if you need to see larger payloads
- Default is 1MB to prevent log files from becoming too large

## Performance Considerations

- Request logging adds minimal overhead
- Large request bodies are automatically truncated
- Sensitive data is masked, not removed, so original functionality is preserved
- Logging is skipped entirely if `LOG_REQUESTS=false`

## Example Usage

1. Set environment variables:
   ```bash
   export LOG_REQUESTS=true
   export LOG_LEVEL=INFO
   export LOG_TO_FILE=true
   export LOG_FOLDER=logs
   ```

2. Start the gateway:
   ```bash
   mcpgateway --host 0.0.0.0 --port 4444
   ```

3. Make a request and check the logs:
   ```bash
   # Check console output or log file
   tail -f logs/mcpgateway.log
   ```

Now you can see the full request payloads (with sensitive data masked) to debug tool registration and other API issues.
