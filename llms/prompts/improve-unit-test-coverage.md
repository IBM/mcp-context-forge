# Prompt: Improve Unit Test Coverage to >90%

Improve unit test coverage for `mcpgateway/` from the current **65.3%** to **>90%** by identifying uncovered code paths, writing targeted tests, and verifying with per-file coverage. The full suite (`make coverage`) is slow — run individual test files to iterate quickly, and only run the full suite to verify final numbers.

## Current State

- **Total coverage: 65.3%** (28,893 / 44,278 lines)
- **150 source files** tracked, **280 test files** with **6,650 test functions** in `tests/unit/`
- **42 files below 70%** account for **78% of all missed lines** (8,294 / 10,608)
- **38 source files have no corresponding test file at all**

## Key Files and Structure

```
mcpgateway/                          # Source code (150 tracked files)
├── main.py                          # App entry + core route handlers (2019 stmts, 57%)
├── admin.py                         # Admin UI HTMX handlers (4268 stmts, 27%)
├── schemas.py                       # Pydantic models (2450 stmts, 80%)
├── db.py                            # ORM models (1479 stmts, 85%)
├── config.py                        # Settings (707 stmts, 82%)
├── auth.py                          # Auth helpers (161 stmts, 87%)
├── translate.py                     # MCP translate (785 stmts, 58%)
├── services/                        # Business logic (55 files)
├── routers/                         # HTTP routers (19 files)
├── middleware/                       # Middleware (15 files)
└── plugins/                         # Plugin framework

tests/
├── conftest.py                      # Root fixtures (app, test_db, app_with_temp_db)
└── unit/mcpgateway/
    ├── conftest.py                  # Auto-mocks PermissionService for all unit tests
    ├── test_*.py                    # Root-level test files (56 files)
    ├── services/                    # Service tests (73 files, 2360 tests)
    ├── routers/                     # Router tests (19 files, 419 tests)
    ├── middleware/                   # Middleware tests (17 files, 243 tests)
    ├── plugins/                     # Plugin tests (50 files, 579 tests)
    ├── utils/                       # Utility tests (28 files, 476 tests)
    └── ...                          # cache/, db/, handlers/, transports/, validation/

pyproject.toml                       # pytest + coverage config
Makefile                             # `make test`, `make coverage`, `make htmlcov`
```

## Commands

### Run a single test file (fast iteration)

```bash
DATABASE_URL=sqlite:///:memory: python3 -m pytest tests/unit/mcpgateway/test_auth.py -v --no-header
```

### Run a single test file with per-file coverage

```bash
DATABASE_URL=sqlite:///:memory: python3 -m pytest tests/unit/mcpgateway/services/test_tool_service.py \
  -v --no-header --cov=mcpgateway.services.tool_service --cov-report=term-missing
```

The `--cov-report=term-missing` output shows exact uncovered line numbers, e.g.:

```
Name                                    Stmts   Miss  Cover   Missing
---------------------------------------------------------------------
mcpgateway/services/tool_service.py       866    220    72%   45-52, 110-125, ...
```

### Run all tests in a subdirectory

```bash
DATABASE_URL=sqlite:///:memory: python3 -m pytest tests/unit/mcpgateway/services/ -v --no-header -x
```

### Run full coverage suite (slow — use sparingly)

```bash
make coverage
# Report: docs/docs/coverage/index.html
# Also generates: coverage.xml, .coverage, annotated .py,cover files
```

### Run tests in parallel (faster for full suite)

```bash
DATABASE_URL=sqlite:///:memory: python3 -m pytest tests/unit/ -n 16 --maxfail=0 -v
```

## Environment Variables for Tests

Set these before running tests (also configured in `pyproject.toml`):

```bash
export DATABASE_URL='sqlite:///:memory:'
export TEST_DATABASE_URL='sqlite:///:memory:'
export ARGON2ID_TIME_COST=1           # Speed up argon2 hashing in tests
export ARGON2ID_MEMORY_COST=1024
export MCPGATEWAY_ADMIN_API_ENABLED=true
export MCPGATEWAY_UI_ENABLED=true
```

## Test Fixtures Available

