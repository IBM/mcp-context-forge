# Architect Review: Pluggable Token Storage Design Document
## Feature #5402 - HashiCorp Vault Integration

**Document Reviewed:** `contextforge-pluggable-token-storage-architect-design-document.html`  
**Reviewer:** AI Architect Assistant  
**Review Date:** 2026-07-07  
**Status:** APPROVED WITH REQUIRED CHANGES

---

## Executive Summary

**Overall Assessment:** ✅ **APPROVED** with critical corrections required before implementation.

The design document is comprehensive and demonstrates strong architectural thinking. However, there are **5 critical issues** and **8 recommendations** that must be addressed before development begins.

**Key Strengths:**
- Clear problem/solution statement with enterprise justification
- Excellent security model preserving client access patterns
- Comprehensive Vault setup for dev and production environments
- Well-defined scope boundaries (in/out of scope)
- Detailed end-to-end flow walkthrough

**Critical Gaps:**
- Missing backward compatibility strategy for existing call sites
- Incomplete error handling and failure mode analysis
- Production deployment considerations underspecified
- Open questions (§18) need architect decisions, not just questions
- Missing observability and operational runbook details

---

## CRITICAL ISSUES (Must Fix Before Implementation)

### 🔴 CRITICAL #1: Interface Design Contradicts Backward Compatibility Claim

**Location:** §5 (AbstractTokenBackend Interface), §6 (TokenStorageService Façade)

**Issue:**  
The document states:
> "All existing call sites are unchanged" (§4 file map)

But the interface signature uses `mcp_url` as the first parameter:
```python
async def store_tokens(
    mcp_url: str,          # gateways.url — the upstream MCP endpoint
    user_id: str,
    ...
```

However, all current call sites pass `gateway_id` (a UUID):
- `oauth_router.py:627` → `store_tokens(gateway_id=...)`
- `tool_service.py:4060` → `get_user_token(gateway_id=...)`
- `gateway_service.py:1931` → `get_user_token(gateway_id=...)`

**This is a breaking change** that contradicts the "UNCHANGED" tags in §4.

**Required Fix:**  
Choose one approach and update document consistently:

**Option A (Recommended - Backward Compatible):**
```python
# TokenStorageService (façade) maintains gateway_id signature
class TokenStorageService:
    async def store_tokens(self, gateway_id: str, user_id: str, ...):
        # Resolve gateway_id → gateways.url internally
        mcp_url = self._resolve_mcp_url(gateway_id)
        return await self._backend.store_tokens(mcp_url, user_id, ...)
    
    def _resolve_mcp_url(self, gateway_id: str) -> str:
        gateway = self.db.get(Gateway, gateway_id)
        return gateway.url
```

**Option B (Breaking Change - Cleaner but risky):**
- Update ALL call sites to resolve `gateway_id → mcp_url` before calling `TokenStorageService`
- Requires changes in 5+ routers and services
- Higher risk of bugs during migration

**Architect Decision Required:** Document must specify which option is chosen and update §4, §5, §6 accordingly.

---

### 🔴 CRITICAL #2: Missing Failure Mode Analysis & Error Handling

**Location:** Entire document - no dedicated section

**Issue:**  
The document describes the happy path thoroughly but does not address:

1. **Vault unreachable during OAuth callback** → `store_tokens()` fails
   - Current behavior: User completes OAuth at IdP, gets redirected back, but token storage fails
   - User impact: Sees error page after successful OAuth → confusing UX
   - **Required:** Specify retry strategy, user messaging, fallback behavior

2. **Vault unreachable during tool call** → `get_user_token()` fails
   - Current behavior: Tool invocation fails with cryptic error
   - User impact: Cannot use tools even though they previously authorized
   - **Required:** Define error message, suggested user action, SRE alerting

3. **Token refresh fails with Vault backend** → `_refresh_access_token()` cannot persist
   - Current behavior: Refresh succeeds at IdP but Vault write fails
   - Impact: Token leak (in memory) + user re-prompted to authorize
   - **Required:** Transactional guarantee or compensating action

