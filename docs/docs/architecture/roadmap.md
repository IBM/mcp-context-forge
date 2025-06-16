# Roadmap

---

## 🌐 Federation & Routing

### 🧭 Epic: Streamable HTTP Transport (Protocol Revision 2025-03-26)

> **Note:** stdio and the legacy HTTP+SSE transports are already supported; this epic adds the new Streamable HTTP transport per the 2025-03-26 spec.

* **HTTP POST Messaging**
  **As** an MCP client
  **I want** to send every JSON-RPC request, notification, or batch in a separate HTTP POST to the MCP endpoint, with `Accept: application/json, text/event-stream`
  **So that** the server can choose between immediate JSON replies or initiating an SSE stream.

* **SSE-Backed Streaming on POST**
  **As** a developer
  **I want** the server, upon receiving request-bearing POSTs, to return `Content-Type: text/event-stream` and open an SSE stream—emitting JSON-RPC responses, server-to-client requests, and notifications until complete—before closing the stream
  **So that** clients can consume large or real-time payloads incrementally without buffering.

* **Unsolicited Server Notifications via GET**
  **As** a client
  **I want** to open an SSE stream with a GET (using `Accept: text/event-stream`) to the same MCP endpoint
  **So that** I can receive unsolicited server-to-client messages independently of POST calls.

* **Session Management & Resumability**
  **As** an operator
  **I want** the server to issue a secure `Mcp-Session-Id` on Initialize, require it on subsequent calls (400 if missing), allow DELETE to terminate, and support SSE resumability via `Last-Event-ID` headers
  **So that** clients can manage, resume, and explicitly end long-running sessions robustly.

* **Security & Compatibility**
  **As** a platform admin
  **I want** to validate `Origin` headers, bind to localhost by default, and enforce authentication against DNS rebinding—while optionally preserving the legacy HTTP+SSE endpoints for backward compatibility with 2024-11-05 clients
  **So that** we uphold security best practices and maintain dual-transport support.

---

## 🌐 Federation & Routing

### 🧭 Epic: A2A Transport Support

Enable full-duplex, application-to-application (A2A) integration so that virtual servers and gateways can speak A2A natively.

* **A2A Gateway Registration**
  **As** a platform admin
  **I want** to register A2A-enabled servers as gateways (in addition to HTTP/SSE/WS)
  **So that** I can federate A2A backends alongside standard MCP peers.

* **A2A Tool Invocation**
  **As** a developer
  **I want** to call A2A servers as tools via the A2A protocol
  **So that** A2A-native services appear in my tool catalog and handle messages over A2A transports.

* **Expose Virtual Servers via A2A**
  **As** an operator
  **I want** to expose virtual servers (i.e. REST-wrapped MCP servers) over the A2A transport
  **So that** clients that only support A2A can invoke those servers transparently.

---

## ⚙️ Lifecycle & Management

### 🧭 Epic: Virtual Server Protocol Version Selection

Allow choosing which MCP protocol version each virtual server uses.

* **Per-Server Protocol Version**
  **As** a platform admin
  **I want** to specify the MCP protocol version (e.g. 2025-03-26 or earlier) on each virtual server
  **So that** clients requiring legacy behavior can continue to work without affecting others.

* **Protocol Compatibility Testing**
  **As** a developer
  **I want** to validate a virtual server's behavior against multiple protocol versions in the Admin UI
  **So that** I can catch breaking changes before rolling out new servers.

---

## 📈 Observability & Telemetry

### 🧭 Epic: OpenTelemetry Tracing & Metrics Export

???+ "Trace & Metric Visibility"
    **Distributed Tracing:** As a developer, I want traces spanning tools, prompts, and gateways so I can understand multi-step flows.

    **Metrics Scraping:** As an SRE, I want a Prometheus-compatible `/metrics` endpoint so I can alert on latency and error rate.

### 🧭 Epic: Structured JSON Logging with Correlation IDs

???+ "Context-Rich Logging"
    **Correlation IDs:** As a DevOps user, I want logs with correlation and trace IDs so I can trace a request across services.

