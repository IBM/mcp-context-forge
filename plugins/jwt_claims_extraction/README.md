# JWT Claims Extraction Plugin

## Overview

Extracts JWT claims and metadata from access tokens and makes them available to downstream authorization plugins (Cedar, OPA, etc.) via `global_context.state`.

## Purpose

JWT tokens can include:
- **Public claims**: Identity information (sub, email, etc.)
- **Private claims**: Roles, permissions, groups, attributes
- **RFC 9396 Rich Authorization Requests**: Fine-grained permissions for specific operations

This plugin extracts these claims and stores them in `global_context.state["jwt_claims"]` for use by policy enforcement plugins.

## Features

- Extracts standard JWT claims (sub, iss, aud, exp, iat, nbf, jti)
- Extracts custom claims (roles, permissions, groups, attributes)
- Supports RFC 9396 authorization_details
- Non-blocking (permissive mode)
- Error handling (logs errors without blocking auth)

## Configuration

Register the plugin in `plugins/config.yaml`:
```yaml
- name: "JwtClaimsExtractionPlugin"
  kind: "plugins.jwt_claims_extraction.jwt_claims_extraction.JwtClaimsExtractionPlugin"
  description: "Extracts JWT claims for downstream authorization plugins."
  version: "1.0.0"
  author: "Ioannis Ioannou"
  hooks: ["http_auth_resolve_user"]
  tags: ["auth", "jwt", "claims"]
  mode: "permissive"
  priority: 10
  config:
    context_key: jwt_claims
```

## Security Model

The `http_auth_resolve_user` hook fires **before** standard JWT signature verification in the authentication flow. This plugin decodes the token without verification because the standard auth system verifies the signature immediately after this hook returns.

Claims stored in `global_context.state` are only consumed by downstream hooks (e.g. `http_auth_check_permission`) which fire **after** authentication is established. If the JWT is invalid, the request is rejected with 401 and no downstream hook ever reads the unverified claims.

## Usage

### For Downstream Plugins (Cedar, OPA, etc.)

Access extracted claims in an `http_auth_check_permission` hook:
```python
class MyAuthPlugin(Plugin):
    async def http_auth_check_permission(self, payload, context):
        claims = context.global_context.state.get("jwt_claims", {})

        user_roles = claims.get("roles", [])
        if "admin" in user_roles:
            return PluginResult(
                modified_payload=HttpAuthCheckPermissionResultPayload(
                    granted=True,
                    reason="User has admin role",
                ),
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
pytest tests/unit/plugins/test_jwt_claims_extraction.py -v
```

## Related Issues

- Issue #1439: Create JWT claims and metadata extraction plugin
- Issue #1422: [EPIC] Agent and tool authentication and authorization plugin

## Authors

- Ioannis Ioannou

## License

Apache-2.0
