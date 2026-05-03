# -*- coding: utf-8 -*-
"""Multi-replica wipe-on-disable convergence probe via Redis pubsub only.

Companion to ``test_rate_limiter_toggle_live_state.py`` (Layer C). That
probe drives mode toggles + traffic via the gateway's HTTP+MCP path —
which means every probe burst is amplified by the MCP STREAMABLEHTTP
transport (one user request → ~9-16 internal hook fires), and convergence
measurement is part of the system being measured.

This probe takes a different angle: bypass HTTP, MCP, admin auth, and
JWT entirely.  It talks *only* to Redis — the same broker every gateway
replica's plugin-invalidation listener subscribes to in production.
The test:

  1. Pre-conditions Redis with a counter key (a "user has hit the limiter"
     state) and the mode key set to ``enforce``.
  2. Triggers the mode change exactly the way ``publish_plugin_mode_change``
     does: SETs the mode key to ``disabled``, then PUBLISHes a JSON
     ``mode_change`` frame on ``plugin:invalidation``.
  3. Polls Redis for the counter key and records the elapsed time until
     the key disappears.

Every running gateway replica's plugin-invalidation listener receives
the broadcast and runs ``invalidate_all_plugin_managers`` →
``factory.invalidate_all`` → per-context ``reload_tenant`` →
``manager.shutdown`` → ``plugin.shutdown`` → wipe.  Single-flight on the
plugin's wipe-lock means exactly one replica wins and clears the
counter; the rest skip cleanly.

What this gives us that Layer C cannot:

  * **No amplification.**  The probe is one PUBLISH and N polls of a
    single key — none of which exercise the MCP transport.  The
    convergence time we measure is the wipe-on-disable claim itself,
    not "wipe-on-disable plus the cost of measuring it."
  * **True multi-replica behaviour.**  The standard ``docker-compose.yml``
    runs ``GATEWAY_REPLICAS:-3`` (3 gateway processes by default), each
    with its own plugin-manager cache and its own invalidation listener.
    A single PUBLISH fans out to all of them — exactly the production
    flow.

Skip behaviour:

  * Skips when the gateway stack isn't running (no point publishing if
    no subscriber will pick it up).
  * Skips when Redis isn't reachable at the expected URL.
  * Does **not** skip when wipe-on-disable code is missing from the
    gateway's installed cpex-rate-limiter — instead, the test fails
    with a clear timeout message.  That's the right semantics: in a
    deployment that has wipe enabled, this test failing is a real
    regression, not "test infrastructure missing."

Once the cpex-plugins wipe-on-disable PR merges and the wheel ships on
PyPI (or gets pulled by ``--extra plugins``), this test runs against
the standard ``docker-compose.yml`` stack with no override and no
derivative image.  Today, point it at a stack running the wipe-enabled
derivative image (see ``wipe-test/README.md`` — local-only, never
committed).
"""

# Standard
import asyncio
import json
import os
import socket
import time

# Third-Party
import pytest

# First-Party (test helpers)
from tests.integration.test_rate_limiter_dynamic_behavior import (
    GATEWAY_URL,
    _is_gateway_running,
)


def _redis_reachable(host: str = "127.0.0.1", port: int = 6379, timeout: float = 0.2) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# Defaults match the standard docker-compose.yml stack: gateway replicas
# share a single Redis exposed on host port 6379, DB 0.  Override via
# REDIS_URL env var if your stack publishes elsewhere.
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

# Constants matching the framework's wire contract.  These intentionally
# duplicate the values from mcpgateway.plugins.framework rather than
# importing them — the test is verifying that publisher and subscriber
# agree on the wire format, so importing the publisher's constants would
# defeat the purpose.
INVALIDATION_CHANNEL = "plugin:invalidation"
PLUGIN_NAME = "RateLimiterPlugin"  # matches plugins/config.yaml's name field
MODE_KEY = f"plugin:{PLUGIN_NAME}:mode"

# Per-process unique counter key so concurrent test runs / interactive
# stack use don't collide on the same key.
TEST_USER = f"converge-probe-{os.getpid()}"
COUNTER_KEY = f"rl:user:{TEST_USER}:60"

# 30s budget — generous compared to the ~22s baseline observed in PR
# #4511 with no wipe.  With wipe, convergence is expected to land in
# under a second.
MAX_CONVERGENCE_S = 30.0


