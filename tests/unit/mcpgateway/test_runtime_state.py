# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_runtime_state.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ``mcpgateway.runtime_state``.
"""

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
    # Simulate an edge-boot deployment so the persisted hint's mode=edge is
    # compatible with the safety invariant; otherwise _reconcile_from_hint
    # would (correctly) discard the hint as INCOMPATIBLE_HINT.
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", True, raising=False)

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
# I5: table-driven _deployment_allows_override_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("runtime_enabled", "session_auth", "all_cores", "mode", "expected_label"),
    [
        # boot=off (runtime disabled): every mode rejected as NO_DISPATCHER
        (False, False, False, "shadow", "no_dispatcher"),
        (False, False, False, "edge", "no_dispatcher"),
        # boot=shadow (runtime, no safety flag, no cores): shadow OK; edge needs safety flag
        (True, False, False, "shadow", "ok"),
        (True, False, False, "edge", "edge_needs_safety_flag"),
        # boot=edge (runtime + safety flag, no cores): both modes OK
        (True, True, False, "shadow", "ok"),
        (True, True, False, "edge", "ok"),
        # boot=full (all six flags): both modes rejected as BOOT_FULL_STRANDS
        (True, True, True, "shadow", "boot_full_strands"),
        (True, True, True, "edge", "boot_full_strands"),
    ],
    ids=[
        "off-shadow",
        "off-edge",
        "shadow-shadow",
        "shadow-edge",
        "edge-shadow",
        "edge-edge",
        "full-shadow",
        "full-edge",
    ],
)
def test_deployment_allows_override_mode_mcp_table(monkeypatch: pytest.MonkeyPatch, runtime_enabled, session_auth, all_cores, mode, expected_label):
    """Pin every (boot config × target mode) → MoveCompatibility outcome for MCP."""
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", runtime_enabled, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", session_auth, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_core_enabled", all_cores, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_event_store_enabled", all_cores, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_resume_core_enabled", all_cores, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_live_stream_core_enabled", all_cores, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_affinity_core_enabled", all_cores, raising=False)

    from mcpgateway.runtime_state import MoveCompatibility
    from mcpgateway.version import deployment_allows_override_mode

    result = deployment_allows_override_mode("mcp", mode)
    assert result == MoveCompatibility(expected_label)


@pytest.mark.parametrize(
    ("runtime_enabled", "delegate_enabled", "mode", "expected_label"),
    [
        # boot=off (runtime disabled): every mode NO_DISPATCHER
        (False, False, "shadow", "no_dispatcher"),
        (False, False, "edge", "no_dispatcher"),
        # boot=shadow (runtime, no delegate): shadow OK; edge needs delegate
        (True, False, "shadow", "ok"),
        (True, False, "edge", "edge_needs_safety_flag"),
        # boot=edge (runtime + delegate): both modes OK
        (True, True, "shadow", "ok"),
        (True, True, "edge", "ok"),
    ],
    ids=["off-shadow", "off-edge", "shadow-shadow", "shadow-edge", "edge-shadow", "edge-edge"],
)
def test_deployment_allows_override_mode_a2a_table(monkeypatch: pytest.MonkeyPatch, runtime_enabled, delegate_enabled, mode, expected_label):
    """Pin every (boot config × target mode) → MoveCompatibility outcome for A2A."""
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_enabled", runtime_enabled, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_delegate_enabled", delegate_enabled, raising=False)

    from mcpgateway.runtime_state import MoveCompatibility
    from mcpgateway.version import deployment_allows_override_mode

    result = deployment_allows_override_mode("a2a", mode)
    assert result == MoveCompatibility(expected_label)


@pytest.mark.asyncio
async def test_override_edge_cannot_bypass_session_auth_reuse_invariant(monkeypatch: pytest.MonkeyPatch):
    """Safety invariant: an admin override=edge on a deployment that didn't opt into
    session-auth-reuse at boot must NOT cause public /mcp to route to Rust.

    This is the belt in the belt-and-braces: the router rejects such PATCHes with
    409, but even if the override somehow landed in state (e.g. cluster reconcile
    from a hint written before we tightened the router), the read side must refuse
    to break the documented safety invariant.
    """
    # Simulate boot=shadow: Rust runtime enabled, session-auth-reuse NOT enabled.
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", False, raising=False)

    # Force the override to "edge" directly on state (bypassing the router).
    state = get_runtime_state()
    await state.apply_local("mcp", "edge", initiator_user="replay", version=1)
    assert state.override_mode("mcp") == "edge"

    # The read side must still refuse to route to Rust.
    from mcpgateway.version import should_mount_public_rust_transport

    assert should_mount_public_rust_transport() is False


@pytest.mark.asyncio
async def test_reconcile_from_hint_discards_incompatible_mode(monkeypatch: pytest.MonkeyPatch):
    """A hint written by a former edge-boot pod must NOT be applied on a shadow-boot deployment.

    Without this guard, a shadow-boot pod would reconcile to override=edge even though the
    transport layer refuses to honor it — and the admin API would need the escape-hatch
    PATCH to clear misleading diagnostics. The coordinator discards the hint and records
    ``INCOMPATIBLE_HINT`` so operators can see what happened via /health.
    """
    # First-Party
    from mcpgateway.runtime_state import BootReconcileStatus

    # Shadow-boot: runtime enabled but session-auth-reuse NOT enabled.
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", False, raising=False)

    hint_payload = orjson.dumps(
        {
            "runtime": "mcp",
            "mode": "edge",
            "version": 42,
            "initiator_pod": "prior-edge-boot",
            "initiator_user": "operator",
            "timestamp": 1.0,
        }
    )

    async def fake_get(key):
        return hint_payload if key == _hint_key("mcp") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        state = get_runtime_state()
        # The stale edge hint must NOT have been applied.
        assert state.override_mode("mcp") is None
        assert state.version("mcp") == 0
        assert state.boot_reconcile_status("mcp") == BootReconcileStatus.INCOMPATIBLE_SAFETY_FLAG
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_discards_shadow_on_full_boot(monkeypatch: pytest.MonkeyPatch):
    """A shadow hint must NOT be applied on boot=full — full mounts a plain RustMCPRuntimeProxy
    with no dispatcher, so the override would strand in state (diagnostics say shadow; transport
    always routes to Rust). The router also 409s for any PATCH on boot=full, so without this
    guard the operator would have no path to clear the stale override.
    """
    from mcpgateway.runtime_state import BootReconcileStatus

    # boot=full: all cores enabled.
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_core_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_event_store_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_resume_core_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_live_stream_core_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_affinity_core_enabled", True, raising=False)

    hint_payload = orjson.dumps({"runtime": "mcp", "mode": "shadow", "version": 9, "initiator_pod": "other", "timestamp": 1.0})

    async def fake_get(key):
        return hint_payload if key == _hint_key("mcp") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        state = get_runtime_state()
        assert state.override_mode("mcp") is None
        assert state.boot_reconcile_status("mcp") == BootReconcileStatus.INCOMPATIBLE_BOOT_FULL
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_discards_any_mode_on_off_boot(monkeypatch: pytest.MonkeyPatch):
    """boot=off has no Rust sidecar at all — no hint can take effect. Must be discarded."""
    from mcpgateway.runtime_state import BootReconcileStatus

    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", False, raising=False)

    hint_payload = orjson.dumps({"runtime": "mcp", "mode": "shadow", "version": 3, "initiator_pod": "other", "timestamp": 1.0})

    async def fake_get(key):
        return hint_payload if key == _hint_key("mcp") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        state = get_runtime_state()
        assert state.override_mode("mcp") is None
        assert state.boot_reconcile_status("mcp") == BootReconcileStatus.INCOMPATIBLE_NO_DISPATCHER
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_discards_a2a_hint_on_a2a_off_boot(monkeypatch: pytest.MonkeyPatch):
    """A2A boot=off has runtime disabled — no hint can take effect."""
    from mcpgateway.runtime_state import BootReconcileStatus

    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_enabled", False, raising=False)

    hint_payload = orjson.dumps({"runtime": "a2a", "mode": "shadow", "version": 11, "initiator_pod": "other", "timestamp": 1.0})

    async def fake_get(key):
        return hint_payload if key == _hint_key("a2a") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        state = get_runtime_state()
        assert state.override_mode("a2a") is None
        assert state.boot_reconcile_status("a2a") == BootReconcileStatus.INCOMPATIBLE_NO_DISPATCHER
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_discards_edge_on_full_boot(monkeypatch: pytest.MonkeyPatch):
    """Symmetric to shadow-on-full: an edge hint on boot=full also strands."""
    from mcpgateway.runtime_state import BootReconcileStatus

    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_core_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_event_store_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_resume_core_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_live_stream_core_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_affinity_core_enabled", True, raising=False)

    hint_payload = orjson.dumps({"runtime": "mcp", "mode": "edge", "version": 9, "initiator_pod": "other", "timestamp": 1.0})

    async def fake_get(key):
        return hint_payload if key == _hint_key("mcp") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        state = get_runtime_state()
        assert state.override_mode("mcp") is None
        assert state.boot_reconcile_status("mcp") == BootReconcileStatus.INCOMPATIBLE_BOOT_FULL
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_discards_edge_on_off_boot(monkeypatch: pytest.MonkeyPatch):
    """Symmetric to shadow-on-off: an edge hint on boot=off also discards."""
    from mcpgateway.runtime_state import BootReconcileStatus

    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", False, raising=False)

    hint_payload = orjson.dumps({"runtime": "mcp", "mode": "edge", "version": 5, "initiator_pod": "other", "timestamp": 1.0})

    async def fake_get(key):
        return hint_payload if key == _hint_key("mcp") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        state = get_runtime_state()
        assert state.override_mode("mcp") is None
        assert state.boot_reconcile_status("mcp") == BootReconcileStatus.INCOMPATIBLE_NO_DISPATCHER
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_incompatible_hint_does_not_delete_redis_key_or_downgrade_propagation(monkeypatch: pytest.MonkeyPatch):
    """Discarded hint must leave the Redis key alone (a future compatible-boot pod must still see it)
    and must NOT downgrade cluster_propagation (the discard is internal — pubsub is healthy).
    """
    from mcpgateway.runtime_state import BootReconcileStatus

    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", False, raising=False)

    hint_payload = orjson.dumps({"runtime": "mcp", "mode": "edge", "version": 7, "initiator_pod": "other", "timestamp": 1.0})

    async def fake_get(key):
        return hint_payload if key == _hint_key("mcp") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    redis.delete = AsyncMock(return_value=1)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        state = get_runtime_state()
        assert state.boot_reconcile_status("mcp") == BootReconcileStatus.INCOMPATIBLE_SAFETY_FLAG
        # S1: hint key must NOT be deleted from Redis.
        redis.delete.assert_not_awaited()
        # S2: an internal discard must not falsely degrade pubsub propagation.
        assert state.cluster_propagation == PROPAGATION_REDIS
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_reconcile_from_hint_accepts_shadow_mode_on_shadow_boot(monkeypatch: pytest.MonkeyPatch):
    """A shadow hint is always compatible — shadow is the Python-default and every boot serves Python for shadow overrides."""
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", False, raising=False)

    hint_payload = orjson.dumps({"runtime": "mcp", "mode": "shadow", "version": 5, "initiator_pod": "other", "timestamp": 1.0})

    async def fake_get(key):
        return hint_payload if key == _hint_key("mcp") else None

    redis = _make_redis_mock()
    redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        from mcpgateway.runtime_state import BootReconcileStatus, OverrideMode

        state = get_runtime_state()
        assert state.override_mode("mcp") == OverrideMode.SHADOW
        assert state.version("mcp") == 5
        assert state.boot_reconcile_status("mcp") == BootReconcileStatus.OK
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_override_edge_cannot_bypass_delegate_enabled_invariant(monkeypatch: pytest.MonkeyPatch):
    """Same invariant for A2A: edge override cannot bypass the delegate_enabled requirement."""
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_delegate_enabled", False, raising=False)

    state = get_runtime_state()
    await state.apply_local("a2a", "edge", initiator_user="replay", version=1)

    from mcpgateway.version import should_delegate_a2a_to_rust

    assert should_delegate_a2a_to_rust() is False


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
    # Make the deployment compatible with the incoming a2a/shadow payload —
    # otherwise _listen_loop will (correctly) discard the message.
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_delegate_enabled", True, raising=False)

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
    """A successful receive of a real message after degraded must promote cluster_propagation back to redis.

    Per the I2 fix, a non-exception return of ``None`` (no message) is NOT
    counted as recovery — only a real message is. This prevents a pubsub
    that's "broken in a way that returns None reliably" from falsely clearing
    the failure counter.
    """
    import asyncio as _asyncio

    from mcpgateway.runtime_state import LISTEN_LOOP_DEGRADE_THRESHOLD

    # Make the deployment compatible with the recovery message we'll deliver.
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_delegate_enabled", True, raising=False)

    redis = _make_redis_mock()
    pubsub = redis.pubsub.return_value
    fail_count = {"n": 0}
    real_message_payload = orjson.dumps({"runtime": "a2a", "mode": "shadow", "version": 1, "initiator_pod": "remote-pod", "timestamp": 1.0})

    async def flaky_get_message(*args, **kwargs):
        if fail_count["n"] < LISTEN_LOOP_DEGRADE_THRESHOLD:
            fail_count["n"] += 1
            raise RuntimeError("pubsub down")
        # Recovery: deliver one real message, then idle.
        if fail_count["n"] == LISTEN_LOOP_DEGRADE_THRESHOLD:
            fail_count["n"] += 1
            return {"type": "message", "channel": RUNTIME_STATE_CHANNEL.encode(), "data": real_message_payload}
        await _asyncio.sleep(0.02)
        return None

    pubsub.get_message = AsyncMock(side_effect=flaky_get_message)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))

    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        for _ in range(80):
            if get_runtime_state().cluster_propagation == PROPAGATION_REDIS and fail_count["n"] > LISTEN_LOOP_DEGRADE_THRESHOLD:
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


# ---------------------------------------------------------------------
# Defensive ValueError branches — accessor methods on RuntimeState
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,expected",
    [
        ("boot_reconcile_status", "coordinator_offline"),
        ("override_mode", None),
        ("version", 0),
        ("last_change", None),
    ],
)
def test_runtime_state_accessors_return_safe_defaults_for_unknown_runtime(method, expected):
    """Accessors must not raise when handed an unknown runtime kind — they return a safe default so callers (e.g. health endpoints) keep working."""
    state = RuntimeState()
    result = getattr(state, method)("rpc")  # "rpc" is not a registered kind
    if method == "boot_reconcile_status":
        assert result.value == expected
    else:
        assert result == expected


# ---------------------------------------------------------------------
# RuntimeStateCoordinator.start: idempotent + degraded path
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_start_is_idempotent():
    """Calling start() twice is a no-op; the second call returns immediately without re-attaching."""
    coord = RuntimeStateCoordinator()
    await coord.start()
    try:
        await coord.start()  # second call must not raise / re-attach
        assert coord._started is True  # noqa: SLF001 — verifying idempotency
    finally:
        await coord.stop()


# ---------------------------------------------------------------------
# _reconcile_from_hint: no-redis and malformed-mode paths
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_from_hint_no_redis_marks_status_ok():
    """When Redis isn't configured, boot reconcile is trivially OK — no hint to apply."""
    coord = RuntimeStateCoordinator()
    coord._redis = None  # noqa: SLF001 — explicitly model the no-Redis deployment
    await coord._reconcile_from_hint("mcp")  # noqa: SLF001
    assert get_runtime_state().boot_reconcile_status("mcp").value == "ok"


