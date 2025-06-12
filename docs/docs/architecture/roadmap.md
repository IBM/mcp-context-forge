# Roadmap

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
