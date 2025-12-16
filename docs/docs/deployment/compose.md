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
| `postgres:` (default) | `postgresql://postgres:...@postgres:5432/mcp` | Recommended for production     |
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
