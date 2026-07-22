# DatabaseTokenBackend Section (for Design Document)

**Insert Location:** After Section 7 (Vault Secret Schema), before Section 8 (New Client-Callable Vault Authorization Endpoints)

**Section Number:** 7.5 or renumber subsequent sections

---

## 7.5 DatabaseTokenBackend — Next Phase (Deferred)

<div class="box bwarn">
  <strong>⚠️ IMPLEMENTATION DEFERRED TO NEXT PHASE</strong><br/>
  The <code>DatabaseTokenBackend</code> extraction is documented here for architectural completeness but is <strong>out of scope for this phase</strong>. The current <code>TokenStorageService</code> implementation (direct DB operations) remains unchanged when <code>OAUTH_TOKEN_BACKEND=database</code> (default). Only <code>VaultTokenBackend</code> will be implemented in this phase.
</div>

The `DatabaseTokenBackend` will encapsulate the existing database OAuth token storage logic, providing a clean implementation of the `AbstractTokenBackend` interface for the database path.

### Implementation Strategy

When implemented in a future phase, `DatabaseTokenBackend` will:

1. **Extract existing logic** from current `TokenStorageService` (lines 119-620 in `mcpgateway/services/token_storage_service.py`)
2. **Accept `team_id` parameter** (for interface compliance) but initially **ignore it**
3. **Preserve all existing behavior** including:
   - UPSERT logic on `(gateway_id, app_user_email)` unique key
   - Encryption via `EncryptionService`
   - Auto-refresh logic with RFC 8707 resource parameter
   - NULL expiry handling (tokens without `expires_in`)
   - Private gateway ownership security check (PR #4341)

### Interface Implementation (Future)

<pre>
<span class="k">class</span> DatabaseTokenBackend(AbstractTokenBackend):
    <span class="k">def</span> __init__(self, db: Session, settings):
        self.db = db
        self.settings = settings
        self.encryption = get_encryption_service(settings.auth_encryption_secret)

    <span class="k">async def</span> store_tokens(
        self,
        gateway_id: str,
        team_id: str,           <span class="c"># ← Accepted but NOT stored (no DB column yet)</span>
        user_id: str,
        app_user_email: str,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
    ) → TokenRecord:
        <span class="c"># Encrypt tokens</span>
        encrypted_access = <span class="k">await</span> self.encryption.encrypt_secret_async(access_token)
        encrypted_refresh = <span class="k">await</span> self.encryption.encrypt_secret_async(refresh_token) <span class="k">if</span> refresh_token <span class="k">else</span> None
        
        <span class="c"># Calculate expiry</span>
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in) <span class="k">if</span> expires_in <span class="k">else</span> None
        
        <span class="c"># UPSERT: query by (gateway_id, app_user_email)</span>
        token_record = self.db.execute(
            select(OAuthToken).where(
                OAuthToken.gateway_id == gateway_id,
                OAuthToken.app_user_email == app_user_email
            )
        ).scalar_one_or_none()
        
        <span class="k">if</span> token_record:
            <span class="c"># Update existing</span>
            token_record.user_id = user_id
            token_record.access_token = encrypted_access
            token_record.refresh_token = encrypted_refresh
            token_record.expires_at = expires_at
            token_record.scopes = scopes
            token_record.updated_at = datetime.now(timezone.utc)
        <span class="k">else</span>:
            <span class="c"># Create new</span>
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
        
        <span class="c"># Convert ORM → TokenRecord dataclass</span>
        <span class="k">return</span> TokenRecord(
            gateway_id=token_record.gateway_id,
            mcp_url=self._resolve_mcp_url(gateway_id),  <span class="c"># Resolve for dataclass</span>
            team_id=<span class="s">"default"</span>,  <span class="c"># ← Fallback (no DB source)</span>
            user_id=token_record.user_id,
            app_user_email=token_record.app_user_email,
            access_token=access_token,  <span class="c"># Plain-text in return value</span>
            refresh_token=refresh_token,
            token_type=token_record.token_type,
            expires_at=token_record.expires_at,
            scopes=token_record.scopes,
            created_at=token_record.created_at,
            updated_at=token_record.updated_at,
        )

    <span class="k">async def</span> get_user_token(
        self,
        gateway_id: str,
        team_id: str,           <span class="c"># ← Accepted but ignored</span>
        app_user_email: str,
        threshold_seconds: int = 300,
    ) → str | None:
        <span class="c"># Query by (gateway_id, app_user_email) — same as today</span>
        token_record = self.db.execute(
            select(OAuthToken).where(
                OAuthToken.gateway_id == gateway_id,
                OAuthToken.app_user_email == app_user_email
            )
        ).scalar_one_or_none()
        
        <span class="k">if not</span> token_record:
            <span class="k">return</span> None
        
        <span class="c"># Check expiry + auto-refresh (same logic as today)</span>
        <span class="k">if</span> self._is_token_expired(token_record, threshold_seconds):
            <span class="k">if</span> token_record.refresh_token:
                new_token = <span class="k">await</span> self._refresh_access_token(token_record)
                <span class="k">if</span> new_token:
                    <span class="k">return</span> new_token
            <span class="k">return</span> None
        
        <span class="c"># Decrypt and return</span>
        <span class="k">if</span> self.encryption:
            <span class="k">return await</span> self.encryption.decrypt_secret_async(token_record.access_token)
        <span class="k">return</span> token_record.access_token

    <span class="c"># get_token_info(), revoke_user_tokens(), cleanup_expired_tokens() follow same pattern</span>