---

## ⚙️ Lifecycle & Management

### 🧭 Epic: Hot Configuration Reload

???+ "Dynamic Config Updates"
    **In-Place Reload:** As a system admin, I want to apply config changes (tools, servers, resources) without restarts so I maintain zero-downtime.

### 🧭 Epic: CLI Enhancements for Admin Operations

???+ "Automated Admin Commands"
    **Admin CLI:** As a DevOps engineer, I want CLI subcommands to register tools, flush caches, and export configs so I can integrate with CI/CD.

### 🧭 Epic: Config Import/Export (JSON Gateways & Virtual Servers)

???+ "JSON Config Portability"
    **Individual Entity Export/Import:** As a platform admin, I want to export or import a single gateway or virtual server's config in JSON so I can backup or migrate that one entity.

    **Bulk Export/Import:** As a platform admin, I want to export or import the full configuration (all gateways, virtual servers, prompts, resources) at once so I can replicate environments or perform large-scale updates.

    **Encrypted Credentials:** As a security-conscious operator, I want passwords and sensitive fields in exported JSON to be encrypted so my backups remain secure.

???+ "Automated Admin Commands"
    **Admin CLI:** As a DevOps engineer, I want CLI subcommands to register tools, flush caches, and export configs so I can integrate with CI/CD.

### 🧭 Epic: Cache Management API

???+ "Cache Control"
    **Cache Inspection & Flush:** As a site admin, I want endpoints to view cache stats and clear entries so I can manage data freshness.

---

## 🌐 Federation & Routing

### 🧭 Epic: Dynamic Federation Management

???+ "Peer Gateway Management"
    **Register/Remove Peers:** As a platform admin, I want to add or remove federated gateways at runtime so I can scale and maintain federation.

### 🧭 Epic: Circuit Breakers for Unstable Backends

???+ "Backend Isolation"
    **Circuit Breaker:** As the gateway, I want to trip circuits for backends after repeated failures so I prevent cascading retries.

### 🧭 Epic: Intelligent Load Balancing for Redundant Servers

???+ "Smart Request Routing"
    **Adaptive Balancing:** As an orchestrator, I want to route to the fastest healthy backend instance so I optimize response times.

---

## 🛠️ Developer Experience

### 🧭 Epic: Prompt Template Tester & Validator

???+ "Prompt Validation"
    **Template Linting:** As a prompt engineer, I want to preview and validate Jinja2 templates with sample data so I avoid runtime errors.

### 🧭 Epic: System Diagnostics & Self-Check Report

???+ "Diagnostics Bundle"
    **Diagnostic Export:** As an operator, I want a self-contained system report (config, health, metrics) so I can troubleshoot effectively.

### 🧭 Epic: Auto-Tuning of Timeout & Retry Policies

???+ "Adaptive Policy Tuning"
    **Auto-Tuning:** As the gateway, I want to adjust timeouts and retry intervals based on observed latencies so I balance reliability and speed.

---

## 📦 Resilience & Runtime

### 🧭 Epic: Graceful Startup and Shutdown

???+ "Graceful Lifecycle"
    **In-Flight Draining:** As the gateway, I want to complete active requests before shutdown so I prevent dropped connections.

### 🧭 Epic: High Availability via Stateless Clustering

???+ "Clustered Scaling"
    **Stateless Instances:** As an architect, I want multiple interchangeable gateway nodes so I can load-balance and ensure failover.

---

## 🧭 Namespaces & Catalog Integrity

### 🧭 Epic: Name Collision Handling in Federated Catalogs

???+ "Unified Naming"
    **Namespaced Tools:** As an operator, I want to distinguish identical tool names from different servers (e.g. `ServerA/toolX` vs `ServerB/toolX`) so I avoid conflicts.

---

## 🔐 Secrets & Sensitive Data

### 🧭 Epic: Secure Secrets Management & Masking

???+ "Externalized Secrets"
    **Secret Store Integration:** As an operator, I want to fetch credentials from a secrets manager so I avoid storing secrets in static configs.

    **Log Scrubbing:** As a compliance officer, I want sensitive data masked in logs and metrics so I maintain data security.