@pytest.mark.asyncio
async def test_reconcile_from_hint_malformed_mode_in_payload_falls_through():
    """A hint payload whose ``mode`` field can't be coerced is treated as 'no compatibility check' and falls through to apply_remote."""
    coord = RuntimeStateCoordinator()
    coord._redis = MagicMock()
    coord._redis.get = AsyncMock(return_value=orjson.dumps({"mode": "not-a-mode", "version": 1, "initiator_pod": "pod-x"}))
    await coord._reconcile_from_hint("mcp")  # noqa: SLF001
    # Either OK (apply_remote rejected the malformed mode silently) or an
    # incompatible-* status — the important thing is no exception bubbled up.
    assert get_runtime_state().boot_reconcile_status("mcp") is not None


# ---------------------------------------------------------------------
# _cleanup_pubsub: timeout + close paths
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_pubsub_handles_unsubscribe_timeout_and_close_paths():
    """Both unsubscribe and close take the timeout/exception arms cleanly — they must never raise out of _cleanup_pubsub."""
    # Standard
    import asyncio as _asyncio

    coord = RuntimeStateCoordinator()
    fake_pubsub = MagicMock()
    fake_pubsub.unsubscribe = AsyncMock(side_effect=_asyncio.TimeoutError())
    fake_pubsub.aclose = AsyncMock(side_effect=_asyncio.TimeoutError())
    coord._pubsub = fake_pubsub  # noqa: SLF001

    # Must not raise.
    await coord._cleanup_pubsub()  # noqa: SLF001
    assert coord._pubsub is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_cleanup_pubsub_falls_back_to_close_when_aclose_missing():
    """Older redis clients expose ``close`` not ``aclose`` — the cleanup must fall back without raising."""
    coord = RuntimeStateCoordinator()
    fake_pubsub = MagicMock(spec=["unsubscribe", "close"])  # NO aclose
    fake_pubsub.unsubscribe = AsyncMock(return_value=None)
    fake_pubsub.close = AsyncMock(return_value=None)
    coord._pubsub = fake_pubsub  # noqa: SLF001

    await coord._cleanup_pubsub()  # noqa: SLF001
    fake_pubsub.close.assert_awaited_once()
    assert coord._pubsub is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_cleanup_pubsub_swallows_unsubscribe_and_close_exceptions():
    """Non-timeout exceptions during unsubscribe / close are caught and logged, never raised."""
    coord = RuntimeStateCoordinator()
    fake_pubsub = MagicMock()
    fake_pubsub.unsubscribe = AsyncMock(side_effect=RuntimeError("unsub blew up"))
    fake_pubsub.aclose = AsyncMock(side_effect=RuntimeError("close blew up"))
    coord._pubsub = fake_pubsub  # noqa: SLF001

    await coord._cleanup_pubsub()  # noqa: SLF001
    assert coord._pubsub is None  # noqa: SLF001