</pre>

### Key Differences from Current Implementation

| Aspect | Current `TokenStorageService` | Future `DatabaseTokenBackend` |
|--------|-------------------------------|------------------------------|
| **team_id handling** | Not present | Accepted but ignored (no DB column) |
| **Return type** | Returns `OAuthToken` ORM object | Returns `TokenRecord` dataclass |
| **mcp_url resolution** | Not needed | Calls `_resolve_mcp_url()` for dataclass field |
| **Encryption** | Same (via `EncryptionService`) | Same |
| **SQL queries** | Same | Same |
| **Refresh logic** | Same | Same |

### Database Schema (No Changes Required)

The `oauth_tokens` table schema remains unchanged:

```sql
CREATE TABLE oauth_tokens (
    id VARCHAR(36) PRIMARY KEY,
    gateway_id VARCHAR(36) NOT NULL REFERENCES gateways(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    app_user_email VARCHAR(255) NOT NULL REFERENCES email_users(email) ON DELETE CASCADE,
    access_token TEXT NOT NULL,  -- Encrypted
    refresh_token TEXT,          -- Encrypted
    token_type VARCHAR(50) DEFAULT 'Bearer',
    expires_at TIMESTAMP WITH TIME ZONE,
    scopes JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_oauth_gateway_user UNIQUE (gateway_id, app_user_email)
);
```

**Note:** No `team_id` column. Adding it would be a separate migration (future scope).

### Migration to DatabaseTokenBackend (Future)

When this phase is implemented:

1. **Create `mcpgateway/services/token_backends/db_backend.py`**
   - Copy lines 119-620 from current `token_storage_service.py`
   - Add `team_id` parameter to all methods (ignored)
   - Change return types from ORM → `TokenRecord` dataclass

2. **Update `TokenStorageService` façade**
   - Add backend selection logic:
     ```python
     if settings.oauth_token_backend == "vault":
         self._backend = VaultTokenBackend(db, settings)
     elif settings.oauth_token_backend == "database":
         self._backend = DatabaseTokenBackend(db, settings)
     ```

3. **No call site changes required**
   - `TokenStorageService(db, user_context)` works for both backends
   - Façade extracts `team_id` and passes to backend
   - Database backend ignores it; Vault backend uses it

### Why Defer This?

Per the design document scope (Section 2):

> **Database Changes Deferred:** Any modifications to the existing database backend (including `team_id` field addition, refactoring into `DatabaseTokenBackend`, or interface alignment) are **out of scope** for this phase. Current priority: deliver Vault storage capability without touching existing database functionality.

**Benefits of deferring:**
- Minimizes risk (no changes to existing OAuth flow)
- Allows Vault implementation to proceed independently
- Database backend can be extracted later without blocking Vault deployment
- Schema migration for `team_id` column can be planned separately

**Current phase focus:** Implement `VaultTokenBackend` only. The existing `TokenStorageService` continues to work as-is when `OAUTH_TOKEN_BACKEND=database`.

---

## Relationship to Section 6 (TokenStorageService Façade)

The façade (Section 6) will need adjustment when `DatabaseTokenBackend` is implemented:

**Current Phase (Vault only):**
```python
class TokenStorageService:
    def __init__(self, db: Session, user_context: dict | None = None):
        self.db = db
        self.user_context = user_context
        settings = get_settings()
        
        if settings.oauth_token_backend == "vault":
            self._backend = VaultTokenBackend(db, settings)
        else:
            # Keep existing direct DB logic (no backend abstraction yet)
            self._use_legacy_db_path = True
```

**Next Phase (Database backend added):**
```python
class TokenStorageService:
    def __init__(self, db: Session, user_context: dict | None = None):
        self.db = db
        self.user_context = user_context
        settings = get_settings()
        
        if settings.oauth_token_backend == "vault":
            self._backend = VaultTokenBackend(db, settings)
        elif settings.oauth_token_backend == "database":
            self._backend = DatabaseTokenBackend(db, settings)  # ← NEW
        else:
            raise ValueError(f"Unknown backend: {settings.oauth_token_backend}")
```

---

**End of DatabaseTokenBackend Section**
