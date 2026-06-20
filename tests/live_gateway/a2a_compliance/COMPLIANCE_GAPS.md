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

---

### A2A-GAP-002 — Echo agent emits v0.3.0-shaped card on v1.0.0 endpoints

| | |
|---|---|
| **Targets affected** | `reference` (**v1.0.0 suite only** — v0.3.0 tests accept the existing card shape because it IS the v0.3.0 schema) |
| **Tests** | `v1_0_0/test_agent_card.py::test_agent_card_required_fields`, `::test_supported_interfaces_non_empty`, `v1_0_0/test_well_known.py::test_extended_agent_card_route`, `v1_0_0/test_version_negotiation.py::test_card_advertises_expected_protocol_version` |
| **Spec** | A2A 1.0.0 vs 0.3.0 `AgentCard` protobuf schemas (verified via Phase-0 introspection of `a2a.types.AgentCard` and `a2a.compat.v0_3.types.AgentCard`) |

**Observed**: the bundled Rust `a2a_echo_agent` always emits a v0.3.0-shaped
card regardless of the advertised `protocolVersion`:

| Card field | v1.0.0 schema | v0.3.0 schema | Echo agent emits |
|---|---|---|---|
| Transport advertisement | `supported_interfaces[]` (array) | `protocol_version`, `url`, `preferred_transport`, `additional_interfaces[]` (top-level) | v0.3.0 shape |
| `protocol_version` at top level | not in schema | required | always emitted |
| `url` at top level | not in schema | required | always emitted |
| `supported_interfaces` array | required | not in schema | never emitted |

The SDK's `ClientFactory.create_from_url` accepts the card under both
advertised versions because the JSON-RPC transport is the default
fallback when `supported_interfaces` is empty — but the card violates
the v1.0.0 protobuf contract on the wire when the agent claims v1.0.0.

**Expected**: when the agent advertises `protocolVersion: 1.x.y`, the
card should serialize with `supported_interfaces: [{ ... }]` and omit
the top-level `protocol_version` / `url` fields. When advertising
`protocolVersion: 0.3.x`, the existing flat shape is correct.

**Why**: the echo agent's card serializer is version-agnostic — it
emits the same JSON regardless of the `A2A_ECHO_PROTOCOL_VERSION`
env var. Card was hand-written against an early-draft schema closer
to v0.3.0 and never adjusted when 1.0.0 introduced the
`supported_interfaces` indirection.

**How to close**: make the echo agent's card serializer version-aware.
When `config.protocol_version` starts with `1.`, emit:

```json
{
  "name": "...", "version": "...", "capabilities": {...}, ...,
  "supportedInterfaces": [
    {"transportProtocol": "JSONRPC", "protocolVersion": "1.0.0", "url": "http://..."}
  ]
}
```

(no top-level `protocolVersion` / `url`). For `0.3.x` versions, keep
the current flat shape. Once the v1.0.0 card validates against the
v1.0.0 protobuf, remove the four `@pytest.mark.xfail` decorators
under `v1_0_0/` that reference this gap.

---

### A2A-GAP-004 — Echo agent returns `-32700 Parse error` for an envelope missing the `method` field

