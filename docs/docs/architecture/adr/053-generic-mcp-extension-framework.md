# ADR-053: Generic MCP Extension Framework

- *Status:* Proposed
- *Date:* 2026-05-29
- *Deciders:* Platform Team
- *Related:*
  - [Issue #2527: Generic MCP Extension Framework with MCP Apps Implementation](https://github.com/IBM/mcp-context-forge/issues/2527)
  - [Issue #4957: ADR for generic MCP extension framework](https://github.com/IBM/mcp-context-forge/issues/4957)
  - [Issue #4974: Generic extension foundation](https://github.com/IBM/mcp-context-forge/issues/4974)
  - [Issue #4975: Auth-scoped aggregation and generic routing](https://github.com/IBM/mcp-context-forge/issues/4975)
  - [MCP Extensions overview](https://modelcontextprotocol.io/docs/extensions/overview)
  - [MCP Apps extension](https://modelcontextprotocol.io/docs/extensions/apps)

## Context

ContextForge federates MCP servers and exposes governed tools, resources, prompts, transports,
RBAC, observability, and admin controls. The current MCP request path is intentionally explicit:
core protocol methods such as `tools/list`, `tools/call`, `resources/read`, `prompts/get`,
`completion/complete`, `elicitation/create`, and logging/sampling methods are handled by known
branches in the gateway. Unknown methods eventually fall through to legacy direct-tool invocation
or `-32601 Method not found`.

That explicit model is safe for the core protocol, but it does not scale to MCP extensions. MCP now
has an extension mechanism where clients and servers advertise optional protocol features through
`capabilities.extensions`. MCP Apps is the first near-term extension ContextForge needs to support,
using the official extension identifier `io.modelcontextprotocol/ui`, but it must not become a
one-off MCP Apps implementation hidden inside the dispatcher.

The bigger requirement is generic: a future simple extension, for example a Tasks extension with
methods like `tasks/list` and `tasks/create`, should be onboarded through metadata and policy rather
than by adding new ContextForge core code branches. Code changes should be reserved for extensions
that genuinely need gateway-side state, security mediation, protocol adaptation, or content
transformation.

This ADR decides the architecture for a generic MCP extension framework, with MCP Apps used as the
first complex validation case.

## Decision

Build a generic MCP extension framework with five primary responsibilities:

1. **Represent extensions using `capabilities.extensions`.**
   ContextForge will add `extensions` to MCP client and server capability models and use it as the
   canonical path for official MCP extensions. Existing `capabilities.experimental` payloads may be
   preserved for compatibility and incubation, but official extensions should not be modeled as
   `experimental` features.

2. **Persist a generic extension registry.**
   ContextForge will store extension definitions and per-gateway extension capability records using
   a schema that is independent of any specific extension. Registry metadata includes extension
   identifier, source, status, risk level, explicit method ownership patterns, required permissions,
   routing mode, source gateways, and optional handler class.

3. **Discover upstream extensions during gateway sync.**
   Gateway initialization and refresh will inspect upstream `capabilities.extensions`, persist
   discovered extension capability payloads per gateway, and associate them with generic extension
   definitions. Legacy `capabilities.experimental` entries can be recorded as compatibility metadata
   but must not automatically become official extension support.

4. **Aggregate capabilities with caller scope.**
   Initialize responses will advertise only extensions that the caller, token scope, team scope,
   target virtual server, enabled-state policy, RBAC permissions, and client capabilities allow.
   Extension aggregation must not leak private or team-only upstream capabilities to unauthorized
   clients.

5. **Route extension methods through registry-owned method patterns.**
   The request dispatcher will route in this order:

   1. Core MCP methods.
   2. Registered extension handler or proxy route.
   3. Existing legacy direct-tool fallback.
   4. `-32601 Method not found`.

   The dispatcher must not gain a new `elif method == ...` branch for every future simple extension.
   Extension method ownership is explicit registry metadata, not inferred from an extension name.

## Extension Capability Model

Official MCP extensions are advertised under `capabilities.extensions` using stable extension
identifiers:

```json
{
  "capabilities": {
    "extensions": {
      "com.example/tasks": {
        "version": "1.0.0"
      }
    }
  }
}
```

MCP Apps uses the official UI extension identifier:

```json
{
  "capabilities": {
    "extensions": {
      "io.modelcontextprotocol/ui": {
        "mimeTypes": ["text/html;profile=mcp-app"]
      }
    }
  }
}
```

ContextForge may still ingest legacy or incubating payloads such as:

```json
{
  "capabilities": {
    "experimental": {
      "apps": {}
    }
  }
}
```

Those entries are compatibility metadata. They do not automatically mean official MCP Apps support
unless an operator or compatibility policy maps them to a real extension definition.

## Registry Model

The extension registry is the control-plane source of truth.

An extension definition includes:

- `identifier`: stable extension identifier, for example `com.example/tasks`.
- `display_name`: human-readable name.
- `source`: `built-in`, `discovered`, `admin-configured`, or `legacy-experimental`.
- `status`: enabled, disabled, deprecated, or blocked.
- `risk_level`: operator-visible risk classification.
- `method_patterns`: explicit method names or prefixes owned by the extension.
- `required_permissions`: RBAC permissions required to see or invoke the extension.
- `auto_proxy`: whether matching methods can be proxied generically.
- `routing_policy`: upstream selection behavior for multi-gateway providers.
- `handler_class`: optional approved handler for complex extensions.

A gateway-extension record includes:

- gateway id.
- extension identifier.
- upstream capability payload.
- enabled state.
- discovery source.
- last seen timestamp.

This shape is intentionally extension-agnostic. Adding a simple Tasks extension should not require
new tables or new dispatcher branches.

## Routing Model

Extension routing is default-deny.

For every non-core method, the gateway asks the registry whether an enabled extension explicitly
owns the method for the current caller and server scope. If no enabled extension owns it, the request
continues to the legacy direct-tool fallback and then to method-not-found behavior.

If an extension owns the method:

1. The gateway enforces authentication, token scoping, server scoping, and RBAC.
2. The gateway checks the extension's enabled state and risk policy.
3. If `handler_class` is configured, the request is passed to the approved handler.
4. Else if `auto_proxy=true`, the request is proxied to an authorized upstream provider.
5. Else the request is denied as unsupported for that extension.

Method ownership must be explicit. The gateway must not infer that `com.example/tasks` owns
`tasks/*` unless that method pattern is configured or discovered through an approved extension
definition.

## No-Code Simple Extension Onboarding

Simple extensions should be onboarded declaratively.

For example, an operator should be able to configure:

```yaml
identifier: com.example/tasks
method_patterns:
  - tasks/list
  - tasks/create
required_permissions:
  - tools.execute
auto_proxy: true
routing_policy:
  strategy: first_authorized_gateway
```

With that metadata, ContextForge can:

- discover upstream `com.example/tasks` capability payloads.
- advertise the extension to authorized clients during initialize.
- route `tasks/list` and `tasks/create` to an authorized upstream.
- audit and trace the extension call.
- deny hidden, disabled, unauthorized, or unowned methods.

No core dispatcher, database schema, or Admin UI structural change should be required.

## Custom Handler Model

Custom handlers are an escape hatch for complex extensions, not the default onboarding path.

Handlers are appropriate when an extension needs gateway-side behavior such as:

- stateful sessions.
- security mediation beyond normal RBAC.
- content transformation.
- protocol adaptation.
- background cleanup.
- custom capability contribution.

Handlers must be loaded only from approved locations, such as built-in modules or explicitly
allowlisted plugin packages. A database row must not be able to load arbitrary Python code. Invalid
or unapproved handlers fail closed and produce admin-visible diagnostics.

The handler interface should provide:

- `on_initialize`.
- `on_method_call`.
- `on_capability_query`.
- `on_cleanup`.

Handlers receive caller identity, token teams, server scope, session id, client capabilities, and
only the services they are allowed to use.

## MCP Apps as the First Complex Extension

MCP Apps validates the complex-handler path but must not define the framework's boundaries.

For MCP Apps:

- the canonical extension identifier is `io.modelcontextprotocol/ui`.
- UI resources use `ui://` URIs.
- UI content is read through MCP resource flows.
- tools associate UIs through `_meta.ui.resourceUri`.
- app-only tools must not leak into model-facing `tools/list`.
- AppBridge calls must be bound to the same server, app session, caller, and RBAC context.
- CSP, sandbox, allowed origin, and permissions policy are security controls, not UI details.

These requirements are specific to MCP Apps. They should be implemented as a complex extension on
top of the generic registry, aggregation, routing, and handler framework.

## Security Invariants

The framework must preserve ContextForge's two-layer security model:

- Layer 1: token scoping controls what the caller can see.
- Layer 2: RBAC controls what the caller can do.

Concrete requirements:

- Capability aggregation is visibility-scoped. Never advertise hidden extension capabilities.
- Extension method routing is default-deny.
- Public-only tokens see only public extension capabilities.
- Team-scoped tokens see public and authorized team extension capabilities.
- Admin bypass follows existing token/session rules.
- Server-scoped tokens cannot route methods outside their server scope.
- Extension handlers must not trust client-provided owner, team, or session fields.
- Unknown methods must not be blindly proxied.
- Extension method conflicts must fail closed or require explicit operator resolution.
- Denied extension calls must be audited.
- High-risk extensions should be disabled by default or require explicit operator enablement.

Implementation must reuse the existing token-team interpretation points instead of reimplementing
token scoping logic.

## Admin and Operations

ContextForge will expose extension governance through both API and Admin UI:

- list registered extensions.
- inspect source gateways and capability payloads.
- enable or disable extensions globally or per gateway.
- configure method patterns, permissions, routing policy, and risk metadata for admin-configured
  extensions.
- show whether an extension is built-in, discovered, admin-configured, or legacy-experimental.
- surface handler load failures and blocked-risk decisions.

Operational telemetry includes:

- discovery events.
- initialize aggregation decisions.
- extension method route decisions.
- proxy target and outcome.
- handler outcome.
- denial reason.
- latency and error metrics.

Logs, metrics, traces, and audit events must not expose secrets from capability payloads, request
headers, or upstream authentication configuration.

## Consequences

### Positive

- Future simple extensions can be onboarded through metadata rather than core code changes.
- MCP Apps becomes the first complex extension, not a one-off gateway feature.
- Capability exposure becomes explicitly auth-scoped, reducing visibility leaks.
- Operators gain governance over discovered and configured extensions.
- Method routing remains default-deny and auditable.
- The framework creates a natural boundary between simple proxyable extensions and complex handler
  extensions.

### Negative

- The MCP request path gains a new registry lookup for non-core methods.
- Extension records add new control-plane state that must be migrated, tested, exported, and
  imported over time.
- Explicit method ownership requires operators or extension definitions to provide correct method
  patterns.
- Custom handler loading introduces a new safety surface that must remain allowlisted and fail
  closed.

### Neutral

- Existing core MCP method handling remains explicit.
- Existing `capabilities.experimental` behavior is preserved as compatibility metadata.
- The legacy direct-tool fallback remains after extension routing to preserve backward
  compatibility.
- MCP Apps-specific UI, CSP, and AppBridge behavior is intentionally outside the simple extension
  path.

## Alternatives Considered

### Implement MCP Apps only

Rejected. It would solve the immediate UI need but repeat the same work for Tasks or any future
extension: capability parsing, routing, RBAC, admin governance, observability, and tests.

### Proxy all unknown methods blindly

Rejected. Blind proxying can leak capability existence, bypass policy, route to the wrong upstream,
or execute unsafe extension behavior without explicit ownership.

### Continue using only `capabilities.experimental`

Rejected for official extensions. MCP extensions now have a formal `capabilities.extensions`
negotiation path. `experimental` remains useful for compatibility and incubation only.

### Require custom handler code for every extension

Rejected. That would turn every future extension into a code deployment and defeat the purpose of a
generic extension framework. Handlers are reserved for complex extensions.

## Migration and Rollout

Delivery is split into six demoable stories:

1. ADR approval ([#4957](https://github.com/IBM/mcp-context-forge/issues/4957)).
2. Generic extension foundation ([#4974](https://github.com/IBM/mcp-context-forge/issues/4974)).
3. Auth-scoped aggregation and generic routing ([#4975](https://github.com/IBM/mcp-context-forge/issues/4975)).
4. Extension governance and operations ([#4976](https://github.com/IBM/mcp-context-forge/issues/4976)).
5. Custom extension handler framework ([#4977](https://github.com/IBM/mcp-context-forge/issues/4977)).
6. MCP Apps complex extension implementation ([#4978](https://github.com/IBM/mcp-context-forge/issues/4978)).

Rollout rules:

- Ship the framework behind explicit extension enablement.
- Keep high-risk discovered extensions disabled until operator approval.
- Preserve existing core MCP behavior and legacy tool fallback.
- Add deny-path regression tests before enabling extension routing by default.
- Validate the no-code path with a Tasks-style fixture before MCP Apps-specific work is considered
  complete.

## Approval Checklist

- [ ] Maintainers agree that `capabilities.extensions` is the canonical path for official
      extensions.
- [ ] Maintainers agree that `capabilities.experimental` remains compatibility/incubation metadata.
- [ ] Maintainers agree that simple extensions must be onboardable without core dispatcher changes.
- [ ] Security review accepts the default-deny routing and auth-scoped aggregation model.
- [ ] Platform review accepts the registry, admin, and observability model.
- [ ] MCP Apps implementers agree to build on the generic framework rather than bypassing it.

## References

- [MCP Extensions overview](https://modelcontextprotocol.io/docs/extensions/overview)
- [MCP Apps extension](https://modelcontextprotocol.io/docs/extensions/apps)
- [MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)
- [Issue #2527: Generic MCP Extension Framework with MCP Apps Implementation](https://github.com/IBM/mcp-context-forge/issues/2527)
- [Issue #4957: ADR for generic MCP extension framework](https://github.com/IBM/mcp-context-forge/issues/4957)
- Prior related ADRs:
  - [ADR-016: Plugin Framework & AI Middleware](016-plugin-framework-ai-middleware.md)
  - [ADR-045: Authentication and Authorization Remain in Core](045-auth-remains-in-core.md)
  - [ADR-049: Multi-Protocol Virtual Servers](049-multi-protocol-virtual-servers.md)
