# MCP Compliance Gaps

A running tally of MCP 2025-11-25 spec gaps and behavioral divergences
surfaced by this harness. Entries describe observed vs. expected behavior,
link to the relevant spec section and tracking issues, and name the test(s)
marked `xfail` for the gap.

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
narrows it to one transport, or a new tracking issue supersedes #4205 —
update **both** the gap entry below **and** the `reason="…"` string in the
test. The reason string is what shows up in pytest output, so it should
read well on its own as a breadcrumb to the gap entry (e.g.
``"GAP-004: gateway does not relay server-initiated sampling (see #4205)"``).

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
| **Tests** | `test_logging.py::test_log_message_reaches_client` |
| **Spec** | [MCP 2025-11-25 — server `logging` capability](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/logging) |
| **Related** | [#4205](https://github.com/IBM/mcp-context-forge/issues/4205) — same root cause |

**Observed**: when an upstream tool calls `ctx.log(...)`, the gateway accepts
the upstream's `notifications/message` but does not relay it to the
downstream client. The client's `log_handler` is never invoked.

**Expected**: the spec requires the server to emit `notifications/message`
to clients that subscribed via `logging/setLevel`. Federation should
forward upstream-emitted log messages.

**Why**: server→client notifications need a long-lived SSE channel
(`GET /mcp/`). The gateway currently returns 405 there (a spec-clean
stopgap), which closes off the only delivery channel for this capability.

---

### GAP-002 — Progress notifications not delivered

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_utilities.py::test_progress_notifications_delivered` |
| **Spec** | [MCP 2025-11-25 — `progress` notifications](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress) |
| **Related** | [#4205](https://github.com/IBM/mcp-context-forge/issues/4205) |

**Observed**: a tool calling `ctx.report_progress(...)` returns successfully,
but the client's `progress_handler` is never invoked.

**Expected**: with a `progressToken` on the request, the server must emit
`notifications/progress` events the client can observe.

**Why**: same root cause as GAP-001 — no GET SSE channel.

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

**Why**: roots forwarding requires a server→client request channel for
`roots/list` (issued from upstream's perspective, brokered by the
gateway). Same dependency as GAP-001/002.

---

### GAP-004 — Server-initiated sampling/createMessage not relayed

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_sampling.py::test_sample_trigger_invokes_client_handler` |
| **Spec** | [MCP 2025-11-25 — `sampling` capability](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling) |
| **Related** | [#4205](https://github.com/IBM/mcp-context-forge/issues/4205) |

**Observed**: an upstream tool calling `ctx.sample(...)` errors or returns
an empty response. The downstream client's `sampling_handler` is never
invoked.

**Expected**: gateway brokers `sampling/createMessage` end-to-end —
upstream → gateway → client, and back. The client's sampling handler
should produce the response.

**Why**: same as above — server→client requests need the GET SSE channel
plus per-client session correlation.

---

### GAP-005 — Server-initiated elicitation/create not relayed

| | |
|---|---|
| **Targets affected** | `gateway_proxy`, `gateway_virtual` |
| **Tests** | `test_elicitation.py::test_elicit_trigger_invokes_client_handler` |
| **Spec** | [MCP 2025-11-25 — `elicitation` capability](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation) |
| **Related** | [#4205](https://github.com/IBM/mcp-context-forge/issues/4205) |

**Observed**: same shape as GAP-004 — upstream calls `ctx.elicit(...)`,
client `elicitation_handler` never sees the request.

**Expected**: gateway forwards `elicitation/create` to the right client and
returns the client's response to the upstream.

**Why**: same root cause.

---

### GAP-006 — Prompts not federated through gateway

| | |
|---|---|
| **Targets affected** | `gateway_proxy` (also `gateway_virtual` to confirm) |
| **Tests** | `test_prompts.py::test_prompt_listed`, `::test_prompt_renders_argument` |
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
| **Tests** | `test_drift.py::test_drift_tool_names`, `test_tools.py::test_tool_error_is_surfaced_as_is_error`, `test_utilities.py::test_long_running_tool_is_cancellable`, `test_notifications.py::test_tools_list_changed_via_mutator`, `test_notifications.py::test_resources_updated_after_bump` |
| **Spec** | [MCP 2025-11-25 — server `tools` capability](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) |

**Observed**: the reference server registers 131 tools (including `echo`,
`add`, `boom`, `bump_subscribable`, `mutate_tool_list`, `long_running`,
`progress_reporter`, `log_at_level`, `roots_echo`, `sample_trigger`,
`elicit_trigger`, and 120 `stub_NNN` pagination stubs). After gateway
federation, `compliance-reference-*` only covers 127 of them. Specifically
missing on the gateway side: `boom`, `bump_subscribable`, `mutate_tool_list`,
`long_running`.

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
explicitly so the reference server can sidestep it in the stubs it uses
to exercise federation. Once federation covers the 4 missing tools,
remove the xfail on `test_drift.py::test_drift_tool_names`.

---

### GAP-009 — Resources / resource templates federated incompletely

| | |
|---|---|
| **Targets affected** | `gateway_virtual` (static + templates still missing) |
| **Tests** | `test_resources.py::test_static_resource_listed_and_readable`, `::test_templated_resource_registered_and_resolves` |
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
