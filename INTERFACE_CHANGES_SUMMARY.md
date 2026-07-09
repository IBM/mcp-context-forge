# Summary: Interface Changes for Vault Integration

## Overview

After analyzing the Vault secret schema requirements and the existing database OAuth implementation, I've identified and documented the required changes to the `AbstractTokenBackend` interface and `TokenStorageService` façade.

## Key Finding

**The `team_id` parameter is MISSING from the interface but REQUIRED by Vault.**

The Vault secret path format requires three components:
```
<mount>/data/<prefix>/<team_id>/<server_id>/<email>
```

Without `team_id` in the interface, `VaultTokenBackend` cannot construct the correct path.

## Documents Created

### 1. `INTERFACE_UPDATES_FOR_VAULT.md`
**Detailed technical specification for required changes:**
- Updated `TokenRecord` dataclass with `team_id` field
- Updated `AbstractTokenBackend` interface with `team_id` parameter on all 4 methods
- Updated `TokenStorageService` façade with `_get_team_id()` helper
- Team ID extraction strategy (JWT claims → session → default)
- Implementation notes for both backends

### 2. `DATABASE_OAUTH_ANALYSIS.md`
**Comprehensive analysis of current implementation:**
- Current `TokenStorageService` method signatures (5 methods)
- Database schema (`oauth_tokens` table structure)
- Existing behavior patterns (encryption, refresh, expiry handling)
- Key design patterns (UPSERT logic, RFC 8707, NULL expiry)
- Call site impact analysis
- Migration strategy for `DatabaseTokenBackend`

### 3. `DATABASE_BACKEND_DESIGN_SECTION.md`
**Future DatabaseTokenBackend design (next phase):**
- Interface implementation strategy
- Accept `team_id` but ignore it (no DB column yet)
- Preserve all existing behavior
- No database schema changes required initially
- Rationale for deferring to next phase

### 4. `contextforge-pluggable-token-storage-architect-design-document.html` (UPDATED)
**Added Section 7.5: DatabaseTokenBackend — Next Phase (Deferred)**
- 159 lines of HTML documentation
- Implementation strategy, code sketches, database schema
- Clear warning box marking it as deferred scope
- Benefits of deferring explained

## Required Interface Changes

### TokenRecord Dataclass

```python
@dataclass
class TokenRecord:
    gateway_id: str
    mcp_url: str
    team_id: str              # ← NEW: required for Vault path
    user_id: str
    app_user_email: str
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: datetime | None
    scopes: list[str]
    created_at: datetime
    updated_at: datetime
```

### AbstractTokenBackend Interface

All 4 data methods need `team_id` parameter:

```python
class AbstractTokenBackend(ABC):
    @abstractmethod
    async def store_tokens(
        self,
        gateway_id: str,
        team_id: str,           # ← NEW
        user_id: str,
        app_user_email: str,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
    ) -> TokenRecord: ...

    @abstractmethod
    async def get_user_token(
        self,
        gateway_id: str,
        team_id: str,           # ← NEW
        app_user_email: str,
        threshold_seconds: int = 300,
    ) -> str | None: ...

    @abstractmethod
    async def get_token_info(
        self,
        gateway_id: str,
        team_id: str,           # ← NEW
        app_user_email: str,
    ) -> dict | None: ...

    @abstractmethod
    async def revoke_user_tokens(
        self,
        gateway_id: str,
        team_id: str,           # ← NEW
        app_user_email: str,
    ) -> bool: ...

    @abstractmethod
    async def cleanup_expired_tokens(
        self,
        max_age_days: int = 30,
    ) -> int: ...
    # ← No team_id needed (operates on all tokens)
```

### TokenStorageService Façade

```python
class TokenStorageService:
    def __init__(self, db: Session, user_context: dict | None = None):
        self.db = db
        self.user_context = user_context
        # ... backend selection logic

    def _get_team_id(self, app_user_email: str) -> str:
        """Extract team_id from JWT claims or session data."""
        if self.user_context:
            teams = get_user_teams(self.user_context)
            return teams[0] if teams else "default"
        return "default"

    async def store_tokens(self, gateway_id, user_id, app_user_email, ...):
        team_id = self._get_team_id(app_user_email)  # ← Extract internally
        return await self._backend.store_tokens(
            gateway_id=gateway_id,
            team_id=team_id,                          # ← Pass to backend
            user_id=user_id,
            app_user_email=app_user_email,
            ...
        )
```

