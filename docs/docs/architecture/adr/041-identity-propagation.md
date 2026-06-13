# ADR-0041: End-User Identity Propagation

- *Status:* Accepted
- *Date:* 2026-02-17
- *Deciders:* Mihai Criveti

## Context

MCP Gateway authenticates inbound requests and extracts user identity (email, teams, roles, admin status) but does not forward any of this identity information to downstream MCP servers when proxying. This means:

- **Upstream MCP servers** never receive the calling user's identity, making per-user authorization and auditing impossible at the upstream level.
- **Plugins** only see user identity when explicitly opted in via `include_user_info=True`, and even then only limited fields.
- **Audit trails** lack authentication method and delegation context, making compliance reporting incomplete.
- **On-behalf-of flows** (RFC 8693 token exchange) are not supported, preventing delegated access patterns common in enterprise environments.

This is a blocking requirement for multi-tenant deployments where upstream services need to enforce their own access control based on the original caller's identity.

## Decision

Implement a comprehensive identity propagation system with the following components:

### 1. UserContext Model

A structured `UserContext` Pydantic model captures the full authenticated identity:

```python
class UserContext(BaseModel):
    user_id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_admin: bool = False
    groups: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    team_id: Optional[str] = None
    teams: Optional[list[str]] = None
    department: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    auth_method: Optional[str] = None
    authenticated_at: Optional[datetime] = None
    service_account: Optional[str] = None
    delegation_chain: list[str] = Field(default_factory=list)
```

This model is populated unconditionally for all authenticated requests (removing the `include_user_info` gate) and stored on `GlobalContext.user_context`.

### 2. Propagation Mechanisms

Identity is forwarded to upstream servers through two complementary mechanisms:

| Mechanism | Transport | Use Case |
|-----------|-----------|----------|
| **HTTP headers** | `X-Forwarded-User-*` | REST proxying, health checks, tool invocation over HTTP |
| **MCP `_meta` field** | JSON in MCP protocol | Native MCP tool calls, resource reads |

Operators choose via `IDENTITY_PROPAGATION_MODE`: `headers`, `meta`, or `both` (default).

### 3. Feature Flag and Per-Gateway Override

- **Global toggle**: `IDENTITY_PROPAGATION_ENABLED=false` (off by default, zero behavioral change for existing deployments)
- **Per-gateway override**: Each gateway registration can set its own `identity_propagation` JSON config, overriding mode, header prefix, signing, and allowed attributes.

### 4. Sensitive Attribute Filtering

A configurable list (`IDENTITY_SENSITIVE_ATTRIBUTES`) strips internal-only fields (password hashes, internal IDs) before propagation. The `UserContext` is copied — the original is never mutated.

### 5. HMAC Claim Signing

Optional HMAC-SHA256 signing (`IDENTITY_SIGN_CLAIMS=true`) allows upstream servers to verify that identity claims originated from the gateway and were not tampered with.

### 6. Audit Trail Enhancement

Three new fields on `AuditTrail` records:

- `auth_method`: How the user authenticated (bearer, api_key, basic, sso, proxy)
- `acting_as`: Service account identity for delegation scenarios
- `delegation_chain`: Full chain of delegated identities

### 7. RFC 8693 Token Exchange

An `OAuthManager.token_exchange()` method supports on-behalf-of flows for gateways that require a user-scoped access token rather than client credentials.

> **Update (2026-06):** Implemented. See "Implementation Update: RFC 8693 Token Exchange" below for the realized design.

## Implementation Update: RFC 8693 Token Exchange

- *Status:* Implemented
- *Date:* 2026-06

RFC 8693 / On-Behalf-Of token exchange (item 7 above) was implemented via **Approach B**: a central resolver-method seam rather than a new standalone service. Each consuming service (`ToolService`, `GatewayService`) gets its own `_resolve_token_exchange_header()` resolver, backed by a shared `TokenExchangeCache`.

### Configuration

A gateway's `oauth_config` opts into the flow with `grant_type: "token-exchange"`, plus:

- `target_audience` (required) — the downstream resource the exchanged token is for.
- `subject_token_source` (default `inbound_user_jwt`) — `inbound_user_jwt` uses the caller's ContextForge JWT as the RFC 8693 `subject_token`; `user_oauth_token` uses the user's previously stored per-gateway OAuth token instead (supported on the tool-invocation path).
- `requested_token_type` (default `urn:ietf:params:oauth:token-type:access_token`).

