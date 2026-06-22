# F2 Code Quality Review — A2A Native Passthrough (re-run after fix commit 35de2f6ac)

**Verdict**: APPROVE
**Reviewer**: Oracle (read-only)
**Branch**: wxo-2026-06 @ 35de2f6ac
**Plan**: .omo/plans/a2a-native-passthrough.md
**Prior verdict**: REJECT (1 blocking finding — disabled-agent streaming bypass)

## Fix verification

### Code change (mcpgateway/services/a2a_service.py)

Verified. `resolve_agent_for_dispatch()` now builds:

- `DbA2AAgent.name == agent_name`
- `DbA2AAgent.enabled.is_(True)`

at [mcpgateway/services/a2a_service.py:1067-1070](mcpgateway/services/a2a_service.py).

The comment block at lines 1057-1066 explains why the filter must live at this lookup layer: streaming dispatch calls `prepare_a2a_invocation` + `client.stream(...)` directly against `agent.endpoint_url` and does not reach `invoke_agent`'s disabled guard. Disabled-agent misses now collapse to `A2AAgentNotFoundError` / HTTP 404, matching the agent-not-found path.

### Regression test (tests/unit/mcpgateway/services/test_a2a_service_native.py)

Verified. `test_disabled_agent_raises_not_found` exists at [tests/unit/mcpgateway/services/test_a2a_service_native.py:213-236](tests/unit/mcpgateway/services/test_a2a_service_native.py).

It includes both required assertions:

- Behavioral assertion: mocked `scalar_one_or_none()` returns `None`, and `resolve_agent_for_dispatch(db, "disabled-agent")` raises `A2AAgentNotFoundError` at lines 227-230.
- SQL-shape assertion: captures `db.execute.call_args`, stringifies the query, and asserts `"enabled" in query_str.lower()` at lines 231-236.

Targeted verification run passed:

```text
uv run pytest tests/unit/mcpgateway/services/test_a2a_service_native.py::TestResolveAgentForDispatch -q
........ [100%]
```

### Defense-in-depth check

Confirmed.

- `synthesize_agent_card` still filters enabled agents at the query layer: `DbA2AAgent.enabled.is_(True)` at [mcpgateway/services/a2a_service.py:1199-1204](mcpgateway/services/a2a_service.py).
- `invoke_agent` still has the defensive disabled-agent guard: `if not agent.enabled: raise A2AAgentError(...)` at [mcpgateway/services/a2a_service.py:3063-3064](mcpgateway/services/a2a_service.py).
- `resolve_agent_for_dispatch` now adds the missing dispatch-layer query filter at lines 1067-1070.

## Per-file findings (delta from prior pass)

### mcpgateway/schemas_a2a_native.py

Unchanged from prior pass. The fix commit touched only `mcpgateway/services/a2a_service.py` and `tests/unit/mcpgateway/services/test_a2a_service_native.py`.

### mcpgateway/services/a2a_service.py

Blocking finding closed. The dispatch resolver now preserves the existing name match and appends the enabled filter rather than replacing visibility/name logic. Existing `TestResolveAgentForDispatch` mock-returning-agent tests still pass, so no over-fix was observed.

### mcpgateway/main.py

Unchanged from prior pass. The fix commit did not touch this file.

### mcpgateway/middleware/a2a_path_rewrite.py

Unchanged from prior pass. The fix commit did not touch this file.

### mcpgateway/services/server_service.py

Unchanged from prior pass. The fix commit did not touch this file.

### tests/live_gateway/a2a_compliance/conftest.py

Unchanged from prior pass. The fix commit did not touch this file.

## Principle compliance (P1-P5)

P1 is now UPHELD post-fix for the prior disabled-agent streaming bypass: disabled agents are filtered before native dispatch resolution, including streaming. P2-P5 remain unchanged from the prior pass and remain UPHELD.

## Decision compliance (D2/D6/D8/D9/D11/D12/D13/D14/D15/D17/D18)

No negative deltas from the prior pass. D14 is reinforced: disabled-agent dispatch resolution now collapses to the same not-found path as missing agents.

## Anti-pattern spot-check

No new anti-patterns observed. The fix is localized, query-layer based, preserves existing resolver flow, and adds a regression test that checks both behavior and SQL shape.

## Findings

### Blocking (would block APPROVE)

none — prior REJECT finding closed

### Non-blocking observations

- The code comment in `resolve_agent_for_dispatch` cites the `invoke_agent` guard as "line 3050", but the current guard is at line 3063 after the inserted comment/query expansion. This is not functionally material, but a future cleanup could avoid brittle line-number references in comments.

## Final verdict

APPROVE — the prior REJECT finding is now closed: disabled agents are filtered at native dispatch resolution, streaming no longer bypasses the disabled-agent policy, and targeted resolver tests pass.
