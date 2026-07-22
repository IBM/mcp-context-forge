# [FEATURE]: Pluggable OAuth Token Storage with HashiCorp Vault Backend

## Summary

Implement pluggable token storage for OAuth credentials with HashiCorp Vault as the first alternative backend to the existing database storage. This enables enterprise clients operating Vault to redirect credential storage without forking the core service, while maintaining the existing database backend as the default.

## Problem Statement

Currently, every OAuth `access_token` and `refresh_token` issued through ContextForge's Authorization Code flow is hardwired into a single `oauth_tokens` database table. Enterprise clients operating HashiCorp Vault cannot redirect credential storage without forking the core service. This creates operational challenges for organizations with:

- Centralized secret management policies requiring Vault
- Compliance requirements for credential storage and audit trails
- Existing Vault infrastructure with established rotation policies
- Need for geo-distributed secret replication

## Proposed Solution

### Architecture Overview

Implement a **pluggable token storage architecture** with three components:

1. **`AbstractTokenBackend`** — Backend-agnostic interface with 5 methods: `store_tokens()`, `get_user_token()`, `get_token_info()`, `revoke_user_tokens()`, `cleanup_expired_tokens()`
2. **`DatabaseTokenBackend`** — Minimal extraction of existing database code (Phase 1: copy-paste, zero behavior changes)
3. **`VaultTokenBackend`** — New Vault KV v2 implementation
4. **`TokenStorageService`** — Thin façade that selects backend via `OAUTH_TOKEN_BACKEND` environment variable

### Key Design Decisions

#### Vault Path Structure

Vault secrets stored at path: `{team_id}/{server_id}/{email}` where:
- `team_id` — extracted from authenticated user context (JWT claims or session)
- `server_id` — derived from **upstream MCP URL** (`gateways.url`) via SHA-256 hash (first 8 hex chars)
- `email` — URL-encoded user email from authentication context

**Critical architectural detail:** The system identifier switches from `gateway_id` (internal UUID FK) to `mcp_url` (human-readable upstream endpoint URL from `gateways.url`). This makes Vault paths portable across database migrations and directly maps to what operators see in the Vault UI.

#### Client Access Model

Clients **never see** gateway internals. The client only knows the virtual server URL:
```json
{
  "servers": {
    "git-server": {
      "type": "streamable-http",
      "url": "http://localhost:4444/servers/647ad7b348044bce8fa27a2157b00a0d/mcp",
      "headers": { "Authorization": "Bearer your-token-here" }
    }
  }
}
```

Resolution chain: `server_id` → `server_tool_association` → `tools.gateway_id` → `gateways.id` → `gateways.url` (the credential anchor)

#### New Vault Endpoints

Two new client-callable endpoints (registered only when `OAUTH_TOKEN_BACKEND=vault`):

1. **`GET /vault/authorize/{server_id}`** — Initiates OAuth flow using virtual server ID
   - Client passes only `server_id` from their MCP config URL
   - Optional `?gateway_url=` param for multi-gateway servers
   - Server resolves chain and redirects to IdP

2. **`GET /vault/callback`** — OAuth callback handler
   - Validates HMAC state
   - Exchanges code for tokens
   - Extracts `team_id` from user context
   - Calls `TokenStorageService.store_tokens()` → `VaultTokenBackend` resolves `gateway_id → mcp_url` and writes to Vault

### Scope

#### ✅ Phase 1 (This Feature)

**Vault Backend:**
- Full `VaultTokenBackend` implementation (store, retrieve, refresh, revoke)
- New endpoints: `/vault/authorize/{server_id}` + `/vault/callback`
- Vault secret schema with path `{team_id}/{server_id}/{email}`
- Static `VAULT_TOKEN` authentication
- Token caching (optional, configurable via `VAULT_TOKEN_CACHE_ENABLED`)
- Local dev setup guide with PostgreSQL storage backend
- Production Vault + PostgreSQL HA configuration

**Database Backend:**
- **Minimal extraction only** — copy existing code → `DatabaseTokenBackend` class
- Accept `team_id` parameter for interface consistency but **completely ignore it**
- ❌ NO database schema changes (no `team_id` column added)
- ❌ NO SQL query changes (continue using `(gateway_id, app_user_email)` as unique key)
- ❌ NO behavior changes (UPSERT, encryption, refresh logic all unchanged)
- This is **purely code reorganization** to enable the façade pattern