From `tests/conftest.py`:
- **`app`** — FastAPI test app with temp SQLite DB, auth disabled, all SessionLocal patched
- **`app_with_temp_db`** — Module-scoped variant (one DB per test module)
- **`test_db`** — Fresh SQLAlchemy session per test
- **`test_engine`** — Session-scoped SQLAlchemy engine
- **`test_settings`** — Settings with in-memory DB, auth disabled
- **`mock_http_client`** — AsyncMock HTTP client
- **`mock_websocket`** — AsyncMock WebSocket
- **`query_counter`** / **`assert_max_queries`** — N+1 detection helpers

From `tests/unit/mcpgateway/conftest.py`:
- **`mock_permission_service`** (autouse) — Auto-mocks `PermissionService` to allow all permissions. Override in individual tests for denial testing.

## Test Writing Patterns

### Unit test for a service (most common pattern)

```python
"""Tests for mcpgateway/services/some_service.py"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mcpgateway.services.some_service import SomeService, SomeError

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db

@pytest.fixture
def service(mock_db):
    return SomeService(db=mock_db)

class TestSomeService:
    async def test_create_success(self, service, mock_db):
        result = await service.create(...)
        assert result is not None

    async def test_create_duplicate_raises(self, service, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        with pytest.raises(SomeError):
            await service.create(...)
```

### Router test with FastAPI TestClient

```python
from fastapi.testclient import TestClient

def test_get_endpoint(app):
    client = TestClient(app)
    response = client.get("/some-endpoint")
    assert response.status_code == 200
```

### Async test

```python
@pytest.mark.asyncio
async def test_async_operation():
    with patch("mcpgateway.services.foo.external_call", new_callable=AsyncMock) as mock:
        mock.return_value = {"status": "ok"}
        result = await function_under_test()
        assert result["status"] == "ok"
```

### Parametrized test for validators/schemas

```python
@pytest.mark.parametrize("input_val,expected", [
    ("valid", True),
    ("", False),
    (None, False),
])
def test_validation(input_val, expected):
    result = validate(input_val)
    assert result == expected
```

## Top 15 Files by Impact (66% of All Missed Lines)

These files account for the most missed lines. Fixing them gives the biggest coverage gain:

| # | File | Stmts | Miss | Cover | Cumulative |
|---|---|---|---|---|---|
| 1 | `mcpgateway/admin.py` | 4268 | 2920 | 27% | 28% |
| 2 | `mcpgateway/main.py` | 2019 | 785 | 57% | 35% |
| 3 | `mcpgateway/services/gateway_service.py` | 1482 | 561 | 57% | 40% |
| 4 | `mcpgateway/schemas.py` | 2450 | 329 | 80% | 43% |
| 5 | `mcpgateway/services/mcp_client_chat_service.py` | 639 | 305 | 45% | 46% |
| 6 | `mcpgateway/translate.py` | 785 | 295 | 58% | 49% |
| 7 | `mcpgateway/services/llm_proxy_service.py` | 276 | 276 | 0% | 52% |
| 8 | `mcpgateway/services/llm_provider_service.py` | 271 | 271 | 0% | 54% |
| 9 | `mcpgateway/services/tool_service.py` | 866 | 220 | 72% | 56% |
| 10 | `mcpgateway/services/grpc_service.py` | 229 | 196 | 11% | 58% |
| 11 | `mcpgateway/translate_grpc.py` | 225 | 191 | 12% | 60% |
| 12 | `mcpgateway/routers/log_search.py` | 309 | 180 | 32% | 62% |
| 13 | `mcpgateway/services/log_aggregator.py` | 204 | 179 | 9% | 63% |
| 14 | `mcpgateway/services/resource_service.py` | 797 | 172 | 76% | 65% |
| 15 | `mcpgateway/routers/email_auth.py` | 217 | 167 | 21% | 66% |

## Files at 0% Coverage (No Tests at All)

These source files have **zero** test coverage:

| File | Stmts | Notes |
|---|---|---|
| `services/llm_proxy_service.py` | 276 | LLM proxy forwarding |
| `services/llm_provider_service.py` | 271 | LLM provider CRUD |
| `toolops/toolops_altk_service.py` | 135 | ALTK integration |
| `toolops/utils/llm_util.py` | 85 | LLM utility helpers |
| `toolops/utils/db_util.py` | 34 | DB utility helpers |
| `toolops/utils/format_conversion.py` | 23 | Format conversion |
| `validators.py` | 2 | Validators |

