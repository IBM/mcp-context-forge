# HTTP Authentication Hooks

## Overview

HTTP authentication hooks enable plugins to customize how MCP Gateway authenticates incoming requests. These hooks support custom authentication mechanisms like API keys, LDAP, mTLS certificates, and external authentication services without modifying core gateway code.

!!! example "Complete Example Implementation"
    For a full working example of HTTP authentication hooks, see the **[Simple Token Auth Plugin](https://github.com/IBM/mcp-context-forge/tree/main/plugins/examples/simple_token_auth)** which demonstrates:

    - Header transformation (`http_pre_request`)
    - Custom authentication (`http_auth_resolve_user`)
    - Permission checking (`http_auth_check_permission`)
    - Response headers (`http_post_request`)

    The plugin replaces JWT authentication with simple token strings and includes a complete CLI for token management.

## Why HTTP Authentication Hooks?

Traditional authentication in MCP Gateway supports:

- JWT bearer tokens
- API tokens (database-backed)
- Email/password login
- SSO (OAuth/OIDC providers)

However, enterprises often need:

- **Custom token formats**: Proprietary authentication schemes or legacy systems
- **LDAP/Active Directory**: Authenticate against corporate directories
- **mTLS certificates**: Client certificate validation from reverse proxies
- **External auth services**: Integrate with existing authentication infrastructure
- **Header transformation**: Convert non-standard auth headers to standard formats

HTTP authentication hooks solve these problems by allowing plugins to participate in the authentication flow without modifying core code.

## Architecture: Three-Layer Design

The authentication hook system has three layers that work together:

### Layer 1: Middleware (Header Transformation)
**Hook**: `HTTP_PRE_REQUEST`

Runs **before** authentication logic in middleware. Transforms custom headers to standard formats.

**Use Cases**:

- Convert `X-API-Key` → `Authorization: Bearer <token>`
- Transform proprietary auth headers
- Add correlation/tracing headers
- Normalize authentication formats

### Layer 2: Auth Resolution (User Authentication)
**Hook**: `HTTP_AUTH_RESOLVE_USER`

Runs **inside** `get_current_user()` before standard JWT validation. Implements custom authentication.

**Use Cases**:

- LDAP/Active Directory lookup
- mTLS certificate validation
- External OAuth token verification
- Database API key validation
- Custom user resolution logic

### Layer 3: Permission Checking (RBAC Override)
**Hook**: `HTTP_AUTH_CHECK_PERMISSION`

Runs **before** RBAC permission checks in route decorators. Allows plugins to grant/deny permissions based on custom logic.

**Use Cases**:

- Bypass RBAC for token-authenticated users
- Implement time-based access control
- IP-based permission restrictions
- Custom authorization logic
- Grant permissions without database roles

## Hook Types

### HTTP_PRE_REQUEST

**Location**: Middleware layer
**Timing**: Before any authentication
**Payload**: `HttpPreRequestPayload`

```python
class HttpPreRequestPayload(PluginPayload):
    path: str                      # Request path
    method: str                    # HTTP method (GET, POST, etc.)
    headers: HttpHeaderPayload     # Request headers (mutable)
    client_host: str | None        # Client IP address
    client_port: int | None        # Client port
```

**Returns**: `PluginResult[HttpHeaderPayload]` - Modified headers only

**Example**:
```python
async def http_pre_request(
    self,
    payload: HttpPreRequestPayload,
    context: PluginContext
) -> PluginResult[HttpHeaderPayload]:
    """Transform X-API-Key to Authorization header."""
    headers = dict(payload.headers.root)

    # Transform custom header to standard bearer token
    if "x-api-key" in headers and "authorization" not in headers:
        headers["authorization"] = f"Bearer {headers['x-api-key']}"
        return PluginResult(
            modified_payload=HttpHeaderPayload(headers),
            continue_processing=True
        )

    return PluginResult(continue_processing=True)
```

**Important**: Modified headers are applied to the request by updating `request.scope["headers"]` (the ASGI scope), making them immediately visible to all downstream code including FastAPI's `bearer_scheme` dependency, route handlers, and other middleware.

### HTTP_POST_REQUEST

**Location**: Middleware layer
**Timing**: After request completion
**Payload**: `HttpPostRequestPayload`

```python
class HttpPostRequestPayload(HttpPreRequestPayload):
    # Includes all HttpPreRequestPayload fields, plus:
    response_headers: HttpHeaderPayload | None  # Response headers
    status_code: int | None                     # HTTP status code
```

**Returns**: `PluginResult[HttpHeaderPayload]` - Modified response headers

**Use Cases**:

- Audit logging of authentication attempts
- Metrics collection
- Response inspection
- Compliance logging
- **Adding custom response headers** (correlation IDs, trace IDs, auth context)
- **Modifying CORS headers** based on authenticated user
- **Adding compliance headers** (audit trails, data classification)

**Example** (Adding correlation ID to response):
```python
async def http_post_request(
    self,
    payload: HttpPostRequestPayload,
    context: PluginContext
) -> PluginResult[HttpHeaderPayload]:
    """Add correlation ID and auth context to response headers."""
    response_headers = dict(payload.response_headers.root) if payload.response_headers else {}

    # Add correlation ID from request
    if "x-correlation-id" in payload.headers.root:
        response_headers["x-correlation-id"] = payload.headers.root["x-correlation-id"]

    # Add auth method used (from context stored in pre-hook)
    if context.get("auth_method"):
        response_headers["x-auth-method"] = context["auth_method"]

    # Log authentication attempt
    logger.info(f"Auth attempt: {payload.path} - {payload.status_code}")

    return PluginResult(
        modified_payload=HttpHeaderPayload(response_headers),
        continue_processing=True
    )
```

### HTTP_AUTH_RESOLVE_USER

**Location**: Auth layer (inside `get_current_user()`)
**Timing**: Before standard JWT validation
**Payload**: `HttpAuthResolveUserPayload`

```python
class HttpAuthResolveUserPayload(PluginPayload):
    credentials: dict | None       # Bearer token credentials
    headers: HttpHeaderPayload     # All request headers
    client_host: str | None        # Client IP
    client_port: int | None        # Client port
```

**Returns**: `PluginResult[dict]` - Authenticated user dictionary

**User Dictionary Format**:
```python
{
    "email": "user@example.com",          # Required: User email
    "full_name": "User Name",             # Optional: Display name
    "is_admin": False,                     # Optional: Admin flag
    "is_active": True,                     # Optional: Active status
    "password_hash": "",                   # Optional: Not used for custom auth
    "email_verified_at": datetime(...),    # Optional: Verification timestamp
    "created_at": datetime(...),           # Optional: Creation timestamp
    "updated_at": datetime(...),           # Optional: Update timestamp
}
```

**Example**:
```python
from mcpgateway.plugins.framework import PluginViolation, PluginViolationError

async def http_auth_resolve_user(
    self,
    payload: HttpAuthResolveUserPayload,
    context: PluginContext
) -> PluginResult[dict]:
    """Authenticate user via LDAP."""
    if payload.credentials:
        token = payload.credentials.get("credentials")

        # Look up user in LDAP
        ldap_user = await self._ldap_lookup(token)

        if ldap_user:
            # Check if account is locked
            if ldap_user.locked:
                # Explicitly deny authentication with custom error
                raise PluginViolationError(
                    message="Account is locked",
                    violation=PluginViolation(
                        reason="Account locked",
                        description="User account is locked due to security policy",
                        code="ACCOUNT_LOCKED",
                    )
                )

            # Successful authentication - store auth_method in context
            context.state["auth_method"] = "ldap"

            return PluginResult(
                modified_payload={
                    "email": ldap_user.email,
                    "full_name": ldap_user.displayName,
                    "is_admin": ldap_user.is_admin,
                    "is_active": True,
                },
                metadata={"auth_method": "ldap"},  # Stored in request.state
                continue_processing=True  # Allow other plugins to run
            )

    # Fall back to standard JWT validation
    return PluginResult(continue_processing=True)
```

**Important**: Set `continue_processing=True` (not `False`) to allow the auth middleware to use your user data. The plugin manager interprets `continue_processing=True` with a `modified_payload` as "I'm providing data, use it, but don't block other plugins."

### HTTP_AUTH_CHECK_PERMISSION

**Location**: RBAC layer (inside `require_permission` decorator)
**Timing**: Before RBAC permission checks, after authentication
**Payload**: `HttpAuthCheckPermissionPayload`

```python
class HttpAuthCheckPermissionPayload(PluginPayload):
    user_email: str                # Authenticated user's email
    permission: str                # Required permission (e.g., "tools.read")
    resource_type: str | None      # Resource type being accessed
    team_id: str | None            # Team context (if applicable)
    is_admin: bool                 # Whether user has admin privileges
    auth_method: str | None        # Authentication method used
    client_host: str | None        # Client IP address
    user_agent: str | None         # User agent string
```

**Returns**: `PluginResult[HttpAuthCheckPermissionResultPayload]` - Permission decision

**Permission Result Payload**:
```python
class HttpAuthCheckPermissionResultPayload(PluginPayload):
    granted: bool                  # Whether permission is granted
    reason: str | None             # Optional reason for decision
```

**Example** (Grant full permissions to token-authenticated users):
```python
async def http_auth_check_permission(
    self,
    payload: HttpAuthCheckPermissionPayload,
    context: PluginContext
) -> PluginResult[HttpAuthCheckPermissionResultPayload]:
    """Grant permissions to token-authenticated users, bypassing RBAC."""
    # Only handle users authenticated via our custom auth
    if payload.auth_method != "simple_token":
        # Not our auth method, let RBAC handle it
        return PluginResult(continue_processing=True)

    # Grant full permissions to token users
    result = HttpAuthCheckPermissionResultPayload(
        granted=True,
        reason=f"Token-authenticated user {payload.user_email} granted full access"
    )

    return PluginResult(
        modified_payload=result,
        continue_processing=True  # Permission granted, let middleware handle response
    )
```

**Use Cases**:

- Bypass RBAC for service accounts authenticated via tokens
- Implement time-based access control (deny access outside business hours)
- IP-based restrictions (deny access from certain IP ranges)
- Custom authorization logic without database roles
- Temporary permission grants for emergency access

## Complete Example: Custom API Key Authentication

This example shows both layers working together.

!!! tip "Production-Ready Example"
    For a complete, production-ready implementation with all four hooks (including permission checking and response headers), see the **[Simple Token Auth Plugin](https://github.com/IBM/mcp-context-forge/tree/main/plugins/examples/simple_token_auth)**. It includes:

    - File-based token storage with expiration
    - CLI tool for token management
    - Full test coverage
    - Integration with RBAC middleware

    Source: `plugins/examples/simple_token_auth/simple_token_auth.py`

### Plugin Implementation

```python
from mcpgateway.plugins.framework import (
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
    HttpPreRequestPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginResult,
)

class ApiKeyAuthPlugin(Plugin):
    """Authenticate users via X-API-Key header."""

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        # Load API key → user mapping from config
        self.api_keys = config.config.get("api_keys", {})

    async def http_pre_request(
        self,
        payload: HttpPreRequestPayload,
        context: PluginContext
    ) -> PluginResult[HttpHeaderPayload]:
        """Layer 1: Transform X-API-Key to Authorization header."""
        headers = dict(payload.headers.root)

        if "x-api-key" in headers and "authorization" not in headers:
            # Transform to standard bearer token format
            headers["authorization"] = f"Bearer {headers['x-api-key']}"
            return PluginResult(
                modified_payload=HttpHeaderPayload(headers),
                continue_processing=True
            )

        return PluginResult(continue_processing=True)

    async def http_auth_resolve_user(
        self,
        payload: HttpAuthResolveUserPayload,
        context: PluginContext
    ) -> PluginResult[dict]:
        """Layer 2: Validate API key and return user."""
        if payload.credentials:
            api_key = payload.credentials.get("credentials")

            # Check if API key is revoked
            if api_key in self.blocked_keys:
                raise PluginViolationError(
                    message="API key has been revoked",
                    violation=PluginViolation(
                        reason="API key revoked",
                        description="This API key has been revoked",
                        code="API_KEY_REVOKED",
                    )
                )

            # Look up user by API key
            if api_key in self.api_keys:
                user_info = self.api_keys[api_key]
                return PluginResult(
                    modified_payload={
                        "email": user_info["email"],
                        "full_name": user_info["full_name"],
                        "is_admin": user_info.get("is_admin", False),
                        "is_active": True,
                    },
                    continue_processing=False  # User authenticated
                )

        # Fall back to standard auth
        return PluginResult(continue_processing=True)
```

### Plugin Configuration

```yaml
# plugins/config.yaml
plugins:
  - name: api_key_auth
    enabled: true
    priority: 10
    config:
      api_keys:
        "sk-prod-abc123":
          email: "service@example.com"
          full_name: "Production Service"
          is_admin: false
        "sk-admin-xyz789":
          email: "admin@example.com"
          full_name: "Admin User"
          is_admin: true
```

### Usage

```bash
# Client sends custom header
curl -H "X-API-Key: sk-prod-abc123" \
     https://gateway.example.com/protocol/initialize

# What happens:
# 1. HTTP_PRE_REQUEST transforms: X-API-Key → Authorization: Bearer sk-prod-abc123
# 2. HTTP_AUTH_RESOLVE_USER validates API key and returns user
# 3. Request succeeds with user context: service@example.com
```

## Hook Result Handling

### HTTP_AUTH_RESOLVE_USER Results

Plugins can return three types of results from this hook:

#### 1. Successful Authentication
**Return**: `PluginResult` with `modified_payload` (user dict) and `continue_processing=True`

```python
return PluginResult(
    modified_payload={
        "email": "user@example.com",
        "full_name": "User Name",
        "is_admin": False,
        "is_active": True,
    },
    metadata={"auth_method": "simple_token"},  # Stored in request.state
    continue_processing=True,  # Auth middleware will use our user data
)
```

**Result**: User is authenticated using plugin's user data. The `auth_method` from metadata is stored in `request.state` for use by permission hooks.

**Important**: Use `continue_processing=True` (not `False`). The plugin manager interprets `True` with `modified_payload` as "I'm providing data, use it."

#### 2. Explicit Authentication Denial
**Raise**: `PluginViolationError` with custom error message

```python
from mcpgateway.plugins.framework import PluginViolation, PluginViolationError

# Example: Revoked API key
raise PluginViolationError(
    message="API key has been revoked",
    violation=PluginViolation(
        reason="API key revoked",
        description="The API key has been revoked and cannot be used",
        code="API_KEY_REVOKED",
        details={"key_id": "abc123"},
    )
)

# Example: Account locked
raise PluginViolationError(
    message="Account is locked due to security policy",
    violation=PluginViolation(
        reason="Account locked",
        description="User account locked after failed login attempts",
        code="ACCOUNT_LOCKED",
        details={"failed_attempts": 5},
    )
)
```

**Result**: HTTP 401 Unauthorized with the custom error message in the response body.

#### 3. Fallback to Standard Authentication
**Return**: `PluginResult` with `continue_processing=True` and no payload

```python
# Plugin doesn't handle this auth type, try standard JWT validation
return PluginResult(continue_processing=True)
```

**Result**: Gateway falls back to standard JWT/API token validation.

### HTTP_AUTH_CHECK_PERMISSION Results

Plugins can return three types of results from this hook:

#### 1. Grant Permission
**Return**: `PluginResult` with `modified_payload` containing `granted=True`

```python
result = HttpAuthCheckPermissionResultPayload(
    granted=True,
    reason="Token-authenticated user granted full access"
)

return PluginResult(
    modified_payload=result,
    continue_processing=True  # Let middleware handle the response
)
```

**Result**: Permission is granted, user can access the resource.

#### 2. Deny Permission
**Return**: `PluginResult` with `modified_payload` containing `granted=False`

```python
result = HttpAuthCheckPermissionResultPayload(
    granted=False,
    reason="Access denied outside business hours"
)

return PluginResult(
    modified_payload=result,
    continue_processing=True
)
```

**Result**: HTTP 403 Forbidden, user cannot access the resource.

#### 3. Fallback to RBAC
**Return**: `PluginResult` with `continue_processing=True` and no payload

```python
# Not our auth method, let RBAC handle it
return PluginResult(continue_processing=True)
```

**Result**: Gateway falls back to standard RBAC permission checks.

## When to Use Each Result Type

### For HTTP_AUTH_RESOLVE_USER

| Scenario | Result Type | Example |
|----------|-------------|---------|
| Plugin successfully authenticated user | Success (modified_payload + metadata + continue_processing=True) | LDAP bind succeeded, API key valid |
| Plugin recognizes auth method but it's invalid | Denial (raise PluginViolationError) | Revoked API key, locked account, invalid password |
| Plugin doesn't handle this auth type | Fallback (continue_processing=True, no payload) | Not an API key, not an LDAP token |

### For HTTP_AUTH_CHECK_PERMISSION

| Scenario | Result Type | Example |
|----------|-------------|---------|
| Plugin wants to grant permission | Grant (modified_payload with granted=True) | Token user gets full access |
| Plugin wants to deny permission | Deny (modified_payload with granted=False) | Access denied outside business hours |
| Plugin doesn't handle this auth method | Fallback (continue_processing=True, no payload) | Not a token user, use RBAC |

## Request Flow

```
Client Request
  ↓
┌──────────────────────────────────────────────────────────────┐
│ HTTP Auth Middleware                                         │
│ - Generate request_id (stored in request.state)             │
│ - Create GlobalContext with request_id                      │
└──────────────────────────────────────────────────────────────┘
  ↓
┌──────────────────────────────────────────────────────────────┐
│ HTTP_PRE_REQUEST Hook (Layer 1: Middleware)                 │
│ - Transform custom headers (X-API-Key → Authorization)      │
│ - Add tracing/correlation IDs                               │
│ - Normalize authentication formats                           │
│ - Uses request_id from GlobalContext                        │
└──────────────────────────────────────────────────────────────┘
  ↓
Token Scoping Middleware
  ↓
get_current_user() Dependency
  ↓
┌──────────────────────────────────────────────────────────────┐
│ HTTP_AUTH_RESOLVE_USER Hook (Layer 2: Authentication)       │
│ - Custom user authentication (LDAP, mTLS, tokens, etc.)     │
│ - Returns user dict with auth_method in metadata            │
│ - Stores auth_method in request.state for later use         │
│ - Three outcomes: authenticate, deny, or fallback           │
│ - Uses same request_id from request.state                   │
└──────────────────────────────────────────────────────────────┘
  ↓
Standard JWT/API Token Validation (if plugin returned continue_processing=True with no payload)
  ↓
get_current_user_with_permissions() → user_context with auth_method
  ↓
┌──────────────────────────────────────────────────────────────┐
│ @require_permission Decorator                                │
│   ↓                                                           │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ HTTP_AUTH_CHECK_PERMISSION Hook (Layer 3: RBAC)       │  │
│ │ - Check if plugin wants to handle permission          │  │
│ │ - Grant/deny based on auth_method, time, IP, etc.     │  │
│ │ - Receives auth_method from user_context               │  │
│ │ - Three outcomes: grant, deny, or fallback to RBAC     │  │
│ │ - Uses same request_id from user_context               │  │
│ └────────────────────────────────────────────────────────┘  │
│   ↓                                                           │
│ Standard RBAC Permission Check (if plugin didn't handle it)  │
└──────────────────────────────────────────────────────────────┘
  ↓
Route Handler Executes
  ↓
┌──────────────────────────────────────────────────────────────┐
│ HTTP_POST_REQUEST Hook (Layer 1: Middleware)                │
│ - Audit logging of auth attempts and outcomes               │
│ - Metrics collection                                         │
│ - Add response headers (correlation ID, auth method, etc.)  │
│ - Uses same request_id from GlobalContext                   │
└──────────────────────────────────────────────────────────────┘
  ↓
Response to Client
```

**Key Data Flow**:

1. **request_id**: Generated once in middleware, propagated through all hooks via `GlobalContext` and `request.state`
2. **auth_method**: Set by authentication plugin in `metadata`, stored in `request.state`, read by permission plugin
3. **user_context**: Contains email, is_admin, auth_method, request_id, ip_address, user_agent

**Hook Invocation Order**: PRE_REQUEST → AUTH_RESOLVE_USER → AUTH_CHECK_PERMISSION → POST_REQUEST

## Advanced Use Cases

### mTLS Certificate Authentication

```python
async def http_auth_resolve_user(
    self,
    payload: HttpAuthResolveUserPayload,
    context: PluginContext
) -> PluginResult[dict]:
    """Authenticate via client certificate (set by reverse proxy)."""
    # Nginx/reverse proxy sets X-Client-Cert-DN header
    cert_dn = payload.headers.root.get("x-client-cert-dn")

    if cert_dn:
        # Parse DN: CN=user@example.com,O=Example Corp
        email = self._extract_email_from_dn(cert_dn)

        # Look up user in directory
        user = await self._user_directory.get_by_email(email)

        if user:
            return PluginResult(
                modified_payload={
                    "email": user.email,
                    "full_name": user.full_name,
                    "is_admin": user.is_admin,
                    "is_active": user.is_active,
                },
                continue_processing=False
            )

    return PluginResult(continue_processing=True)
```

### LDAP/Active Directory

```python
async def http_auth_resolve_user(
    self,
    payload: HttpAuthResolveUserPayload,
    context: PluginContext
) -> PluginResult[dict]:
    """Authenticate against LDAP server."""
    ldap_token = payload.headers.root.get("x-ldap-token")

    if ldap_token:
        # Connect to LDAP server
        conn = await self._ldap_connect()

        # Validate token and retrieve user
        if await conn.authenticate(ldap_token):
            user_attrs = await conn.get_user_attributes()

            return PluginResult(
                modified_payload={
                    "email": user_attrs["mail"],
                    "full_name": user_attrs["displayName"],
                    "is_admin": "admins" in user_attrs.get("groups", []),
                    "is_active": True,
                },
                continue_processing=False
            )

    return PluginResult(continue_processing=True)
```

### Audit Logging (POST_REQUEST)

```python
async def http_post_request(
    self,
    payload: HttpPostRequestPayload,
    context: PluginContext
) -> PluginResult[HttpHeaderPayload]:
    """Log all authentication attempts."""
    # Extract auth info
    auth_header = payload.headers.root.get("authorization", "none")

    # Log authentication attempt
    await self._audit_log.write({
        "timestamp": datetime.now(timezone.utc),
        "path": payload.path,
        "method": payload.method,
        "client_host": payload.client_host,
        "status_code": payload.status_code,
        "auth_type": self._get_auth_type(auth_header),
        "success": payload.status_code < 400,
    })

    return PluginResult(continue_processing=True)
```

## Security Considerations

1. **Fallback Behavior**: If custom auth fails or returns `continue_processing=True`, the gateway falls back to standard JWT/API token validation. This ensures robustness.
2. **Error Handling**: Plugin errors are logged but don't fail requests. Standard authentication continues if plugin fails.
3. **Priority**: Auth plugins should run early (low priority numbers, e.g., 10-20) to ensure they execute before other plugins.
4. **Credential Storage**: Never log or expose credentials. Use secure storage for API key mappings.
5. **Rate Limiting**: Combine with rate_limiter plugin to prevent brute force attacks on custom auth endpoints.
6. **Audit Logging**: Use HTTP_POST_REQUEST for comprehensive audit logging of authentication attempts.

## Testing

Example test for custom auth plugin:

```python
import pytest
from mcpgateway.plugins.framework import (
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
    PluginConfig,
    PluginContext,
)

@pytest.mark.asyncio
async def test_api_key_authentication():
    """Test API key authentication."""
    config = PluginConfig(
        name="api_key_auth",
        config={
            "api_keys": {
                "test-key": {
                    "email": "test@example.com",
                    "full_name": "Test User",
                    "is_admin": False,
                }
            }
        }
    )
    plugin = ApiKeyAuthPlugin(config)

    payload = HttpAuthResolveUserPayload(
        credentials={"scheme": "Bearer", "credentials": "test-key"},
        headers=HttpHeaderPayload({}),
    )
    context = PluginContext(request_id="test-123")

    result = await plugin.http_auth_resolve_user(payload, context)

    assert result.modified_payload is not None
    assert result.modified_payload["email"] == "test@example.com"
    assert result.continue_processing is False
```

## References

### Example Implementations

- **[Simple Token Auth Plugin](https://github.com/IBM/mcp-context-forge/tree/main/plugins/examples/simple_token_auth)** - Production-ready token authentication with all four HTTP hooks, CLI management, and full test coverage
- [Custom Auth Example](https://github.com/IBM/mcp-context-forge/tree/main/plugins/examples/custom_auth_example) - Basic authentication example

### Architecture & Framework

- [Plugin Framework](../../architecture/plugins.md) - Plugin development guide
