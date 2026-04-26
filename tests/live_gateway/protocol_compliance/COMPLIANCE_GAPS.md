# MCP Compliance Gaps

A running tally of MCP 2025-11-25 spec gaps and behavioral divergences
surfaced by this harness. Entries describe observed vs. expected behavior,
link to the relevant spec section and tracking issues, and name the test(s)
marked `xfail` for the gap.

## Stream-attribution note

Streamable HTTP has two server→client streams:

- **Standalone stream** — a long-lived SSE stream opened by an HTTP GET
  to `/mcp/`. Used for server-initiated traffic that isn't tied to any
  specific client request.
- **POST-correlated stream** — SSE opened as the response body to a
  client POST that declared `Accept: text/event-stream`. Carries
  everything emitted in the context of that request (including the
  eventual response).

The spec is explicit: **server→client *requests* (`roots/list`,
`sampling/createMessage`, `elicitation/create`) MUST NOT be sent on the
standalone stream** — they travel on the POST-correlated stream of the
originating client request. Server→client *notifications* are more
flexible: request-tied notifications (progress, `*/list_changed`
triggered by a tool call, the response's own `notifications/message`)
SHOULD ride the POST-correlated stream; notifications not tied to a
specific request (subscription updates, level-change-triggered logs
between calls) ride the standalone stream.

Issue #4205 is specifically about the standalone stream (gateway
returning 405 on `GET /mcp/`). Attributing a gap to #4205 is only
correct for standalone-only traffic (e.g. GAP-011 resource-subscription
updates). Gaps concerning server→client *requests* or request-tied
*notifications* are about POST-correlated-stream relay and should not
point at #4205 as the root cause.

## Workflow

### Logging a new gap

1. A test fails on one or more targets.
2. Investigate. Document the gap below with full details — ID, targets,
   tests, spec reference, observed vs. expected, related issues. Use a
   monotonic ID (`GAP-001`, `GAP-002`, …). Never reuse an ID even after
   a gap closes; keep the historical record stable.
3. Add `xfail_on(request, <targets>, reason="GAP-NNN: <short summary>")`
   at the top of the affected test body. Match the target list to the
   "Targets affected" row of the gap entry.
4. Run the test locally to confirm it reports `XFAIL` (not `FAILED`)
   before committing. `pytest tests/protocol_compliance -k <test> -v`
   should show an `x` / `XFAIL`. Commit only once it's green at the
   suite level.

### Keeping the gap entry and the `xfail` marker in sync

If the gap's scope, symptoms, or related issues change — e.g. a fix
narrows it to one transport, or a new tracking issue supersedes the
cited blocker — update **both** the gap entry below **and** the
`reason="…"` string in the test. The reason string is what shows up in
pytest output, so it should read well on its own as a breadcrumb to
the gap entry and should be accurate about which stream (standalone
vs. POST-correlated) the failing capability would travel on. See the
"Stream-attribution note" section above before citing #4205.

### Closing a gap (fully or partially)

- **Full closure** — every cell listed under the gap now passes. Delete
  the `xfail_on` line in the test and move the entry to "Closed gaps"
  with the fixing PR / commit SHA. pytest's next run will confirm with a
  plain pass.
- **Partial closure** — a fix covers some targets but not others (e.g.
  `gateway_proxy` passes, `gateway_virtual` still fails). **Do not
  delete** the `xfail_on` call. Narrow its target list to only the
  still-broken cells, update the "Targets affected" row of the gap entry
  to match, and add a dated note describing what closed and what's still
  open. This keeps the gap entry accurate and prevents `XPASS` noise on
  the newly-passing cells from re-opening the fail.

When pytest reports `XPASS` unexpectedly (a cell marked xfail now
passes), treat it as a signal the gap is closing on that cell. Update
the marker and the entry per the rules above.

## Open gaps

---