---


## 🛠️ Developer Experience

---

### 🧭 Epic: Chrome MCP Plugin Integration

???+ "Browser-Based MCP Management"
    **Plugin Accessibility:**
    As a developer, I want a Chrome extension to manage MCP configurations, servers, and connections directly from the browser
    **So that** I can reduce dependency on local CLI tools and improve accessibility.

    **Key Features:**
    - **Real-Time Session Control:** Monitor and interact with MCP sessions via a browser UI.
    - **Cross-Platform Compatibility:** Ensure the plugin works seamlessly across devices and operating systems.
    - **Secure API Proxy:** Route requests securely via `mcpgateway.translate` or `mcpgateway.wrapper` for token-based access.

    **Implementation Notes:**
    - Distributed via the Chrome Web Store.
    - Uses JWT tokens stored in extension config or injected from Admin UI.
    - Interfaces with public `/servers`, `/tools`, `/resources`, and `/message` endpoints.

---

### 🧭 Epic: Transport-Translation Bridge (`mcpgateway.translate`)

???+ "CLI Bridge for Any-to-Any Transport"
    **Goal:** As a CLI user or integrator, I want to bridge stdio-only MCP servers to modern transports like SSE, WS, or Streamable HTTP

    **So that** I can use legacy binaries in web clients or tunnel remote services locally.

    **Scenarios:**
    - **Stdio ➜ SSE:**
      Expose a local binary (e.g., `uvx mcp-server-git`) at `http://localhost:9000/sse`.

    - **SSE ➜ Stdio:**
      Tunnel a remote SSE server to `stdin/stdout` so CLI tools can talk to it natively.

    - **Health & CORS:**
      Add `/healthz` and CORS allowlist for reverse proxies and browser integrations.

    - **Dockerized:**
      Run the bridge as a standalone container from GHCR with no Python installed.

    **Example CLI Usage:**

    ```bash
    mcpgateway.translate \
      --stdio "uvx mcp-server-git" \
      --port 9000 \
      --ssePath /sse \
      --messagePath /message \
      --healthEndpoint /healthz \
      --cors "https://app.example.com"
    ```

    **Design:**

    - Uses async pumps between transport pairs (e.g., `Stdio ↔ SSE`, `SSE ↔ WS`).
    - Maintains JSON-RPC fidelity and session state.
    - Adapts message framing (e.g., Base64 for binary over SSE).
    - Secure headers injected via `--header` or `--oauth2Bearer`.

    **Docker:**

    ```bash
    docker run --rm -p 9000:9000 \
      ghcr.io/ibm/mcp-context-forge:translate
    ```

    **Acceptance Criteria:**

    - CLI and Docker bridge exposes `/sse` and `/message` for bidirectional MCP.
    - Session ID and keep-alives handled automatically.
    - Fully observable (`--logLevel`, Prometheus metrics, JWT headers, etc).
    - Invalid flag combinations yield clean error output.

    **Security:**

    - Honors `MCP_AUTH_TOKEN` and CORS allowlist.
    - Redacts tokens in logs.
    - Supports TLS verification toggle (`--skipSSLVerify`).

    ---


---

### 🧭 Epic: One-Click Download of Ready-to-Use Client Config

