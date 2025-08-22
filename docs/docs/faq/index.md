# ContextForge MCP Gateway - Frequently Asked Questions

## ⚡ Quickstart

???+ example "🚀 How can I install and run MCP Gateway in one command?"
    PyPI (pipx / uvx makes an isolated venv):

    ```bash
    # Using pipx - pip install pipx
    pipx run mcp-contextforge-gateway

    # Or uvx - pip install uv (default: admin/changeme)
    uvx mcp-contextforge-gateway --port 4444
    ```

    OCI image (Docker/Podman) - shares host network so localhost works:

    ```bash
    podman run --network=host -p 4444:4444 ghcr.io/ibm/mcp-context-forge:0.6.0
    ```

???+ example "🗂️ What URLs are available for the admin interface and API docs?"
    - Admin UI → <https://localhost:4444>
    - Swagger → <https://localhost:4444/docs>
    - ReDoc → <https://localhost:4444/redoc>

---

## 🤔 What is MCP (Model Context Protocol)?

???+ info "💡 What is MCP in a nutshell?"
    MCP is an open-source protocol released by Anthropic in Nov 2024 that lets language models invoke external tools via a typed JSON-RPC envelope. Community folks call it "USB-C for AI"-one connector for many models.

???+ info "🌍 Who supports MCP and what's the ecosystem like?"
    - Supported by GitHub & Microsoft Copilot, AWS Bedrock, Google Cloud Vertex AI, IBM watsonx, AgentBee, LangChain, CrewAI and 15,000+ community servers.
    - Contracts enforced via JSON Schema.
    - Multiple transports (STDIO, SSE, HTTP) - still converging.

---

## 🧰 Media Kit

???+ tip "🖼️ I want to make a social media post, where can I find samples and logos?"
    See the provided [media kit](../media/index.md)

???+ tip "📄 How do I describe the gateway in boilerplate copy?"
    > "ContextForge MCP Gateway is an open-source reverse-proxy that unifies MCP and REST tool servers under a single secure HTTPS endpoint with discovery, auth and observability baked in."

---

## 🛠️ Installation & Configuration

???+ example "🔧 What is the minimal .env setup required?"
    ```bash
    cp .env.example .env
    ```

    Then edit:

    ```env
    BASIC_AUTH_USER=admin
    BASIC_AUTH_PASSWORD=changeme
    JWT_SECRET_KEY=my-test-key
    ```

???+ example "🪛 What are some advanced environment variables I can configure?"
    - Basic: `HOST`, `PORT`, `APP_ROOT_PATH`
    - Auth: `AUTH_REQUIRED`, `BASIC_AUTH_*`, `JWT_SECRET_KEY`
    - Logging: `LOG_LEVEL`, `LOG_FORMAT`, `LOG_TO_FILE`, `LOG_FILE`, `LOG_FOLDER`, `LOG_ROTATION_ENABLED`, `LOG_MAX_SIZE_MB`, `LOG_BACKUP_COUNT`
    - Transport: `TRANSPORT_TYPE`, `WEBSOCKET_PING_INTERVAL`, `SSE_RETRY_TIMEOUT`
    - Tools: `TOOL_TIMEOUT`, `MAX_TOOL_RETRIES`, `TOOL_RATE_LIMIT`, `TOOL_CONCURRENT_LIMIT`
    - Federation: `FEDERATION_ENABLED`, `FEDERATION_PEERS`, `FEDERATION_SYNC_INTERVAL`

---

## 🚀 Running & Deployment

???+ example "🏠 How do I run MCP Gateway locally using PyPI?"
    ```bash
    python3 -m venv .venv && source .venv/bin/activate
    pip install mcp-contextforge-gateway
    mcpgateway
    ```

???+ example "🐳 How do I use the provided Makefile and Docker/Podman setup?"
    ```bash
    make podman # or make docker
    make podman-run-ssl # or make docker-run-ssl
    make podman-run-ssl-host # or make docker-run-ssl-host
    ```

    Docker Compose is also available, ex: `make compose-up`.

???+ example "☁️ How can I deploy MCP Gateway on Google Cloud Run, Code Engine, Kubernetes, AWS, etc?"
    See the [Deployment Documentation](../deployment/index.md) for detailed deployment instructions across local, docker, podman, compose, AWS, Azure, GCP, IBM Cloud, Helm, Minikube, Kubernetes, OpenShift and more.

---

## 💾 Databases & Persistence

???+ info "🗄️ What databases are supported for persistence?"
    - SQLite (default) - used for development / small deployments.
    - PostgreSQL / MySQL / MariaDB via `DATABASE_URL`
    - Redis (optional) for high performance session management. Sessions can also be stored in the DB or memory.
    - Other databases supported by SQLAlchemy.

???+ info "📦 How do I persist SQLite across container restarts?"
    Include a persistent volume with your container or Kubernetes deployment. Ex:

    ```bash
    docker run -v $(pwd)/data:/app ghcr.io/ibm/mcp-context-forge:0.6.0
    ```

    For production use, we recommend PostgreSQL. A Docker Compose target with PostgreSQL and Redis is provided.

---

## 🔐 Security & Auth

???+ danger "🆓 How do I disable authentication for development?"
    Set `AUTH_REQUIRED=false` - disables login for local testing.

???+ example "🔑 How do I generate and use a JWT token?"
    ```bash
    export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin -exp 0 --secret my-test-key)
    curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" https://localhost:4444/tools
    ```

    The token is used for all API interactions and can be configured to expire using `-exp`.

???+ tip "📥 How do I bulk import multiple tools at once?"
    Use the `/admin/tools/import` endpoint to import up to 200 tools in a single request:

    ```bash
    curl -X POST http://localhost:4444/admin/tools/import \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary @tools.json
    ```

    See the [Bulk Import guide](../manage/bulk-import.md) for details on format and error handling.

