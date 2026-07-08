# Architect Review Summary — Pluggable Token Storage Design

## Document Status: ✅ Ready for Architect Review

**Document:** `contextforge-pluggable-token-storage-architect-design-document.html`  


---

## Executive Summary

This design document proposes **HashiCorp Vault as a new OAuth token storage option** for ContextForge, enabling enterprise customers to store tokens in Vault instead of the application database. The design includes:

1. **Vault Implementation ONLY** — `VaultTokenBackend` as a parallel implementation; existing database code remains **completely untouched**
2. **Composite Lookup Key** — Vault paths structured as `{team_id}/{server_id}/{email}` for efficient multi-key lookups
3. **Nested Token Payload** — OAuth credentials grouped under a `token` object for cleaner structure
4. **Optional Caching Layer** — TTL-based in-memory cache to mitigate Vault API latency
5. **Tested Local Setup** — Complete PostgreSQL-backed Vault setup documented in `docs/vault-local-dev-postgresql.md`

**🎯 Implementation Scope:** This phase focuses exclusively on delivering Vault storage capability. Database refactoring (e.g., `DatabaseTokenBackend`, `AbstractTokenBackend` interface, `team_id` field addition) is **deferred to future phases** if/when business need arises.

---

## Review Findings

### ✅ Consistency Checks Passed

1. **Vault Path Structure** — All references updated to `{team_id}/{server_id}/{email}` format
   - Section 6: `_resolve_mcp_url()` code samples
   - Section 7: Path pattern, payload structure, DB-to-Vault mapping
   - Section 13: Configuration reference table
   - Section 14: Backend comparison table
   - Section 18: Security properties table
   - Section 20: Retry logic code sample

2. **Payload Structure** — Consistent nested `token` object throughout
   - `token.access_token`, `token.refresh_token`, `token.scopes` (array)
   - Lookup keys (`email`, `team_id`, `mcp_url`) in payload + path

3. **Section Numbering** — All 22 sections numbered sequentially
   - New Section 12: Token Caching Strategy
   - Subsequent sections renumbered accordingly

4. **Local Development Reference** — Updated to point to tested PostgreSQL guide
   - Section 9: Links to `docs/vault-local-dev-postgresql.md`
   - Metadata: "Local Dev (Vault + PostgreSQL)"

---

## Key Design Decisions

### 1. Composite Lookup Key

**Path:** `secret/contextforge/oauth/{team_id}/{server_id}/{email}`

**Rationale:**
- Enables lookup by any combination of `team_id`, `mcp_url` (→ `server_id`), and `email`
- Natural team isolation via path structure
- Future-proof for team-based Vault ACL policies

**Trade-offs:**
- ✅ Flexible team assignment (can change without moving secrets)
- ✅ Supports multi-team users if needed
- ⚠️ Requires team context extraction from authenticated user

### 2. Nested Token Object

**Structure:**
```json
{
  "email": "alice@acme.com",
  "team_id": "engineering",
  "mcp_url": "https://mcp.github.acme.com",
  "token": {
    "access_token": "...",
    "refresh_token": "...",
    "scopes": ["repo", "read:user"]
  },
  "user_id": "...",
  "token_type": "Bearer",
  "expires_at": "2026-07-07T18:00:00Z",
  "created_at": "...",
  "updated_at": "..."
}
```

**Rationale:**
- Groups related OAuth fields together
- Easier token rotation (update entire `token` object)
- Consistent with OAuth 2.0 token response structure
- Cleaner security practices (can redact `token` object in logs)

### 3. Optional Token Caching (Section 12)

**Configuration:**
- `VAULT_TOKEN_CACHE_ENABLED=true` (default: `false`)
- `VAULT_TOKEN_CACHE_TTL=300` (5 minutes, default)
- `VAULT_TOKEN_CACHE_MAX_SIZE=10000` (default)

**Cache Strategy:**
- **Read:** Check cache → hit? return · miss? fetch from Vault + cache
- **Write:** Write to Vault → invalidate cache entry
- **Revoke:** Delete from Vault → flush all matching cache entries

**Performance Impact:**
- Read latency: 10-20ms (Vault) → 0.5ms (cache hit)
- Recommended for deployments with >100 concurrent users or >500 tool calls/sec

