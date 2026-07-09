# Phase 1: DatabaseTokenBackend Minimal Extraction

## Executive Summary

**Problem:** Cannot implement VaultTokenBackend without a façade pattern, but the façade requires both backends to exist.

**Solution:** Phase 1 includes **minimal DatabaseTokenBackend extraction** (copy-paste existing code) to enable the façade, with **zero behavior changes**.

## What Changes in Phase 1

### ✅ Changes Required

1. **Create `token_backends/` package**
   - `token_backends/__init__.py` - re-exports TokenRecord, DatabaseTokenBackend, VaultTokenBackend
   - `token_backends/base.py` - TokenRecord dataclass (no SQLAlchemy dependencies)
   - `token_backends/db_backend.py` - DatabaseTokenBackend (copy-paste of existing code)
   - `token_backends/vault_backend.py` - VaultTokenBackend (new implementation)

2. **Update `TokenStorageService` → Façade**
   - Add `user_context` parameter to `__init__()`
   - Add backend selector logic (reads `OAUTH_TOKEN_BACKEND` env var)
   - Add `_get_team_id()` helper to extract team_id from user_context
   - Delegate all 5 methods to `self._backend`

3. **Update call sites (minimal)**
   - Change: `TokenStorageService(db)`
   - To: `TokenStorageService(db, user_context)`
   - Files: `tool_service.py`, `gateway_service.py`, `resource_service.py`, `oauth_router.py`, `admin.py`

### ❌ NO Changes to Database Logic

1. **NO database schema changes**
   - ❌ NO `team_id` column added to `oauth_tokens` table
   - ❌ NO Alembic migration
   - ❌ NO unique constraint changes

2. **NO SQL query changes**
   - ❌ Continue using `(gateway_id, app_user_email)` as unique key
   - ❌ `team_id` is accepted as parameter but **completely ignored** in all SQL queries
   - ❌ NO WHERE clause changes
   - ❌ NO UPSERT logic changes

3. **NO behavior changes**
   - ❌ Same encryption via `EncryptionService`
   - ❌ Same auto-refresh logic
   - ❌ Same NULL expiry handling
   - ❌ Same private gateway ownership checks

## DatabaseTokenBackend Implementation (Phase 1)

```python
class DatabaseTokenBackend:
    """
    Phase 1: Minimal extraction — copy-paste of existing TokenStorageService code.
    
    Accepts team_id parameter (for interface consistency) but IGNORES it completely.
    NO database schema changes. NO SQL query changes. NO behavior changes.
    
    Phase 2 will add team_id column and update SQL queries.
    """
    
    def __init__(self, db: Session, settings):
        self.db = db
        self.settings = settings
        self.encryption = get_encryption_service(settings.auth_encryption_secret)
    
    async def store_tokens(
        self,
        gateway_id: str,
        team_id: str,           # ← Accepted but NOT used in SQL queries
        user_id: str,
        app_user_email: str,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
    ) -> TokenRecord:
        # EXACT same logic as current TokenStorageService
        # team_id parameter is IGNORED — not used in any SQL query
        
        encrypted_access = await self.encryption.encrypt_secret_async(access_token)
        encrypted_refresh = await self.encryption.encrypt_secret_async(refresh_token) if refresh_token else None
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None
        
        # Query by (gateway_id, app_user_email) — same as today, team_id NOT used
        token_record = self.db.execute(
            select(OAuthToken).where(
                OAuthToken.gateway_id == gateway_id,
                OAuthToken.app_user_email == app_user_email
            )
        ).scalar_one_or_none()
        
        if token_record:
            token_record.user_id = user_id
            token_record.access_token = encrypted_access
            token_record.refresh_token = encrypted_refresh
            token_record.expires_at = expires_at
            token_record.scopes = scopes
            token_record.updated_at = datetime.now(timezone.utc)
        else:
            token_record = OAuthToken(
                gateway_id=gateway_id,
                user_id=user_id,
                app_user_email=app_user_email,
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                expires_at=expires_at,
                scopes=scopes,
            )
            self.db.add(token_record)
        
        self.db.commit()
        
        # Convert ORM → TokenRecord dataclass
        return TokenRecord(
            gateway_id=token_record.gateway_id,
            mcp_url=self._resolve_mcp_url(gateway_id),
            team_id="default",  # ← Fallback (no DB source in Phase 1)
            user_id=token_record.user_id,
            app_user_email=token_record.app_user_email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_record.token_type,
            expires_at=token_record.expires_at,
            scopes=token_record.scopes,
            created_at=token_record.created_at,
            updated_at=token_record.updated_at,
        )
    
    async def get_user_token(
        self,
        gateway_id: str,
        team_id: str,           # ← Accepted but NOT used in SQL queries
        app_user_email: str,
        threshold_seconds: int = 300,
    ) -> str | None:
        # Query by (gateway_id, app_user_email) — same as today, team_id NOT used
        token_record = self.db.execute(
            select(OAuthToken).where(
                OAuthToken.gateway_id == gateway_id,
                OAuthToken.app_user_email == app_user_email
            )
        ).scalar_one_or_none()
        
        if not token_record:
            return None
        
        # Same auto-refresh logic as today
        if self._is_token_expired(token_record, threshold_seconds):
            if token_record.refresh_token:
                new_token = await self._refresh_access_token(token_record)
                if new_token:
                    return new_token
            return None
        
        # Same decryption logic as today
        if self.encryption:
            return await self.encryption.decrypt_secret_async(token_record.access_token)
        return token_record.access_token
    
    # ... other methods (get_token_info, revoke_user_tokens, cleanup_expired_tokens)
    # All follow same pattern: accept team_id but ignore it, use existing SQL queries
```

