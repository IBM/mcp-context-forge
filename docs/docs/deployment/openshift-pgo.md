# OpenShift with CrunchyData PGO (Experimental)

Deploy ContextForge on OpenShift using the **CrunchyData Postgres Operator (PGO)** for managed PostgreSQL. This approach uses the `mcp-stack` Helm chart with an OCP-specific values override file and provides a production-ready deployment with benchmarked MCP performance.

## Why use the CrunchyData PGO operator?

The Helm chart can deploy a standalone Postgres pod on its own, but for production workloads the CrunchyData PGO operator adds capabilities that a single Helm-managed pod cannot provide:

- **High availability** — automatic failover with a standby replica. If the primary Postgres pod goes down, PGO promotes the standby with no manual intervention and minimal downtime.
- **Automated backups** — pgBackRest handles WAL archiving and scheduled full/differential backups. Point-in-time recovery is built in.
- **Managed PgBouncer** — the operator deploys and configures PgBouncer as a sidecar, handling connection pooling, credential rotation, and health monitoring automatically.
- **Rolling updates** — Postgres minor version upgrades and config changes are applied without downtime.
- **Monitoring integration** — built-in Prometheus metrics exporter for Postgres and PgBouncer.

If you don't need HA or automated backups (dev/test, POCs, teams without cluster-admin access to install operators), see [openshift.md](openshift.md) for the manual deployment approach.

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
│  │  Session pool enabled  |  Cache TTLs 300s  |  7 plugins (permissive) │  │
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

- **`oc` CLI** with cluster access (developer or admin)
- **Helm** CLI installed locally
- **Ansible** installed locally:
  ```bash
  pip install ansible
  ansible-galaxy collection install kubernetes.core
  ```

---

## One-time cluster setup

These steps are performed once per cluster, not per deployment.

- **Cluster sizing** — use **OCP Large** on Fyre (or equivalent: 3 worker nodes, 16 CPU and 32Gi RAM each).
  Deployment alone requires ~20 CPU: 3 gateway pods (4 CPU each) + 3 NGINX pods (2 CPU each) + Redis (1 CPU) + system overhead.
  Adding Locust benchmark requires ~2 CPU extra: 1 master + 3 workers (500m each).
  OCP Medium (3 × 8 CPU) is insufficient — the third NGINX pod will stay `Pending`.
- **`nfs-client` StorageClass** available on the cluster (dynamic NFS provisioner for Postgres and Redis PVCs)
- **CrunchyData PGO operator** — install once cluster-wide (requires cluster-admin access, skips if already installed):
  ```bash
  make ocp-install-operator OCP_CLUSTER=<api-url>
  ```

---

## Prepare secrets

Create a secrets file at `charts/mcp-stack/profiles/ocp/values-pgo-secrets.yaml` (gitignored — never committed). This file is used for all deployments regardless of namespace:

```yaml
mcpContextForge:
  secret:
    JWT_SECRET_KEY: "<min 32 bytes, for signing JWT tokens>"
    AUTH_ENCRYPTION_SECRET: "<for encrypting stored secrets in DB>"
    BASIC_AUTH_PASSWORD: "<admin login password>"
    PLATFORM_ADMIN_PASSWORD: "<platform admin password>"
    REQUIRE_STRONG_SECRETS: "true"

testing:
  registration:
    jwt:
      secret: "<same as JWT_SECRET_KEY above>"
```

---

## Setup and deployment steps

