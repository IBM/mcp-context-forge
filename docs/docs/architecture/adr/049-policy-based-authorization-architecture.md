# ADR-049: Policy-Based Authorization Architecture

- *Status:* Proposed
- *Date:* 2026-04-12
- *Deciders:* Platform Team
- *Implements:* [ADR-045](045-auth-remains-in-core.md) (Authentication and Authorization Remain in Core)
- *Related:* [ADR-004](004-combine-jwt-and-basic-auth.md), [ADR-043](043-rust-mcp-runtime-sidecar-mode-model.md), [ADR-044](044-module-communication-protocol.md), [Security Features](../security-features.md), [RFC 9728 Compliance](../rfc9728-compliance.md), [OAuth Design](../oauth-design.md)

## Context

### The problem: sprawling conditional auth logic

ContextForge's authorization logic has grown organically into a deeply
nested if-then-else tree distributed across at least five files and four
middleware layers. The most visible symptom is
`_check_resource_team_ownership()` in `token_scoping.py` (lines 817-1177),
which implements the **identical** visibility decision —
public/team/private check, public-only-token guard, team membership match,
owner-email match, unknown-visibility deny — **five separate times**, once
per resource type (server, tool, resource, prompt, gateway). The only
variation between the five blocks is the ORM model queried and the log
message noun. But the problem is not confined to resource visibility: the
same pattern of scattered, duplicated conditional logic pervades token
authentication, permission checks, and transport-level enforcement.

This is not merely an aesthetics issue. It creates concrete risks:

1. **Behavioral drift.** When the visibility model changes (e.g., adding a
   `"restricted"` tier, or supporting multi-team ownership), the change must
   be applied identically in five places. History shows that copy-paste
   policy blocks diverge over time.
2. **Audit difficulty.** A security reviewer must read ~350 lines of
   near-identical code to confirm that all resource types enforce the same
   policy. There is no single policy definition to verify.
3. **Incomplete separation of concerns.** The token scoping middleware
   performs direct ORM queries, imports models at call time, manages its own
   DB sessions, and mixes authorization logic with resource lookup. This
   makes the authorization layer untestable in isolation and impossible to
   reimplement in Rust without also reimplementing the ORM layer.
4. **Scattered auth entry points.** Authentication is checked in at least
   four distinct locations:
   - `_StreamableHttpAuthHandler.authenticate()` in
     `streamablehttp_transport.py` (ASGI-level, before path rewrite)
   - `AuthContextMiddleware` in `auth_middleware.py` (early user extraction)
   - `TokenScopingMiddleware` in `token_scoping.py` (visibility + RBAC)
   - `get_current_user_with_permissions()` in `rbac.py` (handler-level)
   - Rust sidecar's `authenticate_public_request_if_needed()` in `lib.rs`

   Each location has slightly different handling for edge cases (proxy trust,
   cookie rejection, empty bearer, OAuth enforcement, permissive mode).

### The trajectory: gateway-control-bus with Rust edge

ADR-043 through ADR-047 establish that ContextForge is migrating toward a
modular architecture where Rust owns the public edge and Python retains
authority over authentication and authorization. ADR-045 explicitly states
that auth **never moves into modules** — modules consume auth through a
core-owned SPI.

The current architecture partially implements this via internal HTTP
endpoints (`/_internal/mcp/authenticate`), but the auth logic itself
remains tangled with Python middleware, ORM queries, and transport-specific
concerns. For the Rust edge to enforce policy, the policy must be
expressible as a **data-driven contract**, not as Python if-then-else
chains.

### What this ADR addresses

This ADR proposes a redesigned authorization architecture for
ContextForge that:

- Replaces copy-paste visibility checks with a single, resource-type-agnostic
  policy evaluation path
- Unifies scattered authentication entry points into a single typed contract
- Separates resource lookup from authorization decisions
- Defines a policy contract that can be consumed by both Python and Rust
  runtimes, enabling the gateway-control-bus migration
- Identifies the RFC/standards surface that must be supported
- Surveys open source projects that could accelerate implementation

## Decision

We adopt a **policy-based authorization architecture** that replaces the
current procedural if-then-else chains with a structured policy evaluation
model. The architecture has four layers:

### Layer 0: Token Authentication (identity establishment)

**Responsibility:** Verify the caller's identity and produce an
`AuthenticatedContext` — a structured, immutable representation of who the
caller is and what scopes they carry.

**Single entry point:** All transports (streamable HTTP, SSE, WebSocket,
gRPC, Rust edge) must converge to the same `AuthenticatedContext`
construction. Today this is spread across `streamable_http_auth`,
`get_current_user`, `get_current_user_with_permissions`, and the Rust
sidecar's auth handler. The target state is a single `authenticate()`
function that accepts transport-neutral credential material and returns an
`AuthenticatedContext` or a typed denial.

**`AuthenticatedContext` schema (target):**

