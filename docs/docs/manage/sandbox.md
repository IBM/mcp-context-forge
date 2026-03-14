# Policy Testing Sandbox

The Policy Testing Sandbox lets you test RBAC policy drafts **before deploying
them to production**. You can simulate individual access decisions, run batch
test suites, and perform regression testing against historical decisions — all
in an isolated environment that never affects live policy.

---

## Overview

```
┌──────────────────────────────────────────────────────────────┐
│                  Policy Testing Sandbox                       │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Policy Draft ──▶ Sandbox PDP ──▶ Evaluation ──▶ Results     │
│                   (isolated)      (safe)         (diff)      │
│                                                              │
│  Modes:                                                      │
│   • Simulate — single access decision                        │
│   • Batch    — run a full test suite                          │
│   • Regression — compare two policy versions                 │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

The sandbox creates a **temporary, isolated Policy Decision Point (PDP)** loaded
with your draft configuration. Every evaluation runs against this ephemeral PDP
and the results are returned without modifying any production state.

### Key Capabilities

| Feature | Description |
|---------|-------------|
| **Single Simulation** | Evaluate one access request against a policy draft |
| **Batch Testing** | Run a suite of test cases and get pass/fail summary |
| **Regression Testing** | Compare decisions between two policy versions |
| **Test Suite Management** | Create reusable, tagged test suites (CRUD) |
| **Explanation Mode** | Get human-readable explanations of policy decisions |
| **Configurable Timeouts** | Per-case timeout prevents runaway evaluations |
| **Concurrency Control** | Semaphore-limited parallel execution for batch runs |

---

## Configuration

Enable and tune the sandbox with these environment variables in your `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCPGATEWAY_SANDBOX_ENABLED` | `false` | Enable/disable the sandbox feature |
| `MCPGATEWAY_SANDBOX_ISOLATION_MODE` | `process` | PDP isolation mode (`process`, `thread`) |
| `MCPGATEWAY_SANDBOX_MAX_CONCURRENT_TESTS` | `5` | Max concurrent test evaluations |
| `MCPGATEWAY_SANDBOX_TEST_SUITES_PATH` | `test_suites/` | Path for test suite storage |
| `MCPGATEWAY_SANDBOX_REGRESSION_DAYS` | `30` | Default days for regression replay |
| `MCPGATEWAY_SANDBOX_REGRESSION_SAMPLE_SIZE` | `100` | Default sample size for regression |
| `MCPGATEWAY_SANDBOX_MAX_TEST_CASES_PER_RUN` | `500` | Maximum test cases per batch run |
| `MCPGATEWAY_SANDBOX_TIMEOUT_PER_CASE_MS` | `100` | Timeout per test case (milliseconds) |

### Minimal Setup

```bash
# Add to .env
MCPGATEWAY_SANDBOX_ENABLED=true

