# Configurable JWT Authentication Header

ContextForge supports configurable HTTP headers for JWT authentication, allowing you to avoid header collisions with downstream MCP servers.

## Overview

By default, ContextForge uses the standard `Authorization` header for JWT authentication. However, when client applications need to pass their own JWT tokens to downstream MCP servers, this creates a header collision where ContextForge's authentication overwrites the client's token.

The `AUTH_HEADER_NAME` configuration option solves this problem by allowing you to specify an alternative header for ContextForge authentication, preserving the original `Authorization` header for passthrough to backend servers.

## Configuration

### Environment Variable

Set the `AUTH_HEADER_NAME` environment variable to specify which HTTP header ContextForge should use for JWT authentication:

```bash
# Default behavior (uses Authorization header)
AUTH_HEADER_NAME=Authorization

# Alternative header to avoid collision
AUTH_HEADER_NAME=X-MCP-Gateway-Auth
```

### Common Alternative Headers

While you can use any header name, these are commonly used alternatives:

- `X-MCP-Gateway-Auth` - Recommended for MCP-specific deployments
- `X-Gateway-Authorization` - Generic gateway authentication
- `X-CF-Auth` - Short form for ContextForge authentication
- `X-API-Gateway-Auth` - For API gateway deployments

## Use Cases

### Scenario 1: JWT Passthrough to Downstream Servers

**Problem**: Your client application has existing JWT-based authentication and needs to pass tokens to downstream MCP servers, but ContextForge's authentication overwrites the `Authorization` header.

**Solution**: Configure ContextForge to use an alternative authentication header:

```bash
# .env configuration
AUTH_HEADER_NAME=X-MCP-Gateway-Auth
```

**Client Request**:
```http
POST /mcp HTTP/1.1
Host: contextforge.example.com
X-MCP-Gateway-Auth: Bearer <contextforge-jwt>
Authorization: Bearer <downstream-server-jwt>
Content-Type: application/json
```

**Result**:
- ContextForge authenticates using `X-MCP-Gateway-Auth` header
- Original `Authorization` header is preserved and passed to downstream MCP servers
- Backend servers receive the client's original JWT for their authentication

### Scenario 2: Multi-Tenant Deployments

**Problem**: Different tenants have different authentication requirements, and some need to preserve the `Authorization` header for their backend services.

**Solution**: Use a custom authentication header for ContextForge while allowing tenants to use standard `Authorization` for their services:

```bash
AUTH_HEADER_NAME=X-Tenant-Gateway-Auth
```

### Scenario 3: Legacy System Integration

**Problem**: Integrating with legacy systems that expect specific authentication headers.

**Solution**: Configure ContextForge to use a non-conflicting header:

```bash
AUTH_HEADER_NAME=X-Modern-Auth
```

## Implementation Details

### Header Lookup

The authentication header lookup is **case-insensitive**:

```http
# All of these work when AUTH_HEADER_NAME=X-MCP-Gateway-Auth
X-MCP-Gateway-Auth: Bearer token
x-mcp-gateway-auth: Bearer token
X-Mcp-Gateway-Auth: Bearer token
```

### Header Passthrough

When using a custom authentication header (not `Authorization`), the standard `Authorization` header is automatically preserved and passed through to downstream servers:

1. **Custom Auth Header**: ContextForge extracts JWT from configured header
2. **Authorization Header**: Preserved in request and forwarded to backend
3. **Other Headers**: All other headers pass through unchanged

### Security Considerations

#### Protected Headers

When using a custom authentication header, ContextForge protects the configured header from plugin modification while allowing the standard `Authorization` header to pass through:

**With `AUTH_HEADER_NAME=Authorization` (default)**:
- Protected: `Authorization`, `Cookie`, `X-API-Key`, `Proxy-Authorization`

**With `AUTH_HEADER_NAME=X-MCP-Gateway-Auth`**:
- Protected: `X-MCP-Gateway-Auth`, `Cookie`, `X-API-Key`, `Proxy-Authorization`
- **Not Protected**: `Authorization` (allows passthrough)

