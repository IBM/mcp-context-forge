# -*- coding: utf-8 -*-
"""Unit tests for ``mcpgateway.runtime_state``."""

# Standard
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.runtime_state import (
    PROPAGATION_DEGRADED,
    PROPAGATION_REDIS,
    RUNTIME_KINDS,
    RUNTIME_STATE_CHANNEL,
    SUPPORTED_OVERRIDE_MODES,
    ModeChange,
    RuntimeState,
    RuntimeStateCoordinator,
    RuntimeStateError,
    _hint_key,
    _version_key,
    get_runtime_state,
    reset_runtime_state_coordinator_for_tests,
    reset_runtime_state_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Ensure each test starts with fresh state and coordinator singletons."""
    reset_runtime_state_for_tests()
    reset_runtime_state_coordinator_for_tests()
    yield
    reset_runtime_state_for_tests()
    reset_runtime_state_coordinator_for_tests()


@pytest.mark.asyncio
async def test_apply_local_records_change():
    state = RuntimeState()
    change = await state.apply_local("mcp", "edge", initiator_user="alice@example.com", version=1)
    assert change.runtime == "mcp"
    assert change.mode == "edge"
    assert change.version == 1
    assert change.initiator_user == "alice@example.com"
    assert change.initiator_pod == state.pod_id
    assert state.override_mode("mcp") == "edge"
    assert state.version("mcp") == 1
    assert state.last_change("mcp") == change


@pytest.mark.asyncio
async def test_apply_local_isolates_runtimes():
    state = RuntimeState()
    await state.apply_local("mcp", "edge", initiator_user=None, version=1)
    assert state.override_mode("mcp") == "edge"
    assert state.override_mode("a2a") is None
    await state.apply_local("a2a", "shadow", initiator_user=None, version=7)
    assert state.override_mode("a2a") == "shadow"
    assert state.version("a2a") == 7
    assert state.version("mcp") == 1  # unchanged


@pytest.mark.asyncio
async def test_apply_local_rejects_unsupported_mode():
    state = RuntimeState()
    with pytest.raises(ValueError):
        await state.apply_local("mcp", "off", initiator_user=None, version=1)


@pytest.mark.asyncio
async def test_apply_local_rejects_unknown_runtime():
    state = RuntimeState()
    with pytest.raises(ValueError):
        await state.apply_local("rpc", "edge", initiator_user=None, version=1)


@pytest.mark.asyncio
async def test_apply_remote_advances_state_when_newer():
    state = RuntimeState()
    payload = {
        "runtime": "mcp",
        "mode": "edge",
        "version": 5,
        "initiator_pod": "other-pod",
        "initiator_user": "bob",
        "timestamp": 1700000000.0,
    }
    change = await state.apply_remote(payload)
    assert change is not None
    assert change.mode == "edge"
    assert change.version == 5
    assert state.override_mode("mcp") == "edge"


@pytest.mark.asyncio
async def test_apply_remote_drops_stale_versions():
    state = RuntimeState()
    await state.apply_local("mcp", "edge", initiator_user=None, version=10)
    payload = {
        "runtime": "mcp",
        "mode": "shadow",
        "version": 5,
        "initiator_pod": "other-pod",
    }
    assert await state.apply_remote(payload) is None
    assert state.override_mode("mcp") == "edge"


@pytest.mark.asyncio
async def test_apply_remote_dedupes_self_messages():
    state = RuntimeState()
    payload = {
        "runtime": "mcp",
        "mode": "edge",
        "version": 99,
        "initiator_pod": state.pod_id,
    }
    assert await state.apply_remote(payload) is None
    assert state.override_mode("mcp") is None


@pytest.mark.asyncio
async def test_apply_remote_rejects_malformed_payload():
    state = RuntimeState()
    assert await state.apply_remote({"mode": "edge"}) is None  # missing runtime/version
    assert await state.apply_remote({"runtime": "mcp", "mode": "off", "version": 1, "initiator_pod": "x"}) is None
    assert await state.apply_remote({"runtime": "rpc", "mode": "edge", "version": 1, "initiator_pod": "x"}) is None
    assert state.override_mode("mcp") is None


# ---------------------------------------------------------------------------
# RuntimeStateCoordinator
# ---------------------------------------------------------------------------


def _make_redis_mock(get_value: Any = None, incr_value: int = 1) -> MagicMock:
    """Build an async Redis mock with the methods the coordinator uses."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=get_value)
    redis.set = AsyncMock(return_value=True)
    redis.incr = AsyncMock(return_value=incr_value)
    redis.publish = AsyncMock(return_value=1)
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock(return_value=None)
    pubsub.unsubscribe = AsyncMock(return_value=None)
    pubsub.aclose = AsyncMock(return_value=None)
    pubsub.get_message = AsyncMock(side_effect=__import__("asyncio").TimeoutError())
    redis.pubsub = MagicMock(return_value=pubsub)
    return redis


@pytest.mark.asyncio
async def test_coordinator_falls_back_when_redis_unavailable(monkeypatch: pytest.MonkeyPatch):
    coord = RuntimeStateCoordinator()
    monkeypatch.setattr(
        "mcpgateway.utils.redis_client.get_redis_client",
        AsyncMock(return_value=None),
    )
    await coord.start()
    assert coord.started is True
    assert coord.cluster_propagation_enabled is False
    state = __import__("mcpgateway.runtime_state", fromlist=["get_runtime_state"]).get_runtime_state()
    assert state.cluster_propagation == "disabled"
    await coord.stop()


@pytest.mark.asyncio
async def test_coordinator_publish_no_op_when_redis_missing(monkeypatch: pytest.MonkeyPatch):
    coord = RuntimeStateCoordinator()
    monkeypatch.setattr(
        "mcpgateway.utils.redis_client.get_redis_client",
        AsyncMock(return_value=None),
    )
    await coord.start()
    change = ModeChange(runtime="mcp", version=1, mode="edge", initiator_user="x", initiator_pod="p", timestamp=0.0)
    # Must not raise even though Redis is None.
    await coord.publish(change)


@pytest.mark.asyncio
async def test_coordinator_publish_writes_pubsub_and_hint(monkeypatch: pytest.MonkeyPatch):
    redis = _make_redis_mock()
    monkeypatch.setattr(
        "mcpgateway.utils.redis_client.get_redis_client",
        AsyncMock(return_value=redis),
    )
    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        assert coord.cluster_propagation_enabled is True
        change = ModeChange(runtime="a2a", version=42, mode="edge", initiator_user="alice", initiator_pod="pod-1", timestamp=1.0)
        await coord.publish(change)
        redis.publish.assert_awaited_once()
        published_channel, published_payload = redis.publish.await_args.args
        assert published_channel == RUNTIME_STATE_CHANNEL
        decoded = orjson.loads(published_payload)
        assert decoded["runtime"] == "a2a"
        assert decoded["mode"] == "edge"
        assert decoded["version"] == 42
        redis.set.assert_awaited_once()
        set_args = redis.set.await_args
        assert set_args.args[0] == _hint_key("a2a")
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_coordinator_next_version_uses_redis_counter(monkeypatch: pytest.MonkeyPatch):
    redis = _make_redis_mock(incr_value=99)
    monkeypatch.setattr(
        "mcpgateway.utils.redis_client.get_redis_client",
        AsyncMock(return_value=redis),
    )
    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        version = await coord.next_version("mcp", current_version=10)
        assert version == 99
        redis.incr.assert_awaited_once_with(_version_key("mcp"))
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_coordinator_next_version_local_when_redis_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "mcpgateway.utils.redis_client.get_redis_client",
        AsyncMock(return_value=None),
    )
    coord = RuntimeStateCoordinator()
    await coord.start()
    assert await coord.next_version("mcp", current_version=10) == 11