# Restart the gateway
make dev
```

---

## Architecture

### Isolation Model

Each simulation creates an ephemeral Policy Decision Point:

1. **Draft Loading** — The policy draft is loaded from the database
2. **PDP Creation** — A sandbox PDP is instantiated with the draft config
3. **Evaluation** — The access request is checked against the sandbox PDP
4. **Cleanup** — The PDP is destroyed in a `finally` block (even on timeout)

This ensures production policy is **never modified** during testing.

### Timeout Handling

Every evaluation is wrapped in `asyncio.wait_for()`:

- Timeout value: `MCPGATEWAY_SANDBOX_TIMEOUT_PER_CASE_MS / 1000.0` seconds
- On timeout: `asyncio.TimeoutError` is raised
- PDP cleanup always runs (via `try/finally`)
- Batch runs report timed-out cases as failures

### Concurrency Control

Batch and regression runs use `asyncio.Semaphore` to limit parallel evaluations:

- Controlled by `MCPGATEWAY_SANDBOX_MAX_CONCURRENT_TESTS`
- Prevents resource exhaustion during large test suites
- Each evaluation acquires the semaphore before PDP creation

---

## Admin UI

When `MCPGATEWAY_UI_ENABLED=true` and `MCPGATEWAY_SANDBOX_ENABLED=true`, the
sandbox appears as a tab in the Admin panel with three sub-views:

### Simulate Tab

Fill in a single access request:

- **Subject**: email, team, roles
- **Action**: the operation being performed (e.g., `tools.invoke`)
- **Resource**: type, ID, and optional server
- **Expected Decision**: what you expect (ALLOW or DENY)

Results show whether the actual decision matches expectations, along with
matching policies, execution time, and an optional explanation.

### Batch Tab

Select a policy draft and a test suite, then run all cases at once:

- **Pass/Fail Summary**: total tests, passed, failed, pass rate
- **Per-Case Results**: each test case with actual vs expected decision
- **Execution Time**: per-case and total batch duration

### Regression Tab

Compare a new policy draft against a baseline version:

- **Replay Period**: number of days of historical decisions to replay
- **Sample Size**: how many decisions to sample
- **Diff Report**: which decisions changed between versions

---

## API Reference

All sandbox API endpoints are prefixed with `/api/sandbox/sandbox/`.

!!! note
    Full curl examples are available in the [API Usage Guide](api-usage.md#policy-testing-sandbox).

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Liveness probe |
| `GET` | `/info` | No | Service capabilities and feature flags |
| `POST` | `/simulate` | Yes | Simulate a single access decision |
| `POST` | `/batch` | Yes | Run a batch of test cases |
| `POST` | `/regression` | Yes | Run regression test |
| `POST` | `/suites` | Yes | Create a test suite |
| `GET` | `/suites` | Yes | List test suites (with optional tag filter) |
| `GET` | `/suites/{id}` | Yes | Get a specific test suite |
| `PUT` | `/suites/{id}` | Yes | Update a test suite |
| `DELETE` | `/suites/{id}` | Yes | Delete a test suite |

### Quick Examples

```bash
# Health check (no auth)
curl -s $BASE_URL/api/sandbox/sandbox/health | jq .

# Simulate a single decision
curl -s -X POST "$BASE_URL/api/sandbox/sandbox/simulate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "policy_draft_id": "draft-123",
    "test_case": {
      "subject": {"email": "dev@example.com", "roles": ["developer"]},
      "action": "tools.invoke",
      "resource": {"type": "tool", "id": "db-query"},
      "expected_decision": "ALLOW"
    },
    "include_explanation": true
  }' | jq .

# Run batch test suite
curl -s -X POST "$BASE_URL/api/sandbox/sandbox/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "policy_draft_id": "draft-123",
    "test_suite_id": "suite-abc"
  }' | jq .
```

---

## Database Models

The sandbox stores its data in two tables:

### `policy_drafts`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `String(36)` | Primary key (UUID) |
| `name` | `String(256)` | Draft name |
| `description` | `Text` | Optional description |
| `config_json` | `JSON` | PDP configuration as JSON |
| `created_at` | `DateTime` | Creation timestamp |
| `updated_at` | `DateTime` | Last update timestamp |

### `sandbox_test_suites`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `String(36)` | Primary key (UUID) |
| `name` | `String(256)` | Suite name |
| `description` | `Text` | Optional description |
| `tags` | `JSON` | List of string tags for filtering |
| `test_cases` | `JSON` | Array of `TestCase` objects |
| `created_at` | `DateTime` | Creation timestamp |
| `updated_at` | `DateTime` | Last update timestamp |

---

## Troubleshooting

### Sandbox tab not visible

Ensure both settings are enabled:

```bash
MCPGATEWAY_SANDBOX_ENABLED=true
MCPGATEWAY_UI_ENABLED=true
```

### Timeouts on simulation

Increase the per-case timeout:

```bash
MCPGATEWAY_SANDBOX_TIMEOUT_PER_CASE_MS=500
```

### Batch fails with "exceeds maximum"

Reduce the number of test cases or increase the limit:

```bash
MCPGATEWAY_SANDBOX_MAX_TEST_CASES_PER_RUN=1000
```

### High resource usage during batch runs

Lower concurrency:

```bash
MCPGATEWAY_SANDBOX_MAX_CONCURRENT_TESTS=2
```
