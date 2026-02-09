# Prompt: Improve Doctest Coverage Across All Modules

Add doctest examples (`>>>`) to all public functions and methods in `mcpgateway/`. Currently **34% of functions** (953 / 2,797) have doctest examples. Every function already has a docstring (100% interrogate score) — the task is to add executable `>>>` examples inside existing docstrings, not to write new docstrings from scratch.

## Current State

- **2,797 functions/methods** across 191 source files
- **953 have `>>>` examples** (34%), **1,842 do not**
- **1,143 doctests pass**, **52 are skipped** (`+SKIP`), **0 failures**
- **144 files** have at least some doctests, **51 files** have zero
- **97 files** have partial coverage (some functions with `>>>`, some without) — best to extend these first

## Key Files and Commands

### Run all doctests (fast — ~7 seconds)

```bash
JWT_SECRET_KEY=secret .venv/bin/python -m pytest --doctest-modules mcpgateway/ \
  --ignore=mcpgateway/utils/pagination.py --tb=short --no-cov --disable-warnings -n 4
```

### Run doctests for a single file

```bash
.venv/bin/python -m pytest --doctest-modules mcpgateway/services/role_service.py \
  --no-cov --disable-warnings -v
```

### Run doctests with verbose output (see each doctest name)

```bash
JWT_SECRET_KEY=secret .venv/bin/python -m pytest --doctest-modules mcpgateway/ \
  --ignore=mcpgateway/utils/pagination.py -v --tb=short --no-cov --disable-warnings -n 4
```

### Run doctests with coverage

```bash
.venv/bin/python -m pytest --doctest-modules mcpgateway/ \
  --cov=mcpgateway --cov-report=term --cov-report=html:htmlcov-doctest
```

### Quick check pass/fail

```bash
make doctest
```

## Doctest Patterns Used in This Codebase

### Simple pure function

```python
def normalize_teams(payload: dict) -> list:
    """Normalize token teams.

    Examples:
        >>> normalize_teams({"teams": ["a", "b"]})
        ['a', 'b']
        >>> normalize_teams({})
        []
        >>> normalize_teams({"teams": None, "is_admin": True}) is None
        True
    """
```

### Class with mock dependencies

```python
class RoleService:
    """Role management service.

    Examples:
        >>> from unittest.mock import Mock
        >>> service = RoleService(Mock())
        >>> isinstance(service, RoleService)
        True
    """

    def __init__(self, db):
        """Initialize.

        Examples:
            >>> from mcpgateway.services.role_service import RoleService
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> service.db is not None
            True
        """
        self.db = db
```

### Cache / data structure with mocked time

```python
def get(self, key):
    """Get cached value.

    Examples:
        >>> from unittest.mock import patch
        >>> cache = ResourceCache(max_size=2, ttl=1)
        >>> cache.set('a', 1)
        >>> cache.get('a')
        1

        Test TTL expiration:
        >>> with patch("time.time") as mock_time:
        ...     mock_time.return_value = 1000
        ...     cache2 = ResourceCache(max_size=2, ttl=1)
        ...     cache2.set('x', 100)
        ...     mock_time.return_value = 1002
        ...     cache2.get('x') is None
        True
    """
```

### Async function (use `asyncio.run`)

```python
async def _handle_gateway_failure(self, gateway):
    """Handle gateway failure.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import Mock
        >>> service = GatewayService.__new__(GatewayService)
        >>> service._gateway_failure_counts = {}
        >>> gateway = Mock(id='gw1', enabled=True)
        >>> asyncio.run(service._handle_gateway_failure(gateway))  # doctest: +ELLIPSIS
        >>> service._gateway_failure_counts['gw1'] >= 1
        True
    """
```

### Functions that need external resources (use `+SKIP`)

Only use `+SKIP` when the function genuinely cannot run without external services (database, network, filesystem side effects). Do **not** use `+SKIP` as a shortcut to avoid writing proper mock-based examples.

```python
async def start_trace(self, db, name, **kwargs):
    """Start a trace.

    Examples:
        >>> service = ObservabilityService()  # doctest: +SKIP
        >>> trace_id = service.start_trace(db, "GET /tools")  # doctest: +SKIP
    """
```

### Doctest directives used

| Directive | Count | When to use |
|---|---|---|
| `+SKIP` | 158 | Function requires DB, network, or has side effects that can't be mocked inline |
| `+ELLIPSIS` | 24 | Output contains UUIDs, timestamps, or other non-deterministic values |
| `+IGNORE_EXCEPTION_DETAIL` | 2 | Testing that an exception is raised but message varies |

## Top 20 Files by Missing Doctest Examples (Extend These First)