@pytest.mark.asyncio
async def test_coordinator_reconciles_from_hint(monkeypatch: pytest.MonkeyPatch):
    hint_payload = orjson.dumps(
        {
            "runtime": "mcp",
            "mode": "edge",
            "version": 17,
            "initiator_pod": "remote-pod",
            "initiator_user": "carol@example.com",
            "timestamp": 1.0,
        }
    )

    async def fake_get(key):
        if key == _hint_key("mcp"):
            return hint_payload
        return None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr(
        "mcpgateway.utils.redis_client.get_redis_client",
        AsyncMock(return_value=redis),
    )

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        state = __import__("mcpgateway.runtime_state", fromlist=["get_runtime_state"]).get_runtime_state()
        assert state.override_mode("mcp") == "edge"
        assert state.version("mcp") == 17
    finally:
        await coord.stop()


def test_constants_match_kinds():
    assert RUNTIME_KINDS == frozenset({"mcp", "a2a"})
    assert SUPPORTED_OVERRIDE_MODES == frozenset({"shadow", "edge"})


# ---------------------------------------------------------------------------
# Block 1+2 follow-up coverage
# ---------------------------------------------------------------------------


def test_mode_change_post_init_rejects_bogus_runtime():
    with pytest.raises(ValueError):
        ModeChange(runtime="rpc", version=1, mode="edge", initiator_user=None, initiator_pod="p", timestamp=0.0)


