# Features

MCP Gateway offers a robust feature set for integrating and managing tools, servers, prompts, and resources under the Model Context Protocol.

---

## 🧠 Core Capabilities

- **Full MCP 2025-03-26 Protocol Support**
  Implements all required methods: `initialize`, `ping`, `notify`, `complete`, `createMessage`, and fallback JSON-RPC.

- **Multi-Transport Support**
  Accessible via:

  - HTTP/JSON-RPC
  - WebSocket (bi-directional with ping/pong)
  - Server-Sent Events (SSE)
  - stdio (for subprocess embedding)

- **Unified Registry**
  Maintains a centralized catalog of:

  - Tools (native or REST-adapted)
  - Prompts (Jinja2 templates with schema validation)
  - Resources (MIME-aware, URI-addressable)
  - Servers (virtual or federated)
  - Federated Gateways

---

## 🌐 Federation & Discovery

- Peer discovery (mDNS or explicit list)
- Periodic health checks with failover logic
- Transparent merging of capabilities
- Federation timeouts, retries, and sync intervals configurable

---

## 🛠 Tool Management

- Register tools via REST, UI, or JSON-RPC
- Wrap any REST API, CLI command, or function
- Supports:

  - JSON Schema validation
  - Concurrency limits
  - Rate limiting
  - Retry policies
  - Output filtering via JSONPath

---

## 💬 Prompt Templates

- Jinja2-powered text blocks
- Enforced schema (required/optional args)
- Versioned templates with rollback
- Used by agents and sampling calls

---

## 📦 Resource Handling

- URI-addressed resources
- MIME type detection
- LRU+TTL caching (in-memory, Redis, or DB)
- SSE-based subscriptions to dynamic resources

---

## 📊 Observability

- Structured JSON logs
- Log levels per route
- `/health` endpoint with live latency stats
- Metrics for tools, servers, prompts, and gateways

---

## 🖥 Admin Interface

- Interactive UI with full CRUD for:

  - Tools
  - Resources
  - Prompts
  - Servers
  - Gateways
  - Roots
- Built with HTMX, Alpine.js, and Tailwind CSS

---

## 🔐 Authentication & Security

- Supports both Basic and JWT authentication
- Bearer tokens signed with configurable secrets
- TLS verification options
- Optional anonymous/public mode (`AUTH_REQUIRED=false`)
