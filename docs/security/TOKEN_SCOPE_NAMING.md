# Token Scope Field Naming Convention

## Overview

The token scope enforcement implementation uses different field names for JWT tokens vs. database API tokens. This is intentional and reflects the different data models, but both work correctly with the unified `token_scopes` field in the user context.

## Field Names by Token Type

### JWT Tokens (Session & API)
- **Storage**: JWT payload contains `scopes.permissions` array
- **Example**:
  ```json
  {
    "email": "user@example.com",
    "scopes": {
      "permissions": ["tools.read", "a2a.read"]
    }
  }
  ```
- **Extraction**: `mcpgateway/auth.py:1770-1776`
  ```python
  scopes = payload.get("scopes")
  if scopes and isinstance(scopes, dict):
      permissions = scopes.get("permissions", [])
      if permissions:
          request.state.token_scopes = permissions
  ```

### Database API Tokens
- **Storage**: `EmailApiToken.resource_scopes` column (JSON array)
- **Example**:
  ```python
  EmailApiToken(
      user_email="user@example.com",
      resource_scopes=["tools.read", "a2a.read"]
  )
  ```
- **Extraction**: `mcpgateway/auth.py:713-717`
  ```python
  return {
      "user_email": api_token.user_email,
      "jti": api_token.jti,
      "resource_scopes": api_token.resource_scopes or [],
  }
  ```
- **Propagation**: `mcpgateway/auth.py:1821`
  ```python
  request.state.token_scopes = api_token_info.get("resource_scopes", [])
  ```

## Unified User Context

Both token types converge to a single `token_scopes` field in the user context:

```python
# mcpgateway/middleware/rbac.py:416, 439
token_scopes = getattr(request.state, "token_scopes", None)

return {
    "email": user.email,
    # ... other fields ...
    "token_scopes": token_scopes,  # Unified field name
}
```

## Permission Checking

The `@require_permission` decorator uses the unified `token_scopes` field:

```python
# mcpgateway/middleware/rbac.py:683-692
token_scopes = user_context.get("token_scopes")
if token_scopes is not None:
    if permission not in token_scopes:
        raise HTTPException(
            status_code=403,
            detail=f"API token missing required scope: {permission}"
        )
```

## Why Different Names?

1. **JWT Standard**: JWT tokens use nested `scopes.permissions` to align with OAuth 2.0 conventions
2. **Database Schema**: Database tokens use `resource_scopes` to clearly indicate these are resource-level permissions
3. **Backward Compatibility**: Existing JWT tokens in production use the `scopes.permissions` structure
4. **Type Safety**: Different names prevent accidental mixing of JWT and database token fields

## Migration Path

If unified naming is desired in the future:

1. Add `permissions` alias to `EmailApiToken.resource_scopes` in database schema
2. Update JWT generation to use top-level `permissions` array
3. Maintain backward compatibility by checking both field names during transition
4. Deprecate old field names after migration period

## Security Implications

The different naming does NOT affect security:
- Both paths correctly extract scopes into `request.state.token_scopes`
- Both paths use the same permission checking logic
- Both paths enforce Layer 1 (scope) before Layer 2 (RBAC)
- Test coverage validates both JWT and database token paths

## References

- JWT token scope extraction: `mcpgateway/auth.py:1770-1776`
- Database token scope extraction: `mcpgateway/auth.py:713-717, 1821`
- Unified permission checking: `mcpgateway/middleware/rbac.py:680-692`
- Test coverage: `tests/security/test_token_scope_enforcement_regression.py`