**Trade-offs:**
- ✅ 10-50x read latency reduction
- ✅ Reduces Vault API load
- ⚠️ Stale reads within TTL window if token rotated externally
- ⚠️ Increased memory footprint (~1KB per cached token)

---

## Implementation Readiness

### ✅ Completed (Vault Focus)

1. **Design Document** — Comprehensive 22-section document with all Vault architectural decisions
2. **Local Dev Setup** — Complete tested guide (`docs/vault-local-dev-postgresql.md`)
   - PostgreSQL database setup with proper permissions
   - Vault server configuration and initialization
   - Storage table creation (manual pre-creation to avoid init loops)
   - Policy and token generation
   - Comprehensive verification steps (CRUD operations + PostgreSQL storage checks)
3. **Path Structure** — Composite key design (`team_id/server_id/email`)
4. **Payload Schema** — Nested `token` object with self-documenting lookup keys
5. **Caching Strategy** — Optional TTL-based cache specification
6. **Vault Endpoints** — `/vault/authorize/{server_id}` and `/vault/callback` specification
7. **Backend Selection** — `OAUTH_TOKEN_BACKEND=vault` configuration

### 🔄 Pending Architect Review

1. **team_id Extraction** — How to extract `team_id` from authenticated user context (JWT claims vs. session table)
2. **server_id Derivation** — Hash vs. gateway UUID for `server_id` path segment
3. **Cache Implementation** — Confirm caching strategy (TTL, eviction policy, thread safety)
4. **Database Code** — Confirm existing database OAuth flow remains untouched (no refactoring in Phase 1)
5. **Future Phases** — Confirm database refactoring is deferred until business need exists

---

## Open Questions for Architect

### 1. Team Context Extraction

**Question:** How should `VaultTokenBackend` extract `team_id` from the authenticated user?

**Options:**
- A) Add `team_id` to JWT claims (requires token reissuance)
- B) Query `users` or `sessions` table for `team_id` (adds DB dependency to Vault backend)
- C) Pass `team_id` explicitly from caller context (requires updating all call sites)

**Recommendation:** Option C — explicit parameter. Keeps backend pure, caller controls context.

### 2. server_id Derivation Strategy

**Question:** How should `mcp_url` be converted to `server_id` for the Vault path?

**Options:**
- A) Hash `mcp_url` (e.g., SHA256 first 12 chars) — stable, no DB lookup
- B) Use gateway UUID directly — requires DB lookup from `mcp_url`
- C) Sanitized URL (e.g., `https://mcp.github.com` → `mcp_github_com`) — readable but long

**Recommendation:** Option A (hash) with fallback to B (UUID lookup) if gateway record exists. Best of both worlds.

### 3. Cache Consistency Model

**Question:** Is eventual consistency (within TTL window) acceptable for cached tokens?

**Concerns:**
- External token rotation (e.g., admin revokes token in Vault UI)
- Multi-instance deployments (cache is per-instance, not shared)

**Recommendation:** Document as known limitation. Add monitoring for cache invalidation lag.

### 4. Migration Strategy

**Question:** How should existing deployments transition from database to Vault storage?

**Options:**
- A) One-time migration script (read DB → write Vault → drop table)
- B) Dual-write period (write both, read Vault, fallback to DB)
- C) Side-by-side (new servers use Vault, existing servers keep DB)

**Recommendation:** Option B (dual-write) for zero-downtime migration. Requires feature flag.

---

## Security Review Checklist

- ✅ **Secrets never in logs** — Payload structure allows `token` object redaction
- ✅ **TLS enforced** — `VAULT_TLS_VERIFY=true` required in production
- ✅ **Scoped tokens** — ContextForge uses policy-scoped token (not root)
- ✅ **Path isolation** — Team-based paths enable future ACL policies
- ✅ **Audit trail** — Vault audit log captures every read/write
- ✅ **No double-encryption** — Plain-text in Vault (Vault encrypts at rest)
- ✅ **Token rotation** — Vault token TTL monitoring + rotation runbook (Section 21)

---

## Performance Considerations

### Throughput Limits