???+ "Copy Config for Claude or CLI"
    **Goal:**
    As a user viewing a virtual server in the Admin UI, I want a button to **download a pre-filled Claude JSON config**

    **So that** I can immediately use the selected server in `Claude Desktop`, `mcpgateway.wrapper`, or any stdio/SSE-based client.

    **Use Cases:**

    - **Claude Desktop (stdio wrapper):**
      Download a `.json` config that launches the wrapper with correct `MCP_SERVER_CATALOG_URLS` and token pre-set.
    - **Browser / SSE Client:**
      Download a `.json` or `.env` snippet with `Authorization` header, SSE URL, and ready-to-paste curl/Javascript.

    **Implementation Details:**

    - Button appears in the Admin UI under each virtual server's **View** panel.
    - Config supports:
        - `mcpgateway.wrapper` (for stdio clients)
        - `/sse` endpoint with token (for browser / curl)
    - JWT token is generated or reused on demand.
    - Filled-in config includes:
        - Virtual server ID
        - Base gateway URL
        - Short-lived token (`MCP_AUTH_TOKEN`)
        - Optional Docker or pipx run command
    - Claude Desktop format includes `command`, `args`, and `env` block.

    **API Support:**

    - Add endpoint:
      ```http
      GET /servers/{id}/client-config
      ```
    - Optional query params:
        - `type=claude` (default)
        - `type=sse`
    - Returns JSON config with headers:
      ```
      Content-Disposition: attachment; filename="claude-config.json"
      Content-Type: application/json
      ```

    **Example (Claude-style JSON):**

    ```json
    {
      "mcpServers": {
        "server-alias": {
          "command": "python3",
          "args": ["-m", "mcpgateway.wrapper"],
          "env": {
            "MCP_AUTH_TOKEN": "example-token",
            "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/3",
            "MCP_TOOL_CALL_TIMEOUT": "120"
          }
        }
      }
    }
    ```

    **Example (curl-ready SSE config):**

    ```bash
    curl -H "Authorization: ..." \
        http://localhost:4444/servers/3/sse
    ```

    **Acceptance Criteria:**

    - UI exposes a single **Download Config** button per server.
    - Endpoint `/servers/{id}/client-config` returns fully populated config.
    - Tokens are scoped, short-lived, or optionally ephemeral.
    - Claude Desktop accepts the file without user edits.

    **Security:**

    - JWT token is only included if the requester is authenticated.
    - Download links are protected behind user auth and audit-logged.
    - Expiry and scope settings match user profile or server defaults.

    **Stretch goal:**

    - Toggle to choose between Claude, curl, or Docker styles.
    - QR code output or "Copy to Clipboard" button. QR might work with the phone app, etc.

    ---







### 🧭 Epic: LDAP & External Identity Integration

???+ "Corporate Directory Auth"
    **LDAP Authentication:** As a platform admin, I want to configure LDAP/Active Directory so that users authenticate with corporate credentials.

    **Group Sync:** As a platform admin, I want to sync LDAP/AD groups into gateway roles so I can manage permissions via directory groups.

    **SSO Integration:** As a platform admin, I want to support SAML/OIDC so that teams can use existing single sign-on.

---

## 🔐 Authentication, Authorization, Security & Identity

### 🧭 [#87 Epic: JWT Token Catalog with Per-User Expiry and Revocation](https://github.com/IBM/mcp-context-forge/issues/87)

???+ "Token Lifecycle Management"
    - **Generate Tokens:**
        As a platform admin, I want to generate one-time API tokens so I can issue short-lived credentials.
    - **Revoke Tokens:**
        As a platform admin, I want to revoke tokens so I can disable exposed or obsolete tokens.
    - **API Token Management:**
        As a user or automation client, I want to list, create, and revoke tokens via API so I can automate credential workflows.

---

### 🧭 Epic: Per-Virtual-Server API Keys

???+ "Scoped Server Access"
    - **Server-Scoped Keys:**
        As a platform admin, I want to create API keys tied to a specific virtual server so that credentials are limited in scope.
    - **Key Rotation & Revocation:**
        As a platform admin, I want to rotate or revoke a virtual server's API keys so I can maintain security without affecting other servers.
    - **API Management UI & API:**
        As a developer, I want to list, create, rotate, and revoke server API keys via the Admin UI and REST API so I can automate credential lifecycle for each virtual server.

---

### 🧭 Epic: Role-Based Access Control (User/Team/Global Scopes)

???+ "RBAC & Scoping — Overview"
    - **User-Level Scopes:**
        As a platform admin, I want to assign permissions at the individual-user level so that I can grant fine-grained access.
    - **Team-Level Scopes:**
        As a platform admin, I want to define teams and grant scopes to teams so that I can manage permissions for groups of users.
    - **Global Scopes:**
        As a platform admin, I want to set global default scopes so that baseline permissions apply to all users.

