"""Cross-target drift detection.

Each test here opens a client against every available target, runs the
same protocol probe, normalizes the results via ``helpers.drift``, and asserts
pairwise equality. Surviving divergence is drift — a gateway-introduced
behavioral difference not explained by legitimate decoration.

Unlike the rest of the harness, these tests do **not** parametrize via
the ``client`` / ``connect`` fixtures. They open multiple clients in
sequence inside one test body. Targets that fail to connect are recorded
as unavailable and skipped from the comparison; if fewer than two
targets are reachable, the test returns without asserting (drift needs
≥2 data points).
"""

from __future__ import annotations

from typing import Any, AsyncContextManager, Callable, Optional

import pytest
from fastmcp.client import Client

from .helpers.compliance import resolve_tool
from .helpers.drift import (
    assert_drift_free,
    normalize_prompt_names,
    normalize_resource_uris,
    normalize_tool_names,
    normalize_tool_result,
)

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_drift]

_TARGET_NAMES = ("reference", "gateway_proxy", "gateway_virtual")
_TARGET_TRANSPORTS = {"reference": "stdio", "gateway_proxy": "http", "gateway_virtual": "http"}


@pytest.fixture
def drift_helper(request: pytest.FixtureRequest) -> Callable[[str], AsyncContextManager[Client]]:
    """Return a helper that, given a target name, produces a Client context manager.

    Target fixtures are pulled lazily via ``_build_target`` (imported from
    conftest) — a target that skips (gateway unreachable, etc.) raises
    ``pytest.skip.Exception``, which the caller catches to mark that
    target as unavailable for the probe.
    """
    from .conftest import _build_target  # lazy — avoids an import cycle

    def _helper(target_name: str) -> AsyncContextManager[Client]:
        target = _build_target(target_name, request)
        return target.client(_TARGET_TRANSPORTS[target_name])

    return _helper


async def _collect(drift_helper: Callable, collect_fn: Callable) -> dict[str, Optional[Any]]:
    """Run ``collect_fn(client)`` against each target. Unavailable → None.

    Catches ``pytest.skip.Exception`` specifically (that's what ``pytest.skip(...)``
    raises via the ``_pytest.outcomes.Skipped`` BaseException subclass — a
    plain ``except Exception`` would let it escape and fail the drift test
    outright). Real bugs in the probe — crashes, assertion errors, name
    errors — are recorded with their text into the result so the drift
    diff surfaces the root cause instead of silently dropping the target.
    """
    out: dict[str, Optional[Any]] = {}
    skip_exc = pytest.skip.Exception  # type: ignore[attr-defined]
    for name in _TARGET_NAMES:
        try:
            async with drift_helper(name) as client:
                out[name] = await collect_fn(client)
        except skip_exc:
            out[name] = None
        except Exception as exc:  # noqa: BLE001 — record, don't swallow
            out[name] = {"_probe_error": f"{type(exc).__name__}: {exc}"[:200]}
    return out


# ---------------------------------------------------------------------------
# Drift probes
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=False,
    reason=("GAP-008: gateway federation drops boom/bump_subscribable/mutate_tool_list/" "long_running from upstream — expected drift until federation filter is " "understood or fixed."),
)
async def test_drift_tool_names(drift_helper) -> None:
    """Normalized tool-name sets agree across every available target."""

    async def _probe(client: Client) -> list[str]:
        return normalize_tool_names(await client.list_tools())

    results = await _collect(drift_helper, _probe)
    assert_drift_free(results, probe="list_tools.names")


@pytest.mark.xfail(
    strict=False,
    reason=("GAP-009: gateway federates resources incompletely (static visible on " "gateway_proxy but not gateway_virtual; templates missing on both). Drift " "expected until GAP-009 closes."),
)
async def test_drift_resource_uris(drift_helper) -> None:
    """Resource-URI sets agree across targets."""

    async def _probe(client: Client) -> list[str]:
        return normalize_resource_uris(await client.list_resources())

    results = await _collect(drift_helper, _probe)
    assert_drift_free(results, probe="list_resources.uris")


@pytest.mark.xfail(
    strict=False,
    reason=("GAP-006: gateway federation does not surface upstream prompts — drift " "between reference and gateway targets is expected until the gap closes."),
)
async def test_drift_prompt_names(drift_helper) -> None:
    """Prompt-name sets agree across targets."""

    async def _probe(client: Client) -> list[str]:
        return normalize_prompt_names(await client.list_prompts())

    results = await _collect(drift_helper, _probe)
    assert_drift_free(results, probe="list_prompts.names")


async def test_drift_echo_call(drift_helper) -> None:
    """Calling ``echo`` returns the same text across every target."""

    async def _probe(client: Client) -> dict[str, Any]:
        name = await resolve_tool(client, "echo")
        if name is None:
            return {"_unavailable": "echo not advertised"}
        result = await client.call_tool_mcp(name=name, arguments={"message": "drift-probe"})
        return normalize_tool_result(result)

    results = await _collect(drift_helper, _probe)
    assert_drift_free(results, probe="tools/call echo")


async def test_drift_add_call(drift_helper) -> None:
    """Calling ``add`` returns the same result across every target."""

    async def _probe(client: Client) -> dict[str, Any]:
        name = await resolve_tool(client, "add")
        if name is None:
            return {"_unavailable": "add not advertised"}
        result = await client.call_tool_mcp(name=name, arguments={"a": 7, "b": 5})
        return normalize_tool_result(result)

    results = await _collect(drift_helper, _probe)
    assert_drift_free(results, probe="tools/call add")


async def test_drift_ping(drift_helper) -> None:
    """Every reachable target responds to ping without error."""

    async def _probe(client: Client) -> str:
        await client.ping()
        return "ok"

    results = await _collect(drift_helper, _probe)
    assert_drift_free(results, probe="ping")