```
AuthenticatedContext:
  email: string | null           # null = anonymous
  is_authenticated: boolean
  is_admin: boolean              # DB-authoritative, never JWT-only
  token_use: "session" | "api_token" | "anonymous"
  auth_method: string            # "jwt", "proxy", "plugin", "anonymous"
  teams: list[string] | null     # null = admin bypass; [] = public-only
  server_id_scope: string | null # token-level server restriction
  permissions: list[string]      # granted permissions, or ["*"]
  ip_address: string
  jti: string | null             # for revocation tracking
  expires_at: datetime | null
```

**Token types and arrival vectors:**

| Token Type | Arrival Vector | Resolution Strategy |
|------------|---------------|-------------------|
| Session JWT | `Authorization: Bearer` header, `jwt_token`/`access_token` cookie | `resolve_session_teams()` — DB-authoritative for team membership, JWT narrows |
| API JWT | `Authorization: Bearer` header | `normalize_token_teams()` — JWT `teams` claim is sole authority |
| Legacy API token | `Authorization: Bearer` header (SHA256 hash lookup) | `EmailApiToken` table lookup, then `normalize_token_teams()` |
| Proxy-delegated | `X-Forwarded-User` (or configured header) | Trusted only when `is_proxy_auth_trust_active()` — loopback + config |
| Plugin-resolved | Any header/credential | `HTTP_AUTH_RESOLVE_USER` plugin hook — claims resolved against DB |
| Anonymous | No credentials | Allowed only when `mcp_require_auth=False`; yields `teams=[]` | <!-- pragma: allowlist secret -->
| Rust-forwarded context | `x-contextforge-auth-context` header | Base64url-decoded `AuthenticatedContext` from prior Python auth call |

**Cookie restriction (existing invariant, preserved):** Cookie-sourced
tokens are rejected for non-browser API requests. This prevents CSRF-style
token theft from being usable against the API surface.

### Layer 1: Resource Resolution (what is being accessed)

**Responsibility:** Given the request path and method, determine the
target resource identity and load the resource's security-relevant
attributes — without making any authorization decision.

This layer has two parts: an **extraction interface** on the ORM models,
and a **serializable descriptor** that crosses the boundary to Layer 2.

#### `SecurityResource` trait (extraction interface)

A trait (Rust) / Protocol (Python) implemented by each ORM model that
participates in authorization. This formalizes which fields are
security-relevant and eliminates the five-way `if resource_type ==`
dispatch in the current code — every model speaks the same interface.

```rust
// Rust
trait SecurityResource {
    fn resource_type(&self) -> ResourceType;
    fn resource_id(&self) -> &str;
    fn visibility(&self) -> Visibility;  // Public | Team | Private
    fn team_id(&self) -> Option<&str>;
    fn owner_email(&self) -> Option<&str>;
    fn is_enabled(&self) -> bool;
}
```

```python
# Python — structural typing, no base class modification required
class SecurityResource(Protocol):
    resource_type: str
    resource_id: str
    visibility: str          # "public" | "team" | "private"
    team_id: str | None
    owner_email: str | None
    enabled: bool
```

The five ORM models (`Server`, `Tool`, `Resource`, `Prompt`, `Gateway`)
already carry these fields. Implementing the trait is a matter of
exposing what is already there under a uniform interface.

A `GenericRoute` struct implements the same trait for non-resource
endpoints (`/health`, `/metrics`, `/admin/*`) with sensible defaults:
`visibility="public"`, no team, no owner, `enabled=True`. This allows
the policy engine to evaluate route-level permissions through the same
path as resource-level visibility, rather than requiring a separate
skip-list.

#### `ResourceDescriptor` (serializable policy input)

Layer 1 produces a `ResourceDescriptor` from any `SecurityResource`
implementor. This is a concrete, flat, serializable data structure — the
**only** thing Layer 2 sees. It never carries ORM session state, method
behavior, or model relationships.

```
ResourceDescriptor:
  resource_type: "server" | "tool" | "resource" | "prompt" | "gateway" | "route"
  resource_id: string
  visibility: "public" | "team" | "private"
  team_id: string | null
  owner_email: string | null
  oauth_enabled: boolean          # server-specific; false for all others
  oauth_config: dict | null       # server-specific; null for all others
  enabled: boolean
  exists: boolean
```

**Why flat optional fields, not subclasses:** Today there is exactly one
resource type with type-specific security attributes (servers with
`oauth_enabled`/`oauth_config`). Introducing an inheritance hierarchy or
discriminated union for a single case would be premature. The optional
fields make the type-specificity explicit without forcing the policy
engine to downcast. If a second resource type develops its own security
attributes, the flat optionals can be promoted to a discriminated
`TypeAttrs` enum (Rust) / tagged union (Python) — a mechanical change,
not an architectural one.

**Boundary role:** The `ResourceDescriptor` is what crosses the wire
from Python to the Rust edge (via internal HTTP, gRPC, or the auth
context header). The `SecurityResource` trait stays on the Python/ORM
side — Rust never imports it. This preserves the clean separation
between data access (Layer 1) and policy evaluation (Layer 2) that
makes the Rust edge viable.

