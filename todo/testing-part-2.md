# Testing Part 2 - Coverage Follow-up

## Current coverage snapshot
- Line coverage (coverage.xml): 35,720 / 48,444 = 73.73%
- HTML summary (docs/docs/coverage/index.html): 70%
- Last full run used: `make coverage`

## How to run coverage
- Full run (slow, two pytest passes + doctests):
  - `make coverage`
- HTML only (requires existing .coverage):
  - `make htmlcov`

## Quick targeted runs
- JSON-RPC branches in main:
  - `pytest tests/unit/mcpgateway/test_main.py -k "rpc_"`
- Admin UI flows:
  - `pytest tests/unit/mcpgateway/test_admin_module.py -k "join_request or leave_team"`
- Existing suggestions from prior strategy:
  - `pytest tests/unit/mcpgateway/test_main_extended.py -k "error or auth or rpc"`
  - `pytest tests/unit/mcpgateway/services/test_gateway_service.py -k "error or auth or ssl"`
  - `pytest tests/unit/mcpgateway/cache/test_session_registry.py -k "redis or database or cleanup"`

## How to find the biggest misses (post-coverage)
1) Generate JSON:
   - `coverage json -o /tmp/coverage.json`
2) Top missing files:
   -
     ```bash
     python3 - <<'PY'
     import json
     from pathlib import Path
     cov = json.loads(Path('/tmp/coverage.json').read_text())
     items = []
     for file, info in cov['files'].items():
         items.append((len(info['missing_lines']), file))
     for miss, file in sorted(items, reverse=True)[:15]:
         print(f"{miss:5d}  {file}")
     PY
     ```
3) Biggest missing blocks in a file:
   -
     ```bash
     python3 - <<'PY'
     import json
     from pathlib import Path
     cov = json.loads(Path('/tmp/coverage.json').read_text())
     file = 'mcpgateway/main.py'
     missing = sorted(cov['files'][file]['missing_lines'])
     blocks = []
     if missing:
         start = prev = missing[0]
         for line in missing[1:]:
             if line == prev + 1:
                 prev = line
             else:
                 blocks.append((start, prev))
                 start = prev = line
         blocks.append((start, prev))
     blocks.sort(key=lambda b: b[1]-b[0], reverse=True)
     for b in blocks[:20]:
         print(b, 'len', b[1]-b[0]+1)
     PY
     ```

## Highest impact areas (current snapshot)
- mcpgateway/admin.py — 2,069 missing
- mcpgateway/main.py — 990 missing
- mcpgateway/services/gateway_service.py — 728 missing
- mcpgateway/services/tool_service.py — 396 missing
- mcpgateway/services/mcp_client_chat_service.py — 357 missing
- mcpgateway/db.py — 313 missing
- mcpgateway/translate.py — 299 missing
- mcpgateway/services/resource_service.py — 278 missing
- mcpgateway/services/import_service.py — 278 missing
- mcpgateway/schemas.py — 242 missing
- mcpgateway/services/team_management_service.py — 236 missing
- mcpgateway/cache/session_registry.py — 230 missing

## Notes for future test additions
- `RPCRequest` validates method names against `settings.validation_tool_method_pattern` (default: `^[a-zA-Z][a-zA-Z0-9_\./-]*$`). Keep JSON-RPC method names conforming.
- `ResourceSubscription` validates `uri` and `subscriber_id`. Use safe URIs like `/res/1` and subscriber IDs like `user_1` (alnum/underscore/dot/hyphen only).
- Admin routes wrapped with `require_permission` look for `user` in **kwargs**. Call admin handlers with `user=...` in kwargs, or patch `PermissionService.check_permission` to return True.
- Keep tests isolated; avoid real DB/network calls. Prefer patching service singletons and using MagicMock/AsyncMock.

## Suggested next targets
- `mcpgateway/main.py`: remaining JSON-RPC branches (websocket auth errors, final fallback branches) and WebSocket/SSE edge cases.
- `mcpgateway/admin.py`: team/user management error branches (remove member, update role, list join requests error paths).
- `mcpgateway/services/gateway_service.py`: SSL/auth header assembly, error handling branches (mocks only).
- `mcpgateway/services/tool_service.py`: error and validation branches with patched external calls.
- `mcpgateway/services/mcp_client_chat_service.py`: config validators and provider fallbacks without optional deps.