These files already have some doctests — follow the existing patterns to fill gaps:

| File | Funcs | Has `>>>` | Missing | Coverage |
|---|---|---|---|---|
| `mcpgateway/admin.py` | 218 | 69 | 149 | 32% |
| `mcpgateway/db.py` | 150 | 21 | 129 | 14% |
| `mcpgateway/schemas.py` | 143 | 26 | 117 | 18% |
| `mcpgateway/main.py` | 127 | 19 | 108 | 15% |
| `mcpgateway/services/tool_service.py` | 57 | 17 | 40 | 30% |
| `mcpgateway/services/gateway_service.py` | 58 | 19 | 39 | 33% |
| `mcpgateway/services/import_service.py` | 44 | 8 | 36 | 18% |
| `mcpgateway/services/resource_service.py` | 46 | 17 | 29 | 37% |
| `mcpgateway/services/team_management_service.py` | 34 | 9 | 25 | 26% |
| `mcpgateway/plugins/framework/base.py` | 27 | 3 | 24 | 11% |
| `mcpgateway/routers/llmchat_router.py` | 25 | 2 | 23 | 8% |
| `mcpgateway/translate.py` | 46 | 25 | 21 | 54% |
| `mcpgateway/reverse_proxy.py` | 22 | 1 | 21 | 5% |
| `mcpgateway/services/prompt_service.py` | 38 | 18 | 20 | 47% |
| `mcpgateway/services/oauth_manager.py` | 21 | 1 | 20 | 5% |
| `mcpgateway/config.py` | 31 | 12 | 19 | 39% |
| `mcpgateway/services/a2a_service.py` | 22 | 3 | 19 | 14% |
| `mcpgateway/services/email_auth_service.py` | 21 | 2 | 19 | 10% |
| `mcpgateway/plugins/framework/memory.py` | 21 | 4 | 17 | 19% |
| `mcpgateway/routers/teams.py` | 18 | 1 | 17 | 6% |

## 51 Files With Zero Doctests (Create From Scratch)

These files have functions but no `>>>` examples at all:

```
cache/tool_lookup_cache.py              (12 funcs, 340 lines)
cli_export_import.py                    ( 4 funcs, 333 lines)
llm_provider_configs.py                 (11 funcs, 529 lines)
llm_schemas.py                          (29 funcs, 407 lines)
middleware/correlation_id.py            ( 2 funcs, 118 lines)
middleware/db_query_logging.py          (12 funcs, 471 lines)
middleware/http_auth_middleware.py       ( 2 funcs, 180 lines)
middleware/protocol_version.py          ( 2 funcs,  95 lines)
observability.py                        (17 funcs, 530 lines)
plugins/framework/constants.py          ( 0 funcs,  48 lines)
plugins/framework/errors.py             ( 5 funcs,  63 lines)
plugins/framework/external/mcp/client   ( 7 funcs, 488 lines)
plugins/framework/hooks/http.py         (12 funcs, 212 lines)
plugins/tools/models.py                 ( 2 funcs,  34 lines)
routers/cancellation_router.py          ( 2 funcs, 128 lines)
routers/llm_admin_router.py             ( 0 funcs, 880 lines)
routers/llm_config_router.py            ( 0 funcs, 615 lines)
routers/llm_proxy_router.py             ( 0 funcs, 173 lines)
routers/log_search.py                   (12 funcs, 782 lines)
routers/metrics_maintenance.py          ( 7 funcs, 295 lines)
routers/server_well_known.py            ( 0 funcs, 131 lines)
routers/toolops_router.py              ( 1 funcs, 177 lines)
services/audit_trail_service.py         (11 funcs, 451 lines)
services/cancellation_service.py        ( 2 funcs, 302 lines)
services/catalog_service.py             ( 3 funcs, 560 lines)
services/dcr_service.py                 ( 4 funcs, 391 lines)
services/elicitation_service.py         (10 funcs, 330 lines)
services/grpc_service.py                ( 6 funcs, 613 lines)
services/http_client_service.py         ( 8 funcs, 367 lines)
services/llm_provider_service.py        (24 funcs, 795 lines)
services/llm_proxy_service.py           (16 funcs, 764 lines)
services/log_aggregator.py              (17 funcs, 989 lines)
services/mcp_session_pool.py            (25 funcs, 2042 lines)
services/metrics_buffer_service.py      (22 funcs, 774 lines)
services/metrics_cleanup_service.py     (10 funcs, 499 lines)
services/metrics_query_service.py       (13 funcs, 664 lines)
services/metrics_rollup_service.py      (17 funcs, 1017 lines)
services/performance_service.py         (14 funcs, 774 lines)
services/plugin_service.py              ( 9 funcs, 321 lines)
services/security_logger.py             (13 funcs, 598 lines)
services/structured_logger.py           (23 funcs, 489 lines)
toolops/toolops_altk_service.py         ( 1 funcs, 294 lines)
tools/builder/dagger_deploy.py          ( 3 funcs, 556 lines)
tools/cli.py                            ( 1 funcs,  57 lines)
translate_grpc.py                       (10 funcs, 570 lines)
transports/redis_event_store.py         ( 7 funcs, 260 lines)
utils/analyze_query_log.py              ( 4 funcs, 196 lines)
utils/generate_keys.py                  ( 4 funcs, 112 lines)
utils/pagination.py                     ( 5 funcs, 874 lines) [ignored in make doctest]
utils/sqlalchemy_modifier.py            ( 6 funcs, 335 lines)
utils/ssl_context_cache.py              ( 2 funcs,  65 lines)
```

