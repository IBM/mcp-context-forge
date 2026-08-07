# Release History

Every stable release since General Availability, with the three most
impactful changes in each. For the complete list of changes, see the
[CHANGELOG](https://github.com/IBM/mcp-context-forge/blob/main/CHANGELOG.md);
for what's coming next, see the [ContextForge Roadmap](roadmap.md).

| Release | Date | Changes |
|---|---|---|
| **1.0.6** | 2026-07-21 | <ul><li>**MCP Apps support** — interactive UI resources served by MCP servers and rendered securely in agent clients</li><li>**RFC 8693 OAuth token exchange** — on-behalf-of delegation for virtual servers, plus per-user Vault credential resolution</li><li>**Dataplane capability publishing** — resource URIs, capabilities, and original tool names published from the dataplane</li></ul> |
| **1.0.5** | 2026-07-07 | <ul><li>**Versioned API** — all endpoints served under the `/v1` prefix, with OpenAPI-to-MCP tool schema generation</li><li>**Auth hardening** — environment-bound JWTs closing cross-environment token acceptance (GHSA-vgf8-3685-66j9)</li><li>**A2A compatibility** — JSON-RPC passthrough endpoints and sensitive-header forwarding controls</li></ul> |
| **1.0.4** | 2026-06-23 | <ul><li>**Rust server migration** — Rust benchmark server and A2A echo agent replace earlier implementations</li><li>**SSO `client_secret_basic` token exchange** for providers that require confidential-client authentication</li><li>**HTTP compliance** — RFC 6585 status codes and HTTP 202 Accepted responses for async operations</li></ul> |
| **1.0.3** | 2026-06-10 | <ul><li>**Auth & JWT cleanup** — OAuth `audience` parameter support and token-handling fixes</li><li>**FedRAMP/FIPS hardening** — opt-in FIPS compliance mode with parameterized base images</li><li>**PII redaction in logs** — sensitive data scrubbed from log output</li></ul> |
| **1.0.2** | 2026-05-25 | <ul><li>**Admin UI rewrite** — virtual server management, tools page cards, user management, and OAuth popup authorization flow</li><li>**Database migrations** — Alembic-based schema migration chain replaces ad-hoc bootstrapping</li><li>**A2A plugin framework integration** — agents participate in plugin hooks, with an A2A protocol version selector</li></ul> |
| **1.0.1** | 2026-05-13 | <ul><li>**Security hardening** — CSRF token validation, nonce-based CSP (no `unsafe-inline`), and a comprehensive password policy</li><li>**UAID cross-gateway auth forwarding** between federated gateways</li><li>**Operational tooling** — secrets-generation CLI and fail-closed environment-aware defaults</li></ul> |
| **1.0.0** | 2026-05-01 | <ul><li>**General Availability** — the first stable release of the ContextForge gateway</li><li>**JWT security** — server-side token revocation, idle timeout, and logout</li><li>**Content security** — malicious-pattern detection, prompt-template validation, and ReDoS defense for pattern scanning</li></ul> |
