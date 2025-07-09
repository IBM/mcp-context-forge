# ✨ Features Overview

MCP Gateway is a **gateway + registry + proxy** purpose-built for the **Model Context Protocol (MCP)**. It unifies REST, MCP, and stdio worlds while
adding auth, caching, federation, and an HTMX-powered Admin UI.


---

## 🌐 Multi-Transport Core

???+ abstract "Supported Transports"

    | Transport | Description | Typical Use-case |
    |-----------|-------------|------------------|
    | **HTTP / JSON-RPC** | Low-latency request-response, default for most REST clients | Simple tool invocations |
    | **WebSocket** | Bi-directional, full-duplex | Streaming chat or incremental tool results |
    | **Server-Sent Events (SSE)** | Uni-directional server → client stream | LLM completions or real-time updates |
    | **STDIO** | Local process pipes via `mcpgateway-wrapper` | Editor plugins, headless CLI clients |

??? example "Try it: SSE from curl"

    ```bash
    curl -N -H "Accept: text/event-stream" \
         -H "Authorization: Bearer $TOKEN" \
         http://localhost:4444/servers/UUID_OF_SERVER_1/sse
    ```

---

## 🌍 Federation & Discovery

??? summary "Features"

    * **Auto-discovery** - DNS-SD (`_mcp._tcp.local.`) or static peer list
    * **Health checks** - fail-over + removal of unhealthy gateways
    * **Capability sync** - merges remote tool catalogs into the local DB
    * **Request forwarding** - automatic routing to the correct gateway

??? diagram "Architecture"

    ```mermaid
    graph TD
      subgraph Local_Gateway
        A[MCP Gateway Core]
      end
      subgraph Remote_Gateway_1
        B[Peer 1]
      end
      subgraph Remote_Gateway_2
        C[Peer 2]
      end
      A <-- ping / register --> B
      A <-- ping / register --> C
    ```

??? note "Configuration"

    Enable or tweak discovery via `.env`:

    ```env
    FEDERATION_ENABLED=true
    FEDERATION_DISCOVERY=true
    FEDERATION_PEERS=https://remote.example.com
    HEALTH_CHECK_INTERVAL=30
    ```

---

## 🔐 Security

??? tip "Auth mechanisms"

    * **JWT bearer** (default, signed with `JWT_SECRET_KEY`)
    * **HTTP Basic** for the Admin UI
    * **Custom headers** (e.g., API keys) per tool or gateway

??? info "Rate limiting"

    Set `MAX_TOOL_CALLS_PER_MINUTE` to throttle abusive clients.
    Exceeding the limit returns **HTTP 429** with a `Retry-After` header.

??? example "Generate a 24 h token"

    ```bash
    python -m mcpgateway.utils.create_jwt_token \
      --username alice --exp 1440 --secret "$JWT_SECRET_KEY"
    ```

---

## 🛠 Tool & Server Registry

??? success "What you can register"

    | Registry | Entities | Notes |
    |----------|----------|-------|
    | **Tools** | Native MCP tools or wrapped REST / CLI functions | JSON Schema input validation |
    | **Resources** | URIs for blobs, text, images | Optional SSE change notifications |
    | **Prompts** | Jinja2 templates + multimodal content | Versioning & rollback |
    | **Servers** | Virtual collections of tools/prompts/resources | Exposed as full MCP servers |

??? code "REST tool example"

    ```bash
    curl -X POST -H "Authorization: Bearer $TOKEN" \
         -H "Content-Type: application/json" \
         -d '{
               "name": "joke_api",
               "url": "https://icanhazdadjoke.com/",
               "requestType": "GET",
               "integrationType": "REST",
               "headers": {"Accept":"application/json"}
             }' \
         http://localhost:4444/tools
    ```

---

## 🖥 Admin UI

??? abstract "Built with"

    * **FastAPI** + Jinja2 + HTMX + Alpine.js
    * Tailwind CSS for styling

---

## 🗄 Persistence, Caching & Observability

??? info "Storage options"

    * **SQLite** (default dev)
    * **PostgreSQL**, **MySQL/MariaDB**, **MongoDB** - via `DATABASE_URL`

??? example "Redis cache"

    ```env
    CACHE_TYPE=redis
    REDIS_URL=redis://localhost:6379/0
    ```

??? abstract "Observability"

    * Structured JSON logs (tap with `jq`)
    * `/metrics` - Prometheus-friendly counters (`tool_calls_total`, `gateway_up`)
    * `/health` - readiness + dependency checks

---

## 🧩 Dev & Extensibility

??? summary "Highlights"

    * **Makefile targets** - `make dev`, `make test`, `make lint`
    * **400+ unit tests** - Pytest + HTTPX TestClient
    * **VS Code Dev Container** - Python 3.11 + Docker/Podman CLI
    * **Plug-in friendly** - drop-in FastAPI routers or Pydantic models

---

## Next Steps

* **Hands-on Walk-through** → [Quick Start](quick_start.md)
* **Deployment Guides** → [Compose](../deployment/compose.md), [K8s & Cloud](../deployment/index.md)
* **Admin UI deep dive** → [UI Guide](ui.md)

!!! success "Ready to explore"
    With transports, federation, and security handled for you, focus on building great **MCP tools, prompts, and agents**-the gateway has your back.