This replaces the current pattern where `_check_resource_team_ownership()`
performs its own ORM queries with inline session management. The resource
lookup becomes a separate, cacheable step that feeds into policy
evaluation.

### Layer 2: Policy Evaluation (the authorization decision)

**Responsibility:** Given an `AuthenticatedContext` and a
`ResourceDescriptor`, produce an `ALLOW` or `DENY` decision with a
machine-readable reason.

**This is where the current if-then-else sprawl collapses into a single
policy evaluation.** The five identical visibility-check blocks become one
policy that is parameterized by the `ResourceDescriptor`, not by the
resource type. Non-resource endpoints (health, metrics, admin routes)
flow through the same path via `GenericRoute` descriptors with
`resource_type: "route"`.

**Policy inputs:**

| Input | Source |
|-------|--------|
| `AuthenticatedContext` | Layer 0 |
| `ResourceDescriptor` | Layer 1 (includes `GenericRoute` for non-resource endpoints) |
| HTTP method | Request |
| Normalized path | Request |
| Current time (UTC) | System clock |

**Policy rules (replacing current if-then-else chains):**

The following rules express the current security invariants in a
declarative form. They are ordered by evaluation priority; the first
matching rule wins.

1. **Admin bypass:** If `context.is_admin == true` AND
   `context.teams == null`, ALLOW. (Preserves existing admin bypass
   semantics from `normalize_token_teams()`.)
2. **Resource does not exist:** If `resource.exists == false`, DENY
   (`resource_not_found`).
3. **Resource disabled:** If `resource.enabled == false`, DENY
   (`resource_disabled`).
4. **OAuth enforcement (servers only):** If
   `resource.oauth_enabled == true` AND
   `context.is_authenticated == false`, DENY (`oauth_required`). Response
   MUST include `WWW-Authenticate: Bearer resource_metadata="..."` per
   RFC 9728.
5. **Public visibility:** If `resource.visibility == "public"`, ALLOW.
6. **Public-only token guard:** If `context.teams == []` (public-only) AND
   `resource.visibility != "public"`, DENY
   (`public_token_insufficient_scope`).
7. **Team visibility:** If `resource.visibility == "team"`, ALLOW iff
   `resource.team_id` is in `context.teams`.
8. **Private visibility:** If `resource.visibility == "private"`, ALLOW
   iff `resource.owner_email == context.email`.
9. **Unknown visibility:** DENY (`unknown_visibility`) — fail-closed
   default.

**Permission check (orthogonal to visibility):**

After visibility passes, the request is checked against the permission
map (`_PERMISSION_PATTERNS` in current code). This is Layer 2 of the
existing two-layer model (RBAC). The permission map is already
declarative (method + path regex -> required permission) and can be
preserved largely as-is, though it should be extracted from the middleware
into a standalone evaluator.

**Additional token-level restrictions (evaluated in parallel):**

- **Server scope restriction:** If `context.server_id_scope` is set and
  does not match the target server, DENY.
- **IP restriction:** If token carries IP allowlist and client IP is not
  in it, DENY.
- **Time restriction:** If token carries time window and current time is
  outside it, DENY.
- **Usage limits:** If token carries rate limits and they are exceeded,
  DENY.

**Decision output:**

```
AuthorizationDecision:
  allowed: boolean
  reason: string                  # machine-readable denial reason
  response_headers: dict          # e.g., WWW-Authenticate for OAuth
```

### Layer 3: Enforcement (transport-level response)

**Responsibility:** Translate the `AuthorizationDecision` into the
appropriate transport-level response (HTTP 401/403, JSON-RPC error, gRPC
status code, SSE close frame).

This layer is inherently transport-specific. Each transport adapter maps
the decision to its wire format. The key architectural requirement is that
enforcement **only** reads the decision — it never re-evaluates policy.

### Rust gateway alignment

The four-layer model maps cleanly to the gateway-control-bus architecture:

| Layer | Current Python | Target: Rust edge mode |
|-------|---------------|----------------------|
| L0: Authentication | Python `authenticate()` via `/_internal/mcp/authenticate` | Rust calls Python endpoint; caches `AuthenticatedContext` per session with binding fingerprint (existing pattern) |
| L1: Resource Resolution | Python ORM query | Python endpoint (cacheable); or Rust-native query against shared cache/DB in future `full` mode |
| L2: Policy Evaluation | **Can run in Rust** if policy is data-driven | Cedar/OPA/Casbin policy engine embedded in Rust crate; Python-equivalent engine for Python paths |
| L3: Enforcement | Python middleware | Rust owns response construction on edge path |

The critical enabler is that Layer 2 becomes a pure function of
structured inputs (context + descriptor + request metadata) with no ORM
dependency and no transport dependency. This is what makes it portable to
Rust.

