# Rust MCP Runtime Removal

The in-repository Rust MCP and A2A sidecars are removed. The Python gateway serves
MCP and A2A requests. Remove sidecar environment variables from deployments.

The separate external Rust dataplane, `DATAPLANE_PUBLISHER`, and `/contextforge-rs`
ingress remain outside this removal.

## Internal dispatch caller audit

Python session affinity still calls `POST /_internal/mcp/rpc` through
`mcpgateway.utils.internal_http.post_rpc_in_process()`. Both the Streamable HTTP
transport and the session-affinity Redis consumer use this helper. It dispatches
inside the session owner worker, preserving that worker's upstream connections.

The removed sidecars were the only production callers of the other internal MCP
handlers and all internal A2A handlers. Those handlers are removed, including
`/_internal/mcp/authenticate`, the per-method and direct-execution authorization
routes, and the A2A resolve, task, push, and event bridges. Public MCP, RPC, and A2A
routes retain their Python handlers.

## Retained Python affinity trust boundary

`/_internal/mcp/rpc` accepts only the `affinity` marker. The retired `rust` marker
cannot grant internal trust. The route requires the shared-secret HMAC, a
non-empty forwarded auth context, and a loopback client address. Middleware uses
the same trust gate, including deployments with a root path.

Redis consumers verify the signature over the complete forwarded envelope before
in-process dispatch. Forwarded client-IP headers are stripped. The owner worker
validates the decoded context and retains team visibility, token server scope,
scoped permissions, and RBAC checks. Anonymous contexts remain public-only.

The existing `x-contextforge-mcp-runtime` and
`x-contextforge-mcp-runtime-auth` header names remain part of this Python internal
contract. The Python transport also reports `x-contextforge-mcp-runtime: python`
on responses. These headers do not enable a sidecar.

## Deployment cleanup

Compose no longer forwards `A2A_RUST_*` variables or derives sidecar credentials
from gateway secrets. The Helm nginx A2A upstream targets the Python gateway
directly. SSO audience seeding no longer filters retired runtime variables.

## Verification

The affinity trust regressions live in
`tests/unit/mcpgateway/test_internal_runtime_trust.py`. The live ingress and
multi-worker regressions live in
`tests/live_gateway/mcp/test_python_ingress_security.py`. The multi-worker check
requires an isolated stateful gateway with at least two workers, Redis affinity,
`MCP_AFFINITY_TEST_REDIS_URL`, `MCP_AFFINITY_TEST_PEER_URL`, and
`MCP_INGRESS_TEST_TOKEN`. The peer URL addresses a different worker directly. Enable
`MCP_AFFINITY_SENTINEL_TESTS=true` to verify protected backend execution denials.