## Source Files with No Corresponding Test File

These 38 files have no `test_*.py` counterpart — create test files for the important ones:

```
cache/a2a_stats_cache.py              services/email_auth_service.py
cache/auth_cache.py                   services/encryption_service.py
cache/global_config_cache.py          services/http_client_service.py
cache/metrics_cache.py                services/permission_service.py
cli_export_import.py                  services/security_logger.py
llm_provider_configs.py               services/sso_service.py
middleware/http_auth_middleware.py     services/structured_logger.py
middleware/security_headers.py        services/token_storage_service.py
plugins/framework/constants.py        toolops/utils/db_util.py
plugins/framework/decorator.py        toolops/utils/format_conversion.py
plugins/framework/external/mcp/...    toolops/utils/llm_util.py
plugins/framework/hooks/agents.py     tools/builder/factory.py
plugins/framework/hooks/prompts.py    tools/builder/pipeline.py
plugins/framework/hooks/resources.py  utils/base_models.py
plugins/framework/hooks/tools.py      utils/create_slug.py
plugins/framework/loader/plugin.py    utils/display_name.py
routers/email_auth.py                 utils/security_cookies.py
routers/server_well_known.py          utils/ssl_context_cache.py
routers/sso.py
routers/toolops_router.py
```

## Strategy: Prioritized Approach to >90%

### Phase 1: High-Impact Files (65% → ~78%)

Focus on the top 15 files from the impact table. These 15 files alone account for 7,047 of 10,608 missed lines (66%). Target coverage patterns:

- **`admin.py` (27%, 2920 miss)** — Largest file. Test HTMX handler functions with `TestClient(app)` and `Accept: text/html`. Many handlers follow the same pattern: fetch data, render template. Parametrize across endpoints.
- **`main.py` (57%, 785 miss)** — Core REST route handlers. Extend existing `test_main.py` tests. Focus on error paths, edge cases, and missing CRUD operations.
- **`services/gateway_service.py` (57%, 561 miss)** — Gateway federation logic. Mock HTTP clients, test error handling, timeouts, retry logic.
- **`services/llm_proxy_service.py` (0%)** and **`services/llm_provider_service.py` (0%)** — Create test files from scratch. Mock external LLM API calls.
- **`services/grpc_service.py` (11%)** and **`translate_grpc.py` (12%)** — Mock gRPC stubs and channels.

### Phase 2: Mid-Range Files (78% → ~87%)

Target the 33 files between 70-89% (2,128 missed lines). Focus on:
- **Error handling paths** — exception branches, validation failures
- **Edge cases** — empty inputs, None values, boundary conditions
- **Conditional branches** — if/else paths not yet exercised

Use `--cov-report=term-missing` to identify exact uncovered lines, then read the source to understand the branch.

### Phase 3: Zero-Coverage and Missing Files (87% → >90%)

- Create test files for the 38 source files with no test counterpart
- Focus on files with >30 statements (skip trivial `__init__.py`-like files)
- Target `routers/email_auth.py`, `routers/sso.py`, `services/sso_service.py`, `middleware/token_scoping.py`

## Workflow for Each File

1. **Read the source file** to understand what it does and identify testable units
2. **Check existing coverage**: `python3 -m pytest <test_file> --cov=<module> --cov-report=term-missing`
3. **Read the uncovered lines** in the source file to understand what branches are missed
4. **Write tests** targeting the missed lines — focus on error paths, edge cases, conditional branches
5. **Run the test file** to verify tests pass: `DATABASE_URL=sqlite:///:memory: python3 -m pytest <test_file> -v -x`
6. **Re-check coverage** to confirm improvement: `python3 -m pytest <test_file> --cov=<module> --cov-report=term-missing`
7. **Move on** to the next file

Do **not** run `make coverage` after every file — only run it periodically (e.g., after completing a phase) to check overall progress.

## What NOT to Do

- Do not write tests that just call functions without asserting behavior
- Do not mock everything — test real logic paths where possible
- Do not add tests for `__init__.py` files or trivial re-exports
- Do not modify source code to make it easier to test (unless fixing a genuine testability issue)
- Do not add `# pragma: no cover` to skip lines — fix the coverage gap instead
- Do not run `make coverage` after every single test file — it's slow (~5 min). Use per-file `--cov` instead