### Resolver Seam (Approach B)

- `ToolService._resolve_token_exchange_header()` covers the tool-invocation path and supports both `subject_token_source` values.
- `GatewayService._resolve_token_exchange_header()` covers gateway connection/health-check paths, which have no per-request user context and therefore **fail closed** for `token-exchange` gateways (only `inbound_user_jwt` is meaningful on a per-request path).
- `GatewayService._validate_token_exchange_config()` performs SSRF-style validation of `token_url` at gateway create/update time.

### Caching

A shared `TokenExchangeCache` (Redis-backed with in-memory fallback) caches exchanged tokens per gateway/user/audience:

- TTL derived from the Authorization Server's `expires_in`.
- Single-flight de-duplication of concurrent exchange requests for the same key.
- Negative caching of failed exchanges to avoid hammering the AS during outages.
- On a downstream `401`, the cache entry is invalidated and exactly one re-exchange is attempted before the request fails.

### Security Boundary

With `subject_token_source: inbound_user_jwt`, the caller's ContextForge JWT is POSTed to `token_url` as the `subject_token` — but it is **never forwarded to the downstream MCP server**. Only the token returned by the exchange is sent upstream as the `Bearer` credential. `token_url` is therefore an SSRF/egress boundary validated at config time, and creating or modifying `token-exchange` gateways is a privileged action requiring a shared-issuer trust relationship between ContextForge and the downstream IdP.

### Audit

Token exchange attempts (success, failure, and degraded/negative-cache responses) are recorded via `audit_token_exchange`, writing both a structured log entry and a `StructuredLogEntry` database row with `is_security_event=True`, keyed by `correlation_id`. Typed audit columns are deferred to a Phase 2 follow-up with its own Alembic migration.

### Documentation

See [Token Exchange (RFC 8693 / On-Behalf-Of)](../oauth-design.md#token-exchange-rfc-8693--on-behalf-of) and [Migrating OAuth Gateways to Token Exchange](../../manage/identity-propagation.md#migrating-oauth-gateways-to-token-exchange).

## Consequences

### Positive

- Upstream MCP servers can make **per-user authorization decisions** without trusting the gateway blindly
- **Audit trails** are complete with authentication method and delegation context
- **Plugins always see identity** — no more opt-in gate that most deployments forget to enable
- **Per-gateway configuration** allows gradual rollout and mixed-trust topologies
- **Zero breaking changes** — feature is off by default, existing `GlobalContext.user` dict is preserved for backward compatibility
- **Claim signing** provides cryptographic verification for zero-trust upstream environments

### Negative

- Additional HTTP headers on every proxied request (minimal overhead — 6-10 headers, ~500 bytes)
- Per-gateway config adds complexity to gateway registration schema
- HMAC signing adds a small computational cost per request when enabled

### Risks / Mitigations

- **Header injection**: Upstream servers must trust that identity headers come from the gateway, not from clients. Mitigated by HMAC signing and by ensuring the gateway strips any client-provided `X-Forwarded-User-*` headers before adding its own.
- **Sensitive data leakage**: Mitigated by the configurable `IDENTITY_SENSITIVE_ATTRIBUTES` filter that strips internal fields before propagation.
- **Session isolation**: Different users must get isolated upstream sessions. Mitigated by including identity headers in the session affinity key, ensuring different users get separate upstream connections.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Mutual TLS with client certs per user | Too complex for most deployments; requires per-user certificate management |
| OAuth token forwarding (pass-through) | Exposes the gateway's internal tokens to upstream servers; violates least-privilege |
| Custom protocol-level identity field | Non-standard; HTTP headers and MCP `_meta` are the natural extension points |
| Always-on propagation (no feature flag) | Would change behavior for all existing deployments; feature flag allows opt-in |

## Related

- Feature: [Identity Propagation Guide](../../manage/identity-propagation.md)
- Configuration: [Configuration Reference](../../manage/configuration.md#identity-propagation)
- Architecture: [Multi-tenancy](../multitenancy.md)
- Issue: [#1436](https://github.com/IBM/mcp-context-forge/issues/1436)