For the incremental migration period (ADR-047), the Rust edge continues
to delegate L0 and L1 to Python via internal HTTP, but L2 can begin
running in Rust as soon as the policy engine is integrated. The policy
definition is shared between Python and Rust — either through a common
policy file (Cedar, Rego) or through a shared protobuf/JSON schema that
both runtimes interpret identically.

## Standards and Protocol Requirements

### Currently implemented

| Standard | Coverage | Notes |
|----------|----------|-------|
| RFC 6749 (OAuth 2.0) | Authorization Code, Client Credentials, Password grant | Full flow via `oauth_manager.py` |
| RFC 7519 (JWT) | Token validation, JTI revocation, algorithm agility | HS256/384/512, RS256/384/512, ES256/384/512 |
| RFC 7591 (Dynamic Client Registration) | Discovery + registration | Integrated with `DcrService`, issuer allowlists |
| RFC 7636 (PKCE) | S256 challenge method | Mandatory for authorization code flow |
| RFC 8414 (AS Metadata) | Discovery endpoint construction | Used by DCR to find AS capabilities |
| RFC 8707 (Resource Indicators) | Resource parameter in auth requests | Normalizes gateway URL as resource |
| RFC 9728 (Protected Resource Metadata) | Per-server metadata endpoint | `/.well-known/oauth-protected-resource/servers/{id}/mcp` |

### Required for full MCP OAuth 2.1 compliance

| Standard | Gap | Priority |
|----------|-----|----------|
| OAuth 2.1 (draft) | MCP spec now mandates OAuth 2.1 semantics: PKCE mandatory for all clients, no implicit grant, no password grant for public clients | **High** — MCP spec alignment |
| RFC 9449 (DPoP — Demonstrating Proof-of-Possession) | Not implemented; prevents token replay across clients | **Medium** — referenced in MCP spec as SHOULD |
| RFC 8693 (Token Exchange) | Not implemented; needed for service-to-service delegation without forwarding user tokens | **Medium** — federation scenarios |
| RFC 9396 (Rich Authorization Requests) | Partial (plugin-level via JWT claims extraction) | **Low** — full RAR support would allow fine-grained scope requests |
| RFC 9207 (Authorization Server Issuer Identification) | Not implemented; `iss` in authorization response prevents mix-up attacks | **Medium** — defense-in-depth |

### SSO provider requirements

The current SSO integration (GitHub, Google, IBM Security Verify,
Microsoft Entra ID, Okta, Keycloak, generic OIDC) is an external service
dependency that feeds into Layer 0. The proposed architecture does not
change SSO provider integration — SSO produces session JWTs that flow
through the same `AuthenticatedContext` construction as any other token.

The key architectural point is that SSO providers are identity providers
(Layer 0 concern), while resource authorization is a policy concern
(Layer 2). These layers must remain cleanly separated so that adding a new
SSO provider never requires changing authorization logic, and vice versa.

## Open Source Landscape Assessment

The following assessment is **implementation-agnostic** — it catalogs
candidate projects by capability, not by language binding. See the
**Addendum: Policy Engine Suitability Scoring** at the end of this ADR
for ContextForge-specific weighted scoring.

### Policy Engines

| Project | Model | Language | Key Characteristics |
|---------|-------|----------|-------------------|
| **Cedar** | RBAC + ABAC | Rust (native), Java, WASM | Purpose-built for authorization; formally verified in Lean; deterministic evaluation; static analysis can prove policy properties; deny-by-default; human-readable policies. Backed by AWS (Amazon Verified Permissions). |
| **OPA (Open Policy Agent)** | General-purpose policy | Go (server), Rego language, WASM | Turing-complete policy language (Rego); extremely flexible; large ecosystem; CNCF graduated; OPA V1 language standard (2025); strong CI/CD integration. More expressive but less analyzable than Cedar. |
| **Casbin** | ACL, RBAC, ABAC, ReBAC | Go (reference), Rust (`casbin-rs`), Python, 15+ languages | PERM metamodel (Policy, Effect, Request, Matchers); model switching via config file; Apache Incubating; mature Rust crate with async Tokio support; extensive middleware integrations (Axum, Actix, Rocket). |
| **OpenFGA** | ReBAC (Zanzibar) | Go (server), REST/gRPC API | Relationship-based access control inspired by Google Zanzibar; CNCF Incubating; excels at modeling "user X has relation Y to object Z" hierarchies; Rust SDK on roadmap but not yet available. |
| **Oso** | Polar language, RBAC + ABAC + ReBAC | Rust (core), Python, Node.js, WASM | Embedded policy engine; Rust core with language bindings; Polar language designed for authorization; legacy open-source library deprecated, next-gen release pending. |

### OAuth / OIDC Servers (Authorization Server role)

