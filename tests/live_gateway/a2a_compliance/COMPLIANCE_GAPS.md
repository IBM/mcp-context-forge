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

---

### A2A-GAP-002 — Echo agent card omits `supportedInterfaces`; advertises `protocolVersion` at the top level

| | |
|---|---|
| **Targets affected** | `reference` |
| **Tests** | `test_agent_card.py::test_agent_card_required_fields`, `::test_supported_interfaces_non_empty`, `test_well_known.py::test_extended_agent_card_route`, `test_version_negotiation.py::test_card_advertises_expected_protocol_version` |
| **Spec** | A2A 1.0.0 AgentCard — `supported_interfaces` is the canonical field for per-transport version negotiation; top-level `protocol_version` is **not** in the protobuf schema |

**Observed**: the bundled Rust `a2a_echo_agent` serves a card with a
flat top-level `protocolVersion: "1.0.0"` and no `supportedInterfaces`
array at all. The SDK's `ClientFactory.create_from_url` accepts the
shape because the JSON-RPC transport is the default fallback when
`supported_interfaces` is empty, but the card violates the protobuf
contract on the wire.

**Expected**: per the protobuf schema captured during Phase-0 probing
(`AgentCard.DESCRIPTOR.fields_by_name`), the canonical fields are
`name`, `version`, `supported_interfaces`, `provider`, `capabilities`,
`security_schemes`, `security_requirements`, etc. — with no top-level
`protocol_version`. Each interface entry inside `supported_interfaces`
carries its own `protocol_version`.

**Why**: echo agent predates the 1.0.0 schema freeze; its card was
hand-written rather than generated from the protobuf. Tracked as
a fix to the `a2a-agents/rust/a2a-echo-agent` Rust source.

**How to close**: rewrite the echo agent's card serialization to emit
`supported_interfaces: [{ "transportProtocol": "JSONRPC",
"protocolVersion": "1.0.0", "url": "..." }]` and drop the top-level
`protocolVersion`. When the card validates against the protobuf,
remove the four `@pytest.mark.xfail` decorators referencing this gap.

---

### A2A-GAP-003 — Echo agent card omits `securitySchemes` and `securityRequirements`

| | |
|---|---|
| **Targets affected** | `reference` |
| **Tests** | `test_security.py::test_security_schemes_field_present`, `::test_security_requirements_field_present` |
| **Spec** | A2A 1.0.0 AgentCard — `security_schemes` and `security_requirements` are first-class fields the protobuf always carries (even if empty) |

**Observed**: the echo agent's card has no `securitySchemes` /
`securityRequirements` keys. Protobuf JSON serialization can drop
fields whose values are empty unless emit-defaults is on; the echo
agent's Rust implementation appears to default to "drop-if-empty".

**Expected**: clients should be able to confirm "no auth required"
positively. Missing fields are ambiguous — they could mean "no auth"
or "spec-violating card". Explicit emission (empty map / empty list)
is the only way to make the answer unambiguous.

**How to close**: configure the echo agent's serializer to always
emit `securitySchemes: {}` and `securityRequirements: []` (or
`null`-typed equivalents the protobuf JSON contract requires). When
the card includes the fields, remove the two `xfail` decorators
referencing this gap.

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

### A2A-GAP-005 — Echo agent advertises `url: http://localhost:9100` in its card; SDK follow-ups time out

| | |
|---|---|
| **Targets affected** | `reference` |
| **Tests** | `test_jsonrpc_methods.py::test_send_message_returns_at_least_one_response`, `::test_send_message_echoes_input_text`, `::test_list_tasks_returns_response`, `test_messages_artifacts.py::test_send_message_response_populates_message_or_task`, `::test_echo_response_carries_text_part` (all under `[reference-jsonrpc]`) |
| **Spec** | A2A 1.0.0 AgentCard `url` field — the card's `url` is what clients use for follow-up JSON-RPC calls after fetching the card |

**Observed**: the echo agent's card serializes `url: "http://localhost:9100"`.
The SDK's `ClientFactory` reads this and uses it as the JSON-RPC
endpoint for all subsequent `send_message` / `list_tasks` / etc. calls.
On macOS, the project's autouse DNS stub falls through to the system
resolver, which returns IPv6 first for `localhost`; the compose
port-forward binds IPv4 only — so the SDK's follow-up POSTs hit
`[::1]:9100`, time out, and surface as `A2AClientTimeoutError`.

The initial card-fetch hop succeeds because the test harness uses
`http://127.0.0.1:9100` directly (via `ClientFactory.create_from_url`
with the IPv4 literal). It's the *post-card* calls — which read the
URL out of the card payload — that fail.

`test_get_task_for_unknown_id_raises` and `test_cancel_task_for_unknown_id_raises`
incidentally pass on `[reference-jsonrpc]` because they assert that
*any* exception escapes — the timeout satisfies that contract. Those
tests should be tightened to assert on `TaskNotFoundError` once this
gap closes.

**Why**: the echo agent runs in a docker-compose container that needs
to be reachable from two contexts:

- The test harness on the host → `127.0.0.1:9100` (or `host.docker.internal`).
- Other compose services → `a2a_echo_agent:9100` (docker DNS).

A single `url` field in the card can't serve both. The agent defaults
to `localhost:9100` which works for neither without DNS gymnastics.

**Resolution options** (pick one when implementing):

1. **Compose-side**: set `A2A_ECHO_PUBLIC_URL=http://127.0.0.1:9100`
   on the agent service in `docker-compose.yml`. Cards then advertise
   the host-reachable address; compose-internal callers stay on the
   hardcoded `http://a2a_echo_agent:9100/` URL the gateway federation
   passes to register-a2a-echo (which doesn't read the card).
2. **Harness-side**: pre-fetch the card via raw httpx, rewrite the
   `url` field to `127.0.0.1`, and pass the doctored card to
   `factory.create(card, ...)` instead of using `create_from_url`.
3. **SDK-side**: pass a `url` override to `ClientFactory` / `ClientConfig`
   that supersedes the card's `url` for the JSON-RPC transport. Not
   currently exposed by the SDK as of `a2a-sdk` 0.x (verify with the
   shipped version before claiming).

**How to close**: implement any of the three resolution options above
(option 1 is the smallest diff). Once the SDK's follow-up calls reach
the agent, the five affected tests pass on `[reference-jsonrpc]` and
the conftest's `_REFERENCE_GAP_005_TESTS` allowlist (see
`conftest.pytest_collection_modifyitems`) drops to empty — delete the
hook arm at that point and move this entry to "Closed gaps".

---

## Closed gaps

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