def test_mode_change_post_init_rejects_bogus_mode():
    with pytest.raises(ValueError):
        ModeChange(runtime="mcp", version=1, mode="off", initiator_user=None, initiator_pod="p", timestamp=0.0)


@pytest.mark.asyncio
async def test_apply_local_drops_stale_local_version():
    """Concurrent local PATCHes can land out of order; the older one must be dropped."""
    state = RuntimeState()
    first = await state.apply_local("mcp", "edge", initiator_user="alice", version=10)
    assert first is not None and first.version == 10
    # Pretend a second PATCH allocated v=11 and landed first.
    later = await state.apply_local("mcp", "shadow", initiator_user="bob", version=11)
    assert later is not None and later.version == 11
    # Now the v=10 writer (which had been awaiting the lock) lands; must drop.
    stale = await state.apply_local("mcp", "edge", initiator_user="alice", version=10)
    assert stale is None
    assert state.version("mcp") == 11
    assert state.override_mode("mcp") == "shadow"


@pytest.mark.asyncio
async def test_coordinator_marks_propagation_degraded_when_redis_raises(monkeypatch: pytest.MonkeyPatch):
    """Configured-but-broken Redis must surface as 'degraded', not 'disabled'."""
    monkeypatch.setattr(
        "mcpgateway.utils.redis_client.get_redis_client",
        AsyncMock(side_effect=RuntimeError("redis exploded")),
    )
    coord = RuntimeStateCoordinator()
    await coord.start()
    assert coord.started is True
    assert get_runtime_state().cluster_propagation == PROPAGATION_DEGRADED


@pytest.mark.asyncio
async def test_coordinator_marks_propagation_degraded_when_subscribe_fails(monkeypatch: pytest.MonkeyPatch):
    """Pub/sub subscribe failure with Redis attached should mark degraded, not disabled.

    Also asserts ``boot_reconcile_status`` flips to ``PUBSUB_UNAVAILABLE`` for
    every runtime even though ``_reconcile_from_hint`` ran first and marked
    them all ``OK`` (the hint key was empty). Without that override, /health
    would silently advertise ``OK`` boot reconciliation while the listener was
    actually dead.
    """
    # First-Party
    from mcpgateway.runtime_state import BootReconcileStatus

    redis = _make_redis_mock()
    pubsub = redis.pubsub.return_value
    pubsub.subscribe = AsyncMock(side_effect=RuntimeError("subscribe failed"))
    monkeypatch.setattr(
        "mcpgateway.utils.redis_client.get_redis_client",
        AsyncMock(return_value=redis),
    )
    coord = RuntimeStateCoordinator()
    await coord.start()
    state = get_runtime_state()
    assert state.cluster_propagation == PROPAGATION_DEGRADED
    for kind in RUNTIME_KINDS:
        assert state.boot_reconcile_status(kind) == BootReconcileStatus.PUBSUB_UNAVAILABLE


@pytest.mark.asyncio
async def test_coordinator_publish_returns_true_when_redis_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
    coord = RuntimeStateCoordinator()
    await coord.start()
    change = ModeChange(runtime="mcp", version=1, mode="edge", initiator_user="x", initiator_pod="p", timestamp=0.0)
    assert await coord.publish(change) is True