# ---------------------------------------------------------------------
# Listen-loop edge cases — exercised by driving _listen_loop with a
# fake pubsub that yields specific message shapes.
# ---------------------------------------------------------------------


class _ScriptedPubSub:
    """Async stub that yields a scripted sequence of get_message values, then signals the coordinator's stop_event so _listen_loop exits cleanly."""

    def __init__(self, script: list, stop_event) -> None:
        # Each entry is either a callable returning a dict (or raising) OR a
        # bare value yielded as-is.
        self._script = list(script)
        self._stop = stop_event

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0):  # noqa: ARG002
        if not self._script:
            # Set the stop_event then yield None so the coordinator hits its
            # "non-message return" continue and re-checks the loop condition.
            self._stop.set()
            return None
        item = self._script.pop(0)
        if callable(item):
            return item()
        return item


@pytest.mark.asyncio
async def test_listen_loop_recovers_cluster_propagation_after_idle_following_errors():
    """After a stretch of receive errors degrades cluster_propagation, an idle-timeout (no message) restores it."""
    # Standard
    import asyncio as _asyncio

    state = get_runtime_state()
    state.set_cluster_propagation(PROPAGATION_DEGRADED)

    coord = RuntimeStateCoordinator()
    coord._started = True  # noqa: SLF001
    stop = _asyncio.Event()
    coord._stop_event = stop  # noqa: SLF001

    # First call raises a non-Timeout to bump consecutive_errors > 0;
    # second call raises TimeoutError to take the recovery branch.
    def _raise_runtime():
        raise RuntimeError("transient receive error")

    def _raise_timeout():
        raise _asyncio.TimeoutError()

    coord._pubsub = _ScriptedPubSub([_raise_runtime, _raise_timeout], stop)  # noqa: SLF001

    await coord._listen_loop()  # noqa: SLF001

    assert state.cluster_propagation == PROPAGATION_REDIS


