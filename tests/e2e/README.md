# tests/e2e/ — End-to-End Tests

End-to-end tests that exercise ContextForge across component boundaries,
often requiring running services.

## MCP Protocol Tests via mcp-cli

**File:** `test_mcp_cli_protocol.py`

Tests the MCP protocol through IBM's [mcp-cli](https://github.com/IBM/mcp-cli)
client and the `mcpgateway.wrapper` stdio bridge. No LLM provider or API key is
required — all operations are pure MCP protocol.

### Prerequisites

```bash
# Install mcp-cli
pip install "mcp-cli[cli]"

# Start ContextForge (docker-compose)
docker compose up -d          # gateway on :8080 via nginx
```

### Running

```bash
# Default — tests against http://localhost:8080
make test-mcp-cli

# Override gateway URL
MCP_CLI_BASE_URL=http://localhost:4444 make test-mcp-cli

# Run directly with pytest
pytest tests/e2e/test_mcp_cli_protocol.py -v
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_CLI_BASE_URL` | `http://localhost:8080` | Gateway URL (nginx proxy or direct) |
| `JWT_SECRET_KEY` | `my-test-key` | JWT signing secret (must match gateway) |
| `PLATFORM_ADMIN_EMAIL` | `admin@example.com` | Admin email for JWT token |
| `MCP_CLI_TOKEN_EXPIRY` | `60` | JWT token lifetime in minutes |
| `MCP_CLI_TIMEOUT` | `30` | Per-command timeout in seconds |
| `MCP_CLI_PYTHON` | `sys.executable` | Python binary for mcpgateway.wrapper |

### What's Tested (22 tests)

**Via mcp-cli (LLM-free commands):**

| Test | MCP Operation | Description |
|---|---|---|
| `test_ping` | `initialize` | Server connectivity |
| `test_servers_list` | server info | Server status table |
| `test_tools_list_raw` | `tools/list` | JSON array of tools |
| `test_tools_list_has_required_fields` | `tools/list` | name, description, parameters per tool |
| `test_tools_list_table_format` | `tools/list` | Formatted table rendering |
| `test_tools_include_gateway_tools` | `tools/list` | Gateway-prefixed tool discovery |
| `test_tools_schema_types` | `tools/list` | JSON Schema type validation |
| `test_resources_list` | `resources/list` | Resource discovery |
| `test_prompts_list` | `prompts/list` | Prompt discovery |

**Via raw JSON-RPC over mcpgateway.wrapper stdio:**

| Test | MCP Operation | Description |
|---|---|---|
| `test_initialize` | `initialize` | Protocol version, capabilities, server info |
| `test_tools_list_jsonrpc` | `tools/list` | Tool definitions with inputSchema |
| `test_tools_call_get_system_time` | `tools/call` | Invoke time tool, validate content response |
| `test_tools_call_echo` | `tools/call` | Echo tool round-trip |
| `test_tools_call_convert_time` | `tools/call` | Timezone conversion |
| `test_tools_call_get_stats` | `tools/call` | Server stats retrieval |
| `test_tools_call_nonexistent_tool` | `tools/call` | Error handling for missing tools |
| `test_resources_list_jsonrpc` | `resources/list` | Resource list via JSON-RPC |
| `test_prompts_list_jsonrpc` | `prompts/list` | Prompt list via JSON-RPC |
| `test_multiple_concurrent_requests` | mixed | 5 requests in one session |
| `test_invalid_method` | invalid | Error response for unknown method |
| `test_all_discovery_methods` | mixed | All 3 discovery operations |
| `test_server_capabilities` | `initialize` | tools/resources/prompts capabilities |

### Architecture

```
pytest
  ├── mcp-cli commands (ping, tools, resources, prompts, servers)
  │     └── spawns mcpgateway.wrapper via server_config.json
  │           └── HTTP → ContextForge gateway (MCP_CLI_BASE_URL)
  │
  └── direct JSON-RPC via Popen → mcpgateway.wrapper (stdio)
        └── HTTP → ContextForge gateway (MCP_CLI_BASE_URL)
```

The wrapper's async design cancels in-flight requests when stdin closes (EOF
triggers shutdown). The test harness uses `Popen` with a settle delay before
closing stdin, allowing responses to arrive before graceful shutdown.

### mcp-cli Limitations (v0.16)

- **`cmd --tool` is broken** — the `cmd` subcommand is registered as a Typer
  command but not in the unified command registry, so `cli_execute("cmd", ...)`
  returns "Unknown command". Direct tool invocation via mcp-cli is not possible.
- **`--raw` output includes a banner** — mcp-cli prints its startup banner to
  stdout even with `--raw`. The tests use `_extract_json_from_output()` to strip
  non-JSON lines.
- **No `--no-model` flag** — mcp-cli always resolves a provider/model pair, but
  the LLM-free commands (`ping`, `tools`, `resources`, `prompts`, `servers`)
  never actually connect to an LLM.
