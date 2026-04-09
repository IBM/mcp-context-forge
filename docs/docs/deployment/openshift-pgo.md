# OpenShift with CrunchyData PGO

Deploy ContextForge on OpenShift using the **CrunchyData Postgres Operator (PGO)** for managed PostgreSQL. This approach uses the `mcp-stack` Helm chart with an OCP-specific values override file and provides a production-ready deployment with benchmarked MCP performance.

## Why use the CrunchyData PGO operator?

The Helm chart can deploy a standalone Postgres pod on its own, but for production workloads the CrunchyData PGO operator adds capabilities that a single Helm-managed pod cannot provide:

- **High availability** — automatic failover with a standby replica. If the primary Postgres pod goes down, PGO promotes the standby with no manual intervention and minimal downtime.
- **Automated backups** — pgBackRest handles WAL archiving and scheduled full/differential backups. Point-in-time recovery is built in.
- **Managed PgBouncer** — the operator deploys and configures PgBouncer as a sidecar, handling connection pooling, credential rotation, and health monitoring automatically.
- **Rolling updates** — Postgres minor version upgrades and config changes are applied without downtime.
- **Monitoring integration** — built-in Prometheus metrics exporter for Postgres and PgBouncer.

If you don't need HA or automated backups (dev/test, POCs, teams without cluster-admin access to install operators), see [openshift.md](openshift.md) for the manual approach or use the chart's built-in Postgres via `values-ocp.yaml`.

For the manual YAML deployment approach (without Helm or PGO), see [openshift.md](openshift.md).

---

<details>
<summary>Deployment topology</summary>

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
│  │  Session pool enabled  |  Cache TTLs 300s  |  Plugins configurable   │  │
│  └───┬──────────┬──────────────────┬──────────────────┬────────────────┘  │
│      │          │                  │                   │                   │
│      │          ▼                  ▼                   ▼                   │
│      │  ┌─────────────────┐  ┌────────────────┐  ┌────────────────┐      │
│      │  │  MCP servers    │  │  MCP servers    │  │  MCP servers    │      │
│      │  │  (registered)   │  │  (registered)   │  │  (registered)   │      │
│      │  └─────────────────┘  └────────────────┘  └────────────────┘      │
│      │                                                                    │
│      │  Gateway also connects to:                                         │
│      │                                                                    │
│      ├──────────────────────────────────┐                                 │
│      │                                  │                                 │
│      ▼                                  ▼                                 │
│  ┌──────────────────────────────────┐  ┌────────────────────────────┐    │
│  │  CrunchyData PGO                 │  │  Redis                      │    │
│  │                                  │  │  Auth cache, tool cache,    │    │
│  │  PostgreSQL        PgBouncer     │  │  session pool, registry     │    │
│  │  (managed by       (connection   │  │                             │    │
│  │   PGO operator)     pooling)     │  │                             │    │
│  └──────────────────────────────────┘  └────────────────────────────┘    │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

</details>

---

## Prerequisites

- **OCP cluster** with `oc` CLI access (developer or admin)
- **CrunchyData PGO operator** installed from OperatorHub
- **Helm 3** CLI installed locally
- **Persistent storage** for PostgreSQL (dynamic StorageClass or manually provisioned PV)
- Redis persistence is optional. If no PV is available, set in your values file: `redis.persistence.enabled: false`

---

## Step 1: Create namespace

```bash
oc new-project contextforge
# or use an existing namespace:
oc project contextforge
```

---

## Step 2: Install CrunchyData PGO operator

Install from OperatorHub in the OCP web console:

1. Navigate to **Operators → OperatorHub**
2. Search for **Crunchy Postgres for Kubernetes**
3. Install to **All namespaces** (or your specific namespace)
4. Wait for the operator to be ready

Verify:

```bash
oc get csv | grep crunchy
# Should show: Succeeded
```

---

## Step 3: Create PostgresCluster

Apply the CrunchyData PostgresCluster CR. A tuned example is provided in the chart:

> The CR name (`metadata.name`) determines the generated secret name and service names.
> The provided example uses `gp-postgres` — adjust if you prefer a different name.

```bash
oc apply -n contextforge -f charts/mcp-stack/crunchydata-postgres-cr.yaml
```

Wait for the Postgres pods to be ready:

```bash
oc get pods -n contextforge -l postgres-operator.crunchydata.com/cluster
# Expect: instance pod (4/4 Running), pgbouncer pod (2/2 Running), repo-host pod (2/2 Running)
```

The operator creates a secret with the database credentials. Note the secret name — you'll need it in the values file:

```bash
oc get secrets -n contextforge | grep pguser
# Example: gp-postgres-pguser-admin
```

The secret name follows the pattern `<cr-name>-pguser-<username>`. If you used the provided CR (`name: gp-postgres`), the secret will be `gp-postgres-pguser-admin`.

---

## Step 4: Prepare values and secrets files

The chart includes an OCP-specific values override file: `charts/mcp-stack/values-ocp-pgo.yaml`

**Update it for your environment:**

1. Set the CrunchyData secret name (line ~289):
   ```yaml
   postgres:
     external:
       existingSecret: <your-pgo-secret-name>  # e.g. contextforge-postgres-pguser-admin
   ```

2. Create a local secrets file (never committed to git):
   ```bash
   cat > charts/mcp-stack/values-ocp-pgo-secrets.yaml << 'EOF'
   mcpContextForge:
     secret:
       JWT_SECRET_KEY: "<your-strong-jwt-key-at-least-32-chars>"
       AUTH_ENCRYPTION_SECRET: "<your-strong-encryption-key-at-least-32-chars>"
       BASIC_AUTH_PASSWORD: "<your-admin-password>"
       PLATFORM_ADMIN_PASSWORD: "<your-admin-password>"
       REQUIRE_STRONG_SECRETS: "true"

   testing:
     registration:
       jwt:
         secret: "<same-jwt-key-as-above>"
   EOF
   ```

   Replace the placeholder values with your actual secrets.

> The committed `values-ocp-pgo.yaml` has placeholder secrets (`changeme`, `my-test-salt`).
> Real secrets are provided via the local `-secrets.yaml` file at deploy time, keeping
> credentials out of version control.

---

## Step 5: Deploy with Helm

A single `helm install` deploys the full stack — gateway pods acquire an advisory lock internally to serialize migration, so no two-step install is needed.

```bash
helm install contextforge charts/mcp-stack \
  -n contextforge \
  -f charts/mcp-stack/values-ocp-pgo.yaml \
  -f charts/mcp-stack/values-ocp-pgo-secrets.yaml
```

Wait for pods to be ready:

```bash
oc get pods -n contextforge -w
# Expect:
#   3 gateway pods (1/1 Running)
#   3 NGINX pods (1/1 Running)
#   1 Redis pod (1/1 Running)
#   2 fast-time-server pods (1/1 Running)
#   1 Locust master + 3 workers (1/1 Running)
```

Registration hooks run automatically — the fast-time server is registered and a virtual server is created.

---

## Step 6: Verify

**Gateway health:**

```bash
oc -n contextforge exec deploy/contextforge-mcp-stack-mcpgateway -- \
  curl -s http://localhost:4444/health | python3 -m json.tool
```

**External access** (if Route is enabled):

```bash
ROUTE=$(oc -n contextforge get route contextforge -o jsonpath='{.spec.host}')
curl -sk https://$ROUTE/health
```

**Registered servers:**