@pytest.mark.asyncio
async def test_listen_loop_discards_malformed_pubsub_payload(caplog):
    """A pub/sub message whose data isn't valid JSON is logged and skipped — no crash, no state change."""
    # Standard
    import asyncio as _asyncio

    coord = RuntimeStateCoordinator()
    coord._started = True  # noqa: SLF001
    stop = _asyncio.Event()
    coord._stop_event = stop  # noqa: SLF001

    coord._pubsub = _ScriptedPubSub(  # noqa: SLF001
        [{"type": "message", "data": b"not-valid-json{{{"}],
        stop,
    )

    caplog.set_level("WARNING", logger="mcpgateway.runtime_state")
    await coord._listen_loop()  # noqa: SLF001

    assert any("malformed pub/sub payload" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_listen_loop_skips_message_with_empty_data():
    """A pub/sub message with empty ``data`` is skipped without raising."""
    # Standard
    import asyncio as _asyncio

    coord = RuntimeStateCoordinator()
    coord._started = True  # noqa: SLF001
    stop = _asyncio.Event()
    coord._stop_event = stop  # noqa: SLF001

    coord._pubsub = _ScriptedPubSub([{"type": "message", "data": ""}], stop)  # noqa: SLF001

    # Must not raise.
    await coord._listen_loop()  # noqa: SLF001
    assert get_runtime_state().override_mode("mcp") is None


@pytest.mark.asyncio
async def test_listen_loop_treats_uncoerceable_payload_fields_as_none(monkeypatch, caplog):
    """When ``mode`` or ``runtime`` in the payload can't be coerced to enums, the compatibility check is skipped and apply_remote handles the malformed payload."""
    # Standard
    import asyncio as _asyncio

    coord = RuntimeStateCoordinator()
    coord._started = True  # noqa: SLF001
    stop = _asyncio.Event()
    coord._stop_event = stop  # noqa: SLF001

    payload = orjson.dumps(
        {
            "runtime": "not-a-real-runtime",
            "mode": "not-a-real-mode",
            "version": 1,
            "initiator_pod": "pod-other",
        }
    )
    coord._pubsub = _ScriptedPubSub([{"type": "message", "data": payload}], stop)  # noqa: SLF001

    caplog.set_level("WARNING", logger="mcpgateway.runtime_state")
    await coord._listen_loop()  # noqa: SLF001

    # No state change; apply_remote should have rejected the malformed payload.
    assert get_runtime_state().override_mode("mcp") is None


@pytest.mark.asyncio
async def test_listen_loop_decodes_bytes_payload_and_reaches_compatibility_check(monkeypatch, caplog):
    """Message data delivered as bytes is decoded UTF-8, JSON-parsed, and reaches the per-pod compatibility check."""
    # Standard
    import asyncio as _asyncio

    # First-Party
    from mcpgateway.config import settings as _settings

    # Enable MCP runtime + safety flag so the compatibility check returns OK
    # for an edge override; we can then apply_remote it.
    monkeypatch.setattr(_settings, "experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr(_settings, "experimental_rust_mcp_session_auth_reuse_enabled", True, raising=False)

    state = get_runtime_state()
    coord = RuntimeStateCoordinator()
    coord._started = True  # noqa: SLF001
    stop = _asyncio.Event()
    coord._stop_event = stop  # noqa: SLF001

    payload = orjson.dumps(
        {
            "runtime": "mcp",
            "mode": "edge",
            "version": 99,
            "initiator_user": "alice@example.com",
            "initiator_pod": "pod-other",
            "timestamp": 1234567890.0,
        }
    )
    coord._pubsub = _ScriptedPubSub([{"type": "message", "data": payload}], stop)  # noqa: SLF001

    caplog.set_level("INFO", logger="mcpgateway.runtime_state")
    await coord._listen_loop()  # noqa: SLF001

    # The bytes payload was decoded, parsed, found compatible, and applied.
    assert state.override_mode("mcp") == "edge"
    assert state.version("mcp") == 99


# ---------------------------------------------------------------------
# version.py status payload includes last_change after an override
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_runtime_status_payload_includes_last_change_after_override(monkeypatch):
    """After an override is applied, _mcp_runtime_status_payload exposes a last_change block."""
    # First-Party
    from mcpgateway.config import settings as _settings
    from mcpgateway.version import _mcp_runtime_status_payload

    monkeypatch.setattr(_settings, "experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr(_settings, "experimental_rust_mcp_session_auth_reuse_enabled", True, raising=False)

    state = get_runtime_state()
    await state.apply_local("mcp", "edge", initiator_user="alice@example.com", version=42)

    payload = _mcp_runtime_status_payload()
    assert "last_change" in payload
    assert payload["last_change"]["version"] == 42
    assert payload["last_change"]["mode"] == "edge"
    assert payload["last_change"]["initiator_user"] == "alice@example.com"


@pytest.mark.asyncio
async def test_a2a_runtime_status_payload_includes_last_change_after_override(monkeypatch):
    """After an A2A override is applied, _a2a_runtime_status_payload exposes a last_change block."""
    # First-Party
    from mcpgateway.config import settings as _settings
    from mcpgateway.version import _a2a_runtime_status_payload

    monkeypatch.setattr(_settings, "experimental_rust_a2a_runtime_enabled", True, raising=False)

    state = get_runtime_state()
    await state.apply_local("a2a", "shadow", initiator_user="bob@example.com", version=7)

    payload = _a2a_runtime_status_payload()
    assert "last_change" in payload
    assert payload["last_change"]["version"] == 7
    assert payload["last_change"]["mode"] == "shadow"


@pytest.mark.asyncio
async def test_should_delegate_a2a_to_rust_returns_false_under_shadow_override(monkeypatch):
    """An A2A shadow override forces _should_delegate_a2a_to_rust to False even when boot flags allow delegation."""
    # First-Party
    from mcpgateway.config import settings as _settings
    from mcpgateway.version import _should_delegate_a2a_to_rust

    monkeypatch.setattr(_settings, "experimental_rust_a2a_runtime_enabled", True, raising=False)
    monkeypatch.setattr(_settings, "experimental_rust_a2a_runtime_delegate_enabled", True, raising=False)

    state = get_runtime_state()
    await state.apply_local("a2a", "shadow", initiator_user=None, version=1)

    assert _should_delegate_a2a_to_rust() is False


def test_boot_mcp_transport_mount_returns_underlying_value():
    """``boot_mcp_transport_mount`` is a thin public wrapper — verify it returns the same value as the underlying helper."""
    # First-Party
    from mcpgateway.version import _boot_mcp_transport_mount, boot_mcp_transport_mount

    assert boot_mcp_transport_mount() == _boot_mcp_transport_mount()
