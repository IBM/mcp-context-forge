# -*- coding: utf-8 -*-
"""Integration test for the framework -> plugin wipe-on-disable boundary.

This test sits between the framework-boundary unit tests in
``tests/unit/mcpgateway/plugins/framework/test_tenant_plugin_manager_tool_scoped.py``
(which use stub plugins) and the full HTTP-driven integration tests in
``test_rate_limiter_dynamic_behavior.py`` /
``test_rate_limiter_toggle_live_state.py`` (which require a running
gateway with admin auth).

It loads a real ``cpex-rate-limiter`` plugin into a real
``TenantPluginManagerFactory`` against a real Redis, deposits counter
keys via ``manager.invoke_hook``, simulates an operator mode toggle
to ``disabled`` by setting the framework's mode key in Redis directly,
then drives ``factory.reload_tenant`` and asserts the counter keys
were wiped.

What this pins (the boundary between Layer A and Layer B-1):

  * ``factory.reload_tenant`` -> manager.shutdown -> registry.shutdown
    -> plugin.shutdown all fire in sequence against a real plugin.
  * The rate-limiter plugin's wipe-on-disable code path is reached,
    reads the mode key, and clears its counters from Redis.

What this does *not* test (out of scope):

  * The admin HTTP endpoint -> reload_tenant pathway (covered by
    ``test_rate_limiter_dynamic_behavior.py``).
  * Pub/sub-driven multi-worker fan-out (covered by
    ``test_plugin_runtime_redis.py::TestPubSubEvictionRedis``).
  * Convergence timing (covered by
    ``test_rate_limiter_toggle_live_state.py``).

Skips cleanly when:
  * Redis is unreachable and docker is unavailable.
  * The installed ``cpex-rate-limiter`` wheel does not include the
    wipe-on-disable code path (PyPI baseline before the wipe-on-disable
    PR merges; install the wheel from
    ``cpex-plugins:feat/rate-limiter-wipe-on-disable-only`` to exercise
    it -- see ``wipe-test/README.md``).
"""

# Standard
import socket
import subprocess
import time

# Third-Party
import pytest


_REDIS_HOST = "127.0.0.1"
# Dedicated host port for this test's container — avoids collisions with
# any other Redis (or Redis-shaped) listener on the standard 6379, including
# the local TLS smoke-test stack from wipe-test/.
_REDIS_PORT = 16380
_REDIS_CONTAINER_NAME = "pytest-plugin-mgr-wipe-redis"
_FIXTURE_YAML = "./tests/integration/fixtures/configs/rate_limiter_redis_only.yaml"


