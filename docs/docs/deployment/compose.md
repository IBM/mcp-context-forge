# 🧩 Docker Compose

Running **MCP Gateway** with **Compose** spins up a full stack (Gateway, Postgres, Redis, optional MPC servers) behind a single YAML file.
The Makefile detects Podman or Docker automatically, and you can override it with `COMPOSE_CMD=`.
Health-checks (`service_healthy`) gate the Gateway until the database is ready, preventing race conditions.

---

## Configure the compose command to use

For example, install and use Docker Compose v2:

```bash
sudo apt install docker-buildx docker-compose-v2
export COMPOSE_CMD="docker compose"
```

## 🐳/🦭 Build the images

```bash
docker pull ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1
```

## 🐳/🦭 Build the images (when doing local development)

### Using Make (preferred)

| Target             | Image                   | Dockerfile             | Notes                         |
| ------------------ | ----------------------- | ---------------------- | ----------------------------- |
| `make podman`      | `mcpgateway:latest`     | **Containerfile**      | Rootless Podman, dev-oriented |
| `make podman-prod` | `mcpgateway:latest`     | **Containerfile.lite** | Ultra-slim UBI 9-micro build  |
| `make docker`      | `mcpgateway:latest`     | **Containerfile**      | Docker Desktop / CI runners   |
| `make docker-prod` | `mcpgateway:latest`     | **Containerfile.lite** | Same multi-stage "lite" build |

Remember to tag the image or configure the correct image in `docker-compose.yml`

### Manual equivalents

```bash
# Podman (dev image)
podman build -t mcpgateway-dev:latest -f Containerfile .

# Podman (prod image, AMD64, squash layers)
podman build --platform=linux/amd64 --squash \
  -t mcpgateway:latest -f Containerfile.lite .

# Docker (dev image)
docker build -t mcpgateway-dev:latest -f Containerfile .

# Docker (prod image)
docker build -t mcpgateway:latest -f Containerfile.lite .
```

> **Apple Silicon caveat**
> `Containerfile.lite` derives from **ubi9-micro**. Running it via QEMU emulation on M-series Macs often fails with a `glibc x86-64-v2` error.
> Use the *regular* image or build a native `linux/arm64` variant on Mac.

---

## 🏃 Start the Compose stack

### With Make

```bash
make compose-up                   # auto-detects engine
COMPOSE_ENGINE=docker make compose-up   # force Docker
COMPOSE_ENGINE=podman make compose-up   # force Podman
```

### Without Make

| Make target       | Docker CLI                                    | Podman built-in                              | podman-compose                               |
| ----------------- | --------------------------------------------- | -------------------------------------------- | -------------------------------------------- |
| `compose-up`      | `docker compose -f docker-compose.yml up -d`  | `podman compose -f docker-compose.yml up -d` | `podman-compose -f docker-compose.yml up -d` |
| `compose-restart` | `docker compose up -d --pull=missing --build` | idem                                         | idem                                         |
| `compose-logs`    | `docker compose logs -f`                      | `podman compose logs -f`                     | `podman-compose logs -f`                     |
| `compose-ps`      | `docker compose ps`                           | `podman compose ps`                          | `podman-compose ps`                          |
| `compose-stop`    | `docker compose stop`                         | `podman compose stop`                        | `podman-compose stop`                        |
| `compose-down`    | `docker compose down`                         | `podman compose down`                        | `podman-compose down`                        |
| `compose-clean`   | `docker compose down -v` (removes volumes)    | `podman compose down -v`                     | `podman-compose down -v`                     |

---

## 🌐 Access and verify