| Project | Capabilities | Language | Key Characteristics |
|---------|-------------|----------|-------------------|
| **Ory Hydra** | OAuth 2.0/2.1, OpenID Connect | Go | OpenID Certified; headless (no user management — BYO identity); low resource consumption; designed for high-throughput token issuance; used by OpenAI. Pairs with Ory Kratos (identity), Ory Keto (permissions), Ory Oathkeeper (gateway). |
| **Keycloak** | OAuth 2.0, OIDC, SAML 2.0, SCIM | Java | Full-featured IAM; built-in admin UI; user federation (LDAP, AD); extensive protocol support; CNCF project; heavier footprint; broad enterprise adoption. |
| **Authelia** | SSO, 2FA, OIDC | Go | Lightweight SSO portal; designed as reverse-proxy companion; TOTP/WebAuthn/Duo 2FA; less suited for programmatic token issuance at scale. |
| **Authentik** | OAuth 2.0, OIDC, SAML, SCIM, LDAP | Python (Django) | Full IAM with flows/stages model; admin UI; LDAP outpost; growing community; Python-native. |
| **Dex** | OIDC federation | Go | Connector-based OIDC federation; lightweight; designed as identity broker (upstream IdP -> downstream OIDC); used by Kubernetes. |

### Gateway / Proxy Security Middleware

| Project | Capabilities | Language | Key Characteristics |
|---------|-------------|----------|-------------------|
| **Ory Oathkeeper** | Identity/access proxy | Go | Zero-trust proxy that authenticates, authorizes, and mutates requests; integrates with Ory Hydra/Keto; rule-based access control; designed for API gateway pattern. |
| **OpenZiti** | Zero-trust networking | Go, C | Network-level zero-trust overlay; strong identity built into network fabric; overkill for application-layer auth but relevant for defense-in-depth. |
| **Pomerium** | Identity-aware proxy | Go | Context-aware access proxy; integrates with IdPs; policy-based routing; designed for internal services. |

### Token Management / Validation

| Project | Capabilities | Language | Key Characteristics |
|---------|-------------|----------|-------------------|
| **jsonwebtoken** (crate) | JWT validation | Rust | De facto Rust JWT library; supports all standard algorithms; fast validation. Already likely in use or usable by the Rust runtime. |
| **PyJWT / python-jose** | JWT validation | Python | Current Python JWT libraries. PyJWT is the more actively maintained option. |
| **OPA/Cedar/Casbin** | Token claim evaluation | Various | Policy engines can evaluate JWT claims as part of authorization — the token validation itself is typically handled by a dedicated JWT library, with claims passed to the policy engine as input. |

## Consequences

### Positive

- **Single policy definition** replaces five copy-paste visibility-check
  blocks. Behavioral changes to the visibility model are made once.
- **Testable in isolation.** Policy evaluation becomes a pure function of
  structured inputs — no ORM, no middleware, no transport. Unit testing
  the full authorization matrix becomes straightforward.
- **Audit-friendly.** A security reviewer reads one policy definition, not
  350 lines of near-identical branches across five resource types.
- **Rust-portable.** The policy evaluation layer can run in the Rust edge
  without reimplementing Python ORM logic. This directly supports the
  gateway-control-bus architecture (ADR-043, ADR-045).
- **Standards-aligned.** Explicit mapping of OAuth 2.1, RFC 9728, and MCP
  spec requirements to architectural layers clarifies compliance gaps.
- **Open source leverage.** Cedar, Casbin, and OPA each offer mature
  policy engines that can replace hand-rolled if-then-else chains, with
  varying tradeoffs documented for the suitability scoring phase.

### Negative

- **Migration effort.** Refactoring the auth middleware from procedural to
  policy-based is non-trivial. The migration must be incremental and
  preserve all existing deny-path regression tests.
- **New dependency.** Adopting an external policy engine introduces a
  dependency that must be evaluated for security, maintenance, and
  performance.
- **Learning curve.** Contributors must understand the policy language
  (Cedar, Rego, or Casbin model) in addition to Python/Rust.
- **Performance consideration.** An external policy engine adds evaluation
  overhead. For Cedar and Casbin (embeddable), this is typically
  sub-millisecond. For OPA (sidecar/server model), network latency must
  be considered.

### Neutral

- The existing security invariants (fail-closed defaults, DB-authoritative
  admin, two-layer model) are preserved — they are re-expressed in a
  structured form, not changed.
- This ADR **implements** ADR-045 ("auth remains in core"). ADR-045
  established the principle that auth never moves into modules; this ADR
  provides the concrete architecture for how the core-owned auth boundary
  is structured and how modules consume it.
- SSO provider integration is unaffected. SSO operates at Layer 0
  (identity), which is orthogonal to the Layer 2 (policy) changes
  proposed here.

## Migration Path

### Phase 1: Extract `ResourceDescriptor` and unify visibility checks

Replace the five per-resource-type blocks in
`_check_resource_team_ownership()` with a single generic
`evaluate_resource_visibility(context, descriptor)` function. This is a
pure refactoring — no new dependencies, no policy engine — that
immediately eliminates the code duplication and makes the policy surface
testable.

### Phase 2: Extract `AuthenticatedContext` as a first-class type

