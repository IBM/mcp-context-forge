# Configurable JWT Authentication Header

ContextForge supports configurable HTTP headers for JWT authentication, allowing you to free up the standard `Authorization` header for downstream MCP servers.

## Overview

By default, ContextForge uses the standard `Authorization` header for JWT authentication. When a client wants to send a *different* token to a downstream MCP server (for example, the user's own bearer token), the gateway-bound `Authorization` value collides with the downstream-bound one.

The `AUTH_HEADER_NAME` configuration option lets ContextForge read its own JWT from a different header (for example `X-MCP-Gateway-Auth`), so the standard `Authorization` header is left untouched on the inbound request and remains available for downstream forwarding.

!!! warning "Authorization is not auto-forwarded to every downstream server"
    Setting `AUTH_HEADER_NAME` only changes which header the *gateway* reads on the inbound request. Whether `Authorization` reaches a particular downstream MCP server depends on **how that gateway is registered**:

    * `auth_type=none` registered gateways forward the inbound `Authorization` header as-is.
    * `auth_type=basic`, `auth_type=bearer`, or `auth_type=oauth` registered gateways **replace** `Authorization` with the configured server credentials. The client's `Authorization` is not forwarded.
    * For all gateway auth types, clients can opt into explicit downstream passthrough by sending `X-Upstream-Authorization: Bearer <token>`. ContextForge renames it to `Authorization` on the upstream request. This is the recommended mechanism when the registered gateway already uses its own auth.
    * Internal gateway-to-gateway loopback never forwards `Authorization` (loop-prevention).

    Use `AUTH_HEADER_NAME` together with `X-Upstream-Authorization` (or `auth_type=none` registrations) when you need a downstream-bound `Authorization` header.

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

**Problem**: Your client has its own JWT for a downstream MCP server, but ContextForge's authentication uses the same `Authorization` header.

**Solution**: Configure ContextForge to read its JWT from a different header. Pair it with the appropriate forwarding mechanism for your registered gateway:

```bash
# .env configuration
AUTH_HEADER_NAME=X-MCP-Gateway-Auth
```

**Client Request (recommended — works regardless of gateway auth_type)**:
```http
POST /mcp HTTP/1.1
Host: contextforge.example.com
X-MCP-Gateway-Auth: Bearer <contextforge-jwt>
X-Upstream-Authorization: Bearer <downstream-server-jwt>
Content-Type: application/json
```

**Client Request (alternative — only when the registered gateway has `auth_type=none`)**:
```http
POST /mcp HTTP/1.1
Host: contextforge.example.com
X-MCP-Gateway-Auth: Bearer <contextforge-jwt>
Authorization: Bearer <downstream-server-jwt>
Content-Type: application/json
```

**Result**:
- ContextForge authenticates using `X-MCP-Gateway-Auth`.
- With `X-Upstream-Authorization`: the gateway renames it to `Authorization` on the upstream request, regardless of how the gateway is registered.
- With raw `Authorization` and `auth_type=none`: the gateway forwards it as-is. With other auth types, the gateway will replace it with the registered credentials.

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

`AUTH_HEADER_NAME` only changes how the gateway reads its own JWT on the inbound request. Downstream forwarding is governed by the gateway registration and the existing passthrough machinery:

1. **Custom Auth Header (inbound)**: ContextForge extracts its JWT from `AUTH_HEADER_NAME`. The configured header and the standard `Authorization` header are both protected from plugin overrides on the inbound request.
2. **Authorization to a downstream server**: forwarded only when the gateway is registered with `auth_type=none`, or when the client explicitly opts in via `X-Upstream-Authorization` (recommended).
3. **Loopback (internal gateway-to-gateway)**: `Authorization` is never forwarded, regardless of `AUTH_HEADER_NAME`.
4. **Other Headers**: subject to the standard passthrough allowlist (`enable_header_passthrough`, per-gateway overrides).

### Security Considerations

#### Protected Headers

When `PLUGINS_CAN_OVERRIDE_AUTH_HEADERS=false` (the default), ContextForge prevents plugin pre-request hooks from replacing client-supplied auth-sensitive headers. Both the gateway-bound and the downstream-bound auth headers are protected, so a plugin cannot silently swap a client's downstream token:

**With `AUTH_HEADER_NAME=Authorization` (default)**:
- Protected from override: `Authorization`, `Cookie`, `X-API-Key`, `Proxy-Authorization`

**With `AUTH_HEADER_NAME=X-MCP-Gateway-Auth`**:
- Protected from override: `X-MCP-Gateway-Auth`, `Authorization`, `Cookie`, `X-API-Key`, `Proxy-Authorization`

In both modes, plugins **may still create** `Authorization` (or the configured custom header) when the client did not send one — only existing client-supplied values are protected.

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

**Symptom**: Downstream servers don't receive the `Authorization` header even though `AUTH_HEADER_NAME` is set.

**Likely cause**: The registered gateway's `auth_type` is `basic`, `bearer`, or `oauth`. ContextForge replaces the inbound `Authorization` with those configured credentials. `AUTH_HEADER_NAME` only frees up the inbound side — it does not override gateway-credential injection.

**Solutions** (pick the one that matches your deployment):

```http
# Send the downstream-bound token via X-Upstream-Authorization (recommended)
X-MCP-Gateway-Auth: Bearer <gateway-jwt>
X-Upstream-Authorization: Bearer <downstream-jwt>
```

```text
# Or register the upstream gateway with auth_type=none, in which case the
# client's inbound Authorization header is forwarded as-is.
```

If the request is going through internal loopback (gateway-to-gateway) the `Authorization` header is intentionally dropped to prevent loops; use `X-Upstream-Authorization` instead.

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