@pytest.mark.asyncio
async def test_coordinator_publish_returns_false_on_redis_publish_error(monkeypatch: pytest.MonkeyPatch):
    redis = _make_redis_mock()
    redis.publish = AsyncMock(side_effect=RuntimeError("publish failed"))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        change = ModeChange(runtime="mcp", version=1, mode="edge", initiator_user="x", initiator_pod="p", timestamp=0.0)
        assert await coord.publish(change) is False
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_coordinator_publish_returns_false_when_hint_set_fails(monkeypatch: pytest.MonkeyPatch):
    redis = _make_redis_mock()
    redis.set = AsyncMock(side_effect=RuntimeError("set failed"))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        change = ModeChange(runtime="mcp", version=1, mode="edge", initiator_user="x", initiator_pod="p", timestamp=0.0)
        assert await coord.publish(change) is False
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_coordinator_next_version_raises_on_incr_error(monkeypatch: pytest.MonkeyPatch):
    """A bare INCR failure must not silently fall back to a colliding local version."""
    redis = _make_redis_mock()
    redis.incr = AsyncMock(side_effect=RuntimeError("incr failed"))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        with pytest.raises(RuntimeStateError):
            await coord.next_version("mcp", current_version=10)
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_coordinator_next_version_raises_when_counter_below_local(monkeypatch: pytest.MonkeyPatch):
    """If the Redis counter is below local (e.g. counter was deleted), raise rather than publish a stale version."""
    redis = _make_redis_mock(incr_value=3)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        with pytest.raises(RuntimeStateError):
            await coord.next_version("mcp", current_version=10)
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_does_not_clobber_higher_local_version(monkeypatch: pytest.MonkeyPatch):
    """Boot reconciliation must not roll local state back to a stale persisted hint."""
    state = get_runtime_state()
    await state.apply_local("mcp", "shadow", initiator_user="local", version=99)

    hint_payload = orjson.dumps({"runtime": "mcp", "mode": "edge", "version": 5, "initiator_pod": "remote-pod", "initiator_user": "remote", "timestamp": 1.0})

    async def fake_get(key):
        return hint_payload if key == _hint_key("mcp") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        # Local v=99 must win over stale hint v=5.
        assert state.version("mcp") == 99
        assert state.override_mode("mcp") == "shadow"
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_listen_loop_applies_remote_pubsub_message(monkeypatch: pytest.MonkeyPatch):
    """End-to-end pub/sub message should round-trip through the listen loop into RuntimeState."""
    redis = _make_redis_mock()
    pubsub = redis.pubsub.return_value
    payload = orjson.dumps({"runtime": "a2a", "mode": "shadow", "version": 11, "initiator_pod": "remote-pod", "initiator_user": "carol", "timestamp": 1.0})
    delivered = {"yielded": False}

    async def fake_get_message(*args, **kwargs):
        if delivered["yielded"]:
            # After the first delivery, behave like a normal idle pubsub.
            await __import__("asyncio").sleep(0.05)
            return None
        delivered["yielded"] = True
        return {"type": "message", "channel": RUNTIME_STATE_CHANNEL.encode(), "data": payload}

    pubsub.get_message = AsyncMock(side_effect=fake_get_message)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        # Give the listen loop a brief window to consume the queued message.
        for _ in range(20):
            if get_runtime_state().override_mode("a2a") == "shadow":
                break
            await __import__("asyncio").sleep(0.05)
        assert get_runtime_state().override_mode("a2a") == "shadow"
        assert get_runtime_state().version("a2a") == 11
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_cluster_propagation_surfaces_in_runtime_status_payload(monkeypatch: pytest.MonkeyPatch):
    """The /health-bound payload must include cluster_propagation so dashboards can alert on degraded."""
    from mcpgateway import version as version_module

    state = get_runtime_state()
    state.set_cluster_propagation(PROPAGATION_DEGRADED)

    mcp_payload = version_module.mcp_runtime_status_payload()
    a2a_payload = version_module.a2a_runtime_status_payload()

    assert mcp_payload["cluster_propagation"] == PROPAGATION_DEGRADED
    assert a2a_payload["cluster_propagation"] == PROPAGATION_DEGRADED


