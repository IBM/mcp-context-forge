# ⚙️ IBM Code Engine

This guide covers two supported deployment paths for the **MCP Gateway**:

1. **Makefile automation** - a single-command workflow that wraps `ibmcloud` CLI.
2. **Manual IBM Cloud CLI** - the raw commands the Makefile executes, for fine-grained control.

---

## 1 - Prerequisites

| Requirement          | Details                                                            |
| -------------------- | ------------------------------------------------------------------ |
| IBM Cloud account    | [Create one](https://cloud.ibm.com/registration) if needed         |
| Docker **or** Podman | Builds the production container image locally                      |
| IBM Cloud CLI ≥ 2.16 | Installed automatically with `make ibmcloud-cli-install`           |
| Code Engine project  | Create or select one in the IBM Cloud console                      |
| `.env` file          | Runtime secrets & config for the gateway                           |
| `.env.ce` file       | Deployment credentials & metadata for Code Engine / Container Reg. |

---

## 2 - Environment files

Both files are already in **`.gitignore`**.
Template named **`.env.example`** **`.env.ce.example`** and are included; copy them:

```bash
cp .env.example .env         # runtime settings (inside the container)
cp .env.ce.example .env.ce   # deployment credentials (CLI only)
```

### `.env` - runtime settings

This file is **mounted into the container** (via `--env-file=.env`), so its keys live inside Code Engine at runtime. Treat it as an application secret store.

```bash
# ─────────────────────────────────────────────────────────────────────────────
#  Core gateway settings
# ─────────────────────────────────────────────────────────────────────────────
AUTH_REQUIRED=true
# Generate once:  openssl rand -hex 32
JWT_SECRET_KEY=eef5e9f70ca7fe6f9677ad2acaf4d32c55e9d98e9cb74299b33f5c5d1a3c8ef

HOST=0.0.0.0
PORT=4444


# ─────────────────────────────────────────────────────────────────────────────
#  Database configuration  - choose ONE block
# ─────────────────────────────────────────────────────────────────────────────

## (A) Local SQLite  (good for smoke-tests / CI only)
## --------------------------------------------------
## - SQLite lives on the container's ephemeral file system.
## - On Code Engine every new instance starts fresh; scale-out, restarts or
##   deploys will wipe data.  **Not suitable for production.**
## - If you still need file persistence, attach Code Engine's file-system
##   mount or an external filesystem / COS bucket.
#CACHE_TYPE=database
#DATABASE_URL=sqlite:////tmp/mcp.db


## (B) Managed PostgreSQL on IBM Cloud  (recommended for staging/production)
## --------------------------------------------------------------------------
## - Provision an IBM Cloud Databases for PostgreSQL instance (see below).
## - Use the service credentials to build the URL.
## - sslmode=require is mandatory for IBM Cloud databases.
CACHE_TYPE=database
DATABASE_URL=postgresql+psycopg://pguser:pgpass@my-pg-host.databases.appdomain.cloud:32727/mcpgwdb?sslmode=require
#            │ │      │                                   │           │
#            │ │      │                                   │           └─ database name
#            │ │      │                                   └─ hostname:port
#            │ │      └─ password
#            │ └─ username
#            └─ scheme
```

The `JWT_SECRET_KEY` variable is used to generate a Bearer token used to access the APIs.
To access the APIs you need to generate your JWT token using the same `JWT_SECRET_KEY`, for example:

```bash
# Generate a one-off token for the default admin user
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com)
echo ${MCPGATEWAY_BEARER_TOKEN} # Check that the key was generated
```

### `.env.ce` - Code Engine deployment settings

These keys are **only** consumed by Makefile / CLI. They never reach the running container.

```bash
# ─────────────────────────────────────────────────────────────────────────────
#  IBM Cloud / Code Engine deployment variables
# ─────────────────────────────────────────────────────────────────────────────
IBMCLOUD_REGION=us-south
IBMCLOUD_RESOURCE_GROUP=default
IBMCLOUD_PROJECT=my-codeengine-project
IBMCLOUD_CODE_ENGINE_APP=mcpgateway

# Image details
IBMCLOUD_IMAGE_NAME=us.icr.io/myspace/mcpgateway:latest  # target in IBM Container Registry
IBMCLOUD_IMG_PROD=mcpgateway/mcpgateway                  # local tag produced by Make

# Authentication
IBMCLOUD_API_KEY=***your-api-key***    # leave blank to use SSO flow at login

# Resource combo - see https://cloud.ibm.com/docs/codeengine?topic=codeengine-mem-cpu-combo
IBMCLOUD_CPU=1                         # vCPU for the container
IBMCLOUD_MEMORY=4G                     # Memory (must match a valid CPU/MEM pair)

# Registry secret in Code Engine (first-time creation is automated)
IBMCLOUD_REGISTRY_SECRET=my-regcred
```

> **Tip:** run `make ibmcloud-check-env` to verify every required `IBMCLOUD_*` key is present in `.env.ce`.

---

## 3 - Workflow A - Makefile targets

| Target                      | Action it performs                                                                   |
| --------------------------- | ------------------------------------------------------------------------------------ |
| **`podman`** / **`docker`** | Build the production image (`$IBMCLOUD_IMG_PROD`).                                   |
| `ibmcloud-cli-install`      | Install IBM Cloud CLI + **container-registry** and **code-engine** plugins.          |
| `ibmcloud-check-env`        | Ensure all `IBMCLOUD_*` vars exist in `.env.ce`; abort if any are missing.           |
| `ibmcloud-login`            | `ibmcloud login` - uses API key or interactive SSO.                                  |
| `ibmcloud-ce-login`         | `ibmcloud ce project select --name $IBMCLOUD_PROJECT`.                               |
| `ibmcloud-list-containers`  | Show ICR images and existing Code Engine apps.                                       |
| `ibmcloud-tag`              | `podman tag $IBMCLOUD_IMG_PROD $IBMCLOUD_IMAGE_NAME`.                                |
| `ibmcloud-push`             | `ibmcloud cr login` + `podman push` to ICR.                                          |
| `ibmcloud-deploy`           | Create **or** update the app, set CPU/MEM, attach registry secret, expose port 4444. |
| `ibmcloud-ce-status`        | `ibmcloud ce application get` - see route URL, revisions, health.                    |
| `ibmcloud-ce-logs`          | `ibmcloud ce application logs --follow` - live log stream.                           |
| `ibmcloud-ce-rm`            | Delete the application entirely.                                                     |

**Typical first deploy**

```bash
make ibmcloud-check-env
make ibmcloud-cli-install
make ibmcloud-login
make ibmcloud-ce-login
make podman            # or: make docker
make ibmcloud-tag
make ibmcloud-push
make ibmcloud-deploy
```

**Redeploy after code changes**

```bash
make podman ibmcloud-tag ibmcloud-push ibmcloud-deploy
```

---

## 4 - Workflow B - Manual IBM Cloud CLI

```bash
# 1 - Install CLI + plugins
curl -fsSL https://clis.cloud.ibm.com/install/linux | sh
ibmcloud plugin install container-registry -f
ibmcloud plugin install code-engine      -f

# 2 - Login
ibmcloud login --apikey "$IBMCLOUD_API_KEY" -r "$IBMCLOUD_REGION" -g "$IBMCLOUD_RESOURCE_GROUP"
ibmcloud resource groups # list resource groups

# 3 - Target Code Engine project
ibmcloud ce project list # list current projects
ibmcloud ce project select --name "$IBMCLOUD_PROJECT"

# 4 - Build + tag image
podman build -t "$IBMCLOUD_IMG_PROD" .
podman tag "$IBMCLOUD_IMG_PROD" "$IBMCLOUD_IMAGE_NAME"

# 5 - Push image to ICR
ibmcloud cr login
ibmcloud cr namespaces       # Ensure your namespace exists
podman push "$IBMCLOUD_IMAGE_NAME"
ibmcloud cr images # list images

# 6 - Create registry secret (first time)
ibmcloud ce registry create-secret --name "$IBMCLOUD_REGISTRY_SECRET" \
    --server "$(echo "$IBMCLOUD_IMAGE_NAME" | cut -d/ -f1)" \
    --username iamapikey --password "$IBMCLOUD_API_KEY"
ibmcloud ce secret list # list every secret (generic, registry, SSH, TLS, etc.)
ibmcloud ce secret get --name "$IBMCLOUD_REGISTRY_SECRET"         # add --decode to see clear-text values

# 7 - Deploy / update
if ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP" >/dev/null 2>&1; then
  ibmcloud ce application update --name "$IBMCLOUD_CODE_ENGINE_APP" \
      --image "$IBMCLOUD_IMAGE_NAME" \
      --cpu "$IBMCLOUD_CPU" --memory "$IBMCLOUD_MEMORY" \
      --registry-secret "$IBMCLOUD_REGISTRY_SECRET"
else
  ibmcloud ce application create --name "$IBMCLOUD_CODE_ENGINE_APP" \
      --image "$IBMCLOUD_IMAGE_NAME" \
      --cpu "$IBMCLOUD_CPU" --memory "$IBMCLOUD_MEMORY" \
      --port 4444 \
      --registry-secret "$IBMCLOUD_REGISTRY_SECRET"
fi

# 8 - Status & logs
ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP"
ibmcloud ce application events --name "$IBMCLOUD_CODE_ENGINE_APP"
ibmcloud ce application get   --name "$IBMCLOUD_CODE_ENGINE_APP"
ibmcloud ce application logs  --name "$IBMCLOUD_CODE_ENGINE_APP" --follow
```

---

## 5 - Accessing the gateway

```bash
ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP" --output url
```

Open the returned URL (e.g.
`https://mcpgateway.us-south.codeengine.appdomain.cloud/admin`) and log in with the basic-auth credentials from `.env`.

Test the API endpoints with the generated `MCPGATEWAY_BEARER_TOKEN`:

```bash
# Generate a one-off token for the default admin user
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com)

# Call a protected endpoint. Since there are not tools, initially this just returns `[]`
curl -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
     https://mcpgateway.us-south.codeengine.appdomain.cloud/tools

# Check the logs
make ibmcloud-ce-logs
```

---

## 6 - Cleanup

```bash
# via Makefile
make ibmcloud-ce-rm

# or directly
ibmcloud ce application delete --name "$IBMCLOUD_CODE_ENGINE_APP" -f
```

---

## 7 - Using IBM Cloud Databases for PostgreSQL

Need durable data, high availability, and automated backups? Provision **IBM Cloud Databases for PostgreSQL** and connect MCP Gateway to it.

```bash
###############################################################################
# 1 - Provision PostgreSQL
###############################################################################
# Choose a plan:  standard (shared) or enterprise (dedicated). For small
# workloads start with: standard / 1 member / 4 GB RAM.
ibmcloud resource service-instance-create mcpgw-db \
    databases-for-postgresql standard $IBMCLOUD_REGION

###############################################################################
# 2 - Create service credentials
###############################################################################
ibmcloud resource service-key-create mcpgw-db-creds Administrator \
    --instance-name mcpgw-db

###############################################################################
# 3 - Retrieve credentials & craft DATABASE_URL
###############################################################################
creds_json=$(ibmcloud resource service-key mcpgw-db-creds --output json)
host=$(echo "$creds_json" | jq -r '.[0].credentials.connection.postgres.hosts[0].hostname')
port=$(echo "$creds_json" | jq -r '.[0].credentials.connection.postgres.hosts[0].port')
user=$(echo "$creds_json" | jq -r '.[0].credentials.connection.postgres.authentication.username')
pass=$(echo "$creds_json" | jq -r '.[0].credentials.connection.postgres.authentication.password')
db=$(echo "$creds_json"   | jq -r '.[0].credentials.connection.postgres.database')

DATABASE_URL="postgresql+psycopg://${user}:${pass}@${host}:${port}/${db}?sslmode=require"

###############################################################################
# 4 - Store DATABASE_URL as a Code Engine secret
###############################################################################
ibmcloud ce secret create --name mcpgw-db-url \
    --from-literal DATABASE_URL="$DATABASE_URL"

###############################################################################
# 5 - Mount the secret into the application
###############################################################################
ibmcloud ce application update --name "$IBMCLOUD_CODE_ENGINE_APP" \
    --env-from-secret mcpgw-db-url
```

### Choosing the right PostgreSQL size

| Workload profile | Suggested plan | Members × RAM | Notes                                                 |
| ---------------- | -------------- | ------------- | ----------------------------------------------------- |
| **Dev / PoC**    | `standard`     | 1 × 4 GB      | Cheapest; no HA; easy to scale later                  |
| **Prod small**   | `standard`     | 2 × 8 GB      | Two members enable HA & automatic fail-over           |
| **Prod heavy**   | `enterprise`   | 3 × 16 GB     | Dedicated bare-metal; highest performance & isolation |

Scale up at any time with:

```bash
ibmcloud cdb deployment-scaling-set mcpgw-db \
    --members 3 --memory-gb 16

# Update the number of maximum connections:
ibmcloud cdb deployment-configuration YOUR_DB_CRN '{"configuration":{"max_connections":215}}'

# show max_connections;
```

The gateway will reconnect transparently because the host name remains stable. See the [documentation for more details](https://cloud.ibm.com/docs/databases-for-postgresql?topic=databases-for-postgresql-managing-connections&locale=en#raise-connection-limit).

---

### Local SQLite vs. Managed PostgreSQL

| Aspect          | Local SQLite (`sqlite:////tmp/mcp.db`)  | Managed PostgreSQL   |
| --------------- | --------------------------------------- | -------------------- |
| Persistence     | **None** - lost on restarts / scale-out | Durable & backed-up  |
| Concurrency     | Single-writer lock                      | Multiple writers     |
| Scale-out ready | No - state is per-pod                   | Yes                  |
| Best for        | Unit tests, CI pipelines                | Staging & production |

For production workloads you **must** switch to a managed database or mount a persistent file system.

---

## 8 - Adding IBM Cloud Databases for Redis (optional cache layer)

Need a high-performance shared cache? Provision **IBM Cloud Databases for Redis**
and point MCP Gateway at it.

```bash
###############################################################################
# 1 - Provision Redis
###############################################################################
# Choose a plan: standard (shared) or enterprise (dedicated).
ibmcloud resource service-instance-create mcpgw-redis \
    databases-for-redis standard $IBMCLOUD_REGION

###############################################################################
# 2 - Create service credentials
###############################################################################
ibmcloud resource service-key-create mcpgw-redis-creds Administrator \
    --instance-name mcpgw-redis

###############################################################################
# 3 - Retrieve credentials & craft REDIS_URL
###############################################################################
creds_json=$(ibmcloud resource service-key mcpgw-redis-creds --output json)
host=$(echo "$creds_json" | jq -r '.[0].credentials.connection.rediss.hosts[0].hostname')
port=$(echo "$creds_json" | jq -r '.[0].credentials.connection.rediss.hosts[0].port')
pass=$(echo "$creds_json" | jq -r '.[0].credentials.connection.rediss.authentication.password')

REDIS_URL="rediss://:${pass}@${host}:${port}/0"   # rediss = TLS-secured Redis

###############################################################################
# 4 - Store REDIS_URL as a Code Engine secret
###############################################################################
ibmcloud ce secret create --name mcpgw-redis-url \
    --from-literal REDIS_URL="$REDIS_URL"

###############################################################################
# 5 - Mount the secret and switch cache backend
###############################################################################
ibmcloud ce application update --name "$IBMCLOUD_CODE_ENGINE_APP" \
    --env-from-secret mcpgw-redis-url \
    --env CACHE_TYPE=redis
```

### Choosing the right Redis size

| Use-case         | Plan         | Memory | Notes                             |
| ---------------- | ------------ | ------ | --------------------------------- |
| Dev / CI         | `standard`   | 256 MB | Minimum footprint, single member  |
| Small production | `standard`   | 1 GB   | Two-member HA cluster             |
| High-throughput  | `enterprise` | ≥4 GB  | Dedicated nodes, persistence, AOF |

Scale later with:

```bash
ibmcloud cdb deployment-scaling-set mcpgw-redis --memory-gb 4
```

Once redeployed, the gateway will use Redis for request-level caching,
reducing latency and database load.

---

## 9. Gunicorn configuration (optional tuning)

The container starts `gunicorn` with the settings defined in **`gunicorn.conf.py`** found at the project root.
If you need to change worker counts, ports, or time-outs, edit this file **before** you build the image (`make podman` or `make docker`). The settings are baked into the container at build time.

```python
# -*- coding: utf-8 -*-
"""
Gunicorn configuration
Docs: https://docs.gunicorn.org/en/stable/settings.html
"""

# Network interface / port ──────────────────────────────────────────────
bind = "0.0.0.0:4444"        # Listen on all interfaces, port 4444

# Worker processes ──────────────────────────────────────────────────────
workers = 8                  # Rule of thumb: 2-4 × NUM_CPU_CORES

# Request/worker life-cycle ─────────────────────────────────────────────
timeout = 600                # Kill a worker after 600 s of no response
max_requests = 10000         # Restart worker after N requests
max_requests_jitter = 100    # Add randomness to avoid synchronized restarts

# Logging & verbosity ───────────────────────────────────────────────────
loglevel = "info"            # "debug", "info", "warning", "error", "critical"

# Optimisations ─────────────────────────────────────────────────────────
preload_app = True           # Load app code once in parent, fork workers (saves RAM)
reuse_port  = True           # SO_REUSEPORT for quicker restarts

# Alternative worker models (uncomment ONE and install extras) ----------
# worker_class = "gevent"     # pip install "gunicorn[gevent]"
# worker_class = "eventlet"   # pip install "gunicorn[eventlet]"
# worker_class = "tornado"    # pip install "gunicorn[tornado]"
# threads = 2                 # If using the 'sync' worker with threads

# TLS certificates (if you terminate HTTPS inside the container)
# certfile = 'certs/cert.pem'
# keyfile  = 'certs/key.pem'

# Server hooks (logging examples) ───────────────────────────────────────
def when_ready(server):
    server.log.info("Server is ready. Spawning workers")

def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def worker_exit(server, worker):
    server.log.info("Worker exit (pid: %s)", worker.pid)
```

**Typical tweaks**

| Scenario                              | Setting(s) to adjust                            |
| ------------------------------------- | ----------------------------------------------- |
| High-latency model calls → time-outs  | `timeout` (e.g. 1200 s)                         |
| CPU-bound workload on 4-core instance | `workers = 8` → `workers = 16`                  |
| Memory-limited instance               | Reduce `workers` or disable `preload_app`       |
| Websocket / async traffic             | Switch `worker_class` to `gevent` or `eventlet` |

After changing the file, rebuild and redeploy:

```bash
make podman ibmcloud-tag ibmcloud-push ibmcloud-deploy
```
