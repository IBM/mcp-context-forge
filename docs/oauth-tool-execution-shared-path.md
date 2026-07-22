# OAuth Tool Execution with Shared Path

## Problem

After fixing OAuth authorization to use shared Vault path for teamless sessions, tool execution still failed:

```
❌ Internal error
Admin bypass token (token_teams=None) cannot retrieve team-scoped OAuth tokens for gateway 'github-server'.
OAuth delegation requires explicit team scope in JWT 'teams' claim.
```

### Root Cause

`ToolService` had explicit blocking logic that prevented `token_teams=None` (admin bypass tokens) from retrieving OAuth tokens, even though we now support shared path storage.

**Location**: `mcpgateway/services/tool_service.py` lines 5295-5310

## Solution

Modified `ToolService` OAuth token retrieval to allow `token_teams=None` to use shared path fallback.

### Changes

**File**: `mcpgateway/services/tool_service.py` (lines 5295-5313)

**Before**:
```python
if token_teams is None:
    # Admin bypass: cannot retrieve team-scoped OAuth tokens
    logger.warning(...)
    raise ToolInvocationError(
        f"OAuth-protected gateway '{gateway_name}' requires explicit team scope..."
    )

# Non-None token_teams: use as-is
effective_teams = token_teams if token_teams else []
```

**After**:
```python
if token_teams is None:
    # Admin bypass: use shared OAuth token path (fallback for sessions without teams)
    logger.warning(
        f"Admin bypass token (token_teams=None) retrieving OAuth tokens from shared path..."
    )
    effective_teams = []  # Empty teams triggers shared path fallback
else:
    # Non-None token_teams: use as-is
    effective_teams = token_teams
```

### Behavior

| Token Type | `token_teams` | `effective_teams` | Vault Path | Behavior |
|------------|---------------|-------------------|------------|----------|
| **API token** | `["team-123"]` | `["team-123"]` | `vault/oauth/team-123/...` | ✅ Team-isolated |
| **Admin UI session** | `None` | `[]` | `vault/oauth/shared/...` | ✅ Shared fallback |
| **Empty teams token** | `[]` | `[]` | `vault/oauth/shared/...` | ✅ Shared fallback |

## Flow

### API OAuth Tool Execution ✅

1. User has JWT with `teams: ["team-123"]`
2. OAuth authorization → tokens stored in `vault/oauth/team-123/{server_id}/user@example.com`
3. Tool execution → `token_teams=["team-123"]` → `effective_teams=["team-123"]`
4. TokenStorageService retrieves from `vault/oauth/team-123/...` ✅

### Admin UI OAuth Tool Execution ✅

1. User has session JWT without `teams` claim
2. OAuth authorization → tokens stored in `vault/oauth/shared/{server_id}/user@example.com`
3. Tool execution → `token_teams=None` → `effective_teams=[]`
4. TokenStorageService retrieves from `vault/oauth/shared/...` ✅

## Testing

### From Admin UI

1. Login to Admin UI (session JWT, no teams)
2. Navigate to gateway → Click "Authorize"
3. Complete OAuth flow → tokens in shared path ✅
4. **Call a tool** → should succeed now ✅

Expected logs:
```json
{
  "message": "Admin bypass token (token_teams=None) retrieving OAuth tokens from shared path for gateway 'github-server'..."
}
```

### From API with Teams

```bash
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username user@example.com \
  --teams team-123 \
  --exp 10080)

curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:4444/rpc \
  -d '{"method": "tools/call", "params": {"name": "my-tool"}}'
```

Should use team-isolated path ✅

## Security Implications

### Before Fix
- ❌ Admin UI OAuth broken (authorization worked, tool execution failed)
- ✅ API OAuth worked (team-isolated)

### After Fix  
- ✅ Admin UI OAuth works (authorization + tool execution via shared path)
- ✅ API OAuth works (team-isolated)
- ⚠️ Admin UI tokens less isolated (shared path, not team-specific)

### Shared Path Risks

**Same as OAuth authorization** (documented in `oauth-teamless-session-fallback.md`):

1. Multiple users' tokens coexist in `vault/oauth/shared/`
2. Email-based sub-paths provide isolation
3. Vault ACLs must restrict `shared/*` access
4. Less secure than team-isolated paths

### Mitigation

**Long-term**: Add `teams` claim to Admin UI session JWT during login
- Requires: Admin login flow to include user's teams in JWT
- Benefit: Admin UI gets same team isolation as API

## Vault Structure

```
secret/contextforge/oauth/
├── team-123/              # API OAuth (team-isolated)
│   └── 647ad7b3/
│       └── user@example.com
│           ├── access_token
│           ├── refresh_token
│           └── expires_at
└── shared/                # Admin UI OAuth (fallback)
    └── 647ad7b3/
        ├── user@example.com
        │   ├── access_token
        │   └── expires_at
        └── admin@example.com
            └── access_token
```

## Related Changes

1. **OAuth Authorization**: `oauth-teamless-session-fallback.md` - Allow teamless OAuth authorization
2. **This Fix**: Allow teamless tool execution
3. **Token Storage**: `token_storage_service.py` - Return `None` instead of raising error
4. **Vault Backend**: `vault_backend.py` - Handle `None` team_id → use "shared" path

## Code Review Alignment

This change aligns with security review requirement #2:

> "Remove DB team fallback/inference from ToolService"

**Before**: Would have queried DB for teams when `token_teams=None`  
**After**: Uses empty list `[]` → triggers shared path fallback (no DB query)

✅ No database team queries
✅ Teams only from JWT token
✅ Graceful degradation for teamless sessions
