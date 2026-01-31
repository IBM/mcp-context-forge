# Remaining test plan / coverage strategy

## Snapshot
- Last full run: `make coverage`
- Line coverage: 37,197 / 48,425 (76.81% line-rate), total 73% in `docs/docs/test/unittest.md`.
- Target to hit 80% line-rate: ~1,543 more lines covered.

Top remaining misses (by missed lines from `coverage.xml`):
1. `mcpgateway/admin.py` (~1,695)
2. `mcpgateway/main.py` (~528)
3. `mcpgateway/services/gateway_service.py` (~508)
4. `mcpgateway/services/mcp_client_chat_service.py` (~357)
5. `mcpgateway/db.py` (~313)
6. `mcpgateway/services/tool_service.py` (~309)
7. `mcpgateway/translate.py` (~299)
8. `mcpgateway/services/resource_service.py` (~273)
9. `mcpgateway/services/import_service.py` (~237)
10. `mcpgateway/cache/session_registry.py` (~230)

## Strategy (highest impact first)

### 1) Admin UI handlers (`mcpgateway/admin.py`)
Biggest win per test. Focus on pure-handler tests with MagicMock Request/db:
- **Auth flows:** login handler, logout variants, change‑password required flows.
- **Join request flows:** create/cancel/approve/reject join requests (happy + error paths).
- **Overview/config endpoints:** error rendering, redis check branch, cache stats branches, passthrough headers update with validation errors.
- **Selector/partial endpoints:** “controls” and “selector” branches for a2a/tools/resources/prompts/gateways/servers (already started; keep adding team_id/gateway_id filtering, include_inactive toggles).
- **Search endpoints:** empty query vs query; team‑scope denied branch; gateway_id null sentinel branches.

Technique: patch service singletons (`tool_service`, `gateway_service`, etc.), `paginate_query`, `TeamManagementService`, `EmailAuthService`, and `request.app.state.templates.TemplateResponse` to keep tests fast and deterministic.

### 2) Core API (`mcpgateway/main.py`)
Large file with route error branches. Good candidates:
- Bad request paths for JSON-RPC (`initialize`, `tools/call`, unknown method) where we can patch service calls.
- Auth-required toggles and error formatters.
- SSE/WebSocket fallback branches with mocked SessionRegistry.
- Config endpoints and health checks.

Technique: use `TestClient` + patch service methods to raise exceptions; assert error payloads.

### 3) Gateway service (`mcpgateway/services/gateway_service.py`)
Coverage here is expensive but manageable with mocks:
- Methods that parse/validate input, build payloads, or handle error classes.
- Validate branches for SSL context selection, auth header assembly, and federation conflicts.

Technique: patch DB session and external clients (`httpx`, `mcp`, `filelock`) to avoid network.

### 4) LLM chat + optional deps (`mcpgateway/services/mcp_client_chat_service.py`)
Many branches depend on optional libs; focus on validator behavior in the config classes:
- `MCPServerConfig` validators (url required by transport, add auth header).
- Provider factory fallbacks and error paths when libs missing.

Technique: import‑time flags `_LLMCHAT_AVAILABLE`, `_ANTHROPIC_AVAILABLE`, etc., and use small Pydantic tests that don’t require external packages.

### 5) Session registry (`mcpgateway/cache/session_registry.py`)
Existing test suite is strong; remaining misses are in DB/redis branches:
- Exercise redis/database branches with monkeypatch or fake backends.
- Trigger cleanup/reap task code paths.

Technique: monkeypatch availability flags and inject fake redis/db objects; keep async tests minimal.

### 6) Schemas (`mcpgateway/schemas.py`)
Continue targeted validator tests:
- ToolCreate/ToolUpdate/ResourceCreate edge cases (allowlist, plugin chain, timeout, path_template).
- Global config and auth validators.

## Suggested short runs
- `pytest tests/unit/mcpgateway/test_admin.py -k "join_request or login or overview"`
- `pytest tests/unit/mcpgateway/test_main_extended.py -k "error or auth or rpc"`
- `pytest tests/unit/mcpgateway/services/test_gateway_service.py -k "error or auth or ssl"`
- `pytest tests/unit/mcpgateway/cache/test_session_registry.py -k "redis or database or cleanup"`

## Notes / pitfalls
- Many tests emit ResourceWarnings for sqlite; keep new tests isolated (mocked sessions) to avoid adding more.
- Avoid touching heavy external integrations; prefer patched service calls and in‑memory data.
- Keep tests deterministic; avoid time.sleep (use monkeypatched time).

