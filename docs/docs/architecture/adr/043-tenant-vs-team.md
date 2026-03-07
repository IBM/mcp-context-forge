# ADR-0043: Tenant vs Team Separation

## Context

A2A v1.0 adds a `tenant` field to all request messages, providing a routing label that downstream agents can use to partition their behavior (e.g., selecting a knowledge base, applying tenant-specific policies, or routing to tenant-specific backends).

ContextForge already has `team_id` as a gateway-internal authorization scope used for RBAC and resource visibility. The `team_id` determines which resources a caller can see and what actions they can perform (see the two-layer security model in the project guidelines).

These two concepts could be handled in two ways:

- **Conflation**: Map `team_id` directly to `tenant`, treating them as the same value. Simpler but couples gateway authorization boundaries to downstream agent routing.
- **Separation**: Keep them as independent, orthogonal concepts. More flexible but introduces two similar-sounding terms that users must distinguish.

## Decision

Keep `team_id` and `tenant` as **orthogonal concepts** that are configured independently and never cross-referenced.

- **`team_id`** is gateway-internal authorization. It controls who can access a resource within ContextForge. It is never sent in A2A protocol messages.
- **`tenant`** is a protocol-level routing label. It is forwarded to downstream agents in A2A request messages. It is never used for gateway access control decisions.

### Tenant Resolution

Tenant value is resolved using the following precedence (highest to lowest):

1. **Caller-supplied**: The tenant value from the inbound A2A request, accepted only if `allow_caller_tenant_override=true` on the server or agent configuration.
2. **Per-agent override**: A tenant value configured on the specific agent registration.
3. **Server default**: A tenant value configured on the virtual server (`a2a_tenant` field from ADR-0042).
4. **Empty**: No tenant is set in the outbound request.

### Security Controls

- Caller tenant override is **opt-in** per server/agent, disabled by default.
- An optional **tenant allowlist** can restrict which tenant values callers may supply, preventing arbitrary tenant injection.
- `team_id` is never sent in A2A protocol messages to downstream agents.
- `tenant` is never consulted during gateway RBAC checks or resource visibility filtering.

### Operational Model

- Multiple servers in different teams can share the same downstream tenant value (e.g., two teams both route to a shared `production` tenant on a downstream agent).
- A single team can have servers targeting different tenants (e.g., `staging` and `production` tenants for the same downstream service).
- The admin UI presents `team_id` and `tenant` in separate sections with clear labels and descriptions to avoid confusion.

## Consequences

### Positive
- Simpler mental model: each concept has exactly one purpose and one scope of effect.
- Avoids coupling gateway RBAC boundaries to downstream agent tenant partitioning, which may follow entirely different organizational boundaries.
- Operators can restructure teams without affecting downstream tenant routing, and vice versa.
- Clean admin UI separation reduces configuration errors.

### Negative
- Two similar-sounding concepts (`team` and `tenant`) that users must learn to distinguish (mitigated by clear documentation, UI labels, and field-level help text).
- Slightly more configuration surface than a conflated model (mitigated by sensible defaults: tenant is empty unless explicitly set).

### Risks / Mitigations
- Users may confuse `team_id` and `tenant` -- mitigate with explicit documentation, distinct naming in API/UI, and validation warnings when tenant is set without understanding the distinction.
- Caller tenant override could be a security concern if misconfigured -- mitigate by defaulting to disabled and supporting an allowlist for permitted tenant values.
- Tenant value could leak internal routing information to downstream agents -- mitigate by documenting that tenant values should be opaque labels, not sensitive identifiers.

## Alternatives Considered

- **Conflate team_id and tenant**: Rejected. Couples gateway authorization to downstream routing. Breaks when organizational team boundaries do not match downstream tenant boundaries (common in practice). Would require gateway team restructuring to change downstream routing, creating unnecessary operational coupling.
- **Derive tenant from team_id with a mapping table**: Rejected. Adds complexity without clear benefit over direct tenant configuration. The mapping would itself need per-server/per-agent overrides, converging on the same configuration surface as the chosen approach.
- **Ignore tenant entirely (strip from requests)**: Rejected. Breaks A2A v1.0 compliance and prevents ContextForge from participating in tenant-aware agent ecosystems.

## Related
- ADR-0041: A2A Protocol v1.0 RC1 Migration Strategy
- ADR-0042: Virtual Servers as Multi-Protocol Endpoints
- ContextForge two-layer security model: `mcpgateway/auth.py` (`normalize_token_teams()`)
- Multi-tenancy architecture: `docs/docs/architecture/multitenancy.md`
- RBAC documentation: `docs/docs/manage/rbac.md`