## TokenStorageService Façade (Phase 1)

```python
class TokenStorageService:
    """
    Phase 1: Thin façade that selects backend and extracts team_id from user_context.
    
    Delegates all operations to the appropriate backend.
    """
    
    def __init__(self, db: Session, user_context: dict | None = None):
        self.db = db
        self.user_context = user_context
        settings = get_settings()
        
        if settings.oauth_token_backend == "vault":
            self._backend = VaultTokenBackend(db, settings)
        elif settings.oauth_token_backend == "database":
            self._backend = DatabaseTokenBackend(db, settings)
        else:
            raise ValueError(
                f"Unknown OAUTH_TOKEN_BACKEND: {settings.oauth_token_backend}. "
                f"Expected 'database' or 'vault'."
            )
    
    def _get_team_id(self, app_user_email: str) -> str:
        """Extract team_id from authenticated user context."""
        if self.user_context:
            teams = get_user_teams(self.user_context)
            return teams[0] if teams else "default"
        return "default"
    
    async def store_tokens(self, gateway_id, user_id, app_user_email, ...):
        team_id = self._get_team_id(app_user_email)
        return await self._backend.store_tokens(
            gateway_id, team_id, user_id, app_user_email, ...)
    
    async def get_user_token(self, gateway_id, app_user_email, threshold_seconds=300):
        team_id = self._get_team_id(app_user_email)
        return await self._backend.get_user_token(
            gateway_id, team_id, app_user_email, threshold_seconds)
    
    # ... other methods follow same pattern
```

## Phase 2: Add team_id Support (Future)

Phase 2 will modify the database backend to actually use team_id:

1. **Alembic migration**
   - Add `team_id` column to `oauth_tokens` table (nullable, default "default")
   - Change unique constraint from `(gateway_id, app_user_email)` to `(team_id, gateway_id, app_user_email)`

2. **Update DatabaseTokenBackend SQL queries**
   - Change WHERE clauses to include `team_id`
   - Update UPSERT logic to use `team_id`
   - Backfill existing rows with `team_id="default"`

3. **No changes to façade or VaultTokenBackend**
   - Façade already passes `team_id` correctly
   - VaultTokenBackend already uses `team_id` in Vault paths
   - Only DatabaseTokenBackend implementation changes

## Why This Approach?

1. **Enables façade pattern** — Cannot implement VaultTokenBackend without both backends
2. **Minimizes risk** — DatabaseTokenBackend is copy-paste, zero behavior changes
3. **Defers database changes** — Schema migration can be designed after Vault is proven
4. **Clean separation** — Phase 1 (Vault + minimal extraction) vs Phase 2 (database team_id support)

## Summary

- ✅ Phase 1: Extract DatabaseTokenBackend (copy-paste), accept team_id but ignore it
- ✅ Phase 1: Implement full VaultTokenBackend with team_id support
- ✅ Phase 1: Create TokenStorageService façade
- ❌ Phase 1: NO database schema changes
- ❌ Phase 1: NO SQL query changes
- ❌ Phase 1: NO database behavior changes
- ✅ Phase 2: Add team_id column + update SQL queries
