# Configuration Reference

This guide provides comprehensive configuration options for MCP Gateway, including database setup, environment variables, and deployment-specific settings.

---

## 🔐 Required: Change Before Use

These variables have insecure defaults and **must be changed** before production deployment:

| Variable | Description | Default | Action Required |
|----------|-------------|---------|-----------------|
| `JWT_SECRET_KEY` | Secret key for signing JWT tokens | `my-test-key` | Generate with `openssl rand -hex 32` |
| `AUTH_ENCRYPTION_SECRET` | Passphrase for encrypting stored credentials | `my-test-salt` | Generate with `openssl rand -hex 32` |
| `BASIC_AUTH_USER` | Username for HTTP Basic auth | `admin` | Change for production |
| `BASIC_AUTH_PASSWORD` | Password for HTTP Basic auth | `changeme` | Set a strong password |
| `PLATFORM_ADMIN_EMAIL` | Email for bootstrap admin user | `admin@example.com` | Use real admin email |
| `PLATFORM_ADMIN_PASSWORD` | Password for bootstrap admin user | `changeme` | Set a strong password |
| `DEFAULT_USER_PASSWORD` | Default password for new users | `changeme` | Set a strong password |

Copy [.env.example](https://github.com/IBM/mcp-context-forge/blob/main/.env.example) to `.env` and update these values.

!!! warning "Startup Validation"
    If any required `.env` variable is missing or invalid, the gateway will fail fast at startup with a validation error via Pydantic.

### 🔒 Security Defaults (Secure by Default)

These settings are enabled by default for security—only disable for backward compatibility:

| Variable | Description | Default |
|----------|-------------|---------|
| `REQUIRE_JTI` | Require JTI claim in tokens for revocation support | `true` |
| `REQUIRE_TOKEN_EXPIRATION` | Require exp claim in tokens | `true` |
| `PUBLIC_REGISTRATION_ENABLED` | Allow public user self-registration | `false` |
| `PROTECT_ALL_ADMINS` | Prevent any admin from being demoted or deactivated via API/UI | `true` |

### ⚙️ Project Defaults (Dev Setup)

These values in `.env.example` differ from code defaults to provide a working local/dev setup:

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Bind address | `0.0.0.0` |
| `MCPGATEWAY_UI_ENABLED` | Enable Admin UI dashboard | `true` |
| `MCPGATEWAY_ADMIN_API_ENABLED` | Enable Admin API endpoints | `true` |
| `DATABASE_URL` | SQLAlchemy connection URL | `sqlite:///./mcp.db` |

---

## 🗄️ Database Configuration

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

## 🔧 Environment Variables Reference

### Basic Settings

| Setting            | Description                              | Default                | Options                |
|--------------------|------------------------------------------|------------------------|------------------------|
| `APP_NAME`         | Gateway / OpenAPI title                  | `MCP_Gateway`          | string                 |
| `HOST`             | Bind address for the app                 | `127.0.0.1`            | IPv4/IPv6              |
| `PORT`             | Port the server listens on               | `4444`                 | 1-65535                |
| `CLIENT_MODE`      | Client-only mode for gateway-as-client   | `false`                | bool                   |
| `DATABASE_URL`     | SQLAlchemy connection URL                | `sqlite:///./mcp.db`   | any SQLAlchemy dialect |
| `APP_ROOT_PATH`    | Subpath prefix for app (e.g. `/gateway`) | (empty)                | string                 |
| `TEMPLATES_DIR`    | Path to Jinja2 templates                 | `mcpgateway/templates` | path                   |
| `STATIC_DIR`       | Path to static files                     | `mcpgateway/static`    | path                   |
| `PROTOCOL_VERSION` | MCP protocol version supported           | `2025-06-18`           | string                 |
| `FORGE_CONTENT_TYPE` | Content-Type for outgoing requests to Forge | `application/json`  | `application/json`, `application/x-www-form-urlencoded` |

!!! tip "Subpath Deployment"
    Use `APP_ROOT_PATH=/foo` if reverse-proxying under a subpath like `https://host.com/foo/`.

### Authentication

| Setting                     | Description                                                                  | Default             | Options     |
|-----------------------------|------------------------------------------------------------------------------|---------------------|-------------|
| `BASIC_AUTH_USER`           | Username for HTTP Basic authentication (when enabled)                        | `admin`             | string      |
| `BASIC_AUTH_PASSWORD`       | Password for HTTP Basic authentication (when enabled)                        | `changeme`          | string      |
| `API_ALLOW_BASIC_AUTH`      | Enable Basic auth for API endpoints (disabled by default for security)       | `false`             | bool        |
| `DOCS_ALLOW_BASIC_AUTH`     | Enable Basic auth for docs endpoints (disabled by default)                   | `false`             | bool        |
| `PLATFORM_ADMIN_EMAIL`      | Email for bootstrap platform admin user (auto-created with admin privileges) | `admin@example.com` | string      |
| `AUTH_REQUIRED`             | Require authentication for all API routes                                    | `true`              | bool        |
| `JWT_ALGORITHM`             | Algorithm used to sign the JWTs (`HS256` is default, HMAC-based)             | `HS256`             | PyJWT algs  |
| `JWT_SECRET_KEY`            | Secret key used to **sign JWT tokens** for API access                        | `my-test-key`       | string      |
| `JWT_PUBLIC_KEY_PATH`       | If an asymmetric algorithm is used, a public key is required                 | (empty)             | path to pem |
| `JWT_PRIVATE_KEY_PATH`      | If an asymmetric algorithm is used, a private key is required                | (empty)             | path to pem |
| `JWT_AUDIENCE`              | JWT audience claim for token validation                                      | `mcpgateway-api`    | string      |
| `JWT_AUDIENCE_VERIFICATION` | Disables jwt audience verification (useful for DCR)                          | `true`              | boolean     |
| `JWT_ISSUER_VERIFICATION`   | Disables jwt issuer verification (useful for custom auth)                    | `true`              | boolean     |
| `JWT_ISSUER`                | JWT issuer claim for token validation                                        | `mcpgateway`        | string      |
| `TOKEN_EXPIRY`              | Expiry of generated JWTs in minutes                                          | `10080`             | int > 0     |
| `REQUIRE_TOKEN_EXPIRATION`  | Require all JWT tokens to have expiration claims                             | `true`              | bool        |
| `REQUIRE_JTI`               | Require JTI (JWT ID) claim in all tokens for revocation support              | `true`              | bool        |
| `REQUIRE_USER_IN_DB`        | Require all authenticated users to exist in the database                     | `false`             | bool        |
| `EMBED_ENVIRONMENT_IN_TOKENS` | Embed environment claim in gateway-issued JWTs                             | `false`             | bool        |
| `VALIDATE_TOKEN_ENVIRONMENT` | Reject tokens with mismatched environment claim                             | `false`             | bool        |
| `AUTH_ENCRYPTION_SECRET`    | Passphrase used to derive AES key for encrypting tool auth headers           | `my-test-salt`      | string      |
| `OAUTH_REQUEST_TIMEOUT`     | OAuth request timeout in seconds                                             | `30`                | int > 0     |
| `OAUTH_MAX_RETRIES`         | Maximum retries for OAuth token requests                                     | `3`                 | int > 0     |
| `OAUTH_DEFAULT_TIMEOUT`     | Default OAuth token timeout in seconds                                       | `3600`              | int > 0     |
| `INSECURE_ALLOW_QUERYPARAM_AUTH` | Enable query parameter authentication for gateways (see security warning) | `false`             | bool        |
| `INSECURE_QUERYPARAM_AUTH_ALLOWED_HOSTS` | JSON array of hosts allowed to use query param auth               | `[]`                | JSON array  |

!!! warning "Query Parameter Authentication (INSECURE)"
    The `INSECURE_ALLOW_QUERYPARAM_AUTH` setting enables API key authentication via URL query parameters. This is inherently insecure (CWE-598) as API keys may appear in proxy logs, browser history, and server access logs. Only enable this when the upstream MCP server (e.g., Tavily) requires this authentication method. Always configure `INSECURE_QUERYPARAM_AUTH_ALLOWED_HOSTS` to restrict which hosts can use this feature.

!!! info "Basic Authentication"
    **Basic Authentication is DISABLED by default** for security. `BASIC_AUTH_USER`/`PASSWORD` are only used when Basic auth is explicitly enabled:

    - `API_ALLOW_BASIC_AUTH=true` - Enable for API endpoints (e.g., `/api/metrics/*`)
    - `DOCS_ALLOW_BASIC_AUTH=true` - Enable for docs endpoints (`/docs`, `/redoc`)

    **Recommended:** Use JWT tokens instead of Basic auth:
    ```bash
    export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token ...)
    curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/api/...
    ```

!!! tip "JWT Token Generation"
    `JWT_SECRET_KEY` is used to sign JSON Web Tokens. Generate tokens via:
    ```bash
    export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key)
    ```

### UI Features

For detailed guidance on embedding and section customization, see [Admin UI Customization](admin-ui-customization.md).

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `MCPGATEWAY_UI_ENABLED`        | Enable the interactive Admin dashboard | `false` | bool    |
| `MCPGATEWAY_ADMIN_API_ENABLED` | Enable API endpoints for admin ops     | `false` | bool    |
| `MCPGATEWAY_UI_AIRGAPPED`      | Use local CDN assets for airgapped deployments | `false` | bool |
| `MCPGATEWAY_UI_EMBEDDED`       | Embedded UI mode (hides logout + team selector by default) | `false` | bool |
| `MCPGATEWAY_UI_HIDE_SECTIONS`  | CSV/JSON list of UI sections to hide (overview, servers, gateways, tools, prompts, resources, roots, mcp-registry, runtime, metrics, plugins, export-import, logs, version-info, maintenance, teams, users, agents, tokens, settings) | `[]` | CSV/JSON list |
| `MCPGATEWAY_UI_HIDE_HEADER_ITEMS` | CSV/JSON list of header items to hide (logout, team_selector, user_identity, theme_toggle) | `[]` | CSV/JSON list |
| `MCPGATEWAY_BULK_IMPORT_ENABLED` | Enable bulk import endpoint for tools | `true`  | bool    |
| `MCPGATEWAY_BULK_IMPORT_MAX_TOOLS` | Maximum number of tools per bulk import request | `200` | int |
| `MCPGATEWAY_BULK_IMPORT_RATE_LIMIT` | Rate limit for bulk import endpoint (requests per minute) | `10` | int |
| `MCPGATEWAY_UI_TOOL_TEST_TIMEOUT` | Tool test timeout in milliseconds for the admin UI | `60000` | int |

!!! note "Per-Request UI Hiding"
    For embedded contexts, you can also hide UI sections per-request by adding `?ui_hide=...` to the Admin UI URL.

    Example:
    ```text
    /admin/?ui_hide=prompts,resources,teams
    ```

    The query value is stored in an HttpOnly cookie with a 30-day lifetime. Clear it by visiting:
    ```text
    /admin/?ui_hide=
    ```

!!! tip "Production Settings"
    Set both UI and Admin API to `false` to disable management UI and APIs in production.

### A2A (Agent-to-Agent) Features

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `MCPGATEWAY_A2A_ENABLED`       | Enable A2A agent features             | `true`  | bool    |
| `MCPGATEWAY_A2A_MAX_AGENTS`    | Maximum number of A2A agents allowed  | `100`   | int     |
| `MCPGATEWAY_A2A_DEFAULT_TIMEOUT` | Default timeout for A2A HTTP requests (seconds) | `30` | int |
| `MCPGATEWAY_A2A_MAX_RETRIES`   | Maximum retry attempts for A2A calls  | `3`     | int     |
| `MCPGATEWAY_A2A_METRICS_ENABLED` | Enable A2A agent metrics collection | `true`  | bool    |

**Configuration Effects:**

- `MCPGATEWAY_A2A_ENABLED=false`: Completely disables A2A features (API endpoints return 404, admin tab hidden)
- `MCPGATEWAY_A2A_METRICS_ENABLED=false`: Disables metrics collection while keeping functionality

### Direct Proxy Mode

| Setting                              | Description                                    | Default | Options |
| ------------------------------------ | ---------------------------------------------- | ------- | ------- |
| `MCPGATEWAY_DIRECT_PROXY_ENABLED`    | Enable direct_proxy gateway mode               | `false` | bool    |
| `MCPGATEWAY_DIRECT_PROXY_TIMEOUT`    | Timeout for direct proxy operations (seconds)  | `30`    | int     |

**Configuration Effects:**

- `MCPGATEWAY_DIRECT_PROXY_ENABLED=false` (default): Gateways cannot use `gateway_mode=direct_proxy`; existing ones fall back to cache mode
- `MCPGATEWAY_DIRECT_PROXY_ENABLED=true`: Enables pass-through MCP operations bypassing the caching layer

**Usage:** Register a gateway with `"gateway_mode": "direct_proxy"`, then send requests with the `X-Context-Forge-Gateway-Id` header set to the gateway's ID. All MCP operations (tools/list, tools/call, resources/list, resources/read) will be proxied directly to the remote server.

### ToolOps

ToolOps streamlines the entire workflow by enabling seamless tool enrichment, automated test case generation, and comprehensive tool validation.

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `TOOLOPS_ENABLED`             | Enable ToolOps functionality          | `false` | bool    |

### LLM Chat MCP Client

The LLM Chat MCP Client allows you to interact with MCP servers using conversational AI from multiple LLM providers.

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `LLMCHAT_ENABLED`             | Enable LLM Chat functionality          | `false` | bool    |
| `LLM_PROVIDER`                | LLM provider selection                 | `azure_openai` | `azure_openai`, `openai`, `anthropic`, `aws_bedrock`, `ollama` |

**Azure OpenAI Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `AZURE_OPENAI_ENDPOINT`       | Azure OpenAI endpoint URL              | (none)  | string  |
| `AZURE_OPENAI_API_KEY`        | Azure OpenAI API key                   | (none)  | string  |
| `AZURE_OPENAI_DEPLOYMENT`     | Azure OpenAI deployment name           | (none)  | string  |
| `AZURE_OPENAI_API_VERSION`    | Azure OpenAI API version               | `2024-02-15-preview` | string |
| `AZURE_OPENAI_TEMPERATURE`    | Sampling temperature                   | `0.7`   | float (0.0-2.0) |
| `AZURE_OPENAI_MAX_TOKENS`     | Maximum tokens to generate             | (none)  | int     |

**OpenAI Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `OPENAI_API_KEY`              | OpenAI API key                         | (none)  | string  |
| `OPENAI_MODEL`                | OpenAI model name                      | `gpt-4o-mini` | string |
| `OPENAI_BASE_URL`             | Base URL for OpenAI-compatible endpoints | (none) | string  |
| `OPENAI_TEMPERATURE`          | Sampling temperature                   | `0.7`   | float (0.0-2.0) |
| `OPENAI_MAX_RETRIES`          | Maximum number of retries              | `2`     | int     |

**Anthropic Claude Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `ANTHROPIC_API_KEY`           | Anthropic API key                      | (none)  | string  |
| `ANTHROPIC_MODEL`             | Claude model name                      | `claude-3-5-sonnet-20241022` | string |
| `ANTHROPIC_TEMPERATURE`       | Sampling temperature                   | `0.7`   | float (0.0-1.0) |
| `ANTHROPIC_MAX_TOKENS`        | Maximum tokens to generate             | `4096`  | int     |
| `ANTHROPIC_MAX_RETRIES`       | Maximum number of retries              | `2`     | int     |

**AWS Bedrock Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `AWS_BEDROCK_MODEL_ID`        | Bedrock model ID                       | (none)  | string  |
| `AWS_BEDROCK_REGION`          | AWS region name                        | `us-east-1` | string |
| `AWS_BEDROCK_TEMPERATURE`     | Sampling temperature                   | `0.7`   | float (0.0-1.0) |
| `AWS_BEDROCK_MAX_TOKENS`      | Maximum tokens to generate             | `4096`  | int     |
| `AWS_ACCESS_KEY_ID`           | AWS access key ID (optional)           | (none)  | string  |
| `AWS_SECRET_ACCESS_KEY`       | AWS secret access key (optional)       | (none)  | string  |
| `AWS_SESSION_TOKEN`           | AWS session token (optional)           | (none)  | string  |

**IBM WatsonX AI Configuration:**

| Setting                 | Description                     | Default                        | Options         |
| ----------------------- | --------------------------------| ------------------------------ | ----------------|
| `WATSONX_URL`           | watsonx url                     | (none)                         | string          |
| `WATSONX_APIKEY`        | API key                         | (none)                         | string          |
| `WATSONX_PROJECT_ID`    | Project Id for WatsonX          | (none)                         | string          |
| `WATSONX_MODEL_ID`      | Watsonx model id                | `ibm/granite-13b-chat-v2`      | string          |
| `WATSONX_TEMPERATURE`   | temperature (optional)          | `0.7`                          | float (0.0-1.0) |

**Ollama Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `OLLAMA_BASE_URL`             | Ollama base URL                        | `http://localhost:11434` | string |
| `OLLAMA_MODEL`                | Ollama model name                      | `llama3.2` | string |
| `OLLAMA_TEMPERATURE`          | Sampling temperature                   | `0.7`   | float (0.0-2.0) |

**Provider Requirements:**

- **Azure OpenAI**: Requires `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and `AZURE_OPENAI_DEPLOYMENT`
- **OpenAI**: Requires `OPENAI_API_KEY`
- **Anthropic**: Requires `ANTHROPIC_API_KEY` and `pip install langchain-anthropic`
- **AWS Bedrock**: Requires `AWS_BEDROCK_MODEL_ID` and `pip install langchain-aws boto3`. Uses AWS credential chain if explicit credentials not provided.
- **IBM WatsonX AI**: Requires `WATSONX_URL`, `WATSONX_APIKEY`, `WATSONX_PROJECT_ID`, `WATSONX_MODEL_ID` and `pip install langchain-ibm`
- **Ollama**: Requires local Ollama instance running (default: `http://localhost:11434`)

**Redis Configurations for Chat Sessions:**

| Setting                              | Description                                | Default | Options |
| -------------------------------------| -------------------------------------------| ------- | ------- |
| `LLMCHAT_SESSION_TTL`                | Seconds for active_session key TTL         | `300`   | int     |
| `LLMCHAT_SESSION_LOCK_TTL`           | Seconds for lock expiry                    | `30`    | int     |
| `LLMCHAT_SESSION_LOCK_RETRIES`       | How many times to poll while waiting       | `10`    | int     |
| `LLMCHAT_SESSION_LOCK_WAIT`          | Seconds between polls                      | `0.2`   | float   |
| `LLMCHAT_CHAT_HISTORY_TTL`           | Seconds for chat history expiry            | `3600`  | int     |
| `LLMCHAT_CHAT_HISTORY_MAX_MESSAGES`  | Maximum message history to store per user  | `50`    | int     |

### LLM Settings (Internal API)

The LLM Settings feature enables MCP Gateway to act as a unified LLM provider with an OpenAI-compatible API.

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `LLM_API_PREFIX`              | API prefix for internal LLM endpoints  | `/v1`   | string  |
| `LLM_REQUEST_TIMEOUT`         | Request timeout for LLM API calls (seconds) | `120` | int     |
| `LLM_STREAMING_ENABLED`       | Enable streaming responses             | `true`  | bool    |
| `LLM_HEALTH_CHECK_INTERVAL`   | Provider health check interval (seconds) | `300` | int     |

**Gateway Provider Settings:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `GATEWAY_MODEL`               | Default model to use                   | `gpt-4o` | string |
| `GATEWAY_BASE_URL`            | Base URL for gateway LLM API           | (auto)  | string  |
| `GATEWAY_TEMPERATURE`         | Sampling temperature                   | `0.7`   | float   |

**API Endpoints:**

```bash
# List available models
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/v1/models

# Chat completion
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}' \
  http://localhost:4444/v1/chat/completions
```

### Email-Based Authentication & User Management

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `EMAIL_AUTH_ENABLED`          | Enable email-based authentication system         | `true`                | bool    |
| `PLATFORM_ADMIN_EMAIL`        | Email for bootstrap platform admin user          | `admin@example.com`   | string  |
| `PLATFORM_ADMIN_PASSWORD`     | Password for bootstrap platform admin user       | `changeme`            | string  |
| `PLATFORM_ADMIN_FULL_NAME`    | Full name for bootstrap platform admin user      | `Platform Administrator` | string |
| `DEFAULT_USER_PASSWORD`       | Default password for newly created users         | `changeme`            | string  |
| `ARGON2ID_TIME_COST`          | Argon2id time cost (iterations)                  | `3`                   | int > 0 |
| `ARGON2ID_MEMORY_COST`        | Argon2id memory cost in KiB                      | `65536`               | int > 0 |
| `ARGON2ID_PARALLELISM`        | Argon2id parallelism (threads)                   | `1`                   | int > 0 |
| `PASSWORD_MIN_LENGTH`         | Minimum password length                           | `8`                   | int > 0 |
| `PASSWORD_REQUIRE_UPPERCASE`  | Require uppercase letters in passwords           | `true`                | bool    |
| `PASSWORD_REQUIRE_LOWERCASE`  | Require lowercase letters in passwords           | `true`                | bool    |
| `PASSWORD_REQUIRE_NUMBERS`    | Require numbers in passwords                     | `false`               | bool    |
| `PASSWORD_REQUIRE_SPECIAL`    | Require special characters in passwords          | `true`                | bool    |
| `MAX_FAILED_LOGIN_ATTEMPTS`   | Maximum failed login attempts before lockout     | `10`                  | int > 0 |
| `ACCOUNT_LOCKOUT_DURATION_MINUTES` | Account lockout duration in minutes        | `1`                   | int > 0 |
| `ACCOUNT_LOCKOUT_NOTIFICATION_ENABLED` | Send lockout notification emails      | `true`                | bool    |
| `PASSWORD_RESET_ENABLED`      | Enable self-service forgot-password/reset flow   | `true`                | bool    |
| `PASSWORD_RESET_TOKEN_EXPIRY_MINUTES` | Password reset token expiry window     | `60`                  | int > 0 |
| `PASSWORD_RESET_RATE_LIMIT`   | Max reset requests per email in rate window      | `5`                   | int > 0 |
| `PASSWORD_RESET_RATE_WINDOW_MINUTES` | Password reset rate-limit window        | `15`                  | int > 0 |
| `PASSWORD_RESET_INVALIDATE_SESSIONS` | Invalidate active sessions on reset     | `true`                | bool    |
| `PASSWORD_RESET_MIN_RESPONSE_MS` | Minimum forgot-password response duration    | `250`                 | int >= 0 |
| `PROTECT_ALL_ADMINS`         | Prevent any admin from being demoted or deactivated via API/UI. When false, only the last active admin is protected. | `true` | bool |
| `SMTP_ENABLED`                | Enable SMTP notifications for auth emails        | `false`               | bool    |
| `SMTP_HOST`                   | SMTP host                                         | (none)                | string  |
| `SMTP_PORT`                   | SMTP port                                         | `587`                 | int     |
| `SMTP_USER`                   | SMTP username                                     | (none)                | string  |
| `SMTP_PASSWORD`               | SMTP password                                     | (none)                | string  |
| `SMTP_FROM_EMAIL`             | Sender email address                              | (none)                | string  |
| `SMTP_FROM_NAME`              | Sender display name                               | `MCP Gateway`         | string  |
| `SMTP_USE_TLS`                | Use STARTTLS                                      | `true`                | bool    |
| `SMTP_USE_SSL`                | Use implicit SSL/TLS                              | `false`               | bool    |
| `SMTP_TIMEOUT_SECONDS`        | SMTP timeout in seconds                           | `15`                  | int > 0 |

When `PASSWORD_RESET_ENABLED=false`, self-service forgot/reset endpoints are disabled (`403` on API and disabled/redirected UI flows).
When `SMTP_ENABLED=false`, reset requests are accepted but no email is delivered.

### MCP Client Authentication

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `MCP_CLIENT_AUTH_ENABLED`     | Enable JWT authentication for MCP client operations | `true`            | bool    |
| `MCP_REQUIRE_AUTH`            | Require authentication for /mcp endpoints. If false, unauthenticated requests can access public items only | `false` | bool |
| `TRUST_PROXY_AUTH`            | Trust proxy authentication headers               | `false`               | bool    |
| `PROXY_USER_HEADER`           | Header containing authenticated username from proxy | `X-Authenticated-User` | string |

!!! warning "MCP Access Control Dependencies"
    Full MCP access control (visibility + team scoping + membership validation) requires `MCP_CLIENT_AUTH_ENABLED=true` with valid JWT tokens containing team claims. When `MCP_CLIENT_AUTH_ENABLED=false`, access control relies on `MCP_REQUIRE_AUTH` plus tool/resource visibility only—team membership validation is skipped since there's no JWT to extract teams from.

### SSO (Single Sign-On) Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_ENABLED`                 | Master switch for Single Sign-On authentication  | `false`               | bool    |
| `SSO_AUTO_CREATE_USERS`       | Automatically create users from SSO providers    | `true`                | bool    |
| `SSO_TRUSTED_DOMAINS`         | Trusted email domains (JSON array)               | `[]`                  | JSON array |
| `SSO_PRESERVE_ADMIN_AUTH`     | Preserve local admin authentication when SSO enabled | `true`            | bool    |
| `SSO_REQUIRE_ADMIN_APPROVAL`  | Require admin approval for new SSO registrations | `false`               | bool    |
| `SSO_ISSUERS`                 | Optional JSON array of issuer URLs for SSO providers | (none)            | JSON array |
| `SSO_AUTO_ADMIN_DOMAINS`      | Email domains that automatically get admin privileges | `[]`             | JSON array |

**GitHub OAuth:**

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_GITHUB_ENABLED`          | Enable GitHub OAuth authentication               | `false`               | bool    |
| `SSO_GITHUB_CLIENT_ID`        | GitHub OAuth client ID                           | (none)                | string  |
| `SSO_GITHUB_CLIENT_SECRET`    | GitHub OAuth client secret                       | (none)                | string  |
| `SSO_GITHUB_ADMIN_ORGS`       | GitHub orgs granting admin privileges (JSON)     | `[]`                  | JSON array |

**Google OAuth:**

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_GOOGLE_ENABLED`          | Enable Google OAuth authentication               | `false`               | bool    |
| `SSO_GOOGLE_CLIENT_ID`        | Google OAuth client ID                           | (none)                | string  |
| `SSO_GOOGLE_CLIENT_SECRET`    | Google OAuth client secret                       | (none)                | string  |
| `SSO_GOOGLE_ADMIN_DOMAINS`    | Google admin domains (JSON)                      | `[]`                  | JSON array |

**IBM Security Verify OIDC:**

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_IBM_VERIFY_ENABLED`      | Enable IBM Security Verify OIDC authentication   | `false`               | bool    |
| `SSO_IBM_VERIFY_CLIENT_ID`    | IBM Security Verify client ID                    | (none)                | string  |
| `SSO_IBM_VERIFY_CLIENT_SECRET` | IBM Security Verify client secret               | (none)                | string  |
| `SSO_IBM_VERIFY_ISSUER`       | IBM Security Verify OIDC issuer URL             | (none)                | string  |

**Keycloak OIDC:**

| Setting                              | Description                                      | Default                    | Options |
| ------------------------------------ | ------------------------------------------------ | -------------------------- | ------- |
| `SSO_KEYCLOAK_ENABLED`              | Enable Keycloak OIDC authentication              | `false`                    | bool    |
| `SSO_KEYCLOAK_BASE_URL`             | Keycloak base URL                                | (none)                     | string  |
| `SSO_KEYCLOAK_REALM`                | Keycloak realm name                              | `master`                   | string  |
| `SSO_KEYCLOAK_CLIENT_ID`            | Keycloak client ID                               | (none)                     | string  |
| `SSO_KEYCLOAK_CLIENT_SECRET`        | Keycloak client secret                           | (none)                     | string  |
| `SSO_KEYCLOAK_MAP_REALM_ROLES`      | Map Keycloak realm roles to gateway teams        | `true`                     | bool    |
| `SSO_KEYCLOAK_MAP_CLIENT_ROLES`     | Map Keycloak client roles to gateway RBAC        | `false`                    | bool    |
| `SSO_KEYCLOAK_USERNAME_CLAIM`       | JWT claim for username                           | `preferred_username`       | string  |
| `SSO_KEYCLOAK_EMAIL_CLAIM`          | JWT claim for email                              | `email`                    | string  |
| `SSO_KEYCLOAK_GROUPS_CLAIM`         | JWT claim for groups/roles                       | `groups`                   | string  |

**Microsoft Entra ID OIDC:**

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_ENTRA_ENABLED`           | Enable Microsoft Entra ID OIDC authentication    | `false`               | bool    |
| `SSO_ENTRA_CLIENT_ID`         | Microsoft Entra ID client ID                     | (none)                | string  |
| `SSO_ENTRA_CLIENT_SECRET`     | Microsoft Entra ID client secret                 | (none)                | string  |
| `SSO_ENTRA_TENANT_ID`         | Microsoft Entra ID tenant ID                     | (none)                | string  |

**Generic OIDC Provider (Auth0, Authentik, etc.):**

| Setting                              | Description                                      | Default                    | Options |
| ------------------------------------ | ------------------------------------------------ | -------------------------- | ------- |
| `SSO_GENERIC_ENABLED`               | Enable generic OIDC provider authentication      | `false`                    | bool    |
| `SSO_GENERIC_PROVIDER_ID`           | Provider ID (e.g., keycloak, auth0, authentik)   | (none)                     | string  |
| `SSO_GENERIC_DISPLAY_NAME`          | Display name shown on login page                 | (none)                     | string  |
| `SSO_GENERIC_CLIENT_ID`             | Generic OIDC client ID                           | (none)                     | string  |
| `SSO_GENERIC_CLIENT_SECRET`         | Generic OIDC client secret                       | (none)                     | string  |
| `SSO_GENERIC_AUTHORIZATION_URL`     | Authorization endpoint URL                       | (none)                     | string  |
| `SSO_GENERIC_TOKEN_URL`             | Token endpoint URL                               | (none)                     | string  |
| `SSO_GENERIC_USERINFO_URL`          | Userinfo endpoint URL                            | (none)                     | string  |
| `SSO_GENERIC_ISSUER`                | OIDC issuer URL                                  | (none)                     | string  |
| `SSO_GENERIC_SCOPE`                 | OAuth scopes (space-separated)                   | `openid profile email`     | string  |

**Okta OIDC:**

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_OKTA_ENABLED`            | Enable Okta OIDC authentication                  | `false`               | bool    |
| `SSO_OKTA_CLIENT_ID`          | Okta client ID                                   | (none)                | string  |
| `SSO_OKTA_CLIENT_SECRET`      | Okta client secret                               | (none)                | string  |
| `SSO_OKTA_ISSUER`             | Okta issuer URL                                  | (none)                | string  |

### OAuth 2.0 Dynamic Client Registration (DCR) & PKCE

ContextForge implements **OAuth 2.0 Dynamic Client Registration (RFC 7591)** and **PKCE (RFC 7636)** for seamless integration with OAuth-protected MCP servers.

| Setting                                     | Description                                                    | Default                        | Options       |
|--------------------------------------------|----------------------------------------------------------------|--------------------------------|---------------|
| `DCR_ENABLED`                              | Enable Dynamic Client Registration (RFC 7591)                  | `true`                         | bool          |
| `DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS` | Auto-register when gateway has issuer but no client_id         | `true`                         | bool          |
| `DCR_DEFAULT_SCOPES`                       | Default OAuth scopes to request during DCR                     | `["mcp:read"]`                 | JSON array    |
| `DCR_ALLOWED_ISSUERS`                      | Allowlist of trusted issuer URLs (empty = allow any)           | `[]`                           | JSON array    |
| `DCR_TOKEN_ENDPOINT_AUTH_METHOD`           | Token endpoint auth method                                     | `client_secret_basic`          | `client_secret_basic`, `client_secret_post`, `none` |
| `DCR_METADATA_CACHE_TTL`                   | AS metadata cache TTL in seconds                               | `3600`                         | int           |
| `DCR_CLIENT_NAME_TEMPLATE`                 | Template for client_name in DCR requests                       | `MCP Gateway ({gateway_name})` | string        |
| `DCR_REQUEST_REFRESH_TOKEN_WHEN_UNSUPPORTED` | Request refresh_token when AS omits grant_types_supported    | `false`                        | bool          |
| `OAUTH_DISCOVERY_ENABLED`                  | Enable AS metadata discovery (RFC 8414)                        | `true`                         | bool          |
| `OAUTH_PREFERRED_CODE_CHALLENGE_METHOD`    | PKCE code challenge method                                     | `S256`                         | `S256`, `plain` |

### Personal Teams Configuration

| Setting                                  | Description                                      | Default    | Options |
| ---------------------------------------- | ------------------------------------------------ | ---------- | ------- |
| `AUTO_CREATE_PERSONAL_TEAMS`             | Enable automatic personal team creation for new users | `true`   | bool    |
| `PERSONAL_TEAM_PREFIX`                   | Personal team naming prefix                      | `personal` | string  |
| `MAX_TEAMS_PER_USER`                     | Maximum number of teams a user can belong to    | `50`       | int > 0 |
| `MAX_MEMBERS_PER_TEAM`                   | Maximum number of members per team               | `100`      | int > 0 |
| `INVITATION_EXPIRY_DAYS`                 | Number of days before team invitations expire   | `7`        | int > 0 |
| `REQUIRE_EMAIL_VERIFICATION_FOR_INVITES` | Require email verification for team invitations | `true`     | bool    |

### MCP Server Catalog

| Setting                              | Description                                      | Default            | Options |
| ------------------------------------ | ------------------------------------------------ | ------------------ | ------- |
| `MCPGATEWAY_CATALOG_ENABLED`        | Enable MCP server catalog feature                | `true`             | bool    |
| `MCPGATEWAY_CATALOG_FILE`           | Path to catalog configuration file               | `mcp-catalog.yml`  | string  |
| `MCPGATEWAY_CATALOG_AUTO_HEALTH_CHECK` | Automatically health check catalog servers    | `true`             | bool    |
| `MCPGATEWAY_CATALOG_CACHE_TTL`      | Catalog cache TTL in seconds                     | `3600`             | int > 0 |
| `MCPGATEWAY_CATALOG_PAGE_SIZE`      | Number of catalog servers per page               | `100`              | int > 0 |

### Secure MCP Runtime

See [Secure Runtime Operations](runtime.md) for API usage and deployment flows.

| Setting | Description | Default | Options |
| ------- | ----------- | ------- | ------- |
| `MCPGATEWAY_RUNTIME_ENABLED` | Enable secure runtime API (`/runtimes`) | `false` | bool |
| `RUNTIME_PLATFORM_ADMIN_ONLY` | Restrict runtime API access to platform administrators | `true` | bool |
| `RUNTIME_DEFAULT_BACKEND` | Default deployment backend | `docker` | `docker`, `ibm_code_engine` |
| `RUNTIME_DOCKER_ENABLED` | Enable Docker runtime backend | `true` | bool |
| `RUNTIME_DOCKER_BINARY` | Docker CLI binary path | `docker` | string |
| `RUNTIME_DOCKER_SOCKET` | Docker socket path | `/var/run/docker.sock` | path |
| `RUNTIME_DOCKER_NETWORK` | Default Docker network for runtime containers | (empty) | string |
| `RUNTIME_DOCKER_ALLOWED_REGISTRIES` | Allowlisted image registries for runtime deployment | `["docker.io","ghcr.io"]` | JSON array / CSV |
| `RUNTIME_IBM_CODE_ENGINE_ENABLED` | Enable IBM Code Engine backend | `false` | bool |
| `RUNTIME_IBM_CODE_ENGINE_BINARY` | IBM Cloud CLI binary path | `ibmcloud` | string |
| `RUNTIME_IBM_CODE_ENGINE_REGION` | IBM Code Engine region | (empty) | string |
| `RUNTIME_IBM_CODE_ENGINE_PROJECT` | IBM Code Engine project name | (empty) | string |
| `RUNTIME_IBM_CODE_ENGINE_REGISTRY_SECRET` | Registry secret used for CE deployments | (empty) | string |
| `RUNTIME_CATALOG_REMOTE_URLS` | Remote catalog URLs merged into local catalog | `[]` | JSON array / CSV |
| `RUNTIME_CATALOG_REMOTE_TIMEOUT_SECONDS` | Timeout for remote catalog fetch | `15` | int 1-120 |
| `RUNTIME_APPROVAL_ENABLED` | Enable runtime deployment approvals | `false` | bool |
| `RUNTIME_APPROVAL_REQUIRED_SOURCE_TYPES` | Source types requiring approval | `["github"]` | JSON array / CSV |
| `RUNTIME_APPROVAL_REGISTRY_ALLOWLIST` | Registry prefixes that bypass approval checks | `["docker.io/library","docker.io/mcp"]` | JSON array / CSV |
| `RUNTIME_APPROVAL_REQUIRED_GUARDRAILS_PROFILES` | Guardrail profiles requiring approval | `["unrestricted"]` | JSON array / CSV |
| `RUNTIME_APPROVERS` | Approver users/groups for runtime requests | `[]` | JSON array / CSV |
| `RUNTIME_APPROVAL_TIMEOUT_HOURS` | Approval request expiration window | `48` | int 1-168 |

### Security

| Setting                   | Description                    | Default                                        | Options    |
| ------------------------- | ------------------------------ | ---------------------------------------------- | ---------- |
| `SKIP_SSL_VERIFY`         | Skip upstream TLS verification | `false`                                        | bool       |
| `ENVIRONMENT`             | Deployment environment (affects security defaults) | `development`                              | `development`/`production` |
| `APP_DOMAIN`              | Domain for production CORS origins | `http://localhost:4444`                     | string     |
| `ALLOWED_ORIGINS`         | CORS allow-list                | Auto-configured by environment                 | JSON array |
| `CORS_ENABLED`            | Enable CORS                    | `true`                                         | bool       |
| `CORS_ALLOW_CREDENTIALS`  | Allow credentials in CORS      | `true`                                         | bool       |
| `SECURE_COOKIES`          | Force secure cookie flags     | `true`                                         | bool       |
| `COOKIE_SAMESITE`         | Cookie SameSite attribute      | `lax`                                          | `strict`/`lax`/`none` |
| `SECURITY_HEADERS_ENABLED` | Enable security headers middleware | `true`                                     | bool       |
| `X_FRAME_OPTIONS`         | X-Frame-Options header value   | `DENY`                                         | `DENY`/`SAMEORIGIN`/`""`/`null` |
| `X_CONTENT_TYPE_OPTIONS_ENABLED` | Enable X-Content-Type-Options: nosniff header | `true`                           | bool       |
| `X_XSS_PROTECTION_ENABLED` | Enable X-XSS-Protection header | `true`                                         | bool       |
| `X_DOWNLOAD_OPTIONS_ENABLED` | Enable X-Download-Options: noopen header | `true`                              | bool       |
| `HSTS_ENABLED`            | Enable HSTS header             | `true`                                         | bool       |
| `HSTS_MAX_AGE`            | HSTS max age in seconds        | `31536000`                                     | int        |
| `HSTS_INCLUDE_SUBDOMAINS` | Include subdomains in HSTS header | `true`                                      | bool       |
| `REMOVE_SERVER_HEADERS`   | Remove server identification   | `true`                                         | bool       |
| `MIN_SECRET_LENGTH`       | Minimum length for secret keys (JWT, encryption) | `32`                                | int        |
| `MIN_PASSWORD_LENGTH`     | Minimum length for passwords   | `12`                                           | int        |
| `REQUIRE_STRONG_SECRETS`  | Enforce strong secrets (fail startup on weak secrets) | `false`                        | bool       |

!!! info "CORS Configuration"
    When `ENVIRONMENT=development`, CORS origins are automatically configured for common development ports (3000, 8080, gateway port). In production, origins are constructed from `APP_DOMAIN`. Override with `ALLOWED_ORIGINS`.

!!! info "iframe Embedding"
    The gateway controls iframe embedding through both `X-Frame-Options` header and CSP `frame-ancestors` directive:

    - `X_FRAME_OPTIONS=DENY` (default): Blocks all iframe embedding
    - `X_FRAME_OPTIONS=SAMEORIGIN`: Allows embedding from same domain only
    - `X_FRAME_OPTIONS="ALLOW-ALL"`: Allows embedding from all sources
    - `X_FRAME_OPTIONS=null` or `none`: Completely removes iframe restrictions

### SSRF Protection

MCP Gateway includes **Server-Side Request Forgery (SSRF) protection** to prevent the gateway from being used to access internal resources or cloud metadata services.

| Setting                     | Description                                                      | Default | Options |
| --------------------------- | ---------------------------------------------------------------- | ------- | ------- |
| `SSRF_PROTECTION_ENABLED`   | Master switch for SSRF protection                                | `true`  | bool    |
| `SSRF_ALLOW_LOCALHOST`      | Allow localhost/loopback addresses (127.0.0.0/8, ::1)           | `true`  | bool    |
| `SSRF_ALLOW_PRIVATE_NETWORKS` | Allow RFC 1918 private IPs (10.x, 172.16.x, 192.168.x)        | `true`  | bool    |
| `SSRF_DNS_FAIL_CLOSED`      | Reject URLs when DNS resolution fails                           | `false` | bool    |
| `SSRF_BLOCKED_NETWORKS`     | CIDR ranges always blocked (cloud metadata by default)          | See below | JSON array |
| `SSRF_BLOCKED_HOSTS`        | Hostnames always blocked (case-insensitive)                     | See below | JSON array |

**Default Blocked Networks** (always blocked regardless of other settings):
```json
["169.254.169.254/32", "169.254.169.123/32", "fd00::1/128", "169.254.0.0/16", "fe80::/10"]
```

**Default Blocked Hosts**:
```json
["metadata.google.internal", "metadata.internal"]
```

!!! warning "Cloud Metadata Protection"
    Cloud metadata endpoints (169.254.169.254) are **always blocked by default** to prevent credential exposure in cloud environments (AWS, GCP, Azure). This protects against SSRF attacks that attempt to steal instance credentials.

!!! note "DNS Resolution Behavior"
    The SSRF protection resolves ALL IP addresses for a hostname (both A and AAAA records) and validates each one. If ANY resolved IP is blocked, the request is rejected.

    - **DNS fail-open** (default): Unresolvable hostnames are allowed (hostname blocklist still applies)
    - **DNS fail-closed** (`SSRF_DNS_FAIL_CLOSED=true`): Unresolvable hostnames are rejected

    For maximum security, enable `SSRF_DNS_FAIL_CLOSED=true` in production. Note that DNS rebinding attacks (where DNS changes between validation and connection) require additional mitigations like a dedicated SSRF proxy.

!!! tip "Configuration Modes"
    **Development/Internal Mode** (default): Localhost and private networks allowed, only cloud metadata blocked.
    ```bash
    SSRF_PROTECTION_ENABLED=true
    SSRF_ALLOW_LOCALHOST=true
    SSRF_ALLOW_PRIVATE_NETWORKS=true
    ```

    **Strict Production Mode** (external endpoints only):
    ```bash
    SSRF_PROTECTION_ENABLED=true
    SSRF_ALLOW_LOCALHOST=false
    SSRF_ALLOW_PRIVATE_NETWORKS=false
    ```

    **Custom Blocked Networks** (add additional ranges):
    ```bash
    SSRF_BLOCKED_NETWORKS='["169.254.169.254/32","169.254.0.0/16","100.64.0.0/10"]'
    ```
    The `100.64.0.0/10` range blocks Carrier-Grade NAT (CGNAT) used by some cloud providers.

### Ed25519 Certificate Signing

MCP Gateway supports **Ed25519 digital signatures** for certificate validation and integrity verification.

| Setting                     | Description                                      | Default | Options |
| --------------------------- | ------------------------------------------------ | ------- | ------- |
| `ENABLE_ED25519_SIGNING`    | Enable Ed25519 signing for certificates          | `false` | bool    |
| `ED25519_PRIVATE_KEY`       | Ed25519 private key for signing (PEM format)     | (none)  | string  |
| `PREV_ED25519_PRIVATE_KEY`  | Previous Ed25519 private key for key rotation    | (none)  | string  |

**Key Generation:**

```bash
# Generate a new Ed25519 key pair
python mcpgateway/utils/generate_keys.py
```

### Response Compression

MCP Gateway includes automatic response compression middleware that reduces bandwidth usage by 30-70% for text-based responses.

| Setting                       | Description                                       | Default | Options              |
| ----------------------------- | ------------------------------------------------- | ------- | -------------------- |
| `COMPRESSION_ENABLED`         | Enable response compression                       | `true`  | bool                 |
| `COMPRESSION_MINIMUM_SIZE`    | Minimum response size in bytes to compress        | `500`   | int (0=compress all) |
| `COMPRESSION_GZIP_LEVEL`      | GZip compression level (1=fast, 9=best)          | `6`     | int (1-9)            |
| `COMPRESSION_BROTLI_QUALITY`  | Brotli quality (0-3=fast, 4-9=balanced, 10-11=max) | `4`   | int (0-11)           |
| `COMPRESSION_ZSTD_LEVEL`      | Zstd level (1-3=fast, 4-9=balanced, 10+=slow)    | `3`     | int (1-22)           |

### Logging

| Setting                 | Description                        | Default           | Options                    |
| ----------------------- | ---------------------------------- | ----------------- | -------------------------- |
| `LOG_LEVEL`             | Minimum log level                  | `INFO`            | `DEBUG`...`CRITICAL`       |
| `LOG_FORMAT`            | Console log format                 | `json`            | `json`, `text`             |
| `LOG_REQUESTS`          | Enable detailed request logging    | `false`           | bool                       |
| `LOG_DETAILED_MAX_BODY_SIZE` | Max request body size to log (bytes) | `16384`       | int                        |
| `LOG_DETAILED_SKIP_ENDPOINTS` | Path prefixes to skip from detailed logging | `[]` | Comma-separated list       |
| `LOG_DETAILED_SAMPLE_RATE` | Sampling rate for detailed logging | `1.0`            | float (0.0-1.0)            |
| `LOG_RESOLVE_USER_IDENTITY` | Enable DB lookup for user identity | `false`         | bool                       |
| `LOG_TO_FILE`           | Enable file logging                | `false`           | bool                       |
| `LOG_FILE`              | Log filename (when enabled)        | `null`            | string                     |
| `LOG_FOLDER`            | Directory for log files            | `null`            | path                       |
| `LOG_FILEMODE`          | File write mode                    | `a+`              | `a+` (append), `w` (overwrite)|
| `LOG_ROTATION_ENABLED`  | Enable log file rotation           | `false`           | bool                       |
| `LOG_MAX_SIZE_MB`       | Max file size before rotation (MB) | `1`               | int                        |
| `LOG_BACKUP_COUNT`      | Number of backup files to keep     | `5`               | int                        |
| `LOG_BUFFER_SIZE_MB`    | Size of in-memory log buffer (MB)  | `1.0`             | float > 0                  |
| `PERMISSION_AUDIT_ENABLED` | Enable permission audit logging (writes a row per permission check) | `false` | bool |

### Observability (OpenTelemetry)

MCP Gateway includes **vendor-agnostic OpenTelemetry support** for distributed tracing. Works with Phoenix, Jaeger, Zipkin, Tempo, DataDog, New Relic, and any OTLP-compatible backend.

| Setting                         | Description                                    | Default               | Options                                    |
| ------------------------------- | ---------------------------------------------- | --------------------- | ------------------------------------------ |
| `OTEL_ENABLE_OBSERVABILITY`     | Master switch for observability               | `false`               | bool                                       |
| `OTEL_SERVICE_NAME`             | Service identifier in traces                   | `mcp-gateway`         | string                                     |
| `OTEL_SERVICE_VERSION`          | Service version in traces                      | `1.0.0-RC-1`               | string                                     |
| `OTEL_DEPLOYMENT_ENVIRONMENT`   | Environment tag (dev/staging/prod)            | `development`         | string                                     |
| `OTEL_TRACES_EXPORTER`          | Trace exporter backend                         | `otlp`                | `otlp`, `jaeger`, `zipkin`, `console`, `none` |
| `OTEL_RESOURCE_ATTRIBUTES`      | Custom resource attributes                     | (empty)               | `key=value,key2=value2`                   |

**OTLP Configuration:**

| Setting                         | Description                                    | Default               | Options                                    |
| ------------------------------- | ---------------------------------------------- | --------------------- | ------------------------------------------ |
| `OTEL_EXPORTER_OTLP_ENDPOINT`   | OTLP collector endpoint                        | (none)                | `http://localhost:4317`                   |
| `OTEL_EXPORTER_OTLP_PROTOCOL`   | OTLP protocol                                  | `grpc`                | `grpc`, `http/protobuf`                   |
| `OTEL_EXPORTER_OTLP_HEADERS`    | Authentication headers                         | (empty)               | `api-key=secret,x-auth=token`             |
| `OTEL_EXPORTER_OTLP_INSECURE`   | Skip TLS verification                          | `true`                | bool                                       |

**Performance Tuning:**

| Setting                         | Description                                    | Default               | Options                                    |
| ------------------------------- | ---------------------------------------------- | --------------------- | ------------------------------------------ |
| `OTEL_TRACES_SAMPLER`           | Sampling strategy                              | `parentbased_traceidratio` | `always_on`, `always_off`, `traceidratio` |
| `OTEL_TRACES_SAMPLER_ARG`       | Sample rate (0.0-1.0)                         | `0.1`                 | float                                      |
| `OTEL_BSP_MAX_QUEUE_SIZE`       | Max queued spans                              | `2048`                | int > 0                                    |
| `OTEL_BSP_MAX_EXPORT_BATCH_SIZE`| Max batch size for export                     | `512`                 | int > 0                                    |
| `OTEL_BSP_SCHEDULE_DELAY`       | Export interval (ms)                          | `5000`                | int > 0                                    |

### Internal Observability & Tracing

The gateway includes built-in observability features for tracking HTTP requests, spans, and traces independent of OpenTelemetry.

| Setting                              | Description                                           | Default                                              | Options          |
| ------------------------------------ | ----------------------------------------------------- | ---------------------------------------------------- | ---------------- |
| `OBSERVABILITY_ENABLED`              | Enable internal observability tracing and metrics     | `false`                                              | bool             |
| `OBSERVABILITY_TRACE_HTTP_REQUESTS`  | Automatically trace HTTP requests                     | `true`                                               | bool             |
| `OBSERVABILITY_TRACE_RETENTION_DAYS` | Number of days to retain trace data                   | `7`                                                  | int (≥ 1)        |
| `OBSERVABILITY_MAX_TRACES`           | Maximum number of traces to retain                    | `100000`                                             | int (≥ 1000)     |
| `OBSERVABILITY_SAMPLE_RATE`          | Trace sampling rate (0.0-1.0)                        | `1.0`                                                | float            |
| `OBSERVABILITY_INCLUDE_PATHS`        | Regex patterns to include for tracing                | See defaults                                         | JSON array       |
| `OBSERVABILITY_EXCLUDE_PATHS`        | Regex patterns to exclude (after include patterns)   | `["/health","/healthz","/ready","/metrics","/static/.*"]` | JSON array |
| `OBSERVABILITY_METRICS_ENABLED`      | Enable metrics collection                             | `true`                                               | bool             |
| `OBSERVABILITY_EVENTS_ENABLED`       | Enable event logging within spans                     | `true`                                               | bool             |

### Prometheus Metrics

| Setting                      | Description                                              | Default   | Options          |
| ---------------------------- | -------------------------------------------------------- | --------- | ---------------- |
| `ENABLE_METRICS`             | Enable Prometheus metrics instrumentation                | `true`    | bool             |
| `METRICS_EXCLUDED_HANDLERS`  | Regex patterns for paths to exclude from metrics         | (empty)   | comma-separated  |
| `METRICS_NAMESPACE`          | Prometheus metrics namespace (prefix)                    | `default` | string           |
| `METRICS_SUBSYSTEM`          | Prometheus metrics subsystem (secondary prefix)          | (empty)   | string           |
| `METRICS_CUSTOM_LABELS`      | Static custom labels for app_info gauge                  | (empty)   | `key=value,...`  |

### Metrics Cleanup & Rollup

| Setting                              | Description                                      | Default  | Options     |
| ------------------------------------ | ------------------------------------------------ | -------- | ----------- |
| `DB_METRICS_RECORDING_ENABLED`       | Enable execution metrics recording               | `true`   | bool        |
| `METRICS_CLEANUP_ENABLED`            | Enable automatic cleanup of old metrics          | `true`   | bool        |
| `METRICS_RETENTION_DAYS`             | Days to retain raw metrics (fallback)            | `7`      | 1-365       |
| `METRICS_CLEANUP_INTERVAL_HOURS`     | Hours between automatic cleanup runs             | `1`      | 1-168       |
| `METRICS_CLEANUP_BATCH_SIZE`         | Batch size for deletion (prevents long locks)    | `10000`  | 100-100000  |
| `METRICS_ROLLUP_ENABLED`             | Enable hourly metrics rollup                     | `true`   | bool        |
| `METRICS_ROLLUP_INTERVAL_HOURS`      | Hours between rollup runs                        | `1`      | 1-24        |
| `METRICS_ROLLUP_RETENTION_DAYS`      | Days to retain hourly rollup data                | `365`    | 30-3650     |
| `METRICS_ROLLUP_LATE_DATA_HOURS`     | Hours to re-process for late-arriving data       | `1`      | 1-48        |
| `METRICS_DELETE_RAW_AFTER_ROLLUP`    | Delete raw metrics after rollup exists           | `true`   | bool        |
| `METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS` | Hours to retain raw when rollup exists        | `1`      | 1-8760      |
| `USE_POSTGRESDB_PERCENTILES`         | Use PostgreSQL-native percentile_cont            | `true`   | bool        |
| `YIELD_BATCH_SIZE`                   | Rows per batch when streaming rollup queries     | `1000`   | 100-10000   |

### Transport

| Setting                   | Description                        | Default | Options                         |
| ------------------------- | ---------------------------------- | ------- | ------------------------------- |
| `TRANSPORT_TYPE`          | Enabled transports                 | `all`   | `http`,`ws`,`sse`,`stdio`,`all` |
| `WEBSOCKET_PING_INTERVAL` | WebSocket ping (secs)              | `30`    | int > 0                         |
| `SSE_RETRY_TIMEOUT`       | SSE retry timeout (ms)             | `5000`  | int > 0                         |
| `SSE_KEEPALIVE_ENABLED`   | Enable SSE keepalive events        | `true`  | bool                            |
| `SSE_KEEPALIVE_INTERVAL`  | SSE keepalive interval (secs)      | `30`    | int > 0                         |
| `USE_STATEFUL_SESSIONS`   | streamable http config             | `false` | bool                            |
| `JSON_RESPONSE_ENABLED`   | json/sse streams (streamable http) | `true`  | bool                            |

### Federation

| Setting                    | Description            | Default | Options    |
| -------------------------- | ---------------------- | ------- | ---------- |
| `FEDERATION_TIMEOUT`       | Gateway timeout (secs) | `30`    | int > 0    |

### Resources

| Setting               | Description           | Default    | Options    |
| --------------------- | --------------------- | ---------- | ---------- |
| `RESOURCE_CACHE_SIZE` | LRU cache size        | `1000`     | int > 0    |
| `RESOURCE_CACHE_TTL`  | Cache TTL (seconds)   | `3600`     | int > 0    |
| `MAX_RESOURCE_SIZE`   | Max resource bytes    | `10485760` | int > 0    |
| `ALLOWED_MIME_TYPES`  | Acceptable MIME types | see code   | JSON array |

### Tools

| Setting                 | Description                    | Default | Options |
| ----------------------- | ------------------------------ | ------- | ------- |
| `TOOL_TIMEOUT`          | Tool invocation timeout (secs) | `60`    | int > 0 |
| `MAX_TOOL_RETRIES`      | Max retry attempts             | `3`     | int ≥ 0 |
| `TOOL_RATE_LIMIT`       | Tool calls per minute          | `100`   | int > 0 |
| `TOOL_CONCURRENT_LIMIT` | Concurrent tool invocations    | `10`    | int > 0 |
| `GATEWAY_TOOL_NAME_SEPARATOR` | Tool name separator for gateway routing | `-`     | `-`, `--`, `_`, `.` |

### Prompts

| Setting                 | Description                      | Default  | Options |
| ----------------------- | -------------------------------- | -------- | ------- |
| `PROMPT_CACHE_SIZE`     | Cached prompt templates          | `100`    | int > 0 |
| `MAX_PROMPT_SIZE`       | Max prompt template size (bytes) | `102400` | int > 0 |
| `PROMPT_RENDER_TIMEOUT` | Jinja render timeout (secs)      | `10`     | int > 0 |

### Schema Validation

| Setting | Description | Default | Options |
| :--- | :--- | :--- | :--- |
| `JSON_SCHEMA_VALIDATION_STRICT` | Enforce strict JSON Schema validation for tools and prompts | `true` | bool |

**Strict Mode Scenarios:**

- **`true` (Default)**: Invalid schemas (e.g., unknown types, malformed JSON Schema) will cause registration to **fail** with a 400 error. This ensures that only valid, spec-compliant tools and prompts are registered, preventing runtime issues later.
- **`false`**: Invalid schemas will be **logged as warnings** but successfully persisted. Use this **only** for backward compatibility if you have legacy tools with broken schemas that cannot be immediately updated. Invalid schemas may still cause runtime errors when used by LLMs or downstream tools.

### Health Checks

| Setting                 | Description                               | Default | Options |
| ----------------------- | ----------------------------------------- | ------- | ------- |
| `HEALTH_CHECK_INTERVAL` | Health poll interval (secs)               | `60`    | int > 0 |
| `HEALTH_CHECK_TIMEOUT`  | Health request timeout (secs)             | `5`     | int > 0 |
| `GATEWAY_HEALTH_CHECK_TIMEOUT` | Per-check timeout for gateway health check (secs) | `5.0` | float > 0 |
| `UNHEALTHY_THRESHOLD`   | Fail-count before peer deactivation (-1 to disable) | `3`     | int     |
| `GATEWAY_VALIDATION_TIMEOUT` | Gateway URL validation timeout (secs) | `5`     | int > 0 |
| `MAX_CONCURRENT_HEALTH_CHECKS` | Max concurrent health checks        | `20`    | int > 0 |
| `AUTO_REFRESH_SERVERS` | Auto refresh tools/prompts/resources        | `false` | bool    |
| `FILELOCK_NAME`         | File lock for leader election             | `gateway_service_leader.lock` | string |
| `DEFAULT_ROOTS`         | Default root paths for resources          | `[]`    | JSON array |

### Database Connection Pool

| Setting                 | Description                     | Default | Options |
| ----------------------- | ------------------------------- | ------- | ------- |
| `DB_POOL_SIZE`          | SQLAlchemy connection pool size | `200`   | int > 0 |
| `DB_MAX_OVERFLOW`       | Extra connections beyond pool   | `10`    | int ≥ 0 |
| `DB_POOL_TIMEOUT`       | Wait for connection (secs)      | `30`    | int > 0 |
| `DB_POOL_RECYCLE`       | Recycle connections (secs)      | `3600`  | int > 0 |
| `DB_MAX_RETRIES`        | Max retry attempts at startup   | `30`    | int > 0 |
| `DB_RETRY_INTERVAL_MS`  | Base retry interval (ms)        | `2000`  | int > 0 |
| `DB_SQLITE_BUSY_TIMEOUT`| SQLite lock wait timeout (ms)   | `5000`  | 1000-60000 |
| `DB_POOL_CLASS`         | Pool class selection            | `auto`  | `auto`, `null`, `queue` |
| `DB_POOL_PRE_PING`      | Validate connections before use | `auto`  | `auto`, `true`, `false` |

### Cache Backend

| Setting                   | Description                | Default    | Options                  |
| ------------------------- | -------------------------- | ---------- | ------------------------ |
| `CACHE_TYPE`              | Backend type               | `database` | `none`, `memory`, `database`, `redis` |
| `REDIS_URL`               | Redis connection URL       | (none)     | string                   |
| `CACHE_PREFIX`            | Key prefix                 | `mcpgw:`   | string                   |
| `SESSION_TTL`             | Session validity (secs)    | `3600`     | int > 0                  |
| `MESSAGE_TTL`             | Message retention (secs)   | `600`      | int > 0                  |
| `REDIS_MAX_RETRIES`       | Max retry attempts         | `30`       | int > 0                  |
| `REDIS_RETRY_INTERVAL_MS` | Base retry interval (ms)   | `2000`     | int > 0                  |
| `REDIS_MAX_CONNECTIONS`   | Connection pool size       | `50`       | int > 0                  |
| `REDIS_SOCKET_TIMEOUT`    | Socket timeout (secs)      | `2.0`      | float > 0                |
| `REDIS_SOCKET_CONNECT_TIMEOUT` | Connect timeout (secs) | `2.0`     | float > 0                |
| `REDIS_RETRY_ON_TIMEOUT`  | Retry on timeout           | `true`     | bool                     |
| `REDIS_HEALTH_CHECK_INTERVAL` | Health check (secs)    | `30`       | int >= 0                 |
| `REDIS_DECODE_RESPONSES`  | Return strings vs bytes    | `true`     | bool                     |
| `REDIS_LEADER_TTL`        | Leader election TTL (secs) | `15`       | int > 0                  |
| `REDIS_LEADER_KEY`        | Leader key name            | `gateway_service_leader` | string |
| `REDIS_LEADER_HEARTBEAT_INTERVAL` | Heartbeat (secs)   | `5`        | int > 0                  |

!!! tip "Cache Backend Selection"
    Use `memory` for dev, `database` for local persistence, or `redis` for distributed caching across multiple instances. `none` disables caching entirely.

### Tool Lookup Cache

| Setting                               | Description                                                     | Default | Options          |
| ------------------------------------- | --------------------------------------------------------------- | ------- | ---------------- |
| `TOOL_LOOKUP_CACHE_ENABLED`           | Enable tool lookup cache for `invoke_tool` hot path             | `true`  | bool             |
| `TOOL_LOOKUP_CACHE_TTL_SECONDS`       | Cache TTL (seconds) for tool lookup entries                     | `60`    | int (5-600)      |
| `TOOL_LOOKUP_CACHE_NEGATIVE_TTL_SECONDS` | Cache TTL (seconds) for missing/inactive/offline entries     | `10`    | int (1-60)       |
| `TOOL_LOOKUP_CACHE_L1_MAXSIZE`        | Max entries in in-memory L1 cache                               | `10000` | int              |
| `TOOL_LOOKUP_CACHE_L2_ENABLED`        | Enable Redis-backed L2 cache when `CACHE_TYPE=redis`            | `true`  | bool             |

### Metrics Aggregation Cache

| Setting                     | Description                           | Default | Options    |
| --------------------------- | ------------------------------------- | ------- | ---------- |
| `METRICS_CACHE_ENABLED`     | Enable metrics query caching          | `true`  | bool       |
| `METRICS_CACHE_TTL_SECONDS` | Cache TTL (seconds)                   | `60`    | int (1-300)|

### MCP Session Pool

| Setting                                   | Description                                        | Default | Options     |
| ----------------------------------------- | -------------------------------------------------- | ------- | ----------- |
| `MCP_SESSION_POOL_ENABLED`                | Enable session pooling (10-20x latency improvement)| `false` | bool        |
| `MCP_SESSION_POOL_MAX_PER_KEY`            | Max sessions per (URL, identity, transport)        | `10`    | int (1-100) |
| `MCP_SESSION_POOL_TTL`                    | Session TTL before forced close (seconds)          | `300`   | float       |
| `MCP_SESSION_POOL_TRANSPORT_TIMEOUT`      | Timeout for all HTTP operations (seconds)          | `30`    | float       |
| `MCP_SESSION_POOL_HEALTH_CHECK_INTERVAL`  | Idle time before health check (seconds)            | `60`    | float       |
| `MCP_SESSION_POOL_ACQUIRE_TIMEOUT`        | Timeout waiting for session slot (seconds)         | `30`    | float       |
| `MCP_SESSION_POOL_CREATE_TIMEOUT`         | Timeout creating new session (seconds)             | `30`    | float       |
| `MCP_SESSION_POOL_CIRCUIT_BREAKER_THRESHOLD` | Failures before circuit opens                   | `5`     | int         |
| `MCP_SESSION_POOL_CIRCUIT_BREAKER_RESET`  | Seconds before circuit resets                      | `60`    | float       |
| `MCP_SESSION_POOL_IDLE_EVICTION`          | Evict idle pool keys after (seconds)               | `600`   | float       |
| `MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC`    | Force explicit RPC on health checks                | `false` | bool        |

!!! tip "Session Pool Performance"
    Session pooling reduces per-request overhead from ~20ms to ~1-2ms (10-20x improvement). Sessions are isolated per user/tenant via identity hashing.

### Development

| Setting    | Description            | Default | Options |
| ---------- | ---------------------- | ------- | ------- |
| `DEV_MODE` | Enable dev mode        | `false` | bool    |
| `RELOAD`   | Auto-reload on changes | `false` | bool    |
| `DEBUG`    | Debug logging          | `false` | bool    |

### Well-Known URI Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `WELL_KNOWN_ENABLED`          | Enable well-known URI endpoints (/.well-known/*) | `true`                | bool    |
| `WELL_KNOWN_ROBOTS_TXT`       | robots.txt content                               | (blocks crawlers)     | string  |
| `WELL_KNOWN_SECURITY_TXT`     | security.txt content (RFC 9116)                 | (empty)               | string  |
| `WELL_KNOWN_SECURITY_TXT_ENABLED` | Enable security.txt endpoint                 | `false`               | bool    |
| `WELL_KNOWN_CUSTOM_FILES`     | Additional custom well-known files (JSON)       | `{}`                  | JSON object |
| `WELL_KNOWN_CACHE_MAX_AGE`    | Cache control for well-known files (seconds)    | `3600`                | int > 0 |

### Header Passthrough Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `ENABLE_HEADER_PASSTHROUGH`   | Enable HTTP header passthrough feature           | `false`               | bool    |
| `ENABLE_OVERWRITE_BASE_HEADERS` | Enable overwriting of base headers             | `false`               | bool    |
| `DEFAULT_PASSTHROUGH_HEADERS` | Default headers to pass through (JSON array)    | `["X-Tenant-Id", "X-Trace-Id"]` | JSON array |
| `GLOBAL_CONFIG_CACHE_TTL`     | In-memory cache TTL for GlobalConfig (seconds)  | `60`                  | int     |

!!! warning "Security Warning"
    Header passthrough is disabled by default for security. Only enable if you understand the implications.

### Plugin Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `PLUGINS_ENABLED`             | Enable the plugin framework                      | `false`               | bool    |
| `PLUGIN_CONFIG_FILE`          | Path to main plugin configuration file          | `plugins/config.yaml` | string  |
| `PLUGINS_CLIENT_MTLS_CA_BUNDLE`      | Default CA bundle for external plugin mTLS | (empty)               | string  |
| `PLUGINS_CLIENT_MTLS_CERTFILE`       | Gateway client certificate for plugin mTLS | (empty)               | string  |
| `PLUGINS_CLIENT_MTLS_KEYFILE`        | Gateway client key for plugin mTLS         | (empty)               | string  |
| `PLUGINS_CLIENT_MTLS_KEYFILE_PASSWORD` | Password for plugin client key           | (empty)               | string  |
| `PLUGINS_CLIENT_MTLS_VERIFY`         | Verify remote plugin certificates          | `true`                | bool    |
| `PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME` | Enforce hostname verification for plugins  | `true`                | bool    |
| `PLUGINS_CLI_COMPLETION`      | Enable auto-completion for plugins CLI          | `false`               | bool    |
| `PLUGINS_CLI_MARKUP_MODE`     | Set markup mode for plugins CLI                 | (none)                | `rich`, `markdown`, `disabled` |

### HTTP Retry Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `RETRY_MAX_ATTEMPTS`          | Maximum retry attempts for HTTP requests         | `3`                   | int > 0 |
| `RETRY_BASE_DELAY`            | Base delay between retries (seconds)             | `1.0`                 | float > 0 |
| `RETRY_MAX_DELAY`             | Maximum delay between retries (seconds)          | `60`                  | int > 0 |
| `RETRY_JITTER_MAX`            | Maximum jitter fraction of base delay            | `0.5`                 | float 0-1 |

### CPU Spin Loop Mitigation

These settings mitigate CPU spin loops that can occur when SSE/MCP connections are cancelled.

**Layer 1: SSE Connection Protection**

| Setting                    | Description                                              | Default | Options     |
| -------------------------- | -------------------------------------------------------- | ------- | ----------- |
| `SSE_SEND_TIMEOUT`         | ASGI send() timeout - protects against hung connections | `30.0`  | float       |
| `SSE_RAPID_YIELD_WINDOW_MS`| Time window for rapid yield detection (milliseconds)    | `1000`  | int > 0     |
| `SSE_RAPID_YIELD_MAX`      | Max yields per window before assuming client dead       | `50`    | int         |

**Layer 2: Cleanup Timeouts**

| Setting                          | Description                                        | Default | Options |
| -------------------------------- | -------------------------------------------------- | ------- | ------- |
| `MCP_SESSION_POOL_CLEANUP_TIMEOUT` | Session `__aexit__` timeout (seconds)            | `5.0`   | float > 0 |
| `SSE_TASK_GROUP_CLEANUP_TIMEOUT`   | SSE task group cleanup timeout (seconds)         | `5.0`   | float > 0 |

**Layer 3: EXPERIMENTAL - anyio Monkey-Patch**

| Setting                                  | Description                                                   | Default | Options |
| ---------------------------------------- | ------------------------------------------------------------- | ------- | ------- |
| `ANYIO_CANCEL_DELIVERY_PATCH_ENABLED`    | Enable anyio `_deliver_cancellation` iteration limit          | `false` | bool    |
| `ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS`   | Max iterations before forcing termination                     | `100`   | int > 0 |

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
# Embedded UI mode (hides logout + team selector by default)
MCPGATEWAY_UI_EMBEDDED=false
# CSV/JSON list of UI sections/header items to hide (optional)
MCPGATEWAY_UI_HIDE_SECTIONS=
MCPGATEWAY_UI_HIDE_HEADER_ITEMS=
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

## 📚 Related Documentation

- [Docker Compose Deployment](../deployment/compose.md)
- [Local Development Setup](../deployment/local.md)
- [Kubernetes Deployment](../deployment/kubernetes.md)
- [Secure Runtime](runtime.md)
- [MCP Server Catalog](catalog.md)
- [Backup & Restore](backup.md)
- [Logging Configuration](logging.md)
- [SSO Configuration](sso.md)
- [OAuth Configuration](oauth.md)
- [MCP Server Catalog](catalog.md)
