# ContextForge - Frequently Asked Questions

## ⚡ Quickstart

???+ example "🚀 How can I install and run ContextForge in one command?"
    PyPI (pipx / uvx makes an isolated venv):

    ```bash
    # Using pipx - pip install pipx
    pipx run --spec mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444

    # Or uvx - pip install uv (default login: admin@example.com/changeme)
    uvx --from mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444
    ```

    OCI image (Docker/Podman) - shares host network so localhost works:

    ```bash
    podman run --network=host -p 4444:4444 ghcr.io/ibm/mcp-context-forge:1.0.0-RC-2
    ```

???+ example "🗂️ What URLs are available for the admin interface and API docs?"

    - Admin UI → `http://localhost:4444/admin` (or `http://localhost:8080/admin` with Compose)
    - Swagger → `http://localhost:4444/docs` (JWT-protected by default)
    - ReDoc → `http://localhost:4444/redoc` (JWT-protected by default)

    !!! tip
        Log in to the Admin UI to get a session cookie, or enable `DOCS_ALLOW_BASIC_AUTH=true` for Basic auth access to `/docs` and `/redoc`.

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
    > "ContextForge is an open-source reverse-proxy that unifies MCP and REST tool servers under a single secure HTTPS endpoint with discovery, auth and observability baked in."

---

## 🛠️ Installation & Configuration

???+ example "🔧 What is the minimal .env setup required?"
    ```bash
    cp .env.example .env
    ```

    Then edit:

    ```env
    # JWT authentication (required)
    JWT_SECRET_KEY=my-test-key

    # Admin UI login credentials
    PLATFORM_ADMIN_EMAIL=admin@example.com
    PLATFORM_ADMIN_PASSWORD=changeme
    ```

    !!! info "Authentication"
        The Admin UI uses email/password authentication. Basic auth for API endpoints is disabled by default for security. Use JWT tokens for API access.

???+ example "🪛 What are some advanced environment variables I can configure?"

    - Basic: `HOST`, `PORT`, `APP_ROOT_PATH`
    - Auth: `AUTH_REQUIRED`, `BASIC_AUTH_*`, `JWT_SECRET_KEY`
    - Logging: `LOG_LEVEL`, `LOG_FORMAT`, `LOG_TO_FILE`, `LOG_FILE`, `LOG_FOLDER`, `LOG_ROTATION_ENABLED`, `LOG_MAX_SIZE_MB`, `LOG_BACKUP_COUNT`
    - Transport: `TRANSPORT_TYPE`, `WEBSOCKET_PING_INTERVAL`, `SSE_RETRY_TIMEOUT`
    - Tools: `TOOL_TIMEOUT`, `MAX_TOOL_RETRIES`, `TOOL_RATE_LIMIT`, `TOOL_CONCURRENT_LIMIT`

---

## 🚀 Running & Deployment

???+ example "🏠 How do I run ContextForge locally using PyPI?"
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

???+ example "☁️ How can I deploy ContextForge on Google Cloud Run, Code Engine, Kubernetes, AWS, etc?"
    See the [Deployment Documentation](../deployment/index.md) for detailed deployment instructions across local, docker, podman, compose, AWS, Azure, GCP, IBM Cloud, Helm, Minikube, Kubernetes, OpenShift and more.

---

## 💾 Databases & Persistence

???+ info "🗄️ What databases are supported for persistence?"

    - SQLite (default) - used for development / small deployments.
    - PostgreSQL (recommended for production) via `DATABASE_URL`.
    - Redis (optional) for caching and federation.

???+ info "📦 How do I persist SQLite across container restarts?"
    Include a persistent volume with your container or Kubernetes deployment. Ex:

    ```bash
    docker run -v $(pwd)/data:/app ghcr.io/ibm/mcp-context-forge:1.0.0-RC-2
    ```

    For production use, we recommend PostgreSQL. A Docker Compose target with PostgreSQL and Redis is provided.

---

## 🔐 Security & Auth

???+ danger "🆓 How do I disable authentication for development?"
    Set `AUTH_REQUIRED=false` - disables login for local testing.