```bash
TOKEN=$(oc -n contextforge exec deploy/contextforge-mcp-stack-mcpgateway -- \
  python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 60 \
  --secret "<your-jwt-key>")

curl -s http://localhost:4444/servers -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## Running the MCP Benchmark

To validate the deployment with an MCP protocol benchmark using Locust.

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
│  │                                  │  │  Auth cache, tool cache,    │    │
│  │  PostgreSQL        PgBouncer     │  │  session pool, registry     │    │
│  └──────────────────────────────────┘  └────────────────────────────┘    │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

</details>

The Helm chart deploys Locust with the MCP protocol locustfile and standardized configuration from `values-ocp-pgo.yaml`:

- 3 Locust workers (auto-connected via ZeroMQ)
- 125 users, 30/s spawn rate, 60s runtime
- OCP-patched locustfile deployed from `charts/mcp-stack/tests/locustfile_mcp_protocol_ocp.py`

**1. Pass the virtual server ID:**

After the initial install (Step 5), registration hooks create the virtual server. Get its ID and update the deployment:

```bash
# Get the virtual server UUID
SERVER_ID=$(oc -n <namespace> exec deploy/<release>-mcp-stack-mcpgateway -- \
  curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/servers | \
  python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")

# Update Locust with the server ID
helm upgrade <release> charts/mcp-stack \
  -n <namespace> \
  -f charts/mcp-stack/values-ocp-pgo.yaml \
  -f charts/mcp-stack/values-ocp-pgo-secrets.yaml \
  --set testing.locust.mcpServerID=$SERVER_ID
```

**2. Run the benchmark:**

```bash
make benchmark-ocp OCP_NS=<namespace>
```

Results appear in the Locust web UI or pod logs after ~60s.

**Benchmark results (OCP 4.20, 3 gateway pods, 3 NGINX, PGO Postgres):**

| Config | Plugins Loaded | RPS | Avg Latency | Med Latency | Failures |
|--------|---------------|-----|-------------|-------------|----------|
| No plugins (all disabled) | 0 | 292 | 59ms | 44ms | 0% |
| 3 enforce only (others disabled) | 3 | 288 | 57ms | 44ms | 0% |

Plugins in enforce: RateLimiterPlugin (10,000/m), OutputLengthGuardPlugin (15K chars), SecretsDetectionPlugin (block on detection). Plugins add no meaningful overhead — 0% failures in both configurations.

---

## Enabling Plugins

By default, `pluginConfig.enabled: false` in the values file. To enable plugins:

1. Set `pluginConfig.enabled: true` in `values-ocp-pgo.yaml`
2. Redeploy (uninstall + two-step install)
3. Plugins load from the plugin config in the values file

The following plugins are included:

| Plugin | Default Mode | Description |
|--------|-------------|-------------|
| PIIFilterPlugin | permissive | Detects and masks PII |
| RateLimiterPlugin | permissive | Per-user/tenant rate limiting via Redis |
| RetryWithBackoffPlugin | permissive | Automatic retry on transient failures |
| OutputLengthGuardPlugin | permissive | Enforces output length limits |
| SecretsDetectionPlugin | permissive | Detects secrets/tokens in outputs |
| EncodedExfilDetectorPlugin | permissive | Detects encoded exfiltration patterns |
| UnifiedPDPPlugin | permissive | Policy decision point for access control |

To enforce a plugin, change its `mode` from `"permissive"` to `"enforce"` in the plugin config section of the values file.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Gateway pods stuck at 0/1 Running | Check `oc logs` for DB connectivity. Verify PGO Postgres and PgBouncer pods are Running. |
| Gateway pod Pending | Insufficient CPU on worker nodes. Check `oc describe pod` for scheduling errors. Free resources from other namespaces or reduce CPU requests. |
| Redis PVC stuck in Pending | No dynamic PV provisioner. Set `redis.persistence.enabled: false` in values, or provision a PV manually. |
| Locust workers not connecting | Ensure `testing.enabled: true` in values. ZeroMQ ports 5557/5558 are included in the Locust Service template. If workers still fail, check DNS resolution to `<release>-mcp-stack-locust`. |
| `helm upgrade` fails with field conflicts | Manual `oc` patches create field manager conflicts. Use `helm uninstall` + `helm install` instead. |
| Route returns 503 | Gateway pods not Ready yet. Check `oc get pods` and wait for 1/1 Running. |
| Rate limiter not blocking | Plugin mode is `permissive` (default). Change to `enforce` in the plugin ConfigMap and restart gateways. |
| Benchmark shows high failure rate | Check `testing.locust.mcpServerID` matches an existing virtual server. Get the correct ID from `/servers` API. |

---

## Key Configuration

The `values-ocp-pgo.yaml` file includes these OCP-specific settings:

| Setting | Value | Why |
|---------|-------|-----|
| `mcpContextForge.image.pullPolicy` | `Always` | Ensure latest image is pulled |
| `mcpContextForge.hpa.enabled` | `false` | Prevent HPA from fighting manual scaling during benchmarking |
| `postgres.external.enabled` | `true` | Connect to CrunchyData PGO instead of Helm-managed Postgres |
| `pgbouncer.enabled` | `false` | CrunchyData provides its own PgBouncer |
| `nginxProxy.enabled` | `true` | NGINX proxy layer for load balancing |
| `nginxProxy.replicaCount` | `3` | Match gateway replica count |
| `nginxProxy.containerPort` | `8080` | Unprivileged port (restricted SCC) |
| `nginxProxy.tls.enabled` | `true` | TLS for re-encrypt Route termination |
| `route.enabled` | `true` | OpenShift Route for external access |
| `MCP_SESSION_POOL_ENABLED` | `true` | Reuse MCP sessions to backends (critical for performance) |
| `TRANSPORT_TYPE` | `streamablehttp` | MCP Streamable HTTP transport |

---

## Further Reading

- [OpenShift manual deployment (without Helm)](openshift.md)
- [Helm chart deployment](helm.md)
- [CrunchyData PGO documentation](https://access.crunchydata.com/documentation/postgres-operator/latest/)
- [OpenShift Route documentation](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/networking/configuring-routes)
- [OpenShift restricted-v2 SCC](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/authentication_and_authorization/managing-pod-security-policies)
