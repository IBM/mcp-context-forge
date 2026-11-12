# ADR-048: A2A v1.0 Protocol Migration

## Status
Accepted

!!! warning "Deprecated Rust A2A runtime reference"
    The Rust A2A runtime reference in this ADR is deprecated as of 2026-06-11
    and sunsets on 2026-07-07. The A2A protocol adapter remains supported.
    Prefer the Python A2A invocation path. See [Deprecations](../../deprecations.md).

## Context
The A2A protocol evolved from v0.3 to v1.0, introducing breaking changes in wire format:

- **Part discrimination via protobuf `oneof`** (field presence) instead of explicit `kind`/`type` fields
- **Uppercase enum values**: `ROLE_USER`, `ROLE_AGENT`, `TASK_STATE_COMPLETED`, etc.
- **PascalCase method names**: `SendMessage`, `GetTask`, `ListTasks`, etc.
- **Removal of `kind` wrapper fields** from messages, tasks, and artifacts

Previously, A2A v0.3 used explicit type discriminators (e.g., `kind: "user_message"`) and lowercase enum values. The v1.0 format reduces boilerplate and aligns with protobuf best practices by using field presence (`oneof`) for discrimination.

## Decision
Migrate to A2A v1.0 as the default protocol while retaining v0.3 backward compatibility via a shared protocol adapter (`mcpgateway/services/a2a_protocol.py`).

The adapter normalizes between v1 and legacy forms at the gateway boundary, allowing:
- Clients using v1.0 format to interoperate transparently
- Legacy v0.3 clients and agents to continue functioning without modification
- Gradual deprecation of v0.3 support in a future release

## Consequences

### Positive
- **Reduced message overhead**: v1.0 eliminates redundant `kind` fields, reducing payload size
- **Clearer contract**: PascalCase and uppercase enums align with protobuf naming conventions
- **Rust echo agent**: Serves v1 agent cards natively without SDK dependencies or translation layers
- **Simplified routing**: The Rust A2A runtime routes both v1 and legacy method names identically
- **Backward compatible**: Existing v0.3 integrations remain functional during the transition period

### Negative
- **Adapter complexity**: Protocol translation adds a maintenance burden
- **Testing overhead**: Both v1 and v0.3 paths must be tested to ensure correctness
- **Migration lag**: Clients upgrading at different rates may experience interoperability testing challenges

## Agent Card Shape

Agent cards dispatch on the stored protocol version through `is_v1_a2a_protocol()`. Cards for 1.x agents use the A2A 1.0 `AgentCard` shape. Cards for 0.x agents keep the legacy shape.

- The `protocol_version` column defaults to `"1.0"` and an empty value counts as 1.x. Existing agents with the default switch to the 1.0 shape.
- The internal card endpoint reads the caller's `A2A-Version` header. A pre-1.0 value gets the legacy shape for a 1.x agent. A missing header follows the stored version. The caller version never upgrades a 0.x agent.
- 1.x cards drop `url`, `protocolVersion`, `supportsAuthenticatedExtendedCard`, and `capabilities.stateTransitionHistory`.
- The card describes the upstream agent. `supportedInterfaces[].url` carries the stored `endpoint_url`, and OAuth flows carry the stored `token_url` and `authorization_url`. Callers reach the agent through the gateway. Layer-1 visibility scopes who can read the card.
- Server cards report `ServerInterface.binding` as the interface `url`. `resolve_server_agent` treats `binding` as the endpoint, so the card and invocation agree. Issue #7027 asks for the endpoint, not the protocol binding, and this decision follows that request. The protocol binding comes from `ServerInterface.protocol`.
- `protocolBinding: "JSONRPC"` and `extendedAgentCard: true` for agent cards reflect the only binding and the `GetExtendedAgentCard` support of the sidecar.
- Server cards aggregate capabilities, modes, and skills from enabled associated agents and skip malformed entries.
- Security schemes derive from auth configuration only. Cards never read `auth_value`, `client_secret`, or `private_key`.

## Implementation Notes

- Legacy method aliases (`message/send`, `tasks/get`) are accepted alongside v1 names (`SendMessage`, `GetTask`, `ListTasks`)
- The protocol adapter is single-threaded; all translation happens at the gateway boundary
- New agents should use v1 format; legacy support will be deprecated in a future release (to be announced)
- Integration tests verify both v1 and v0.3 paths for invoke, health checks, retries, timeouts, and URL validation

## References
- `mcpgateway/services/a2a_protocol.py` - Protocol adapter implementation
- `a2a-agents/rust/a2a-echo-agent/` - Rust reference implementation
- `crates/a2a_runtime/` - Deprecated Rust A2A runtime
