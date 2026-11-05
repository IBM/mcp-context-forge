# compliance-reference-server

A deliberately minimal, fully MCP-compliant reference server built on
[FastMCP](https://github.com/jlowin/fastmcp). It exists as the known-good
"ground truth" target for the ContextForge MCP protocol compliance test
harness (`tests/live_gateway/protocol_compliance/`).

## Scope

Phase 4b covers the MCP 2025-11-25 server- and client-initiated surface the
harness asserts against:

- **Tools**
  - Core: `echo`, `add`, `boom` (raises, for error-path assertions)
  - Utilities: `progress_reporter` (emits progress notifications),
    `long_running` (sleeps; exercises cancellation)
  - Notifications: `mutate_tool_list` (fires `tools/list_changed`),
    `bump_subscribable` (fires `resources/updated`)
  - Client-initiated: `roots_echo`, `sample_trigger`, `elicit_trigger`
  - Logging: `log_at_level`
  - Pagination: 120 `stub_NNN` stubs
- **Resources**: static greeting, templated `reference://users/{user_id}`,
  subscribable `reference://mutable/counter`
- **Prompts**: `greet` (takes a `name` argument)

Completions are not implemented — FastMCP 2.x at the version pinned here
does not expose a `@mcp.completion` decorator. Either raise it to a later
FastMCP that does, or add via the lower-level MCP Server API.

## Transports

Selectable via `--transport`:

| Flag | Transport |
|------|-----------|
| `stdio` (default) | stdio framing |
| `sse` | Server-Sent Events |
| `http` | Streamable HTTP |

```bash
compliance-reference-server --transport stdio
compliance-reference-server --transport sse  --host 127.0.0.1 --port 9100
compliance-reference-server --transport http --host 127.0.0.1 --port 9100
```

## Development

```bash
make dev-install
make test
```