* **Gateway URL:** [http://localhost:4444](http://localhost:4444)
  (Bound to `0.0.0.0` inside the container so port-forwarding works.)

```bash
curl http://localhost:4444/health    # {"status":"ok"}
```

* **Logs:** `make compose-logs` or raw `docker compose logs -f gateway`.

---

## 🗄 Selecting a database

Uncomment one service block in `docker-compose.yml` and align `DATABASE_URL`:

| Service block         | Connection string                             | Notes                          |
| --------------------- | --------------------------------------------- | ------------------------------ |
| `postgres:` (default) | `postgresql+psycopg://postgres:...@postgres:5432/mcp` | Recommended for production     |
| `mariadb:`            | `mysql+pymysql://mysql:...@mariadb:3306/mcp`  | **Fully supported** - MariaDB 10.6+ |
| `mysql:`              | `mysql+pymysql://admin:...@mysql:3306/mcp`    | Alternative MySQL variant      |

Named volumes (`pgdata`, `mariadbdata`, `mysqldata`, `mongodata`) isolate persistent data.

!!! info "MariaDB & MySQL Full Support"
    MariaDB and MySQL are **fully supported** alongside SQLite and PostgreSQL:

    - **36+ database tables** work perfectly with MariaDB 10.6+ and MySQL 8.0+
    - All **VARCHAR length issues** have been resolved for MariaDB/MySQL compatibility
    - The `mariadb:` service block is available in `docker-compose.yml`
    - Use connection string: `mysql+pymysql://mysql:changeme@mariadb:3306/mcp`

---

## 🔀 PgBouncer Connection Pooling

PgBouncer is a lightweight connection pooler for PostgreSQL that reduces connection overhead and improves throughput under high concurrency. **PgBouncer is enabled by default** in the Docker Compose configuration.

### Default Architecture

```
Gateway (2 replicas × 16 workers) → PgBouncer → PostgreSQL (max_connections=500)
```

Benefits of PgBouncer (enabled by default):

- **Connection multiplexing**: Many app connections share fewer database connections
- **Reduced PostgreSQL overhead**: Lower `max_connections` reduces memory per connection
- **Connection reuse**: PgBouncer maintains persistent connections to PostgreSQL
- **Graceful handling of connection storms**: Queues requests instead of rejecting

### Disabling PgBouncer (Direct PostgreSQL)

If you need to bypass PgBouncer for debugging or specific workloads:

1. **Update gateway `DATABASE_URL`** to connect directly to PostgreSQL:

```yaml
# In gateway environment section, change:
- DATABASE_URL=postgresql+psycopg://postgres:mysecretpassword@pgbouncer:6432/mcp
# To:
- DATABASE_URL=postgresql+psycopg://postgres:mysecretpassword@postgres:5432/mcp
```

2. **Increase gateway pool settings**:

```yaml
# Change from:
- DB_POOL_SIZE=10
- DB_MAX_OVERFLOW=20
# To:
- DB_POOL_SIZE=50
- DB_MAX_OVERFLOW=100
```

3. **Increase PostgreSQL max_connections**:

```yaml
# In postgres command section, change:
- "max_connections=500"
# To:
- "max_connections=4000"
```

4. **Update gateway depends_on** to wait for PostgreSQL directly:

```yaml
depends_on:
  postgres:
    condition: service_healthy
  redis:
    condition: service_started
```

### Pool Modes

PgBouncer supports three pool modes:

| Mode | Description | Best For |
|------|-------------|----------|
| **transaction** (default) | Connection returned after transaction commit | Web applications, APIs |
| session | Connection held for entire session | Legacy apps requiring session state |
| statement | Connection returned after each statement | Simple read-heavy workloads |

!!! warning "Transaction Mode Limitations"
    Transaction mode (the default) returns connections to the pool after each transaction. This means:

    - **Prepared statements** may not work as expected across transactions
    - **Session-level settings** (like `SET` commands) are not preserved
    - **LISTEN/NOTIFY** requires session mode

    MCP Gateway is designed to work with transaction mode.

### Configuration Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_CLIENT_CONN` | 2000 | Maximum connections from applications |
| `DEFAULT_POOL_SIZE` | 100 | Connections per user/database pair |
| `MIN_POOL_SIZE` | 10 | Minimum connections to keep open |
| `RESERVE_POOL_SIZE` | 25 | Extra connections for burst traffic |
| `MAX_DB_CONNECTIONS` | 200 | Maximum connections to PostgreSQL |
| `SERVER_LIFETIME` | 3600 | Max age of server connection (seconds) |
| `SERVER_IDLE_TIMEOUT` | 600 | Close idle connections after (seconds) |

### Monitoring PgBouncer

Connect to PgBouncer's admin console:

```bash
# Connect to PgBouncer admin
docker compose exec pgbouncer psql -p 6432 -U postgres pgbouncer

# View pool statistics
SHOW STATS;

# View current pools
SHOW POOLS;

# View active clients
SHOW CLIENTS;

# View server connections
SHOW SERVERS;
```

### Troubleshooting

**Connection timeouts:**
- Increase `RESERVE_POOL_SIZE` for burst handling
- Check if `MAX_DB_CONNECTIONS` is sufficient

**Slow queries with PgBouncer:**
- Verify pool mode is appropriate for your workload
- Check for long-running transactions holding connections

**Authentication failures:**
- Ensure `AUTH_TYPE` matches PostgreSQL's `pg_hba.conf`
- Verify password is correct in `DATABASE_URL`

---

## 🔄 Lifecycle cheatsheet

| Task               | Make                   | Manual (engine-agnostic)                        |
| ------------------ | ---------------------- | ----------------------------------------------- |
| Start / create     | `make compose-up`      | `<engine> compose up -d`                        |
| Re-create changed  | `make compose-restart` | `<engine> compose up -d --pull=missing --build` |
| Tail logs          | `make compose-logs`    | `<engine> compose logs -f`                      |
| Shell into gateway | `make compose-shell`   | `<engine> compose exec gateway /bin/sh`         |
| Stop               | `make compose-stop`    | `<engine> compose stop`                         |
| Remove containers  | `make compose-down`    | `<engine> compose down`                         |
| **Nuke volumes**   | `make compose-clean`   | `<engine> compose down -v`                      |

`<engine>` = `docker`, `podman`, or `podman-compose` as shown earlier.

---

## 🔍 Troubleshooting port publishing on WSL2 (rootless Podman)

```bash
# Verify the port is listening (dual-stack)
ss -tlnp | grep 4444        # modern tool
netstat -anp | grep 4444    # legacy fallback
```

> A line like `:::4444 LISTEN rootlessport` is **normal** - the IPv6
> wildcard socket (`::`) also accepts IPv4 when `net.ipv6.bindv6only=0`
> (the default on Linux).

**WSL2 quirk**

WSL's NAT maps only the IPv6 side, so `http://127.0.0.1:4444` fails from Windows. Tell Podman you are inside WSL and restart your containers:

```bash
# inside the WSL distro
echo "wsl" | sudo tee /etc/containers/podman-machine
```

`ss` should now show an explicit `0.0.0.0:4444` listener, making the
service reachable from Windows and the LAN.

## 📚 References

* Docker Compose CLI (`up`, `logs`, `down`) - official docs
* Podman's integrated **compose** wrapper - man page
* `podman-compose` rootless implementation - GitHub project
* Health-check gating with `depends_on: condition: service_healthy`
* [UBI9 runtime on Apple Silicon limitations (`x86_64-v2` glibc)](https://github.com/containers/podman/issues/15456)
* General Containerfile build guidance (Fedora/Red Hat)
