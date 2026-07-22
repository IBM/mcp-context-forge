# Database OAuth Implementation Analysis

## Current Implementation Overview

The existing `TokenStorageService` in `mcpgateway/services/token_storage_service.py` provides OAuth token management using direct SQLAlchemy ORM operations against the `oauth_tokens` table.

## Database Schema

**Table: `oauth_tokens`** (`mcpgateway/db.py`, line 5262)

```python
class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    
    id: Mapped[str]                          # Primary key (UUID hex)
    gateway_id: Mapped[str]                  # FK → gateways.id (CASCADE)
    user_id: Mapped[str]                     # OAuth provider user ID
    app_user_email: Mapped[str]              # FK → email_users.email (CASCADE)
    access_token: Mapped[str]                # Encrypted via EncryptedText()
    refresh_token: Mapped[Optional[str]]     # Encrypted via EncryptedText()
    token_type: Mapped[str]                  # Default "Bearer"
    expires_at: Mapped[Optional[datetime]]   # Nullable (some providers don't specify)
    scopes: Mapped[Optional[List[str]]]      # JSON array
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    
    # IMPORTANT: Unique constraint (gateway_id, app_user_email)
    __table_args__ = (UniqueConstraint("gateway_id", "app_user_email", name="uq_oauth_gateway_user"),)
```

**Key observations:**
- **NO `team_id` column** in the current schema (deferred per design doc scope)
- Composite unique key: `(gateway_id, app_user_email)`
- Tokens are encrypted at storage time using `EncryptedText()` column type
- `expires_at` can be NULL (RFC 6749 §5.1 makes it RECOMMENDED, not REQUIRED)

## Current TokenStorageService Method Signatures

### 1. `store_tokens()` — Line 119

```python
async def store_tokens(
    self,
    gateway_id: str,
    user_id: str,           # OAuth provider user ID
    app_user_email: str,
    access_token: str,
    refresh_token: Optional[str],
    expires_in: Optional[int],  # Seconds, or None
    scopes: List[str],
) -> OAuthToken
```

**Behavior:**
- Encrypts `access_token` and `refresh_token` via `EncryptionService`
- Converts `expires_in` → `expires_at` (datetime)
- **UPSERT logic**: Queries by `(gateway_id, app_user_email)` — updates if exists, creates if not
- Returns the `OAuthToken` ORM object
- Commits immediately (not deferred to caller)

**Call sites:**
- `mcpgateway/routers/oauth_router.py` (OAuth callback handler)
- `mcpgateway/services/oauth_manager.py` (via OAuthManager)

### 2. `get_user_token()` — Line 194

```python
async def get_user_token(
    self,
    gateway_id: str,
    app_user_email: str,
    threshold_seconds: int = 300,  # Refresh if expires within 5 minutes
) -> Optional[str]
```

**Behavior:**
- Queries by `(gateway_id, app_user_email)`
- Checks expiry with `_is_token_expired()` helper
- **Auto-refresh**: If near expiry and `refresh_token` exists, calls `_refresh_access_token()`
- Decrypts and returns plain-text access token
- Returns `None` if not found or refresh fails

**Call sites:**
- `mcpgateway/services/tool_service.py` (before tool execution)
- `mcpgateway/services/gateway_service.py` (health checks)
- `mcpgateway/services/resource_service.py` (resource fetches)
- `mcpgateway/routers/oauth_router.py` (admin endpoints)

### 3. `get_token_info()` — Line 472

```python
async def get_token_info(
    self,
    gateway_id: str,
    app_user_email: str,
) -> Optional[Dict[str, Any]]
```

**Behavior:**
- Queries by `(gateway_id, app_user_email)`
- Returns metadata dict (no sensitive tokens):
  ```python
  {
      "user_id": str,
      "app_user_email": str,
      "token_type": str,
      "expires_at": str | None,  # ISO-8601
      "scopes": list[str],
      "created_at": str,
      "updated_at": str,
      "is_expired": bool,
  }
  ```
- Used by admin status API

**Call sites:**
- `mcpgateway/routers/oauth_router.py` (admin token status endpoint)
- `mcpgateway/admin.py` (admin UI)

### 4. `revoke_user_tokens()` — Line 524

```python
async def revoke_user_tokens(
    self,
    gateway_id: str,
    app_user_email: str,
) -> bool
```

**Behavior:**
- Deletes token record matching `(gateway_id, app_user_email)`
- Returns `True` if deleted, `False` if not found
- Commits immediately

**Call sites:**
- `mcpgateway/routers/oauth_router.py` (user logout, admin revoke)
- `mcpgateway/admin.py` (admin UI revoke action)

### 5. `cleanup_expired_tokens()` — Line 566

```python
async def cleanup_expired_tokens(
    self,
    max_age_days: int = 30,
) -> int
```

**Behavior:**
- Deletes tokens matching:
  1. `expires_at < (now - max_age_days)` — expired tokens
  2. `expires_at IS NULL AND updated_at < (now - max_age_days)` — stale tokens with no provider expiry
- Returns count of deleted rows
- Called by scheduled cleanup job

**Call sites:**
- Scheduled background task (not HTTP endpoint)

## Key Design Patterns in Current Implementation

### 1. Encryption Handling

```python
# Storage (line 139-145)
if self.encryption:
    encrypted_access = await self.encryption.encrypt_secret_async(access_token)
    if refresh_token:
        encrypted_refresh = await self.encryption.encrypt_secret_async(refresh_token)

# Retrieval (line 232-234)
if self.encryption:
    return await self.encryption.decrypt_secret_async(token_record.access_token)
return token_record.access_token
```

