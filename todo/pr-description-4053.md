## Summary

Adds OpenShift (OCP) deployment support using an externally managed PostgreSQL operator (CrunchyData PGO). The standard Helm chart assumes root container access and Helm-managed Postgres/PgBouncer, which are blocked by OpenShift's restricted-v2 SCC. This PR makes the chart OCP-compatible with backwards-compatible template changes and provides a tested OCP values file with MCP benchmark results.

All template changes are gated by values that default to off — non-OCP deployments are unaffected.

The deployment was validated on a 3-worker OCP 4.20 cluster with 3 gateway replicas, 3 NGINX proxies, CrunchyData-managed PostgreSQL with PgBouncer, and Redis. The MCP benchmark achieved **371 RPS with 0% failures** using the Python MCP core with session pooling enabled.

Full deployment guide: [`docs/docs/deployment/openshift-pgo.md`](https://github.com/IBM/mcp-context-forge/blob/ocp-mcp-benchmark-python/docs/docs/deployment/openshift-pgo.md)

---

## Gaps closed

**Gap 1 (HIGH)** — NGINX default image requires root (port 80, pid file): Pod fails to start under restricted-v2 SCC. Fixed by making `containerPort` configurable (defaults to 80) and adding `pid /tmp/nginx.pid;` to the NGINX ConfigMap template. OCP deployments set `containerPort: 8080` via values.

**Gap 2 (HIGH)** — No support for externally managed Postgres: Can't connect to operator-provided Postgres via existing secret. Fixed by using `postgres.external.enabled` with configurable secret key mappings (`hostKey`, `portKey`, `databaseKey`, `userKey`, `passwordKey`) that read from the CrunchyData PGO-generated secret.

**Gap 3 (HIGH)** — No OpenShift Route for external access: OCP doesn't use Ingress by default. Fixed by adding `templates/route.yaml` with support for both edge and re-encrypt TLS termination. Gated by `route.enabled` (default: false). In re-encrypt mode, OCP's Service CA auto-generates and rotates TLS certificates via the `serving-cert-secret-name` annotation — no manual certificate management needed.

**Gap 4 (MEDIUM)** — No TLS support on NGINX proxy: Re-encrypt termination requires NGINX to accept TLS connections. Fixed by adding a TLS server block to the NGINX ConfigMap, TLS volume mounts in the deployment, and HTTPS port in the service — all gated by `nginxProxy.tls.enabled` (default: false).

**Gap 5 (MEDIUM)** — Redis inline comments break config parser: Redis `save` directives had inline comments (`save 900 1 # comment`) which Redis silently ignores, causing RDB persistence to not work. Fixed by removing the inline comments.

**Gap 6 (MEDIUM)** — No OCP performance baseline: No benchmark results to measure against. Fixed with documented results showing 371 RPS / 0% failures with Python MCP core and session pooling.

---

## Architecture

### OCP deployment topology

```text
                         ┌─────────────┐
                         │   Client     │
                         │  (laptop /   │
                         │   browser)   │
                         └──────┬───────┘
                                │ HTTPS
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  OCP Cluster                                                              │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  OCP Router (HAProxy)                                                │  │
│  │  TLS termination: edge (simple) or re-encrypt (encrypted in cluster)│  │
│  │  Certs auto-managed by OCP Service CA in re-encrypt mode            │  │
│  └────────────────────────────────┬────────────────────────────────────┘  │
│                                   │ HTTP (:80) or HTTPS (:8443)           │
│                                   ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  NGINX Proxy                                                         │  │
│  │  3 pods × 4 CPU  |  Port 8080 (HTTP), 8443 (TLS)  |  32K conns     │  │
│  └────────────────────────────────┬────────────────────────────────────┘  │
│                                   │ HTTP (K8s Service, round-robin)        │
│                                   ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  ContextForge Gateway                                                │  │
│  │  3 pods × 8 CPU  |  Gunicorn 8 workers  |  Python MCP core          │  │
│  │  Session pool enabled  |  Cache TTLs 300s  |  Plugins disabled       │  │
│  └───┬──────────┬──────────────────┬──────────────────┬────────────────┘  │
│      │          │                  │                   │                   │
│      │          ▼                  ▼                   ▼                   │
│      │  ┌─────────────────┐  ┌────────────────┐  ┌────────────────┐      │
│      │  │  fast-test       │  │  fast-time     │  │  fast-time     │      │
│      │  │  server          │  │  server        │  │  server        │      │
│      │  │  Rust, :8880     │  │  Go, :80       │  │  Go, :80       │      │
│      │  │  echo, stats,    │  │  get-time,     │  │  (replica 2)   │      │
│      │  │  get-system-time │  │  convert-time  │  │                │      │
│      │  └─────────────────┘  └────────────────┘  └────────────────┘      │
│      │                                                                    │
│      │  Gateway also connects to:                                         │
│      │                                                                    │
│      ├──────────────────────────────────┐                                 │
│      │                                  │                                 │
│      ▼                                  ▼                                 │
│  ┌──────────────────────────────────┐  ┌────────────────────────────┐    │
│  │  CrunchyData PGO                 │  │  Redis                      │    │
│  │                                  │  │  2 CPU, 2Gi                 │    │
│  │  PostgreSQL        PgBouncer     │  │                             │    │
│  │  4 CPU, 8Gi        pool: 600    │  │  Auth cache, tool cache,    │    │
│  │  shared_buf 512MB  max DB: 700   │  │  session pool, registry     │    │
│  │  sync_commit: off  max cli: 5000 │  │                             │    │
│  │                                  │  │  (Gateway reads/writes      │    │
│  │  (users, tools, servers,         │  │   on every request for      │    │
│  │   sessions, migrations)          │  │   auth + tool resolution)   │    │
│  └──────────────────────────────────┘  └────────────────────────────┘    │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

<details>
<summary>MCP benchmark test setup</summary>

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  OCP Cluster                                                              │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  Locust (benchmark)                                                  │  │
│  │  Master (4 CPU, 2Gi)  +  3 Workers (2 CPU each)                     │  │
│  │  125 concurrent users, distributed mode                              │  │
│  └────────────────────────────────┬────────────────────────────────────┘  │
│                                   │ HTTP (port 80, plain text)             │
│                                   ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  NGINX Proxy                                                         │  │
│  │  3 pods × 4 CPU  |  Port 8080  |  32K worker connections            │  │
│  └────────────────────────────────┬────────────────────────────────────┘  │
│                                   │ HTTP (K8s Service, round-robin)        │
│                                   ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  ContextForge Gateway                                                │  │
│  │  3 pods × 8 CPU  |  Gunicorn 8 workers  |  Python MCP core          │  │
│  │  Session pool enabled  |  Cache TTLs 300s  |  Plugins disabled       │  │
│  └───┬──────────┬──────────────────┬──────────────────┬────────────────┘  │
│      │          │                  │                   │                   │
│      │          ▼                  ▼                   ▼                   │
│      │  ┌─────────────────┐  ┌────────────────┐  ┌────────────────┐      │
│      │  │  fast-test       │  │  fast-time     │  │  fast-time     │      │
│      │  │  server          │  │  server        │  │  server        │      │
│      │  │  Rust, :8880     │  │  Go, :80       │  │  Go, :80       │      │
│      │  │  echo, stats,    │  │  get-time,     │  │  (replica 2)   │      │
│      │  │  get-system-time │  │  convert-time  │  │                │      │
│      │  └─────────────────┘  └────────────────┘  └────────────────┘      │
│      │                                                                    │
│      │  Gateway also connects to:                                         │
│      │                                                                    │
│      ├──────────────────────────────────┐                                 │
│      │                                  │                                 │
│      ▼                                  ▼                                 │
│  ┌──────────────────────────────────┐  ┌────────────────────────────┐    │
│  │  CrunchyData PGO                 │  │  Redis                      │    │
│  │                                  │  │  2 CPU, 2Gi                 │    │
│  │  PostgreSQL        PgBouncer     │  │                             │    │
│  │  4 CPU, 8Gi        pool: 600    │  │  Auth cache, tool cache,    │    │
│  │  shared_buf 512MB  max DB: 700   │  │  session pool, registry     │    │
│  │  sync_commit: off  max cli: 5000 │  │                             │    │
│  │                                  │  │  (Gateway reads/writes      │    │
│  │  (users, tools, servers,         │  │   on every request for      │    │
│  │   sessions, migrations)          │  │   auth + tool resolution)   │    │
│  └──────────────────────────────────┘  └────────────────────────────┘    │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

</details>

---

## Test results

<details>
<summary>OCP environment setup</summary>

**Prerequisites:**
- OCP cluster with CrunchyData PGO operator installed
- `nfs-client` StorageClass available (dynamic NFS provisioner)
- Local secrets override file created (`values-ocp-pgo-secrets.yaml`, gitignored — see values file header for expected keys)

**Deploy via Make commands:**
```bash
make ocp-setup OCP_NS=<namespace>           # namespace + PostgresCluster CR + schema privileges
make ocp-deploy OCP_NS=<namespace>          # helm install (migration runs as pre-install hook)
```

This deploys 3 gateway pods, 3 NGINX pods, Redis, and fast-time-server. PVCs are dynamically provisioned via `nfs-client`. Migration runs as a `pre-install` hook directly to Postgres (bypasses PgBouncer). Registration hooks auto-register the fast-time server and create a virtual server.

For detailed steps including CrunchyData PGO setup, see [`docs/docs/deployment/openshift-pgo.md`](https://github.com/IBM/mcp-context-forge/blob/ocp-mcp-benchmark-python/docs/docs/deployment/openshift-pgo.md).

</details>

<details>
<summary>MCP benchmark — in-cluster (Locust, 125 users, 60s)</summary>

**Test setup:**
```bash
make ocp-benchmark-setup OCP_NS=<namespace>   # enables Locust, fetches server ID, waits for workers
make ocp-benchmark OCP_NS=<namespace>          # triggers the benchmark
```

The Helm chart deploys the OCP-patched locustfile from `charts/mcp-stack/tests/locustfile_mcp_protocol_ocp.py`, configures ZeroMQ ports in the Locust Service, and injects MCP_SERVER_ID — all automatically via values. No manual patching needed.

**Results:**

| Metric | Value |
|--------|-------|
| Total requests | ~19,200 |
| **RPS** | **372** |
| Avg response | 261ms |
| **Failures** | **0%** |

Configuration: 3 gateway pods (8 CPU, Gunicorn 8 workers), 3 NGINX pods, CrunchyData Postgres, Redis, Locust (1 master + 3 workers), all MCP protocol user classes.

Path: Locust → HTTP (port 80) → NGINX → Gateway → MCP servers

</details>

<details>
<summary>MCP benchmark — external from laptop (HTTPS via OCP Route, 125 users, 60s)</summary>

Same MCP benchmark running from a laptop over VPN. Tests the full external access path including TLS.

**Test setup:**
```bash
# Prerequisites: Locust and pyjwt installed locally
pip install locust pyjwt

# Get the Route URL and virtual server ID
ROUTE_HOST=$(oc -n <namespace> get route <release>-mcp-stack -o jsonpath='{.spec.host}')
SERVER_ID=$(curl -sk https://$ROUTE_HOST/servers \
  -H "Authorization: Bearer <token>" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
```

**Run:**
```bash
MCP_SERVER_ID=$SERVER_ID \
JWT_SECRET_KEY=<your-jwt-key> \
locust -f tests/loadtest/locustfile_mcp_protocol.py \
  --host=https://$ROUTE_HOST \
  --users=125 --spawn-rate=30 --run-time=60s \
  --headless --only-summary
```

**Results:**

| TLS Mode | Total Requests | RPS | Avg | p50 | p95 | p99 | Failures |
|----------|---------------|-----|-----|-----|-----|-----|----------|
| Re-encrypt | 11,627 | **194** | 179ms | 170ms | 210ms | 610ms | **0%** |
| Edge | 11,529 | **193** | 187ms | 170ms | 260ms | 620ms | **0%** |

Path: Laptop → HTTPS → OCP Router (TLS termination) → NGINX → Gateway → MCP servers

</details>

<details>
<summary>In-cluster vs External comparison</summary>

| Source | RPS | p50 Latency | Path | Failures |
|--------|-----|-------------|------|----------|
| In-cluster (Locust) | **357** | 94ms | HTTP → NGINX → Gateway | 0% |
| Laptop (external) | **194** | 170ms | HTTPS → OCP Router → NGINX → Gateway | 0% |

The ~80ms latency difference is VPN + internet network distance. Both edge and re-encrypt TLS modes perform identically from the laptop — the network latency dominates over the extra TLS hop.

**Both paths: 0% failures, fully functional end-to-end.**

</details>

<details>
<summary>Rate limiter correctness test (enforce mode, 3 gateway pods)</summary>

Validates that the RateLimiterPlugin correctly enforces per-user limits across multiple gateway pods using Redis as a shared backend.

**Configuration:**

| Setting | Value |
|---------|-------|
| Algorithm | `fixed_window` (default) |
| Backend | `redis` (shared across 3 pods) |
| Limit | `by_user: "30/m"` (30 requests per minute per user) |
| Mode | `enforce` (patched from default `permissive`) |

**Test setup:**

Requires `pluginConfig.enabled: true` and a redeploy. Then patch the RateLimiterPlugin to enforce mode:

```bash
# Patch plugin ConfigMap — change RateLimiterPlugin mode to enforce
oc -n <namespace> get cm <release>-mcp-stack-gateway-plugins -o json > /tmp/plugins.json
# Edit: change "mode": "permissive" to "mode": "enforce" for RateLimiterPlugin
oc apply -f /tmp/plugins.json
oc -n <namespace> delete pods -l app=<release>-mcp-stack-mcpgateway

# Verify
oc -n <namespace> logs deploy/<release>-mcp-stack-mcpgateway | grep "RateLimiter.*mode"
# Expect: Loaded plugin: RateLimiterPlugin (mode: PluginMode.ENFORCE)
```

Deploy rate limiter locustfile (needs OCP patches — see [deployment guide](https://github.com/IBM/mcp-context-forge/blob/ocp-mcp-benchmark-python/docs/docs/deployment/openshift-pgo.md)):

```bash
oc -n <namespace> create configmap <release>-mcp-stack-locust-script \
  --from-file=locustfile.py=tests/loadtest/locustfile_rate_limiter_backend_correctness.py \
  --dry-run=client -o yaml | oc replace -f -

oc -n <namespace> set env deploy/<release>-mcp-stack-locust \
  JWT_SECRET_KEY=<your-jwt-key> MCP_SERVER_ID=<virtual-server-uuid>
oc -n <namespace> set env deploy/<release>-mcp-stack-locust-worker \
  JWT_SECRET_KEY=<your-jwt-key> MCP_SERVER_ID=<virtual-server-uuid>

oc -n <namespace> delete pods -l app=<release>-mcp-stack-locust
oc -n <namespace> delete pods -l app=<release>-mcp-stack-locust-worker
```

**Run:** 1 user at 1 req/s (60 req/min = 2x the 30/min limit) for 2 minutes:
```bash
curl -X POST http://locust:8089/swarm \
  -d 'user_count=1&spawn_rate=1&run_time=120s'
```

**Results:**

| Endpoint | Requests | Description |
|----------|----------|-------------|
| MCP tools/call [allowed] | **60** | Requests within the rate limit |
| MCP tools/call [rate-limited] | **60** | Requests blocked by rate limiter |
| MCP initialize | 1 | Session setup |

**Result: 50/50 split — Redis backend correctly enforcing shared rate limits across all 3 gateway pods.** 0% infrastructure failures.

</details>

<details>
<summary>Rate limiter Redis capacity test (100 users, prompt pre-fetch path)</summary>

Tests the Redis rate limiter hot path throughput under concurrent load. 100 users hitting the prompt pre-fetch path at 0.25 req/s each, avoiding downstream MCP tool invocation to isolate the rate limiter path.

**Configuration:**

| Setting | Value |
|---------|-------|
| Algorithm | `fixed_window` (default) |
| Backend | `redis` (shared across 3 pods) |
| Limit | `by_user: "30/m"` (30 requests per minute per user) |
| Mode | `enforce` (patched from default `permissive`) |

**Test setup:**

Requires `pluginConfig.enabled: true` and RateLimiterPlugin in enforce mode (same as correctness test above). Deploy the capacity locustfile:

```bash
# Deploy capacity locustfile (needs OCP patches — see deployment guide)
oc -n <namespace> create configmap <release>-mcp-stack-locust-script \
  --from-file=locustfile.py=tests/loadtest/locustfile_rate_limiter_redis_capacity.py \
  --dry-run=client -o yaml | oc replace -f -

oc -n <namespace> set env deploy/<release>-mcp-stack-locust \
  JWT_SECRET_KEY=<your-jwt-key> MCP_SERVER_ID=<virtual-server-uuid>
oc -n <namespace> set env deploy/<release>-mcp-stack-locust-worker \
  JWT_SECRET_KEY=<your-jwt-key> MCP_SERVER_ID=<virtual-server-uuid>

oc -n <namespace> delete pods -l app=<release>-mcp-stack-locust
oc -n <namespace> delete pods -l app=<release>-mcp-stack-locust-worker
```

**Run:** 100 users, 0.25 req/s each, 2 minutes:
```bash
curl -X POST http://locust:8089/swarm \
  -d 'user_count=100&spawn_rate=10&run_time=120s'
```

**Results:**

| Endpoint | Requests | % | Avg Latency | RPS |
|----------|----------|---|-------------|-----|
| Prompt execute [rate-limited] | 1,640 | 96.5% | 185ms | 18.6 |
| Prompt execute [allowed] | 60 | 3.5% | 604ms | 1.4 |
| **Total** | **1,700** | **0% failures** | **200ms** | **20.0** |

**Result: Rate limiter correctly enforces per-user limits at scale. Redis backend sustained 20 RPS with 200ms average latency under 100 concurrent users.**

</details>

<details>
<summary>Rate limiter algorithm scale test (100 unique users, 3 algorithms)</summary>

100 unique users, each with their own rate limit key in Redis, sending tools/call at 1 req/s. Tests correctness across all three algorithms: `fixed_window`, `sliding_window`, `token_bucket`.

**Configuration:**

| Setting | Value |
|---------|-------|
| Algorithm | `fixed_window` / `sliding_window` / `token_bucket` (one per run) |
| Backend | `redis` (shared across 3 pods) |
| Limit | `by_user: "30/m"` (30 requests per minute per user) |
| Mode | `enforce` |

**Test setup:**

Requires `pluginConfig.enabled: true` and RateLimiterPlugin in enforce mode (same as correctness test above). Deploy the scale locustfile:

```bash
# Deploy scale locustfile (needs OCP patches — see deployment guide)
oc -n <namespace> create configmap <release>-mcp-stack-locust-script \
  --from-file=locustfile.py=tests/loadtest/locustfile_rate_limiter_scale.py \
  --dry-run=client -o yaml | oc replace -f -

oc -n <namespace> set env deploy/<release>-mcp-stack-locust \
  JWT_SECRET_KEY=<your-jwt-key> MCP_SERVER_ID=<virtual-server-uuid>
oc -n <namespace> set env deploy/<release>-mcp-stack-locust-worker \
  JWT_SECRET_KEY=<your-jwt-key> MCP_SERVER_ID=<virtual-server-uuid>

oc -n <namespace> delete pods -l app=<release>-mcp-stack-locust
oc -n <namespace> delete pods -l app=<release>-mcp-stack-locust-worker
```

Between algorithm runs, flush Redis rate limit keys and patch the algorithm:
```bash
# Flush rate limit keys
oc -n <namespace> exec deploy/<release>-mcp-stack-redis -- \
  redis-cli -a <redis-password> EVAL "local keys = redis.call('keys', 'rl:*'); for i=1,#keys do redis.call('del', keys[i]) end; return #keys" 0

# Patch algorithm in plugin ConfigMap
oc -n <namespace> get cm <release>-mcp-stack-gateway-plugins -o json > /tmp/plugins.json
# Edit: change algorithm: "fixed_window" to "sliding_window" (or "token_bucket")
oc apply -f /tmp/plugins.json
oc -n <namespace> delete pods -l app=<release>-mcp-stack-mcpgateway
```

**Run:** 100 users, 1 req/s each, 2 minutes:
```bash
curl -X POST http://locust:8089/swarm \
  -d 'user_count=100&spawn_rate=20&run_time=120s'
```

**Results:**

| Algorithm | Allowed | Rate-limited | Total | RPS | Avg Latency | Failures |
|-----------|---------|-------------|-------|-----|-------------|----------|
| fixed_window | 3,029 (70%) | 1,189 (28%) | 4,318 | 80.6 | 897ms | 0% |
| sliding_window | 3,429 (78%) | 860 (20%) | 4,389 | 90.8 | 999ms | 0% |
| token_bucket | 1,735 (54%) | 1,424 (44%) | 3,209 | 48.4 | 260ms | 0% |

**Result: All three algorithms pass with 0% infrastructure failures.** `token_bucket` is the strictest (44% blocked), `sliding_window` the most permissive (20% blocked), `fixed_window` in the middle (28% blocked).

</details>

<details>
<summary>MCP benchmark — with plugins enforced (3 gateway pods, 125 users, 60s)</summary>

**Plugin configuration:**

RateLimiterPlugin (enforce)
- `by_user`: 10,000/m (~167 req/s per user)
- `by_tenant`: 100,000/m
- `backend`: Redis (shared across 3 pods)
- `algorithm`: fixed_window (default)

OutputLengthGuardPlugin (enforce)
- `max_chars`: 15,000
- `min_chars`: 0
- `strategy`: truncate
- `ellipsis`: "..."

SecretsDetectionPlugin (enforce)
- `block_on_detection`: true
- `min_findings_to_block`: 1
- Detects: AWS keys, Google API keys, Slack tokens, private key blocks, JWTs, hex secrets
- `redact`: false

Other plugins (PIIFilterPlugin, RetryWithBackoffPlugin, EncodedExfilDetector, UnifiedPDPPlugin) disabled.

Rate limit is set high (10,000/m per user) to measure plugin pipeline overhead without triggering rate limiting on benchmark traffic.

**Test setup:**

```bash
# Patch plugin ConfigMap — set 3 plugins to enforce, disable the rest
oc -n <namespace> get cm <release>-mcp-stack-gateway-plugins -o json > /tmp/plugins.json
# Edit: set RateLimiterPlugin, OutputLengthGuardPlugin, SecretsDetection mode to "enforce"
# Edit: set RateLimiterPlugin by_user to "10000/m", by_tenant to "100000/m"
# Edit: set PIIFilterPlugin, RetryWithBackoffPlugin, EncodedExfilDetector, UnifiedPDPPlugin mode to "disabled"
oc apply -f /tmp/plugins.json

# Restart gateway pods to pick up new config
oc -n <namespace> delete pods -l app=<release>-mcp-stack-mcpgateway

# Verify only 3 plugins loaded
oc -n <namespace> logs deploy/<release>-mcp-stack-mcpgateway | grep "Loaded plugin"
# Expect: RateLimiterPlugin (ENFORCE), OutputLengthGuardPlugin (ENFORCE), SecretsDetection (ENFORCE)
```

**Run:**
```bash
curl -X POST http://locust:8089/swarm \
  -d 'user_count=125&spawn_rate=30&run_time=60s'
```

**Results:**

| Endpoint | Requests | Failures | Avg | Med |
|----------|----------|----------|-----|-----|
| MCP tools/list | 4,137 | 0 (0%) | 66ms | 52ms |
| MCP initialize [churn] | 2,495 | 0 (0%) | 37ms | 24ms |
| MCP tools/list [churn] | 2,494 | 0 (0%) | 45ms | 35ms |
| MCP prompts/list | 2,268 | 0 (0%) | 63ms | 49ms |
| MCP resources/list | 2,239 | 0 (0%) | 60ms | 46ms |
| MCP tools/list [rapid] | 1,274 | 0 (0%) | 63ms | 51ms |
| MCP resources/templates/list | 776 | 0 (0%) | 61ms | 46ms |
| MCP ping | 530 | 0 (0%) | 50ms | 37ms |
| MCP tools/list [stress] | 400 | 0 (0%) | 69ms | 53ms |
| MCP ping [stress] | 133 | 0 (0%) | 54ms | 36ms |
| MCP initialize | 113 | 0 (0%) | 127ms | 110ms |
| **TOTAL** | **16,859** | **0 (0%)** | **57ms** | **44ms** |

**288 RPS, 0% failures, 57ms avg latency**

Configuration: 3 gateway pods (8 CPU, Gunicorn 8 workers), 1 NGINX pod, CrunchyData Postgres + PgBouncer, Redis, Locust 1 master + 1 worker.

</details>

<details>
<summary>Plugin overhead comparison</summary>

| Config | Plugins Loaded | RPS | Avg Latency | Med Latency | Failures |
|--------|---------------|-----|-------------|-------------|----------|
| No plugins (all disabled) | 0 | 292 | 59ms | 44ms | 0% |
| 3 enforce only (others disabled) | 3 | 288 | 57ms | 44ms | 0% |

RateLimiter, OutputLengthGuard, and SecretsDetection in enforce mode add no meaningful overhead — **292 vs 288 RPS, identical median latency, 0% failures in both configurations.**

</details>

<details>
<summary>RPS scaling with user count (125–750 users, 3 gateway pods)</summary>

The benchmark supports configurable user count via `BENCH_USERS`, `BENCH_SPAWN`, and `BENCH_RUNTIME`:

```bash
# Default (125 users, 30/s spawn, 60s)
make ocp-benchmark OCP_NS=<namespace>

# Medium load (300 users)
make ocp-benchmark OCP_NS=<namespace> BENCH_USERS=300 BENCH_SPAWN=30

# Heavy load (500 users)
make ocp-benchmark OCP_NS=<namespace> BENCH_USERS=500 BENCH_SPAWN=50

# Max throughput (750 users)
make ocp-benchmark OCP_NS=<namespace> BENCH_USERS=750 BENCH_SPAWN=75
```

**Scaling results (3 gateway pods, 3 NGINX, PGO Postgres, 1 Locust master + 3 workers):**

| Users | Spawn Rate | RPS | Avg Latency | Med Latency | Failures | Command |
|-------|-----------|-----|-------------|-------------|----------|---------|
| 125 | 30/s | 331 | 242ms | 110ms | 0% | `make ocp-benchmark OCP_NS=<ns>` |
| 300 | 30/s | 522 | 449ms | 210ms | 0% | `make ocp-benchmark OCP_NS=<ns> BENCH_USERS=300 BENCH_SPAWN=30` |
| 500 | 50/s | 601 | 657ms | 320ms | 0% | `make ocp-benchmark OCP_NS=<ns> BENCH_USERS=500 BENCH_SPAWN=50` |
| 750 | 75/s | 669 | 1,029ms | 480ms | 0% | `make ocp-benchmark OCP_NS=<ns> BENCH_USERS=750 BENCH_SPAWN=75` |

The gateway saturates around 670 RPS with the current 3-pod configuration. 500 users is the best balance of throughput (601 RPS) and latency (320ms median) with 0% failures.

</details>

---

## Limitations

1. **Database migration** — the migration step runs as a `pre-install` hook directly to Postgres (bypasses PgBouncer) so that schema creation and advisory locks work correctly on fresh databases. Once migration completes, all gateway traffic flows through PgBouncer as normal. Requires Postgres to be running before `helm install`, which is handled by `make ocp-setup`.

2. **Pod-to-pod network overhead** — MCP benchmark shows 371 RPS on OCP vs 512 RPS on Colima (Python). The gap is from K8s Service routing across multiple pod hops — inherent to distributed deployments on Kubernetes. Further optimizations and fine-tuning (NGINX keepalive, TCP settings, worker scaling) may improve these numbers.

3. **Rust MCP runtime** — This PR validates the Python MCP core. Rust MCP runtime (`RUST_MCP_MODE=full`) with multi-pod session affinity will be addressed in a separate PR.

Closes #4052