4. **Vault token expires mid-request** (VAULT_TOKEN TTL in production)
   - Impact: All OAuth token operations fail until VAULT_TOKEN rotated
   - **Required:** Token rotation strategy, alerting thresholds

5. **Partial migration state** (Phase 3)
   - User has DB token, switches to Vault backend, token not migrated
   - Impact: Tool calls fail with "No token found"
   - **Required:** Dual-read mode or clear migration runbook

**Required Addition:**  
Add new section **§19: Failure Modes & Recovery**

```markdown
## §19: Failure Modes & Recovery

| Failure Scenario | Detection | User Impact | Recovery Action | Monitoring |
|------------------|-----------|-------------|-----------------|------------|
| Vault unreachable (network) | httpx.ConnectTimeout | 503 Service Unavailable | Retry 3x with exponential backoff | Alert if >5% requests fail |
| Vault auth failure (invalid VAULT_TOKEN) | 403 Forbidden | 500 Internal Error | Rotate VAULT_TOKEN (manual) | Critical alert immediately |
| Token not found in Vault | GET returns 404 | User prompted to re-authorize | Redirect to /vault/authorize/{server_id} | Log as INFO |
| Token refresh + Vault write fails | IdP succeeds, Vault PUT fails | Tool call fails, retry succeeds | Keep old token in memory cache (5 min) | WARN log + metric |
| Vault write timeout during callback | Timeout after 5s | User sees spinner, retries | Idempotent PUT (same path) safe to retry | Track p99 latency |
```

---

### 🔴 CRITICAL #3: Production PostgreSQL Vault Backend Underspecified

**Location:** §10 (Production — Vault with PostgreSQL Storage Backend)

**Issues:**

1. **No HA/DR strategy:**
   - Single Vault node + single Postgres instance = **single point of failure**
   - Production system cannot have 5-nines uptime without HA

2. **Missing connection pool sizing:**
   - Document shows `connection_url` but no `max_parallel` tuning guidance
   - Risk: Connection pool exhaustion under load

3. **No backup/restore procedure:**
   - Postgres `vault_kv_store` table contains encrypted tokens
   - If Postgres fails without backup → **all OAuth tokens lost**, all users must re-authorize

4. **No auto-unseal strategy:**
   - Manual unseal with 3/5 keys after server restart = **downtime during incident**
   - Enterprise requirement: auto-unseal with KMS (AWS KMS, Azure Key Vault, GCP KMS)

**Required Additions to §10:**

```markdown
### §10.8 — High Availability Configuration (Required for Production)

#### Vault HA Cluster (3 nodes minimum)
vault.hcl:
```hcl
storage "postgresql" {
  connection_url = "postgres://vault:pass@postgres-ha.acme.com:5432/vault?sslmode=require"
  ha_enabled     = "true"
  ha_table       = "vault_ha_locks"
}
```

#### PostgreSQL HA
- Use managed service (AWS RDS Multi-AZ, Azure Database HA, Google Cloud SQL)
- OR manual: Patroni + etcd for leader election
- Point-in-time recovery enabled (WAL archiving to S3/GCS)

#### Auto-Unseal (Phase 2 requirement)
```hcl
seal "awskms" {
  region     = "us-west-2"
  kms_key_id = "arn:aws:kms:us-west-2:123456789012:key/vault-unseal"
}
```
- Eliminates manual unseal step
- Vault can auto-restart after crash
```

---

### 🔴 CRITICAL #4: Open Questions (§18) Must Be Answered By Architect

**Location:** §18 (Open Questions for Architect / Product Owner)

**Issue:**  
An architect design document should **make recommendations**, not defer decisions to later.

**Current state:** 4 open questions with no architect guidance  
**Required:** Answer each question with a recommendation and justification

**Proposed Answers:**

#### Q1: Migration Strategy — Should switching backends force re-authorization?

**Architect Recommendation:** ✅ **Manual re-authorization in Phase 1, automated migration in Phase 3**