Note: Files with `0 funcs` (only module-level code/routes) don't need function-level doctests.

## Strategy

### Phase 1: Extend files with partial coverage (97 files, highest ROI)

These files already have doctest patterns to follow. For each file:

1. Read the file and note which functions have `>>>` examples
2. Look at the existing pattern (mock style, import style, assertion style)
3. Add `>>>` examples to functions without them, following the same pattern
4. Run: `.venv/bin/python -m pytest --doctest-modules mcpgateway/<file>.py --no-cov -v`
5. Fix any failures and move on

Focus on:
- **Pure functions** (validators, formatters, parsers) — easiest, no mocks needed
- **`__init__` methods** — show basic construction with mocked deps
- **Property methods and simple getters** — verify return type/value
- **Error paths** — show what happens with bad input (`pytest.raises` doesn't work in doctests; assert the behavior instead)

### Phase 2: Add doctests to zero-coverage files (51 files)

For files with no doctests at all:
1. Read the file to understand what it does
2. Identify pure functions and simple methods — add real `>>>` examples
3. For async methods with DB dependencies — add basic construction examples with mocks
4. For functions requiring external services — use `+SKIP` only as last resort
5. Run the single-file doctest to verify

### Phase 3: Convert `+SKIP` to runnable doctests (158 skips)

Many `+SKIP` doctests can be converted to runnable examples with proper mocking. The 52 skipped doctests are in:

| File | Skips | Reason |
|---|---|---|
| `services/observability_service.py` | 63 | DB dependency — mock with `unittest.mock` |
| `services/mcp_client_chat_service.py` | 41 | Complex async + DB — consider partial conversion |
| `translate.py` | 14 | Transport/stdio — hard to mock inline |
| `instrumentation/sqlalchemy.py` | 8 | Engine dependency |
| `utils/ssl_key_manager.py` | 6 | Filesystem |
| Other files | 26 | Mixed reasons |

### Priority approach

For maximum impact, work on files in this order:
1. **Services with existing patterns** — `tool_service.py`, `gateway_service.py`, `resource_service.py`, `prompt_service.py` (already 30-50% covered, extend the pattern)
2. **Pure utility files** — `utils/`, `common/validators.py`, `validation/` (easiest to write real examples)
3. **Cache files** — already well-covered, fill remaining gaps
4. **Config and schemas** — many validators/properties that are easy to test
5. **Large files** — `admin.py`, `main.py`, `db.py` (most missing but harder; do incrementally)

## Workflow for Each File

1. **Read the source file** — understand functions and identify which lack `>>>`
2. **Check existing examples** — match the style (`from unittest.mock import Mock`, import patterns, etc.)
3. **Add `>>>` examples** inside existing `Examples:` sections (or add an `Examples:` section to the docstring)
4. **Run single-file doctest**: `.venv/bin/python -m pytest --doctest-modules mcpgateway/<file>.py --no-cov -v`
5. **Fix failures** — common issues: non-deterministic output (use `+ELLIPSIS`), import errors, missing mocks
6. **Run full suite periodically**: `make doctest` — confirm no regressions (~7s)

## What NOT to Do

- Do not add `+SKIP` to avoid writing proper examples — use it only when genuinely impossible to mock inline
- Do not write examples that test nothing (`>>> True\nTrue`) — each example should demonstrate real behavior
- Do not duplicate unit tests — doctests serve as documentation-first examples, not exhaustive test cases
- Do not add doctests to `__init__.py` files or files with 0 functions
- Do not modify function signatures or behavior to make doctests easier
- Do not remove existing passing doctests
- Do not add doctests for private helper functions that are implementation details (focus on public API)
- Do not worry about `mcpgateway/utils/pagination.py` — it is excluded via `--ignore` in the Makefile