def _redis_port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _redis_responds_to_ping(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if Redis at host:port answers PING with PONG.

    TCP-port-open is not sufficient: Docker's port mapping can succeed
    while the redis process is started with ``--port 0`` (plain TCP
    disabled), in which case clients see "Connection closed by server"
    on first command. Driving a real PING is the only reliable signal.
    """
    try:
        # Third-Party
        import redis as _redis_sync  # noqa: PLC0415
    except Exception:
        return False
    try:
        client = _redis_sync.Redis(
            host=host,
            port=port,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
        try:
            return bool(client.ping())
        finally:
            try:
                client.close()
            except Exception:
                pass
    except Exception:
        return False


@pytest.fixture(scope="module")
def redis_url_for_test():
    """Yield a Redis URL pointing at a real Redis instance.

    Always starts a dedicated Docker container on a non-standard host
    port (16380) so the test is hermetic — no risk of collision with a
    developer's local Redis on 6379, the local TLS smoke-test stack, or
    any other Redis-shaped listener. PING confirms readiness; TCP alone
    isn't enough (Docker's port mapping can succeed while the redis
    process inside has plain TCP disabled).

    Skips cleanly if docker is unavailable.
    """
    container_id = None
    try:
        res = subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "-p", f"{_REDIS_PORT}:6379",
                "--name", _REDIS_CONTAINER_NAME,
                "redis:7",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        container_id = res.stdout.strip()
    except Exception as exc:
        pytest.skip(f"Docker unavailable for Redis container: {exc}")

    for _ in range(50):
        if _redis_port_open(_REDIS_HOST, _REDIS_PORT) and _redis_responds_to_ping(_REDIS_HOST, _REDIS_PORT):
            break
        time.sleep(0.1)
    else:
        if container_id:
            subprocess.run(["docker", "stop", container_id], check=False)
        pytest.skip("Redis did not become ready in time")

    yield f"redis://{_REDIS_HOST}:{_REDIS_PORT}/14"  # DB 14 — isolated

    if container_id:
        subprocess.run(["docker", "stop", container_id], check=False)


@pytest.mark.asyncio
async def test_factory_reload_tenant_wipes_rate_limiter_counters_on_disable(
    redis_url_for_test, monkeypatch
):
    """Direct ``factory.reload_tenant`` against a real rate-limiter plugin
    + real Redis must wipe the plugin's counters when mode key says
    ``disabled``.

    Phase 1 deposits counter keys via the manager's hook dispatch path.
    Phase 2 sets the framework's mode key in Redis directly (skipping
    the admin HTTP endpoint and pub/sub, which are out of scope here)
    and drives ``factory.reload_tenant``.  Phase 3 asserts the counter
    keys are gone — proving the framework's rebuild path reached the
    plugin's wipe-on-disable code path.
    """
    # Skip-guards before any imports that might fail or any Redis writes.
    try:
        from cpex_rate_limiter.rate_limiter import RateLimiterPlugin  # noqa: PLC0415
    except ImportError:
        pytest.skip("cpex-rate-limiter not installed in test venv")

    if not hasattr(RateLimiterPlugin, "_wipe_my_counters"):
        pytest.skip(
            "installed cpex-rate-limiter does not include wipe-on-disable code path "
            "(see wipe-test/README.md to install the wipe-enabled wheel)"
        )

    # Imports — local so the module-level skip path is fast and the
    # test doesn't pay for these imports if it skips.
    # Third-Party
    import redis.asyncio as aioredis  # noqa: PLC0415

    # First-Party
    from mcpgateway.plugins.framework import (  # noqa: PLC0415
        GlobalContext,
        ToolPreInvokePayload,
    )
    from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory  # noqa: PLC0415

    # The yaml uses {{ env.REDIS_URL }}; inject the test redis URL via
    # env so the plugin loader resolves the placeholder at construction.
    monkeypatch.setenv("REDIS_URL", redis_url_for_test)

    factory = TenantPluginManagerFactory(yaml_path=_FIXTURE_YAML)
    redis_client = aioredis.from_url(redis_url_for_test, decode_responses=True)

    try:
        # Clean slate — drop both rl:* counters and any stale mode keys.
        await redis_client.flushdb()

        # ── Phase 1: enforce — deposit counter keys via the manager ──
        manager = await factory.get_manager(context_id="wipe_boundary_ctx")
        assert manager is not None

        ctx = GlobalContext(request_id="r1", user="alice")
        payload = ToolPreInvokePayload(name="t", arguments={})

        # A couple of hook calls — under 30/m the bucket won't saturate;
        # we just want a counter key in Redis to wipe.
        for _ in range(2):
            await manager.invoke_hook("tool_pre_invoke", payload, ctx)

        keys_pre_disable = await redis_client.keys("rl:*")
        assert any("alice" in k for k in keys_pre_disable), (
            f"alice's counter key should exist after Phase 1; got {keys_pre_disable}"
        )

        # ── Phase 2: simulate operator disable + drive the rebuild ──
        await redis_client.set("plugin:RateLimiter:mode", "disabled")

        manager_new = await factory.reload_tenant(context_id="wipe_boundary_ctx")
        assert manager_new is not None
        assert manager_new is not manager, (
            "reload_tenant must construct a new manager instance"
        )

        # ── Phase 3: counters must be gone ──
        keys_post_wipe = await redis_client.keys("rl:*")
        assert keys_post_wipe == [], (
            "factory.reload_tenant under mode=disabled must wipe the plugin's "
            f"counters via the manager.shutdown -> plugin.shutdown -> wipe path; "
            f"expected [], got {keys_post_wipe}"
        )
    finally:
        await redis_client.aclose()
        await factory.shutdown()