**Justification:**
- Automated migration script requires complex logic: decrypt DB token (Fernet) → resolve gateway_id → write to Vault
- Building this in Phase 1 delays the feature and increases risk of bugs
- Manual re-auth UX: Admin enables `OAUTH_TOKEN_BACKEND=vault`, users see "OAuth token expired" on next tool call → click link → re-authorize
- Phase 3 migration script runs AFTER Vault integration is stable in production

**Impact:** Phase 1 delivery accelerated by 2-3 weeks; users experience one-time re-auth during migration window

---

#### Q2: Is AppRole auth (Phase 2) required before production deployment?

**Architect Recommendation:** ⚠️ **Static VAULT_TOKEN acceptable for Phase 1 IF:**
1. Documented as "Phase 1 only — not for production"
2. Token TTL set to 720h (30 days)
3. Manual rotation documented in runbook
4. Phase 2 (AppRole) required before GA/production deployment

**Justification:**
- Static tokens simplify Phase 1 testing and early adopter feedback
- Enterprise deployments REQUIRE AppRole/Kubernetes SA auth for security compliance
- Compromise: Accept static token for dev/staging, mandate AppRole before prod

**Implementation Note:** Add startup warning log:
```python
if settings.oauth_token_backend == "vault" and settings.vault_token:
    logger.warning("Using static VAULT_TOKEN — not recommended for production. "
                   "Implement AppRole auth (Phase 2) before GA deployment.")
```

---

#### Q3: Should `cleanup_expired_tokens()` log WARNING or DEBUG when no-op for Vault?

**Architect Recommendation:** ✅ **WARNING level, logged once on first call**

**Justification:**
- Operators expect cleanup job to do something; silent no-op is confusing
- WARNING educates operator: "Vault TTL is YOUR responsibility"
- Log only once per process lifecycle to avoid log spam

**Implementation:**
```python
# VaultTokenBackend.cleanup_expired_tokens()
if not self._cleanup_warning_logged:
    logger.warning(
        "Vault backend does not support automatic token cleanup. "
        "Configure Vault KV TTL policy or vault-agent for expiration. "
        "See: https://developer.hashicorp.com/vault/docs/secrets/kv/kv-v2#ttl"
    )
    self._cleanup_warning_logged = True
return 0
```

---

#### Q4: Multi-gateway virtual servers — UI prompt or auto-list?

**Architect Recommendation:** ✅ **Auto-redirect if single gateway, interactive selection if multiple**

**Justification:**
- 80% use case: virtual server has one OAuth gateway → auto-redirect (zero clicks)
- 20% use case: virtual server aggregates multiple OAuth gateways → show selection page

**UX Flow:**
```
GET /vault/authorize/{server_id}

1. Resolve server → find OAuth gateways (can be 0, 1, or N)
2. If N == 0: return 400 "No OAuth gateways on this server"
3. If N == 1: auto-redirect to that gateway's IdP
4. If N > 1: render HTML selection page:
   
   ┌─────────────────────────────────────────┐
   │ This server uses multiple OAuth systems │
   │ Select which system to authorize:       │
   │                                          │
   │  ○ GitHub MCP (github.com)              │
   │  ○ Jira MCP (jira.acme.com)             │
   │                                          │
   │         [ Continue to OAuth ]           │
   └─────────────────────────────────────────┘
```

**API clients:** Use `?gateway_url=https://mcp.github.acme.com` query param to skip selection

---

### 🔴 CRITICAL #5: Missing Observability & Operational Readiness

**Location:** No dedicated section

**Issue:**  
Production deployment requires metrics, logs, alerts, and runbooks. Document has none.

**Required Addition:** Add new section **§20: Observability & Operations**

