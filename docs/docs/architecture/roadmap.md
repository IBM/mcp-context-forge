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

## 🔐 Authentication & Identity

### 🧭 [#87 Epic: JWT Token Catalog with Per-User Expiry and Revocation](https://github.com/IBM/mcp-context-forge/issues/87)

???+ "Token Lifecycle Management"
    **Generate Tokens:** As a platform admin, I want to generate one-time API tokens so I can issue short-lived credentials.

    **Revoke Tokens:** As a platform admin, I want to revoke tokens so I can disable exposed or obsolete tokens.

    **API Token Management:** As a user or automation client, I want to list, create, and revoke tokens via API so I can automate credential workflows.

🧭 Epic: Per-Virtual-Server API Keys

???+ "Scoped Server Access"
    **Server-Scoped Keys:** As a platform admin, I want to create API keys tied to a specific virtual server so that credentials are limited in scope.

    **Key Rotation & Revocation:** As a platform admin, I want to rotate or revoke a virtual server's API keys so I can maintain security without affecting other servers.

    **API Management UI & API:** As a developer, I want to list, create, rotate, and revoke server API keys via the Admin UI and REST API so I can automate credential lifecycle for each virtual server.

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

### 🧭 Epic: LDAP & External Identity Integration

???+ "Corporate Directory Auth"
    **LDAP Authentication:** As a platform admin, I want to configure LDAP/Active Directory so that users authenticate with corporate credentials.

    **Group Sync:** As a platform admin, I want to sync LDAP/AD groups into gateway roles so I can manage permissions via directory groups.

    **SSO Integration:** As a platform admin, I want to support SAML/OIDC so that teams can use existing single sign-on.

---

### 🧭 Epic: Role-Based Access Control (User/Team/Global Scopes)

???+ "RBAC & Scoping"
    **User-Level Scopes:** As a platform admin, I want to assign permissions at the individual user level so that I can grant fine-grained access.

    **Team-Level Scopes:** As a platform admin, I want to define teams and grant scopes to teams so that I can manage permissions for groups of users.

    **Global Scopes:** As a platform admin, I want to set global default scopes so that baseline permissions apply to all users.
