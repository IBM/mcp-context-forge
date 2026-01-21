---
classification:
status: draft
owner: Mihai Criveti
---

# 🚀 Quick Start

MCP Gateway can be running on your laptop or server in **< 5 minutes**.
Pick an install method below, generate an auth token, then walk through a real tool + server demo.

## Installing and starting MCP Gateway

=== "PyPI / uv"

    !!! note
        **Prereqs**: Install uv (https://docs.astral.sh/uv/getting-started/installation/)

    ```bash
    # Quick start with environment variables
    BASIC_AUTH_PASSWORD=pass \
    MCPGATEWAY_UI_ENABLED=true \
    MCPGATEWAY_ADMIN_API_ENABLED=true \
    PLATFORM_ADMIN_EMAIL=admin@example.com \
    PLATFORM_ADMIN_PASSWORD=changeme \
    PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
    uvx --from mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444

    # Or better: use the provided .env.example
    curl -O https://raw.githubusercontent.com/IBM/mcp-context-forge/main/.env.example
    cp .env.example .env
    # Edit .env to customize your settings
    uvx --from mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444
    ```

=== "PyPI / virtual-env"

    ### Local install via PyPI

    !!! note
        **Prereqs**: Python ≥ 3.11, plus `curl` & `jq` for the smoke test.

    1. **Create an isolated environment and upgrade pip if required**

        ```bash
        mkdir mcpgateway && cd mcpgateway
        python3 -m venv .venv && source .venv/bin/activate
        python3 -m pip install --upgrade pip
        ```

    2. **Install the gateway from pypi**

        ```bash
        pip install mcp-contextforge-gateway
        mcpgateway --version
        ```

    3. **Configure and launch it**

        ```bash
        # Option 1: Download and use the provided .env.example
        curl -O https://raw.githubusercontent.com/IBM/mcp-context-forge/main/.env.example
        cp .env.example .env
        # Edit .env to customize your settings (especially passwords!)
        mcpgateway --host 0.0.0.0 --port 4444

        # Option 2: Set environment variables directly
        export BASIC_AUTH_PASSWORD=changeme
        export JWT_SECRET_KEY=my-test-key
        export MCPGATEWAY_UI_ENABLED=true
        export MCPGATEWAY_ADMIN_API_ENABLED=true
        export PLATFORM_ADMIN_EMAIL=admin@example.com
        export PLATFORM_ADMIN_PASSWORD=changeme
        export PLATFORM_ADMIN_FULL_NAME="Platform Administrator"
        mcpgateway --host 0.0.0.0 --port 4444
        ```

        The terminal shows startup logs; keep it running.

    4. **Generate a bearer token with an expiration time of 10080 seconds (1 week)**

        ```bash
        export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
            --username admin --exp 10080 --secret my-test-key)
        ```

        !!! tip "Use `--exp 0` for tokens that don't expire"

    5. **Smoke-test health + version**

        ```bash
        curl -s http://localhost:4444/health | jq
        curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/version | jq
        ```

=== "Docker / Podman"

    ### Docker/Podman Container install

    !!! note
        Substitute **`docker`** with **`podman`** if preferred.

    1. **Run the image**

        ```bash
        docker run -d --name mcpgateway \
          -p 4444:4444 \
          -e HOST=0.0.0.0 \
          -e JWT_SECRET_KEY=my-test-key \
          -e BASIC_AUTH_USER=admin \
          -e BASIC_AUTH_PASSWORD=changeme \
          -e PLATFORM_ADMIN_EMAIL=admin@example.com \
          -e PLATFORM_ADMIN_PASSWORD=changeme \
          -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
          ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
        ```

    2. **(Optional) persist the DB**

        === "SQLite (Default)"
            ```bash
            mkdir -p $(pwd)/data
            docker run -d --name mcpgateway \
              -p 4444:4444 \
              -v $(pwd)/data:/data \
              -e DATABASE_URL=sqlite:////data/mcp.db \
              -e JWT_SECRET_KEY=my-test-key \
              -e BASIC_AUTH_USER=admin \
              -e BASIC_AUTH_PASSWORD=changeme \
              -e PLATFORM_ADMIN_EMAIL=admin@example.com \
              -e PLATFORM_ADMIN_PASSWORD=changeme \
              -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
              ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
            ```

        === "MySQL"
            ```bash
            # Start MySQL container first
            docker run -d --name mysql-db \
              -e MYSQL_ROOT_PASSWORD=mysecretpassword \
              -e MYSQL_DATABASE=mcp \
              -e MYSQL_USER=mysql \
              -e MYSQL_PASSWORD=changeme \
              -p 3306:3306 \
              mysql:8

            # Start MCP Gateway with MySQL connection
            docker run -d --name mcpgateway \
              -p 4444:4444 \
              --link mysql-db:mysql \
              -e DATABASE_URL=mysql+pymysql://mysql:changeme@mysql:3306/mcp \
              -e JWT_SECRET_KEY=my-test-key \
              -e BASIC_AUTH_USER=admin \
              -e BASIC_AUTH_PASSWORD=changeme \
              -e PLATFORM_ADMIN_EMAIL=admin@example.com \
              -e PLATFORM_ADMIN_PASSWORD=changeme \
              -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
              ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
            ```

        === "PostgreSQL"
            ```bash
            # Start PostgreSQL container first
            docker run -d --name postgres-db \
              -e POSTGRES_USER=postgres \
              -e POSTGRES_PASSWORD=mysecretpassword \
              -e POSTGRES_DB=mcp \
              -p 5432:5432 \
              postgres:17

            # Start MCP Gateway with PostgreSQL connection
            docker run -d --name mcpgateway \
              -p 4444:4444 \
              --link postgres-db:postgres \
              -e DATABASE_URL=postgresql+psycopg://postgres:mysecretpassword@postgres:5432/mcp \
              -e JWT_SECRET_KEY=my-test-key \
              -e BASIC_AUTH_USER=admin \
              -e BASIC_AUTH_PASSWORD=changeme \
              -e PLATFORM_ADMIN_EMAIL=admin@example.com \
              -e PLATFORM_ADMIN_PASSWORD=changeme \
              -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
              ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
            ```

    3. **Generate a token inside the container**

        ```bash
        docker exec mcpgateway python3 -m mcpgateway.utils.create_jwt_token \
          --username admin --exp 10080 --secret my-test-key
        ```

    4. **Smoke-test**

        ```bash
        export MCPGATEWAY_BEARER_TOKEN=<paste_from_previous_step>
        curl -s http://localhost:4444/health | jq
        curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/version | jq
        ```

=== "Docker Compose"

    ### Run the full stack with Compose

    Typical Compose file includes **Gateway + Postgres + Redis and optional PgAdmin / Redis Commander**.
    See the complete sample and advanced scenarios in [Deployment › Compose](../deployment/compose.md).

    1. **Install Compose v2 (if needed)**

        ```bash
        # Ubuntu example
        sudo apt install docker-buildx docker-compose-v2
        # Tell the Makefile / docs which command to use
        export COMPOSE_CMD="docker compose"
        ```

    2. **Pull the published image**

        ```bash
        docker pull ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
        ```

    3. **Start the stack**

        ```bash
        # Uses podman or docker automatically
        make compose-up
        # -or- raw CLI
        docker compose -f docker-compose.yml up -d
        ```

    4. **Verify**

        ```bash
        curl -s http://localhost:4444/health | jq
        ```

    !!! tip "Database Support"
        The sample Compose file includes multiple database options:

        - **PostgreSQL** (default): `postgresql+psycopg://postgres:password@postgres:5432/mcp`
        - **MariaDB**: `mysql+pymysql://mysql:changeme@mariadb:3306/mcp` - fully supported with 36+ tables
        - **MySQL**: `mysql+pymysql://admin:changeme@mysql:3306/mcp`

        MariaDB 10.6+ and MySQL 8.0+ are fully compatible with all VARCHAR length requirements resolved.

---

## Registering MCP tools & creating a virtual server

```bash
# Spin up a sample MCP time server (SSE, port 8002)
pip install uv
python3 -m mcpgateway.translate \
  --stdio "uvx mcp_server_time -- --local-timezone=Europe/Dublin" \
  --expose-sse \
  --port 8002 &
```

```bash
# Register that server with your gateway
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"local_time","url":"http://localhost:8002/sse"}' \
     http://localhost:4444/gateways | jq
```

```bash
# Bundle the imported tool(s) into a virtual MCP server
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"demo_server","description":"Time tools","associatedTools":["1"]}' \
     http://localhost:4444/servers | jq
```

```bash
# Verify catalog entries
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools   | jq
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/servers | jq
```

```bash
# Optional: Connect interactively via MCP Inspector
npx -y @modelcontextprotocol/inspector
# Transport SSE → URL http://localhost:4444/servers/UUID_OF_SERVER_1/sse
# Header Authorization → Bearer $MCPGATEWAY_BEARER_TOKEN
```

---

## Connect via `mcpgateway-wrapper` (stdio)

```bash
export MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}"
export MCP_SERVER_URL=http://localhost:4444/servers/UUID_OF_SERVER_1/mcp
python3 -m mcpgateway.wrapper   # behaves as a local MCP stdio server - run from MCP client
```

Use this in GUI clients (Claude Desktop, Continue, etc.) that prefer stdio. Example:

```jsonc
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "python3",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp",
        "MCP_AUTH": "Bearer <YOUR_JWT_TOKEN>",
        "MCP_TOOL_CALL_TIMEOUT": "120"
      }
    }
  }
}
```

For more information see [MCP Clients](../using/index.md)

---

## 4 - Useful URLs

| URL                             | Description                                 |
| ------------------------------- | ------------------------------------------- |
| `http://localhost:4444/admin`   | Admin UI (Basic Auth: `admin` / `changeme`) |
| `http://localhost:4444/tools`   | Tool registry (GET)                         |
| `http://localhost:4444/servers` | Virtual servers (GET)                       |
| `/servers/<id>/sse`             | SSE endpoint for that server                |
| `/docs`, `/redoc`               | Swagger / ReDoc (JWT-protected)             |

---

## 5 - Next Steps

* [Features Overview](features.md) - deep dive on transports, federation, caching
* [Admin UI Guide](ui.md)
* [Deployment to K8s / AWS / GCP / Azure](../deployment/index.md)
* [Wrap any client via `mcpgateway-wrapper`](../using/mcpgateway-wrapper.md)
* Tweak **`.env`** - see [example](https://github.com/IBM/mcp-context-forge/blob/main/.env.example)

!!! success "Gateway is ready!"
You now have an authenticated MCP Gateway proxying a live tool, exposed via SSE **and** stdio.
Jump into the Admin UI or start wiring it into your agents and clients!