- Encryption is **optional** (falls back to plain text if service unavailable)
- Uses `EncryptionService` from `mcpgateway/services/encryption_service.py`
- Encryption happens in service layer, not at ORM level (though `EncryptedText()` column type also encrypts)

### 2. Token Refresh Logic (line 243-427)

The `_refresh_access_token()` helper:
1. Validates gateway exists and has OAuth config
2. **Security check**: Refuses refresh if gateway is private and owner doesn't match token owner (PR #4341)
3. Decrypts `refresh_token` and `client_secret`
4. Adds RFC 8707 `resource` parameter (JWT audience)
5. Calls `OAuthManager.refresh_token()` to exchange with IdP
6. **Handles missing `expires_in`**: Preserves prior TTL if provider omits it
7. Encrypts and stores new tokens
8. Commits immediately

### 3. Expiry Checking (line 429-470)

```python
def _is_token_expired(self, token_record: OAuthToken, threshold_seconds: int = 300) -> bool:
    if not token_record.expires_at:
        # NULL expiry = non-expired (provider didn't specify lifetime)
        return False
    expires_at = token_record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) + timedelta(seconds=threshold_seconds) >= expires_at
```

- Tokens with `expires_at IS NULL` are **never expired** (by design)
- Threshold allows proactive refresh (default 5 minutes before expiry)

## Differences Between Current Implementation and Proposed Interface

| Aspect | Current `TokenStorageService` | Proposed `AbstractTokenBackend` |
|--------|-------------------------------|----------------------------------|
| **team_id parameter** | ❌ Not present | ✅ Required for Vault path |
| **Return type** | `store_tokens()` returns `OAuthToken` ORM object | Returns `TokenRecord` dataclass |
| **Encryption** | Handled in service + ORM column type | Backend-specific (Vault encrypts natively) |
| **Commit strategy** | Immediate `db.commit()` after each operation | Backend-specific (DB: commit, Vault: atomic write) |
| **Lookup key** | `(gateway_id, app_user_email)` | `(gateway_id, team_id, app_user_email)` |
| **Token refresh** | Built into `get_user_token()` | Same (interface requirement) |
| **NULL expiry handling** | Supported (tokens without `expires_in`) | Must be preserved in Vault backend |

## Migration Strategy: Database → DatabaseTokenBackend

When extracting the current implementation into `DatabaseTokenBackend`, the key changes are:

### 1. Accept `team_id` but Don't Use It

```python
class DatabaseTokenBackend(AbstractTokenBackend):
    async def store_tokens(
        self,
        gateway_id: str,
        team_id: str,  # ← NEW: accept but ignore (no DB column yet)
        user_id: str,
        app_user_email: str,
        ...
    ) -> TokenRecord:
        # Current implementation (lines 119-192) with:
        # - No changes to SQL queries (still use gateway_id + app_user_email)
        # - Return TokenRecord instead of OAuthToken
        # - Include team_id="default" in returned TokenRecord (no source in DB)
        ...
```

### 2. Return `TokenRecord` Instead of ORM Object

```python
@dataclass
class TokenRecord:
    gateway_id: str
    mcp_url: str        # ← Resolve from gateways.url via _resolve_mcp_url()
    team_id: str        # ← Default to "default" (no DB column)
    user_id: str
    app_user_email: str
    access_token: str   # Plain-text (after decryption)
    refresh_token: str | None
    token_type: str
    expires_at: datetime | None
    scopes: list[str]
    created_at: datetime
    updated_at: datetime
```

The `DatabaseTokenBackend` would:
- Query `OAuthToken` ORM object as today
- Decrypt tokens (encryption service)
- Map ORM fields → `TokenRecord` dataclass
- Populate `mcp_url` by resolving `gateway_id` → `gateways.url`
- Populate `team_id` with fallback value (no DB source)

### 3. Preserve All Existing Behavior

The extraction is **behavior-preserving**:
- Same SQL queries (no schema changes)
- Same encryption logic
- Same refresh logic (including RFC 8707, TTL preservation)
- Same NULL expiry handling
- Same security checks (PR #4341 private gateway check)

## Call Site Impact Analysis

All call sites currently pass:
```python
TokenStorageService(db)
```

With the new design, they would pass user context:
```python
TokenStorageService(db, user_context)
```

The façade extracts `team_id` internally, so call sites don't need to change their method calls:

### Current
```python
service = TokenStorageService(db)
token = await service.get_user_token(gateway_id, app_user_email)
```

### After Refactor
```python
service = TokenStorageService(db, user_context)  # ← Only change
token = await service.get_user_token(gateway_id, app_user_email)  # ← Same
```

The `user_context` would typically come from:
- JWT claims (parsed by auth middleware)
- Session data (from `request.state.user`)
- Request context (from dependency injection)

## Summary

| Component | Current State | Required Changes |
|-----------|---------------|------------------|
| **`oauth_tokens` table** | No `team_id` column | **OUT OF SCOPE** (deferred) |
| **`TokenStorageService`** | Direct DB operations, no `team_id` | Becomes façade, extracts `team_id`, delegates to backend |
| **Method signatures** | 5 methods without `team_id` | Interface adds `team_id` to 4 methods (not cleanup) |
| **Return types** | Returns `OAuthToken` ORM | Returns `TokenRecord` dataclass |
| **Encryption** | Service-layer + ORM column | Backend-specific (DB: same, Vault: native) |
| **Call sites** | Pass `db` only | Pass `db` + `user_context` |

The refactor is **additive and non-breaking** for the database path:
- No database schema changes required
- No changes to existing SQL queries
- No changes to encryption/decryption logic
- No changes to token refresh flow
- Call sites need minimal adjustment (add `user_context` parameter)
