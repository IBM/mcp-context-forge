# OCP Deployment — Standalone Postgres + PgBouncer (No Operator)

Deploys ContextForge on OpenShift using the Helm chart's built-in
Postgres and PgBouncer. No CrunchyData PGO operator required.

## Architecture

```
                  ┌─────────────┐
                  │  OCP Route  │  (reencrypt TLS)
                  └──────┬──────┘
                         │
                  ┌──────▼──────┐
                  │    NGINX    │  UBI9 nginx-126
                  │   (port 8080/8443)
                  └──────┬──────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
    │  Gateway  │ │  Gateway  │ │  Gateway  │  3 pods × 8 CPU
    │  (4444)   │ │  (4444)   │ │  (4444)   │  Gunicorn 8 workers
    └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
          │              │              │
          └──────────────┼──────────────┘
                         │
                  ┌──────▼──────┐
                  │  PgBouncer  │  crunchydata/crunchy-pgbouncer
                  │  (6432)     │  transaction pooling
                  └──────┬──────┘
                         │
                  ┌──────▼──────┐      ┌───────────┐
                  │  Postgres   │      │   Redis   │
                  │  (5432)     │      │  (6379)   │
                  └─────────────┘      └───────────┘
```

## Prerequisites

- OpenShift 4.x cluster with `restricted-v2` SCC
- `oc` CLI authenticated as cluster admin
- Helm 3.x
- Namespace created: `oc new-project gp-context-forge`
- Docker Hub pull secret (if needed): `oc create secret docker-registry dockerhub-pull ...`

## Files

| File | Purpose |
|------|---------|
| `values-ocp.yaml` | Main values override (committed) |
| `values-ocp-secrets.yaml` | Secret overrides — **not committed** (gitignored by `*-secrets.yaml`) |
| `DEPLOY-OCP-STANDALONE.md` | This guide |

## Step 1: Create Secrets File

```bash
cat > charts/mcp-stack/values-ocp-secrets.yaml <<'EOF'
mcpContextForge:
  secret:
    JWT_SECRET_KEY: "<your-jwt-secret-min-32-bytes>"
    AUTH_ENCRYPTION_SECRET: "<your-encryption-secret>"
    BASIC_AUTH_PASSWORD: "<your-admin-password>"
    PLATFORM_ADMIN_PASSWORD: "<your-admin-password>"
    REQUIRE_STRONG_SECRETS: "true"

postgres:
  credentials:
    password: "<your-postgres-password>"

testing:
  registration:
    jwt:
      secret: "<same-jwt-secret-as-above>"
EOF
```

## Step 2: Install (Single Replica for Migration)

```bash
helm install gp-context-forge charts/mcp-stack \
  -n gp-context-forge \
  -f charts/mcp-stack/values-ocp.yaml \
  -f charts/mcp-stack/values-ocp-secrets.yaml \
  --set mcpContextForge.replicaCount=1 \
  --no-hooks
```

Wait for Postgres, PgBouncer, and migration to complete:

```bash
oc get pods -n gp-context-forge -w
# Wait until migration job shows Completed and gateway is 1/1 Running
```

## Step 3: Scale to Full Replicas

```bash
helm upgrade gp-context-forge charts/mcp-stack \
  -n gp-context-forge \
  -f charts/mcp-stack/values-ocp.yaml \
  -f charts/mcp-stack/values-ocp-secrets.yaml \
  --no-hooks
```

This scales the gateway to 3 replicas (as set in `values-ocp.yaml`).

## Step 4: Register MCP Servers

Port-forward and generate a JWT:

```bash
oc -n gp-context-forge port-forward svc/gp-context-forge-mcp-stack-mcpgateway 4444:80 &

export JWT=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 10080 \
  --secret "<your-jwt-secret>")
```

Register the fast-time-server:

```bash
curl -s -X POST http://localhost:4444/gateways \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "fast-time",
    "url": "http://gp-context-forge-mcp-stack-mcp-fast-time-server.gp-context-forge.svc.cluster.local/sse"
  }' | jq .
```

## Step 5: Verify

