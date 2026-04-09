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

## Step 5: Deploy with Helm (two-step install)

ContextForge requires a two-step install because Alembic database migrations through PgBouncer hang with multiple replicas. Start with 1 replica, let migration complete, then scale up.

**Step 5a: Install with 1 replica**

```bash
helm install contextforge charts/mcp-stack \
  -n contextforge \
  -f charts/mcp-stack/values-ocp-pgo.yaml \
  -f charts/mcp-stack/values-ocp-pgo-secrets.yaml \
  --set mcpContextForge.replicaCount=1
```

Wait for the single gateway pod to be **1/1 Ready**:

> **Note:** The install may report `INSTALLATION FAILED` due to registration hook timeouts.
> This is expected — the gateway pod still starts successfully. Verify with `oc get pods`.

```bash
oc get pods -n contextforge -l app=contextforge-mcp-stack-mcpgateway -w
# Wait until READY shows 1/1
```

**Step 5b: Scale to 3 replicas**

```bash
helm upgrade contextforge charts/mcp-stack \
  -n contextforge \
  -f charts/mcp-stack/values-ocp-pgo.yaml \
  -f charts/mcp-stack/values-ocp-pgo-secrets.yaml
```

Verify all pods are running:

```bash
oc get pods -n contextforge
# Expect:
#   3 gateway pods (1/1 Running)
#   1 NGINX pod (1/1 Running)
#   1 Redis pod (1/1 Running)
#   2 fast-time-server pods (1/1 Running)
#   1 fast-test-server pod (1/1 Running)
```

---

## Step 6: Post-install manual steps

These steps are needed until the Helm chart templates are updated to handle them automatically.

**Scale NGINX to 3 replicas** (the template currently hardcodes replicas to 1):

```bash
oc -n contextforge scale deploy/contextforge-mcp-stack-nginx --replicas=3
```

**Verify the gateway health:**

```bash
oc -n contextforge exec deploy/contextforge-mcp-stack-mcpgateway -- \
  curl -s http://localhost:4444/health | python3 -m json.tool
```

**Verify external access** (if Route is enabled):

```bash
ROUTE=$(oc -n contextforge get route contextforge -o jsonpath='{.spec.host}')
curl -sk https://$ROUTE/health
```

---

## Step 7: Register MCP servers

The Helm chart includes registration hook jobs, but if they timeout you can register manually.

First, port-forward to access the gateway API from your laptop:

```bash
oc -n contextforge port-forward deploy/contextforge-mcp-stack-mcpgateway 4444:4444 &
```

Then register the servers:

```bash
# Get a JWT token
TOKEN=$(oc -n contextforge exec deploy/contextforge-mcp-stack-mcpgateway -- \
  python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 60 \
  --secret "<your-jwt-key>")

# Register fast-test-server
curl -X POST http://localhost:4444/gateways \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"fast_test","url":"http://contextforge-mcp-stack-fast-test-server:8880/mcp","transport":"STREAMABLEHTTP"}'

# Register fast-time-server
curl -X POST http://localhost:4444/gateways \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"fast_time","url":"http://contextforge-mcp-stack-mcp-fast-time-server:80/http","transport":"STREAMABLEHTTP"}'

# Create a virtual server
curl -X POST http://localhost:4444/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"server":{"name":"Test Server","protocolVersion":"2024-11-05","visibility":"public"}}'

# Verify tools are registered
curl -s http://localhost:4444/tools -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
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

**Standardized benchmark configuration:**

The Helm chart deploys Locust with the following settings from `values-ocp-pgo.yaml`:

- 3 Locust workers (`testing.locust.worker.replicaCount: 3`)
- 125 users, 30/s spawn rate, 60s runtime
- ZeroMQ ports 5557/5558 included in the Locust Service (workers connect automatically)
- MCP_SERVER_ID passed via `--set` at install time

**1. Pass the virtual server ID at install time:**

```bash
# Get the virtual server UUID (after registration)
SERVER_ID=$(curl -s http://localhost:4444/servers \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")

# Include in helm install/upgrade
helm upgrade <release> charts/mcp-stack \
  -n <namespace> \
  -f charts/mcp-stack/values-ocp-pgo.yaml \
  -f charts/mcp-stack/values-ocp-pgo-secrets.yaml \
  --set testing.locust.mcpServerID=$SERVER_ID \
  --no-hooks
```

**2. Deploy the MCP protocol locustfile:**

The locustfile at `tests/loadtest/locustfile_mcp_protocol.py` needs two patches for OCP:
- Wrap `_load_env_file()` in `try/except (PermissionError, OSError)` (OCP restricted SCC blocks `Path.home()/.env`)
- Replace `import jwt` / `jwt.encode()` with stdlib `hmac/hashlib` JWT generation (pyjwt not available in Locust container)

```bash
# After patching the locustfile:
oc -n <namespace> create configmap <release>-mcp-stack-locust-script \
  --from-file=locustfile.py=tests/loadtest/locustfile_mcp_protocol.py \
  --dry-run=client -o yaml | oc replace -f -

# Restart Locust pods to pick up new locustfile
oc -n <namespace> delete pods -l app=<release>-mcp-stack-locust
oc -n <namespace> delete pods -l app=<release>-mcp-stack-locust-worker
```

**3. Run the benchmark:**

The benchmark starts automatically via the Locust web UI, or trigger via API:

```bash
curl -X POST http://locust:8089/swarm \
  -d 'user_count=125&spawn_rate=30&run_time=60s'
```

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
| Gateway pods stuck at 0/1 Running | Migration hang through PgBouncer. Ensure only 1 replica during first install. Scale to 3 after pod is Ready. |
| `ErrImagePull` on fast-test-server | Image pull auth failed. Grant pull access: `oc policy add-role-to-group system:image-puller system:serviceaccounts:<namespace> -n contextforge-images` |
| Redis PVC stuck in Pending | No dynamic PV provisioner. Set `redis.persistence.enabled: false` in values, or provision a PV manually. |
| Locust workers not connecting | Ensure `testing.enabled: true` in values. ZeroMQ ports 5557/5558 are included in the Locust Service template. If workers still fail, check DNS resolution to `<release>-mcp-stack-locust`. |
| Locust crashes with PermissionError | OCP restricted SCC blocks `Path.home()/.env`. Patch `_load_env_file()` with try/except. |
| `helm upgrade` fails with field conflicts | Manual `oc` patches create field manager conflicts. Use `helm uninstall` + `helm install` instead. |
| Route returns 503 | Gateway pods not Ready yet, or NGINX not scaled. Check `oc get pods` and scale NGINX to 3. |
| Rate limiter not blocking | Plugin mode is `permissive` (default). Change to `enforce` in the plugin ConfigMap and restart gateways. |

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
