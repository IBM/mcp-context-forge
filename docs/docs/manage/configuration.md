# Configuration Reference

This guide provides comprehensive configuration options for MCP Gateway, including database setup, environment variables, and deployment-specific settings.

---

## 🗄 Database Configuration

MCP Gateway supports multiple database backends with full feature parity across all supported systems.

### Supported Databases

| Database    | Support Level | Connection String Example                                    | Notes                          |
|-------------|---------------|--------------------------------------------------------------|--------------------------------|
| SQLite      | ✅ Full       | `sqlite:///./mcp.db`                                        | Default, file-based            |
| PostgreSQL  | ✅ Full       | `postgresql://postgres:changeme@localhost:5432/mcp`         | Recommended for production     |
| MariaDB     | ✅ Full       | `mysql+pymysql://mysql:changeme@localhost:3306/mcp`         | **36+ tables**, MariaDB 12.0+ |
| MySQL       | ✅ Full       | `mysql+pymysql://admin:changeme@localhost:3306/mcp`         | Alternative MySQL variant      |
| MongoDB     | ✅ Full       | `mongodb://admin:changeme@localhost:27017/mcp`              | NoSQL document store           |

### MariaDB/MySQL Setup Details

!!! success "MariaDB & MySQL Full Support"
    MariaDB and MySQL are **fully supported** alongside SQLite and PostgreSQL:

    - **36+ database tables** work perfectly with MariaDB 12.0+ and MySQL 8.4+
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
DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp          # MySQL
DATABASE_URL=postgresql://postgres:changeme@localhost:5432/mcp          # PostgreSQL
DATABASE_URL=mongodb://admin:changeme@localhost:27017/mcp               # MongoDB

# Connection pool settings (optional)
DB_POOL_SIZE=200
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=60
DB_POOL_RECYCLE=3600
DB_MAX_RETRIES=5
DB_RETRY_INTERVAL_MS=2000
```

### Server Configuration

```bash
# Network binding & runtime
HOST=0.0.0.0
PORT=4444
ENVIRONMENT=development
APP_DOMAIN=localhost
APP_ROOT_PATH=

# TLS helper (run-gunicorn.sh)
# SSL=true CERT_FILE=certs/cert.pem KEY_FILE=certs/key.pem ./run-gunicorn.sh
```

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
REQUIRE_TOKEN_EXPIRATION=true

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

# Federation & Discovery
FEDERATION_ENABLED=true
FEDERATION_DISCOVERY=true
FEDERATION_PEERS=["https://gateway-1.internal", "https://gateway-2.internal"]
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

# Cache TTL (seconds)
SESSION_TTL=3600
MESSAGE_TTL=600
RESOURCE_CACHE_TTL=1800
```

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
```

### Development & Debug

```bash
# Development Mode
ENVIRONMENT=development             # development, staging, production
DEV_MODE=true
RELOAD=true
DEBUG=true

# Observability
OTEL_ENABLE_OBSERVABILITY=true
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

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
DB_POOL_SIZE=200
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=60
DB_POOL_RECYCLE=3600

# Tool execution
TOOL_TIMEOUT=120
MAX_TOOL_RETRIES=5
TOOL_CONCURRENT_LIMIT=10
```

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

# Paths to exclude from tracing (comma-separated regex patterns)
OBSERVABILITY_EXCLUDE_PATHS=/health,/healthz,/ready,/metrics,/static/.*

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