### GAP-001 — Server-initiated log notifications not delivered

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_logging.py::test_log_message_reaches_client`; secondary blocker for `test_notifications.py::test_tools_list_changed_notification_delivered` and `::test_resources_list_changed_notification_delivered` (primary GAP-008) |
| **Spec** | [MCP 2025-11-25 — server `logging` capability](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/logging) |

**Observed**: when an upstream tool calls `ctx.log(...)` during a tool
invocation, the gateway accepts the upstream's `notifications/message`
but does not relay it to the downstream client. The client's
`log_handler` is never invoked.

**Expected**: the spec requires the server to emit `notifications/message`
to clients that subscribed via `logging/setLevel`. Federation should
forward upstream-emitted log messages.

**Why**: the log emitted during a tool call is a request-tied
notification — it SHOULD ride the POST-correlated stream for that call.
The gateway isn't relaying notifications on that stream. (Logs emitted
*between* calls — e.g. in response to a `logging/setLevel` change —
would ride the standalone stream, which #4205 also closes, but the
test exercises the in-call path.)

---

### GAP-002 — Progress notifications not delivered

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_utilities.py::test_progress_notifications_delivered`; secondary blocker for `test_notifications.py::test_tools_list_changed_notification_delivered` and `::test_resources_list_changed_notification_delivered` (primary GAP-008) |
| **Spec** | [MCP 2025-11-25 — `progress` notifications](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress) |

**Observed**: a tool calling `ctx.report_progress(...)` returns successfully,
but the client's `progress_handler` is never invoked.

**Expected**: with a `progressToken` on the request, the server must emit
`notifications/progress` events the client can observe.

**Why**: progress notifications are request-tied (the `progressToken`
is scoped to one client request) and ride the POST-correlated stream
of that request. Root cause is the gateway not relaying notifications
on the POST-correlated stream — **not** #4205, which only closes the
standalone GET stream that progress wouldn't have used anyway.

---

### GAP-003 — Client roots not forwarded to upstream

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_roots.py::test_roots_echo_receives_client_roots` |
| **Spec** | [MCP 2025-11-25 — `roots` capability](https://modelcontextprotocol.io/specification/2025-11-25/client/roots) |

**Observed**: an upstream tool calling `ctx.list_roots()` receives an empty
list even when the downstream client advertised roots in initialize.

**Expected**: the gateway should propagate the downstream client's
`capabilities.roots` and `roots/list` responses to upstream sessions
that ask. Without this, server-initiated roots queries can't see what
the actual user-facing client offered.

**Why**: `roots/list` is a server→client *request* — spec (basic/
transports § Listening for Messages from the Server) says it MUST NOT
be sent on the standalone stream, so it has to travel on the
POST-correlated stream of the originating client call. Gateway does
not broker server→client requests on that stream. Independent of
#4205.

---

### GAP-004 — Server-initiated sampling/createMessage not relayed

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_sampling.py::test_sample_trigger_invokes_client_handler`, `test_sampling_depth.py::test_sample_with_max_tokens_parameter` |
| **Spec** | [MCP 2025-11-25 — `sampling` capability](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling) |

**Observed**: an upstream tool calling `ctx.sample(...)` errors or returns
an empty response. The downstream client's `sampling_handler` is never
invoked.

**Expected**: gateway brokers `sampling/createMessage` end-to-end —
upstream → gateway → client, and back. The client's sampling handler
should produce the response.

**Why**: `sampling/createMessage` is a server→client *request* — per
spec MUST NOT be on the standalone stream. Must be brokered on the
POST-correlated stream of the originating tool call, and needs
per-client session correlation because the gateway may have multiple
downstream clients. Independent of #4205.

---