| Backend | Bottleneck | Max Ops/Sec |
|---------|------------|-------------|
| DatabaseTokenBackend | CF connection pool (200) | ~66,000 |
| VaultTokenBackend (1 node) | Vault API + PG pool | ~1,000 |
| VaultTokenBackend (3 nodes) | Cluster aggregate | ~3,000 |
| **VaultTokenBackend + Cache** | In-memory hits | **~100,000** |

**Recommendation:** Enable caching for deployments with >500 tool calls/sec.

---

## Testing Validation

### Local Setup (Verified)

✅ **PostgreSQL database** — `vault_dev` created with proper permissions  
✅ **Vault server** — Running with PostgreSQL backend  
✅ **Storage table** — `vault_kv_store` manually created  
✅ **Initialization** — `vault operator init` successful  
✅ **Unsealing** — `vault operator unseal` working  
✅ **Policy** — `contextforge` policy created and verified  
✅ **Token** — Scoped token generated and saved  
✅ **CRUD operations** — Write, read, list, delete all tested  
✅ **PostgreSQL storage** — Verified data persists in `vault_kv_store` table (51+ rows)  
✅ **Restart persistence** — Secrets survive Vault restart

### Command-Line Test Suite

All commands from `docs/vault-local-dev-postgresql.md` Step 12 verified:
```bash
vault kv put secret/contextforge/oauth/test-server/testuser@example.com ...   # ✓
vault kv get secret/contextforge/oauth/test-server/testuser@example.com       # ✓
vault kv list secret/contextforge/oauth/test-server                           # ✓
vault kv delete secret/contextforge/oauth/test-server/testuser@example.com    # ✓
```

---

## Documentation Status

### ✅ Complete

- `contextforge-pluggable-token-storage-architect-design-document.html` — 22 sections, all consistent
- `docs/vault-local-dev-postgresql.md` — Tested 16-step guide with verification

### 📝 To Be Created (Post-Approval)

- Implementation tickets (broken down by section)
- API documentation updates (new `/vault/*` endpoints)
- Operations runbook (Vault token rotation, troubleshooting)
- Migration guide (database → Vault transition plan)

---

## Architect Sign-Off Checklist

Please review and approve/comment on:

- [ ] **Implementation Scope** — Vault ONLY (no database changes in Phase 1)
- [ ] **Path Structure** — `{team_id}/{server_id}/{email}` composite key
- [ ] **Payload Schema** — Nested `token` object structure
- [ ] **Caching Strategy** — Optional TTL-based cache (Section 12)
- [ ] **team_id Extraction** — How to derive `team_id` from authenticated user (Vault-only concern)
- [ ] **server_id Derivation** — Hash vs. UUID for path segment
- [ ] **Database Preservation** — Confirm existing database OAuth flow remains untouched
- [ ] **Future Phases** — Confirm database refactoring is deferred (Phase 3+)
- [ ] **Performance Trade-offs** — Cache consistency vs. latency
- [ ] **Security Model** — Vault policies, audit logging, token scoping
- [ ] **New Endpoints** — `/vault/authorize/{server_id}` and `/vault/callback` design

---

## Recommendation

**Status: ✅ READY FOR ARCHITECT REVIEW**

This design is comprehensive, internally consistent, and backed by a tested local development setup. All path references, payload structures, and section numbers are aligned. The caching strategy addresses performance concerns for high-throughput deployments.

**Suggested Next Steps:**

1. Architect reviews and approves/requests changes
2. Resolve open questions (team_id extraction, server_id derivation)
3. Break down into implementation tickets
4. **Phase 1 (Current):** VaultTokenBackend + `/vault/*` endpoints + caching (optional)
5. **Phase 2 (Future):** Production-grade Vault auth (AppRole, K8s SA)
6. **Phase 3+ (Future, if needed):** Database refactoring, migration tooling

**Estimated Implementation Time:** 
- **Phase 1 (Vault implementation):** 2-3 weeks
- **Phase 1 + caching:** +1 week (total 3-4 weeks)
- **Database refactoring (Phase 3):** Deferred until business need exists

---

**Document Version:** 1.0  
**Last Updated:** 2026-07-08  

