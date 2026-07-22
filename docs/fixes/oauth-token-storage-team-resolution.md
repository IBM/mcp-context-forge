# OAuth Token Storage Team Resolution Fix

## Issue

When completing an OAuth authorization flow, tokens were being stored under `team_id="default"` even when the user belonged to specific teams. This caused tokens to be unfindable when attempting to fetch tools from the MCP server after OAuth completion.

### Root Cause

In `mcpgateway/routers/oauth_router.py` (line 646-648), the OAuth callback handler attempted to build a user context from `request.state.user`:

```python
user_context = _build_user_context(getattr(request.state, "user", None)) if request and hasattr(request, "state") else {}
oauth_manager = OAuthManager(token_storage=TokenStorageService(db, user_context))
```

However, OAuth callbacks are unauthenticated (they come from the external OAuth provider), so `request.state.user` is `None`, resulting in an empty `user_context = {}`.

When `TokenStorageService._get_team_id()` was called with an empty context, it would fall back to returning `"default"`:

```python
def _get_team_id(self, app_user_email: str) -> str:
    if self.user_context:
        teams = self.user_context.get("teams", [])
        if isinstance(teams, list) and teams:
            return teams[0]
    return "default"  # ← Always returned when context is empty
```

Later, when `fetch_tools_after_oauth` was called (which has authentication), it would build a proper user context with the user's actual teams, creating a mismatch:

- **Tokens stored at**: `team_id="default"`
- **Tokens retrieved from**: `team_id="engineering"` (user's actual team)

This affected both database and Vault backends.

## Solution

Modified `TokenStorageService._get_team_id()` in `mcpgateway/services/token_storage_service.py` to query the database for the user's team memberships when `user_context` is empty or has no teams:

```python
def _get_team_id(self, app_user_email: str) -> str:
    """
    Extract team_id from authenticated user context or query database.

    Precedence: JWT 'teams' claim → session 'teams' → database query → fallback 'default'.
    """
    # Try user_context first
    if self.user_context:
        teams = self.user_context.get("teams", [])
        if isinstance(teams, list) and teams:
            return teams[0]

    # Fallback: query database for user's teams
    if app_user_email and self.db:
        try:
            from mcpgateway.db import EmailTeamMember
            from sqlalchemy import select

            team_members = self.db.execute(
                select(EmailTeamMember).where(
                    EmailTeamMember.user_email == app_user_email,
                    EmailTeamMember.is_active.is_(True),
                )
            ).scalars().all()

            if team_members:
                return team_members[0].team_id
        except Exception as e:
            logger.warning(f"Failed to query user teams for {app_user_email}: {e}, falling back to 'default'")

    return "default"
```

### Precedence

1. **JWT 'teams' claim** (from user_context) - used when available
2. **Database query** (EmailTeamMember) - used when context is empty (OAuth callback scenario)
3. **Fallback to "default"** - used only when user has no team memberships

## Impact

- ✅ Tokens are now stored under the correct team_id during OAuth callbacks
- ✅ Works with both database and Vault backends
- ✅ Maintains backward compatibility with existing code paths
- ✅ No changes needed to OAuth callback handler or other services
- ✅ All existing tests pass
- ✅ Three new test cases added to verify the fix

## Testing

Added three new test cases in `tests/unit/mcpgateway/services/test_token_storage_service.py`:

1. `test_get_team_id_with_user_context` - Verifies user_context takes precedence when available
2. `test_get_team_id_queries_database_when_context_empty` - Verifies database query during OAuth callback
3. `test_get_team_id_falls_back_to_default_when_no_teams` - Verifies fallback to "default" when user has no teams

Updated two existing tests to account for the database query behavior:
- `test_get_team_id_empty_teams`
- `test_get_team_id_no_user_context`

## Environment Variables

This fix works correctly with:
- `OAUTH_TOKEN_BACKEND=database` (default)
- `OAUTH_TOKEN_BACKEND=vault`

## Related Files

- `mcpgateway/services/token_storage_service.py` (modified)
- `tests/unit/mcpgateway/services/test_token_storage_service.py` (tests added/updated)
- `mcpgateway/routers/oauth_router.py` (unchanged - no changes needed)
- `mcpgateway/services/gateway_service.py` (unchanged - fetch_tools_after_oauth)

## Performance Considerations

The database query only happens when:
1. `user_context` is empty or has no teams (OAuth callback scenario)
2. `app_user_email` is provided

For authenticated API requests with proper user_context, no additional query is made.