**Façade:**
- `TokenStorageService` becomes thin backend selector
- Call sites minimally changed — only instantiation adds `user_context` parameter
- Method signatures unchanged

#### ⛔ Out of Scope (Future Phases)

**Phase 2:**
- Add `team_id` column to `oauth_tokens` table (Alembic migration)
- Update SQL queries to use `team_id` in WHERE clauses
- Change unique constraint to `(team_id, gateway_id, app_user_email)`
- Replace static `VAULT_TOKEN` with Vault AppRole or Kubernetes ServiceAccount auth

**Phase 3:**
- CLI migration script: read DB rows → decrypt → resolve `gateway_id → gateways.url` → write to Vault → delete DB rows

**Never:**
- Changes to OAuth 2.0 / PKCE flow (RFC 6749)
- Redis / AWS Secrets Manager / Azure Key Vault backends (future, requires abstract interface)
- Dual-backend fallback mode (choose one backend at deployment time)

## Implementation Details

### File Structure

```
mcpgateway/services/
  token_storage_service.py         [CHANGED] thin façade — reads OAUTH_TOKEN_BACKEND, delegates all 5 methods
  token_backends/                   [NEW PACKAGE]
    __init__.py                     re-exports AbstractTokenBackend, DatabaseTokenBackend, VaultTokenBackend
    base.py                         AbstractTokenBackend ABC + TokenRecord dataclass (no SQLAlchemy)
    db_backend.py                   DatabaseTokenBackend — exact extraction of today's DB logic, zero behavior change
    vault_backend.py                VaultTokenBackend — Vault KV v2 via httpx; path built from gateways.url

mcpgateway/routers/
  vault_router.py                   [NEW] GET /vault/authorize/{server_id} · GET /vault/callback

mcpgateway/config.py                [CHANGED] 10 new env vars (7 Vault + 3 cache); no existing field touched
mcpgateway/main.py                  [CHANGED] register vault_router when OAUTH_TOKEN_BACKEND=vault
pyproject.toml                      [CHANGED] optional extra [vault] = hvac>=2.3.0 (not mandatory)

mcpgateway/db.py · OAuthToken       [UNCHANGED] table stays; no team_id column yet (Phase 2)
routers/oauth_router.py             [MINIMAL] TokenStorageService(db) → TokenStorageService(db, user_context)
services/tool_service.py            [MINIMAL] TokenStorageService(db) → TokenStorageService(db, user_context)
services/gateway_service.py         [MINIMAL] TokenStorageService(db) → TokenStorageService(db, user_context)
services/resource_service.py        [MINIMAL] TokenStorageService(db) → TokenStorageService(db, user_context)
admin.py                            [MINIMAL] TokenStorageService(db) → TokenStorageService(db, user_context)
```

### Configuration

#### Backend Selection
```bash
OAUTH_TOKEN_BACKEND=vault  # or "database" (default)
```

#### Vault Connection (when OAUTH_TOKEN_BACKEND=vault)
```bash
VAULT_ADDR=https://vault.acme.com:8200
VAULT_TOKEN=<scoped-token>                    # Static token (Phase 1); AppRole in Phase 2
VAULT_NAMESPACE=                              # Enterprise only; omit for CE
VAULT_KV_MOUNT=secret                         # KV v2 mount path
VAULT_KV_PATH_PREFIX=contextforge/oauth       # Prefix within mount
VAULT_TLS_VERIFY=true                         # Always true in production; false for local dev
```

#### Token Cache (Vault backend only — optional)
```bash
VAULT_TOKEN_CACHE_ENABLED=false               # Enable for production >100 concurrent users
VAULT_TOKEN_CACHE_TTL=300                     # Cache TTL in seconds
VAULT_TOKEN_CACHE_MAX_SIZE=10000              # Max cached entries before LRU eviction
```