```bash
# Gateway health
oc exec -n gp-context-forge deploy/gp-context-forge-mcp-stack-mcpgateway \
  -- curl -s http://localhost:4444/health | jq .status
# Expect: "healthy"

# PgBouncer traffic
oc logs -n gp-context-forge deploy/gp-context-forge-mcp-stack-pgbouncer --tail=5
# Expect: stats lines showing xacts/s > 0

# All pods running
oc get pods -n gp-context-forge -l app.kubernetes.io/instance=gp-context-forge
```

---

## Images Used

| Component | Image | Notes |
|-----------|-------|-------|
| Gateway | `ghcr.io/ibm/mcp-context-forge:latest` | |
| Postgres | `docker.io/library/postgres:17` | Handles non-root on OCP |
| PgBouncer | `registry.connect.redhat.com/crunchydata/crunchy-pgbouncer:latest` | Red Hat certified |
| NGINX | `registry.access.redhat.com/ubi9/nginx-126:latest` | Red Hat UBI, S2I bypass |
| Redis | `docker.io/library/redis:7-alpine` | |

## Key Differences from PGO Approach

| | PGO (values-ocp-pgo.yaml) | Standalone (values-ocp.yaml) |
|--|---------------------------|------------------------------|
| Postgres | CrunchyData operator manages it | Helm chart Deployment (single pod) |
| PgBouncer | Operator-managed sidecar | Helm chart Deployment with crunchy-pgbouncer |
| HA / Failover | Automatic (operator) | None (single pod) |
| Backups | WAL archiving via pgBackRest | Manual |
| Operator required | Yes (PGO v5) | No |
| Setup complexity | Higher (install operator + CR) | Lower (single helm install) |

Both approaches can coexist in the same namespace — different service names,
different secrets, no conflicts. Gateway connects to whichever DATABASE_URL
its values file configures.

---

## Issues Encountered and Fixes

### 1. CrunchyData PgBouncer CrashLoopBackOff (no config file)

**Symptom:** PgBouncer pod starts and immediately exits with no logs.

**Root cause:** The `crunchy-pgbouncer` image is raw PgBouncer — it does not
accept env vars like `edoburu/pgbouncer`. It requires a `pgbouncer.ini` config
file at `/etc/pgbouncer/pgbouncer.ini`. The default config has:
- `listen_addr = localhost` (not reachable from other pods)
- Empty `[databases]` section
- `logfile = /var/log/pgbouncer/pgbouncer.log` (permission denied under OCP arbitrary UID)
- No `userlist.txt`

**Fix:** Created `configmap-pgbouncer.yaml` template that generates a proper
`pgbouncer.ini` with all pool settings from values, plus a `userlist.txt`.
Added `pgbouncer.useConfigFile: true` and `pgbouncer.command` values to
control mounting. Template changes are backwards-compatible — existing
`edoburu/pgbouncer` users are unaffected (env var path still works).

Key config changes in the generated `pgbouncer.ini`:
```ini
listen_addr = 0.0.0.0          # reachable from other pods
logfile = /tmp/pgbouncer.log   # writable under OCP restricted SCC
pidfile = /tmp/pgbouncer.pid   # writable under OCP restricted SCC
* = host=<postgres-svc> port=5432  # wildcard database routing
```

### 2. Readiness Probe Failure (no pg_isready)

**Symptom:** PgBouncer pod stays `0/1 Running` — readiness probe always fails.
Gateway cannot reach PgBouncer through the Service (no endpoints).

**Root cause:** The default PgBouncer probes use `pg_isready -h localhost -p 6432`.
The `crunchy-pgbouncer` image is minimal and does not include `pg_isready`.

**Fix:** Override probes in `values-ocp.yaml` to use TCP socket checks:
```yaml
pgbouncer:
  probes:
    readiness:
      type: tcp
      port: 6432
```

### 3. Password Authentication Failed

**Symptom:** PgBouncer logs show
`password authentication failed for user "admin"` and
`closing because: login failed`.

**Root cause:** With `auth_type = trust`, PgBouncer does not capture the
client's password. When it opens a server connection to Postgres, it cannot
forward the credentials, so Postgres rejects the connection.

**Fix:** Changed to `auth_type = plain` in the ConfigMap template and included
the Postgres password in `userlist.txt`:
```ini
auth_type = plain
auth_file = /etc/pgbouncer/userlist.txt
```