```markdown
## §20: Observability & Operations

### Metrics (Prometheus format)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `contextforge_token_backend_operations_total` | Counter | `backend={vault,database}`, `operation={store,get,refresh,revoke}`, `status={success,error}` | Track backend usage and errors |
| `contextforge_token_backend_latency_seconds` | Histogram | `backend`, `operation` | Detect slow Vault responses |
| `contextforge_vault_connection_errors_total` | Counter | `error_type={timeout,auth_failure,network}` | Alert threshold: >10/min |
| `contextforge_oauth_token_refresh_total` | Counter | `status={success,failure}`, `gateway_id` | Track refresh success rate |

### Logs (Structured JSON)

**Success:**
```json
{
  "level": "info",
  "operation": "vault.store_tokens",
  "mcp_url": "https://mcp.github.acme.com",
  "user_email": "alice@acme.com",
  "duration_ms": 47
}
```

**Error:**
```json
{
  "level": "error",
  "operation": "vault.get_user_token",
  "mcp_url": "https://mcp.jira.acme.com",
  "user_email": "bob@acme.com",
  "error": "VaultConnectionTimeout",
  "vault_addr": "https://vault.acme.com:8200",
  "retry_count": 3
}
```

**Never log:** `access_token`, `refresh_token`, raw Vault responses

### Alerts

| Alert | Threshold | Severity | Action |
|-------|-----------|----------|--------|
| `VaultBackendErrorRate` | >5% requests fail | Critical | Check Vault health, network, VAULT_TOKEN validity |
| `VaultLatencyHigh` | p99 >500ms | Warning | Investigate Vault/Postgres load |
| `OAuthRefreshFailureSpike` | >10 failures/min | Warning | Check IdP availability (GitHub, Jira) |
| `VaultTokenExpiring` | VAULT_TOKEN TTL <48h | Warning | Rotate token (runbook link) |

### Operational Runbook

#### Rotate VAULT_TOKEN (manual, Phase 1)
```bash
export VAULT_ADDR=https://vault.acme.com:8200
export VAULT_TOKEN=<current-root-token>

# Create new token
NEW_TOKEN=$(vault token create \
  -policy="contextforge" \
  -ttl="720h" \
  -format=json | jq -r '.auth.client_token')

# Update .env on all ContextForge nodes
# Rolling restart required (zero downtime with load balancer)

# Revoke old token after 1 hour grace period
vault token revoke <old-token>
```

#### Vault Postgres Backup
```bash
# Automated daily backup (cron)
pg_dump -h postgres-ha.acme.com -U vault \
  --format=custom \
  --file=/backups/vault-$(date +%Y%m%d).dump \
  vault

# Retention: 30 days local, 90 days in S3
```

#### Emergency Token Migration (Vault → DB fallback)
```bash
# If Vault is down for >2 hours and cannot be restored:
# 1. Switch all nodes to OAUTH_TOKEN_BACKEND=database
# 2. Users re-authorize (tokens written to DB)
# 3. When Vault restored: run Phase 3 migration script to sync back
```
```

---

## RECOMMENDATIONS (Should Fix)

### 📋 RECOMMENDATION #1: Clarify "System Field" Admin UI Behavior

**Location:** §7 (Vault Secret Schema), §13 (Backend Comparison)

**Issue:** Your comment mentions "system field will rename as with mcp url" but document doesn't clearly specify Admin UI behavior.

**Clarification Needed:** Add subsection to §13:

```markdown
### §13.1 — Admin UI Token Management Display

**Current UI (Database backend):**
| User Email | System | Status | Expires | Actions |
|------------|--------|--------|---------|---------|
| alice@acme.com | GitHub MCP | Active | 2026-07-08 | Revoke |

**"System" column source:**
- DatabaseTokenBackend: `SELECT gateways.name FROM oauth_tokens JOIN gateways ON gateway_id`
- VaultTokenBackend: `mcp_url` field from Vault payload → resolve to `gateways.name` via lookup

**No UI changes required** — both backends populate the same display column.
```

---

### 📋 RECOMMENDATION #2: Add Vault Enterprise vs Community Edition Guidance

**Location:** §12 (Configuration Reference)

**Issue:** `VAULT_NAMESPACE` is Enterprise-only but no guidance on licensing

**Add to §12:**
```markdown
### Vault Edition Compatibility

| Feature | Community Edition | Enterprise |
|---------|-------------------|------------|
| KV v2 secrets | ✅ Yes | ✅ Yes |
| PostgreSQL storage backend | ✅ Yes | ✅ Yes |
| Namespaces | ❌ No (leave VAULT_NAMESPACE blank) | ✅ Yes |
| Replication (DR/Performance) | ❌ No | ✅ Yes |
| HSM auto-unseal | ❌ No | ✅ Yes |

**Recommendation:** Community Edition sufficient for Phase 1. Enterprise required for multi-region deployments.
```