#### Plugin Override Control

The `PLUGINS_CAN_OVERRIDE_AUTH_HEADERS` setting controls whether plugins can modify authentication headers:

```bash
# Default: plugins cannot override auth headers (secure)
PLUGINS_CAN_OVERRIDE_AUTH_HEADERS=false

# Allow plugins to transform auth headers (use with caution)
PLUGINS_CAN_OVERRIDE_AUTH_HEADERS=true
```

## API Examples

### Python Client

```python
import requests

# ContextForge authentication token
gateway_token = "eyJhbGc..."

# Downstream server authentication token
downstream_token = "eyJhbGc..."

response = requests.post(
    "https://contextforge.example.com/mcp",
    headers={
        "X-MCP-Gateway-Auth": f"Bearer {gateway_token}",
        "Authorization": f"Bearer {downstream_token}",
        "Content-Type": "application/json"
    },
    json={
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 1
    }
)
```

### JavaScript/TypeScript Client

```typescript
const response = await fetch('https://contextforge.example.com/mcp', {
  method: 'POST',
  headers: {
    'X-MCP-Gateway-Auth': `Bearer ${gatewayToken}`,
    'Authorization': `Bearer ${downstreamToken}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    jsonrpc: '2.0',
    method: 'tools/list',
    id: 1
  })
});
```

### cURL

```bash
curl -X POST https://contextforge.example.com/mcp \
  -H "X-MCP-Gateway-Auth: Bearer ${GATEWAY_TOKEN}" \
  -H "Authorization: Bearer ${DOWNSTREAM_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
  }'
```

## WebSocket Support

The configurable authentication header also works with WebSocket connections:

```javascript
const ws = new WebSocket('wss://contextforge.example.com/mcp', {
  headers: {
    'X-MCP-Gateway-Auth': `Bearer ${gatewayToken}`,
    'Authorization': `Bearer ${downstreamToken}`
  }
});
```

## Backward Compatibility

The feature is fully backward compatible:

- **Default Value**: `Authorization` (standard behavior)
- **Existing Deployments**: No changes required unless you want to use the feature
- **Existing Clients**: Continue to work without modification

## Troubleshooting

### Authentication Fails with Custom Header

**Symptom**: 401 Unauthorized when using custom header

**Solution**: Verify the header name matches your configuration:

```bash
# Check your configuration
echo $AUTH_HEADER_NAME

# Ensure client sends matching header (case-insensitive)
curl -v -H "X-MCP-Gateway-Auth: Bearer token" ...
```

### Authorization Header Not Passed Through

**Symptom**: Downstream servers don't receive the `Authorization` header

**Solution**: Ensure you're using a custom authentication header (not `Authorization`):

```bash
# This enables passthrough
AUTH_HEADER_NAME=X-MCP-Gateway-Auth

# This does NOT enable passthrough (default behavior)
AUTH_HEADER_NAME=Authorization
```

### Plugin Conflicts

**Symptom**: Plugins modify authentication headers unexpectedly

**Solution**: Check plugin override settings:

```bash
# Disable plugin auth header override (recommended)
PLUGINS_CAN_OVERRIDE_AUTH_HEADERS=false
```

## Related Configuration

- [`AUTH_REQUIRED`](./rbac.md#authentication-requirements) - Enable/disable authentication
- [`JWT_SECRET_KEY`](./rbac.md#jwt-configuration) - JWT signing key
- [`PLUGINS_CAN_OVERRIDE_AUTH_HEADERS`](../using/plugins/overview.md) - Plugin header modification

## See Also

- [RBAC Documentation](./rbac.md)
- [Multi-tenancy Architecture](../architecture/multitenancy.md)
- [OAuth Token Delegation](../architecture/oauth-design.md)
- [Plugin Framework](../using/plugins/overview.md)
