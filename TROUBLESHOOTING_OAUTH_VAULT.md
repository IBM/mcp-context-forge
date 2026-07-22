# Troubleshooting OAuth + Vault Integration

## Issue: "No OAuth tokens found" after successful authorization

### Symptoms
- ✅ OAuth authorization completes successfully
- ✅ Tokens are stored in Vault (visible with `vault kv list`)
- ❌ "Fetch Tools" fails with: `No OAuth tokens found for user user2@example.com on gateway github-server`
- ❌ Path in Vault is `secret/contextforge/oauth/d855a360a0f24f56ac2b5a1ab54cbb70/` instead of expected `secret/contextforge/oauth/team1/ca602dd4/`

### Root Cause
The `team_id` is being derived incorrectly during token storage OR retrieval, leading to a path mismatch.

### Diagnosis Steps

#### Step 1: Check Vault Structure

```bash
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=test-root-token

# Run the debug script
python3 scripts/check-vault-structure.py
```

**Expected Output:**
```
📂 secret/data/contextforge/oauth/
  📁 team1/               # ← Should be team_id, not a hash
    📁 ca602dd4/           # ← server_id (hash of gateway.url)
      📄 user2%40example.com
        Keys: ['email', 'team_id', 'mcp_url', 'token', 'user_id', ...]
        email: user2@example.com
        team_id: team1
        mcp_url: https://mcp.github.example.com
```

**Actual Output (Bug):**
```
📂 secret/data/contextforge/oauth/
  📁 d855a360a0f24f56ac2b5a1ab54cbb70/   # ← This is wrong! Should be team_id
```

#### Step 2: Check User's Team Membership

```bash
# Check database for user's team
sqlite3 mcp.db "SELECT * FROM email_team_members WHERE user_email='user2@example.com';"
```

Expected: At least one active team membership

If **no rows found**, the user has no team membership, so `_get_team_id()` falls back to `"default"`.

#### Step 3: Check User Context During OAuth Flow

Add debug logging to `mcpgateway/services/token_storage_service.py`:

```python
def _get_team_id(self, app_user_email: str) -> str:
    logger.info(f"🔍 _get_team_id called for {app_user_email}")
    logger.info(f"   user_context: {self.user_context}")
    
    # First priority: Try user_context (JWT teams claim)
    if self.user_context:
        teams = self.user_context.get("teams", [])
        logger.info(f"   teams from context: {teams}")
        if isinstance(teams, list) and teams:
            team_id = teams[0]
            logger.info(f"   ✅ Using team_id from context: {team_id}")
            return team_id

    # Second priority: Query database for user's teams
    if app_user_email and self.db:
        try:
            from mcpgateway.db import EmailTeamMember
            from sqlalchemy import select

            team_members = self.db.execute(
                select(EmailTeamMember)
                .where(
                    EmailTeamMember.user_email == app_user_email,
                    EmailTeamMember.is_active.is_(True),
                )
                .order_by(EmailTeamMember.team_id)
            ).scalars().all()

            logger.info(f"   team_members from DB: {[tm.team_id for tm in team_members]}")

            if team_members:
                team_id = team_members[0].team_id
                logger.info(f"   ✅ Using team_id from DB: {team_id}")
                return team_id
        except Exception as e:
            logger.warning(f"   ❌ Failed to query user teams: {e}")

    logger.info(f"   ⚠️  Falling back to 'default'")
    return "default"
```

Restart the server and check logs during OAuth flow.

### Solution A: Ensure User Has Team Membership

If the user has no team membership in the database:

```bash
# Add user to team
sqlite3 mcp.db << 'EOF'
INSERT INTO email_team_members (team_id, user_email, is_active, created_at)
VALUES ('team1', 'user2@example.com', 1, datetime('now'))
ON CONFLICT (team_id, user_email) DO UPDATE SET is_active = 1;
EOF
```

### Solution B: Pass User Context During OAuth Callback

The OAuth callback needs access to the authenticated user's context. Currently, `request.state.user` might be `None`.

Check `mcpgateway/routers/oauth_router.py` line 647:

```python
user_context = _build_user_context(getattr(request.state, "user", None))
```

If `request.state.user` is `None`, the `user_context` is empty, so `_get_team_id()` falls back to database query or "default".

**Workaround:** Extract user email from OAuth state and look up their teams:

```python
# In oauth_callback, after resolving gateway_id from state:
from mcpgateway.services.email_auth_service import EmailAuthService

# Extract app_user_email from state
app_user_email_from_state = await oauth_manager.get_app_user_email_from_state(state)

if app_user_email_from_state:
    auth_service = EmailAuthService(db)
    user = await auth_service.get_user_by_email(app_user_email_from_state)
    if user:
        user_context = {
            "email": user.email,
            "teams": user.team_ids,
            "is_admin": user.is_admin
        }
    else:
        user_context = {}
else:
    user_context = {}

oauth_manager = OAuthManager(token_storage=TokenStorageService(db, user_context))
```

### Solution C: Fix Path Generation Bug

If the path `d855a360a0f24f56ac2b5a1ab54cbb70/` is actually the `gateway_id` being hashed instead of `team_id`, there's a bug in `VaultTokenBackend._construct_vault_path()`.

Check `mcpgateway/services/token_backends/vault_backend.py` line 107:

```python
def _construct_vault_path(self, team_id: str, mcp_url: str, app_user_email: str) -> str:
    server_id = self._hash_server_id(mcp_url)  # ← Should hash mcp_url
    email_encoded = quote(app_user_email, safe="")
    return f"{self.mount}/data/{self.prefix}/{team_id}/{server_id}/{email_encoded}"
    #                                           ↑        ↑
    #                                        Should NOT be hashed
```

Verify `team_id` is passed correctly to `store_tokens()`.

## Immediate Workaround

Until the bug is fixed, you can manually retrieve the token:

```bash
# Find the actual path
ACTUAL_PATH=$(vault kv list -mount=secret contextforge/oauth/ | tail -n +3 | head -1 | tr -d '/')

# Find the email
ACTUAL_EMAIL=$(vault kv list -mount=secret "contextforge/oauth/$ACTUAL_PATH/" | tail -n +3 | head -1 | tr -d '/')

# Get the token
vault kv get -mount=secret "contextforge/oauth/$ACTUAL_PATH/$ACTUAL_EMAIL"
```

Then use the token directly in your MCP client configuration.

## Testing the Fix

After applying a fix:

1. **Delete old tokens:**
   ```bash
   vault kv metadata delete -mount=secret "contextforge/oauth"
   ```

2. **Re-run OAuth flow:**
   - Visit `http://localhost:8000/oauth/authorize/{gateway_id}`
   - Complete authorization

3. **Verify structure:**
   ```bash
   python3 scripts/check-vault-structure.py
   ```

4. **Expected output:**
   ```
   📂 secret/data/contextforge/oauth/
     📁 team1/               # ✅ team_id (not hashed!)
       📁 ca602dd4/           # ✅ server_id (hashed mcp_url)
         📄 user2%40example.com
   ```

5. **Test token retrieval:**
   ```bash
   # Should succeed now
   curl -X POST "http://localhost:8000/oauth/fetch-tools/{gateway_id}" \
     -H "Authorization: Bearer $BEARER_TOKEN" \
     -H "X-CSRF-Token: $CSRF_TOKEN"
   ```

## References

- [OAuth + Vault Testing Guide](docs/testing-oauth-vault.md)
- [Token Storage Service](mcpgateway/services/token_storage_service.py)
- [Vault Backend](mcpgateway/services/token_backends/vault_backend.py)
- [OAuth Router](mcpgateway/routers/oauth_router.py)