---

### 📋 RECOMMENDATION #3: Document Token Rotation Behavior Difference

**Location:** §13 (Backend Comparison)

**Issue:** Missing comparison of token rotation mechanics

**Add row to table:**
```markdown
| **Token refresh atomicity** | UPDATE oauth_tokens row (transactional) | Creates new KV version (eventual consistency if Postgres replicating) |
```

**Implication:** Vault backend with HA Postgres may briefly return stale token during refresh if read hits replica. Recommend read-your-writes consistency config.

---

### 📋 RECOMMENDATION #4: Phase 2 Should Include Vault Audit Log Integration

**Location:** §16 (Delivery Phases)

**Current Phase 2:** "AppRole + Kubernetes SA auth"

**Recommendation:** Expand Phase 2 scope:
```markdown
Phase 2 deliverables:
1. AppRole authentication (priority 1)
2. Kubernetes ServiceAccount auth (priority 1)
3. Vault audit log integration (priority 2)
   - Log all OAuth token read/write to Vault's audit backend
   - Correlate CF request ID with Vault operation for forensics
```

**Justification:** Enterprise security teams require audit trail correlation. Low effort, high compliance value.

---

### 📋 RECOMMENDATION #5: Add Performance Comparison Section

**Location:** Add new §21

**Suggested content:**
```markdown
## §21: Performance Considerations

### Latency Comparison (expected)

| Operation | DatabaseTokenBackend | VaultTokenBackend |
|-----------|---------------------|-------------------|
| store_tokens() | ~5ms (local Postgres) | ~25ms (Vault + Postgres write) |
| get_user_token() | ~3ms (SELECT + decrypt) | ~20ms (Vault GET) |
| Network hops | 1 (CF → Postgres) | 2 (CF → Vault → Postgres) |

### Throughput Impact

- **DatabaseTokenBackend:** Bound by CF database connection pool (typically 200 conns)
- **VaultTokenBackend:** Bound by Vault's Postgres pool (default 128) + Vault API rate limit

**Recommendation for high-traffic deployments:**
- Increase Vault `max_parallel` in storage config to 256
- Add Vault read replicas if >1000 tool calls/sec
- Consider short-lived in-memory cache (5 min) for hot tokens in future optimization
```

---

### 📋 RECOMMENDATION #6: Add Security Audit Checklist

**Location:** Add to §17 (Security Properties)

**Suggested addition:**
```markdown
### §17.1 — Pre-Production Security Checklist

- [ ] Vault TLS certificate valid and trusted by CF
- [ ] VAULT_TOKEN has minimal policy (contextforge/* prefix only)
- [ ] Vault audit logging enabled and forwarded to SIEM
- [ ] Vault PostgreSQL credentials rotated and stored in secrets manager (not plaintext in vault.hcl)
- [ ] Network policy: CF → Vault on private network (not public internet)
- [ ] Vault unseal keys stored in separate KMS (not on Vault host)
- [ ] OAuth callback URL allowlist configured in IdP (prevent redirect attacks)
- [ ] Rate limiting enabled on /vault/authorize endpoint (prevent DoS)
```

---

### 📋 RECOMMENDATION #7: Clarify Development Workflow

**Location:** §9 (Local Development)

**Issue:** Dev mode doesn't persist tokens across restarts — may confuse developers

**Add warning box after §9 Step 2:**
```markdown
⚠️ **Dev Mode Limitations:**
- Vault dev server stores secrets **in-memory only**
- Restarting vault server loses all tokens
- For persistent local testing, use Vault + PostgreSQL (Docker Compose provided):
  ```yaml
  # docker-compose.vault.yml
  services:
    postgres:
      image: postgres:16
      environment:
        POSTGRES_DB: vault
        POSTGRES_USER: vault
        POSTGRES_PASSWORD: dev-password
    vault:
      image: hashicorp/vault:1.17
      ports: ["8200:8200"]
      volumes: ["./vault.hcl:/vault/config/vault.hcl"]
      cap_add: [IPC_LOCK]
      command: vault server -config=/vault/config/vault.hcl
  ```
```