???+ "1️⃣ Core Role / Permission Model"
    - **Define Canonical Roles:**
        Built-in `Owner`, `Admin`, `Developer`, `Read-Only`, and `Service` roles.
        *Acceptance Criteria:*
        - Roles stored in `roles` table, seeded by migration
        - Each role maps to a JSON list of named permissions (e.g. `tools:list`)
        - Unit tests prove `Read-Only` cannot mutate anything
    - **Fine-Grained Permission Catalog:**
        - Full CRUD coverage for `tools`, `servers`, `resources`, `prompts`, `gateways`
        - Meta-permissions like `metrics:view`, `admin:impersonate`
        - All FastAPI routes must declare a permission via decorator

???+ "2️⃣ Scope Hierarchy & Resolution"
    - **Precedence:**
        Global → Team → User; resolution returns union of allow rules minus any denies.
    - **Wildcards:**
        Support `tools:*`, `admin:*` and expand dynamically into specific scopes.

???+ "3️⃣ Teams & Membership"
    - **Team CRUD APIs & UI:**
        Admin panel and REST API for team management (`GET/POST/PATCH/DELETE`), plus CSV/JSON import with dry-run mode.
    - **Nested Teams (Optional v2):**
        Support hierarchical teams with depth-first inheritance and first-match-wins precedence.

???+ "4️⃣ OAuth 2.1 / OIDC Integration"
    - **External IdP Mapping:**
        SSO/OIDC `groups` and `roles` claims map to gateway teams via a `team_mappings` table.
    - **PKCE Auth Code Flow:**
        Public clients get redirected to IdP; receive gateway-signed JWT with scopes in `scp` claim.
    - **Refresh-Token Rotation & Revocation List:**
        Short-lived access tokens (≤15 min), refresh token rotation, revocation checked per request.

???+ "5️⃣ Service / Machine Credentials"
    - **Client-Credentials Grant:**
        CI systems and automation can obtain scoped access tokens using client ID and secret.
    - **Signed JWT Actor Tokens:**
        Internal components can impersonate users or declare service identities via signed JWTs with `act` and `sub`.

???+ "6️⃣ Enforcement Middleware"
    - **FastAPI Dependency:**
        `require_scope("...")` uses JWT and Redis permission cache; 403 on scope mismatch.
    - **Transport-Level Guards:**
        HTTP/SSE/A2A transports reject missing or invalid scopes early (401/403).

???+ "7️⃣ Delegated (On-Behalf-Of) Flow"
    - **User-Delegated Tokens:**
        Users can mint scoped, short-lived tokens for agents to act on their behalf (e.g. tool calls); modal in Admin UI allows setting scopes and expiry.

???+ "8️⃣ Audit & Observability"
    - **RBAC Audit Log:**
        Logs every grant/revoke/login with full metadata (who, what, when, IP, UA); exports to JSON Lines and Prometheus metrics (`authz_denied_total`).
    - **Correlation IDs:**
        403s include `correlation_id` header for traceability in logs and dashboards.

???+ "9️⃣ Self-Service Permission Inspector"
    - **Why-Denied Endpoint:**
        `POST /authz/explain` returns an evaluation trace (role → scope → result); Admin UI visualizes graph with colored indicators.

???+ "🔟 Migration & Back-Compat"
    - **Mixed-Mode Auth Toggle:**
        Support `AUTH_MODE=legacy|rbac`; legacy JWTs fallback to a `compat` role.
    - **Data Migration Scripts:**
        Alembic sets up `roles`, `permissions`, `teams`; CLI `mcpgateway migrate-rbac` assigns global admins from legacy data.

???+ "✅ Definition of Done"
    - All HTTP/SSE/WS/A2A routes enforce scopes; fuzz tests confirm no bypass
    - Full Admin UI coverage for role, team, and permission management
    - End-to-end: IdP login → group-to-team mapping → scope-enforced tool access
    - Regression tests for scope resolution, wildcard expansion, token lifecycles, delegated access, and audit logging
    - Upgrade guide and SDK usage examples available in documentation
