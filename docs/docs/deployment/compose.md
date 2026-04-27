# 🧩 Docker Compose

Running **ContextForge** with **Compose** spins up a full stack (Gateway, Postgres, Redis, optional MCP servers) behind a single YAML file.
The Makefile detects Podman or Docker automatically, and you can override it with `COMPOSE_CMD=`.
Health-checks (`service_healthy`) gate the Gateway until the database is ready, preventing race conditions.
If dependencies become temporarily unavailable, the Gateway uses **exponential backoff with jitter** for connection retries—see [Startup Resilience](../architecture/performance-architecture.md#startup-resilience) for details.

!!! tip "Gateway base URL"
    Docker Compose routes the gateway through nginx on `http://localhost:8080`.

    Direct access to the gateway container (port 4444) is intentionally disabled in `docker-compose.yml`.

---

## 🚀 Automated Setup Script

For fresh Linux systems, the **contextforge-setup.sh** script automates the entire setup process including Docker installation, user configuration, and starting the Compose stack.

### Supported Distributions

- Ubuntu, Debian (and derivatives like Linux Mint, Pop!_OS)
- Rocky Linux, RHEL, CentOS, AlmaLinux, Fedora

### Quick Start

```bash
# 1. Create a dedicated user (as root)
useradd -m contextforge && passwd contextforge
usermod -aG wheel contextforge   # RHEL-family
usermod -aG sudo contextforge    # Debian-family

# 2. Switch to the new user
su - contextforge

# 3. Clone the repository and run the setup script
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge
./scripts/contextforge-setup.sh
```

The script will install Docker, configure the user, clone the repository (if not already present), and start the Compose stack.

### Script Options

| Option | Description |
|--------|-------------|
| `--skip-start` | Install dependencies but don't start services |
| `--skip-docker-login` | Skip Docker registry login prompt |
| `--remove-podman` | (RHEL-family only) Remove podman/runc without prompting |
| `-y, --yes` | Non-interactive mode for CI/automation |

### Environment Variables for Automated Docker Login

| Variable | Description |
|----------|-------------|
| `DOCKER_USERNAME` | Docker registry username |
| `DOCKER_PASSWORD` | Docker registry password |
| `DOCKER_REGISTRY` | Registry URL (default: Docker Hub) |
| `DOCKER_CONFIG` | Custom Docker config directory |

### Examples

```bash
# Non-interactive install without starting services
./scripts/contextforge-setup.sh -y --skip-start

# Automated install with Docker Hub credentials
DOCKER_USERNAME=myuser DOCKER_PASSWORD=mypass ./scripts/contextforge-setup.sh -y

# Install to custom directory
./scripts/contextforge-setup.sh ~/my-contextforge
```

---

## Configure the compose command to use

For example, install and use Docker Compose v2:

```bash
sudo apt install docker-buildx docker-compose-v2
export COMPOSE_CMD="docker compose"
```

## 🐳/🦭 Build the images

```bash
docker pull ghcr.io/ibm/mcp-context-forge:1.0.0-RC-3
```

## 🐳/🦭 Build the images (when doing local development)

### Using Make (preferred)

| Target             | Image                   | Dockerfile             | Notes                                       |
| ------------------ | ----------------------- | ---------------------- | ------------------------------------------- |
| `make podman`      | `mcpgateway:latest`     | **Containerfile.lite** | Rootless Podman, multi-stage UBI build      |
| `make podman-prod` | `mcpgateway:latest`     | **Containerfile.lite** | Same build, used for production             |
| `make docker`      | `mcpgateway:latest`     | **Containerfile.lite** | Docker Desktop / CI runners                 |
| `make docker-prod` | `mcpgateway:latest`     | **Containerfile.lite** | Same, with Docker Content Trust when pushed |

Remember to tag the image or configure the correct image in `docker-compose.yml`

### Manual equivalents

```bash
# Podman
podman build -t mcpgateway:latest -f Containerfile.lite .

# Podman (AMD64, squash layers)
podman build --platform=linux/amd64 --squash \
  -t mcpgateway:latest -f Containerfile.lite .

# Docker
docker build -t mcpgateway:latest -f Containerfile.lite .
```

> **Apple Silicon note**
> `Containerfile.lite` runtime base is `ubi10-minimal` which supports
> `linux/amd64`, `linux/arm64`, `linux/s390x`, and `linux/ppc64le`. On M-series
> Macs, build native arm64 with `--platform=linux/arm64` — QEMU emulation is
> unnecessary.

---

## 🏃 Start the Compose stack

### With Make

```bash
make compose-up                   # auto-detects engine
COMPOSE_CMD="docker compose" make compose-up   # force Docker
COMPOSE_CMD="podman compose" make compose-up   # force Podman
```

### SSO Profile (Keycloak)

```bash
make compose-sso                  # Gateway + Keycloak profile (recommended)
make sso-test-login               # Smoke-check SSO providers/login URL/test users
```

Manual equivalent:

```bash
docker compose -f docker-compose.yml -f docker-compose.sso.yml --profile sso up -d
```

Keycloak admin console:

- URL: `http://localhost:8180`
- Credentials: `admin` / `changeme`

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

* **Gateway URL:** [http://localhost:8080](http://localhost:8080)
  (Nginx reverse proxy; gateway port 4444 is not published in Compose.)

```bash
curl http://localhost:8080/health    # {"status":"healthy"}
```

* **Logs:** `make compose-logs` or raw `docker compose logs -f gateway`.

---

## Rust MCP Compose Modes

For the compose-backed testing stack, the Rust MCP runtime is exposed through
mode-specific make targets:

```bash
make testing-rebuild-rust-shadow
make testing-rebuild-rust
make testing-rebuild-rust-full
```

Mode summary:

- `shadow`: Rust sidecar present, but public `/mcp` stays on Python
- `edge`: public `/mcp` routed directly from nginx to Rust
- `full`: `edge` plus Rust session/event-store/resume/live-stream/affinity
  cores

Verify the active mode via `/health`:

```bash
curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'
```

Examples:

- `x-contextforge-mcp-transport-mounted: python` means the public MCP path is
  still Python-owned
- `x-contextforge-mcp-transport-mounted: rust` means nginx is routing public
  `/mcp` traffic directly to the Rust runtime

For the current runtime architecture, see
[Rust MCP Runtime](../architecture/rust-mcp-runtime.md).

---

## 🗄 Selecting a database

Uncomment one service block in `docker-compose.yml` and align `DATABASE_URL`:

| Service block         | Connection string                             | Notes                          |
| --------------------- | --------------------------------------------- | ------------------------------ |
| `postgres:` (default) | `postgresql+psycopg://postgres:...@postgres:5432/mcp` | Recommended for production     |

Named volumes (`pgdata`) isolate persistent data.

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
    - **Advisory locks** (used during migrations/bootstrap) are session-level; ensure `server_reset_query` clears them (use `DISCARD ALL` or add `SELECT pg_advisory_unlock_all()`), or run migrations against direct PostgreSQL.

    ContextForge is designed to work with transaction mode.

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

## 🔐 TLS/HTTPS Support

Enable HTTPS with zero configuration using the TLS profile:

```bash
make compose-tls
```

This automatically:

- Generates self-signed certificates (if `./certs/` is empty)
- Starts nginx with TLS on port 8443
- Keeps HTTP available on port 8080

### TLS Commands

| Command | Description |
|---------|-------------|
| `make compose-tls` | Start with HTTPS (HTTP + HTTPS both work) |
| `make compose-tls-https` | Start with forced HTTPS redirect |
| `make compose-tls-down` | Stop TLS stack |
| `make compose-tls-logs` | View TLS service logs |
| `make compose-tls-ps` | Check TLS service status |

### Using Custom Certificates

```bash
mkdir -p certs
cp /path/to/cert.pem certs/cert.pem
cp /path/to/key.pem certs/key.pem
make compose-tls
```

### Access Points

- **HTTP:** `http://localhost:8080`
- **HTTPS:** `https://localhost:8443`
- **Admin UI:** `https://localhost:8443/admin`

!!! tip "Self-Signed Certificate Warning"
    Browsers will show a security warning for self-signed certificates. Click "Advanced" → "Proceed" to continue, or use `curl -k` to skip verification.

For advanced TLS configuration (end-to-end encryption, custom ciphers, etc.), see [TLS Configuration Guide](tls-configuration.md).

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
ss -tlnp | grep 8080        # modern tool
netstat -anp | grep 8080    # legacy fallback
```

> A line like `:::8080 LISTEN rootlessport` is **normal** - the IPv6
> wildcard socket (`::`) also accepts IPv4 when `net.ipv6.bindv6only=0`
> (the default on Linux).

**WSL2 quirk**

WSL's NAT maps only the IPv6 side, so `http://127.0.0.1:8080` fails from Windows. Tell Podman you are inside WSL and restart your containers:

```bash
# inside the WSL distro
echo "wsl" | sudo tee /etc/containers/podman-machine
```

`ss` should now show an explicit `0.0.0.0:8080` listener, making the
service reachable from Windows and the LAN.

## 📚 References

* Docker Compose CLI (`up`, `logs`, `down`) - official docs
* Podman's integrated **compose** wrapper - man page
* `podman-compose` rootless implementation - GitHub project
* Health-check gating with `depends_on: condition: service_healthy`
* [UBI9 runtime on Apple Silicon limitations (`x86_64-v2` glibc)](https://github.com/containers/podman/issues/15456)
* General Containerfile build guidance (Fedora/Red Hat)
