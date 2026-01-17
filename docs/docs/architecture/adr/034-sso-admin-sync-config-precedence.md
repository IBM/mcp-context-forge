# ADR-034: SSO Admin Synchronization and Configuration Precedence

- *Status:* Accepted
- *Date:* 2026-01-17
- *Deciders:* Platform Team

## Context

The EntraID role mapping feature (#2129) introduced automatic role assignment based on SSO group memberships. This raised two critical design questions:

1. **Admin Status Synchronization**: Should SSO logins update the `is_admin` flag based on group membership, potentially revoking admin access for users who were manually granted admin via the Admin UI/API?

2. **Configuration Precedence**: When SSO providers are bootstrapped from environment variables but also modifiable via Admin API, which source should take precedence on application restart?

Both decisions have significant security and operational implications.

## Decision

### 1. Admin Status: Upgrade-Only Synchronization

**Decision**: SSO can only **upgrade** `is_admin` from False to True, never downgrade.

```python
# Only UPGRADE is_admin via SSO, never downgrade
if should_be_admin and not user.is_admin:
    user.is_admin = True
```

**Rationale**:

- The `is_admin` flag is a **platform-level override** that grants `["*"]` permissions via JWT scopes
- Manual admin grants via Admin UI/API are intentional decisions by platform administrators
- SSO should enhance access control, not unexpectedly revoke access
- The RBAC system (`platform_admin` role) already handles group-based role revocation with proper tracking (`granted_by='sso_system'`)
- To revoke admin access, administrators should use the Admin UI/API explicitly

**Trade-offs**:

| Benefit | Trade-off |
|---------|-----------|
| Manual admin grants preserved | Users who gained admin via SSO keep it after losing the group |
| No unexpected access revocation | SSO is not fully authoritative for admin status |
| Simple, predictable behavior | Must use Admin UI to revoke admin |

**Alternative Considered**: Track grant source with `admin_granted_by` field to only revoke SSO-granted admins. Rejected due to schema change complexity and the fact that RBAC roles already provide this granularity.

### 2. Configuration Precedence: Smart Merge

**Decision**: Use "smart merge" for `provider_metadata` during bootstrap:
- Environment config provides **defaults** for keys not in database
- Database values are **preserved** (Admin API changes survive restarts)
- New environment keys introduced in upgrades **apply** automatically

```python
# Env provides base, DB values override
merged_metadata = {**env_metadata, **db_metadata}
```

**Rationale**:

- Admin API changes (like `sync_roles=false`) should survive application restarts
- New configuration options added in upgrades should apply without manual intervention
- Environment config establishes the baseline; Admin API provides customization

**Trade-offs**:

| Benefit | Trade-off |
|---------|-----------|
| Admin API changes survive restarts | Env config changes for existing keys don't apply |
| New env keys apply automatically | Must use Admin API (or reset provider) to change existing keys |
| Predictable precedence rules | Slightly more complex mental model |

**Example**:
```
Env config:  {"groups_claim": "groups", "new_feature": true}
DB config:   {"groups_claim": "custom", "sync_roles": false}
Result:      {"groups_claim": "custom", "new_feature": true, "sync_roles": false}
```

### 3. ID Token Trust Model

**Decision**: Trust the `id_token` received from the token endpoint without signature validation.

**Rationale**:

- The token is received directly from the IdP's token endpoint over HTTPS
- The OAuth flow (state, code exchange) has already been validated
- The token endpoint response is trusted by definition in OAuth 2.0
- Signature validation would require JWKS fetching, caching, rotation handling, and clock skew management
- The threat model (compromised IdP or MITM despite TLS) is beyond what signature validation prevents

**Security Considerations**:

- TLS provides transport security for the token endpoint request
- The code exchange validates the authorization code
- This approach is consistent with most OAuth client libraries

## Implementation Details

### Admin Sync (sso_service.py)

Location: `mcpgateway/services/sso_service.py:761-770`

```python
# Synchronize is_admin status based on current group membership
# NOTE: Only UPGRADE is_admin via SSO, never downgrade
# This preserves manual admin grants made via Admin UI/API
provider = self.get_provider(user_info.get("provider"))
if provider:
    should_be_admin = self._should_user_be_admin(email, user_info, provider)
    if should_be_admin and not user.is_admin:
        logger.info(f"Upgrading is_admin to True for {email}")
        user.is_admin = True
```

### Config Precedence (sso_bootstrap.py)

Location: `mcpgateway/utils/sso_bootstrap.py:329-346`

```python
# Smart merge for provider_metadata
if "provider_metadata" in provider_config and existing_provider.provider_metadata:
    env_metadata = provider_config["provider_metadata"] or {}
    db_metadata = existing_provider.provider_metadata or {}
    merged_metadata = {**env_metadata, **db_metadata}
    provider_config["provider_metadata"] = merged_metadata
```

## Consequences

### Positive

- **Predictable behavior**: Administrators know that manual grants won't be revoked
- **Upgrade safety**: New configuration options apply without manual intervention
- **Admin API respect**: Customizations made via API persist across restarts
- **Simple mental model**: Clear rules for when each config source applies

### Negative

- **Partial SSO authority**: SSO doesn't fully control admin status
- **Config change complexity**: Changing existing keys requires Admin API
- **No signature validation**: Relies on TLS and OAuth flow for token security

### Neutral

- RBAC roles (`platform_admin`) still sync bidirectionally with `granted_by` tracking
- Environment config remains the source of truth for new deployments
- Existing deployments can reset provider to re-apply full env config

## Operational Guidance

### To Revoke Admin Access
Use the Admin UI or API to set `is_admin=false`. SSO will not revoke it automatically.

### To Change provider_metadata After Initial Bootstrap
1. **Option A**: Use Admin API to update the provider's metadata
2. **Option B**: Delete the provider and let bootstrap recreate it from env config

### To Force Env Config to Win
Delete the provider via Admin API, then restart the application. Bootstrap will recreate it with full env config.

## References

- PR #2129: EntraID role mapping feature
- Microsoft UserInfo endpoint docs: https://learn.microsoft.com/en-us/entra/identity-platform/userinfo
- `mcpgateway/services/sso_service.py` - Admin sync implementation
- `mcpgateway/utils/sso_bootstrap.py` - Config merge implementation
- `docs/docs/manage/sso-entra-role-mapping.md` - Feature documentation

## Status

Implemented in PR #2129. Monitor SSO login logs for admin upgrade events.
