# 🧪 MCP Gateway Testing Guide

This repository includes a comprehensive test suite organized by test type and purpose:

| Category             | Location                  | Description                                                                           |
| -------------------- | ------------------------- | ------------------------------------------------------------------------------------- |
| **Unit**             | `tests/unit/`             | Fast, isolated tests for individual functions, services, models and handlers.         |
| **Integration**      | `tests/integration/`      | Happy-path flows that stitch several endpoints together with `TestClient`.            |
| **End-to-End (E2E)** | `tests/e2e/`              | Full, high-level workflows that drive the running server (admin, federation, client). |
| **Security**         | `tests/security/`         | Security validation: input validation, headers, cookies, middleware.                  |
| **Performance**      | `tests/performance/`      | Database performance, N+1 detection, and benchmarking.                                |
| **Fuzz**             | `tests/fuzz/`             | Fuzzing and property-based testing with Hypothesis.                                   |
| **Playwright**       | `tests/playwright/`       | Browser-based UI automation tests.                                                    |
| **Migration**        | `tests/migration/`        | Database migration tests (SQLite and PostgreSQL).                                     |
| **Load**             | `tests/load/`             | Load test data generators and verification.                                           |
| **Loadtest**         | `tests/loadtest/`         | Locust-based load testing scenarios.                                                  |
| **Differential**     | `tests/differential/`     | Differential testing (comparing implementations).                                     |

```
tests/
├── conftest.py           # Shared pytest fixtures
├── unit/                 # Unit tests (mirrors mcpgateway/ structure)
├── integration/          # Integration tests
├── e2e/                  # End-to-end tests
├── security/             # Security validation tests
├── performance/          # Performance and N+1 detection
├── fuzz/                 # Fuzzing / property-based tests
├── playwright/           # Browser UI tests
├── migration/            # Database migration tests
├── load/                 # Load test generators
├── loadtest/             # Locust load tests
├── differential/         # Differential testing
├── async/                # Async profiling and benchmarks
├── client/               # HTTP client benchmarks
├── manual/               # Manual test cases and plans
├── helpers/              # Test utilities (query_counter, etc.)
├── utils/                # Shared test mocks (RBAC, etc.)
└── hey/                  # Load test artifacts (ignored by CI)
```

---

## Quick Commands

### Core Testing

| Purpose                              | Command                                              |
| ------------------------------------ | ---------------------------------------------------- |
| **Run unit tests (CI default)**      | `make test`                                          |
| Run full suite                       | `pytest -q`                                          |
| Unit tests only                      | `pytest tests/unit`                                  |
| Integration tests                    | `pytest tests/integration`                           |
| E2E tests                            | `pytest tests/e2e`                                   |
| Single module (verbose)              | `pytest -v tests/unit/mcpgateway/test_main.py`       |
| Single test method                   | `pytest tests/unit/path/test_mod.py::TestClass::test_method` |
| By name substring                    | `pytest -k "fragment"`                               |
| Exclude slow tests                   | `pytest -m "not slow"`                               |
| Run doctests                         | `make doctest`                                       |
| Smoke test (container + E2E)         | `make smoketest`                                     |

### Coverage

| Purpose                              | Command                                              |
| ------------------------------------ | ---------------------------------------------------- |
| **HTML coverage report**             | `make htmlcov` → open `docs/docs/coverage/index.html`|
| Full coverage (md + HTML + XML)      | `make coverage`                                      |
| Coverage for specific module         | `pytest tests/unit/mcpgateway/test_main.py --cov=mcpgateway.main --cov-report=term-missing` |

### Specialized Test Suites

| Purpose                              | Command                                              |
| ------------------------------------ | ---------------------------------------------------- |
| **Security tests**                   | `pytest tests/security`                              |
| **Fuzz / property-based tests**      | `pytest tests/fuzz`                                  |
| **Performance / N+1 detection**      | `make test-db-perf` or `pytest tests/performance`    |
| **Migration tests**                  | `pytest tests/migration`                             |
| **Playwright UI tests**              | `pytest tests/playwright` (requires Playwright setup)|
| **Load tests (Locust)**              | `cd tests/loadtest && locust`                        |

### Database Performance

| Purpose                              | Command                                              |
| ------------------------------------ | ---------------------------------------------------- |
| Dev server with query logging        | `make dev-query-log`                                 |
| Tail query log                       | `make query-log-tail`                                |
| Analyze for N+1 patterns             | `make query-log-analyze`                             |

---

## Coverage workflow

1. **Spot the gaps**

   ```bash
   pytest tests/unit/mcpgateway/test_main.py \
          --cov=mcpgateway.main \
          --cov-report=term-missing
   ```

   Lines listed under *Missing* are un-executed.

2. **Write focused tests**

   Add/extend tests in the relevant sub-folder (unit ➜ fine-grained; integration ➜ flows).

