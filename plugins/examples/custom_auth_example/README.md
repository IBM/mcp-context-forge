# Custom Authentication Example Plugin

This plugin demonstrates the two-layer HTTP authentication hook architecture in ContextForge, showing how to implement custom authentication mechanisms.

## Overview

The plugin showcases both authentication layers:

1. **HTTP_PRE_REQUEST** (Middleware Layer): Transform custom authentication headers before authentication
2. **HTTP_AUTH_RESOLVE_USER** (Auth Layer): Implement custom user authentication systems

## Use Cases

- Convert custom API key headers to standard bearer tokens
- Authenticate users via LDAP/Active Directory
- Validate mTLS client certificates
- Integrate with external authentication services
- Support proprietary token formats

## Configuration

Add to `plugins/config.yaml`:

```yaml
plugins:
  - name: custom_auth_example
    enabled: true
    priority: 10
    config:
      # Custom header to extract API key from (case-insensitive)
      api_key_header: "x-api-key"

      # Mapping of API keys to user information
      # Key: API key value
      # Value: User information dict
      api_key_mapping:
        "demo-key-12345":
          email: "demo@example.com"
          full_name: "Demo User"
          is_admin: false
        "admin-key-67890":
          email: "admin@example.com"
          full_name: "Admin User"
          is_admin: true

      # Enable LDAP authentication (placeholder for demonstration)
      ldap_enabled: false

      # Enable mTLS certificate authentication
      mtls_enabled: false

      # Transform custom headers to Authorization: Bearer format
      transform_headers: true
```

## How It Works

### Layer 1: Header Transformation (HTTP_PRE_REQUEST)

Runs in middleware **before** any authentication logic:

```
Client Request:
  X-API-Key: demo-key-12345

↓ HTTP_PRE_REQUEST hook transforms headers

Modified Request:
  Authorization: Bearer demo-key-12345
  X-API-Key: demo-key-12345  (original preserved)
```

This allows clients to use custom authentication headers that get transformed into standard formats.

### Layer 2: User Authentication (HTTP_AUTH_RESOLVE_USER)

Runs inside `get_current_user()` **before** standard JWT validation:

```
1. Plugin receives authentication payload:
   - credentials: {"scheme": "Bearer", "credentials": "demo-key-12345"}
   - headers: All request headers
   - client_host: "192.168.1.100"
   - client_port: 54321

2. Plugin checks API key mapping:
   - Finds "demo-key-12345" in api_key_mapping
   - Retrieves user info: {"email": "demo@example.com", ...}

3. Plugin returns authenticated user:
   - User object created from mapping
   - continue_processing = False (skip standard JWT auth)

4. If no match, plugin returns continue_processing = True:
   - Falls back to standard JWT/API token validation
```

## Usage Examples

### Example 1: API Key Authentication

**Client Request:**
```bash
curl -H "X-API-Key: demo-key-12345" \
     https://gateway.example.com/protocol/initialize
```

**What Happens:**
1. Middleware transforms `X-API-Key` → `Authorization: Bearer demo-key-12345`
2. Auth resolution hook looks up `demo-key-12345` in `api_key_mapping`
3. User `demo@example.com` is authenticated
4. Request succeeds with user context

### Example 2: Standard Bearer Token (Fallback)

**Client Request:**
```bash
curl -H "Authorization: Bearer eyJhbGciOi..." \
     https://gateway.example.com/protocol/initialize
```

**What Happens:**
1. Middleware sees standard Authorization header, no transformation needed
2. Auth resolution hook doesn't find token in API key mapping
3. Returns `continue_processing=True`
4. Falls back to standard JWT validation
5. Request succeeds if JWT is valid

### Example 3: mTLS Certificate Authentication

**Configuration:**
```yaml
config:
  mtls_enabled: true
```

**Nginx/Reverse Proxy Configuration:**
```nginx
location / {
    proxy_pass http://mcp-gateway:4444;
    proxy_set_header X-Client-Cert-DN $ssl_client_s_dn;
    ssl_client_certificate /path/to/ca.crt;
    ssl_verify_client on;
}
```

**What Happens:**
1. Client presents TLS client certificate
2. Reverse proxy validates certificate
3. Proxy adds `X-Client-Cert-DN: CN=user@example.com,O=Example` header
4. Plugin extracts DN and authenticates user
5. Request succeeds with user context from certificate

### Example 4: Multiple Authentication Methods

The plugin supports fallback chains:

```
Priority 1: API Key Mapping
  ↓ (if not found)
Priority 2: mTLS Certificate
  ↓ (if not enabled/found)
Priority 3: LDAP Token
  ↓ (if not enabled/found)
Fallback: Standard JWT/API Token Validation
```

## Security Considerations

1. **API Key Storage**: Store API keys securely, never commit to version control
2. **Environment Variables**: Use environment variable substitution in config:
   ```yaml
   api_key_mapping:
     "${DEMO_API_KEY}":
       email: "demo@example.com"
   ```
3. **Rate Limiting**: Combine with rate_limiter plugin to prevent brute force
4. **Audit Logging**: Plugin logs authentication attempts at INFO level
5. **Token Rotation**: Regularly rotate API keys in production
6. **mTLS Security**: Validate certificate revocation status in production

