# Configuration Reference

This guide provides comprehensive configuration options for MCP Gateway, including database setup, environment variables, and deployment-specific settings.

---

## 🗄 Database Configuration

MCP Gateway supports multiple database backends with full feature parity across all supported systems.

### Supported Databases

| Database    | Support Level | Connection String Example                                    | Notes                          |
|-------------|---------------|--------------------------------------------------------------|--------------------------------|
| SQLite      | ✅ Full       | `sqlite:///./mcp.db`                                        | Default, file-based            |
| PostgreSQL  | ✅ Full       | `postgresql+psycopg://postgres:changeme@localhost:5432/mcp` | Recommended for production     |
| MariaDB     | ✅ Full       | `mysql+pymysql://mysql:changeme@localhost:3306/mcp`         | **36+ tables**, MariaDB 10.6+ |
| MySQL       | ✅ Full       | `mysql+pymysql://admin:changeme@localhost:3306/mcp`         | Alternative MySQL variant      |

### PostgreSQL System Dependencies

!!! warning "Required: libpq Development Headers"
    The PostgreSQL adapter (`psycopg[c]`) requires the `libpq` development headers to compile. Install them before running `pip install .[postgres]`:

    === "Debian/Ubuntu"
        ```bash
        sudo apt-get install libpq-dev
        ```

    === "RHEL/CentOS/Fedora"
        ```bash
        sudo dnf install postgresql-devel
        ```

    === "macOS (Homebrew)"
        ```bash
        brew install libpq
        ```

    After installing the system dependencies, install the Python package:
    ```bash
    pip install .[postgres]
    ```

### MariaDB/MySQL Setup Details

!!! success "MariaDB & MySQL Full Support"
    MariaDB and MySQL are **fully supported** alongside SQLite and PostgreSQL:

    - **36+ database tables** work perfectly with MariaDB 10.6+ and MySQL 8.0+
    - All **VARCHAR length issues** have been resolved for MariaDB/MySQL compatibility
    - Complete feature parity with SQLite and PostgreSQL
    - Supports all MCP Gateway features including federation, caching, and A2A agents

#### Connection String Format

```bash
DATABASE_URL=mysql+pymysql://[username]:[password]@[host]:[port]/[database]
```

#### Local MariaDB/MySQL Installation

=== "Ubuntu/Debian (MariaDB)"
    ```bash
    # Install MariaDB server
    sudo apt update && sudo apt install mariadb-server

    # Secure installation (optional)
    sudo mariadb-secure-installation

    # Create database and user
    sudo mariadb -e "CREATE DATABASE mcp;"
    sudo mariadb -e "CREATE USER 'mysql'@'localhost' IDENTIFIED BY 'changeme';"
    sudo mariadb -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'localhost';"
    sudo mariadb -e "FLUSH PRIVILEGES;"
    ```

=== "Ubuntu/Debian (MySQL)"
    ```bash
    # Install MySQL server
    sudo apt update && sudo apt install mysql-server

    # Secure installation (optional)
    sudo mysql_secure_installation

    # Create database and user
    sudo mysql -e "CREATE DATABASE mcp;"
    sudo mysql -e "CREATE USER 'mysql'@'localhost' IDENTIFIED BY 'changeme';"
    sudo mysql -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'localhost';"
    sudo mysql -e "FLUSH PRIVILEGES;"
    ```

=== "CentOS/RHEL/Fedora (MariaDB)"
    ```bash
    # Install MariaDB server
    sudo dnf install mariadb-server
    sudo systemctl start mariadb
    sudo systemctl enable mariadb

    # Create database and user
    sudo mariadb -e "CREATE DATABASE mcp;"
    sudo mariadb -e "CREATE USER 'mysql'@'localhost' IDENTIFIED BY 'changeme';"
    sudo mariadb -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'localhost';"
    sudo mariadb -e "FLUSH PRIVILEGES;"
    ```

=== "CentOS/RHEL/Fedora (MySQL)"
    ```bash
    # Install MySQL server
    sudo dnf install mysql-server  # or: sudo yum install mysql-server
    sudo systemctl start mysqld
    sudo systemctl enable mysqld

    # Create database and user
    sudo mysql -e "CREATE DATABASE mcp;"
    sudo mysql -e "CREATE USER 'mysql'@'localhost' IDENTIFIED BY 'changeme';"
    sudo mysql -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'localhost';"
    sudo mysql -e "FLUSH PRIVILEGES;"
    ```

=== "macOS (Homebrew - MariaDB)"
    ```bash
    # Install MariaDB
    brew install mariadb
    brew services start mariadb

    # Create database and user
    mariadb -u root -e "CREATE DATABASE mcp;"
    mariadb -u root -e "CREATE USER 'mysql'@'localhost' IDENTIFIED BY 'changeme';"
    mariadb -u root -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'localhost';"
    mariadb -u root -e "FLUSH PRIVILEGES;"
    ```

=== "macOS (Homebrew - MySQL)"
    ```bash
    # Install MySQL
    brew install mysql
    brew services start mysql

    # Create database and user
    mysql -u root -e "CREATE DATABASE mcp;"
    mysql -u root -e "CREATE USER 'mysql'@'localhost' IDENTIFIED BY 'changeme';"
    mysql -u root -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'localhost';"
    mysql -u root -e "FLUSH PRIVILEGES;"
    ```

#### Docker MariaDB/MySQL Setup

```bash
# Start MariaDB container (recommended)
docker run -d --name mariadb-mcp \
  -e MYSQL_ROOT_PASSWORD=mysecretpassword \
  -e MYSQL_DATABASE=mcp \
  -e MYSQL_USER=mysql \
  -e MYSQL_PASSWORD=changeme \
  -p 3306:3306 \
  registry.redhat.io/rhel9/mariadb-106:12.0.2-ubi10

# Or start MySQL container
docker run -d --name mysql-mcp \
  -e MYSQL_ROOT_PASSWORD=mysecretpassword \
  -e MYSQL_DATABASE=mcp \
  -e MYSQL_USER=mysql \
  -e MYSQL_PASSWORD=changeme \
  -p 3306:3306 \
  mysql:8

# Connection string for MCP Gateway (same for both)
DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp
```

---

