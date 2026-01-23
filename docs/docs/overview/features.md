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
    python3 -m mcpgateway.utils.create_jwt_token \
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
    | **gRPC Services** | gRPC microservices via automatic reflection | Protocol translation to MCP/JSON |

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

## 🔌 gRPC-to-MCP Translation

??? success "Automatic gRPC Integration"

    * **Server Reflection** - Automatically discovers gRPC services and methods
    * **Protocol Translation** - Converts between gRPC/Protobuf ↔ MCP/JSON
    * **Zero Configuration** - No manual schema definition required
    * **TLS Support** - Secure connections to gRPC servers
    * **Metadata Headers** - Custom gRPC metadata for authentication
    * **Admin UI** - Manage gRPC services via web interface

??? code "Register a gRPC service"

    ```bash
    # CLI: Expose gRPC service via HTTP/SSE
    python3 -m mcpgateway.translate --grpc localhost:50051 --port 9000

    # REST API: Register for persistence
    curl -X POST -H "Authorization: Bearer $TOKEN" \
         -H "Content-Type: application/json" \
         -d '{
               "name": "payment-service",
               "target": "payments.example.com:50051",
               "reflection_enabled": true,
               "tls_enabled": true
             }' \
         http://localhost:4444/grpc
    ```

??? info "How it works"

    1. Gateway connects to gRPC server using [Server Reflection Protocol](https://grpc.io/docs/guides/reflection/)
    2. Discovers all available services and methods automatically
    3. Translates Protobuf messages to/from JSON
    4. Exposes each gRPC method as an MCP tool
    5. Handles streaming (unary and server-streaming)

??? example "Supported gRPC features"

    | Feature | Status | Notes |
    |---------|--------|-------|
    | Unary RPCs | ✅ Supported | Request-response methods |
    | Server Streaming | ⚠️ Partial | Basic support implemented |
    | Client Streaming | 🚧 Planned | Future enhancement |
    | Bidirectional Streaming | 🚧 Planned | Future enhancement |
    | TLS/mTLS | ✅ Supported | Certificate-based auth |
    | Metadata Headers | ✅ Supported | Custom headers for auth |
    | Reflection | ✅ Required | Auto-discovery mechanism |

---

## 🖥 Admin UI

??? abstract "Built with"

    * **FastAPI** + Jinja2 + HTMX + Alpine.js
    * Tailwind CSS for styling

??? info "📊 Audit & Metadata Tracking"

    * **Comprehensive metadata** for all entities (Tools, Resources, Prompts, Servers, Gateways)
    * **Creation tracking** - who, when, from where, how
    * **Modification history** - change attribution and versioning
    * **Federation source** tracking for MCP server entities
    * **Bulk import** batch identification
    * **Auth-agnostic** - works with/without authentication
    * **Backwards compatible** - legacy entities show graceful fallbacks

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
