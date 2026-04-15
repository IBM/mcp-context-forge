# ADR-048: A2A v1.0 Protocol Migration

## Status
Accepted

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
- **Go echo agent**: Serves v1 agent cards natively without SDK dependencies or translation layers
- **Simplified routing**: The Rust A2A runtime routes both v1 and legacy method names identically
- **Backward compatible**: Existing v0.3 integrations remain functional during the transition period

### Negative
- **Adapter complexity**: Protocol translation adds a maintenance burden
- **Testing overhead**: Both v1 and v0.3 paths must be tested to ensure correctness
- **Migration lag**: Clients upgrading at different rates may experience interoperability testing challenges

## Implementation Notes

- Legacy method aliases (`message/send`, `tasks/get`) are accepted alongside v1 names (`SendMessage`, `GetTask`, `ListTasks`)
- The protocol adapter is single-threaded; all translation happens at the gateway boundary
- New agents should use v1 format; legacy support will be deprecated in a future release (to be announced)
- Integration tests verify both v1 and v0.3 paths for invoke, health checks, retries, timeouts, and URL validation

## References
- `mcpgateway/services/a2a_protocol.py` - Protocol adapter implementation
- `a2a-agents/go/a2a-echo-agent/` - Go reference implementation
- `crates/a2a_runtime/` - Rust A2A runtime