### GAP-005 — Server-initiated elicitation/create not relayed

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_elicitation.py::test_elicit_trigger_invokes_client_handler`, `test_elicitation_depth.py::test_elicit_numeric_schema_roundtrip` |
| **Spec** | [MCP 2025-11-25 — `elicitation` capability](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation) |

**Observed**: same shape as GAP-004 — upstream calls `ctx.elicit(...)`,
client `elicitation_handler` never sees the request.

**Expected**: gateway forwards `elicitation/create` to the right client and
returns the client's response to the upstream.

**Why**: `elicitation/create` is a server→client *request* — same
stream-attribution story as GAP-004: MUST travel on the POST-correlated
stream, not the standalone stream. Independent of #4205.

---

### GAP-006 — Prompts not federated through gateway

| | |
|---|---|
| **Targets affected** | `gateway_proxy` (also `gateway_virtual` to confirm) |
| **Tests** | `test_prompts.py::test_prompt_listed`, `::test_prompt_renders_argument`, `test_drift.py::test_drift_prompt_names`, `test_notifications.py::test_prompts_list_changed_notification_delivered` (co-blocked with GAP-008) |
| **Spec** | [MCP 2025-11-25 — server `prompts` capability](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts) |

**Observed**: the reference server registers a `greet` prompt; after
gateway federation, `client.list_prompts()` against the gateway returns
no entries that match.

**Expected**: gateway should federate upstream prompts the same way it
federates tools — names slug-prefixed, arguments preserved, `prompts/get`
brokered.

**Why**: gateway currently federates tools (and possibly resources) but
not prompts. Implementation gap rather than a session-channel
limitation. Independent of #4205.

---

### GAP-008 — Gateway federation drops a subset of upstream tools

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_drift.py::test_drift_tool_names`, `test_tools.py::test_tool_error_is_surfaced_as_is_error`, `test_utilities.py::test_long_running_tool_is_cancellable`, `::test_cancellation_notification_reaches_server`, `test_notifications.py::test_tools_list_changed_notification_delivered`, `::test_resources_list_changed_notification_delivered`, `::test_prompts_list_changed_notification_delivered` (co-blocked with GAP-006), `::test_resources_updated_after_bump` (co-blocked with GAP-009) |
| **Spec** | [MCP 2025-11-25 — server `tools` capability](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) |

**Observed**: the reference server registers 136 tools (16 named tools —
`echo`, `add`, `boom`, `progress_reporter`, `long_running`,
`get_cancellation_count`, `mutate_tool_list`, `mutate_resource_list`,
`mutate_prompt_list`, `bump_subscribable`, `roots_echo`,
`sample_trigger`, `sample_trigger_with_params`, `elicit_trigger`,
`elicit_trigger_numeric`, `log_at_level` — plus 120 `stub_NNN`
pagination stubs). Several of the named tools are missing after gateway
federation (specifically the no-arg / raising / long-sleep variants —
`boom`, `bump_subscribable`, `mutate_tool_list`, `long_running` have
been observed dropped; exact current set varies and should be re-probed
when this gap is investigated).

**Expected**: the gateway should federate every tool the upstream
advertises, provided it passes the gateway's validator layer. If a tool
is intentionally rejected (e.g. missing input schema), the rejection
should be observable (log, diagnostic endpoint) so operators can spot it.

**Why**: unclear. Not obviously a common property — the dropped tools
don't all lack args (e.g. `long_running` takes `duration_seconds`). The
dropped `boom` tool has no args AND raises; possibly the gateway
validates return types or rejects tools without output schemas.
Investigation needed to confirm whether this is intentional filtering
or a silent federation bug.

**How to close**: confirm root cause, either (a) fix federation to
propagate all well-formed tools, or (b) document the filter rule
explicitly so the reference server can sidestep it in the stubs it
uses to exercise federation. Once federation covers the missing tools,
re-probe every test in the "Tests" row and drop or narrow the
`xfail_on` call individually as each passes. Tests that depend on a
dropped tool AND a separate gap (e.g. `test_resources_updated_after_bump`
needs GAP-009's resource federation too, and
`test_tools_list_changed_notification_delivered` needs the
POST-correlated notification relay tracked by GAP-001/002) will
remain xfailed against the surviving gap after GAP-008 closes.

---

### GAP-009 — Resources / resource templates federated incompletely