???+ example "🛡️ How do I enable TLS and configure CORS?"
    - Use `make podman-run-ssl` for self-signed certs or drop your own certificate under `certs`.
    - Set `ALLOWED_ORIGINS` or `CORS_ENABLED` for CORS headers.

---

## 📡 Tools, Servers & Federation

???+ example "➕ How do I register a tool with the gateway?"
    ```bash
    curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \\
         -H "Content-Type: application/json" \\
         -d '{"name":"clock_tool","url":"http://localhost:9000/rpc","input_schema":{"type":"object"}}' \\
         http://localhost:4444/tools
    ```

???+ example "🌉 How do I add a peer MCP gateway?"
    A "Gateway" is another MCP Server. The MCP Gateway itself is an MCP Server. This means you can add any MCP Server under "Gateways" and it will retrieve Tools/Resources/Prompts.

    ```bash
    curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \\
         -d '{"name":"peer","url":"http://peer:4444"}' \\
         http://localhost:4444/gateways
    ```

???+ example "🖇️ What are virtual servers and how do I use them?"
    A Virtual Server is a MCP Server composed from Tools/Resources/Prompts from multiple servers. Add one or more MCP Servers under "Gateways", then select which Tools/Prompts/Resources to use to create your Virtual Server.

---

## 🏎️ Performance Tuning & Scaling

???+ example "⚙️ What environment variables affect performance?"
    - `TOOL_CONCURRENT_LIMIT`
    - `TOOL_RATE_LIMIT`
    - `WEBSOCKET_PING_INTERVAL`
    - `SSE_RETRY_TIMEOUT`

???+ example "🧵 How do I scale the number of worker processes?"
    - `GUNICORN_WORKERS` (for Gunicorn)
    - `UVICORN_WORKERS` (for Uvicorn)

???+ example "📊 How can I benchmark performance?"
    Use `ab` or `wrk` against `/health` to measure raw latency.
    Check out the detail performance testing harness under `tests/hey`.

---

## 📈 Observability & Logging

???+ example "🔍 What metrics are available?"
    - Prometheus-style `/metrics` endpoint
    - Tool/server/prompt stats via Admin UI

???+ example "📜 What log formats are supported?"
    - `LOG_FORMAT=json` or `text`
    - Adjust with `LOG_LEVEL`

---

## 🧪 Smoke Tests & Troubleshooting

???+ example "🛫 Is there a full test script I can run?"
    Yes - see `docs/basic.md`.

???+ example "🚨 What common errors should I watch for?"
    | Symptom               | Resolution                             |
    |-----------------------|----------------------------------------|
    | 401 Unauthorized      | Refresh token / check Authorization    |
    | database is locked    | Use Postgres / increase DB_POOL_SIZE   |
    | already exists errors | Use *Show inactive* toggle in UI       |
    | SSE drops every 30 s  | Raise `SSE_RETRY_TIMEOUT`              |

---

## 💻 Integration Recipes

???+ example "🦜 How do I use MCP Gateway with LangChain?"
    ```python
    from langchain.tools import MCPTool
    tool = MCPTool(endpoint="https://localhost:4444/json-rpc",
                   token=os.environ["MCPGATEWAY_BEARER_TOKEN"])
    ```

???+ example "🦾 How do I connect GitHub's mcp-server-git via Translate Bridge?"
    ```bash
    python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 9001
    ```

---

## 🗺️ Roadmap

???+ info "🧭 What features are planned for future versions?"
    - 🔐 OAuth2 client-credentials upstream auth with full spec compliance
    - [🌙 Dark-mode UI](https://github.com/IBM/mcp-context-forge/issues/26)
    - [🧾 Add "Version and Environment Info" tab to Admin UI](https://github.com/IBM/mcp-context-forge/issues/25)
    - 🔒 Fine-grained role-based access control (RBAC) for Admin UI and API routes and per-virtual-server API keys
    - 📦 Marketplace-style tool catalog with categories, tags, and search
    - 🔁 Support for long-running / async tool executions with polling endpoints
    - 📂 UI-driven prompt and resource file management (upload/edit from browser)
    - 🛠️ Visual "tool builder" UI to design new tools with schema and auth interactively
    - 🧪 Auto-validation tests for registered tools (contract + mock invocation)
    - 🚨 Event subscription framework: trigger hooks or alerts on Gateway changes
    - 🧵 Real-time tool logs and debug traces in Admin UI
    - 🧠 Adaptive routing based on tool health, model, or load
    - 🔍 Filterable tool invocation history with replay support
    - 📡 Plugin-based architecture for custom transports or auth methods

    [Check out the Feature issues](https://github.com/IBM/mcp-context-forge/issues?q=is%3Aissue%20state%3Aopen%20label%3Aenhancement) tagged `enhancement` on GitHub for more upcoming features!

---

## ❓ Rarely Asked Questions (RAQ)

???+ example "🐙 Does MCP Gateway work on a Raspberry Pi?"
    Yes - build as `arm64` and reduce RAM/workers.

---

## 🤝 Contributing & Community

???+ tip "👩💻 How can I file issues or contribute?"
    Use [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues) and `CONTRIBUTING.md`.

???+ tip "🧑🎓 What code style and CI tools are used?"
    - Pre-commit: `ruff`, `black`, `mypy`, `isort`
    - Run `make lint` before PRs

???+ tip "💬 Where can I chat or ask questions?"
    Join the [GitHub Discussions board](https://github.com/IBM/mcp-context-forge/discussions).

---

### 🙋 Need more help?

Open an [Issue](https://github.com/IBM/mcp-context-forge/issues) or [discussion](https://github.com/IBM/mcp-context-forge/discussions) on GitHub.
