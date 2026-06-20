# A2A Compliance Gaps

A running tally of A2A spec gaps and behavioral divergences surfaced by
this harness. Entries describe observed vs. expected behavior, link to
the relevant spec section and tracking issues, and name the test(s)
marked `xfail` for the gap.

Gap IDs are namespaced as `A2A-GAP-NNN` so they don't collide with the
MCP harness's `GAP-NNN` series. Monotonic within this file — never
reuse an ID even after closure.

## Workflow

### Logging a new gap

1. A test fails on one or more targets.
2. Investigate. Document the gap below with full details — ID, targets,
   tests, spec reference, observed vs. expected, related issues.
3. Add `xfail_on(request, <targets>, reason="A2A-GAP-NNN: <short summary>")`
   at the top of the affected test body. Match the target list to the
   "Targets affected" row of the gap entry.
4. Run the test locally to confirm it reports `XFAIL` (not `FAILED`)
   before committing.

### Keeping the gap entry and the `xfail` marker in sync

If the gap's scope, symptoms, or related issues change — e.g. a fix
narrows it to one transport, or a new tracking issue supersedes the
cited blocker — update **both** the gap entry below **and** the
`reason="…"` string in the test. The reason string is what shows up in
pytest output, so it should read well on its own as a breadcrumb to
the gap entry.

### Closing a gap (fully or partially)

- **Full closure** — every cell listed under the gap now passes. Delete
  the `xfail_on` line in the test and move the entry to "Closed gaps"
  with the fixing PR / commit SHA. pytest's next run will confirm with
  a plain pass.
- **Partial closure** — a fix covers some targets but not others (e.g.
  `gateway_proxy` passes, `gateway_virtual` still fails). **Do not
  delete** the `xfail_on` call. Narrow its target list to only the
  still-broken cells, update the "Targets affected" row of the gap
  entry to match, and add a dated note describing what closed and
  what's still open.

When pytest reports `XPASS` unexpectedly (a cell marked xfail now
passes), treat it as a signal the gap is closing on that cell. Update
the marker and the entry per the rules above.

## Open gaps

---

