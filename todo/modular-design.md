# Modular Design Investigation: Making MCP and A2A Replaceable Extensions

## Executive Summary

Short answer:

- Rewriting the **MCP protocol core** in Rust is feasible.
- Replacing the current MCP implementation as a clean **extension** is **not easy today** because MCP behavior is spread across routing, transport, session state, auth/RBAC, and downstream client code.
- Rewriting **A2A wire behavior** is easier than making **A2A a replaceable module**, because A2A is a first-class domain model tied to DB tables, admin UI, metrics, and tool/server integration.

My recommendation:

1. Do **not** start by trying to swap the whole MCP subsystem directly.
2. First extract an internal **protocol runtime seam** in Python.
3. Then implement the MCP runtime behind that seam as either:
   - a **Rust sidecar** over Unix socket / gRPC / local HTTP for a full replacement, or
   - a **PyO3 module** for targeted hot paths only.
4. After MCP is modularized, apply the same runtime/extension pattern to A2A.

If the goal is "I want to replace MCP and A2A independently," the architecture should move toward:

- Python core = control plane, auth, RBAC, persistence, admin UI, config
- Extension runtime = protocol engines
- Thin adapters between the two

## What I Investigated

I dug through the current MCP and A2A implementation, validated existing Rust integration paths in the repo, and built two throwaway Rust proofs of concept under `/tmp/cf-modular-poc`:

- an **in-process PyO3 MCP dispatcher**
- an **out-of-process Rust sidecar MCP dispatcher**

I also verified existing Rust assets already present in the repo:

- `plugins_rust/` builds successfully with `cargo check`
- `tools_rust/wrapper/` builds successfully with `cargo check`
- there is now an in-repo Rust MCP runtime prototype at [`tools_rust/mcp_runtime`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime)

## In-Repo Rust MCP Prototype

There is now a working Rust MCP runtime prototype in the repo:

- [`tools_rust/mcp_runtime/Cargo.toml`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime/Cargo.toml)
- [`tools_rust/mcp_runtime/src/lib.rs`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime/src/lib.rs)
- [`tools_rust/mcp_runtime/src/main.rs`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime/src/main.rs)
- [`tools_rust/mcp_runtime/tests/runtime.rs`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime/tests/runtime.rs)

Current ownership in Rust:

- `POST /mcp`, `POST /mcp/`, `POST /rpc`, `POST /rpc/`
- `MCP-Protocol-Version` validation with defaulting when the header is absent
- JSON-RPC request validation and batch rejection
- local `ping`
- notification transport semantics (`202 Accepted`)
- initialize parameter validation
- backend forwarding to Python `/rpc` for business execution

Still owned by Python:

- auth and token scoping
- RBAC
- session ownership and affinity
- streamable HTTP session lifecycle beyond plain POST JSON mode
- upstream tool/resource/prompt behavior

Verification completed:

- `cargo test --release` passed for [`tools_rust/mcp_runtime`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime)
- selected MCP 2025-11-25 compliance files passed against the Rust runtime when pointed at a small mock backend over `/rpc`
- the repo's full `tests/e2e/test_mcp_cli_protocol.py` passed when routed through the Rust runtime with `mcpgateway.wrapper` in front and a controlled `/rpc` backend behind it

This matters because the repo now has a real sidecar-style MCP runtime shell, not just throwaway `/tmp` experiments.

## Current MCP Architecture

MCP is currently spread across several layers, not one module.

### Main MCP implementation sites

- [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py)
  - mounts `/mcp`
  - defines `/rpc`
  - defines `/initialize`, `/ping`, notifications, completion, sampling
  - contains the large RPC method switch for `tools/list`, `tools/call`, `resources/list`, `resources/read`, `prompts/list`, `prompts/get`, `initialize`, notifications, elicitation, logging, etc.
- [`mcpgateway/transports/streamablehttp_transport.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/transports/streamablehttp_transport.py)
  - owns `mcp_app = Server("mcp-streamable-http")`
  - registers MCP handlers with SDK decorators
  - owns streamable HTTP auth
  - owns `SessionManagerWrapper`
  - directly depends on DB, permission checks, OAuth enforcement, and gateway services
- [`mcpgateway/cache/session_registry.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/session_registry.py)
  - owns `handle_initialize_logic`
  - tracks client capabilities, session owners, broadcast, elicitation capability
  - internally loops back into `http://127.0.0.1:{settings.port}/rpc`
