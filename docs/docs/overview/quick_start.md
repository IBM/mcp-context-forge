---
classification:
status: draft
owner: Mihai Criveti
---

# 🚀 Quick Start

MCP Gateway can be running on your laptop or server in **< 5 minutes**.
Pick an install method below, generate an auth token, then walk through a real tool + server demo.

## Installing and starting MCP Gateway

=== "PyPI / virtual-env"

    ### Local install via PyPI

    !!! note
        **Prereqs**: Python ≥ 3.10, plus `curl` & `jq` for the smoke test.

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

    3. **Launch it, listening on all interfaces**

        ```bash
        export BASIC_AUTH_PASSWORD=changeme
        export JWT_SECRET_KEY=my-test-key
        mcpgateway --host 0.0.0.0 --port 4444
        ```

        The terminal shows startup logs; keep it running.

    4. **Generate a bearer token with an expiration time of 10080 seconds (1 week)**

        ```bash
        export MCP_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
            --username admin --exp 10080 --secret my-test-key)
        ```

        !!! tip "Use `--exp 0` for tokens that don't expire"

    5. **Smoke-test health + version**

        ```bash
        curl -s http://localhost:4444/health | jq
        curl -s -H "Authorization: Bearer $MCP_BEARER_TOKEN" http://localhost:4444/version | jq
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
          ghcr.io/ibm/mcp-context-forge:0.3.0
        ```

    2. **(Optional) persist the DB**

        ```bash
        mkdir -p $(pwd)/data
        docker run -d --name mcpgateway \
          -p 4444:4444 \
          -v $(pwd)/data:/data \
          -e DATABASE_URL=sqlite:////data/mcp.db \
          -e JWT_SECRET_KEY=my-test-key \
          -e BASIC_AUTH_USER=admin \
          -e BASIC_AUTH_PASSWORD=changeme \
          ghcr.io/ibm/mcp-context-forge:0.3.0
        ```

    3. **Generate a token inside the container**

        ```bash
        docker exec mcpgateway python3 -m mcpgateway.utils.create_jwt_token \
          --username admin --exp 10080 --secret my-test-key
        ```

    4. **Smoke-test**

        ```bash
        export MCP_BEARER_TOKEN=<paste_from_previous_step>
        curl -s http://localhost:4444/health | jq
        curl -s -H "Authorization: Bearer $MCP_BEARER_TOKEN" http://localhost:4444/version | jq
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
        docker pull ghcr.io/ibm/mcp-context-forge:0.3.0
        ```

    3. **Start the stack**

        ```bash
        # Uses podman or docker automatically
        make compose-up
        # -or- raw CLI
        docker compose -f podman-compose.yml up -d
        ```

    4. **Verify**

        ```bash
        curl -s http://localhost:4444/health | jq
        ```

    > **Tip :** The sample Compose file has multiple database blocks
    > (Postgres, MariaDB, MySQL, MongoDB) and admin tools. Uncomment one and align
    > `DATABASE_URL` for your preferred backend.

---

## Registering MCP tools & creating a virtual server

```bash
# Spin up a sample MCP time server (SSE, port 8002)
pip install uv
npx -y supergateway --stdio "uvx mcp_server_time -- --local-timezone=Europe/Dublin" --port 8002 &
```

```bash
# Register that server with your gateway
curl -s -X POST -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"local_time","url":"http://localhost:8002/sse"}' \
     http://localhost:4444/gateways | jq
```

```bash
# Bundle the imported tool(s) into a virtual MCP server
curl -s -X POST -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"demo_server","description":"Time tools","associatedTools":["1"]}' \
     http://localhost:4444/servers | jq
```

```bash
# Verify catalog entries
curl -s -H "Authorization: Bearer $MCP_BEARER_TOKEN" http://localhost:4444/tools   | jq
curl -s -H "Authorization: Bearer $MCP_BEARER_TOKEN" http://localhost:4444/servers | jq
```

```bash
# Optional: Connect interactively via MCP Inspector
npx -y @modelcontextprotocol/inspector
# Transport SSE → URL http://localhost:4444/servers/UUID_OF_SERVER_1/sse
# Header Authorization → Bearer $MCP_BEARER_TOKEN
```

---

## Connect via `mcpgateway-wrapper` (stdio)

```bash
export MCP_AUTH_TOKEN=$MCP_BEARER_TOKEN
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/UUID_OF_SERVER_1
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
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/UUID_OF_SERVER_1",
        "MCP_AUTH_TOKEN": "<YOUR_JWT_TOKEN>",
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