### 4. Helm Release Stuck in "failed" (registration hook timeout)

**Symptom:** `helm list` shows `STATUS: failed` even though all core pods
are running. Cannot `helm upgrade`.

**Root cause:** The `register-fast-test` post-install hook job fails because
`fast-test-server` has `ImagePullBackOff` (OCP shared image registry auth).
Helm marks the entire release as failed.

**Fix:** Use `--no-hooks` to skip registration jobs during install:
```bash
helm install ... --no-hooks
```
Registration can be done manually via port-forward + curl after install.

### 5. Official Postgres Image on OCP

**Non-issue:** The `postgres:17` image works under OCP `restricted-v2` SCC.
When running as non-root (which OCP forces), the entrypoint script skips
`gosu`/`chown` and initializes directly. With `emptyDir` volumes the data
directory is writable by the arbitrary UID.

---

## Test Results

### Deployment: April 8, 2026

**Cluster:** OCP 4.20, namespace `gp-context-forge`

**Configuration:**
- 3 gateway pods (8 CPU, Gunicorn 8 workers each)
- 1 NGINX pod (UBI9, 4 CPU)
- 1 PgBouncer pod (crunchy-pgbouncer, transaction mode)
- 1 Postgres pod (postgres:17, emptyDir storage)
- 1 Redis pod (7-alpine, persistent)

**Result:** All pods 1/1 Running. Gateway health check returns `{"status":"healthy"}`.
PgBouncer successfully routing connections from all 3 gateway pods to Postgres.

```
Gateway (3 pods)  ──►  PgBouncer (crunchy)  ──►  Postgres (standalone)
    ✓ 1/1 Running         ✓ 1/1 Running           ✓ 1/1 Running
```

### MCP Protocol Benchmark: April 8, 2026

**Locustfile:** `tests/loadtest/locustfile_mcp_protocol.py` (patched for OCP)

**Parameters:** 125 users, 30/s spawn rate, 60s, 1 Locust worker, 3 gateway pods

**Results (fresh-session MCP operations):**

| Endpoint | Requests | Failures | Avg Latency | Med Latency |
|----------|----------|----------|-------------|-------------|
| MCP initialize | 1,849 | 0 (0%) | 31ms | 22ms |
| MCP tools/list | 1,849 | 0 (0%) | 38ms | 32ms |
| **Total** | **3,698** | **0 (0%)** | **35ms** | **28ms** |

**317 RPS, 0% failures, 35ms avg latency**

**Comparison with PGO approach:**

| Metric | Standalone | PGO |
|--------|-----------|-----|
| RPS | 317 | 350 |
| Avg latency | 35ms | 227ms |
| Median latency | 28ms | 100ms |
| Failures | 0% | 0% |

The standalone stack delivers comparable RPS to the PGO approach with
significantly lower latency.

### MCP Protocol Benchmark with Plugins: April 9, 2026

**Plugins in enforce mode:** RateLimiterPlugin (10000/m), OutputLengthGuardPlugin,
SecretsDetectionPlugin. Other plugins (PIIFilter, RetryWithBackoff,
EncodedExfilDetector, UnifiedPDP) in permissive.

**Parameters:** 125 users, 30/s spawn rate, 60s, 1 Locust worker, 3 gateway pods

**Results (fresh-session MCP operations):**

| Endpoint | Requests | Failures | Avg Latency | Med Latency |
|----------|----------|----------|-------------|-------------|
| MCP initialize | 2,474 | 0 (0%) | 36ms | 24ms |
| MCP tools/list | 2,473 | 0 (0%) | 45ms | 35ms |
| **Total** | **4,947** | **0 (0%)** | **40ms** | **32ms** |

**306 RPS, 0% failures, 40ms avg latency**

**Plugin overhead comparison (standalone stack):**

| Config | Pods | RPS | Avg Latency | Med Latency | Failures |
|--------|------|-----|-------------|-------------|----------|
| Without plugins | 3 | 317 | 35ms | 28ms | 0% |
| With plugins (enforce) | 3 | 306 | 40ms | 32ms | 0% |

Plugins add ~5ms latency with **0% failures**. Consistent with the PGO
benchmark observation that plugins do not degrade performance.