## Backend Implementation Strategy

### VaultTokenBackend (This Phase)

```python
class VaultTokenBackend(AbstractTokenBackend):
    async def store_tokens(self, gateway_id, team_id, user_id, ...):
        mcp_url = self._resolve_mcp_url(gateway_id)
        server_id = self._hash_server_id(mcp_url)
        # Construct path with all three segments
        path = f"{mount}/data/{prefix}/{team_id}/{server_id}/{quote(email)}"
        # Write to Vault KV v2
        ...
```

### DatabaseTokenBackend (Next Phase - Deferred)

```python
class DatabaseTokenBackend(AbstractTokenBackend):
    async def store_tokens(self, gateway_id, team_id, user_id, ...):
        # Accept team_id but ignore it (no DB column yet)
        # Use gateway_id directly as FK (current behavior)
        token_record = self.db.execute(
            select(OAuthToken).where(
                OAuthToken.gateway_id == gateway_id,
                OAuthToken.app_user_email == app_user_email
            )
        ).scalar_one_or_none()
        # ... rest of current implementation
```

## Call Site Changes

**Minimal impact** - only the service instantiation changes:

### Before
```python
service = TokenStorageService(db)
```

### After
```python
service = TokenStorageService(db, user_context)  # ← Add user context
```

Method calls remain the same:
```python
token = await service.get_user_token(gateway_id, app_user_email)
```

## Implementation Phases

### Phase 1 (Current - Vault Only)
- ✅ Add `team_id` to `TokenRecord` dataclass
- ✅ Add `team_id` parameter to `AbstractTokenBackend` interface (all 4 methods)
- ✅ Update `TokenStorageService` façade with `_get_team_id()` helper
- ✅ Implement `VaultTokenBackend` (uses `team_id` in path)
- ❌ **DatabaseTokenBackend NOT implemented** - current code stays as-is

### Phase 2 (Future - Database Backend Extraction)
- Extract current `TokenStorageService` logic → `DatabaseTokenBackend`
- Accept `team_id` parameter but ignore it initially
- Add backend selection to façade: `database` → `DatabaseTokenBackend`
- No database schema changes required
- All existing behavior preserved

### Phase 3 (Future - Database Schema Migration)
- Add `team_id` column to `oauth_tokens` table (Alembic migration)
- Update `DatabaseTokenBackend` to store and use `team_id`
- Migrate existing tokens (backfill `team_id` from user sessions)
- Update unique constraint to include `team_id`

## Summary Table

| Component | Current State | Phase 1 (Vault) | Phase 2 (DB Backend) | Phase 3 (DB Schema) |
|-----------|---------------|-----------------|----------------------|---------------------|
| `TokenRecord` | No `team_id` | ✅ Add `team_id` | Same | Same |
| `AbstractTokenBackend` | No `team_id` | ✅ Add `team_id` | Same | Same |
| `TokenStorageService` | No façade | ✅ Becomes façade | ✅ Add DB backend | Same |
| `VaultTokenBackend` | Doesn't exist | ✅ Implement | Same | Same |
| `DatabaseTokenBackend` | Doesn't exist | ❌ Deferred | ✅ Implement | ✅ Use `team_id` |
| `oauth_tokens` table | No `team_id` | ❌ No change | ❌ No change | ✅ Add column |

## Next Steps

1. **Review this analysis** and the design document updates
2. **Approve the interface changes** (team_id addition)
3. **Implement Phase 1** (VaultTokenBackend only)
4. **Defer Phase 2** (DatabaseTokenBackend extraction)
5. **Defer Phase 3** (database schema migration)

## Files to Review

1. `INTERFACE_UPDATES_FOR_VAULT.md` - Technical specification
2. `DATABASE_OAUTH_ANALYSIS.md` - Current implementation analysis
3. `DATABASE_BACKEND_DESIGN_SECTION.md` - Future design (plain text)
4. `contextforge-pluggable-token-storage-architect-design-document.html` - Updated design doc (Section 7.5 added)

All documents clearly mark DatabaseTokenBackend as **next phase / deferred** per the design scope.