---

### 📋 RECOMMENDATION #8: Document Migration Window Planning

**Location:** §15 (Migration Path)

**Issue:** "Migration window" mentioned but not defined

**Add subsection:**
```markdown
### §15.1 — Migration Execution Plan (Phase 3)

**Assumptions:**
- 500 users with OAuth tokens in database
- Average 2 gateways per user = 1000 total tokens
- Migration script throughput: ~10 tokens/sec (includes Vault write + verification)

**Estimated duration:** ~2 minutes for full migration

**Recommended approach:**
1. **T-7 days:** Announce maintenance window to users via email/Slack
2. **T-0 (start):** Enable read-only mode (block new OAuth authorizations)
3. **T+0:00 to T+0:02:** Run migration script:
   ```bash
   python -m mcpgateway.scripts.migrate_tokens_to_vault \
     --batch-size 50 \
     --dry-run false \
     --delete-after-confirm
   ```
4. **T+0:02 to T+0:05:** Verification phase (smoke test tool calls with Vault backend)
5. **T+0:05:** Switch `OAUTH_TOKEN_BACKEND=vault` in production
6. **T+0:10:** Re-enable write mode, monitor for errors
7. **T+1 day:** If stable, drop oauth_tokens rows: `DELETE FROM oauth_tokens`

**Rollback plan:** Keep DB rows for 7 days; revert OAUTH_TOKEN_BACKEND=database if critical issues
```

---

## DECISION LOG (Architect Must Sign Off)

| Decision ID | Question | Recommendation | Rationale | Approved? |
|-------------|----------|----------------|-----------|-----------|
| D1 | Interface signature (mcp_url vs gateway_id) | Option A: Facade resolves gateway_id internally | Backward compatible, lower risk | ⬜ |
| D2 | Phase 1 migration strategy | Manual re-authorization; automated script in Phase 3 | Accelerates Phase 1 delivery | ⬜ |
| D3 | Static VAULT_TOKEN acceptable? | Yes for dev/staging; AppRole required before GA | Balances speed vs security | ⬜ |
| D4 | cleanup_expired_tokens() log level | WARNING, logged once | Operator education | ⬜ |
| D5 | Multi-gateway UX | Auto-redirect if 1, selection page if N>1 | Optimizes common case | ⬜ |
| D6 | HA/DR strategy | Mandate Vault HA + Postgres HA + auto-unseal in Phase 2 | Production readiness | ⬜ |
| D7 | Add observability section (§20) | Required before Phase 1 merge | Operational readiness | ⬜ |

---

## FINAL VERDICT

**Status:** ✅ **CONDITIONALLY APPROVED**

**Conditions for proceeding to implementation:**
1. ✅ **Critical #1 resolved:** Update document with Option A (backward compatible interface) OR justify Option B
2. ✅ **Critical #2 resolved:** Add §19 (Failure Modes & Recovery) with table above
3. ✅ **Critical #3 resolved:** Expand §10 with HA/DR strategy (can defer full implementation to Phase 2 if documented)
4. ✅ **Critical #4 resolved:** Replace §18 open questions with architect decisions above
5. ✅ **Critical #5 resolved:** Add §20 (Observability & Operations)

**Once these 5 critical issues are addressed, the document is APPROVED for Phase 1 implementation.**

**Recommendations 1-8 should be incorporated but are not blockers.**

---

## NEXT STEPS

1. **Author:** Update HTML document with required changes above
2. **Architect:** Review updated document, sign decision log
3. **DevOps:** Review §10 (Vault production setup) and §20 (operational runbook)
4. **Security:** Review §17 (security properties) and pre-production checklist
5. **Product:** Review Phase 1 delivery scope excludes automated migration (Phase 3)
6. **Engineering:** Begin Phase 1 implementation once all sign-offs complete

---

**Document Version:** v1.0  
**Review Completed:** 2026-07-07  
**Reviewer:** AI Architect Assistant  
**Distribution:** Feature #5402 stakeholders
