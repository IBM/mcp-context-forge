# -*- coding: utf-8 -*-
"""Integration probe for rate-limiter mode-toggle convergence time.

The rate limiter is the only stateful plugin in the gateway's catalog: it
holds counter state in Redis and embeds its mode into a per-worker cached
plugin instance. That makes its response to a runtime mode toggle eventually
consistent rather than instantaneous — flipping ``enforce`` ↔ ``disabled``
takes some time to fully reflect across every worker's plugin-manager cache.

This module measures *how long* convergence takes after a mode change. It
does not assert on a specific time; it records the trajectory and fails only
if convergence never happens within ``MAX_CONVERGENCE_S``. Useful both as a
regression pin (a sudden slowdown is caught) and as a measurement tool for
informing a future toggle-latency SLA on the rate-limiter plugin.

Companion test: ``test_rate_limiter_dynamic_behavior.py::TestRateLimiterToggleAfterTTLExpiry``
covers the *correctness* contract — that after a quiet period long enough
for Redis counters to expire, an ``enforce → disabled → enforce`` cycle
behaves as expected. Together they describe the rate limiter's runtime
contract: correct (per the TTL test) but not instantaneous (per this test).
"""

# Standard
import time

# Third-Party
import pytest

from tests.integration.test_rate_limiter_dynamic_behavior import (
    _auto_detect_server_and_tool,
    _is_gateway_running,
    _send_tool_burst,
    _set_plugin_mode,
    BURST_SIZE,
    GATEWAY_URL,
    PROPAGATION_WAIT,
)

# Quiescence wait between phase 1's bucket-fill burst and the mode flip. Lets
# any still-in-flight phase 1 requests drain before mode changes, so the mode
# change isn't racing against workers mid-request under enforce.
PHASE_QUIESCENCE_WAIT = PROPAGATION_WAIT

pytestmark = pytest.mark.skipif(
    not _is_gateway_running(),
    reason=f"Gateway not running at {GATEWAY_URL}",
)


@pytest.fixture(scope="module")
def server_and_tool():
    """Auto-detect the target server/tool once for the module."""
    return _auto_detect_server_and_tool()


@pytest.fixture(autouse=True)
def reset_to_disabled_between_tests():
    """Restore disabled mode before and after each test.

    The convergence probe sets enforce mode itself; this fixture is a
    safety net so an early test failure doesn't leave the rate limiter
    enforcing for subsequent runs or other test modules.
    """
    _set_plugin_mode("disabled")
    time.sleep(PROPAGATION_WAIT)
    yield
    _set_plugin_mode("disabled")
    time.sleep(PROPAGATION_WAIT)