### AbstractTokenBackend Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TokenRecord:
    """Plain dataclass — no SQLAlchemy dependencies."""
    gateway_id: str           # gateways.id (UUID) — used by DB backend
    mcp_url: str              # gateways.url — resolved by VaultTokenBackend; used as Vault path key
    team_id: str              # Team identifier — extracted from user context; required for Vault path
    user_id: str              # OAuth provider user ID
    app_user_email: str       # ContextForge user identity
    access_token: str         # Plain-text (each backend handles encryption differently)
    refresh_token: str | None
    token_type: str           # Always "Bearer"
    expires_at: datetime | None
    scopes: list[str]
    created_at: datetime
    updated_at: datetime


class AbstractTokenBackend(ABC):
    """Backend-agnostic token storage interface.
    
    All methods receive gateway_id and team_id. Each backend uses them appropriately:
      DatabaseTokenBackend  → uses gateway_id directly as FK; team_id ignored (no DB column yet)
      VaultTokenBackend     → uses team_id in path; resolves gateway_id → mcp_url → server_id
    """

    @abstractmethod
    async def store_tokens(
        self,
        gateway_id: str,
        team_id: str,
        user_id: str,
        app_user_email: str,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
    ) → TokenRecord: ...

    @abstractmethod
    async def get_user_token(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
        threshold_seconds: int = 300,
    ) → str | None: ...

    @abstractmethod
    async def get_token_info(
        self, gateway_id: str, team_id: str, app_user_email: str,
    ) → dict | None: ...

    @abstractmethod
    async def revoke_user_tokens(
        self, gateway_id: str, team_id: str, app_user_email: str,
    ) → bool: ...

    @abstractmethod
    async def cleanup_expired_tokens(
        self, max_age_days: int = 30,
    ) → int: ...