pytestmark = [
    pytest.mark.skipif(
        not _is_gateway_running(),
        reason=f"Gateway not running at {GATEWAY_URL}",
    ),
    pytest.mark.skipif(
        not _redis_reachable(),
        reason="Redis not reachable on 127.0.0.1:6379 (the gateway stack's broker)",
    ),
]


@pytest.mark.asyncio
async def test_wipe_on_disable_converges_via_redis_pubsub_only():
    """Drive a mode-change toggle externally via Redis pubsub only and
    measure how long the wipe takes to fire end-to-end across every
    running gateway replica.

    Records convergence time = elapsed from PUBLISH to "counter key is
    gone in Redis."  No HTTP, no MCP, no admin endpoint, no auth.  Just
    the Redis bus that every gateway replica's plugin-invalidation
    listener subscribes to.
    """
    # Third-Party
    import redis.asyncio as aioredis  # noqa: PLC0415

    client = aioredis.from_url(REDIS_URL, decode_responses=True)

    try:
        # ── Pre-condition ──────────────────────────────────────────────
        # Mode is enforce; a counter key exists (deposited directly via
        # Redis SET — bypasses the gateway entirely).
        await client.set(MODE_KEY, "enforce", ex=86400)
        await client.set(COUNTER_KEY, "5", ex=120)
        assert await client.exists(COUNTER_KEY), (
            "pre-condition setup failed: counter key was not written"
        )

        # ── Trigger ────────────────────────────────────────────────────
        # Replicate publish_plugin_mode_change's behaviour exactly:
        # SET mode key first (so listeners that re-read it on receipt
        # see the new value), then PUBLISH the invalidation frame.
        await client.set(MODE_KEY, "disabled", ex=86400)
        publish_t0 = time.monotonic()
        await client.publish(
            INVALIDATION_CHANNEL,
            json.dumps(
                {
                    "type": "mode_change",
                    "plugin": PLUGIN_NAME,
                    "mode": "disabled",
                    "ttl_seconds": 86400,
                }
            ),
        )

        # ── Poll until the wipe lands ──────────────────────────────────
        converged_s: float | None = None
        observations: list[dict[str, object]] = []
        while time.monotonic() - publish_t0 < MAX_CONVERGENCE_S:
            elapsed = round(time.monotonic() - publish_t0, 2)
            exists = bool(await client.exists(COUNTER_KEY))
            observations.append({"t": elapsed, "counter_exists": exists})
            if not exists:
                converged_s = elapsed
                break
            await asyncio.sleep(0.1)

        # ── Trajectory output ──────────────────────────────────────────
        # Always print so the convergence data is visible whether the
        # test passes or fails.  Pytest captures stdout; -s shows it.
        print("\nConvergence trajectory:")
        # Cap printed observations so the log stays readable on a long
        # timeout — first 5, last 5, gap marker.
        if len(observations) <= 12:
            shown = observations
        else:
            shown = observations[:5] + [{"t": "...", "counter_exists": "..."}] + observations[-5:]
        for obs in shown:
            print(f"  t={obs['t']:>6}  counter_exists={obs['counter_exists']}")

        if converged_s is not None:
            print(f"\n✓ Wipe converged in {converged_s:.2f}s")
        else:
            print(f"\n✗ Wipe did NOT converge within {MAX_CONVERGENCE_S}s")

        # ── Assertion ──────────────────────────────────────────────────
        assert converged_s is not None, (
            f"expected wipe-on-disable to clear {COUNTER_KEY} within "
            f"{MAX_CONVERGENCE_S}s of PUBLISH; either the running gateway's "
            f"cpex-rate-limiter does not include the wipe-on-disable code, "
            f"or the broadcast on '{INVALIDATION_CHANNEL}' is not reaching "
            f"the replicas' invalidation listeners. "
            f"Trajectory: {observations}"
        )
    finally:
        # Restore mode to enforce + drop any residual counter so
        # subsequent runs / interactive stack use start clean.
        try:
            await client.set(MODE_KEY, "enforce", ex=86400)
        except Exception:
            pass
        try:
            await client.delete(COUNTER_KEY)
        except Exception:
            pass
        await client.aclose()
