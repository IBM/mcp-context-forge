# OAuth Credentials Vault Storage Design

## Problem
When `OAUTH_TOKEN_BACKEND=vault`, OAuth credentials (client_id/client_secret) are stored in the database `gateways.oauth_config` table, which is **not team-scoped**. However, Vault token storage paths are team-scoped: `{mount}/data/{prefix}/{team_id}/{server_id}/{email}`.

This creates a mismatch:
- **Token storage**: Team-scoped (Vault path includes team_id)
- **OAuth credentials**: Gateway-scoped (database gateways table)

## Root Cause
The OAuth callback flow:
1. User with JWT `team_id: f8927490a44d4ede95889136d004c202` initiates OAuth
2. OAuth state stores this team_id
3. On callback, code retrieves `gateway.oauth_config` from database (NOT team-scoped)
4. Uses those credentials for token exchange
5. But the credentials might be wrong for this team!

## Solution: Store OAuth Credentials Per Team in Vault

### Vault Path Structure

OAuth credentials should be stored in Vault at a team-scoped path:
```
{mount}/data/{prefix}/credentials/{team_id}/{server_id}
```

Example:
```
secret/data/contextforge/oauth/credentials/f8927490a44d4ede95889136d004c202/a1b2c3d4
```

Payload:
```json
{
  "data": {
    "mcp_url": "https://mcp.github.acme.com",
    "client_id": "Iv1.abc123def456",
    "client_secret": "secret_value",  
    "authorization_url": "https://github.com/login/oauth/authorize",
    "token_url": "https://github.com/login/oauth/access_token",
    "scopes": ["repo", "read:org"],
    "grant_type": "authorization_code",
    "token_endpoint_auth_method": "client_secret_post",
    "resource": "https://mcp.github.acme.com",
    "created_at": "2026-07-13T11:00:00Z",
    "updated_at": "2026-07-13T11:00:00Z"
  }
}
```

### Migration Path

1. **Phase 1**: Add `VaultTokenBackend._get_oauth_credentials(team_id, mcp_url)` method
2. **Phase 2**: Modify `oauth_router.py` and `vault_router.py` callback handlers to:
   - Try fetching credentials from Vault first
   - Fall back to database `gateway.oauth_config` if Vault returns 404
   - Log warning about database fallback
3. **Phase 3**: Add Admin API endpoint to store OAuth credentials in Vault
4. **Phase 4**: Update documentation to recommend Vault storage for multi-team deployments

### Implementation

```python
# In VaultTokenBackend

def _construct_credentials_path(self, team_id: str, mcp_url: str) -> str:
    """Construct Vault path for OAuth credentials.
    
    Args:
        team_id: Team identifier
        mcp_url: Gateway URL (will be hashed to server_id)
        
    Returns:
        Vault path (e.g., secret/data/contextforge/oauth/credentials/engineering/a1b2c3d4)
    """
    server_id = self._hash_server_id(mcp_url)
    return f"{self.mount}/data/{self.prefix}/credentials/{team_id}/{server_id}"

async def get_oauth_credentials(
    self, 
    team_id: str, 
    mcp_url: str
) -> dict | None:
    """Retrieve team-scoped OAuth credentials from Vault.
    
    Args:
        team_id: Team identifier
        mcp_url: Gateway URL
        
    Returns:
        OAuth config dict or None if not found in Vault
    """
    path = self._construct_credentials_path(team_id, mcp_url)
    result = await self._vault_request("GET", path)
    
    if not result or "data" not in result:
        return None
        
    return result["data"]["data"]
```

### Backward Compatibility

The solution maintains backward compatibility:
- If Vault credential lookup returns None, fall back to `gateway.oauth_config`
- Existing deployments continue working
- Only teams that explicitly store credentials in Vault use team-scoped OAuth

### Security Benefits

1. **Team isolation**: Each team's OAuth credentials are isolated in Vault
2. **Audit trail**: Vault audit logs track OAuth credential access per team
3. **Rotation**: Teams can rotate OAuth credentials independently
4. **Encryption**: Vault encrypts credentials at rest
5. **Access control**: Vault policies can restrict credential access by team

## Next Steps

1. Implement `_get_oauth_credentials()` in `VaultTokenBackend`
2. Update OAuth callback handlers to use Vault credentials
3. Add Admin API for storing OAuth credentials in Vault
4. Document team-scoped OAuth credential management
5. Add migration guide for existing deployments
