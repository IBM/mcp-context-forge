# Tool Invocation & Output-Schema Validation

ContextForge invokes tools across several very different backends — federated MCP peers, REST endpoints, OpenAPI-discovered services, A2A agents, and admin-registered tools — and in all cases exposes the result back to downstream MCP clients. Every one of those paths has at least one output-schema validation layer, and some have three. This document catalogues them end-to-end so contributors can reason about the full lifecycle of a tool call, the invariants at each hop, and where the MCP spec's "skip validation for error responses" rule takes effect.

> **Why this matters:** ContextForge issue [#4202] surfaced a class of bug where error responses from a tool with a declared `outputSchema` were silently replaced with validation-error payloads at more than one layer in the pipeline. Fixing it required coordinated changes across the ingress validator, the transport handler's egress shape, and an upstream-fixture description filter. Keeping the flow documented prevents re-introductions.

[#4202]: https://github.com/IBM/mcp-context-forge/issues/4202

## High-level flow

```
 Downstream MCP client (e.g. mcp-cli via mcpgateway.wrapper)
                   │  tools/call (JSON-RPC)
                   ▼
 ┌──────────────────────────────────────────────────────────┐
 │ Gateway — MCP Python SERVER SDK                          │
 │   streamablehttp_transport.py::call_tool                 │
 │   (dispatches based on Tool.integration_type)            │
 └──────────────────────────────────────────────────────────┘
         │                                 │
         │ integration_type == "MCP"       │ integration_type in {"REST","OPENAPI","A2A",...}
         ▼                                 ▼
 ┌───────────────────────┐         ┌────────────────────────────┐
 │ mcp.ClientSession     │         │ HTTP client (httpx)        │
 │ federation call to    │         │ REST-style invocation      │
 │ upstream MCP server   │         │                            │
 └───────────────────────┘         └────────────────────────────┘
         │                                 │
         │ upstream CallToolResult         │ upstream HTTP response
         ▼                                 ▼
 ┌────────────────────────────────┐ ┌────────────────────────────────┐
 │ Validator A                    │ │ _coerce_to_tool_result │
 │ ClientSession._validate_tool_  │ │ → ToolResult                   │
 │ result (MCP CLIENT SDK)        │ └────────────────────────────────┘
 │ Skips when isError=true.       │         │
 │ Raises RuntimeError otherwise. │         ▼
 └────────────────────────────────┘ ┌────────────────────────────────┐
         │                          │ Validator B                    │
         │ (federation path         │ ToolService._extract_and_      │
         │  does NOT invoke         │ validate_structured_content    │
         │  Validator B)            │ Skips when is_error=true       │
         │                          │ (#4202 ingress fix).           │
         │                          └────────────────────────────────┘
         └──────────────┬────────────────────┘
                        ▼
        ToolResult (content[, structured_content][, is_error])
                        │
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ streamablehttp_transport.py::call_tool — egress shape    │
 │   if is_error: return types.CallToolResult(...)          │
 │   else:        return (unstructured, structured) or list │
 └──────────────────────────────────────────────────────────┘
                        │
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ Validator C                                              │
 │ MCP Python SERVER SDK (outbound)                         │
 │ mcp.server.lowlevel.server (isinstance short-circuit)    │
 │ • CallToolResult → short-circuits (no validation)        │
 │ • list/tuple     → validates against gateway's own       │
 │                    advertised outputSchema               │
 └──────────────────────────────────────────────────────────┘
                        │
                        ▼
 Downstream MCP client receives the response
```

## The three validation layers

### Validator A — MCP client SDK (federation ingress)

**Where:** `ClientSession._validate_tool_result` in the installed `mcp` client SDK.

**When:** Gateway calls a federated MCP peer via `mcp.ClientSession`. Runs before the response returns from `ToolService.invoke_tool`.

**Rule:**

- If `result.isError` is truthy → **skip**. This is the spec rule codified by the MCP project itself ([Error Handling][spec-error]).
- Else, if the tool advertised an `outputSchema` but `result.structuredContent` is `None` → raise `RuntimeError("Tool X has an output schema but did not return structured content")`.
- Else, validate `structuredContent` against the *upstream-advertised* schema with `jsonschema.validate`.

**Failure mode:** Raises `RuntimeError`; caught in `tool_service.py::invoke_tool` and re-wrapped as `Tool invocation failed: …` text. **The gateway never sees a malformed MCP-federated response** — the client SDK acts as the trust boundary for the upstream.

### Validator B — `ToolService._extract_and_validate_structured_content`

**Where:** `mcpgateway/services/tool_service.py`.

**When:** Invoked explicitly and exclusively from the **REST** branch of `invoke_tool`. The MCP federation branch does **not** call it — Validator A is considered authoritative for federated peers. The **A2A branch does not call it either today** — that's a known gap; see "Known gaps and follow-ups" below.

**Rule:**

| Condition | Outcome |
|---|---|
| `is_error` or `isError` truthy | **Skip** (`return True`). The #4202 fix. |
| `tool.output_schema` missing or empty | Skip (`return True`). |
| `structured_content` set but not a JSON object | Fast-fail with a structured `invalid_structured_content_type` error. |
| `structured_content` absent → best-effort promote first parseable `TextContent` item | Parses both raw dicts and Pydantic `TextContent` (needed since `_coerce_to_tool_result` produces the latter for REST responses). |
| No structured payload obtainable + `is_error=False` + schema declared | Currently `return True` — known **spec deviation** tracked in [#4208]. |
| `jsonschema.validate` raises | Replace `tool_result.content` with a validation-error TextContent, set `is_error=True`, `return False`. |

**Failure mode:** In-place mutation of the passed `ToolResult`.

### Validator C — MCP server SDK (downstream egress)

**Where:** The `call_tool` dispatch in the installed `mcp` server-framework (`mcp.server.lowlevel.server` — look for the `isinstance(results, types.CallToolResult)` short-circuit).

**When:** Runs for every `tools/call` the gateway serves. Receives whatever `streamablehttp_transport.py::call_tool` returns.

**Rule:**

| Handler return shape | SDK behaviour |
|---|---|
| `types.CallToolResult(...)` | **Short-circuit** — returned verbatim to the downstream client. Used for error responses to preserve the upstream error text intact (#4202 egress fix). |
| `list[Content]` (no structured) | Treats as unstructured-only. If tool has `outputSchema` ⇒ replaces payload with `Output validation error: outputSchema defined but no structured output returned`. |
| `tuple(list[Content], dict)` | Validates the dict against the gateway's `outputSchema`; on failure, synthesises `Output validation error: …`. |
| `dict` | Treats as structured-only (unstructured is JSON-dumped). |

**Failure mode:** Replaces the entire tool result with a synthesised error envelope. This is what #4202 was ultimately about on the outbound side — without the `CallToolResult` short-circuit, the server SDK re-clobbered error responses the ingress had just preserved.

## Spec references

- MCP 2025-11-25 **Error Handling**: <https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling>
  - "Error responses do not require structured content."
- MCP 2025-11-25 **Output Schema**: <https://modelcontextprotocol.io/specification/2025-11-25/server/tools#output-schema>
  - "If an output schema is provided: Servers MUST provide structured results that conform to this schema."

[spec-error]: https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling
[spec-output]: https://modelcontextprotocol.io/specification/2025-11-25/server/tools#output-schema

## Per-path summary

`DbTool.integration_type` is the primary discriminator at invocation time and is one of three literal values: `"MCP"`, `"REST"`, or `"A2A"` (see `mcpgateway/schemas.py::ToolCreate.integration_type`). The `invoke_tool` branches in `tool_service.py` fan out on this field — grep for `if tool_integration_type == "REST":` / `elif tool_integration_type == "MCP":` / `elif tool_integration_type == "A2A"` to land on each.

> **OpenAPI is not a separate class.** There is no `"OPENAPI"` integration type. The OpenAPI importer in `mcpgateway/services/openapi_service.py` compiles each operation down into a `"REST"` tool at registration time — populating `base_url`, `path_template`, `query_mapping`, `header_mapping`, etc. on the resulting `DbTool`. At invocation time an OpenAPI-imported tool is indistinguishable from a hand-registered REST tool and takes the REST branch of `invoke_tool`. Treat the `"REST"` rows below as covering both hand-registered REST endpoints *and* OpenAPI-discovered ones.

| Backend (`integration_type`) | Invocation branch | Validator A (MCP client SDK) | Validator B (`_extract_and_validate_structured_content`) | Validator C (MCP server SDK) |
|---|---|---|---|---|
| **MCP federation, success** | `elif tool_integration_type == "MCP":` (via `mcp.ClientSession`) | ✅ runs against upstream's advertised schema | — not invoked (Validator A is authoritative) | ✅ runs against gateway's advertised schema |
| **MCP federation, `isError=true`** | same | skipped per MCP spec "Error Handling" | — not invoked | skipped via `CallToolResult` short-circuit (#4202 egress) |
| **REST (incl. OpenAPI-imported), success** | `if tool_integration_type == "REST":` (via `httpx`) | — n/a (no federated client) | ✅ runs | ✅ runs |
| **REST (incl. OpenAPI-imported), `isError=true`** | same | — n/a | skipped per MCP spec (#4202 ingress fix) | skipped via `CallToolResult` short-circuit |
| **REST (incl. OpenAPI-imported), success but no structured payload** | same | — n/a | ⚠️ currently lenient (returns `True`) — tracked in [#4208] | ✅ runs (may reject) |
| **A2A agent, success** | `elif tool_integration_type == "A2A"` (via A2A service) | — n/a (no MCP client SDK on this path) | ⚠️ **not invoked today** — Validator B gap | ✅ runs |
| **A2A agent, `isError=true`** | same | — n/a | ⚠️ **not invoked today** (but moot — no schema enforcement to skip) | skipped via `CallToolResult` short-circuit |
| **A2A agent, success but no structured payload** | same | — n/a | ⚠️ **not invoked today** | ✅ runs (may reject if Validator C sees outputSchema) |

A2A tools do not currently route through Validator B. In practice this means gateway-side `output_schema` enforcement is absent for A2A — any validation on that path happens at Validator C only. Wiring A2A through a unified post-invoke pipeline (so REST and A2A really are symmetric) is scoped into the option-B refactor referenced in "Known gaps and follow-ups" below.

[#4207]: https://github.com/IBM/mcp-context-forge/issues/4207
[#4208]: https://github.com/IBM/mcp-context-forge/issues/4208

## Known gaps and follow-ups

- **[#4207] — e2e coverage for non-MCP paths.** REST (incl. OpenAPI-imported) tools have Validator B as their only gateway-side enforcement, and A2A has none (see the "option B" item below). Today those paths are covered by unit tests but not by `make test-mcp-cli` e2e tests.

- **[#4208] — success path with declared schema but empty output.** Validator B currently returns `True` when it cannot obtain any structured payload, even if an `outputSchema` is declared. The MCP spec says servers MUST provide conforming structured output in that case. Tightening requires deciding how to handle upstream servers that legitimately return empty success bodies (HTTP 204, REST tools without data shapes) — scoped out of #4202 because the blast radius is wider.

- **[#4210] — Option B: unify the tool-invocation pipeline around a canonical `ToolResult`.** Each `integration_type` currently builds `ToolResult` differently, and only REST currently routes through Validator B. The PR that closed #4202 landed a first structural step — a single `_coerce_to_tool_result` helper — but it is only wired into two of the four paths today: the REST branch and the MCP **direct-proxy** sub-branch. The MCP **non-direct-proxy** branch still builds its own `ToolResult` inline (via `tool_call_result.model_dump(by_alias=True)` + manual field extraction), and the A2A branch has its own bespoke construction as well. The remaining option-B work is the broader refactor that routes all four paths through the helper and a shared post-invoke pipeline: extract a `_post_invoke_pipeline` that owns plugins → Validator B → metrics, route A2A and the MCP non-direct-proxy branch through it, and promote the direct-proxy bypass from a mid-dispatch `if` into a first-class entry point with a documented contract. That refactor is the permanent fix for the #4202 class of divergent-shape bugs. See <https://github.com/IBM/mcp-context-forge/issues/4210>.

## Testing map

Unit tests:

- `tests/unit/mcpgateway/services/test_tool_service_coverage.py::TestExtractAndValidateErrorResponses` — Validator B skip-on-error and its positive/negative schema branches.
- `tests/unit/mcpgateway/services/test_tool_service_coverage.py::TestStructuredContentAdditional` — Validator B edge cases (non-dict structured content, malformed JSON in a text item, `orjson.dumps` fallback).
- `tests/unit/mcpgateway/services/test_tool_service_coverage.py::TestCoerceToToolResult` — canonical-shape coercion fed to Validator B (MCP SDK `CallToolResult` round-trip, REST-payload field-dropping guards, `_meta` preservation).
- `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py::test_call_tool_preserves_is_error_for_egress` — Validator C short-circuit, local (non-pooled) branch.
- `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py::test_call_tool_session_affinity_forwarded_preserves_is_error` — Validator C short-circuit, worker-forwarded branch.

End-to-end (via `make test-mcp-cli`):

- `tests/e2e/test_mcp_cli_protocol.py::TestMcpStdioProtocol::test_tools_call_schema_error_preserves_payload` — drives the full pipeline against the upstream Rust fixture `fast-test-schema-error`, asserts the original error text arrives at the downstream client untouched (all three validator layers verified in concert).
- `tests/e2e/test_mcp_cli_protocol.py::TestMcpStdioProtocol::test_tools_call_schema_success_validates_payload` — positive control against `fast-test-schema-success`, asserts `structuredContent` reaches the client when the payload satisfies the schema.

## Adding a new backend

When adding a new tool backend (e.g. gRPC, WebSocket stdio), keep the contract uniform:

1. Produce a `ToolResult` pydantic model from the upstream response (use `_coerce_to_tool_result` for anything non-MCP-shaped).
2. Decide whether the backend has its own authoritative validator (like Validator A for MCP). If so, you may skip Validator B; if not, call `_extract_and_validate_structured_content` before returning.
3. Ensure the egress path in `streamablehttp_transport.py::call_tool` returns a `CallToolResult` for error responses so Validator C doesn't re-clobber them.
4. Add regression tests at both layers — unit for the in-process validator(s), e2e for the full round-trip. A preflight `tools/list` guard like `_require_declared_output_schema` is worth replicating to give operators an actionable failure when the fixture stack is stale.
