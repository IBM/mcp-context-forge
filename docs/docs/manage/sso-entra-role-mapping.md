# Microsoft EntraID Role and Group Claim Mapping

## Overview

This feature enables automatic role assignment for Microsoft EntraID (formerly Azure AD) SSO users based on their group memberships or app role assignments. Users are automatically assigned Context Forge RBAC roles based on their EntraID groups, providing granular access control without manual intervention.

## Features

- ✅ Extract groups and roles from EntraID tokens
- ✅ Map EntraID groups to Context Forge RBAC roles
- ✅ Support for both Security Groups (Object IDs) and App Roles
- ✅ Automatic role synchronization on login
- ✅ Platform admin assignment via admin groups
- ✅ Default role assignment for users without group mappings
- ✅ Consistent with Keycloak implementation pattern

## Architecture

### Role System

Context Forge includes a comprehensive RBAC system with the following default roles:

1. **`platform_admin`** (global scope)
   - Permissions: `["*"]` (all permissions)
   - Full platform access

2. **`team_admin`** (team scope)
   - Permissions: Team management, tools, resources, prompts
   - Can manage team members and settings

3. **`developer`** (team scope)
   - Permissions: Tool execution, resource access, prompts
   - Can execute tools and access resources

4. **`viewer`** (team scope)
   - Permissions: Read-only access to tools, resources, prompts
   - Cannot execute tools or modify resources

### Implementation Components

1. **Configuration** (`mcpgateway/config.py`)
   - `sso_entra_groups_claim`: JWT claim for groups (default: "groups")
   - `sso_entra_admin_groups`: Groups granting platform_admin role
   - `sso_entra_role_mappings`: Map groups to roles
   - `sso_entra_default_role`: Default role for unmapped users
   - `sso_entra_sync_roles_on_login`: Sync roles on each login

2. **Token Parsing** (`_get_user_info()` and `_decode_jwt_claims()`)
   - Parses the `id_token` JWT to extract claims (Microsoft's userinfo endpoint doesn't return groups)
   - Extracts `groups` claim (Security Groups as Object IDs)
   - Extracts `roles` claim (App Roles)
   - Falls back to userinfo for basic profile claims (email, name, etc.)

3. **Group Normalization** (`_normalize_user_info()`)
   - Combines groups and roles from id_token
   - Deduplicates and returns normalized user info
   - Supports custom groups claim via provider metadata

4. **Role Mapping** (`_map_groups_to_roles()`)
   - Maps EntraID groups to Context Forge roles
   - Checks admin groups first (case-insensitive)
   - Applies role mappings from configuration
   - Assigns default role if no mappings found

5. **Role Synchronization** (`_sync_user_roles()`)
   - Synchronizes roles on user creation and login
   - Revokes SSO-granted roles no longer in groups
   - Assigns new roles based on current groups
   - Preserves manually assigned roles
   - Maintains audit trail with `granted_by='sso_system'`

6. **Admin Status Synchronization** (`authenticate_or_create_user()`)
   - Upgrades `is_admin` flag when user gains admin group membership
   - **Never downgrades** `is_admin` - manual admin grants via Admin UI/API are preserved
   - To revoke admin access, use the Admin UI/API directly

## Configuration

### 1. EntraID App Registration Setup

#### Token Configuration (Azure Portal)

> **Important**: Groups and roles must be configured in the **ID token**, not just the access token.
> Microsoft's OIDC userinfo endpoint does not return group claims - Context Forge extracts them from the ID token.

1. Navigate to **Azure Portal** → **App Registrations** → Your App
2. Go to **Token Configuration**
3. Click **+ Add groups claim**
4. Select token types: **ID** (required), Access (optional)
5. Select group types:
   - **Security groups** (recommended for most use cases)
   - Or **All groups** if you need Microsoft 365 groups
