# Design Document Updates Summary

## Changes Made to `contextforge-pluggable-token-storage-architect-design-document.html`

### Statistics
- **233 lines modified** (206 additions, 27 deletions)
- Sections updated: 5, 6, 7.5 (new)

---

## Section 5: AbstractTokenBackend Interface

### Updated TokenRecord Dataclass
**Added `team_id` field:**
```python
@dataclass
class TokenRecord:
    gateway_id: str
    mcp_url: str
    team_id: str              # ← NEW: Team identifier from user context
    user_id: str
    app_user_email: str
    # ... rest unchanged
```

### Updated AbstractTokenBackend Interface
**Added `team_id` parameter to 4 methods:**

1. **store_tokens()** — Added `team_id: str` (after `gateway_id`, before `user_id`)
2. **get_user_token()** — Added `team_id: str` (after `gateway_id`, before `app_user_email`)
3. **get_token_info()** — Added `team_id: str` (after `gateway_id`, before `app_user_email`)
4. **revoke_user_tokens()** — Added `team_id: str` (after `gateway_id`, before `app_user_email`)
5. **cleanup_expired_tokens()** — No change (operates on all tokens)

### Updated Class Docstring
Changed from:
> "All methods receive gateway_id. Each backend resolves it appropriately..."

To:
> "All methods receive gateway_id and team_id. Each backend uses them appropriately:
>   DatabaseTokenBackend → uses gateway_id directly as FK; team_id ignored (no DB column yet)
>   VaultTokenBackend → uses team_id in path; resolves gateway_id → mcp_url → server_id"

### Updated Design Decision Box
Changed from:
> "Key Design Decision — gateway_id as the interface discriminator"

To:
> "Key Design Decision — gateway_id + team_id as interface parameters"

Added explanation that `team_id` is extracted from authenticated user context (JWT/session).

---

## Section 6: TokenStorageService Façade

### Updated Constructor
**Added `user_context` parameter:**
```python
def __init__(self, db: Session, user_context: dict | None = None):
    self.db = db
    self.user_context = user_context  # ← NEW: JWT claims or session data
    # ... backend selection
```

### Added Helper Method
**New `_get_team_id()` method:**
```python
def _get_team_id(self, app_user_email: str) → str:
    """Extract team_id from authenticated user context.
    Precedence: JWT claims → session data → fallback 'default'."""
    if self.user_context:
        teams = get_user_teams(self.user_context)
        return teams[0] if teams else "default"
    return "default"
```

### Updated All Delegate Methods
**Each method now extracts and passes `team_id`:**

```python
# BEFORE
async def store_tokens(self, gateway_id, user_id, app_user_email, ...):
    return await self._backend.store_tokens(
        gateway_id, user_id, app_user_email, ...)

# AFTER
async def store_tokens(self, gateway_id, user_id, app_user_email, ...):
    team_id = self._get_team_id(app_user_email)  # ← Extract
    return await self._backend.store_tokens(
        gateway_id, team_id, user_id, app_user_email, ...)  # ← Pass
```

Same pattern for:
- `get_user_token()`
- `get_token_info()`
- `revoke_user_tokens()`
- `cleanup_expired_tokens()` (no team_id needed)

### Updated VaultTokenBackend Examples
**Fixed parameter order to match interface:**
```python
# BEFORE (incorrect order)
async def store_tokens(self, gateway_id, user_id, app_user_email, team_id, ...):

# AFTER (correct order)
async def store_tokens(self, gateway_id, team_id, user_id, app_user_email, ...):
```

### Updated "Why this is correct" Box
Changed from:
> "Call sites unchanged..."

To:
> "Call sites minimally changed — existing call sites pass gateway_id exactly as today; only the TokenStorageService instantiation adds user_context parameter."

Added:
> "Vault path uses all three keys — team_id (from user context), server_id (from mcp_url hash), and email."

---

## Section 7.5: DatabaseTokenBackend (NEW)

**Added 159 lines of documentation** for the next-phase DatabaseTokenBackend implementation.

Key points:
- Clearly marked as **"IMPLEMENTATION DEFERRED TO NEXT PHASE"**
- Warning box at the top
- Implementation strategy (accept team_id but ignore it)
- Interface implementation sketch
- Database schema (no changes required)
- Rationale for deferring

---

## Consistency Achieved

### Before Updates (INCONSISTENT)
- Interface: No `team_id` parameter ❌
- Façade: No `team_id` extraction ❌
- Vault path: Requires `{team_id}/{server_id}/{email}` ✓
- **Problem:** VaultTokenBackend cannot construct the path!

### After Updates (CONSISTENT)
- Interface: `team_id` parameter on all 4 data methods ✓
- Façade: Extracts `team_id` from user context ✓
- Vault path: Uses `{team_id}/{server_id}/{email}` ✓
- **Result:** VaultTokenBackend can construct the correct path!

---

## Call Site Impact

### Minimal Changes Required

**Before:**
```python
service = TokenStorageService(db)
token = await service.get_user_token(gateway_id, app_user_email)
```

**After:**
```python
service = TokenStorageService(db, user_context)  # ← Only change
token = await service.get_user_token(gateway_id, app_user_email)  # ← Same
```

The façade handles `team_id` extraction internally, so method signatures at call sites remain unchanged.

---

## Implementation Order

1. ✅ **Interface updated** (Section 5)
2. ✅ **Façade updated** (Section 6)
3. ✅ **DatabaseTokenBackend documented** (Section 7.5) — next phase
4. ⏳ **VaultTokenBackend implementation** — this phase
5. ⏳ **DatabaseTokenBackend extraction** — next phase
6. ⏳ **Database schema migration** (add team_id column) — future phase

---

## Files Modified

1. `contextforge-pluggable-token-storage-architect-design-document.html` — **233 lines changed**
   - Section 5: AbstractTokenBackend Interface (updated)
   - Section 6: TokenStorageService Façade (updated)
   - Section 7.5: DatabaseTokenBackend (new)

## Supporting Documents (Previously Created)

1. `INTERFACE_UPDATES_FOR_VAULT.md` — Technical specification
2. `DATABASE_OAUTH_ANALYSIS.md` — Current implementation analysis
3. `DATABASE_BACKEND_DESIGN_SECTION.md` — Plain text version of Section 7.5
4. `INTERFACE_CHANGES_SUMMARY.md` — Executive summary

**Status:** Design document is now internally consistent and ready for VaultTokenBackend implementation.
