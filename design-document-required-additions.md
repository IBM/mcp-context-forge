# Required Additions to Pluggable Token Storage Design Document
## Supplement to: contextforge-pluggable-token-storage-architect-design-document.html

**Purpose:** This document contains the critical sections that need to be added or updated in your HTML design document before architect approval.

**How to use:** Copy the content below into corresponding sections of your HTML file.

---

## UPDATE §5: AbstractTokenBackend Interface (CORRECTED)

**Replace the current §5 content with:**

The backend interface uses `gateway_id` as the discriminator (not `mcp_url`) to maintain backward compatibility with existing call sites. The `TokenStorageService` façade handles resolution of `gateway_id → gateways.url` internally.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TokenRecord:
    """Plain dataclass - no SQLAlchemy dependencies."""
    gateway_id: str           # gateways.id (UUID)
    mcp_url: str              # gateways.url (resolved by façade)
    user_id: str              # OAuth provider user ID
    app_user_email: str       # ContextForge user identity
    access_token: str         # Plain-text (backends handle encryption)
    refresh_token: str | None
    token_type: str           # Always "Bearer"
    expires_at: datetime | None
    scopes: list[str]
    created_at: datetime
    updated_at: datetime


class AbstractTokenBackend(ABC):
    """
    Backend-agnostic token storage interface.
    
    All methods receive gateway_id and rely on the backend implementation
    to resolve it to the appropriate storage key (DB: gateway_id FK,
    Vault: gateways.url as path component).
    """

    @abstractmethod
    async def store_tokens(
        self,
        gateway_id: str,        # UUID from gateways.id
        user_id: str,           # OAuth provider user ID
        app_user_email: str,    # ContextForge user email
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
    ) -> TokenRecord:
        """Store or update OAuth tokens for a user."""
        pass

    @abstractmethod
    async def get_user_token(
        self,
        gateway_id: str,
        app_user_email: str,
        threshold_seconds: int = 300,
    ) -> str | None:
        """
        Retrieve valid access token for user.
        
        Auto-refreshes if within threshold_seconds of expiry.
        Returns None if no token found.
        """
        pass

    @abstractmethod
    async def get_token_info(
        self,
        gateway_id: str,
        app_user_email: str,
    ) -> dict | None:
        """Return non-sensitive metadata (scopes, expiry, status)."""
        pass

    @abstractmethod
    async def revoke_user_tokens(
        self,
        gateway_id: str,
        app_user_email: str,
    ) -> bool:
        """Delete tokens. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    async def cleanup_expired_tokens(
        self,
        max_age_days: int = 30,
    ) -> int:
        """
        Remove stale tokens older than max_age_days.
        
        DatabaseTokenBackend: deletes DB rows.
        VaultTokenBackend: returns 0 (Vault TTL handles cleanup).
        """
        pass
```

**Key Design Decision:**
- Call sites (oauth_router.py, tool_service.py, gateway_service.py) remain **unchanged** - they continue passing `gateway_id`
- `TokenStorageService` (façade) resolves `gateway_id → gateways.url` once per request
- `DatabaseTokenBackend` uses `gateway_id` directly as FK
- `VaultTokenBackend` receives `gateway_id`, looks up `gateways.url`, uses it as Vault path key

---

## UPDATE §6: TokenStorageService Façade (CORRECTED)

**Replace the current §6 content with:**

```python
from sqlalchemy.orm import Session
from mcpgateway.config import get_settings
from mcpgateway.db import Gateway
from mcpgateway.services.token_backends import (
    AbstractTokenBackend,
    DatabaseTokenBackend,
    VaultTokenBackend,
)


class TokenStorageService:
    """
    Façade that selects backend from OAUTH_TOKEN_BACKEND env var.
    
    All public methods maintain the existing gateway_id signature.
    Resolution to mcp_url happens internally for VaultTokenBackend.
    """

    def __init__(self, db: Session):
        self.db = db
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

    async def store_tokens(
        self,
        gateway_id: str,
        user_id: str,
        app_user_email: str,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
    ) -> TokenRecord:
        """Store tokens. Delegates to backend; signature unchanged."""
        return await self._backend.store_tokens(
            gateway_id, user_id, app_user_email,
            access_token, refresh_token, expires_in, scopes
        )

    async def get_user_token(
        self,
        gateway_id: str,
        app_user_email: str,
        threshold_seconds: int = 300,
    ) -> str | None:
        """Get valid token. Delegates to backend; signature unchanged."""
        return await self._backend.get_user_token(
            gateway_id, app_user_email, threshold_seconds
        )

    async def get_token_info(
        self,
        gateway_id: str,
        app_user_email: str,
    ) -> dict | None:
        """Get metadata. Delegates to backend; signature unchanged."""
        return await self._backend.get_token_info(gateway_id, app_user_email)

    async def revoke_user_tokens(
        self,
        gateway_id: str,
        app_user_email: str,
    ) -> bool:
        """Revoke tokens. Delegates to backend; signature unchanged."""
        return await self._backend.revoke_user_tokens(gateway_id, app_user_email)

    async def cleanup_expired_tokens(
        self,
        max_age_days: int = 30,
    ) -> int:
        """Cleanup stale tokens. Delegates to backend."""
        return await self._backend.cleanup_expired_tokens(max_age_days)
```

**Implementation Detail:**

`VaultTokenBackend.__init__()` receives the `db` session so it can resolve `gateway_id → gateways.url` on each operation:

```python
class VaultTokenBackend(AbstractTokenBackend):
    def __init__(self, db: Session, settings):
        self.db = db
        self.settings = settings
        # ... Vault client init ...
    
    def _resolve_mcp_url(self, gateway_id: str) -> str:
        """Internal helper: resolve gateway_id to gateways.url."""
        gateway = self.db.get(Gateway, gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")
        return gateway.url
    
    async def store_tokens(self, gateway_id: str, user_id: str, ...):
        mcp_url = self._resolve_mcp_url(gateway_id)
        # Now use mcp_url as Vault path key
        path = f"{self.mount}/data/{self.prefix}/{quote(mcp_url)}/{quote(app_user_email)}"
        # ... Vault PUT ...
```

**Why This Works:**
- ✅ Zero changes to existing call sites in oauth_router, tool_service, gateway_service
- ✅ DatabaseTokenBackend continues using gateway_id FK (no code change)
- ✅ VaultTokenBackend gets human-readable URLs in Vault paths
- ✅ Client MCP config remains unchanged (uses server_id, not gateway_id)

---

## ADD NEW §19: Failure Modes & Recovery

### Vault Backend Failure Scenarios

| Failure Scenario | Detection | User Impact | Recovery Action | SRE Alert |
|------------------|-----------|-------------|-----------------|-----------|
| **Vault unreachable (network)** | `httpx.ConnectTimeout` after 5s | 503 Service Unavailable on tool calls | Retry 3x with exponential backoff (1s, 2s, 4s) | Critical if >5% requests fail for >5 min |
| **Vault auth failure** | `403 Forbidden` response | 500 Internal Error | Check VAULT_TOKEN validity; rotate if expired | Critical alert immediately |
| **VAULT_TOKEN expired** | `403 Permission Denied` | All OAuth operations fail | Manual rotation (see §20.1 runbook) | Critical if detected, Warning 48h before expiry |
| **Token not found in Vault** | `404 Not Found` on GET | User sees "OAuth authorization required" | Redirect to `/vault/authorize/{server_id}` | INFO log only (expected after token revocation) |
| **Vault write timeout (callback)** | Timeout after 10s | User sees error page after IdP redirect | Idempotent retry safe (same path PUT) | Warning if p99 latency >1s |
| **Token refresh succeeds at IdP, Vault write fails** | IdP 200, Vault 5xx | Tool call fails; next call retries refresh | Keep old token in memory cache (5 min TTL) as fallback | Error log + metric spike |
| **Postgres backend down (Vault storage)** | Vault returns 500 | All Vault operations fail | Postgres HA failover (automatic with managed service) | Critical |
| **Vault sealed after restart** | `503 Service Unavailable` with `"sealed":true` | All operations fail | Auto-unseal (KMS) or manual unseal with 3/5 keys | Critical page |

### Error Response Format

When Vault backend fails, return user-friendly error with actionable guidance:

```json
{
  "error": {
    "code": "OAUTH_TOKEN_UNAVAILABLE",
    "message": "Could not retrieve your OAuth credentials. Please re-authorize.",
    "details": "The credential storage system is temporarily unavailable.",
    "action": {
      "text": "Click here to re-authorize",
      "url": "/vault/authorize/647ad7b348044bce8fa27a2157b00a0d"
    }
  }
}
```

**Never expose internal details** (Vault URLs, paths, token format) to end users.

### Retry Logic (VaultTokenBackend Implementation)

```python
async def get_user_token(self, gateway_id: str, app_user_email: str, ...):
    for attempt in range(3):
        try:
            return await self._vault_get(path)
        except httpx.ConnectTimeout:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s
                continue
            logger.error(f"Vault unreachable after 3 attempts", extra={...})
            raise GatewayConnectionError("Credential storage unavailable")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.critical("Vault auth failure - VAULT_TOKEN invalid")
                raise
            elif e.response.status_code == 404:
                return None  # No token found - expected
            else:
                raise
```

---

## ADD NEW §20: Observability & Operations

### §20.1: Metrics (Prometheus Format)

Export the following metrics for production monitoring:

```python
# Counter: backend operation totals
contextforge_token_backend_operations_total{
    backend="vault",           # or "database"
    operation="store",         # store, get, refresh, revoke, cleanup
    status="success"           # success, error
} 1234

# Histogram: operation latency
contextforge_token_backend_latency_seconds{
    backend="vault",
    operation="get"
} 0.047  # 47ms

# Counter: Vault-specific errors
contextforge_vault_errors_total{
    error_type="timeout"       # timeout, auth_failure, not_found, server_error
} 5

# Gauge: Vault connection health
contextforge_vault_healthy{
    vault_addr="https://vault.acme.com:8200"
} 1  # 1=healthy, 0=unhealthy

# Counter: OAuth token refresh operations
contextforge_oauth_refresh_total{
    gateway_id="gw-github",
    status="success"           # success, failure
} 42
```

### §20.2: Structured Logging

**Success (INFO level):**
```json
{
  "timestamp": "2026-07-07T14:35:22.123Z",
  "level": "info",
  "component": "vault_backend",
  "operation": "store_tokens",
  "gateway_id": "gw-github-01",
  "mcp_url": "https://mcp.github.acme.com",
  "user_email": "alice@acme.com",
  "duration_ms": 47
}
```

**Error (ERROR level):**
```json
{
  "timestamp": "2026-07-07T14:35:22.456Z",
  "level": "error",
  "component": "vault_backend",
  "operation": "get_user_token",
  "gateway_id": "gw-jira-01",
  "user_email": "bob@acme.com",
  "error_type": "VaultConnectionTimeout",
  "vault_addr": "https://vault.acme.com:8200",
  "retry_count": 3,
  "stack_trace": "..."
}
```

**NEVER log:** `access_token`, `refresh_token`, VAULT_TOKEN value, or raw Vault responses containing secrets.

### §20.3: Alerting Rules

| Alert Name | Condition | Severity | Runbook |
|------------|-----------|----------|---------|
| `VaultBackendErrorRate` | `rate(contextforge_vault_errors_total[5m]) > 0.05` | Critical | Check Vault health, network connectivity, VAULT_TOKEN validity |
| `VaultLatencyHigh` | `histogram_quantile(0.99, contextforge_token_backend_latency_seconds) > 0.5` | Warning | Investigate Vault or Postgres load; check network latency |
| `VaultTokenExpiring` | `vault_token_ttl_seconds < 172800` (48h) | Warning | Rotate VAULT_TOKEN per runbook §20.4 |
| `OAuthRefreshFailureSpike` | `rate(contextforge_oauth_refresh_total{status="failure"}[5m]) > 0.1` | Warning | Check IdP availability (GitHub, Jira APIs) |
| `VaultUnhealthy` | `contextforge_vault_healthy == 0` | Critical | Check Vault service status, unseal state, Postgres backend |

### §20.4: Operational Runbook

#### Rotate VAULT_TOKEN (Manual - Phase 1)

**When:** Token TTL <48 hours, or on suspected compromise

**Steps:**
```bash
# 1. Create new token with same policy
export VAULT_ADDR=https://vault.acme.com:8200
export VAULT_TOKEN=<current-root-or-admin-token>

NEW_TOKEN=$(vault token create \
  -policy="contextforge" \
  -display-name="contextforge-prod-$(date +%Y%m%d)" \
  -ttl="720h" \
  -format=json | jq -r '.auth.client_token')

echo "New token: $NEW_TOKEN"

# 2. Update ContextForge environment
# Option A: Update .env file on all nodes
sed -i.bak "s/VAULT_TOKEN=.*/VAULT_TOKEN=$NEW_TOKEN/" /etc/contextforge/.env

# Option B: Update Kubernetes secret
kubectl create secret generic contextforge-vault \
  --from-literal=token=$NEW_TOKEN \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Rolling restart (zero downtime)
# If multiple instances behind load balancer:
systemctl restart contextforge@node1
sleep 30  # Wait for health check
systemctl restart contextforge@node2

# Or Kubernetes:
kubectl rollout restart deployment/contextforge

# 4. Verify new token works
curl -H "Authorization: Bearer <cf-user-token>" \
  https://contextforge.acme.com/health

# 5. Grace period: wait 1 hour for all instances to pick up new token

# 6. Revoke old token
vault token revoke <old-token>
```

**Expected duration:** 15 minutes  
**Downtime:** 0 (rolling restart)

#### Emergency Fallback: Vault → Database

**When:** Vault unavailable for >2 hours and cannot be restored quickly

**Steps:**
```bash
# 1. Switch all instances to database backend
export OAUTH_TOKEN_BACKEND=database
systemctl restart contextforge

# 2. Users will see "OAuth authorization required" on next tool call
#    → They re-authorize → tokens written to DB

# 3. When Vault restored: Run Phase 3 migration script to sync DB → Vault
python -m mcpgateway.scripts.migrate_tokens_to_vault
```

---

## UPDATE §10: Production Vault Setup (Add HA/DR Section)

**Add the following subsection after §10 Step 7:**

### §10.8 — High Availability & Disaster Recovery (Required for Production)

#### Vault HA Cluster (3-node minimum)

**vault.hcl configuration:**
```hcl
storage "postgresql" {
  connection_url = "postgres://vault:password@postgres-ha.acme.com:5432/vault?sslmode=require"
  ha_enabled     = "true"
  ha_table       = "vault_ha_locks"
  max_parallel   = "256"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/etc/vault.d/tls/vault.crt"
  tls_key_file  = "/etc/vault.d/tls/vault.key"
}

api_addr     = "https://vault.acme.com:8200"
cluster_addr = "https://vault-node1.internal:8201"
ui           = true
```

**Deployment:**
- 3 Vault nodes behind load balancer (active/standby/standby)
- Only one node active at a time (handles reads/writes)
- Standby nodes forward requests to active node
- If active node fails, standby promotes automatically (HA lock in Postgres)

#### PostgreSQL High Availability

**Option A (Recommended): Managed Service**
- AWS RDS Multi-AZ (automatic failover)
- Azure Database for PostgreSQL (HA mode)
- Google Cloud SQL (regional HA)

**Option B: Self-Managed**
- Patroni + etcd for leader election
- Streaming replication with synchronous commit
- pgBouncer connection pooling

**Connection pooling tuning:**
```sql
-- Vault requires ~10 connections per node (max_parallel / 25)
-- With 3 Vault nodes: 3 × 10 = 30 connections minimum
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET shared_buffers = '1GB';
```

#### Auto-Unseal (Phase 2 Requirement)

**Without auto-unseal:** Server restart requires manual unseal with 3/5 keys → downtime during incidents

**With auto-unseal:** Vault uses KMS to automatically unseal on startup

**AWS KMS Example:**
```hcl
seal "awskms" {
  region     = "us-west-2"
  kms_key_id = "arn:aws:kms:us-west-2:123456789012:key/vault-unseal"
}
```

**Setup:**
```bash
# 1. Create KMS key
aws kms create-key \
  --description "Vault auto-unseal key" \
  --tags TagKey=Application,TagValue=ContextForge

# 2. Grant Vault IAM role access
aws kms create-grant \
  --key-id <key-id> \
  --grantee-principal arn:aws:iam::123456789012:role/vault-role \
  --operations Encrypt Decrypt DescribeKey
```

**Benefits:**
- Vault auto-restarts after crash (no manual intervention)
- Eliminates unseal key management burden
- Required for production uptime SLA >99.9%

#### Backup & Disaster Recovery

**PostgreSQL Backup (Automated):**
```bash
#!/bin/bash
# /etc/cron.daily/vault-postgres-backup

pg_dump -h postgres-ha.acme.com -U vault \
  --format=custom \
  --file=/backups/vault-$(date +%Y%m%d-%H%M%S).dump \
  vault

# Upload to S3 with 90-day retention
aws s3 cp /backups/vault-$(date +%Y%m%d-*).dump \
  s3://acme-backups/vault/ \
  --storage-class GLACIER

# Local retention: 30 days
find /backups -name "vault-*.dump" -mtime +30 -delete
```

**Restore Procedure:**
```bash
# 1. Stop Vault cluster
systemctl stop vault

# 2. Restore Postgres
pg_restore -h postgres-ha.acme.com -U vault \
  --dbname=vault --clean \
  /backups/vault-20260707-140000.dump

# 3. Restart Vault (auto-unseal will unseal automatically)
systemctl start vault
```

**RTO (Recovery Time Objective):** 15 minutes  
**RPO (Recovery Point Objective):** 24 hours (daily backups)

---

## UPDATE §18: Open Questions → Architect Decisions

**Replace §18 with:**

### §18: Architect Decisions & Rationale

| Decision ID | Question | Decision | Rationale |
|-------------|----------|----------|-----------|
| **D1** | Should switching `database → vault` force users to re-authorize? | ✅ **Phase 1:** Manual re-authorization. **Phase 3:** Automated migration script. | Automated migration requires decrypt + gateway_id resolution logic. Building in Phase 1 delays release. Manual re-auth UX: user clicks link on next tool call → redirects to OAuth. |
| **D2** | Is static VAULT_TOKEN acceptable before Phase 2 AppRole? | ⚠️ **Yes for dev/staging only.** Production requires AppRole or Kubernetes SA auth (Phase 2 blocker). | Static tokens simplify early testing. Enterprise compliance mandates dynamic auth. Compromise: allow for non-prod, document limitation. |
| **D3** | Should `cleanup_expired_tokens()` log WARNING or DEBUG when no-op for Vault? | ✅ **WARNING level, logged once per process.** | Operators expect cleanup jobs to do something. WARNING educates: "Vault TTL is your responsibility." Log once to avoid spam. |
| **D4** | Multi-gateway virtual servers: UI prompt or auto-list? | ✅ **Auto-redirect if 1 gateway, selection page if N>1.** | 80% use case: single gateway → zero-click UX. 20% use case: multi-gateway → user selects. API clients use `?gateway_url=...` param. |

---

## ADD NEW §21: Performance Considerations

### Expected Latency Impact

| Operation | DatabaseTokenBackend | VaultTokenBackend | Overhead |
|-----------|---------------------|-------------------|----------|
| `store_tokens()` | ~5ms (local Postgres) | ~35ms (CF → Vault → Postgres) | +30ms (7x) |
| `get_user_token()` | ~3ms (SELECT + Fernet decrypt) | ~25ms (CF → Vault GET) | +22ms (8x) |
| `get_user_token()` with refresh | ~150ms (IdP call + DB update) | ~180ms (IdP call + Vault PUT) | +30ms |

**Network hops:**
- DatabaseTokenBackend: 1 hop (CF → Postgres)
- VaultTokenBackend: 2 hops (CF → Vault → Postgres)

### Throughput Considerations

**DatabaseTokenBackend bottleneck:**
- ContextForge database connection pool (default 200 connections)
- Typical: 200 conns × 333 req/sec/conn = ~66,000 token ops/sec (theoretical max)

**VaultTokenBackend bottleneck:**
- Vault's Postgres storage backend pool (default `max_parallel=128`)
- Vault API rate limits (per-node: ~1000 req/sec)
- 3-node Vault cluster: ~3000 req/sec aggregate

**Recommendation for high-traffic deployments (>500 tool calls/sec):**
1. Increase Vault `max_parallel` to 256 in vault.hcl
2. Scale Vault horizontally (5+ nodes)
3. Add Vault Performance Replication (Enterprise) for read scaling
4. Consider short-lived in-memory token cache in ContextForge (future optimization)

### When to Choose Each Backend

| Scenario | Recommended Backend | Reason |
|----------|---------------------|--------|
| Development / Testing | Either (Vault dev mode simpler) | Dev mode no persistence needed |
| Small deployment (<100 users) | Database | Lower latency, simpler ops |
| Enterprise / Regulated industry | Vault | Compliance, audit trail, centralized secrets |
| Multi-region deployment | Vault + Replication | Vault Enterprise handles geo-distribution |
| High throughput (>1000 req/sec) | Database or Vault + caching | Vault adds latency; cache mitigates |

---

## Summary of Changes

**Sections Updated:**
- ✅ §5: Interface now uses `gateway_id` (backward compatible)
- ✅ §6: Façade maintains existing signatures, backend resolves internally
- ✅ §10: Added HA/DR subsection (Vault cluster, Postgres HA, auto-unseal, backups)
- ✅ §18: Converted open questions to architect decisions

**Sections Added:**
- ✅ §19: Failure Modes & Recovery (error handling, retry logic)
- ✅ §20: Observability & Operations (metrics, logs, alerts, runbooks)
- ✅ §21: Performance Considerations (latency impact, throughput, recommendations)

**Next Steps:**
1. Integrate these sections into your HTML document
2. Circulate updated document for final architect sign-off
3. DevOps review §10.8 (HA/DR) and §20.4 (runbooks)
4. Security review §19 (error handling - no secret leakage)
5. Begin Phase 1 implementation after approval

---

**Document Version:** Supplement v1.0  
**Date:** 2026-07-07  
**Status:** Ready for integration into main HTML document