## 🔧 Core Environment Variables

### Database Settings

```bash
# Database connection (choose one)
DATABASE_URL=sqlite:///./mcp.db                                        # SQLite (default)
DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp          # MariaDB/MySQL
DATABASE_URL=postgresql+psycopg://postgres:changeme@localhost:5432/mcp  # PostgreSQL

# Connection pool settings (optional)
DB_POOL_SIZE=200                   # Pool size (QueuePool only)
DB_MAX_OVERFLOW=5                  # Max overflow connections (QueuePool only)
DB_POOL_TIMEOUT=60                 # Wait timeout for connection
DB_POOL_RECYCLE=3600               # Recycle connections after N seconds
DB_MAX_RETRIES=30                  # Retry attempts on connection failure (default: 30)
DB_RETRY_INTERVAL_MS=2000          # Base retry interval in ms (uses exponential backoff with jitter)

# Connection pool class selection
# - "auto": NullPool with PgBouncer, QueuePool otherwise (default)
# - "null": Always NullPool (recommended with PgBouncer)
# - "queue": Always QueuePool (application-side pooling)
DB_POOL_CLASS=auto

# Pre-ping connections before checkout (validates connection is alive)
# - "auto": Enabled for non-PgBouncer setups (default)
# - "true": Always enable (adds SELECT 1 overhead but catches stale connections)
# - "false": Always disable
DB_POOL_PRE_PING=auto

# psycopg3 auto-prepared statements (PostgreSQL only)
# Queries executed N+ times are prepared server-side for performance
DB_PREPARE_THRESHOLD=5
```

#### Database Startup Resilience

The gateway uses **exponential backoff with jitter** when waiting for the database at startup:

- **Retry progression**: 2s → 4s → 8s → 16s → 30s (capped) → 30s...
- **Jitter**: ±25% randomization prevents thundering herd when multiple workers reconnect
- **Default behavior**: 30 retries with 2s base interval ≈ 5 minutes total wait

This prevents CPU-intensive crash-respawn loops when the database is temporarily unavailable.

### Server Configuration

```bash
# Network binding & runtime
HOST=0.0.0.0
PORT=4444
ENVIRONMENT=development
APP_DOMAIN=localhost
APP_ROOT_PATH=

# HTTP Server selection (for containers)
HTTP_SERVER=gunicorn              # Options: gunicorn (default), granian
```

### Gunicorn Production Server (Default)

The production server uses Gunicorn with UVicorn workers by default. Configure via environment variables or `.env` file:

```bash
# Worker Configuration
GUNICORN_WORKERS=auto                 # Number of workers ("auto" = 2*CPU+1, capped at 16)
GUNICORN_TIMEOUT=600                  # Worker timeout in seconds (increase for long requests)
GUNICORN_MAX_REQUESTS=100000          # Requests per worker before restart (prevents memory leaks)
GUNICORN_MAX_REQUESTS_JITTER=100      # Random jitter to prevent thundering herd

# Performance Options
GUNICORN_PRELOAD_APP=true             # Preload app before forking (saves memory, runs migrations once)
GUNICORN_DEV_MODE=false               # Enable hot reload (not for production!)
DISABLE_ACCESS_LOG=true               # Disable access logs for performance (default: true)

# TLS/SSL Configuration
SSL=false                             # Enable TLS/SSL
CERT_FILE=certs/cert.pem              # Path to SSL certificate
KEY_FILE=certs/key.pem                # Path to SSL private key
KEY_FILE_PASSWORD=                    # Passphrase for encrypted private key

# Process Management
FORCE_START=false                     # Bypass lock file check
```

**Starting the Production Server:**

```bash
# Basic startup
./run-gunicorn.sh

# With TLS
SSL=true ./run-gunicorn.sh

# With custom workers
GUNICORN_WORKERS=8 ./run-gunicorn.sh

# Use fixed worker count instead of auto-detection
GUNICORN_WORKERS=4 ./run-gunicorn.sh

# High-performance mode (disable access logs)
DISABLE_ACCESS_LOG=true ./run-gunicorn.sh
```

!!! tip "Worker Count Recommendations"
    - **CPU-bound workloads**: 2-4 × CPU cores
    - **I/O-bound workloads**: 4-12 × CPU cores
    - **Memory-constrained**: Start with 2 and monitor
    - **Auto mode**: Uses formula `min(2*CPU+1, 16)`

### Granian Production Server (Alternative)

Granian is a Rust-based HTTP server with native backpressure for overload protection. Under load, excess requests receive immediate 503 responses instead of queuing indefinitely.

```bash
# Worker Configuration
GRANIAN_WORKERS=auto              # Number of workers (auto = CPU cores, max 16)
GRANIAN_RUNTIME_MODE=auto         # Runtime mode: auto, mt (multi-threaded), st (single-threaded)
GRANIAN_RUNTIME_THREADS=1         # Runtime threads per worker
GRANIAN_BLOCKING_THREADS=1        # Blocking threads per worker (must be 1 for ASGI)

# Backpressure Configuration (overload protection)
GRANIAN_BACKLOG=4096              # OS socket backlog for pending connections
GRANIAN_BACKPRESSURE=64           # Max concurrent requests per worker before 503
# Total capacity = WORKERS × BACKPRESSURE (e.g., 16 × 64 = 1024 concurrent requests)

# Performance Options
GRANIAN_HTTP=auto                 # HTTP version: auto, 1, 2
GRANIAN_LOOP=uvloop               # Event loop: uvloop, asyncio, rloop
GRANIAN_HTTP1_BUFFER_SIZE=524288  # HTTP/1 buffer size (512KB)
GRANIAN_RESPAWN_FAILED=true       # Auto-restart failed workers
GRANIAN_DEV_MODE=false            # Enable hot reload
DISABLE_ACCESS_LOG=true           # Disable access logs for performance

# TLS/SSL (same as Gunicorn)
SSL=false
CERT_FILE=certs/cert.pem
KEY_FILE=certs/key.pem
```

**Starting with Granian:**

```bash
# Local development
make serve-granian

# With HTTP/2 + TLS
make serve-granian-http2

# Container with Granian
docker run -e HTTP_SERVER=granian mcpgateway/mcpgateway
```

