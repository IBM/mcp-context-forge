# Design Document Updates: Phase 1 DatabaseTokenBackend Clarification

## What Changed

The design document has been updated to clarify the **phased approach** for DatabaseTokenBackend implementation.

### Original Confusion

The original document said:
- ❌ "DatabaseTokenBackend (if needed) will be a separate future effort"
- ❌ "Database extraction deferred to next phase"
- ❌ Implied DatabaseTokenBackend would NOT be implemented in Phase 1

This created a problem: **You cannot implement the façade pattern without having both backends**.

### Clarified Approach

The updated document now clearly states:

**Phase 1** includes minimal DatabaseTokenBackend extraction:
- ✅ Extract existing code → `DatabaseTokenBackend` class (copy-paste)
- ✅ Accept `team_id` parameter (for interface consistency)
- ✅ **Completely ignore `team_id`** in all SQL queries
- ❌ NO database schema changes (no `team_id` column)
- ❌ NO SQL query changes (continue using `(gateway_id, app_user_email)`)
- ❌ NO behavior changes (UPSERT, encryption, refresh logic all unchanged)

**Phase 2** will add `team_id` support to database:
- ✅ Add `team_id` column to `oauth_tokens` table (Alembic migration)
- ✅ Update SQL queries to use `team_id` in WHERE clauses
- ✅ Change unique constraint to `(team_id, gateway_id, app_user_email)`

## Key Updates Made to Design Document

### Section 2: Scope

**Before:**
> Database Changes Deferred: Any modifications to the existing database backend (including team_id field addition, refactoring into DatabaseTokenBackend, or interface alignment) are out of scope for this phase.

**After:**
> Database Extraction Approach: Phase 1 includes minimal DatabaseTokenBackend extraction (copy-paste existing code) to enable the façade pattern, but with zero behavior changes:
> - ✅ Extract existing code → DatabaseTokenBackend class
> - ✅ Accept team_id parameter (for interface consistency) but completely ignore it
> - ❌ NO database schema changes (no team_id column added)
> - ❌ NO SQL query changes (continue using (gateway_id, app_user_email) as unique key)
> - ❌ NO behavior changes (UPSERT, encryption, refresh logic all unchanged)

### Section 7.5: DatabaseTokenBackend

**Before:**
> ⚠️ IMPLEMENTATION DEFERRED TO NEXT PHASE
> The DatabaseTokenBackend extraction is documented here for architectural completeness but is out of scope for this phase.

**After:**
> Two-Phase Database Backend Implementation
> 
> **Phase 1:** Minimal extraction (copy-paste) to enable façade pattern — accepts team_id but ignores it (no DB schema changes).
> 
> **Phase 2:** Add team_id column to oauth_tokens table and update SQL queries to use it.

Includes detailed implementation showing:
- How `team_id` parameter is accepted but ignored
- How SQL queries remain unchanged
- How this is purely code reorganization

### Section 17: Delivery Phases

**Before:**
> Phase 1: VaultTokenBackend + /vault/* endpoints only. Database code untouched.

**After:**
> Phase 1: VaultTokenBackend + /vault/* endpoints + minimal DatabaseTokenBackend extraction
> 
> **Vault:** Full flow (store, retrieve, refresh, revoke). Uses team_id in Vault paths.
> 
> **Database:** Copy existing code → DatabaseTokenBackend class. Accept team_id parameter but ignore it completely. ❌ NO database schema changes. ❌ NO SQL query changes. ❌ NO behavior changes. This is purely code reorganization to enable the façade pattern.

## Why This Matters

**The façade pattern requires both backends to exist:**

```python
class TokenStorageService:
    def __init__(self, db: Session, user_context: dict | None = None):
        settings = get_settings()
        
        if settings.oauth_token_backend == "vault":
            self._backend = VaultTokenBackend(db, settings)  # ← Must exist
        elif settings.oauth_token_backend == "database":
            self._backend = DatabaseTokenBackend(db, settings)  # ← Must exist
        else:
            raise ValueError("Unknown OAUTH_TOKEN_BACKEND")
    
    async def store_tokens(self, gateway_id, user_id, app_user_email, ...):
        team_id = self._get_team_id(app_user_email)
        return await self._backend.store_tokens(
            gateway_id, team_id, user_id, app_user_email, ...)
```

Without `DatabaseTokenBackend`, the façade cannot be implemented, which means `VaultTokenBackend` cannot be used.

## Implementation Checklist

**Phase 1 (Current):**

- [ ] 1. Create `token_backends/` package
  - [ ] `token_backends/__init__.py`
  - [ ] `token_backends/base.py` (TokenRecord dataclass)
  - [ ] `token_backends/db_backend.py` (minimal extraction)
  - [ ] `token_backends/vault_backend.py` (full implementation)

- [ ] 2. Update `TokenStorageService`
  - [ ] Add `user_context` parameter
  - [ ] Add backend selector logic
  - [ ] Add `_get_team_id()` helper
  - [ ] Delegate all 5 methods to backend

- [ ] 3. Update call sites (minimal changes)
  - [ ] `tool_service.py`: `TokenStorageService(db, user_context)`
  - [ ] `gateway_service.py`: `TokenStorageService(db, user_context)`
  - [ ] `resource_service.py`: `TokenStorageService(db, user_context)`
  - [ ] `oauth_router.py`: `TokenStorageService(db, user_context)`
  - [ ] `admin.py`: `TokenStorageService(db, user_context)`

- [ ] 4. Add new `/vault/*` endpoints
  - [ ] `vault_router.py`: `GET /vault/authorize/{server_id}`
  - [ ] `vault_router.py`: `GET /vault/callback`

- [ ] 5. Update configuration
  - [ ] `config.py`: Add 7 Vault environment variables
  - [ ] `main.py`: Register `vault_router` when backend=vault

**Phase 2 (Future):**

- [ ] 1. Alembic migration
  - [ ] Add `team_id` column to `oauth_tokens` table (nullable, default "default")
  - [ ] Change unique constraint to `(team_id, gateway_id, app_user_email)`
  - [ ] Backfill existing rows with `team_id="default"`

- [ ] 2. Update `DatabaseTokenBackend`
  - [ ] Update `store_tokens()`: use `team_id` in WHERE clause
  - [ ] Update `get_user_token()`: use `team_id` in WHERE clause
  - [ ] Update `get_token_info()`: use `team_id` in WHERE clause
  - [ ] Update `revoke_user_tokens()`: use `team_id` in WHERE clause

- [ ] 3. Update `VaultTokenBackend` authentication
  - [ ] Replace static `VAULT_TOKEN` with AppRole
  - [ ] Add Kubernetes ServiceAccount auth support

## Summary

**Before:** Document implied DatabaseTokenBackend would not be implemented in Phase 1.

**After:** Document clearly states DatabaseTokenBackend will be implemented in Phase 1 as a minimal extraction (copy-paste, zero behavior changes) to enable the façade pattern.

**Key principle:** Phase 1 = code reorganization only. Phase 2 = database schema changes + team_id support.