Unify the scattered auth entry points (`streamable_http_auth`,
`get_current_user`, Rust forwarded context) to all produce the same
`AuthenticatedContext` structure. This formalizes the contract between
Layer 0 and Layer 2.

### Phase 3: Evaluate and adopt a policy engine

Per the suitability scoring addendum below, Cedar is the recommended
engine (with Casbin as fallback). Rewrite `evaluate_resource_visibility()`
to delegate to the Cedar engine. Integrate the same `.cedar` policy
files into the Rust edge crate via the native `cedar-policy` crate.

### Phase 4: Expose policy evaluation via SPI

Define the gRPC/protobuf contract (per ADR-044) for modules to request
authorization decisions. This completes the ADR-045 story: modules
consume auth through a core-owned SPI backed by a formal policy engine.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Keep the current if-then-else structure** | Drift risk increases with every new resource type or visibility tier. The Rust edge cannot consume it without reimplementing Python ORM logic. |
| **Simple refactoring without a policy engine** | Phase 1-2 are worth doing regardless, but without a policy engine, the authorization logic remains procedural code that must be manually kept in sync between Python and Rust. |
| **Move all auth into Rust immediately** | Contradicts ADR-045 and ADR-047 (incremental migration). Auth remains in core; what changes is the *form* of the policy (data-driven vs procedural). |
| **Adopt a full IAM platform (Keycloak, Ory stack)** | ContextForge already has a working identity layer. The problem is authorization policy expression, not identity management. A full IAM replacement would be a much larger scope change with limited benefit for the specific problem identified. |

## References