???+ example "🔑 How do I generate and use a JWT token?"
    ```bash
    export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
        --username admin@example.com --exp 10080 --secret my-test-key)
    curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools
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

???+ example "🔐 How do I pass Authorization headers to upstream MCP servers when the gateway uses authentication?"
    When ContextForge uses authentication (JWT/Bearer/Basic/OAuth), there's a conflict if you need to pass different Authorization headers to upstream MCP servers.

    **Solution: Use X-Upstream-Authorization header**

    ```bash
    # Send X-Upstream-Authorization header - gateway automatically renames it to Authorization for upstream
    curl -H "Authorization: Bearer $GATEWAY_TOKEN" \
         -H "X-Upstream-Authorization: Bearer $UPSTREAM_TOKEN" \
         -X POST http://localhost:4444/tools/invoke/my_tool \
         -d '{"arguments": {}}'
    ```

    The gateway will:

    1. Use the `Authorization` header for gateway authentication
    2. Rename `X-Upstream-Authorization` to `Authorization` when forwarding to the upstream MCP server
    3. This solves the header conflict and allows different auth tokens for gateway vs upstream

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
    A "Gateway" is another MCP Server. ContextForge itself is an MCP Server. This means you can add any MCP Server under "Gateways" and it will retrieve Tools/Resources/Prompts.

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

    - Run `mcpgateway --workers 4` (Uvicorn CLI flag)
    - Set `GUNICORN_WORKERS` when using the bundled Gunicorn scripts

???+ example "📊 How can I benchmark performance?"
    Use `hey` against `/rpc` with sample payloads from `tests/hey`.
    Focus on p99 latency, error rate, and throughput.

---

## 📈 Observability & Logging

???+ example "🔍 How do I enable tracing and observability?"
    Use OpenTelemetry (OTLP) to export traces to Phoenix, Jaeger, Zipkin, Tempo, DataDog, etc.

    ```bash
    export OTEL_ENABLE_OBSERVABILITY=true
    export OTEL_TRACES_EXPORTER=otlp
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    ```

    See the Observability docs for backend-specific setup. Admin UI also shows tool/server/prompt stats. A Prometheus `/metrics` endpoint may be added later.

???+ example "📜 What log formats are supported?"

    - `LOG_FORMAT=json` or `text`
    - Adjust with `LOG_LEVEL`

---

## 🧪 Smoke Tests & Troubleshooting

???+ example "🛫 Is there a full test script I can run?"
    Yes - see the basic testing guide: [Testing › Basic](../testing/basic.md).

???+ example "🚨 What common errors should I watch for?"
    | Symptom               | Resolution                             |
    |-----------------------|----------------------------------------|
    | 401 Unauthorized      | Refresh token / check Authorization    |
    | database is locked    | Use Postgres / increase DB_POOL_SIZE   |
    | already exists errors | Use *Show inactive* toggle in UI       |
    | SSE drops every 30 s  | Raise `SSE_RETRY_TIMEOUT`              |

???+ example "🔄 What happens if the database or Redis is temporarily unavailable?"
    The gateway uses **exponential backoff with jitter** for connection retries at startup:

    - **Retry pattern**: 2s → 4s → 8s → 16s → 30s (capped), with ±25% random jitter
    - **Default**: 30 retries ≈ 5 minutes total wait before worker exits
    - **Benefit**: Prevents CPU-intensive crash-respawn loops during dependency outages

    Configuration:
    ```bash
    DB_MAX_RETRIES=30              # Database retry attempts (default: 30)
    DB_RETRY_INTERVAL_MS=2000      # Base interval, doubles each attempt
    REDIS_MAX_RETRIES=30           # Redis retry attempts (default: 30)
    REDIS_RETRY_INTERVAL_MS=2000   # Base interval, doubles each attempt
    ```

    See [Performance Architecture › Startup Resilience](../architecture/performance-architecture.md#startup-resilience) for details.

---

## 💻 Integration Recipes

???+ example "🦜 How do I use ContextForge with LangChain?"
    ```python
    import os
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langgraph.prebuilt import create_react_agent

    client = MultiServerMCPClient(
        {
            "gateway": {
                "url": "http://localhost:4444/mcp",
                "transport": "streamable_http",
                "headers": {"Authorization": f"Bearer {os.environ['MCPGATEWAY_BEARER_TOKEN']}"}
            }
        }
    )
    agent = create_react_agent(tools=client.get_tools(), llm=your_language_model)
    ```

???+ example "🦾 How do I connect GitHub's mcp-server-git via Translate Bridge?"
    ```bash
    python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 9001
    ```

---

## 👥 Multi‑Tenancy & Migration (v0.7.0)

???+ example "🔐 How do I enable email/password login and teams?"
    Add the following to your `.env`:

    ```bash
    EMAIL_AUTH_ENABLED=true
    PLATFORM_ADMIN_EMAIL=admin@example.com
    PLATFORM_ADMIN_PASSWORD=changeme
    AUTO_CREATE_PERSONAL_TEAMS=true
    ```

    Upgrading from earlier releases? Follow [MIGRATION-0.7.0.md](https://github.com/IBM/mcp-context-forge/blob/main/MIGRATION-0.7.0.md).

???+ info "🔁 Does basic auth still work?"
    Basic auth for API endpoints is **disabled by default** for security. To enable it, set `API_ALLOW_BASIC_AUTH=true`. Email/password authentication is recommended for the Admin UI. For programmatic API access, use JWT tokens.

???+ info "🧩 How do teams and visibility work?"
    Users belong to teams. Resources (servers, tools, prompts, resources) can be `private`, `team`, or `public`. Assign via API or Admin UI. Use SSO mappings to auto‑assign teams.

---

## 🔐 SSO & Team Mapping

???+ example "👥 Can I auto‑assign users to teams via SSO?"
    Yes. Add **Team Mapping** rules to each SSO provider (Admin UI → Manage → SSO → Provider → Team Mapping). Example JSON:

    ```json
    {
      "team_mapping": {
        "your-org": {
          "team_id": "team-uuid",
          "role": "member"
        }
      }
    }
    ```

    You can manage the same payload via the Admin API (`/auth/sso/admin/providers/{id}`) — see the SSO guides under Manage › SSO.

---

## 🖧 Stdio Wrapper

???+ example "🧰 How do I use the stdio wrapper with Claude Desktop?"
    Configure a stdio server in your client:

    ```json
    {
      "mcpServers": {
        "mcpgateway-wrapper": {
          "command": "python3",
          "args": ["-m", "mcpgateway.wrapper"],
          "env": {
            "MCP_AUTH": "Bearer <your-token>",
            "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp",
            "MCP_TOOL_CALL_TIMEOUT": "120"
          }
        }
      }
    }
    ```

    See: [mcpgateway.wrapper](../using/mcpgateway-wrapper.md).

---

## 🧾 Protocol Version

???+ info "📜 Which MCP protocol version is supported?"
    You can choose the MCP protocol version (e.g., `2025-03-26`) when integrating. See README "Gateway Layer with Protocol Flexibility".

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

???+ example "🐙 Does ContextForge work on a Raspberry Pi?"
    Yes - build as `arm64` and reduce RAM/workers.

---

## 🤝 Contributing & Community

???+ tip "👩💻 How can I file issues or contribute?"
    Use [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues) and [CONTRIBUTING.md](https://github.com/IBM/mcp-context-forge/blob/main/CONTRIBUTING.md).

???+ tip "🧑🎓 What code style and CI tools are used?"

    - Pre-commit: `ruff`, `black`, `mypy`, `isort`
    - Run `make lint` before PRs

???+ tip "💬 Where can I chat or ask questions?"
    Join the [GitHub Discussions board](https://github.com/IBM/mcp-context-forge/discussions).

---

### 🙋 Need more help?

Open an [Issue](https://github.com/IBM/mcp-context-forge/issues) or [discussion](https://github.com/IBM/mcp-context-forge/discussions) on GitHub.