### A2A-GAP-001 — Gateway lacks native A2A protocol passthrough

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | every test under `v1_0_0/` against the two gateway targets — the harness's `gateway_proxy` and `gateway_virtual` targets currently raise on `_open_client` so the entire matrix column xfails through this one gap |
| **Spec** | [A2A 1.0.0 — JSON-RPC transport binding](https://a2a-protocol.org/) (placeholder; update with canonical URL when finalized) |

**Observed**: ContextForge exposes A2A agents through three surfaces:

| Surface | Path | Shape |
|---|---|---|
| Admin CRUD | `GET/POST/PUT/DELETE /a2a` and `/a2a/{agent_id}` | REST over the gateway's `A2AAgentRead` model — not the A2A AgentCard schema |
| REST invocation | `POST /a2a/{agent_name}/invoke` | Custom REST body — not JSON-RPC |
| Internal authz | `POST /_internal/a2a/{invoke,list,get}/authz`, `POST /_internal/a2a/tasks/{get,list,cancel}` | Internal-only, not publicly routed |

None of these answer the public JSON-RPC + well-known-card contract
that an `a2a.client.Client` instance expects when called with
`ClientFactory.create_from_url(...)`.

**Expected**: the gateway exposes a native A2A endpoint per registered
agent — minimally:

- `GET /a2a/{agent_name}/.well-known/agent-card.json` returning the
  agent's spec-shaped AgentCard.
- `POST /a2a/{agent_name}/` accepting JSON-RPC envelopes for the full
  A2A method set (``SendMessage``, ``GetTask``, ``ListTasks``,
  ``CancelTask``, ``GetExtendedAgentCard``, plus 0.3.0 legacy aliases
  for backwards compatibility).

— so an A2A SDK client can connect end-to-end without bespoke
transport adaptation.

**Why**: Phase 4 of the ContextForge A2A roadmap. Tracked separately
once an issue is filed; this gap exists to mark all gateway-target
cells as known-failing in the meantime.

**How to close**: implement native A2A passthrough at the per-agent
public route + add the well-known agent-card endpoint. Update
`A2AGatewayProxyTarget` and `A2AGatewayVirtualServerTarget._open_client`
to construct real `Client` instances via
`ClientFactory.create_from_url(...)`. Remove the placeholder
`NotImplementedError` raises; the next matrix run will surface XPASS
on every previously-xfailed cell.

## Closed gaps

### A2A-GAP-006 — Echo agent response payloads included non-protobuf fields *(closed 2026-06-20)*

**Was**: the SDK's `Client.send_message` round-trip succeeded at the HTTP
layer but `google.protobuf.json_format.ParseError` blew up at parse time
because the echo agent emitted `task` payload fields at the
`SendMessageResponse` root rather than wrapping them in the protobuf
`oneof { Task task; Message message; }`. A separate symptom on v1.0.0
list_tasks: each `Task` emitted non-schema `createdAt` / `updatedAt`
fields that the v1.0.0 parser rejected.

**How closed**: two Rust changes in `a2a-agents/rust/a2a-echo-agent/src/main.rs`.

1. `handle_send_message` now wraps the task value for v1.0.0 methods —
   ``Ok(json!({ "task": task_value }))`` — so `SendMessageResponse`
   parsing finds the `task` field at the expected path. Legacy v0.3.x
   methods stay unwrapped (`CompatJsonRpcTransport` tolerates the flat
   shape).
2. `task_to_value` no longer emits `createdAt` / `updatedAt` for v1.0.0;
   those fields are not in the v1.0.0 `Task.DESCRIPTOR`. They remain on
   the legacy shape (under the existing `kind: "task"` discriminator)
   for v0.3.x back-compat.

The unit tests in main.rs were updated to dig into `result["task"]`
for v1.0.0 method calls and to assert the absent timestamp fields.

**v0.3.0 list_tasks nuance**: the SDK's `CompatJsonRpcTransport`
explicitly raises `NotImplementedError: ListTasks is not supported in
A2A v0.3 JSONRPC` regardless of agent behavior. `test_list_tasks_returns_response`
now catches that and `pytest.skip`s on the v0.3.0 cell — not an
xfail. The conftest's `_REFERENCE_GAP_006_TESTS_BY_VERSION` arm was
deleted entirely; the only remaining xfail dimension is GAP-001.

---

### A2A-GAP-005 — Echo agent advertised `url: http://localhost:9100` *(closed 2026-06-20)*

**Was**: echo agent's card serialized `url: "http://localhost:9100"`.
On macOS, the SDK's JSON-RPC follow-up calls hit IPv6-first DNS
resolution; compose binds IPv4 only → `A2AClientTimeoutError`.

**How closed**: set `A2A_ECHO_PUBLIC_URL=http://127.0.0.1:9100` on
the `a2a_echo_agent` service in `docker-compose.yml`. Card now
serializes with the IPv4 literal. Verified: HTTP POSTs to
`http://127.0.0.1:9100/` succeed (200 OK).

**Successor**: the five SDK Client tests this gap blocked still failed
initially for a different reason — the echo agent's response shape
issue — which became A2A-GAP-006 (also now closed).

---

### A2A-GAP-004 — Echo agent returned `-32700 Parse error` for missing-method envelope *(closed 2026-06-20)*

**Was**: the agent's `handle_jsonrpc_body` mapped *any* serde
deserialization failure to `-32700`, including the well-formed JSON
case where `method` was simply missing. JSON-RPC 2.0 § 5.1 reserves
`-32700` for actual parse errors and `-32600` for valid JSON with an
invalid Request envelope (which includes missing `method`).

**How closed**: refactored `handle_jsonrpc_body` to a two-stage parse.
Step 1 attempts raw `serde_json::from_slice::<Value>` — failure here
returns `-32700`. Step 2 inspects the parsed object for required
fields — missing or non-string `method` returns `-32600` with the
preserved `id` (per spec). Only after both gates does the body
deserialize into the typed `JsonRpcRequest`. A new unit test
(`missing_method_returns_invalid_request_envelope`) pins the
behavior at the agent level.

---

### A2A-GAP-003 — Echo agent card omits `securitySchemes` / `securityRequirements` *(closed 2026-06-20 — wontfix, test-side spec misreading)*

**Was**: the echo agent's card had no `securitySchemes` /
`securityRequirements` keys. Tests asserted "MUST emit even if empty"
and xfailed under this gap.

**How closed**: re-examined the protobuf JSON convention — empty maps
and empty lists are legitimately omittable per the standard
`json_format` serializer behavior, and the A2A spec doesn't override
that default. Absence is semantically equivalent to "no auth
required". The tests were too strict; the agent is conformant.

Tests under `v1_0_0/test_security.py` and `v0_3_0/test_security.py`
were softened from "MUST be present" to "IF present, validate shape".
The `xfail` decorators referencing A2A-GAP-003 were removed. Both
suites now pass on this surface.

**Lesson**: protobuf JSON omit-defaults is the norm. Future compliance
tests should validate field shape when present and accept absence as
the schema default, unless a specific spec section requires explicit
emission.

---

### A2A-GAP-002 — Echo agent emitted v0.3.0-shaped card on v1.0.0 endpoints *(closed 2026-06-20)*

**Was**: the bundled Rust `a2a_echo_agent` emitted a single flat card
shape (top-level `protocolVersion` / `url`, no `supportedInterfaces`)
regardless of the advertised `protocolVersion`. The flat shape is
correct for v0.3.0's `AgentCard` schema; for v1.0.0, transport
advertisement moved into a `supported_interfaces` array and the
top-level fields were dropped from the protobuf.

**How closed**: made `agent_card()` in
`a2a-agents/rust/a2a-echo-agent/src/main.rs` version-aware. When
`config.protocol_version` starts with `1.`, the agent now emits a
v1.0.0-shaped card with `supportedInterfaces: [{ "protocolBinding":
"JSONRPC", "protocolVersion": "...", "url": "..." }]` and **no**
top-level `protocolVersion` / `url`. For `0.3.x` versions, the flat
shape is preserved.

**Wire-detail gotcha**: the initial fix used `transportProtocol` as
the interface field name (intuited from the
`TransportProtocol.JSONRPC` enum). The actual protobuf field is
`protocol_binding` (JSON: `protocolBinding`) — the SDK silently
dropped the misnamed field and `ClientFactory.create_from_url` failed
with `ValueError: no compatible transports found`. The reliable
fix-path is always `cls.DESCRIPTOR.fields_by_name` introspection, not
inferring field names from sibling enum names.

Tests: the four `@pytest.mark.xfail` decorators on v1.0.0 (in
`test_agent_card.py`, `test_well_known.py`,
`test_version_negotiation.py`) were removed. v0.3.0 tests were
rewritten earlier this session to assert against the v0.3.0 schema
(top-level `protocolVersion` / `url`) and so were unaffected by the
agent change.