- `mcpgateway/middleware/token_scoping.py:817-1177` — Current five-way visibility check
- `mcpgateway/auth.py:474-524` — `normalize_token_teams()`
- `mcpgateway/auth.py:418-471` — `resolve_session_teams()`
- `mcpgateway/transports/streamablehttp_transport.py:3248-3450` — `_StreamableHttpAuthHandler`
- `tools_rust/mcp_runtime/src/lib.rs:2400-2587` — Rust auth binding and session reuse
- [ADR-043](043-rust-mcp-runtime-sidecar-mode-model.md) — Rust sidecar mode model
- [ADR-044](044-module-communication-protocol.md) — Module communication protocol
- [ADR-045](045-auth-remains-in-core.md) — Auth remains in core
- [ADR-047](047-incremental-migration-over-rewrite.md) — Incremental migration
- [MCP Authorization Specification (draft)](https://modelcontextprotocol.io/specification/draft/basic/authorization) — OAuth 2.1 requirements for MCP
- [Cedar Policy Language](https://github.com/cedar-policy/cedar) — Formally verified authorization engine (Rust)
- [Open Policy Agent](https://www.openpolicyagent.org/) — General-purpose policy engine (CNCF Graduated)
- [Casbin](https://casbin.apache.org/) — Multi-model authorization library (Apache Incubating)
- [OpenFGA](https://openfga.dev/) — Zanzibar-inspired ReBAC engine (CNCF Incubating)
- [Ory Hydra](https://github.com/ory/hydra) — OpenID Certified OAuth 2.1 server

---

## Addendum: Policy Engine Suitability Scoring

- *Date:* 2026-04-12

### Evaluation Criteria

Scoring uses a 1–5 scale where 5 is the strongest fit for ContextForge's
constraints. Criteria are weighted to reflect the project's priorities:
dual-language embeddability matters more than ecosystem size because the
gateway-control-bus architecture requires the policy engine to run in both
the Python control plane and the Rust edge.

| # | Criterion | Weight | What it measures |
|---|-----------|--------|-----------------|
| C1 | **Rust embeddability** | 5 | Can the engine run in-process in a Rust binary? Native crate maturity, async compatibility, thread safety. |
| C2 | **Python embeddability** | 4 | Can the engine run in-process in Python? Published PyPI package, API maturity, no sidecar required. |
| C3 | **Policy portability** | 5 | Can the identical policy definition be loaded and evaluated by both the Rust and Python runtimes? Divergent policy formats between languages is a disqualifier for the same reason the current copy-paste code is. |
| C4 | **RBAC + ABAC expressiveness** | 4 | Can the engine express the ContextForge visibility model (team membership, owner match, attribute-based conditions) naturally? ReBAC/relationship-graph capability is not required. |
| C5 | **Formal verification / auditability** | 3 | Can policy properties be statically analyzed or formally proven? Static analysis, termination guarantees, absence of side effects. |
| C6 | **Deny-by-default semantics** | 3 | Does the engine default to deny when no policy matches? Is the deny-default guaranteed by design rather than convention? |
| C7 | **Evaluation latency** | 3 | Sub-millisecond evaluation for typical policy sets (< 50 rules, < 10 entity types). This is the hot path for every request. |
| C8 | **Project health** | 3 | Active maintenance, release cadence, backing organization, bus-factor. |
| C9 | **License compatibility** | 2 | Apache-2.0 or equivalent permissive license. |

### Candidates Disqualified Before Scoring

| Project | Reason |
|---------|--------|
| **OpenFGA** | Server-only architecture (Go binary); cannot embed in-process in Rust or Python. No official Rust SDK. ReBAC-focused, mismatched with ContextForge's flat-team RBAC+ABAC model. |
| **Oso** | Open-source library deprecated (last release 2024-01-13, explicit deprecation notice in README). No active maintenance. Company pivoted to cloud service. |

### Scoring Matrix

| Criterion | Wt | Cedar | OPA/Regorus | Casbin |
|-----------|----|-------|-------------|--------|
| **C1: Rust embed** | 5 | **5** — `cedar-policy` 4.9.1, native Rust, first-party crate, WASM feature flag | **4** — `regorus` 0.9.1, Microsoft-backed pure-Rust Rego evaluator, 780K downloads, `no_std` capable | **4** — `casbin` 2.20.0, Tokio async default, 1.17M downloads. Caveat: `Enforcer` is not `Send+Sync` — requires `Arc<RwLock<>>` wrapper |
| **C2: Python embed** | 4 | **3** — `cedarpy` 4.8.0 on PyPI, third-party (k9securityio), PyO3 wrapper. Lags one minor version behind Rust crate. Functional but not first-party supported | **2** — No published PyPI package for regorus. Python bindings exist in-repo (Maturin/PyO3) but require building from source. Alternative: OPA sidecar over HTTP, which adds network latency | **5** — `casbin` (pycasbin) 1.43.0 on PyPI, actively maintained, first-party, pure Python with adapter ecosystem |
| **C3: Policy portability** | 5 | **5** — Cedar policy files (`.cedar`) and schema files (`.cedarschema`) are the same format consumed by both the Rust engine and the Python (via PyO3) engine. One policy definition, one schema, two runtimes | **3** — Rego `.rego` files are portable in principle, but `regorus` implements a subset of Rego builtins (documented per-function). Policies must stay within the supported subset to work in both Go OPA and Rust regorus. Python path unclear (sidecar uses full OPA; embedded uses regorus subset) | **5** — Identical `.conf` model and `.csv`/adapter policy files load in both Rust (`casbin-rs`) and Python (`pycasbin`). This is a first-class design goal of the project |
| **C4: RBAC+ABAC** | 4 | **5** — Purpose-built for ABAC with typed entity attributes. The ContextForge visibility policy is a one-liner: `permit(principal, action, resource) when { resource.visibility == "team" && context.teams.contains(resource.team_id) };` Supports set operations, record attributes, entity hierarchy | **5** — Rego is Turing-complete; any RBAC/ABAC policy is expressible. More power than needed, but no expressiveness ceiling | **3** — RBAC is first-class (PERM metamodel). ABAC is supported via string-based matcher expressions (e.g., `r.sub.teams.contains(r.obj.team_id)`), but matchers are evaluated as string expressions, not typed policy language. Less auditable than Cedar/Rego for complex attribute conditions |
| **C5: Formal verification** | 3 | **5** — Formalized in Lean proof assistant. Provable decidability, termination, and policy-property verification. Static analysis can detect conflicts and unreachable rules. Cedar Analysis is a unique differentiator | **2** — Rego has testing frameworks (`opa test`) and coverage analysis, but no formal verification. Evaluation is deterministic for pure policies, but Rego permits side-effecting builtins (`http.send`) that must be restricted | **1** — No formal verification. Model is config-file-driven; correctness depends on convention and testing. No static analysis beyond syntax checking |
| **C6: Deny-by-default** | 3 | **5** — Default-deny is a language invariant. Access requires explicit `permit`; any `forbid` overrides. Cannot accidentally create an open policy | **4** — Default-deny by convention (empty result = deny), but this is enforced by the calling code, not the language. A policy that evaluates to `true` allows; absence of a matching rule returns undefined (falsy). Slightly less ironclad than Cedar | **4** — Default-deny: if no policy matches, `enforce()` returns `false`. This is a framework guarantee, not a language-level proof |
| **C7: Latency** | 3 | **5** — Benchmarked at sub-100μs for typical policy sets. No interpretation overhead (compiled Rust). Formally guaranteed termination (no runaway evaluation) | **4** — Regorus is compiled Rust with good performance. Rego evaluation is more complex (Datalog unification) but still sub-millisecond for typical policies. No formal termination guarantee for arbitrary Rego | **4** — Compiled Rust enforcer. String-based matcher evaluation adds overhead vs. typed evaluation, but still sub-millisecond for typical RBAC policies |
| **C8: Project health** | 3 | **4** — AWS-backed, 1.4K GitHub stars, active releases (4.9.1 in Feb 2026). Smaller community than OPA. Third-party Python binding is a bus-factor risk | **5** — OPA is CNCF Graduated (highest maturity level), massive ecosystem. Regorus is Microsoft-backed (294 stars, active releases). Combined backing is strong | **4** — Apache Incubating, 1.17M Rust crate downloads, active releases in both Rust and Python. Strong multi-language community. Not backed by a single large vendor |
| **C9: License** | 2 | **5** — Apache-2.0 | **5** — Apache-2.0 (OPA), MIT + Apache-2.0 + BSD-3 (regorus) | **5** — Apache-2.0 |

### Weighted Scores

| Criterion | Wt | Cedar | OPA/Regorus | Casbin |
|-----------|----|-------|-------------|--------|
| C1 | 5 | 25 | 20 | 20 |
| C2 | 4 | 12 | 8 | 20 |
| C3 | 5 | 25 | 15 | 25 |
| C4 | 4 | 20 | 20 | 12 |
| C5 | 3 | 15 | 6 | 3 |
| C6 | 3 | 15 | 12 | 12 |
| C7 | 3 | 15 | 12 | 12 |
| C8 | 3 | 12 | 15 | 12 |
| C9 | 2 | 10 | 10 | 10 |
| **Total** | **32** | **149** | **118** | **126** |
| **Normalized (%)** | | **93%** | **74%** | **79%** |

### Analysis

**Cedar scores highest (93%)** with particular strength in the criteria
that matter most for ContextForge: Rust embeddability, policy portability
across runtimes, ABAC expressiveness, and formal verification. Its main
weakness is the third-party Python binding (`cedarpy`), which is
functional and PyO3-based but not maintained by the Cedar team. This is a
manageable risk: ContextForge already maintains PyO3 bridges for its own
plugin crates (ADR-048), and the Cedar Rust crate's stability means the
Python wrapper is thin.

**Casbin scores second (79%)** with the strongest cross-language story —
both Rust and Python packages are first-party, actively maintained, and
share identical policy file formats. Its weakness is ABAC expressiveness
and the complete absence of formal verification. For ContextForge's
current visibility model (which is straightforward RBAC + simple attribute
checks), Casbin is sufficient. For future policy complexity (e.g., rich
authorization requests per RFC 9396, hierarchical team scopes), the
string-based matcher model becomes a liability.

**OPA/Regorus scores third (74%)** despite having the strongest
organizational backing (CNCF Graduated + Microsoft). The critical gap is
Python embeddability: there is no published PyPI package for regorus, and
the alternative (OPA HTTP sidecar) adds network latency and operational
complexity to the Python control plane. This could be mitigated by
building and publishing regorus Python wheels internally, but that is
additional maintenance burden.

### Recommendation

**Cedar is the recommended policy engine**, contingent on validation of
the `cedarpy` Python binding against ContextForge's authorization test
suite during Phase 3 of the migration path.

The recommendation is based on:

1. **Architectural fit.** Cedar's Rust-native engine runs directly in the
   Rust edge sidecar (Layer 2 in the proposed architecture). The same
   `.cedar` policy files load in Python via `cedarpy`. This is the only
   candidate where the identical policy source is guaranteed to produce
   identical decisions in both runtimes, backed by formal proofs.

2. **Security properties.** Cedar's formal verification in Lean provides
   guarantees that no other candidate offers: decidability, termination,
   and static policy analysis. For a security-critical authorization
   layer in a gateway that federates access to external tools and agents,
   these properties have concrete operational value — they allow the team
   to prove that a policy change cannot accidentally open access.

3. **Gateway-control-bus alignment.** As the Rust edge assumes more of
   the hot MCP path (ADR-043 `edge` and `full` modes), Cedar evaluation
   runs natively without FFI, sidecar, or network overhead. The Python
   control plane uses the same policies through a thin PyO3 wrapper. This
   cleanly implements ADR-045's principle that "modules consume auth
   through a core-owned auth and policy SPI."

4. **Incremental adoptability.** Phase 1–2 of the migration path
   (extract `ResourceDescriptor`, unify `AuthenticatedContext`) can
   proceed without Cedar. Cedar is introduced in Phase 3 as a drop-in
   replacement for the `evaluate_resource_visibility()` function, with
   the full deny-path regression test suite validating behavioral
   equivalence.

**Fallback:** If `cedarpy` proves inadequate (binding instability, version
lag exceeding one major version, or unmaintained for > 6 months), Casbin
is the fallback. Its cross-language maturity is proven, and the ABAC
limitations are manageable for the current visibility model. The Phase 1–2
refactoring makes the policy engine substitutable by design.

### Version Inventory (as of 2026-04-12)

| Component | Package | Version | Source |
|-----------|---------|---------|--------|
| Cedar (Rust) | `cedar-policy` | 4.9.1 | crates.io |
| Cedar (Python) | `cedarpy` | 4.8.0 | PyPI |
| Regorus (Rust) | `regorus` | 0.9.1 | crates.io |
| OPA (Go) | `opa` | 1.15.2 | GitHub |
| Casbin (Rust) | `casbin` | 2.20.0 | crates.io |
| Casbin (Python) | `casbin` | 1.43.0 | PyPI |
