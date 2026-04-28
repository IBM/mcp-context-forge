# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_runtime_state_cluster.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration test: two ``RuntimeStateCoordinator`` instances converge via pub/sub.

The unit-test suite for ``runtime_state`` covers each Redis call site with a
single mocked client. This test stands up two coordinator instances pointed at
the same in-process Redis simulator (a hand-rolled broker that implements just
enough of ``publish``/``subscribe``/``get_message``/``incr``/``get``/``set``
for the coordinator) so we can prove the cross-pod convergence end-to-end.

We deliberately avoid ``fakeredis`` (not in the project's dependency set) and
keep the simulator local to this file.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

# Third-Party
import pytest

# First-Party
from mcpgateway.runtime_state import (
    BootReconcileStatus,
    ClusterPropagation,
    OverrideMode,
    RuntimeKind,
    RuntimeState,
    RuntimeStateCoordinator,
    _hint_key,
    _version_key,
    reset_runtime_state_coordinator_for_tests,
    reset_runtime_state_for_tests,
)


class FakeRedisBroker:
    """Shared, in-process simulator of Redis pub/sub + key-value semantics.

    Sufficient to back any number of ``FakeRedisClient`` instances pointed at
    the same broker — what one publishes, the others receive.
    """

    def __init__(self) -> None:
        self.kv: Dict[str, bytes] = {}
        self.counters: Dict[str, int] = {}
        self.subscribers: List[List[Dict[str, Any]]] = []  # each subscriber gets its own queue

    def register_subscriber(self) -> List[Dict[str, Any]]:
        queue: List[Dict[str, Any]] = []
        self.subscribers.append(queue)
        return queue

    def publish(self, channel: str, payload: bytes) -> None:
        for queue in self.subscribers:
            queue.append({"type": "message", "channel": channel.encode(), "data": payload})


class FakeRedisClient:
    """Per-coordinator Redis-like client backed by the shared broker."""

    def __init__(self, broker: FakeRedisBroker) -> None:
        self._broker = broker

    async def get(self, key: str) -> Optional[bytes]:
        return self._broker.kv.get(key)

    async def set(self, key: str, value: bytes, ex: Optional[int] = None) -> bool:  # pylint: disable=unused-argument
        self._broker.kv[key] = value
        return True

    async def incr(self, key: str) -> int:
        self._broker.counters[key] = self._broker.counters.get(key, 0) + 1
        return self._broker.counters[key]

    async def publish(self, channel: str, payload: bytes) -> int:
        self._broker.publish(channel, payload)
        return len(self._broker.subscribers)

    def pubsub(self) -> "FakePubSub":
        return FakePubSub(self._broker)


class FakePubSub:
    """Per-subscriber pubsub stand-in with its own message queue."""

    def __init__(self, broker: FakeRedisBroker) -> None:
        self._broker = broker
        self._queue = broker.register_subscriber()
        self._subscribed: List[str] = []

    async def subscribe(self, *channels: str) -> None:
        self._subscribed.extend(channels)

    async def unsubscribe(self, *_channels: str) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0):  # pylint: disable=unused-argument
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue:
                msg = self._queue.pop(0)
                if msg.get("channel", b"").decode() in self._subscribed:
                    return msg
                continue
            await asyncio.sleep(0.01)
        return None


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_runtime_state_for_tests()
    reset_runtime_state_coordinator_for_tests()
    yield
    reset_runtime_state_for_tests()
    reset_runtime_state_coordinator_for_tests()


@pytest.mark.asyncio
async def test_two_coordinators_converge_through_pubsub(monkeypatch: pytest.MonkeyPatch):
    """A flip on coordinator A must converge to the local state owned by coordinator B."""
    # Both coordinators must look like edge-boot so the published shadow flip
    # is compatible on the receiver (per the new _deployment_allows_override_mode
    # check in the listen-loop).
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", True, raising=False)

    broker = FakeRedisBroker()

    # Each coordinator gets its own RuntimeState (simulating two pods) and its
    # own FakeRedisClient pointing at the shared broker.
    state_a = RuntimeState()
    state_b = RuntimeState()
    state_a._pod_id = "pod-A"  # noqa: SLF001 — test fixture exposes internal id for cross-pod simulation
    state_b._pod_id = "pod-B"  # noqa: SLF001 — test fixture exposes internal id for cross-pod simulation

    coord_a = RuntimeStateCoordinator()
    coord_b = RuntimeStateCoordinator()

    # The coordinator's get_runtime_state() lookup uses the module singleton.
    # We swap that lookup per-coordinator by patching just before each .start().
    import mcpgateway.runtime_state as runtime_state_module

    monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_a)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedisClient(broker)))
    await coord_a.start()

    monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_b)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedisClient(broker)))
    await coord_b.start()

    try:
        # Coordinator A "issues" a flip: allocate a version, apply locally, publish.
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_a)
        version = await coord_a.next_version("mcp", state_a.version("mcp"))
        change = await state_a.apply_local("mcp", "shadow", initiator_user="alice@example.com", version=version)
        assert change is not None
        assert await coord_a.publish(change) is True

        # Coordinator B's listen loop should observe the message and apply it
        # to its own RuntimeState.
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_b)
        for _ in range(50):
            if state_b.override_mode("mcp") == OverrideMode.SHADOW:
                break
            await asyncio.sleep(0.05)

        assert state_b.override_mode("mcp") == OverrideMode.SHADOW
        assert state_b.version("mcp") == version
        last = state_b.last_change("mcp")
        assert last is not None
        assert last.runtime == RuntimeKind.MCP
        assert last.initiator_pod == "pod-A"
        assert last.initiator_user == "alice@example.com"
        # Coordinator A's local state already had the flip applied; it must not
        # double-apply when the broker echoes its own message.
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_a)
        assert state_a.version("mcp") == version

        # Both coordinators should report healthy propagation throughout.
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_a)
        assert state_a.cluster_propagation == ClusterPropagation.REDIS
        assert state_a.boot_reconcile_status("mcp") == BootReconcileStatus.OK
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_b)
        assert state_b.cluster_propagation == ClusterPropagation.REDIS
        # B reconciled from the empty hint at boot (before A published), so OK.
        assert state_b.boot_reconcile_status("mcp") == BootReconcileStatus.OK

    finally:
        # stop() reaches into get_runtime_state() to reset cluster_propagation;
        # rebind to each coordinator's state for clean shutdown.
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_a)
        await coord_a.stop()
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_b)
        await coord_b.stop()