```

### Vault Secret Schema

**Path pattern:**
```
<VAULT_KV_MOUNT>/data/<VAULT_KV_PATH_PREFIX>/<team_id>/<server_id>/<url-encoded email>
```

**Example paths:**
```
secret/data/contextforge/oauth/engineering/647ad7b3/alice%40acme.com
secret/data/contextforge/oauth/sales/8f2c91e5/bob%40acme.com
```

**Secret payload (JSON):**
```json
{
  "email": "alice@acme.com",
  "team_id": "engineering",
  "mcp_url": "https://mcp.github.acme.com",
  "token": {
    "access_token": "gho_Aa1Bb2...",
    "refresh_token": "ghr_Rr9Ss8...",
    "scopes": ["repo", "read:user"]
  },
  "user_id": "github_uid_44712",
  "token_type": "Bearer",
  "expires_at": "2026-07-07T18:00:00Z",
  "created_at": "2025-07-07T10:00:00Z",
  "updated_at": "2025-07-07T10:00:00Z"
}
```

### End-to-End Flow Example

1. Alice calls `GET /vault/authorize/647ad7b3…` with ContextForge Bearer token
2. ContextForge resolves: `server_id → server_tool_association → tools.gateway_id → gateways.url`
3. Builds PKCE + HMAC state, saves to `oauth_states` table
4. 302 Redirect → GitHub IdP authorization URL
5. Alice approves, GitHub redirects to `GET /vault/callback?code=abc&state=…`
6. ContextForge validates state, exchanges code for tokens
7. Extracts `team_id` from user context (JWT/session)
8. Calls `TokenStorageService.store_tokens()` → `VaultTokenBackend`
9. Backend resolves `gateway_id → gateways.url`, hashes to `server_id`
10. Writes to Vault: `PUT secret/data/contextforge/oauth/engineering/647ad7b3/alice%40acme.com`
11. Alice's MCP client calls tool → `TokenStorageService.get_user_token()`
12. Backend resolves path, reads from Vault: `GET secret/data/contextforge/oauth/...`
13. Returns token to tool service, which forwards to upstream with `Authorization: Bearer gho_Aa1Bb2…`

## Security Properties

| Property | DB Backend | Vault Backend |
|----------|------------|---------------|
| Client sees gateway internals | No | No — client uses server_id only; mcp_url resolved server-side |
| Tokens encrypted at rest | Fernet AES-128 (app-layer) | AES-256-GCM (Vault seal — Postgres stores only ciphertext) |
| Per-user isolation | UNIQUE (gateway_id, app_user_email) | Unique path per (team_id, server_id, email) + Vault ACL |
| Key ownership | ContextForge (AUTH_ENCRYPTION_SECRET) | Vault seal key — ContextForge holds no key material |
| Audit trail | CF audit log + DB timestamps | CF audit log + Vault audit log (every read/write) + KV version history |
| Vault auth endpoint | N/A | Requires ContextForge Bearer token — same auth as /servers/* |

## Performance Considerations

### Expected Latency

| Operation | Database Backend | Vault Backend | Overhead |
|-----------|------------------|---------------|----------|
| `store_tokens()` | ~5ms (local Postgres) | ~35ms (CF → Vault → Postgres) | +30ms (7×) |
| `get_user_token()` | ~3ms (SELECT + decrypt) | ~25ms (CF → Vault GET) | +22ms (8×) |
| `get_user_token()` with refresh | ~150ms (IdP + DB update) | ~180ms (IdP + Vault PUT) | +30ms |

**Network hops:** Database = 1 hop (CF → Postgres). Vault = 2 hops (CF → Vault → Postgres).

### Token Cache Impact (when enabled)

| Metric | No Cache | With Cache (hit) | With Cache (miss) |
|--------|----------|------------------|-------------------|
| Read latency | ~25ms | ~0.5ms (50× faster) | ~25ms |
| Memory overhead | ~0 | ~1KB per token (~10MB for 10k tokens) | ~1KB per token |

**Recommendation:** Enable cache for production deployments with >100 concurrent users or >500 tool calls/sec.

## Testing Requirements

### Unit Tests
- [ ] `test_abstract_token_backend.py` — interface contract validation
- [ ] `test_database_token_backend.py` — existing behavior preserved (copy-paste verification)
- [ ] `test_vault_token_backend.py` — Vault KV v2 operations (store, retrieve, refresh, revoke)
- [ ] `test_token_storage_service.py` — façade backend selection logic
- [ ] `test_vault_router.py` — authorize/callback endpoints
- [ ] `test_gateway_id_resolution.py` — server_id → gateway_id → mcp_url chain

### Integration Tests
- [ ] `test_vault_oauth_flow_e2e.py` — full OAuth flow with Vault backend
- [ ] `test_database_oauth_flow_e2e.py` — existing flow still works (regression)
- [ ] `test_token_cache.py` — cache hit/miss/eviction/invalidation
- [ ] `test_vault_connectivity.py` — Vault unreachable/auth failures
- [ ] `test_multi_gateway_server.py` — virtual server with multiple OAuth gateways

### Manual Testing
- [ ] Local dev setup with Vault + PostgreSQL storage backend
- [ ] Production Vault HA cluster with PostgreSQL backend
- [ ] Token rotation after expiry
- [ ] Admin revoke flow
- [ ] Vault UI verification (secret paths, payload structure)
- [ ] PostgreSQL verification (vault_kv_store table contains ciphertext only)

## Documentation Requirements

- [ ] `docs/vault-local-dev-complete-guide.md` — Complete local dev setup guide (PostgreSQL + Vault)
- [ ] `docs/vault-production-setup.md` — Production Vault HA + PostgreSQL configuration
- [ ] `docs/oauth-vault-team-isolation.md` — Team-scoped token storage architecture
- [ ] `docs/vault-api-reference.md` — Vault KV v2 API usage patterns
- [ ] Update `CLAUDE.md` — Add Vault backend configuration section
- [ ] Update `README.md` — Add Vault as supported token storage backend
- [ ] Update `.env.example` — Add commented Vault configuration block

## Migration Path

| Scenario | Action Required |
|----------|-----------------|
| Keep database backend | Do nothing. `OAUTH_TOKEN_BACKEND=database` is the default. Zero code change. |
| New deployment with Vault | Set `OAUTH_TOKEN_BACKEND=vault` + Vault env vars. Follow setup guide. |
| Existing deployment → Vault | Existing DB tokens not auto-migrated. Users re-authorize once. Old rows can be purged after migration window. |
| Phase 3 migration script | CLI command to decrypt DB rows, resolve gateway_id → mcp_url, write to Vault, delete DB rows. |

## Rollout Plan

### Phase 1: Development (Week 1-2)
1. Implement `AbstractTokenBackend` + `TokenRecord` dataclass
2. Extract `DatabaseTokenBackend` (copy-paste, zero behavior changes)
3. Implement `VaultTokenBackend` with path resolution
4. Update `TokenStorageService` façade
5. Add `/vault/authorize` and `/vault/callback` endpoints
6. Unit tests + integration tests

### Phase 2: Local Testing (Week 3)
1. Complete local dev setup guide with PostgreSQL backend
2. Manual testing of full OAuth flow
3. Verify Vault UI shows correct secret structure
4. Verify PostgreSQL `vault_kv_store` table contains ciphertext only
5. Test token cache (enable/disable/eviction)

### Phase 3: Staging Deployment (Week 4)
1. Deploy to staging with Vault + PostgreSQL HA backend
2. Load testing (100 concurrent users, 500 tool calls/sec)
3. Vault monitoring + alerting setup
4. Document operational runbooks

### Phase 4: Production Rollout (Week 5+)
1. Production Vault cluster (3 nodes) + PostgreSQL HA backend
2. Auto-unseal with AWS KMS / Azure Key Vault / GCP KMS
3. Backup/restore procedures documented
4. Gradual rollout (20% → 50% → 100% traffic)
5. Monitor latency P99, error rates, Vault health

## Success Criteria

- [ ] Zero behavior changes to existing database backend
- [ ] Vault backend passes all integration tests
- [ ] Local dev setup guide allows contributor to run Vault in <15 minutes
- [ ] Production Vault HA setup documented with DR procedures
- [ ] Latency P99 for `get_user_token()` < 50ms (Vault backend without cache)
- [ ] Latency P99 for `get_user_token()` < 5ms (Vault backend with cache enabled)
- [ ] Zero downtime during Vault token rotation
- [ ] Admin UI works transparently with both backends
- [ ] All security invariants maintained (Layer 1 + Layer 2 auth model)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Database extraction introduces subtle bugs | High | Extensive regression tests; flag Phase 1 extraction as behavior-preserving only |
| Vault latency impacts P99 for tool calls | Medium | Implement token cache; document cache trade-offs; allow disabling per deployment |
| Vault unavailable → all OAuth operations fail | High | Document emergency fallback to database backend; implement retry logic with exponential backoff |
| Static VAULT_TOKEN compromised | High | Phase 1 limitation acknowledged; Phase 2 AppRole/SA auth required for production; document rotation procedure |
| Migration path unclear for existing users | Medium | Phase 3 CLI script; document manual re-auth UX |

## Open Questions

1. **Should Phase 1 include Vault AppRole auth, or defer to Phase 2?**
   - **Recommendation:** Defer to Phase 2. Static token acceptable for dev/staging; document limitation clearly.

2. **Should cleanup_expired_tokens() log WARNING or DEBUG for Vault no-op?**
   - **Decision:** WARNING level, logged once per process start. Educates operators: "Vault KV TTL is your responsibility."

3. **Multi-gateway servers: UI prompt or auto-select?**
   - **Decision:** Auto-redirect if 1 gateway; selection page if N > 1. API clients use `?gateway_url=` param directly.

4. **Should Phase 1 include migration script (DB → Vault)?**
   - **Recommendation:** Defer to Phase 3. Manual re-auth acceptable for Phase 1; automated migration adds complexity.

## Related Issues

- #3883 — Observability separate session pattern (audit trail for Vault writes)
- #2871 — Audit trail separate session pattern (log Vault operations)
- #4341 — Private gateway ownership security check (preserved in both backends)
- #4671 — Token scope enforcement at Layer 1 (applies to both backends)

## References

- Design Document: `contextforge-pluggable-token-storage-architect-design-document.html`
- AGENTS.md: Two-layer security model (token scoping + RBAC)
- AGENTS.md: User identity extraction (canonical email-over-sub precedence)
- Local Dev Guide: `docs/vault-local-dev-complete-guide.md` (to be created)
- OAuth Design: `docs/docs/architecture/oauth-design.md`
- Multi-tenancy: `docs/docs/architecture/multitenancy.md`
- RBAC: `docs/docs/manage/rbac.md`

---

**Labels:** `enhancement`, `security`, `oauth`, `vault`, `api`, `python`, `triage`

**Milestone:** Phase 1 (Vault Backend + Minimal DB Extraction)

**Assignee:** TBD

**Estimated Effort:** 3-4 weeks (including testing and documentation)