| | |
|---|---|
| **Targets affected** | `gateway_virtual` (static + templates still missing) |
| **Tests** | `test_resources.py::test_static_resource_listed_and_readable`, `::test_templated_resource_registered_and_resolves`, `test_drift.py::test_drift_resource_uris`, `test_notifications.py::test_resources_updated_after_bump` (co-blocked with GAP-008) |
| **Spec** | [MCP 2025-11-25 — server `resources` capability](https://modelcontextprotocol.io/specification/2025-11-25/server/resources) |

**Scope history**:
- **2026-04-18** — partial closure. `gateway_proxy` now federates resource
  templates correctly (matrix-run XPASS on
  `test_templated_resource_registered_and_resolves[gateway_proxy-http]`).
  xfail narrowed from `(gateway_proxy, gateway_virtual)` → `(gateway_virtual,)`.

**Observed (remaining)**:
- On `gateway_virtual`, `resources/list` is empty — virtual-server
  composition did not pick up the upstream's resources at all. Only
  tools were composed. Both static and templated resources are missing
  on this path.

**Expected**: virtual-server composition should surface upstream resources
and resource templates identically to how it surfaces tools (modulo URI
namespacing, if any).

**How to close**: extend virtual-server composition (POST /servers
payload handling) to accept associated resources + prompts in the same
way it accepts tools today. Once `gateway_virtual` advertises the
reference server's `reference://static/greeting` and the
`reference://users/{user_id}` template, remove the remaining
`xfail_on(request, "gateway_virtual", ...)` calls on the two
`test_resources.py` tests and close this gap.

---

### GAP-010 — Reverse-proxy doesn't follow runtime-mode flips

| | |
|---|---|
| **Targets affected** | any deployment with nginx (or equivalent) in front of the gateway |
| **Tests** | `test_runtime_mode.py::test_data_plane_runtime_header_under_shadow` |
| **Spec / docs** | [rust-mcp-runtime.md § "Reverse-proxy deployments — important caveat"](../../docs/docs/architecture/rust-mcp-runtime.md) |
| **Related** | [#4273](https://github.com/IBM/mcp-context-forge/issues/4273) (parent runtime-mode feature); the rust-mcp-runtime docs reference an OpenResty-style tracking issue for dynamic routing |

**Observed**: under the bundled docker-compose topology (nginx fronting
one or more gateway pods) with boot_mode=edge:
- `PATCH /admin/runtime/mcp-mode {"mode":"shadow"}` succeeds; admin plane
  reports `effective_mode=shadow`, `mounted=python`.
- A subsequent MCP `initialize` POST to the public ingress returns
  `x-contextforge-mcp-runtime: rust` regardless — 41/41 requests in a
  sustained probe.
- Bypassing nginx (`docker exec … curl :4444/mcp/`) does return
  `x-contextforge-mcp-runtime: python` after the shadow flip, proving
  the Python gateway's dispatch correctly honors the override.

**Expected**: after a successful runtime flip, the public-ingress data
plane serves requests through the newly-mounted transport.

**Why**: nginx's `/mcp` location block is generated at container boot
from `RUST_MCP_MODE` and routes directly to the Rust listener under
`edge`/`full`. Nginx has no mechanism today to re-read the effective
mode after a runtime flip. This is the "observable but not
behavior-changing" caveat documented in the architecture page.

**How to close**: land the dynamic-routing piece tracked in the
rust-mcp-runtime docs (OpenResty / shared-store config), or
structure the harness to run in a single-pod / no-proxy topology where
FastAPI is the sole public ingress. When nginx follows the flip,
remove the xfail on
`test_data_plane_runtime_header_under_shadow`; the XPASS will
confirm the fix.

---

### GAP-011 — Subscription updates (`notifications/resources/updated`) not relayed

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_subscriptions.py::test_resources_updated_notification_delivered_to_subscriber` |
| **Spec** | [MCP 2025-11-25 — server `resources` subscription](https://modelcontextprotocol.io/specification/2025-11-25/server/resources#subscriptions) |
| **Related** | [#4205](https://github.com/IBM/mcp-context-forge/issues/4205) — standalone `GET /mcp/` stream returns 405 |

**Observed**: after a subscribing client calls `resources/subscribe`, a
subsequent server-side mutation (`bump_subscribable`) correctly fires
`notifications/resources/updated` on the reference target but the client
never receives it through either gateway target.

**Expected**: subscribers should receive the notification on the same
session that opened the subscription.

**Why**: `notifications/resources/updated` for subscribed resources is
not tied to any specific client request — per spec it rides the
standalone stream (`GET /mcp/`). The gateway currently closes that
stream with 405 (see #4205), so the notification has no channel to
the client. Unlike the other server→client gaps (GAP-001/002/003/004/
005), this one is genuinely about the standalone stream and #4205 is
the correct blocker.

**How to close**: once #4205 lands server→client relay, the test will
XPASS. Remove `xfail_on` and move this entry to the closed section.

---

### GAP-012 — Unknown JSON-RPC method returns -32000 instead of -32601

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_jsonrpc_envelope.py::test_method_not_found_returns_32601` |
| **Spec** | [JSON-RPC 2.0 § 5.1 reserved error codes](https://www.jsonrpc.org/specification#error_object), referenced by MCP 2025-11-25 base protocol |

**Observed**: POSTing a JSON-RPC request with an unknown `method` to the
gateway yields an error envelope with `code: -32000` and
`message: "Invalid method"`.

**Expected**: JSON-RPC 2.0 reserves `-32601 Method not found` specifically
for this failure mode. `-32000..-32099` is a range for
*implementation-defined* server errors; using it for method-not-found
loses the interoperable distinction the spec defines. A client with
routing logic that branches on `code == -32601` (e.g. "try a different
server") can't work against this gateway.

**Why**: likely a generic error-path fallthrough in the gateway's
method-dispatch layer rather than a deliberate design choice.

**How to close**: map the method-not-found path in the gateway's JSON-RPC
handler to `-32601`. The same dispatch point should also emit `-32602
Invalid params` when arguments fail schema validation on a recognized
method. Once fixed, remove the `xfail_on` from this test.

---

### GAP-013 — Id-less JSON-RPC messages treated as requests instead of notifications

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_jsonrpc_envelope.py::test_request_without_id_is_rejected_or_treated_as_notification` |
| **Spec** | [JSON-RPC 2.0 § 4.1 Notification](https://www.jsonrpc.org/specification#notification), referenced by MCP 2025-11-25 base protocol (REQ-007, REQ-008) |
| **Related** | [#4438](https://github.com/IBM/mcp-context-forge/issues/4438) |

**Observed**: POSTing a JSON-RPC message without an `id` field (e.g.
`{"jsonrpc":"2.0","method":"ping","params":{}}`) returns a successful
result envelope with a server-fabricated UUID as the `id`:

```json
{"jsonrpc": "2.0", "result": {}, "id": "5baca3f1-a093-40f2-b76f-cb4e1afb0c29"}
```

**Expected**: JSON-RPC 2.0 § 4.1 defines a message without `id` as a
*Notification* — "the Server MUST NOT reply to a Notification." The
server should either reject the message (HTTP 4xx) or accept it as a
notification (HTTP 202 Accepted with no id-bearing body).

**Why**: the gateway's MCP handler (`main.py:10201-10202`) unconditionally
auto-generates a UUID when `req_id is None`, then processes the message
as a normal request. This erases the JSON-RPC distinction between
requests and notifications.

**How to close**: guard the `req_id is None` → `uuid4()` fallback so it
only fires for messages that already have an `id` field set to a
non-None value (i.e. the field is present but needs normalization).
Messages with no `id` at all should be dispatched as notifications
(return 202, no response envelope). Once fixed, drop the `@pytest.mark.xfail`
on this test.

---

## Closed gaps

### GAP-007 — `tools/list` pagination cap below upstream tool count *(closed 2026-04-18)*

**Was**: reference server registered 120 `stub_NNN` tools; through the
gateway, fewer than 120 were visible to a client that exhausted
pagination.

**How we learned it closed**: after flipping xfail markers from
imperative `pytest.xfail()` to decorator-based
`@pytest.mark.xfail(strict=False)` with the XPASS sidecar hook, the
compliance matrix run surfaced XPASS on
`test_pagination.py::test_list_tools_returns_all_stubs[gateway_proxy-http]`
across both python and rust_edge engines. Independent isolated run
confirmed plain pass on every target (reference, gateway_proxy,
gateway_virtual). The `xfail_on(...)` call was removed from the test and
this entry moved here.

**Origin commit**: unknown — detected after the harness's XPASS mechanism
was wired up. The fix predates the detection.