The Make commands below wrap Ansible playbooks under the hood (`ansible/ocp/playbooks/`). You can also run the playbooks directly — see [ansible/ocp/README.md](https://github.com/IBM/mcp-context-forge/blob/main/ansible/ocp/README.md) for details.

**0. Create Docker Hub pull secret** (one-time per namespace, required to pull `redis:7` without hitting anonymous rate limits):

```bash
oc create secret docker-registry dockerhub-pull \
  --docker-server=docker.io \
  --docker-username=<your-dockerhub-username> \
  --docker-password=<your-dockerhub-password-or-token> \
  -n <namespace>
```

**1. Set up namespace and Postgres:**

```bash
make ocp-setup OCP_NS=<namespace>
```

Checks the PGO operator is installed, creates the namespace if needed, applies the PostgresCluster CR (PVCs use dynamic `nfs-client` provisioning), waits for Postgres to be Ready, and grants the required schema privileges. Safe to run multiple times.

**2. Deploy the full stack:**

```bash
make ocp-deploy OCP_NS=<namespace>
```

Runs `helm install` with the PGO values and secrets files. Deploys gateway (3 pods), NGINX (3 pods), Redis (PVC dynamically provisioned), and connects to the PGO-managed Postgres. Database migration runs as a `pre-install` hook directly to Postgres (bypasses PgBouncer for advisory lock safety). Locust is **not** deployed at this stage — it is enabled on demand by `ocp-benchmark-setup`.

**3. Run the MCP benchmark:**

```bash
make ocp-benchmark-setup OCP_NS=<namespace>
make ocp-benchmark OCP_NS=<namespace>
```

`ocp-benchmark-setup` enables Locust (1 master + 3 workers), waits for workers to schedule, auto-fetches the virtual server ID, and configures everything. If only some workers schedule due to CPU pressure, the test continues with whatever workers are available and prints a warning.

`ocp-benchmark` triggers the benchmark — defaults to 125 users, 30/s spawn, 60s. Override for heavier load:

```bash
make ocp-benchmark OCP_NS=<namespace> BENCH_USERS=500 BENCH_SPAWN=50     # heavy load
make ocp-benchmark OCP_NS=<namespace> BENCH_USERS=750 BENCH_SPAWN=75     # max throughput
```

Benchmark results (OCP Large, 3 gateway pods, 3 NGINX, PGO Postgres, 3 Locust workers):

> Results vary by cluster infrastructure (network topology, NFS performance, hypervisor density). The first benchmark run on a fresh deployment will show lower numbers as connection pools and caches warm up — run 2-3 times for stable results.

| Users | Spawn | RPS | Avg Latency | Failures |
|-------|-------|-----|-------------|----------|
| 125 | 30/s | 262–331 | 242–357ms | 0% |
| 300 | 30/s | 260–522 | 449–929ms | 0% |
| 500 | 50/s | 328–601 | 657–1275ms | 0% |
| 750 | 75/s | 300–669 | 1029–1888ms | 0–0.2% |

500 users is the recommended setting for heavy load testing — best balance of throughput and latency with 0% failures across all tested clusters.

**To uninstall and start over:**

```bash
make ocp-uninstall OCP_NS=<namespace>
```

Runs `helm uninstall` to remove the gateway, NGINX, Redis, Locust, and fast-time-server pods. The PostgresCluster (Postgres + PgBouncer + repo-host) and the namespace itself are preserved, so you can re-run `make ocp-deploy` without re-creating Postgres. Dynamically provisioned PVs are cleaned up automatically by the `nfs-client` provisioner based on the StorageClass reclaim policy.

Each Make target prompts for confirmation before running. The underlying Ansible playbooks can also be run directly for more control:

```bash
ansible-playbook ansible/ocp/playbooks/setup.yml -i ansible/ocp/inventory/cluster.yml
ansible-playbook ansible/ocp/playbooks/deploy.yml -i ansible/ocp/inventory/cluster.yml
ansible-playbook ansible/ocp/playbooks/benchmark.yml -i ansible/ocp/inventory/cluster.yml -e bench_users=500
```

For step-by-step details, troubleshooting, or if the Make commands don't work as expected, see the detailed steps below.

---

## Detailed Manual Steps

> The sections below are for manual control or troubleshooting. For most deployments, the quick setup and deployment steps above are sufficient.

---

### Step 1: Create namespace

```bash
oc new-project contextforge
# or use an existing namespace:
oc project contextforge
```

---

### Step 2: Install CrunchyData PGO operator

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

### Step 3: Create PostgresCluster

Apply the CrunchyData PostgresCluster CR. A tuned example is provided in the chart:

> The CR name (`metadata.name`) determines the generated secret name and service names.
> The provided example uses `gp-postgres` — adjust if you prefer a different name.

```bash
oc apply -n contextforge -f charts/mcp-stack/profiles/ocp/manifests/pgo-postgrescluster.yaml
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

### Step 4: Prepare values and secrets files

The chart includes an OCP-specific values override file: `charts/mcp-stack/profiles/ocp/values-pgo.yaml`

**Update it for your environment:**

1. Set the CrunchyData secret name (line ~289):
   ```yaml
   postgres:
     external:
       existingSecret: <your-pgo-secret-name>  # e.g. contextforge-postgres-pguser-admin
   ```

2. Create a local secrets file (never committed to git):
   ```bash
   cat > charts/mcp-stack/profiles/ocp/values-pgo-secrets.yaml << 'EOF'
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

> The committed `profiles/ocp/values-pgo.yaml` has placeholder secrets (`changeme`, `my-test-salt`).
> Real secrets are provided via the local `-secrets.yaml` file at deploy time, keeping
> credentials out of version control.

---

### Step 5: Deploy with Helm

A single `helm install` deploys the full stack. Database migration runs as a `pre-install` hook directly to Postgres (bypassing PgBouncer), so the schema is ready before gateway pods start.

```bash
helm install contextforge charts/mcp-stack \
  -n contextforge \
  -f charts/mcp-stack/profiles/ocp/values-pgo.yaml \
  -f charts/mcp-stack/profiles/ocp/values-pgo-secrets.yaml
```

Wait for pods to be ready:

```bash
oc get pods -n contextforge -w
# Expect:
#   3 gateway pods (1/1 Running)
#   3 NGINX pods (1/1 Running)
#   1 Redis pod (1/1 Running)
#   2 fast-time-server pods (1/1 Running)
```

Locust pods are **not** deployed at this stage — they are enabled on demand by `make ocp-benchmark-setup` (see "Running the MCP Benchmark" below).

Registration hooks run automatically — the fast-time server is registered and a virtual server is created.

---

### Step 6: Verify

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
│  │  Session pool enabled  |  Cache TTLs 300s  |  7 plugins (permissive) │  │
│  └───┬──────────┬──────────────────┬──────────────────┬────────────────┘  │
│      │          │                  │                   │                   │
│      │          ▼                          ▼                               │
│      │  ┌────────────────────┐  ┌────────────────────┐                    │
│      │  │  fast-time server   │  │  fast-time server   │                    │
│      │  │  Go, :80            │  │  Go, :80 (replica)  │                    │
│      │  │  get-time,          │  │                      │                    │
│      │  │  convert-time       │  │                      │                    │
│      │  └────────────────────┘  └────────────────────┘                    │
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

Locust is **off by default** in the OCP values file (`testing.locust.enabled: false`) so that `ocp-deploy` doesn't waste cluster resources on test pods. The Locust master and workers are enabled on demand by `make ocp-benchmark-setup`.

When enabled, Locust is configured with:

- 3 worker replicas (auto-connected via ZeroMQ)
- 125 users, 30/s spawn rate, 60s runtime
- `expectWorkers: 1` so the master starts as soon as 1 worker connects (additional workers join as they come up)
- OCP-patched locustfile deployed from `charts/mcp-stack/files/ocp/locustfile_mcp_protocol.py`

**1. Enable Locust and configure the server ID:**

```bash
make ocp-benchmark-setup OCP_NS=<namespace>
```

This is the recommended path. The target:
- Fetches a JWT token from inside the gateway pod
- Calls `/servers` to get the virtual server UUID created by the registration hooks
- Runs `helm upgrade` with `--set testing.locust.enabled=true --set testing.locust.mcpServerID=<uuid>`
- Waits up to 90s for the 3 Locust workers to schedule, polling every 10s
- If only some workers schedule due to CPU pressure, prints a warning explaining the impact and continues

If you prefer to do it manually, it's equivalent to:

```bash
SERVER_ID=$(oc -n <namespace> exec deploy/<release>-mcp-stack-mcpgateway -- \
  curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/servers | \
  python3 -c "import json,sys; print(next(s for s in json.load(sys.stdin) if s['name'] == 'Fast Time Server')['id'])")

helm upgrade <release> charts/mcp-stack \
  -n <namespace> \
  -f charts/mcp-stack/profiles/ocp/values-pgo.yaml \
  -f charts/mcp-stack/profiles/ocp/values-pgo-secrets.yaml \
  --set testing.locust.enabled=true \
  --set testing.locust.mcpServerID=$SERVER_ID
```

**2. Run the benchmark:**

```bash
# Default (125 users, 30/s spawn, 60s)
make ocp-benchmark OCP_NS=<namespace>

# Override for heavier load
make ocp-benchmark OCP_NS=<namespace> BENCH_USERS=500 BENCH_SPAWN=50
```

Results are printed automatically when the benchmark completes.

**Benchmark results (OCP 4.20, 3 gateway pods, 3 NGINX, PGO Postgres):**

| Config | Plugins Loaded | RPS | Avg Latency | Med Latency | Failures |
|--------|---------------|-----|-------------|-------------|----------|
| No plugins (all disabled) | 0 | 292 | 59ms | 44ms | 0% |
| 3 enforce only (others disabled) | 3 | 288 | 57ms | 44ms | 0% |

Plugins in enforce: RateLimiterPlugin (10,000/m), OutputLengthGuardPlugin (15K chars), SecretsDetectionPlugin (block on detection). Plugins add no meaningful overhead — 0% failures in both configurations.

---

## Enabling Plugins

By default, `pluginConfig.enabled: true` in the OCP values file. The plugins are configured in the plugin config section of `profiles/ocp/values-pgo.yaml`.

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
| Redis PVC stuck in Pending | Check the `nfs-client` StorageClass exists (`oc get sc nfs-client`). If the dynamic provisioner isn't installed, see your cluster admin. |
| Locust workers not connecting | Locust is off by default in the OCP values file. Run `make ocp-benchmark-setup` to enable it (sets `testing.locust.enabled=true`). If still failing, check DNS resolution to `<release>-mcp-stack-locust` — ZeroMQ ports 5557/5558 are included in the Locust Service template. |
| Only some Locust workers scheduled | Cluster CPU is at high allocation. The benchmark setup target waits 90s and continues with whatever workers are available. RPS may be slightly lower than the 3-worker baseline. Free CPU on worker nodes if you want all 3. |
| `helm upgrade` fails with field conflicts | Manual `oc` patches create field manager conflicts. Use `helm uninstall` + `helm install` instead. |
| Route returns 503 | Gateway pods not Ready yet. Check `oc get pods` and wait for 1/1 Running. |
| Rate limiter not blocking | Plugin mode is `permissive` (default). Change to `enforce` in the plugin ConfigMap and restart gateways. |
| Benchmark shows high failure rate | Check `testing.locust.mcpServerID` matches an existing virtual server. Get the correct ID from `/servers` API. |

---

## Key Configuration

The `profiles/ocp/values-pgo.yaml` file includes these OCP-specific settings:

| Setting | Value | Why |
|---------|-------|-----|
| `mcpContextForge.image.pullPolicy` | `Always` | Ensure latest image is pulled |
| `mcpContextForge.hpa.enabled` | `false` | Prevent HPA from fighting manual scaling during benchmarking |
| `migration.hookPhase` | `pre-install,pre-upgrade` | Migration runs before gateway pods start (Postgres already exists via PGO) |
| `migration.hostKey` | `host` | Migration connects directly to Postgres, bypassing PgBouncer for advisory lock safety |
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