## Extending the Plugin

### Add LDAP Authentication

```python
async def http_auth_resolve_user(self, payload, context):
    if self._cfg.ldap_enabled:
        ldap_token = payload.headers.root.get("x-ldap-token")
        if ldap_token:
            # Import LDAP library
            import ldap3

            # Connect to LDAP server
            server = ldap3.Server(self._cfg.ldap_server)
            conn = ldap3.Connection(server, user=dn, password=ldap_token)

            # Authenticate
            if conn.bind():
                # Query user attributes
                conn.search(...)
                user_info = conn.entries[0]

                # Return authenticated user
                return PluginResult(
                    modified_payload={
                        "email": user_info.mail.value,
                        "full_name": user_info.displayName.value,
                        ...
                    },
                    continue_processing=False
                )

    return PluginResult(continue_processing=True)
```

### Add OAuth Token Validation

```python
async def http_auth_resolve_user(self, payload, context):
    if payload.credentials:
        token = payload.credentials.get("credentials")

        # Validate with external OAuth provider
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://oauth.provider.com/userinfo",
                headers={"Authorization": f"Bearer {token}"}
            )

            if resp.status_code == 200:
                user_info = resp.json()
                return PluginResult(
                    modified_payload={
                        "email": user_info["email"],
                        "full_name": user_info["name"],
                        ...
                    },
                    continue_processing=False
                )

    return PluginResult(continue_processing=True)
```

## Testing

Create test cases in `tests/unit/mcpgateway/plugins/plugins/custom_auth_example/`:

```python
import pytest
from mcpgateway.plugins.framework import (
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
    HttpPreRequestPayload,
    PluginConfig,
    PluginContext,
)
from mcpgateway.plugins.custom_auth_example.custom_auth import CustomAuthPlugin

@pytest.fixture
def plugin():
    config = PluginConfig(
        name="custom_auth",
        config={
            "api_key_mapping": {
                "test-key-123": {
                    "email": "test@example.com",
                    "full_name": "Test User",
                    "is_admin": False,
                }
            }
        }
    )
    return CustomAuthPlugin(config)

@pytest.mark.asyncio
async def test_header_transformation(plugin):
    """Test X-API-Key → Authorization transformation."""
    payload = HttpPreRequestPayload(
        path="/protocol/initialize",
        method="POST",
        headers=HttpHeaderPayload({"x-api-key": "test-key-123"}),
    )
    context = PluginContext(request_id="test-123")

    result = await plugin.http_pre_request(payload, context)

    assert result.modified_payload is not None
    assert result.modified_payload.root["authorization"] == "Bearer test-key-123"

@pytest.mark.asyncio
async def test_api_key_authentication(plugin):
    """Test API key lookup and user authentication."""
    payload = HttpAuthResolveUserPayload(
        credentials={"scheme": "Bearer", "credentials": "test-key-123"},
        headers=HttpHeaderPayload({}),
    )
    context = PluginContext(request_id="test-456")

    result = await plugin.http_auth_resolve_user(payload, context)

    assert result.modified_payload is not None
    assert result.modified_payload["email"] == "test@example.com"
    assert result.continue_processing is False
```

## Integration with Authorization Flow

This plugin integrates with ContextForge's authentication flow as documented in `docs/docs/architecture/authorization-flow.md`:

```
Client Request
  ↓
[1] HTTP_PRE_REQUEST Hook (this plugin)
  - Transform X-API-Key to Authorization header
  ↓
[2] TokenScopingMiddleware
  - Check IP/time restrictions
  ↓
[3] Route Handler with get_current_user()
  ↓
  [3a] HTTP_AUTH_RESOLVE_USER Hook (this plugin)
    - Check API key mapping
    - Authenticate user via custom method
    ↓ (if continue_processing=False)
  User Authenticated by Plugin
    ↓
  [3b] Standard JWT Validation (skipped)
  ↓
[4] RBAC Permission Checks
  ↓
Response
```

## Troubleshooting

### API Key Not Working

1. Check plugin is enabled in `plugins/config.yaml`
2. Verify API key is in `api_key_mapping`
3. Check header name matches `api_key_header` (case-insensitive)
4. Review logs: `grep "CustomAuthPlugin" logs/mcpgateway.log`

### Headers Not Transformed

1. Ensure `transform_headers: true` in config
2. Verify Authorization header is not already present
3. Check plugin priority (should run early, priority < 50)

### Authentication Falls Back to JWT

This is expected behavior when:
- API key not found in mapping
- Custom auth method not enabled
- Plugin returns `continue_processing=True`

The gateway will try standard JWT/API token validation as fallback.

## References

- [Authorization Flow Documentation](../../docs/docs/architecture/authorization-flow.md)
- [Plugin Framework Documentation](../../docs/docs/architecture/plugins.md)
- [HTTP Authentication Hooks](../../mcpgateway/plugins/framework/hooks/http.py)
- [Auth Middleware](../../mcpgateway/middleware/http_auth_middleware.py)
- [get_current_user() Implementation](../../mcpgateway/auth.py)