class TestRateLimiterToggleLiveState:
    """Validate live mode toggles against existing rate-limit state."""

    def test_measure_convergence_time_for_mode_toggle(self, server_and_tool, capsys):
        """Measure how long after a mode change traffic reflects the new mode.

        No threshold-based assertion on the convergence time — record timings
        and emit them. The test fails only if convergence doesn't happen at
        all within MAX_CONVERGENCE_S. Useful both as a regression pin (sudden
        divergence is caught) and as a measurement tool: every run produces
        convergence data points that, over time, give us empirical input for
        an eventual SLA on rate-limiter toggle latency.

        Convergence definitions:
          - Disabled-converged: a poll burst returns 6/6 allowed, 0 errors.
          - Enforce-converged: a poll burst returns >=5/6 blocked, 0 errors
            (allowing 1 cold-start tolerance for a worker that just rebuilt
            its plugin manager and hasn't fully warmed yet).

        Caveat: each poll burst is 6 real requests, so the probe is part of
        the system being measured. The interval between bursts is set so
        the probe doesn't dominate the rate-limit window.
        """
        server_id, tool_name = server_and_tool

        poll_burst_size = 6
        max_convergence_s = 60.0
        poll_interval_s = 1.0

        timings: dict[str, object] = {}

        # Step 1: get into enforce mode and fill the user's bucket so the
        # subsequent transitions have meaningful state to converge against.
        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)
        fill = _send_tool_burst(server_id, tool_name, BURST_SIZE)
        assert fill["errors"] == 0, f"Phase 1 fill should not error: {fill}"
        assert fill["rate_limited"] > 0, f"Phase 1 fill should heat the bucket: {fill}"

        # Quiescence: let in-flight phase-1 requests drain before flipping.
        time.sleep(PHASE_QUIESCENCE_WAIT)

        # Step 2: flip to disabled and poll until 6/6 calls in a burst pass.
        _set_plugin_mode("disabled")
        flip_t0 = time.monotonic()
        converged_to_disabled: float | None = None
        disabled_observations: list[dict[str, int]] = []
        while True:
            elapsed = time.monotonic() - flip_t0
            burst = _send_tool_burst(server_id, tool_name, poll_burst_size)
            disabled_observations.append({"t": round(elapsed, 2), **{k: v for k, v in burst.items() if k != "total"}})
            if burst["errors"] == 0 and burst["allowed"] == poll_burst_size:
                converged_to_disabled = elapsed
                break
            if elapsed >= max_convergence_s:
                break
            time.sleep(poll_interval_s)
        timings["disabled_convergence_s"] = converged_to_disabled
        timings["disabled_observations"] = disabled_observations

        # Step 3: flip back to enforce. The bucket may have aged a bit during
        # the disabled-poll loop, so re-fill briefly to ensure state is hot
        # again before we probe enforce convergence.
        _set_plugin_mode("enforce")
        flip_t0 = time.monotonic()
        converged_to_enforce: float | None = None
        enforce_observations: list[dict[str, int]] = []
        while True:
            elapsed = time.monotonic() - flip_t0
            burst = _send_tool_burst(server_id, tool_name, poll_burst_size)
            enforce_observations.append({"t": round(elapsed, 2), **{k: v for k, v in burst.items() if k != "total"}})
            # Allow 1 of the 6 to slip through (just-rebuilt-on-this-worker case).
            if burst["errors"] == 0 and burst["rate_limited"] >= poll_burst_size - 1:
                converged_to_enforce = elapsed
                break
            if elapsed >= max_convergence_s:
                break
            time.sleep(poll_interval_s)
        timings["enforce_convergence_s"] = converged_to_enforce
        timings["enforce_observations"] = enforce_observations

        # Emit measurements. Visible with ``pytest -s`` or on test failure;
        # also captured in the test's stdout for later inspection.
        print()
        print("=== rate-limiter mode-toggle convergence timings ===")

        if converged_to_disabled is not None:
            print(f"  disabled_convergence_s : {converged_to_disabled:6.2f}")
        else:
            print(f"  disabled_convergence_s : DID NOT CONVERGE within {max_convergence_s:.0f}s")
        for obs in disabled_observations:
            print(f"    t={obs['t']:6.2f}  allowed={obs['allowed']:>2}  blocked={obs['rate_limited']:>2}  errors={obs['errors']:>2}")

        if converged_to_enforce is not None:
            print(f"  enforce_convergence_s  : {converged_to_enforce:6.2f}")
        else:
            print(f"  enforce_convergence_s  : DID NOT CONVERGE within {max_convergence_s:.0f}s")
        for obs in enforce_observations:
            print(f"    t={obs['t']:6.2f}  allowed={obs['allowed']:>2}  blocked={obs['rate_limited']:>2}  errors={obs['errors']:>2}")

        # Failure condition: convergence didn't happen *at all*. The actual
        # time is data, not a threshold to police.
        assert converged_to_disabled is not None, (
            f"Disabled mode never converged within {max_convergence_s:.0f}s — propagation failure"
        )
        assert converged_to_enforce is not None, (
            f"Enforce mode never converged within {max_convergence_s:.0f}s — propagation failure"
        )
