# 🧪 MCP Gateway Testing Guide

This repository comes with a **three-tier test-suite**:

| layer                | location              | what it covers                                                                        |
| -------------------- | --------------------- | ------------------------------------------------------------------------------------- |
| **Unit**             | `tests/unit/…`        | Fast, isolated tests for individual functions, services, models and handlers.         |
| **Integration**      | `tests/integration/…` | Happy-path flows that stitch several endpoints together with `TestClient`.            |
| **End-to-End (E2E)** | `tests/e2e/…`         | Full, high-level workflows that drive the running server (admin, federation, client). |

```
tests/
├── conftest.py               # shared fixtures
├── e2e/            … 3 files
├── integration/    … 8 files
└── unit/           … 60+ files
```

---

## Quick commands

| purpose                                                 | command                                                                                                                     |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Run the full suite (default):**                       | `pytest -q`                                                                                                                 |
| Unit tests only                                         | `pytest tests/unit`                                                                                                         |
| A single module (verbose)                               | `pytest -v tests/unit/mcpgateway/test_main.py`                                                                              |
| **Coverage for `mcpgateway/main.py` from *unit* suite** | <br>`pytest tests/unit/mcpgateway/test_main.py \`<br>`       --cov=mcpgateway.main \`<br>`       --cov-report=term-missing` |
| **HTML coverage report (all code)**                     | `make htmlcov` → open `htmlcov/index.html`                                                                                  |
| Project-wide tests + coverage (CI default)              | `make test`                                                                                                                 |

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

## Test layout & naming conventions

* Each top-level domain inside `mcpgateway/` has a mirrored **unit-test
  package**: `tests/unit/mcpgateway/<domain>/`.
  *Example*: `mcpgateway/services/tool_service.py` →
  `tests/unit/mcpgateway/services/test_tool_service.py`.

* **Integration tests** live in `tests/integration/` and use
  `TestClient`, but patch actual DB/network calls with `AsyncMock`.

* **E2E tests** (optional) assume a running server and may involve
  HTTP requests, WebSockets, SSE streams, etc.

* Log-replay / load-test artefacts are parked in `tests/hey/` (ignored by CI).

---

## Fixtures cheat-sheet

| fixture        | scope                                        | description                                      |
| -------------- | -------------------------------------------- | ------------------------------------------------ |
| `test_client`  | function                                     | A FastAPI `TestClient` with JWT auth overridden. |
| `auth_headers` | function                                     | A ready-made `Authorization: Bearer …` header.   |
| Extra helpers  | module-level `conftest.py` files per folder. |                                                  |

---

## Makefile targets

| target         | does…                                                                  |
| -------------- | ---------------------------------------------------------------------- |
| `make test`    | Runs `pytest --cov --cov-report=term` across the whole repo.           |
| `make htmlcov` | Re-runs tests and generates an **HTML coverage report** in `htmlcov/`. |
| `make lint`    | Static analysis (ruff, mypy, etc.) — optional in CI.                   |

---