6. Choose **Group ID** format for stability (Object IDs won't change)
7. For App Roles: Go to **App Roles** and create roles (they are automatically included in tokens)

#### App Roles (Recommended Approach)

1. Navigate to **App Roles** in your App Registration
2. Create roles with semantic names:
   ```json
   {
     "displayName": "Admin",
     "value": "Admin",
     "description": "Platform administrators"
   }
   {
     "displayName": "Developer",
     "value": "Developer",
     "description": "Developers with tool access"
   }
   {
     "displayName": "Viewer",
     "value": "Viewer",
     "description": "Read-only users"
   }
   ```

### 2. Environment Variables

```bash
# Basic EntraID SSO
SSO_ENTRA_ENABLED=true
SSO_ENTRA_CLIENT_ID=your-client-id
SSO_ENTRA_CLIENT_SECRET=your-secret
SSO_ENTRA_TENANT_ID=your-tenant-id

# Role Mapping Configuration
SSO_ENTRA_GROUPS_CLAIM=groups  # or "roles" for app roles
SSO_ENTRA_DEFAULT_ROLE=viewer
SSO_ENTRA_SYNC_ROLES_ON_LOGIN=true

# Admin Groups (Object IDs or App Role names)
SSO_ENTRA_ADMIN_GROUPS=["a1b2c3d4-1234-5678-90ab-cdef12345678","Admin"]

# Group to Role Mapping (JSON format)
SSO_ENTRA_ROLE_MAPPINGS={"e5f6g7h8-1234-5678-90ab-cdef12345678":"developer","i9j0k1l2-1234-5678-90ab-cdef12345678":"team_admin","Developer":"developer","TeamAdmin":"team_admin","Viewer":"viewer"}
```

### 3. Provider Metadata (Database Configuration)

You can also configure role mappings in the SSO provider metadata:

```json
{
  "groups_claim": "roles",
  "role_mappings": {
    "Admin": "platform_admin",
    "Developer": "developer",
    "TeamAdmin": "team_admin",
    "Viewer": "viewer"
  }
}
```

## Usage Examples

### Example 1: Using App Roles (Recommended)

**EntraID Configuration:**
- App Roles: `Admin`, `Developer`, `Viewer`
- Token includes `roles` claim

**Environment Variables:**
```bash
SSO_ENTRA_GROUPS_CLAIM=roles
SSO_ENTRA_ADMIN_GROUPS=["Admin"]
SSO_ENTRA_ROLE_MAPPINGS={"Developer":"developer","Viewer":"viewer"}
SSO_ENTRA_DEFAULT_ROLE=viewer
```

**Result:**
- User with `Admin` role → `platform_admin` (global scope)
- User with `Developer` role → `developer` (team scope)
- User with `Viewer` role → `viewer` (team scope)
- User with no roles → `viewer` (default)

### Example 2: Using Security Groups (Object IDs)

**EntraID Configuration:**
- Security Groups with Object IDs
- Token includes `groups` claim

**Environment Variables:**
```bash
SSO_ENTRA_GROUPS_CLAIM=groups
SSO_ENTRA_ADMIN_GROUPS=["a1b2c3d4-1234-5678-90ab-cdef12345678"]
SSO_ENTRA_ROLE_MAPPINGS={"e5f6g7h8-1234-5678-90ab-cdef12345678":"developer","i9j0k1l2-1234-5678-90ab-cdef12345678":"viewer"}
```

**Result:**
- User in group `a1b2c3d4-...` → `platform_admin`
- User in group `e5f6g7h8-...` → `developer`
- User in group `i9j0k1l2-...` → `viewer`

### Example 3: Mixed Approach

**EntraID Configuration:**
- Both Security Groups and App Roles
- Token includes both `groups` and `roles` claims

**Environment Variables:**
```bash
SSO_ENTRA_GROUPS_CLAIM=groups
SSO_ENTRA_ADMIN_GROUPS=["Admin","a1b2c3d4-1234-5678-90ab-cdef12345678"]
SSO_ENTRA_ROLE_MAPPINGS={"Developer":"developer","e5f6g7h8-1234-5678-90ab-cdef12345678":"team_admin"}
```

## Role Synchronization

### On User Creation

When a new user logs in via EntraID SSO:

1. User info is extracted including groups
2. Groups are mapped to roles via `_map_groups_to_roles()`
3. Roles are assigned via `_sync_user_roles()`
4. User is created with `is_admin` flag if in admin groups
5. RBAC roles are assigned with `granted_by='sso_system'`

### On User Login

When an existing user logs in:

1. User info is updated (name, provider, etc.)
2. If `sso_entra_sync_roles_on_login=true`:
   - Current groups are extracted
   - Groups are mapped to roles
   - Old SSO-granted roles are revoked if no longer in groups
   - New roles are assigned based on current groups

### Manual Role Management

- Admins can manually assign additional roles via the Admin UI
- Manually assigned roles (not granted by `sso_system`) are preserved
- Only SSO-granted roles are synchronized on login

## Token Claims

### Groups Claim Formats

EntraID can return groups in different formats:

1. **Object IDs** (default):
   ```json
   {
     "groups": [
       "a1b2c3d4-1234-5678-90ab-cdef12345678",
       "e5f6g7h8-1234-5678-90ab-cdef12345678"
     ]
   }
   ```

2. **Group Names** (requires configuration):
   ```json
   {
     "groups": [
       "Developers",
       "Admins"
     ]
   }
   ```

3. **App Roles**:
   ```json
   {
     "roles": [
       "Admin",
       "Developer"
     ]
   }
   ```

### Token Size Considerations

EntraID has a token size limit (~200 groups). When a user belongs to more groups than can fit in the token, EntraID returns a "group overage" indicator (`_claim_names`/`_claim_sources`) instead of the actual groups array.

**Context Forge detects this condition and logs a warning:**
```
Group overage detected for user user@example.com - token contains too many groups (>200).
Role mapping may be incomplete. Consider using App Roles or Azure group filtering.
```

**Solutions for group overage:**

1. **Use App Roles** (Recommended) - App roles are always included in the token and not subject to overage limits
2. **Azure group filtering** - In Azure Portal → App Registration → Token Configuration, filter groups to only include specific security groups
3. **Claims transformation** - Use Azure claims mapping policies to reduce group claims
4. **Direct group assignment** - Assign groups directly to the application instead of user-level membership

**Reference:** [Microsoft Groups Overage Claim](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens#groups-overage-claim)

## Security Considerations

### Group ID vs Name Mapping

- **Object IDs**: Stable but not human-readable
- **Group Names**: Readable but can change
- **App Roles**: Stable, semantic, and recommended

### Best Practices

1. **Use App Roles** for stable, semantic mappings
2. **Limit admin groups** to minimize security risk
3. **Enable role sync** to keep permissions current
4. **Audit role assignments** via permission audit logs
5. **Test mappings** before production deployment

## Troubleshooting

### Issue: Users not getting roles

**Check:**
1. Token includes `groups` or `roles` claim
2. `SSO_ENTRA_GROUPS_CLAIM` matches claim name in token
3. Group IDs/names match `SSO_ENTRA_ROLE_MAPPINGS`
4. Roles exist in Context Forge (check via Admin UI)

**Debug:**
```bash
# Check user's SSO metadata
SELECT sso_metadata FROM pending_user_approval WHERE email='user@example.com';

# Check user's current roles
SELECT r.name, ur.scope, ur.granted_by
FROM user_roles ur
JOIN roles r ON ur.role_id = r.id
WHERE ur.user_email='user@example.com';
```

### Issue: Admin users not getting admin access

**Check:**
1. User's group is in `SSO_ENTRA_ADMIN_GROUPS`
2. Group ID/name matches exactly (case-insensitive)
3. `is_admin` flag is set on user record

**Debug:**
```bash
# Check user's admin status
SELECT email, is_admin, auth_provider FROM email_users WHERE email='user@example.com';
```

### Issue: Roles not syncing on login

**Check:**
1. `SSO_ENTRA_SYNC_ROLES_ON_LOGIN=true`
2. User has groups in token
3. No errors in application logs

**Debug:**
```bash
# Check application logs for role sync messages
grep "Assigned SSO role" /var/log/mcpgateway.log
grep "Revoked SSO role" /var/log/mcpgateway.log
```

### Issue: Group overage - user has too many groups

**Symptoms:**
- User doesn't receive expected roles
- Application logs show: `Group overage detected for user ... token contains too many groups (>200)`

**Cause:**
User belongs to more than ~200 security groups. EntraID cannot fit all groups in the token and instead includes a "groups overage" indicator.

**Solutions:**
1. **Use App Roles** (Recommended) - Not subject to token size limits
2. **Configure group filtering** - In Azure Portal, limit which groups are included in the token
3. **Assign groups to the application** - Use application-assigned groups instead of user memberships

**Debug:**
```bash
# Check for overage warnings in logs
grep "Group overage detected" /var/log/mcpgateway.log
```

See [Token Size Considerations](#token-size-considerations) for detailed solutions.

## Migration Guide

### Migrating from Admin-Only to RBAC

If you previously used only the `is_admin` flag:

1. **Identify current admin users**:
   ```sql
   SELECT email FROM email_users WHERE is_admin=true AND auth_provider='entra';
   ```

2. **Configure admin groups**:
   ```bash
   SSO_ENTRA_ADMIN_GROUPS=["your-admin-group-id"]
   ```

3. **Configure role mappings** for non-admin users:
   ```bash
   SSO_ENTRA_ROLE_MAPPINGS={"developer-group":"developer","viewer-group":"viewer"}
   ```

4. **Enable role sync**:
   ```bash
   SSO_ENTRA_SYNC_ROLES_ON_LOGIN=true
   ```

5. **Test with non-admin users** first
6. **Roll out to all users**

## API Reference

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sso_entra_groups_claim` | str | "groups" | JWT claim for groups |
| `sso_entra_admin_groups` | list[str] | [] | Groups granting platform_admin |
| `sso_entra_role_mappings` | dict[str,str] | {} | Map groups to roles |
| `sso_entra_default_role` | str | None | Default role for unmapped users (None = no automatic role) |
| `sso_entra_sync_roles_on_login` | bool | true | Sync roles on each login |

### Methods

#### `_normalize_user_info(provider, user_data)`
Extracts user info and groups from EntraID token.

**Returns:**
```python
{
  "email": str,
  "full_name": str,
  "provider": "entra",
  "groups": list[str]  # Group IDs or role names
}
```

#### `_map_groups_to_roles(user_email, user_groups, provider)`
Maps EntraID groups to Context Forge roles.

**Returns:**
```python
[
  {
    "role_name": str,
    "scope": str,  # "global" or "team"
    "scope_id": Optional[str]
  }
]
```

#### `_sync_user_roles(user_email, role_assignments, provider)`
Synchronizes user's role assignments.

**Side Effects:**
- Revokes old SSO-granted roles
- Assigns new roles from current groups
- Commits changes to database

## Comparison with Other Providers

| Feature | Keycloak | EntraID | GitHub | Google |
|---------|----------|---------|--------|--------|
| Group extraction | ✅ | ✅ | ❌ | ❌ |
| Role mapping | ✅ | ✅ | ❌ | ❌ |
| Admin groups | ✅ | ✅ | ✅ | ✅ |
| Role sync on login | ✅ | ✅ | ❌ | ❌ |
| Custom claim name | ✅ | ✅ | N/A | N/A |

## Future Enhancements

- [ ] Team-scoped role assignments based on groups
- [ ] Role mapping UI in Admin panel
- [ ] Group-to-team mapping
- [ ] Conditional role assignment based on additional claims
- [ ] Role assignment expiration based on group membership duration

## Design Decisions

This section documents key architectural decisions. See [ADR-034](../architecture/adr/034-sso-admin-sync-config-precedence.md) for full details.

### Admin Status Synchronization

**Behavior**: SSO can only **upgrade** `is_admin` to True, never downgrade.

| Scenario | Behavior |
|----------|----------|
| User gains admin group | `is_admin` upgraded to True |
| User loses admin group | `is_admin` **preserved** (not revoked) |
| Manual admin grant | Preserved across all SSO logins |

**Rationale**:
- Manual admin grants via Admin UI/API are intentional decisions
- RBAC roles (`platform_admin`) already handle group-based role sync with revocation
- To revoke admin access, use the Admin UI/API explicitly

**Note**: The `is_admin` flag provides a platform-level bypass. RBAC roles provide granular, auditable access control with proper `granted_by` tracking.

### Configuration Precedence (Bootstrap)

**Behavior**: Smart merge - environment provides defaults, database values preserved.

| Key Source | Behavior |
|------------|----------|
| Only in env config | Applied (new features) |
| Only in database | Preserved (Admin API changes) |
| In both | **Database wins** |

**Example**:
```
Env:    {"groups_claim": "groups", "new_feature": true}
DB:     {"groups_claim": "custom", "sync_roles": false}
Result: {"groups_claim": "custom", "new_feature": true, "sync_roles": false}
```

**To change a key that exists in database**:
1. Use Admin API to update the provider
2. Or delete the provider and restart (bootstrap recreates from env)

### ID Token Trust Model

Groups and roles are extracted from the `id_token` JWT received from the token endpoint. The token is trusted without signature validation because:

- Received directly from IdP over HTTPS after valid code exchange
- OAuth flow (state, PKCE) already validated
- Consistent with standard OAuth client library behavior

**Important**: Configure group claims in the **ID token** in Azure Portal. The OIDC userinfo endpoint does not return groups.

## References

- [Microsoft identity platform UserInfo endpoint](https://learn.microsoft.com/en-us/entra/identity-platform/userinfo) - Why groups aren't in userinfo
- [Configure optional claims](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims) - Group limits and token configuration
- [ID token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference) - Groups overage claim details
- [Configure group claims for applications](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-fed-group-claims) - Advanced group claim configuration

## Support

For issues or questions:
1. Check application logs for error messages
2. Verify EntraID token configuration in Azure Portal
3. Test with a single user before rolling out
4. Consult the troubleshooting section above
5. Open an issue on GitHub with logs and configuration (redact secrets)