- Upstream MCP client behavior is embedded in:
  - [`mcpgateway/services/tool_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/tool_service.py)
  - [`mcpgateway/services/resource_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/resource_service.py)
  - [`mcpgateway/services/gateway_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/gateway_service.py)
  - [`mcpgateway/services/mcp_session_pool.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/mcp_session_pool.py)

### Why MCP is hard to swap today

The MCP subsystem is not just "protocol handling." It is also:

- FastAPI routing
- ASGI path rewriting
- auth and token normalization
- RBAC enforcement
- session affinity
- session ownership
- client capability tracking
- SSE/WebSocket/Streamable HTTP handling
- upstream MCP client pooling and federation

That means a Rust rewrite cannot cleanly replace one file. It would either:

- duplicate a lot of gateway logic, or
- require a new internal seam first

## Current A2A Architecture

A2A is more domain-coupled than MCP.

### Main A2A implementation sites

- [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py)
  - defines `/a2a` CRUD and invoke endpoints inline
  - initializes the global `a2a_service`
- [`mcpgateway/services/a2a_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/a2a_service.py)
  - registration
  - listing
  - access checks
  - outbound invocation
  - metrics
  - cache invalidation
  - auth decode
- [`mcpgateway/admin.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/admin.py)
  - admin/UI behavior for A2A
  - some direct SQL over `DbA2AAgent`
- [`mcpgateway/db.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/db.py)
  - `A2AAgent`
  - metrics tables
  - server association
  - `tool_id` foreign key
- [`mcpgateway/schemas.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/schemas.py)
  - A2A request/response schemas and validation

### Why A2A is hard to swap today

A2A is tied to:

- DB schema
- admin UI
- metrics and cache
- RBAC permissions
- tool auto-creation/update/delete
- server associations

There is also duplicated protocol behavior:

- [`mcpgateway/services/a2a_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/a2a_service.py) invokes A2A agents
- [`mcpgateway/services/tool_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/tool_service.py) also invokes A2A agents for `integration_type == "A2A"`

So replacing the **A2A wire client** is feasible, but replacing **A2A as a core module** is a larger refactor.

## Existing Extension and Rust Patterns Already in the Repo

This matters because it shows what the codebase already tolerates.

### Existing Rust patterns

- PyO3 extension package:
  - [`plugins_rust/Cargo.toml`](/home/cmihai/agents2/pr/mcp-context-forge/plugins_rust/Cargo.toml)
  - [`plugins_rust/pyproject.toml`](/home/cmihai/agents2/pr/mcp-context-forge/plugins_rust/pyproject.toml)
  - [`plugins_rust/src/lib.rs`](/home/cmihai/agents2/pr/mcp-context-forge/plugins_rust/src/lib.rs)
- Standalone Rust binary:
  - [`tools_rust/wrapper/Cargo.toml`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/wrapper/Cargo.toml)
  - [`tools_rust/wrapper/src/lib.rs`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/wrapper/src/lib.rs)

### Existing out-of-process extension patterns

The plugin framework already supports external runtimes over multiple transports:

- MCP transport:
  - [`mcpgateway/plugins/framework/external/mcp/client.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/plugins/framework/external/mcp/client.py)
  - [`mcpgateway/plugins/framework/external/mcp/server/runtime.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/plugins/framework/external/mcp/server/runtime.py)
- gRPC transport:
  - [`mcpgateway/plugins/framework/external/grpc/client.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/plugins/framework/external/grpc/client.py)
  - [`mcpgateway/plugins/framework/external/grpc/server/runtime.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/plugins/framework/external/grpc/server/runtime.py)
- Unix socket transport:
  - [`mcpgateway/plugins/framework/external/unix/client.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/plugins/framework/external/unix/client.py)
  - [`mcpgateway/plugins/framework/external/unix/server/server.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/plugins/framework/external/unix/server/server.py)

This is a strong signal that a **sidecar protocol runtime** fits repo conventions better than a giant embedded FFI rewrite.

## Best Extraction Seam Confirmed

After going deeper into the current MCP implementation, the best first seam is clearer:

- replace the mounted `/mcp` runtime layer in Rust
- keep Python auth/path rewriting in front of it
- keep Python `/rpc` as the business-logic backend

Concretely, the most useful boundary today is:

- Rust runtime behind the mounted MCP transport at [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py#L7836)
- Python path rewrite and auth ahead of it at [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py#L1898) and [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py#L2021)
- Python `/rpc` as the backend dispatch seam at [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py#L5940)

Why this seam is better than extracting `SessionRegistry` first:

- the current Streamable HTTP implementation already routes POSTs into `/rpc`
- legacy SSE also self-calls `/rpc`
- auth/session ownership logic is security-critical and still cleaner to leave in Python during the first cut
- the decorated MCP SDK handlers are more coupled to service/DB internals than the `/mcp` mount boundary

### Packaging and release implications

PyO3 is supported here, but it is not yet integrated as a first-class path for the main gateway package.

- Rust wheel packaging is separate today:
  - [`plugins_rust/pyproject.toml`](/home/cmihai/agents2/pr/mcp-context-forge/plugins_rust/pyproject.toml) uses `maturin`
  - the root [`pyproject.toml`](/home/cmihai/agents2/pr/mcp-context-forge/pyproject.toml) still builds the Python package separately
- The repo already has explicit Rust build targets in [`Makefile`](/home/cmihai/agents2/pr/mcp-context-forge/Makefile), including `rust-build`, `rust-dev`, `rust-test`, and cross-platform wheel targets.

Practical effect:

- **PyO3** gives lower latency, but couples protocol delivery to Python wheel/ABI/release coordination.
- **Sidecar** gives a cleaner release boundary:
  - separate binary or container
  - easier rollback
  - easier crash isolation
  - less packaging coupling to Python interpreter details

## Prototype Results

I built two throwaway prototypes outside the repo under `/tmp/cf-modular-poc`.

### Prototype 1: PyO3 in-process MCP dispatcher

What it tested:

- Can Rust sit inside Python and accept gateway-shaped JSON-RPC payloads?
- Is the packaging/build story workable?
- What is the rough overhead of using Rust for dispatch/parsing?

Result:

- Build succeeded with `maturin develop --release`
- The module handled `initialize`, `ping`, `tools/list`, and `tools/call`
- Benchmark result for a simple `tools/call`-style dispatch loop:
  - Rust PyO3 module: about **1.43 microseconds per call**
  - Pure Python baseline: about **5.18 microseconds per call**
  - Rough speedup: about **3.6x**

Interpretation:

- PyO3 is viable for hot-path parsing/dispatch/codec work.
- It is attractive for:
  - JSON-RPC validation
  - schema normalization
  - SSE framing/parsing
  - message transforms
- It is **not** the cleanest first choice for replacing the full MCP subsystem because the FFI boundary gets wide fast once async I/O, auth, sessions, and callbacks get involved.

### Prototype 2: Rust sidecar MCP dispatcher

What it tested:

- Can Rust run as a separate protocol engine and respond to local JSON-RPC style requests cleanly?
- What is the boundary overhead of crossing into another process?

Result:

- Build succeeded with `cargo build --release`
- Local sidecar endpoint worked over loopback HTTP
- Benchmark result with a reused keep-alive connection:
  - about **239.8 microseconds per call**
- I then extended the throwaway sidecar to support **Unix domain sockets**
- Benchmark result with a reused UDS connection:
  - about **161.3 microseconds per call**

Interpretation:

- Boundary cost is much higher than PyO3, as expected.
- UDS is noticeably better than loopback TCP for the sidecar shape.
- But the process boundary is architecturally cleaner:
  - crash isolation
  - simpler ownership split
  - easier language boundary
  - easier to swap implementations
- For a full MCP engine replacement, this is the more realistic pattern.

### Important benchmark caveat

These prototypes only measured protocol dispatch overhead. They did **not** include:

- DB access
- auth/RBAC
- Redis
- session affinity
- real MCP SDK compatibility
- plugin execution

So the benchmark is not "full system speed." It is only useful for understanding **integration cost at the seam**.

## Compliance-Oriented Runtime Validation

I ran the repo's MCP 2025-11-25 compliance tests against the new Rust runtime using:

- Rust runtime as the HTTP edge
- a small mock backend behind `/rpc`

The following suites passed in that configuration:

- `base/test_no_batch_payloads.py`
- `lifecycle/test_initialize.py`
- `transport_core/test_streamable_http_protocol_header.py`
- `server_features/test_discovery_methods.py`
- `utilities/test_ping_and_notifications.py`
- `tasks/test_tasks_optional_capability.py`
- `authorization/test_protected_resource_metadata.py`
- `base/test_schema_surface_runtime.py`

What that proves:

- the Rust runtime already satisfies the MCP-2025 transport contract for:
  - protocol header validation
  - notification status mapping
  - JSON-RPC envelope handling
  - batch rejection
  - `/mcp` POST behavior
- the runtime is already a viable protocol shell
- the remaining hard work is not basic MCP wire handling, it is the Python-owned policy/session/business coupling behind it

## mcp-cli Validation

I also ran the repo's actual `mcp-cli` E2E suite:

- `tests/e2e/test_mcp_cli_protocol.py`

with this path:

- `mcp-cli`
- `mcpgateway.wrapper` over stdio
- Rust runtime on the HTTP MCP edge
- controlled backend behind `/rpc`

Result:

- `22 passed`

This matters because it validates more than protocol compliance. It proves the Rust runtime already works through the repo's actual stdio client bridge, not just direct HTTP JSON-RPC calls.

Two practical compatibility details mattered:

- the runtime needed `GET /health` because the `mcp-cli` E2E suite probes that path before running
- default support for older MCP protocol versions still matters because the current `mcp-cli` path and helper stack are not yet fully `2025-11-25` only

## Immediate Quick Wins

These are low-risk refactors that improve modularity before any Rust rewrite.

### MCP quick wins

#### 1. Extract auth visibility normalization into one helper

Why:

- The `is_admin` / `token_teams` / `public-only` normalization pattern is duplicated heavily.
- I counted **62** occurrences of `token_teams is None` in [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py).
- I counted **23** occurrences of the same pattern in [`mcpgateway/transports/streamablehttp_transport.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/transports/streamablehttp_transport.py).

Quick win:

- create one helper that returns normalized auth scope context
- use it in `/rpc`, REST MCP endpoints, and streamable HTTP handlers

Why it matters:

- removes copy-paste policy logic
- lowers risk when MCP moves behind a protocol runtime boundary

#### 2. Extract a shared MCP dispatcher from `/rpc`

Why:

- The main `/rpc` switch in [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py) is the current de facto MCP application core.
- Streamable HTTP handlers in [`mcpgateway/transports/streamablehttp_transport.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/transports/streamablehttp_transport.py) implement overlapping operations again.

Quick win:

- create an `MCPDispatcher` or `MCPApplicationService`
- have `/rpc` call it first
- later route streamable HTTP through the same service

Why it matters:

- this is the cleanest seam needed for any Rust runtime
- it matches the new in-repo Rust runtime, which already uses Python `/rpc` as its backend contract

#### 3. Remove self-HTTP from `SessionRegistry`

Why:

- [`mcpgateway/cache/session_registry.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/session_registry.py) still posts to `http://127.0.0.1:{settings.port}/rpc` for internal SSE RPC handling.

Quick win:

- inject the dispatcher directly instead of going through loopback HTTP

Why it matters:

- removes transport from internal control flow
- reduces latency
- makes the MCP core more portable to a runtime boundary later

#### 4. Consolidate session-affinity forwarding logic

Why:

- session-affinity forwarding logic exists in both [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py) and [`mcpgateway/transports/streamablehttp_transport.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/transports/streamablehttp_transport.py)

Quick win:

- extract one reusable affinity-forwarding helper/service

Why it matters:

- lowers transport-specific duplication before any runtime swap

### A2A quick wins

#### 1. Create one shared A2A protocol adapter

Why:

- outbound A2A request shaping exists in both [`mcpgateway/services/a2a_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/a2a_service.py) and [`mcpgateway/services/tool_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/tool_service.py)
- both build JSON-RPC payloads and custom A2A payloads separately

Quick win:

- create `A2AProtocolAdapter` or `A2AClient`
- centralize:
  - request shaping
  - auth application
  - query-param auth handling
  - response normalization

Why it matters:

- this is the easiest first seam for later Rust or SDK-backed A2A replacement

#### 2. Move admin A2A querying behind shared service/repository code

Why:

- [`mcpgateway/admin.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/admin.py) contains direct `DbA2AAgent` query logic for listing/searching/filtering
- that bypasses a clean A2A abstraction

Quick win:

- extract shared query helpers or an `A2ARepository`

Why it matters:

- makes A2A less UI-coupled
- reduces the amount of code that must change when A2A becomes more modular

## Recommended First PRs

If I were sequencing this for real, I would start with these PRs:

1. Add a shared auth-scope normalization helper and replace duplicated `token_teams` handling in MCP paths.
2. Extract an `MCPDispatcher` from the `/rpc` route without changing behavior.
3. Replace `SessionRegistry` loopback `/rpc` calls with direct dispatcher invocation.
4. Add an `A2AProtocolAdapter` and make both `A2AAgentService` and `ToolService` use it.
5. Move admin-side A2A list/search query code into shared service/repository helpers.

## Difficulty Assessment

### MCP

#### Replacing only hot paths with Rust

Difficulty: **moderate**

Examples:

- JSON parsing
- stream framing
- schema validation/normalization
- event buffer logic

This is the easiest Rust entry point.

#### Replacing the MCP protocol engine behind a new internal interface

Difficulty: **medium-hard**

This is the right target if you want MCP to become a true extension.

Main blockers:

- `/rpc` method dispatch is in [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py)
- streamable HTTP auth is in [`mcpgateway/transports/streamablehttp_transport.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/transports/streamablehttp_transport.py)
- session semantics live in [`mcpgateway/cache/session_registry.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/session_registry.py)
- upstream MCP client behavior is embedded in several services

#### Replacing the entire current MCP subsystem immediately

Difficulty: **hard**

This is the wrong first move. Too much behavior is currently cross-wired.

### A2A

#### Replacing the A2A HTTP/JSON-RPC client logic

Difficulty: **moderate**

This is very doable and should happen before any full modularization.

Main first step:

- introduce one shared `A2AClient` or `A2AProtocolAdapter`
- remove duplicate invocation logic from [`mcpgateway/services/a2a_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/a2a_service.py) and [`mcpgateway/services/tool_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/tool_service.py)

#### Replacing A2A as a full extension

Difficulty: **medium-hard to hard**

Because A2A currently owns:

- persistence
- UI
- metrics
- server relationships
- tool relationships

## Recommended Architecture

### Principle

Protocols should become **runtimes**, not **core modules**.

Core gateway should own:

- auth
- RBAC
- token scoping
- persistence
- admin UI
- plugin lifecycle
- audit/logging/metrics policy

Protocol runtimes should own:

- protocol message parsing
- transport semantics
- capability negotiation
- wire-level request/response mapping

### Proposed internal seam

Introduce a protocol runtime contract in Python first.

Example shape:

```python
class ProtocolRuntime(Protocol):
    name: str

    async def initialize(self, ctx: RuntimeContext) -> None: ...
    async def shutdown(self) -> None: ...

    async def dispatch_rpc(self, call: ProtocolCall, ctx: RequestContext) -> ProtocolResult: ...
    async def handle_stream(self, scope, receive, send, ctx: RequestContext) -> None: ...

    async def create_upstream_client(self, target: UpstreamTarget) -> UpstreamProtocolClient: ...
```

And the gateway side would provide:

- `RequestContextResolver`
- `PermissionAuthorizer`
- `SessionStore`
- `GatewayCatalog`
- `ToolCatalog`
- `PromptCatalog`
- `ResourceCatalog`

That lets the runtime ask the core for business decisions instead of reimplementing them.

## Best Rust strategy by scope

### If you want performance acceleration inside the existing Python architecture

Use **PyO3**.

Good candidates:

- JSON-RPC parser/validator
- event ring buffer
- SSE parser/framer
- schema normalization
- session-id parsing/validation

Not recommended as the first step for:

- full async transport ownership
- auth callbacks crossing FFI
- session lifecycle crossing FFI

### If you want MCP to be truly replaceable

Use a **Rust sidecar**.

Preferred transports in order:

1. **Unix socket**
2. **gRPC**
3. local HTTP

Why:

- Unix socket keeps latency lower than loopback TCP
- process boundary is clean
- fits current external runtime patterns already present in the plugin framework
- aligns with `tools_rust/wrapper` being a separate Rust process

## Concrete MCP Migration Plan

### Phase 0: Stop adding more MCP logic to `main.py`

Goal:

- freeze the current architectural sprawl

Actions:

- no new MCP method handling in [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py)
- no new self-HTTP loops where direct dispatcher calls would work better

### Phase 1: Extract an in-process MCP application service

Goal:

- separate "protocol dispatch" from FastAPI routes

Actions:

- move the `/rpc` method switch out of [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py)
- create one dispatcher that both `/rpc` and streamable HTTP use
- remove the loopback dependency in [`mcpgateway/cache/session_registry.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/session_registry.py)

Success criteria:

- `/rpc`, SSE, and streamable HTTP all call the same in-process dispatcher

### Phase 2: Extract gateway-owned dependency interfaces

Goal:

- keep policy/core concerns in Python while making the protocol engine swappable

Interfaces to extract:

- auth context resolver
- permission authorizer
- session store
- capability registry
- tool/prompt/resource lookup and invocation adapters

### Phase 3: Introduce runtime selection

Goal:

- make MCP runtime pluggable

Example:

- `python-sdk` runtime
- `rust-sidecar` runtime

At this stage, Python remains the default, Rust becomes an optional alternative.

Practical note:

- the new [`tools_rust/mcp_runtime`](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime) prototype is the starting point for the `rust-sidecar` runtime option

### Phase 4: Move MCP wire protocol into Rust

Goal:

- Rust owns:
  - message parsing
  - initialize/ping/notifications semantics
  - stream handling
  - capability negotiation

Python still owns:

- auth
- RBAC
- DB-backed catalogs
- policy
- plugin hooks

### Phase 5: Revisit upstream MCP client logic

Goal:

- decide whether upstream MCP client pooling/federation also moves behind the same runtime

This should happen last, not first.

## Concrete A2A Migration Plan

### Phase 1: Extract one A2A protocol adapter

Create a shared adapter used by both:

- [`mcpgateway/services/a2a_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/a2a_service.py)
- [`mcpgateway/services/tool_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/tool_service.py)

This is the obvious cleanup step and should happen even if you never rewrite A2A in Rust.

### Phase 2: Separate domain model from wire adapter

Keep in Python:

- `A2AAgent` persistence
- metrics
- admin UI
- RBAC

Move behind interface:

- request building
- auth/header/query-param application
- outbound transport behavior
- response normalization

### Phase 3: Optional Rust A2A runtime

Once MCP has a runtime model, A2A can follow it.

Important point:

A2A should probably be the **second** protocol runtime you modularize, not the first.

MCP is the better pathfinder because:

- it is more performance-sensitive
- it already has stronger transport semantics
- it already has Rust-adjacent code in the repo

## What I Would Do Next

In order:

1. Extract a shared MCP dispatcher from [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py).
2. Remove the loopback `/rpc` dependency from [`mcpgateway/cache/session_registry.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/session_registry.py).
3. Introduce a runtime contract for MCP.
4. Build a **Rust sidecar** proof of concept against that contract using Unix sockets.
5. Extract a shared A2A protocol adapter and deduplicate A2A invocation logic.
6. Only after that, consider A2A as a full extension runtime.

## Final Recommendation

## Implementation Update: Integrated Rust MCP Edge

The MCP Rust runtime is now integrated into the real gateway path behind an
experimental flag.

New runtime settings:

- `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_URL`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_TIMEOUT_SECONDS`

Container/launcher support:

- `Containerfile.lite` now copies a bundled `contextforge-mcp-runtime` binary
  when built with `--build-arg ENABLE_RUST=true`
- `docker-entrypoint.sh` can supervise that sidecar with
  `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`

Important design decision:

- the mounted `/mcp` app is now hybrid
- POST MCP traffic proxies to Rust
- non-POST MCP traffic still falls back to the Python streamable HTTP transport

Why this matters:

- it keeps existing session-management behavior available while the Rust runtime
  is still POST-focused
- it makes the integration safe enough to run in the actual gateway instead of
  only in a synthetic standalone demo

Correctness fix added during integration:

- server-scoped `/servers/<id>/mcp` requests now preserve semantics because the
  Python proxy injects `server_id` into forwarded JSON-RPC params before the
  Rust runtime passes the request to Python `/rpc`

Hardening fix added during integration:

- the Rust runtime now strips internal-only headers such as
  `x-forwarded-internally` and `x-mcp-session-id` instead of forwarding them
  back into Python `/rpc`

If the question is "how easy is it to rewrite MCP in Rust and then do the same for A2A?"

My answer is:

- **Rewriting MCP internals in Rust:** feasible
- **Making MCP replaceable right now:** not easy
- **Best path:** extract seams first, then use a Rust sidecar for the full protocol runtime
- **A2A afterward:** yes, but first deduplicate and isolate the A2A wire adapter from the A2A domain model

If you try to rewrite MCP directly without extracting the seam first, you will mostly be rewriting Python coupling in another language.

If you extract the seam first, then the Rust rewrite becomes a bounded systems task instead of an architecture fight.
