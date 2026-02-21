# Multiple Authentication Headers

## Overview

ContextForge now supports multiple custom authentication headers for gateway connections. This feature allows you to configure multiple header key-value pairs that will be sent with every request to your MCP servers.

!!! tip "Admin UI URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444/admin/`
    - Docker Compose (nginx proxy): `http://localhost:8080/admin/`
    - Dev server (`make dev`): `http://localhost:8000/admin/`

## Use Cases

Multiple authentication headers are useful when:

- Your MCP server requires multiple API keys or tokens
- You need to send client identification along with authentication
- Your service uses region-specific or version-specific headers
- You're integrating with services that require complex header-based authentication

## Configuration

### Via Admin UI

1. Navigate to the Admin Panel (see Admin UI URL above)
2. Click on the "Gateways" tab
3. When adding or editing a gateway:

   - Select "Custom Headers" as the Authentication Type
   - Click "Add Header" to add multiple header pairs
   - Enter the header key (e.g., `X-API-Key`) and value for each header
   - Click "Remove" next to any header to delete it
   - Submit the form to save your configuration

### Via API

Send a POST request to `/admin/gateways` with the `auth_headers` field as a JSON array:

```json
{
  "name": "My Gateway",
  "url": "http://mcp-server.example.com",
  "auth_type": "authheaders",
  "auth_headers": [
    {"key": "X-API-Key", "value": "secret-key-123"},
    {"key": "X-Client-ID", "value": "client-456"},
    {"key": "X-Region", "value": "us-east-1"}
  ]
}
```

### Via Python SDK

```python
from mcpgateway.schemas import GatewayCreate

gateway = GatewayCreate(
    name="My Gateway",
    url="http://mcp-server.example.com",
    auth_type="authheaders",
    auth_headers=[
        {"key": "X-API-Key", "value": "secret-key-123"},
        {"key": "X-Client-ID", "value": "client-456"},
        {"key": "X-Region", "value": "us-east-1"}
    ]
)
```

## Backward Compatibility

The gateway still supports the legacy single-header format for backward compatibility:

```json
{
  "name": "My Gateway",
  "url": "http://mcp-server.example.com",
  "auth_type": "authheaders",
  "auth_header_key": "X-API-Key",
  "auth_header_value": "secret-key-123"
}
```

If both `auth_headers` (multi) and `auth_header_key`/`auth_header_value` (single) are provided, the multi-header format takes precedence.

## Security Considerations

### Encryption
All authentication headers are encrypted before being stored in the database using AES-256-GCM encryption. The encryption key is derived from the `AUTH_ENCRYPTION_SECRET` environment variable.

### Header Validation
- Empty header keys are ignored
- Duplicate header keys will use the last provided value
- Header values can be empty strings if required by your authentication scheme
- Special characters in header keys and values are supported

### Best Practices
1. **Use HTTPS**: Always use HTTPS URLs for your MCP servers to prevent header interception
2. **Rotate Keys**: Regularly rotate your API keys and update them in the gateway configuration
3. **Minimal Headers**: Only include headers that are strictly necessary for authentication
4. **Environment Variables**: Store sensitive values in environment variables when deploying

## Common Patterns

### Multiple API Keys
```json
{
  "auth_headers": [
    {"key": "X-Primary-Key", "value": "primary-secret"},
    {"key": "X-Secondary-Key", "value": "secondary-secret"}
  ]
}
```

### API Key with Client Identification
```json
{
  "auth_headers": [
    {"key": "X-API-Key", "value": "api-secret"},
    {"key": "X-Client-ID", "value": "client-123"},
    {"key": "X-Client-Secret", "value": "client-secret"}
  ]
}
```

### Regional Configuration
```json
{
  "auth_headers": [
    {"key": "X-API-Key", "value": "api-secret"},
    {"key": "X-Region", "value": "eu-west-1"},
    {"key": "X-Environment", "value": "production"}
  ]
}
```

## Troubleshooting

### Headers Not Being Sent
1. Check that your gateway is using `auth_type: "authheaders"`
2. Verify headers are properly formatted in the JSON array
3. Ensure the gateway is enabled and reachable
4. Check server logs to confirm headers are being received

### Case Sensitivity
HTTP headers are case-insensitive by specification. Some HTTP clients or servers may normalize header names to lowercase. Your MCP server should handle headers in a case-insensitive manner.

### Validation Errors
If you receive validation errors when saving:

- Ensure at least one header is provided when using "Custom Headers" authentication
- Check that your JSON is properly formatted if using the API
- Verify that header keys don't contain invalid characters

### Testing Your Configuration
Use the "Test" button in the Admin UI to verify your gateway connection with the configured headers. The test will attempt to connect to your MCP server and validate that authentication is working correctly.

## Migration from Single Headers

If you have existing gateways using single header authentication, they will continue to work without modification. To migrate to multi-headers:

1. Edit your gateway in the Admin UI
2. Your existing single header will be displayed
3. Add additional headers as needed
4. Save the configuration

The system will automatically convert your configuration to the multi-header format while preserving your existing authentication.

## API Reference

### GatewayCreate Schema
```python
{
    "name": str,
    "url": str,
    "auth_type": "authheaders",
    "auth_headers": [
        {"key": str, "value": str},
        ...
    ]
}
```

### GatewayUpdate Schema
```python
{
    "auth_type": "authheaders",
    "auth_headers": [
        {"key": str, "value": str},
        ...
    ]
}
```

## Related Documentation
- [Gateway Authentication](../manage/securing.md)
- [Security Best Practices](../architecture/security-features.md)
- [Multi-Auth Headers](./multi-auth-headers.md)
