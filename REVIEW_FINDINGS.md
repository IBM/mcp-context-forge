# Design Document Review - Mismatches Found and Fixed

## Summary
Found and fixed **5 critical mismatches** where the interface, method signatures, and Vault paths were inconsistent.

---

## Issues Found and Fixed

### ✅ Issue 1: Wrong callback method signature (Line 637)
**Location:** Section 8 - New Client-Callable Vault Authorization Endpoints

**Before:**
```
4. Calls VaultTokenBackend.store_tokens(mcp_url, …) — writes to Vault
```

**After:**
```
3. Extracts team_id from user context (JWT/session)
4. Calls TokenStorageService.store_tokens(gateway_id, …) → VaultTokenBackend resolves gateway_id → mcp_url and writes to Vault
```

**Why:** Backend receives `gateway_id` not `mcp_url` directly. The façade passes `gateway_id` and `team_id`, backend resolves internally.

---

### ✅ Issue 2: Wrong flow diagram method call (Line 1038)
**Location:** Section 15 - End-to-End Flow, Step 4

**Before:**
```html
<code>VaultTokenBackend.store_tokens("https://mcp.github.acme.com", …)</code>
```

**After:**
```html
<code>TokenStorageService.store_tokens(gateway_id, …)</code> → <code>VaultTokenBackend</code>
```

**Why:** Call goes through the façade, not directly to backend. Parameters are `gateway_id` not `mcp_url` string.

---

### ✅ Issue 3: Wrong Vault path (missing team_id segment) (Line 1038)
**Location:** Section 15 - End-to-End Flow, Step 4

**Before:**
```
PUT secret/data/contextforge/oauth/https%3A%2F%2Fmcp.github.acme.com/alice%40acme.com
```

**After:**
```
PUT secret/data/contextforge/oauth/engineering/647ad7b3/alice%40acme.com
```

**Why:** Vault path requires **three segments**: `{team_id}/{server_id}/{email}`. The old path was missing `team_id` and using URL-encoded `mcp_url` instead of hashed `server_id`.

**Correct format:**
- `team_id` = `"engineering"` (from user context)
- `server_id` = `"647ad7b3"` (hash of `mcp_url`)
- `email` = `"alice%40acme.com"` (URL-encoded)

---

### ✅ Issue 4: Wrong method parameters in flow (Line 1040)
**Location:** Section 15 - End-to-End Flow, Step 6

**Before:**
```html
<code>VaultTokenBackend.get_user_token("https://mcp.github.acme.com", "alice@acme.com")</code>
```

**After:**
```html
<code>TokenStorageService.get_user_token(gateway_id, "alice@acme.com")</code> → <code>VaultTokenBackend</code>
```

**Why:** Same as Issue 2 - calls go through façade, parameters are `(gateway_id, app_user_email)` not `(mcp_url, email)`.

---

### ✅ Issue 5: Wrong parameter order in retry example (Line 1152)
**Location:** Section 18 - Retry Logic (VaultTokenBackend)

**Before:**
```python
async def get_user_token(self, gateway_id: str, app_user_email: str, team_id: str, ...):
```

**After:**
```python
async def get_user_token(self, gateway_id: str, team_id: str, app_user_email: str, ...):
```

**Why:** Interface signature is `(gateway_id, team_id, app_user_email, ...)`. Parameter order must match the abstract interface definition in Section 5.

---

## Verification Checklist

### ✅ Section 5: AbstractTokenBackend Interface
- [x] `TokenRecord` has `team_id` field
- [x] `store_tokens()` has `team_id` parameter (correct position)
- [x] `get_user_token()` has `team_id` parameter (correct position)
- [x] `get_token_info()` has `team_id` parameter (correct position)
- [x] `revoke_user_tokens()` has `team_id` parameter (correct position)
- [x] `cleanup_expired_tokens()` has NO `team_id` (correct)

### ✅ Section 6: TokenStorageService Façade
- [x] Constructor accepts `user_context` parameter
- [x] Has `_get_team_id()` helper method
- [x] All delegate methods extract and pass `team_id`
- [x] VaultTokenBackend example has correct parameter order

### ✅ Section 7: Vault Secret Schema
- [x] Path pattern shows `{team_id}/{server_id}/{email}` ✓
- [x] Example paths include all three segments ✓
- [x] Secret payload includes `team_id` field ✓

### ✅ Section 7.5: DatabaseTokenBackend (Deferred)
- [x] Correctly shows `team_id` parameter accepted but ignored
- [x] Interface implementation matches Section 5
- [x] Clearly marked as next phase

### ✅ Section 8: Vault Authorization Endpoints
- [x] Callback flow mentions `team_id` extraction ✓
- [x] Calls go through `TokenStorageService` not direct backend ✓

### ✅ Section 14: Backend Comparison
- [x] Path key comparison mentions `(team_id, server_id, email)` ✓

### ✅ Section 15: End-to-End Flow
- [x] Step 4: Correct method call and Vault path ✓
- [x] Step 6: Correct method call and Vault path ✓
- [x] Both paths include `{team_id}/{server_id}/{email}` ✓

### ✅ Section 18: Retry Logic
- [x] Parameter order matches interface ✓

---

## Consistency Verification

### Interface → Façade → Backend → Vault Path

```
┌─────────────────────────────────────────────────────────────────┐
│ AbstractTokenBackend Interface (Section 5)                      │
│ ✓ store_tokens(gateway_id, team_id, user_id, app_user_email...) │
│ ✓ get_user_token(gateway_id, team_id, app_user_email, ...)     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ TokenStorageService Façade (Section 6)                          │
│ ✓ Extracts team_id via _get_team_id(app_user_email)            │
│ ✓ Passes (gateway_id, team_id, ...) to backend                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ VaultTokenBackend Implementation (Section 7)                    │
│ ✓ Receives (gateway_id, team_id, ...)                          │
│ ✓ Resolves gateway_id → gateways.url → server_id (hash)        │
│ ✓ Constructs path: {team_id}/{server_id}/{email}               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Vault KV v2 Path (Section 7, 15)                               │
│ ✓ secret/data/contextforge/oauth/engineering/647ad7b3/alice... │
│ ✓ All three segments present                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Changes Summary

**Total fixes:** 5 critical mismatches
**Sections updated:** 8, 15, 18
**Lines changed:** ~10 lines

**Result:** The design document is now **internally consistent** across all sections.

---

## Final Status

✅ **All mismatches resolved**
✅ **Interface matches implementation examples**
✅ **Vault paths include all three required segments**
✅ **Method signatures consistent throughout**
✅ **Ready for implementation**

The design document now correctly specifies:
1. Interface with `team_id` parameter
2. Façade that extracts `team_id` from user context
3. VaultTokenBackend that uses `(gateway_id, team_id, app_user_email)`
4. Vault paths with `{team_id}/{server_id}/{email}` format