@pytest.mark.asyncio
async def test_fresh_pod_reconciles_to_persisted_hint(monkeypatch: pytest.MonkeyPatch):
    """A pod that boots after a flip on another pod must reconcile to the persisted hint."""
    # Simulate an edge-boot deployment for both pods so the a2a hint's
    # mode=edge is compatible with the safety invariant; without this the
    # coordinator (correctly) discards the hint as INCOMPATIBLE_HINT.
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_delegate_enabled", True, raising=False)

    broker = FakeRedisBroker()

    state_a = RuntimeState()
    state_b = RuntimeState()
    state_a._pod_id = "pod-A"  # noqa: SLF001 — test fixture exposes internal id for cross-pod simulation
    state_b._pod_id = "pod-B"  # noqa: SLF001 — test fixture exposes internal id for cross-pod simulation

    coord_a = RuntimeStateCoordinator()
    coord_b = RuntimeStateCoordinator()

    import mcpgateway.runtime_state as runtime_state_module

    # Bring up coordinator A and have it apply + publish a flip.
    monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_a)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedisClient(broker)))
    await coord_a.start()

    try:
        version = await coord_a.next_version("a2a", state_a.version("a2a"))
        change = await state_a.apply_local("a2a", "edge", initiator_user="bob@example.com", version=version)
        assert change is not None
        assert await coord_a.publish(change) is True

        # The hint key must now hold the published payload.
        assert _hint_key("a2a") in broker.kv
        # Bring up coordinator B AFTER the publish; it should reconcile from the
        # persisted hint at start time, not via pub/sub.
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_b)
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedisClient(broker)))
        await coord_b.start()
        assert state_b.override_mode("a2a") == OverrideMode.EDGE
        assert state_b.version("a2a") == version
        # Boot reconciliation succeeded → OK.
        assert state_b.boot_reconcile_status("a2a") == BootReconcileStatus.OK
        # And the version-key counter survived B's start (no INCR happened).
        assert broker.counters[_version_key("a2a")] == version
    finally:
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_a)
        await coord_a.stop()
        monkeypatch.setattr(runtime_state_module, "get_runtime_state", lambda: state_b)
        await coord_b.stop()


@pytest.mark.asyncio
async def test_concurrent_flips_allocate_distinct_versions_via_incr(monkeypatch: pytest.MonkeyPatch):
    """Two near-simultaneous PATCHes through one broker allocate distinct, monotonic versions.

    A full two-pod end-to-end concurrent-flip test would require binding a
    ``RuntimeState`` per ``RuntimeStateCoordinator`` (today both reach into
    the module-level singleton). That refactor is tracked separately; for
    now we prove the version-allocation half of the story — which is the
    half that actually prevents silent collisions at peer dedup time.
    """
    broker = FakeRedisBroker()
    state = RuntimeState()
    state._pod_id = "pod-test"  # noqa: SLF001 — test fixture exposes internal id for cross-pod simulation

    coord = RuntimeStateCoordinator()
    monkeypatch.setattr("mcpgateway.runtime_state.get_runtime_state", lambda: state)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedisClient(broker)))
    await coord.start()

    try:
        # Two PATCHes allocate distinct versions via INCR; nothing falls back
        # to current_version + 1.
        v_first = await coord.next_version("mcp", state.version("mcp"))
        change_first = await state.apply_local("mcp", "shadow", initiator_user="alice", version=v_first)
        assert change_first is not None

        v_second = await coord.next_version("mcp", state.version("mcp"))
        assert v_second == v_first + 1
        change_second = await state.apply_local("mcp", "edge", initiator_user="bob", version=v_second)
        assert change_second is not None

        # The persisted Redis counter advanced exactly once per allocation.
        assert broker.counters[_version_key("mcp")] == v_second

        # Both publishes succeed; the broker holds two distinct payloads.
        assert await coord.publish(change_first) is True
        assert await coord.publish(change_second) is True
    finally:
        await coord.stop()
