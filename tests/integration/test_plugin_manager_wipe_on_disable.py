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


@pytest.mark.asyncio
async def test_publish_plugin_mode_change_round_trips_to_wipe(
    redis_url_for_test, monkeypatch
):
    """Real PUBLISH on the framework's invalidation channel must round-trip
    to wipe the plugin's counters end-to-end.

    Distinct from
    ``test_factory_reload_tenant_wipes_rate_limiter_counters_on_disable``
    (B-0): that test sets the mode key in Redis directly and calls
    ``factory.reload_tenant`` directly.  This test exercises the
    publish/subscribe round-trip — calls ``publish_plugin_mode_change``
    (the function the admin handler invokes), captures the resulting
    message off the real Redis channel, and feeds it through
    ``_handle_invalidation_message`` (the function the gateway's
    listener calls).

    What this pins (the boundary B-0 doesn't exercise):

      * The publisher's actual wire format on the channel — channel
        name, JSON keys, value types — matches what
        ``_handle_invalidation_message`` accepts and routes to
        ``invalidate_all_plugin_managers`` -> ``factory.invalidate_all``
        -> ``reload_tenant`` -> ``manager.shutdown`` -> ``plugin.shutdown``.
      * A regression where ``publish_plugin_mode_change`` and the
        handler drift on format (e.g. one renames a JSON key without
        the other) would still pass every existing mocked-JSON pubsub
        test, because those tests construct the message bytes
        themselves.  This test PUBLISHes via the real publisher and
        receives off the real channel, so any drift breaks the round-trip.
    """
    # Skip-guards (same shape as the B-0 test above).
    try:
        from cpex_rate_limiter.rate_limiter import RateLimiterPlugin  # noqa: PLC0415
    except ImportError:
        pytest.skip("cpex-rate-limiter not installed in test venv")

    if not hasattr(RateLimiterPlugin, "_wipe_my_counters"):
        pytest.skip(
            "installed cpex-rate-limiter does not include wipe-on-disable code path "
            "(see wipe-test/README.md to install the wipe-enabled wheel)"
        )

    # Imports — local, same pattern as B-0.
    # Third-Party
    import redis.asyncio as aioredis  # noqa: PLC0415

    # First-Party
    import mcpgateway.plugins.framework as framework  # noqa: PLC0415
    from mcpgateway.plugins.framework import (  # noqa: PLC0415
        GlobalContext,
        ToolPreInvokePayload,
        publish_plugin_mode_change,
    )
    from mcpgateway.plugins.framework._redis import (  # noqa: PLC0415
        set_shared_redis_provider,
    )
    from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory  # noqa: PLC0415

    # YAML uses {{ env.REDIS_URL }} — inject the test redis URL via env so the
    # plugin loader resolves the placeholder at construction time.
    monkeypatch.setenv("REDIS_URL", redis_url_for_test)

    # Wire the framework's globals to point at our test setup.  Two need to be
    # set: (1) the framework's shared-redis provider, so
    # ``publish_plugin_mode_change`` and the invalidation listener get a
    # client pointed at the test Redis (the framework uses a dependency-
    # inversion shim — see ``mcpgateway/plugins/framework/_redis.py`` — not
    # ``mcpgateway.utils.redis_client._client`` directly); (2)
    # ``framework._plugin_manager_factory`` so the handler dispatches
    # ``invalidate_all`` against our factory rather than a real production
    # one.  Both restored in the finally block.
    test_redis_for_framework = aioredis.from_url(redis_url_for_test, decode_responses=True)

    async def _test_redis_provider():
        return test_redis_for_framework

    set_shared_redis_provider(_test_redis_provider)

    factory = TenantPluginManagerFactory(yaml_path=_FIXTURE_YAML)
    original_factory = framework._plugin_manager_factory
    framework._plugin_manager_factory = factory

    # Test-side redis + pubsub for capturing the published message off the
    # channel.  Independent client to keep the test's pubsub state separate
    # from the framework's.
    redis_client = aioredis.from_url(redis_url_for_test, decode_responses=True)
    pubsub = redis_client.pubsub()

    try:
        await redis_client.flushdb()

        # ── Phase 1: enforce — deposit a counter key (same as B-0) ──
        manager = await factory.get_manager(context_id="b05_ctx")
        ctx = GlobalContext(request_id="r1", user="alice")
        payload = ToolPreInvokePayload(name="t", arguments={})
        for _ in range(2):
            await manager.invoke_hook("tool_pre_invoke", payload, ctx)

        keys_pre = await redis_client.keys("rl:*")
        assert any("alice" in k for k in keys_pre), (
            f"alice's counter key should exist after Phase 1; got {keys_pre}"
        )

        # ── Phase 2: subscribe + real publish + receive + hand off to handler ──
        await pubsub.subscribe(framework._REDIS_INVALIDATION_CHANNEL)
        # redis-py emits a subscribe-confirmation as the first frame; drain it
        # so it doesn't get mistaken for the data message we're about to send.
        _ = await pubsub.get_message(timeout=1.0)

        published = await publish_plugin_mode_change("RateLimiter", "disabled")
        assert published is True, (
            "publish_plugin_mode_change must return True against the test "
            "Redis — if False, the framework's redis client wiring "
            "(rc._client) is wrong and the rest of this test would silently "
            "skip the publish path"
        )

        # Loop get_message until we receive the actual data frame.  The
        # publish/subscribe path is async on the Redis side, so the message
        # may not arrive on the very first poll; we budget ~2s total.
        message = None
        for _ in range(20):
            frame = await pubsub.get_message(timeout=0.1)
            if frame is not None and frame.get("type") == "message":
                message = frame
                break
        assert message is not None, (
            "expected an invalidation message on the channel after "
            "publish_plugin_mode_change; check that "
            "framework._REDIS_INVALIDATION_CHANNEL hasn't drifted"
        )

        # The core round-trip assertion: drive the framework's handler with the
        # message we *actually received off the wire*.  If the publisher and
        # handler disagree on format, this is where it shows up.
        # ``_handle_invalidation_message`` awaits the full cascade
        # (invalidate_all_plugin_managers -> factory.invalidate_all ->
        # reload_tenant -> manager.shutdown -> plugin.shutdown -> wipe), so by
        # the time it returns the wipe has run.
        await framework._handle_invalidation_message(message)

        # ── Phase 3: counters wiped ──
        keys_post = await redis_client.keys("rl:*")
        assert keys_post == [], (
            "publish_plugin_mode_change -> handler -> reload -> wipe chain "
            f"must clear alice's counter; got {keys_post}"
        )
    finally:
        try:
            await pubsub.unsubscribe()
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass
        await redis_client.aclose()
        await test_redis_for_framework.aclose()
        await factory.shutdown()
        framework._plugin_manager_factory = original_factory
        set_shared_redis_provider(None)
