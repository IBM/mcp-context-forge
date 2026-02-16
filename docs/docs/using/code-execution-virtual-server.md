# Using Code Execution Virtual Servers (MCP Code Mode)

This guide shows how to enable and use `code_execution` servers with `shell_exec` and `fs_browse`.

## 1) Enable Feature Flags

Set the core flag and optional controls in `.env`:

```bash
CODE_EXECUTION_ENABLED=true
CODE_EXECUTION_SHELL_EXEC_ENABLED=true
CODE_EXECUTION_FS_BROWSE_ENABLED=true
CODE_EXECUTION_REPLAY_ENABLED=true
```

Optional tuning is available through `CODE_EXECUTION_DEFAULT_*` settings.

See full config reference: [Configuration - Code Execution](../manage/configuration.md#code-execution-mcp-code-mode).

## 2) Create a `code_execution` Server

Create a server with `type=code_execution` and policies.

```bash
curl -s -X POST http://localhost:4444/servers \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "secure-code-lab",
    "description": "Sandboxed execution for analytics workflows",
    "type": "code_execution",
    "stub_language": "python",
    "mount_rules": {
      "include_tags": ["analytics"],
      "exclude_servers": ["admin-internal"]
    },
    "sandbox_policy": {
      "runtime": "python",
      "max_execution_time_ms": 30000,
      "max_memory_mb": 256,
      "max_cpu_percent": 50,
      "max_network_connections": 0,
      "max_file_size_mb": 10,
      "max_total_disk_mb": 100,
      "max_runs_per_minute": 20,
      "allow_raw_http": false
    },
    "tokenization": {
      "enabled": true,
      "types": ["email", "phone", "name"],
      "strategy": "bidirectional"
    },
    "skills_scope": "team:platform-eng",
    "skills_require_approval": true
  }'
```

## 3) Verify Meta-Tools

`code_execution` servers auto-expose synthetic tools.

```bash
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  http://localhost:4444/servers/<SERVER_ID>/tools | jq
```

Look for `shell_exec` and `fs_browse`.

## 4) Execute Code with `shell_exec`

Invoke through JSON-RPC (`/rpc`) with `tools/call`:

```bash
curl -s -X POST http://localhost:4444/rpc \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "server_id": "<SERVER_ID>",
      "name": "shell_exec",
      "arguments": {
        "language": "python",
        "code": "print(\"hello from sandbox\")",
        "timeout_ms": 10000
      }
    }
  }' | jq
```

Returned payload includes:

- `output`
- `error`
- `metrics`
- `tool_calls_made`
- `run_id`

## 5) Browse the Virtual Filesystem with `fs_browse`

```bash
curl -s -X POST http://localhost:4444/rpc \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "server_id": "<SERVER_ID>",
      "name": "fs_browse",
      "arguments": {
        "path": "/tools",
        "include_hidden": false,
        "max_entries": 100
      }
    }
  }' | jq
```

## 6) Skills Workflow (Optional)

Create reusable skills for the server:

```bash
curl -s -X POST http://localhost:4444/servers/<SERVER_ID>/skills \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "summarize_csv",
    "language": "python",
    "description": "Summarize CSV columns and basic stats",
    "source_code": "def run(csv_path):\n    return {\"path\": csv_path}"
  }' | jq
```

If `skills_require_approval=true`, review via:

- `GET /servers/<SERVER_ID>/skills/approvals`
- `POST /servers/<SERVER_ID>/skills/approvals/<APPROVAL_ID>/approve`
- `POST /servers/<SERVER_ID>/skills/approvals/<APPROVAL_ID>/reject`

## 7) Runs, Sessions, Security Events, Replay

- `GET /servers/<SERVER_ID>/code/runs`
- `GET /servers/<SERVER_ID>/code/sessions`
- `GET /servers/<SERVER_ID>/code/security-events`
- `POST /servers/<SERVER_ID>/code/runs/<RUN_ID>/replay`

Use these endpoints for debugging, audit review, and performance tuning.

## Admin UI Notes

In Admin UI create/edit server forms:

- choose `code_execution` type
- use **Insert editable JSON template** for `mount_rules`, `sandbox_policy`, and `tokenization`
- edit the inserted JSON directly before saving

## Common Errors

- `code_execution servers are disabled`: set `CODE_EXECUTION_ENABLED=true`
- `Deno runtime is not available on this host`: install/configure Deno or switch runtime/policy
- `Python runtime is not available on this host`: ensure Python runtime is available, or enable fallback
- `EACCES` errors: mount/sandbox policy blocked filesystem/tool/network operation
- `Rate limit exceeded`: increase `max_runs_per_minute` (or global default) if needed