| | |
|---|---|
| **Targets affected** | `reference` |
| **Tests** | `test_error_handling.py::test_missing_method_returns_invalid_request` |
| **Spec** | [JSON-RPC 2.0 § 5.1 reserved error codes](https://www.jsonrpc.org/specification#error_object) — `-32700 Parse error` is reserved specifically for *invalid JSON*. A well-formed JSON envelope missing the `method` field is `-32600 Invalid Request`. |

**Observed**: posting `{"jsonrpc":"2.0","id":"...","params":{}}` (valid
JSON, no `method`) returns `{"code":-32700,"message":"parse error"}`.

**Expected**: well-formed JSON parses successfully, so `-32700` is the
wrong code. `-32600 Invalid Request` is the JSON-RPC 2.0 reserved
value for a JSON object that "is not a valid Request object". A client
with routing logic that branches on `code == -32600` can't distinguish
this case from network garbage.

**Why**: likely a single error-mapping function in the echo agent's
JSON-RPC dispatch that conflates "JSON parse failed" with "envelope
missing method".

**How to close**: separate the two error paths in the echo agent's
dispatch and emit `-32600` when `method` is missing or non-string. Drop
the `xfail` on this test.

---

### A2A-GAP-006 — Echo agent response payloads include non-protobuf fields the SDK parser rejects

| | |
|---|---|
| **Targets affected** | `reference` |
| **Tests (v1.0.0)** | 5 cells: `test_jsonrpc_methods.py::test_send_message_returns_at_least_one_response`, `::test_send_message_echoes_input_text`, `::test_list_tasks_returns_response`, `test_messages_artifacts.py::test_send_message_response_populates_message_or_task`, `::test_echo_response_carries_text_part` |
| **Tests (v0.3.0)** | 1 cell: `test_jsonrpc_methods.py::test_list_tasks_returns_response` (the four `SendMessage`-related tests pass under `CompatJsonRpcTransport`) |
| **Spec** | A2A 1.0.0 — `SendMessageResponse` protobuf schema: `oneof { Task task; Message message; }`. `artifacts` belongs on `Task`, not at the response root. |

**Observed (v1.0.0)**: the SDK's `Client.send_message` round-trip
succeeds at the HTTP layer (`POST http://127.0.0.1:9100/` returns
`200 OK`), then parsing the response into `SendMessageResponse` fails
with:

```
google.protobuf.json_format.ParseError: Message type "lf.a2a.v1.SendMessageResponse"
has no field named "artifacts" at "SendMessageResponse". Available
Fields(except extensions): "['task', 'message']"
```

**Observed (v0.3.0)**: the `SendMessage`-related tests **pass** —
the SDK's `CompatJsonRpcTransport` for legacy 0.3.x has a different
response shape that doesn't trip on the agent's flat layout.
`test_list_tasks_returns_response` still fails on v0.3.0 with an
analogous parse error against the legacy `ListTasksResponse` shape,
suggesting the agent's response builder has the same flatness bug on
`tasks/list` as on `SendMessage` but the SDK happens to tolerate the
`SendMessage`-shape rewrite for v0.3.x.

**Expected**: per the protobuf schema captured during Phase-0
introspection (`SendMessageResponse.DESCRIPTOR.fields_by_name`,
`Task.DESCRIPTOR.fields_by_name`), responses carry either a `task`
field (full Task with its own `artifacts`) or a `message` field. The
v0.3.0 legacy schema has its own equivalent. Artifacts always
belong inside a Task, never at the response envelope root.

**Why**: the echo agent's response serializer likely emits a flat
struct with `message` + `artifacts` instead of wrapping artifacts
inside a Task or omitting them entirely for the echo-only case. The
v0.3.0 `CompatJsonRpcTransport` has a more forgiving parser for the
`SendMessage` path; the `tasks/list` path doesn't get the same lenience.

**How to close**: rework the echo agent's response builder to emit
`{"message": {...}}` for the message-only echo case, or
`{"task": {"id": "...", "artifacts": [...], ...}}` when a task is
involved — for both the 1.0.0 and 0.3.0 schemas. Once responses parse,
the five v1.0.0 cells and the one v0.3.0 cell pass — drop the conftest's
`_REFERENCE_GAP_006_TESTS_BY_VERSION` arm at that point and move this
entry to "Closed gaps".

---

## Closed gaps

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

### A2A-GAP-005 — Echo agent advertised `url: http://localhost:9100` *(closed 2026-06-20)*

**Was**: echo agent's card serialized `url: "http://localhost:9100"`.
On macOS, the SDK's JSON-RPC follow-up calls hit IPv6-first DNS
resolution; compose binds IPv4 only → `A2AClientTimeoutError`.

**How closed**: set `A2A_ECHO_PUBLIC_URL=http://127.0.0.1:9100` on
the `a2a_echo_agent` service in `docker-compose.yml`. Card now
serializes with the IPv4 literal. Verified: HTTP POSTs to
`http://127.0.0.1:9100/` succeed (200 OK).

**Successor**: the five SDK Client tests this gap blocked still fail
on `[reference-jsonrpc]`, but for a different reason: the echo agent's
`SendMessageResponse` includes a non-protobuf `artifacts` field at the
response root. Tracked as A2A-GAP-006.
