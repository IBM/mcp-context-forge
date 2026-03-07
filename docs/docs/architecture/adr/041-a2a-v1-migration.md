# ADR-0041: A2A Protocol v1.0 RC1 Migration Strategy

## Context

ContextForge implements A2A Protocol v0.3.0 across proto definitions, Pydantic schemas, service logic, admin UI, and multiple transports (JSON-RPC, REST, gRPC, passthrough). The A2A protocol has released v1.0 RC1 with significant breaking changes:

- **Part restructuring**: Removal of `FilePart`/`DataPart` wrappers in favor of inline `kind`-discriminated unions.
- **Message field rename**: `content` renamed to `parts`.
- **AgentCard overhaul**: Introduction of `supported_interfaces` replacing flat endpoint fields.
- **Method name changes**: Transition from slash-style (`tasks/send`) to PascalCase (`SendTask`).
- **TaskState enum spelling**: `cancelled` changed to `canceled`.
- **New fields**: `tenant` and `blocking` added to request messages.

The broader ecosystem (Google A2A SDK, other implementations) is converging on v1.0. Continuing to support only v0.3.0 risks interoperability isolation as upstream agents and clients adopt the new specification.

## Decision

Adopt A2A v1.0 RC1 as the target specification. Maintain a backward compatibility layer for v0.3.0 agents during the transition period:

- **Dual method name acceptance**: Accept both slash-style (`tasks/send`) and PascalCase (`SendTask`) method names on inbound JSON-RPC requests.
- **Part normalization**: Accept parts with and without the `kind` discriminator field; normalize internally to v1.0 format.
- **`content`/`parts` field compatibility**: Accept either field name on inbound messages; always emit `parts` on outbound v1.0 wire format.
- **Protocol version per agent**: Each agent registration carries a `protocol_version` field that determines the outbound wire format used when forwarding requests to that agent.
- **Global feature flag**: `A2A_V1_COMPAT_MODE` (default `true`) controls whether v0.3.0 method names and field shapes are accepted. Setting to `false` enforces strict v1.0-only processing.
- **Deprecation headers**: Responses served through v0.3.0 compatibility paths include `Deprecation` and `Sunset` headers per RFC 8594.
- **Telemetry**: Compatibility-path usage is logged with structured metrics to track migration progress and identify agents still using v0.3.0 conventions.

## Consequences

### Positive
- Full interoperability with the v1.0 ecosystem from day one.
- Future-proof: aligns with the specification the community is standardizing on.
- Clean migration path for operators via per-agent `protocol_version` field -- agents can be upgraded individually.
- Migration tracking through telemetry provides visibility into remaining v0.3.0 usage.

### Negative
- Breaking change for clients hardcoded to v0.3.0 method names when `A2A_V1_COMPAT_MODE` is eventually disabled.
- Additional code complexity to maintain dual-version normalization logic in the service and transport layers.
- Testing surface increases: both v0.3.0 and v1.0 wire formats must be validated across all transports.

### Risks / Mitigations
- v1.0 RC1 may change before final release -- mitigate by isolating version-specific logic behind well-defined normalization functions that can be updated in a single pass.
- Compatibility layer may mask migration urgency -- mitigate with deprecation headers and telemetry dashboards that surface v0.3.0 usage to operators.
- Downstream agents may reject mixed-version traffic -- mitigate by strictly using the registered `protocol_version` for outbound formatting per agent.

## Alternatives Considered

- **Hard cutover to v1.0 only**: Rejected. Would break all existing v0.3.0 agent integrations immediately with no migration path.
- **Version negotiation at connection time**: Deferred. More complex and not required while only two versions exist. Can be revisited if a v2.0 emerges.
- **Separate v0.3.0 and v1.0 endpoint trees**: Rejected. Doubles the routing surface and complicates agent management without clear benefit over in-place normalization.

## Related
- A2A v1.0 RC1 specification: https://google.github.io/A2A/
- ADR-0042: Virtual Servers as Multi-Protocol Endpoints
- ADR-0043: Tenant vs Team Separation
- Existing A2A implementation: `mcpgateway/services/a2a_service.py`, `mcpgateway/schemas.py`
