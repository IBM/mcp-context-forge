# JWT Claims Extraction Plugin

## Overview

This plugin extracts JWT claims and metadata from access tokens and makes them available to downstream authorization plugins (Cedar, OPA, etc.) via a reserved context key.

## Purpose

JWT tokens can include:
- **Public claims**: Identity information (sub, email, etc.)
- **Private claims**: Roles, permissions, groups, attributes
- **RFC 9396 Rich Authorization Requests**: Fine-grained permissions for specific operations

This plugin extracts these claims after JWT verification and stores them in `global_context.metadata["jwt_claims"]` for use by policy enforcement plugins.

## Features

- ✅ Extracts standard JWT claims (sub, iss, aud, exp, iat, nbf, jti)
- ✅ Extracts custom claims (roles, permissions, groups, attributes)
- ✅ Supports RFC 9396 authorization_details
- ✅ Non-blocking (permissive mode)
- ✅ Error handling (logs errors without blocking auth)

## Configuration

The plugin is configured via `config.yaml`:
```yaml
name: jwt_claims_extraction
version: 1.0.0
enabled: true
mode: permissive  # Non-blocking mode
priority: 10      # Runs early in the hook chain
hooks:
  - http_auth_resolve_user
```

## Usage

### For Downstream Plugins

Access extracted claims in your plugin:
```python
class MyAuthPlugin(Plugin):
    async def handle_auth_check(self, payload, context):
        # Access JWT claims from global context
        claims = self._global_context.metadata.get("jwt_claims", {})
        
        # Use claims for authorization
        user_roles = claims.get("roles", [])
        user_permissions = claims.get("permissions", [])
        
        if "admin" in user_roles:
            return PluginResult(
                modified_payload=HttpAuthCheckPermissionResultPayload(
                    granted=True,
                    reason="User has admin role"
                )
            )
```

### Extracted Claims Example
```json
{
  "sub": "user123",
  "email": "user@example.com",
  "roles": ["developer", "admin"],
  "permissions": ["tools.read", "tools.invoke"],
  "groups": ["engineering", "security"],
  "iss": "mcpgateway",
  "aud": "mcpgateway-api",
  "exp": 1234567890,
  "iat": 1234567800,
  "authorization_details": [
    {
      "type": "tool_invocation",
      "actions": ["invoke"],
      "locations": ["db-query", "api-call"]
    }
  ]
}
```

## RFC 9396 Support

The plugin supports [RFC 9396 (Rich Authorization Requests)](https://datatracker.ietf.org/doc/html/rfc9396) for fine-grained permissions:
```json
{
  "authorization_details": [
    {
      "type": "tool_invocation",
      "actions": ["invoke"],
      "locations": ["production-db"],
      "datatypes": ["customer_data"]
    }
  ]
}
```

## Integration with Cedar/OPA

### Cedar Example
```cedar
permit (
  principal,
  action == Action::"tools.invoke",
  resource
)
when {
  context.jwt_claims.roles.contains("developer") &&
  context.jwt_claims.permissions.contains("tools.invoke")
};
```

### OPA Example
```rego
allow {
  input.jwt_claims.roles[_] == "admin"
}

allow {
  "tools.invoke" == input.jwt_claims.permissions[_]
  input.action == "tools.invoke"
}
```

## Testing

Run tests with:
```bash
pytest tests/unit/mcpgateway/plugins/test_jwt_claims_extraction.py -v
```

## Related Issues

- Issue #1439: Create JWT claims and metadata extraction plugin
- Issue #1422: [EPIC] Agent and tool authentication and authorization plugin

## Authors

- Ioannis Ioannou

## License

Apache-2.0