@pytest.mark.asyncio
async def test_listen_loop_downgrades_after_consecutive_failures(monkeypatch: pytest.MonkeyPatch):
    """Consecutive get_message failures must downgrade cluster_propagation to degraded."""
    import asyncio as _asyncio

    from mcpgateway.runtime_state import LISTEN_LOOP_DEGRADE_THRESHOLD

    redis = _make_redis_mock()
    pubsub = redis.pubsub.return_value
    pubsub.get_message = AsyncMock(side_effect=RuntimeError("pubsub down"))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        # Wait until the loop has registered enough failures to downgrade.
        for _ in range(60):
            if get_runtime_state().cluster_propagation == PROPAGATION_DEGRADED:
                break
            await _asyncio.sleep(0.05)
        assert get_runtime_state().cluster_propagation == PROPAGATION_DEGRADED
        assert pubsub.get_message.await_count >= LISTEN_LOOP_DEGRADE_THRESHOLD
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_listen_loop_repromotes_after_recovery(monkeypatch: pytest.MonkeyPatch):
    """A successful receive after degraded must promote cluster_propagation back to redis."""
    import asyncio as _asyncio

    from mcpgateway.runtime_state import LISTEN_LOOP_DEGRADE_THRESHOLD

    redis = _make_redis_mock()
    pubsub = redis.pubsub.return_value
    fail_count = {"n": 0}

    async def flaky_get_message(*args, **kwargs):
        if fail_count["n"] < LISTEN_LOOP_DEGRADE_THRESHOLD:
            fail_count["n"] += 1
            raise RuntimeError("pubsub down")
        # Recovery: behave like an idle pubsub (None message).
        await _asyncio.sleep(0.02)

    pubsub.get_message = AsyncMock(side_effect=flaky_get_message)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        for _ in range(80):
            if get_runtime_state().cluster_propagation == PROPAGATION_REDIS and fail_count["n"] >= LISTEN_LOOP_DEGRADE_THRESHOLD:
                break
            await _asyncio.sleep(0.05)
        assert get_runtime_state().cluster_propagation == PROPAGATION_REDIS
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_marks_degraded_on_redis_failure(monkeypatch: pytest.MonkeyPatch):
    """A Redis read failure during boot reconciliation must downgrade to degraded."""
    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=RuntimeError("redis read failed"))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        assert get_runtime_state().cluster_propagation == PROPAGATION_DEGRADED
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_marks_degraded_on_malformed_payload(monkeypatch: pytest.MonkeyPatch):
    """A malformed JSON hint must downgrade cluster_propagation to degraded."""

    async def fake_get(key):
        # Return malformed JSON for the mcp hint key only.
        if key == _hint_key("mcp"):
            return b"{not json"
        return None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        assert get_runtime_state().cluster_propagation == PROPAGATION_DEGRADED
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_listen_loop_dedupes_self_pubsub_message(monkeypatch: pytest.MonkeyPatch):
    """A pub/sub message originating from this pod must not bump local state."""
    redis = _make_redis_mock()
    pubsub = redis.pubsub.return_value

    state = get_runtime_state()
    self_payload = orjson.dumps({"runtime": "mcp", "mode": "edge", "version": 99, "initiator_pod": state.pod_id, "timestamp": 1.0})
    delivered = {"yielded": False}

    async def fake_get_message(*args, **kwargs):
        if delivered["yielded"]:
            await __import__("asyncio").sleep(0.05)
            return None
        delivered["yielded"] = True
        return {"type": "message", "channel": RUNTIME_STATE_CHANNEL.encode(), "data": self_payload}

    pubsub.get_message = AsyncMock(side_effect=fake_get_message)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        # Wait long enough for the listen loop to have processed the message.
        await __import__("asyncio").sleep(0.2)
        assert state.override_mode("mcp") is None
        assert state.version("mcp") == 0
    finally:
        await coord.stop()