3. **Iterate** until the target percentage (or 100 %) is reached.

---

## Test Layout & Naming Conventions

* Each top-level domain inside `mcpgateway/` has a mirrored **unit-test
  package**: `tests/unit/mcpgateway/<domain>/`.
  *Example*: `mcpgateway/services/tool_service.py` →
  `tests/unit/mcpgateway/services/test_tool_service.py`.

* **Integration tests** live in `tests/integration/` and use
  `TestClient`, but patch actual DB/network calls with `AsyncMock`.

* **E2E tests** assume a running server and may involve
  HTTP requests, WebSockets, SSE streams, etc.

* **Security tests** validate input sanitization, headers, cookies, and middleware security.

* **Fuzz tests** use Hypothesis for property-based testing of schemas, JSON-RPC, and API inputs.

* **Performance tests** detect N+1 queries and measure database performance.

* **Migration tests** verify Alembic migrations work correctly on SQLite and PostgreSQL.

* **Playwright tests** automate browser-based UI testing (requires `playwright install`).

* **Load tests** use Locust for stress testing; data generators live in `tests/load/`.

* Log-replay / load-test artifacts are parked in `tests/hey/` (ignored by CI).

---

## Fixtures Cheat-Sheet

| Fixture        | Scope    | Description                                       |
| -------------- | -------- | ------------------------------------------------- |
| `test_client`  | function | A FastAPI `TestClient` with JWT auth overridden.  |
| `auth_headers` | function | A ready-made `Authorization: Bearer ...` header.  |
| `db_session`   | function | Database session for tests requiring persistence. |

Additional fixtures are defined in module-level `conftest.py` files per folder.

---

## Test Markers

Use markers to categorize and filter tests:

| Marker   | Description                    | Example                        |
| -------- | ------------------------------ | ------------------------------ |
| `slow`   | Long-running tests             | `pytest -m "not slow"`         |
| `ui`     | UI/Playwright tests            | `pytest -m "ui"`               |
| `api`    | API endpoint tests             | `pytest -m "api"`              |
| `smoke`  | Smoke tests                    | `pytest -m "smoke"`            |
| `e2e`    | End-to-end tests               | `pytest -m "e2e"`              |

Combine markers: `pytest -m "api and not slow"`

---

## Makefile Targets

| Target                | Description                                                      |
| --------------------- | ---------------------------------------------------------------- |
| `make test`           | Run unit tests with coverage.                                    |
| `make doctest`        | Run doctests in modules.                                         |
| `make htmlcov`        | Generate HTML coverage report → `docs/docs/coverage/index.html`. |
| `make coverage`       | Full coverage (md + HTML + XML + badge + annotated).             |
| `make smoketest`      | Container build + simple E2E flow.                               |
| `make test-db-perf`   | Run database performance tests.                                  |
| `make dev-query-log`  | Dev server with query logging enabled.                           |
| `make query-log-tail` | Tail the query log in another terminal.                          |
| `make query-log-analyze` | Analyze query log for N+1 patterns.                           |
| `make lint`           | Static analysis (ruff, mypy, etc.).                              |

---

## Specialized Test Suites

### Security Tests (`tests/security/`)

Validates security controls including:
- Input validation and sanitization
- Security headers (CSP, HSTS, etc.)
- Cookie security attributes
- Middleware security behavior

```bash
pytest tests/security -v
```

### Fuzz Tests (`tests/fuzz/`)

Property-based testing using Hypothesis:
- API schema fuzzing
- JSON-RPC message fuzzing
- JSONPath expression fuzzing
- Input validation edge cases

```bash
pytest tests/fuzz -v
# Or run with more examples:
pytest tests/fuzz --hypothesis-seed=0
```

### Performance Tests (`tests/performance/`)

Database and query performance:
- N+1 query detection
- Query count assertions
- Response time benchmarks

```bash
make test-db-perf
# Or directly:
pytest tests/performance -v
```

See `tests/performance/README.md` for detailed profiling instructions.

### Migration Tests (`tests/migration/`)

Database migration validation:
- SQLite migration paths
- PostgreSQL migration paths
- Data integrity verification

```bash
pytest tests/migration -v
```

Requires Docker for PostgreSQL tests. See `tests/migration/README.md`.

### Playwright Tests (`tests/playwright/`)

Browser-based UI automation:
- Admin UI flows
- Authentication workflows
- API endpoint testing via browser

```bash
# Install Playwright browsers first:
playwright install

# Run tests:
pytest tests/playwright -v
```

See `tests/playwright/README.md` for setup details.

### Load Tests (`tests/loadtest/`)

Locust-based load testing:

```bash
cd tests/loadtest
locust -f locustfile.py --host=http://localhost:4444
```

Open http://localhost:8089 to configure and run load tests.

---