!!! info "When to use Granian"
    - **Load spike protection**: Backpressure rejects excess requests with 503 instead of queuing
    - **Bursty traffic**: Graceful degradation under unpredictable load
    - **Native HTTP/2**: Without reverse proxy
    - **High concurrency**: 1000+ concurrent users

    See [ADR-0025](../architecture/adr/025-granian-http-server.md) for detailed comparison and [Tuning Guide](tuning.md#backpressure-for-overload-protection) for backpressure configuration.

### Authentication & Security

```bash
# JWT Algorithm Configuration
JWT_ALGORITHM=HS256                    # HMAC: HS256, HS384, HS512 | RSA: RS256, RS384, RS512 | ECDSA: ES256, ES384, ES512

# Symmetric (HMAC) JWT Configuration - Default
JWT_SECRET_KEY=your-secret-key-here    # Required for HMAC algorithms (HS256, HS384, HS512)

# Asymmetric (RSA/ECDSA) JWT Configuration - Enterprise
JWT_PUBLIC_KEY_PATH=jwt/public.pem     # Required for asymmetric algorithms (RS*/ES*)
JWT_PRIVATE_KEY_PATH=jwt/private.pem   # Required for asymmetric algorithms (RS*/ES*)

# JWT Claims & Validation
JWT_AUDIENCE=mcpgateway-api
JWT_ISSUER=mcpgateway
JWT_AUDIENCE_VERIFICATION=true         # Set to false for Dynamic Client Registration
JWT_ISSUER_VERIFICATION=true           # Set to false if issuer validation is not needed
REQUIRE_TOKEN_EXPIRATION=true
EMBED_ENVIRONMENT_IN_TOKENS=false      # Embed env claim in tokens for environment isolation
VALIDATE_TOKEN_ENVIRONMENT=false       # Reject tokens with mismatched env claim

# Basic Auth (Admin UI)
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme

# Email-based Auth
EMAIL_AUTH_ENABLED=true
PLATFORM_ADMIN_EMAIL=admin@example.com
PLATFORM_ADMIN_PASSWORD=changeme

# Security Features
AUTH_REQUIRED=true
SECURITY_HEADERS_ENABLED=true
CORS_ENABLED=true
CORS_ALLOW_CREDENTIALS=true
ALLOWED_ORIGINS="https://admin.example.com,https://api.example.com"
AUTH_ENCRYPTION_SECRET=$(openssl rand -hex 32)
```

### Feature Flags

```bash
# Core Features
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
MCPGATEWAY_UI_AIRGAPPED=false          # Use local CDN assets for airgapped deployments
MCPGATEWAY_BULK_IMPORT_ENABLED=true
MCPGATEWAY_BULK_IMPORT_MAX_TOOLS=200

# A2A (Agent-to-Agent) Features
MCPGATEWAY_A2A_ENABLED=true
MCPGATEWAY_A2A_MAX_AGENTS=100
MCPGATEWAY_A2A_DEFAULT_TIMEOUT=30
MCPGATEWAY_A2A_MAX_RETRIES=3
MCPGATEWAY_A2A_METRICS_ENABLED=true
```

### Airgapped Deployments

For environments without internet access, the Admin UI can be configured to use local CDN assets instead of external CDNs.

```bash
# Enable airgapped mode (loads CSS/JS from local files)
MCPGATEWAY_UI_AIRGAPPED=true
```

!!! info "Airgapped Mode Features"
    When `MCPGATEWAY_UI_AIRGAPPED=true`:

    - All CSS and JavaScript libraries are loaded from local files
    - No external CDN connections required (Tailwind, HTMX, CodeMirror, Alpine.js, Chart.js)
    - Assets are automatically downloaded during container build
    - Total asset size: ~932KB
    - Full UI functionality maintained

!!! warning "Container Build Required"
    Airgapped mode requires building with `Containerfile.lite` which automatically downloads all CDN assets during the build process. The assets are not included in the Git repository.

**Container Build Example:**
```bash
docker build -f Containerfile.lite -t mcpgateway:airgapped .
docker run -e MCPGATEWAY_UI_AIRGAPPED=true -p 4444:4444 mcpgateway:airgapped
```

### Caching Configuration

```bash
# Cache Backend
CACHE_TYPE=redis                    # Options: memory, redis, database, none
REDIS_URL=redis://localhost:6379/0
CACHE_PREFIX=mcpgateway

# Redis Startup Resilience (exponential backoff with jitter)
REDIS_MAX_RETRIES=30                # Max attempts before worker exits (default: 30)
REDIS_RETRY_INTERVAL_MS=2000        # Base interval in ms (uses exponential backoff with jitter)

# Cache TTL (seconds)
SESSION_TTL=3600
MESSAGE_TTL=600
RESOURCE_CACHE_TTL=1800

# Redis Connection Pool (performance-tuned defaults)
REDIS_MAX_CONNECTIONS=50            # Pool size per worker
REDIS_SOCKET_TIMEOUT=2.0            # Read/write timeout (seconds)
REDIS_SOCKET_CONNECT_TIMEOUT=2.0    # Connection timeout (seconds)
REDIS_RETRY_ON_TIMEOUT=true         # Retry commands on timeout
REDIS_HEALTH_CHECK_INTERVAL=30      # Health check interval (seconds, 0=disabled)
REDIS_DECODE_RESPONSES=true         # Return strings instead of bytes

# Redis Parser (ADR-026 - performance optimization)
REDIS_PARSER=auto                   # auto, hiredis, python (auto uses hiredis if available)

# Redis Leader Election (multi-node deployments)
REDIS_LEADER_TTL=15                 # Leader TTL (seconds)
REDIS_LEADER_KEY=gateway_service_leader
REDIS_LEADER_HEARTBEAT_INTERVAL=5   # Heartbeat interval (seconds)

# Authentication Cache (ADR-028 - reduces DB queries per auth from 3-4 to 0-1)
AUTH_CACHE_ENABLED=true             # Enable auth data caching (user, team, revocation)
AUTH_CACHE_USER_TTL=60              # User data cache TTL in seconds (10-300)
AUTH_CACHE_REVOCATION_TTL=30        # Token revocation cache TTL (5-120, security-critical)
AUTH_CACHE_TEAM_TTL=60              # Team membership cache TTL in seconds (10-300)
AUTH_CACHE_BATCH_QUERIES=true       # Batch auth DB queries into single call
```

#### Redis Startup Resilience

The gateway uses **exponential backoff with jitter** when waiting for Redis at startup:

- **Retry progression**: 2s → 4s → 8s → 16s → 30s (capped) → 30s...
- **Jitter**: ±25% randomization prevents thundering herd when multiple workers reconnect
- **Default behavior**: 30 retries with 2s base interval ≈ 5 minutes total wait

This prevents CPU-intensive crash-respawn loops when Redis is temporarily unavailable.

#### Authentication Cache

When `AUTH_CACHE_ENABLED=true` (default), authentication data is cached to reduce database queries:

- **User data**: Cached for `AUTH_CACHE_USER_TTL` seconds (default: 60)
- **Team memberships**: Cached for `AUTH_CACHE_TEAM_TTL` seconds (default: 60)
- **User roles in teams**: Cached for `AUTH_CACHE_ROLE_TTL` seconds (default: 60)
- **User teams list**: Cached for `AUTH_CACHE_TEAMS_TTL` seconds (default: 60) when `AUTH_CACHE_TEAMS_ENABLED=true`
- **Token revocations**: Cached for `AUTH_CACHE_REVOCATION_TTL` seconds (default: 30)

The cache uses Redis when available (`CACHE_TYPE=redis`) and falls back to in-memory caching.

When `AUTH_CACHE_BATCH_QUERIES=true` (default), the 3 separate authentication database queries are batched into a single query, reducing thread pool contention and connection overhead.

**Performance Note**: The role cache (`AUTH_CACHE_ROLE_TTL`) caches `get_user_role_in_team()` which is called 11+ times per team operation. The teams list cache (`AUTH_CACHE_TEAMS_TTL`) caches `get_user_teams()` which is called 20+ times per request for authorization checks. Together, these can reduce "idle in transaction" connections by 50-70% under high load.

**Security Note**: Keep `AUTH_CACHE_REVOCATION_TTL` short (30s default) to limit the window where revoked tokens may still work.

See [ADR-028](../architecture/adr/028-auth-caching.md) for implementation details.

#### Registry Cache

```bash
# Registry Cache (ADR-029 - caches list endpoints for tools, prompts, resources, etc.)
REGISTRY_CACHE_ENABLED=true         # Enable registry list caching
REGISTRY_CACHE_TOOLS_TTL=20         # Tools list cache TTL in seconds (5-300)
REGISTRY_CACHE_PROMPTS_TTL=15       # Prompts list cache TTL in seconds (5-300)
REGISTRY_CACHE_RESOURCES_TTL=15     # Resources list cache TTL in seconds (5-300)
REGISTRY_CACHE_AGENTS_TTL=20        # Agents list cache TTL in seconds (5-300)
REGISTRY_CACHE_SERVERS_TTL=20       # Servers list cache TTL in seconds (5-300)
REGISTRY_CACHE_GATEWAYS_TTL=20      # Gateways list cache TTL in seconds (5-300)
REGISTRY_CACHE_CATALOG_TTL=300      # Catalog servers cache TTL in seconds (60-600)
```

When `REGISTRY_CACHE_ENABLED=true` (default), the first page of registry list results is cached:

- **Tools**: Cached for `REGISTRY_CACHE_TOOLS_TTL` seconds (default: 20)
- **Prompts**: Cached for `REGISTRY_CACHE_PROMPTS_TTL` seconds (default: 15)
- **Resources**: Cached for `REGISTRY_CACHE_RESOURCES_TTL` seconds (default: 15)
- **Agents**: Cached for `REGISTRY_CACHE_AGENTS_TTL` seconds (default: 20)
- **Servers**: Cached for `REGISTRY_CACHE_SERVERS_TTL` seconds (default: 20)
- **Gateways**: Cached for `REGISTRY_CACHE_GATEWAYS_TTL` seconds (default: 20)
- **Catalog**: Cached for `REGISTRY_CACHE_CATALOG_TTL` seconds (default: 300, longer since external catalog changes infrequently)

Cache is automatically invalidated when items are created, updated, or deleted.

#### Admin Stats Cache

```bash
# Admin Stats Cache (ADR-029 - caches admin dashboard statistics)
ADMIN_STATS_CACHE_ENABLED=true      # Enable admin stats caching
ADMIN_STATS_CACHE_SYSTEM_TTL=60     # System stats cache TTL in seconds (10-300)
ADMIN_STATS_CACHE_OBSERVABILITY_TTL=30  # Observability stats TTL (10-120)
```

When `ADMIN_STATS_CACHE_ENABLED=true` (default), admin dashboard statistics are cached:

- **System stats**: Cached for `ADMIN_STATS_CACHE_SYSTEM_TTL` seconds (default: 60)
- **Observability**: Cached for `ADMIN_STATS_CACHE_OBSERVABILITY_TTL` seconds (default: 30)

See [ADR-029](../architecture/adr/029-registry-admin-stats-caching.md) for implementation details.

#### Team Member Count Cache

```bash
# Team member count cache (reduces N+1 queries in admin UI)
TEAM_MEMBER_COUNT_CACHE_ENABLED=true  # Enable team member count caching
TEAM_MEMBER_COUNT_CACHE_TTL=300       # Cache TTL in seconds (30-3600)
```

When `TEAM_MEMBER_COUNT_CACHE_ENABLED=true` (default), team member counts are cached in Redis:

- **Member counts**: Cached for `TEAM_MEMBER_COUNT_CACHE_TTL` seconds (default: 300)

Cache is automatically invalidated when team members are added, removed, or their `is_active` status changes.

**Performance Note**: This cache eliminates N+1 query patterns in the admin UI team listings, reducing `/admin/` P95 latency from ~14s to <500ms under load.

#### Metrics Aggregation Cache

```bash
# Metrics aggregation cache (reduces full table scans, see #1906)
METRICS_CACHE_ENABLED=true       # Enable metrics query caching (default: true)
METRICS_CACHE_TTL_SECONDS=60     # Cache TTL in seconds (1-300, default: 60)
```

When `METRICS_CACHE_ENABLED=true` (default), aggregate metrics queries are cached in memory:

- **Aggregated metrics**: Cached for `METRICS_CACHE_TTL_SECONDS` seconds (default: 60)
- **Top performers**: Cached separately with the same TTL

Cache is automatically invalidated when metrics are recorded.

**Performance Note**: This cache reduces full table scans on metrics tables. Under high load (3000+ users), increasing TTL to 60-120 seconds can reduce sequential scans by 6-12×. See [Issue #1906](https://github.com/IBM/mcp-context-forge/issues/1906) for details.

### Session Registry Polling (Database Backend)

When using `CACHE_TYPE=database`, sessions poll the database to check for incoming messages. Adaptive backoff reduces database load by ~90% during idle periods while maintaining responsiveness when messages arrive.

```bash
# Adaptive backoff polling configuration
POLL_INTERVAL=1.0          # Initial polling interval in seconds (default: 1.0)
MAX_INTERVAL=5.0           # Maximum polling interval cap in seconds (default: 5.0)
BACKOFF_FACTOR=1.5         # Multiplier for exponential backoff (default: 1.5)
```

**How Adaptive Backoff Works:**

1. Polling starts at `POLL_INTERVAL` (1.0s by default)
2. When no message is found, interval increases by `BACKOFF_FACTOR` (1.5×)
3. Interval continues growing until it reaches `MAX_INTERVAL` (5.0s cap)
4. When a message arrives, interval immediately resets to `POLL_INTERVAL`

**Example Progression:**

```
1.0s → 1.5s → 2.25s → 3.375s → 5.0s (capped) → 5.0s → ...
         ↓ message arrives
         1.0s (reset)
```

**Tuning Guide:**

| Use Case | POLL_INTERVAL | MAX_INTERVAL | BACKOFF_FACTOR |
|----------|---------------|--------------|----------------|
| Real-time (<1s latency) | 0.1-0.5 | 2.0-5.0 | 1.5 |
| Standard (default) | 1.0 | 5.0 | 1.5 |
| Batch workloads | 1.0-2.0 | 10.0-30.0 | 2.0 |
| Minimal DB load | 2.0 | 30.0 | 2.0 |

**Per-Session Database Impact:**

| Configuration | Idle Queries/Min | Active Queries/Min |
|---------------|------------------|-------------------|
| Default (1.0s/5.0s) | 12 | 60 |
| Aggressive (0.1s/2.0s) | 30-600 | 600 |
| Conservative (2.0s/30.0s) | 2 | 30 |

!!! tip "Redis Eliminates Polling"
    With `CACHE_TYPE=redis`, sessions use Redis Pub/Sub for instant message delivery with zero polling overhead. Redis is recommended for production deployments with many concurrent sessions.

### HTTPX Client Connection Pool

MCP Gateway uses HTTP client connection pooling for outbound requests, providing ~20x better performance than per-request clients by reusing TCP connections. These settings affect federation, health checks, A2A agent calls, SSO, MCP server connections, and catalog operations.

!!! note "Shared vs Factory Clients"
    Most requests use a shared singleton client for optimal connection reuse. SSE/streaming MCP connections use factory-created clients with the same settings, as they require dedicated long-lived connections for proper lifecycle management.

```bash
# Connection Pool Limits
HTTPX_MAX_CONNECTIONS=200              # Total connections in pool (10-1000, default: 200)
HTTPX_MAX_KEEPALIVE_CONNECTIONS=100    # Keepalive connections (1-500, default: 100)
HTTPX_KEEPALIVE_EXPIRY=30.0            # Idle connection expiry in seconds (5.0-300.0)

# Timeout Configuration
HTTPX_CONNECT_TIMEOUT=5.0              # TCP connection timeout in seconds (default: 5, fast for LAN)
HTTPX_READ_TIMEOUT=120.0               # Response read timeout in seconds (default: 120, high for slow tools)
HTTPX_WRITE_TIMEOUT=30.0               # Request write timeout in seconds (default: 30)
HTTPX_POOL_TIMEOUT=10.0                # Wait for available connection in seconds (default: 10, fail fast)

# Protocol Configuration
HTTPX_HTTP2_ENABLED=false              # Enable HTTP/2 (requires server support)

# Admin Operations Timeout
HTTPX_ADMIN_READ_TIMEOUT=30.0          # Admin UI operations timeout (default: 30, fail fast)
```

**Sizing Guidelines:**

| Deployment Size | `HTTPX_MAX_CONNECTIONS` | `HTTPX_MAX_KEEPALIVE_CONNECTIONS` | Notes |
|----------------|------------------------|----------------------------------|-------|
| Development    | 50                     | 25                               | Minimal footprint |
| Production     | 200                    | 100                              | Default, handles typical load |
| High-traffic   | 300-500                | 150-250                          | Heavy federation/A2A usage |

**Formula:** `HTTPX_MAX_CONNECTIONS = concurrent_outbound_requests × 1.5`

!!! tip "Connection Pool vs Per-Request Clients"
    The shared connection pool eliminates TCP handshake and TLS negotiation overhead for each request. In benchmarks, this provides ~20x improvement in throughput compared to creating a new client per request.

!!! warning "HTTP/2 Support"
    HTTP/2 (`HTTPX_HTTP2_ENABLED=true`) enables multiplexing over a single connection but requires upstream servers to support HTTP/2. Leave disabled unless all upstream services support HTTP/2.

### Logging Settings

```bash
# Log Level
LOG_LEVEL=INFO                      # DEBUG, INFO, WARNING, ERROR, CRITICAL

# Log Destinations
LOG_TO_FILE=false
LOG_ROTATION_ENABLED=false
LOG_FILE=mcpgateway.log
LOG_FOLDER=logs

# Structured Logging
LOG_FORMAT=json                     # json, plain

# Database Log Persistence (disabled by default for performance)
STRUCTURED_LOGGING_DATABASE_ENABLED=false

# Audit Trail Logging (disabled by default for performance)
AUDIT_TRAIL_ENABLED=false

# Security Event Logging (disabled by default for performance)
SECURITY_LOGGING_ENABLED=false
SECURITY_LOGGING_LEVEL=failures_only  # all, failures_only, high_severity
```

#### Audit Trail Logging

When `AUDIT_TRAIL_ENABLED=true`, all CRUD operations (create, read, update, delete) on resources are logged to the `audit_trails` database table. This provides:

- **Compliance logging** for SOC2, HIPAA, and other regulatory requirements
- **Data access tracking** - who accessed what resources and when
- **Change history** - before/after values for updates and deletes
- **Admin UI Audit Log Viewer** - browse and filter audit entries

**Warning:** Enabling audit trails causes a database write on **every API request**, which can significantly impact performance. During load testing, this can generate millions of rows. Only enable for production compliance requirements.

#### Structured Log Database Persistence

When `STRUCTURED_LOGGING_DATABASE_ENABLED=true`, logs are persisted to the database enabling:

- **Log Search API** (`/api/logs/search`) - Search logs by level, component, user, time range
- **Request Tracing** (`/api/logs/trace/{correlation_id}`) - Trace all logs for a request
- **Performance Metrics** - Aggregated p50/p95/p99 latencies and error rates
- **Admin UI Log Viewer** - Browse and filter logs in the web interface

When disabled (default), logs only go to console/file. This improves performance by avoiding synchronous database writes on each log entry. Use this setting if you have an external log aggregator (ELK, Datadog, Splunk, etc.).

### Development & Debug

```bash
# Development Mode
ENVIRONMENT=development             # development, staging, production
DEV_MODE=true
RELOAD=true
TEMPLATES_AUTO_RELOAD=true          # Auto-reload Jinja2 templates (default: false for production)
DEBUG=true

# Observability
OTEL_ENABLE_OBSERVABILITY=true
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

### LLM Settings (Internal API)

MCP Gateway can act as a unified LLM provider with an OpenAI-compatible API. Configure multiple external LLM providers through the Admin UI and expose them through a single proxy endpoint.

```bash
# LLM API Configuration
LLM_API_PREFIX=/v1                  # API prefix for internal LLM endpoints
LLM_REQUEST_TIMEOUT=120             # Request timeout for LLM API calls (seconds)
LLM_STREAMING_ENABLED=true          # Enable streaming responses
LLM_HEALTH_CHECK_INTERVAL=300       # Provider health check interval (seconds)

# Gateway Provider Settings (for LLM Chat with provider=gateway)
GATEWAY_MODEL=gpt-4o                # Default model to use
GATEWAY_BASE_URL=                   # Base URL (defaults to internal API)
GATEWAY_TEMPERATURE=0.7             # Sampling temperature
```

!!! info "Provider Configuration"
    LLM providers (OpenAI, Azure OpenAI, Anthropic, Ollama, Google, Mistral, Cohere, AWS Bedrock, Groq, etc.) are configured through the Admin UI under **LLM Settings > Providers**. The settings above control the gateway's internal LLM proxy behavior.

**OpenAI-Compatible API Endpoints:**

```bash
# List available models
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/v1/models

# Chat completion
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}' \
  http://localhost:4444/v1/chat/completions
```

**Admin UI Features:**

- **Providers**: Add, edit, enable/disable, and delete LLM providers
- **Models**: View, test, and manage models from configured providers
- **Health Checks**: Monitor provider health with automatic status checks
- **Model Discovery**: Fetch available models from providers and sync to database

---

## 🔐 JWT Configuration Examples

MCP Gateway supports both symmetric (HMAC) and asymmetric (RSA/ECDSA) JWT algorithms for different deployment scenarios.

### HMAC (Symmetric) - Simple Deployments

Best for single-service deployments where you control both token creation and verification.

```bash
# Standard HMAC configuration
JWT_ALGORITHM=HS256
JWT_SECRET_KEY=your-256-bit-secret-key-here
JWT_AUDIENCE=mcpgateway-api
JWT_ISSUER=mcpgateway
JWT_AUDIENCE_VERIFICATION=true
JWT_ISSUER_VERIFICATION=true
```

### RSA (Asymmetric) - Enterprise Deployments

Ideal for distributed systems, microservices, and enterprise environments.

```bash
# RSA configuration
JWT_ALGORITHM=RS256
JWT_PUBLIC_KEY_PATH=certs/jwt/public.pem      # Path to RSA public key
JWT_PRIVATE_KEY_PATH=certs/jwt/private.pem    # Path to RSA private key
JWT_AUDIENCE=mcpgateway-api
JWT_ISSUER=mcpgateway
JWT_AUDIENCE_VERIFICATION=true
JWT_ISSUER_VERIFICATION=true
```

#### Generate RSA Keys

```bash
# Option 1: Use Makefile (Recommended)
make certs-jwt                   # Generates certs/jwt/{private,public}.pem with proper permissions

# Option 2: Manual generation
mkdir -p certs/jwt
openssl genrsa -out certs/jwt/private.pem 4096
openssl rsa -in certs/jwt/private.pem -pubout -out certs/jwt/public.pem
chmod 600 certs/jwt/private.pem
chmod 644 certs/jwt/public.pem
```

### ECDSA (Asymmetric) - High Performance

Modern elliptic curve cryptography for performance-sensitive deployments.

```bash
# ECDSA configuration
JWT_ALGORITHM=ES256
JWT_PUBLIC_KEY_PATH=certs/jwt/ec_public.pem
JWT_PRIVATE_KEY_PATH=certs/jwt/ec_private.pem
JWT_AUDIENCE=mcpgateway-api
JWT_ISSUER=mcpgateway
JWT_AUDIENCE_VERIFICATION=true
```

#### Generate ECDSA Keys

```bash
# Option 1: Use Makefile (Recommended)
make certs-jwt-ecdsa             # Generates certs/jwt/{ec_private,ec_public}.pem with proper permissions

# Option 2: Manual generation
mkdir -p certs/jwt
openssl ecparam -genkey -name prime256v1 -noout -out certs/jwt/ec_private.pem
openssl ec -in certs/jwt/ec_private.pem -pubout -out certs/jwt/ec_public.pem
chmod 600 certs/jwt/ec_private.pem
chmod 644 certs/jwt/ec_public.pem
```

### Dynamic Client Registration (DCR)

For scenarios where JWT audience varies by client:

```bash
JWT_ALGORITHM=RS256
JWT_PUBLIC_KEY_PATH=certs/jwt/public.pem
JWT_PRIVATE_KEY_PATH=certs/jwt/private.pem
JWT_AUDIENCE_VERIFICATION=false         # Disable audience validation for DCR
JWT_ISSUER_VERIFICATION=false           # Disable issuer validation for DCR
JWT_ISSUER=your-identity-provider
```

### Security Considerations

- **Key Storage**: Store private keys securely, never commit to version control
- **Permissions**: Set restrictive file permissions (600) on private keys
- **Key Rotation**: Implement regular key rotation procedures
- **Path Security**: Use absolute paths or secure relative paths for key files
- **Algorithm Choice**:
  - Use RS256 for broad compatibility
  - Use ES256 for better performance and smaller signatures
  - Use HS256 only for simple, single-service deployments

---

## 🐳 Container Configuration

### Docker Environment File

Create a `.env` file for Docker deployments:

```bash
# .env file for Docker
HOST=0.0.0.0
PORT=4444
DATABASE_URL=mysql+pymysql://mysql:changeme@mysql:3306/mcp
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=my-secret-key
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
```

### Docker Compose with MySQL

```yaml
version: "3.9"

services:
  gateway:
    image: ghcr.io/ibm/mcp-context-forge:latest
    ports:

      - "4444:4444"
    environment:

      - DATABASE_URL=mysql+pymysql://mysql:changeme@mysql:3306/mcp
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET_KEY=my-secret-key
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_started

  mysql:
    image: mysql:8
    environment:

      - MYSQL_ROOT_PASSWORD=mysecretpassword
      - MYSQL_DATABASE=mcp
      - MYSQL_USER=mysql
      - MYSQL_PASSWORD=changeme
    volumes:

      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 30s
      timeout: 10s
      retries: 5

  redis:
    image: redis:7
    volumes:

      - redis_data:/data

volumes:
  mysql_data:
  redis_data:
```

---

## ☸️ Kubernetes Configuration

### ConfigMap Example

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcpgateway-config
data:
  DATABASE_URL: "mysql+pymysql://mysql:changeme@mysql-service:3306/mcp"
  REDIS_URL: "redis://redis-service:6379/0"
  JWT_SECRET_KEY: "your-secret-key"
  BASIC_AUTH_USER: "admin"
  BASIC_AUTH_PASSWORD: "changeme"
  MCPGATEWAY_UI_ENABLED: "true"
  MCPGATEWAY_ADMIN_API_ENABLED: "true"
  LOG_LEVEL: "INFO"
```

### MySQL Service Example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mysql
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mysql
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:

        - name: mysql
          image: mysql:8
          env:

            - name: MYSQL_ROOT_PASSWORD
              value: "mysecretpassword"

            - name: MYSQL_DATABASE
              value: "mcp"

            - name: MYSQL_USER
              value: "mysql"

            - name: MYSQL_PASSWORD
              value: "changeme"
          volumeMounts:

            - name: mysql-storage
              mountPath: /var/lib/mysql
      volumes:

        - name: mysql-storage
          persistentVolumeClaim:
            claimName: mysql-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: mysql-service
spec:
  selector:
    app: mysql
  ports:

    - port: 3306
      targetPort: 3306
```

---

## 🔧 Advanced Configuration

### Performance Tuning

```bash
# Database connection pool
DB_POOL_CLASS=auto               # auto, null (PgBouncer), or queue
DB_POOL_SIZE=200                 # Pool size (QueuePool only)
DB_MAX_OVERFLOW=5                # Overflow connections (QueuePool only)
DB_POOL_TIMEOUT=60               # Connection wait timeout
DB_POOL_RECYCLE=3600             # Recycle connections (seconds)
DB_POOL_PRE_PING=auto            # Validate connections: auto, true, false

# Tool execution
TOOL_TIMEOUT=120
MAX_TOOL_RETRIES=5
TOOL_CONCURRENT_LIMIT=10
```

### Execution Metrics Recording

Control whether execution metrics are recorded to the database:

```bash
DB_METRICS_RECORDING_ENABLED=true   # Record execution metrics (default)
DB_METRICS_RECORDING_ENABLED=false  # Disable execution metrics database writes
```

**What are execution metrics?**

Each MCP operation (tool call, resource read, prompt get, etc.) records one database row with:

- Entity ID (tool_id, resource_id, etc.)
- Timestamp
- Response time (seconds)
- Success/failure status
- Error message (if failed)
- Interaction type (A2A metrics only)

**When disabled:**

- No new rows written to `ToolMetric`, `ResourceMetric`, `PromptMetric`, `ServerMetric`, `A2AAgentMetric` tables
- Existing metrics remain queryable until cleanup removes them
- Cleanup and rollup services still run (they process existing data)
- Admin UI metrics pages show no new data

**Use cases for disabling:**

- External observability platforms handle all metrics (ELK, Datadog, Splunk, Grafana)
- Minimal database footprint deployments
- High-throughput environments where per-operation DB writes are costly

**Related settings (separate systems):**

| Setting | What it controls |
|---------|------------------|
| `METRICS_AGGREGATION_ENABLED` | Log aggregation into `PerformanceMetric` table |
| `ENABLE_METRICS` | Prometheus `/metrics` endpoint |
| `OBSERVABILITY_METRICS_ENABLED` | Internal observability system |

To fully minimize metrics database writes, disable both:

```bash
DB_METRICS_RECORDING_ENABLED=false   # Disable execution metrics
METRICS_AGGREGATION_ENABLED=false    # Disable log aggregation
```

### Metrics Cleanup and Rollup

!!! tip "Automatic Metrics Management"
    MCP Gateway automatically manages metrics data to prevent unbounded table growth while preserving historical analytics through hourly rollups.

#### Understanding Raw vs Rollup Metrics

**Raw metrics** store individual execution events (timestamp, response time, success/failure, error message). **Hourly rollups** aggregate these into summary statistics (counts, averages, p50/p95/p99 percentiles).

| Use Case | Raw Metrics Needed? |
|----------|---------------------|
| Dashboard charts (latency percentiles) | No - rollups have p50/p95/p99 |
| Error rate monitoring | No - rollups have success/failure counts |
| Debugging specific failures | Yes - need exact error messages |
| Identifying slowest requests | Yes - need individual rows |

#### External Observability Integration

If you use external observability platforms (ELK Stack, Datadog, Splunk, Grafana/Loki, CloudWatch, OpenTelemetry), raw metrics in the gateway database are typically redundant. Your external platform handles:

- Detailed request logs and traces
- Error message search and filtering
- Individual request debugging
- Compliance audit trails

With external observability, the gateway's hourly rollups provide efficient aggregated analytics, while raw metrics can be deleted quickly (1 hour default).

#### Configuration Reference

**Cleanup Settings:**

```bash
METRICS_CLEANUP_ENABLED=true           # Enable automatic cleanup (default: true)
METRICS_CLEANUP_INTERVAL_HOURS=1       # Hours between cleanup runs (default: 1)
METRICS_RETENTION_DAYS=7               # Fallback retention when rollup disabled (default: 7)
METRICS_CLEANUP_BATCH_SIZE=10000       # Batch size for deletion (default: 10000)
```

**Rollup Settings:**

```bash
METRICS_ROLLUP_ENABLED=true            # Enable hourly rollup (default: true)
METRICS_ROLLUP_INTERVAL_HOURS=1        # Hours between rollup runs (default: 1)
METRICS_ROLLUP_RETENTION_DAYS=365      # Rollup data retention (default: 365)
METRICS_ROLLUP_LATE_DATA_HOURS=1       # Hours to re-process for late data (default: 1)
```

**Raw Metrics Deletion (when rollups exist):**

```bash
METRICS_DELETE_RAW_AFTER_ROLLUP=true   # Delete raw after rollup (default: true)
METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS=1  # Hours before deletion (default: 1)
```

**Performance Optimization (PostgreSQL):**

```bash
USE_POSTGRESDB_PERCENTILES=true  # Use PostgreSQL-native percentile_cont (default: true)
YIELD_BATCH_SIZE=1000            # Rows per batch for streaming queries (default: 1000)
```

When `USE_POSTGRESDB_PERCENTILES=true` (default), PostgreSQL uses native `percentile_cont()` for p50/p95/p99 calculations, which is 5-10x faster than Python-based percentile computation. For SQLite or when disabled, falls back to Python linear interpolation.

`YIELD_BATCH_SIZE` controls memory usage by streaming query results in batches instead of loading all rows into RAM at once.

#### Configuration Examples

**Default (recommended for most deployments):**
Raw metrics deleted after 1 hour, hourly rollups retained for 1 year.

**Without external observability (need debugging from raw data):**
```bash
METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS=168  # Keep raw data 7 days for debugging
```

**Disable raw deletion (compliance/audit requirements):**
```bash
METRICS_DELETE_RAW_AFTER_ROLLUP=false   # Keep all raw metrics
METRICS_RETENTION_DAYS=90               # Delete raw after 90 days via cleanup
```

**Admin API Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics/cleanup` | POST | Trigger manual cleanup |
| `/api/metrics/rollup` | POST | Trigger manual rollup |
| `/api/metrics/stats` | GET | Get cleanup/rollup statistics |
| `/api/metrics/config` | GET | Get current configuration |

**Deletion behavior:**
- Deleted tools/resources/prompts/servers are removed from Top Performers by default, but historical rollups remain for reporting.
- To permanently erase metrics for a deleted entity, use the Admin UI delete prompt and choose **Purge metrics**, or call the delete endpoints with `?purge_metrics=true`.
- Purge deletes use batched deletes sized by `METRICS_CLEANUP_BATCH_SIZE` to reduce long table locks on large datasets.

See [ADR-030: Metrics Cleanup and Rollup](../architecture/adr/030-metrics-cleanup-rollup.md) for architecture details.

### Security Hardening

```bash
# Enable all security features
SECURITY_HEADERS_ENABLED=true
CORS_ALLOW_CREDENTIALS=false
AUTH_REQUIRED=true
REQUIRE_TOKEN_EXPIRATION=true
TOKEN_EXPIRY=60
```

### OpenTelemetry Observability

```bash
# OpenTelemetry (Phoenix, Jaeger, etc.)
OTEL_ENABLE_OBSERVABILITY=true
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_SERVICE_NAME=mcp-gateway
```

### Internal Observability System

MCP Gateway includes a built-in observability system that stores traces and metrics in the database, providing performance analytics and error tracking through the Admin UI.

```bash
# Enable internal observability (database-backed tracing)
OBSERVABILITY_ENABLED=false

# Automatically trace HTTP requests
OBSERVABILITY_TRACE_HTTP_REQUESTS=true

# Trace retention (days)
OBSERVABILITY_TRACE_RETENTION_DAYS=7

# Maximum traces to retain (prevents unbounded growth)
OBSERVABILITY_MAX_TRACES=100000

# Trace sampling rate (0.0-1.0)
# 1.0 = trace everything, 0.1 = trace 10% of requests
OBSERVABILITY_SAMPLE_RATE=1.0

# Paths to include for tracing (JSON array of regex patterns)
OBSERVABILITY_INCLUDE_PATHS=["^/rpc/?$","^/sse$","^/message$","^/mcp(?:/|$)","^/servers/[^/]+/mcp/?$","^/servers/[^/]+/sse$","^/servers/[^/]+/message$","^/a2a(?:/|$)"]

# Paths to exclude from tracing (JSON array of regex patterns, applied after include patterns)
OBSERVABILITY_EXCLUDE_PATHS=["/health","/healthz","/ready","/metrics","/static/.*"]

# Enable metrics collection
OBSERVABILITY_METRICS_ENABLED=true

# Enable event logging within spans
OBSERVABILITY_EVENTS_ENABLED=true
```

See the [Internal Observability Guide](observability/internal-observability.md) for detailed usage instructions including Admin UI dashboards, performance metrics, and trace analysis.

---

## 📚 Related Documentation

- [Docker Compose Deployment](../deployment/compose.md)
- [Local Development Setup](../deployment/local.md)
- [Kubernetes Deployment](../deployment/kubernetes.md)
- [Backup & Restore](backup.md)
- [Logging Configuration](logging.md)
