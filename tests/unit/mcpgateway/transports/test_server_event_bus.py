# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_server_event_bus.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the server-to-client event bus (ADR-052).

Covers the in-memory backend end-to-end (publish/subscribe/replay/overflow)
and the factory's backend selection. The Redis backend's network-bound paths
are exercised in integration tests under compose.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from unittest.mock import AsyncMock

# Third-Party
from mcp.types import JSONRPCMessage, JSONRPCNotification
import pytest

# First-Party
from mcpgateway.transports.server_event_bus import (
    BusEvent,
    InMemoryServerEventBus,
    ListenerBacklogOverflow,
    RedisServerEventBus,
    _events_after,
    get_server_event_bus,
    reset_server_event_bus,
)


def _notif(i: int) -> JSONRPCMessage:
    return JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/test", params={"i": i}))


@pytest.mark.asyncio
async def test_publish_then_subscribe_replays_after_last_event_id():
    """Replay: subscribe with Last-Event-Id yields events strictly after it, then tails."""
    bus = InMemoryServerEventBus(max_events_per_stream=10)
    sid = "sess-replay"

    eid_1 = await bus.publish(sid, _notif(1))
    eid_2 = await bus.publish(sid, _notif(2))

    received: list[str] = []

    async def consume() -> None:
        async for evt in bus.subscribe(sid, last_event_id=eid_1):
            received.append(evt.event_id)
            if len(received) == 2:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    eid_3 = await bus.publish(sid, _notif(3))
    await asyncio.wait_for(consumer, timeout=2.0)

    assert received == [eid_2, eid_3]


@pytest.mark.asyncio
async def test_subscribe_without_last_event_id_replays_buffered_events():
    """Reconnect-without-cursor: every event in the buffer must be delivered.

    Codex P1 regression: a reconnecting client whose connection dropped
    before any event ids reached it has no Last-Event-Id to resume from,
    but the buffer holds events that arrived during the disconnect —
    most importantly server-initiated requests whose ``RequestResponder``
    on the gateway side will TTL out if we silently drop them. With the
    fix, the consumer receives the buffered backlog *and* the new
    event published after subscription.
    """
    bus = InMemoryServerEventBus(max_events_per_stream=10)
    sid = "sess-replay-no-cursor"

    await bus.publish(sid, _notif(1))  # buffered before subscribe

    received: list[int] = []

    async def consume() -> None:
        async for evt in bus.subscribe(sid):
            received.append(evt.message.root.params["i"])
            if len(received) >= 2:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await bus.publish(sid, _notif(2))
    await asyncio.wait_for(consumer, timeout=2.0)

    assert received == [1, 2], "must replay buffered backlog AND tail future events"


@pytest.mark.asyncio
async def test_unknown_last_event_id_starts_at_head():
    """An unknown Last-Event-Id behaves as if no resume was requested."""
    bus = InMemoryServerEventBus(max_events_per_stream=10)
    sid = "sess-unknown"
    await bus.publish(sid, _notif(1))

    received: list[int] = []

    async def consume() -> None:
        async for evt in bus.subscribe(sid, last_event_id="bogus"):
            received.append(evt.message.root.params["i"])
            break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await bus.publish(sid, _notif(2))
    await asyncio.wait_for(consumer, timeout=2.0)

    assert received == [2]


@pytest.mark.asyncio
async def test_multiple_subscribers_each_get_every_event():
    """Two listeners on the same session both receive published events."""
    bus = InMemoryServerEventBus(max_events_per_stream=10)
    sid = "sess-fanout"

    received_a: list[int] = []
    received_b: list[int] = []

    async def consume(target: list[int]) -> None:
        async for evt in bus.subscribe(sid):
            target.append(evt.message.root.params["i"])
            break

    a = asyncio.create_task(consume(received_a))
    b = asyncio.create_task(consume(received_b))
    await asyncio.sleep(0.05)
    await bus.publish(sid, _notif(99))
    await asyncio.gather(a, b)

    assert received_a == [99]
    assert received_b == [99]


@pytest.mark.asyncio
async def test_listener_queue_overflow_raises_backlog_overflow():
    """A subscriber that can't keep up gets ListenerBacklogOverflow on the next get."""
    bus = InMemoryServerEventBus(max_events_per_stream=10, listener_queue_depth=2)
    sid = "sess-overflow"

    started = asyncio.Event()
    received: list[int] = []

    async def driver() -> None:
        with pytest.raises(ListenerBacklogOverflow):
            started.set()
            async for evt in bus.subscribe(sid):
                received.append(evt.message.root.params["i"])

    consumer = asyncio.create_task(driver())
    await started.wait()
    await asyncio.sleep(0.05)
    # Publish well past the queue depth without yielding to the consumer.
    # The drain+sentinel path injects None; the consumer raises on its next
    # get. Note we don't await each publish — they're all synchronous from
    # the bus's perspective (in-memory put_nowait).
    for i in range(20):
        await bus.publish(sid, _notif(i))
    await asyncio.wait_for(consumer, timeout=2.0)
    # Whether any events landed before the sentinel depends on scheduling;
    # the contract this test pins is "raises ListenerBacklogOverflow".


@pytest.mark.asyncio
async def test_subscribe_unregisters_on_aclose():
    """Closing the async-iterator (explicitly) removes the listener from the bus's registry.

    Note: async-for ``break`` does NOT auto-aclose generators in Python — the
    generator is finalized on garbage collection. Call sites that need
    deterministic cleanup (e.g. the GET handler's response generator) get
    it for free because the SSE response wrapper closes its source generator
    on disconnect. We mirror that contract here with an explicit aclose.
    """
    bus = InMemoryServerEventBus(max_events_per_stream=10)
    sid = "sess-cleanup"

    sub = bus.subscribe(sid)
    started = asyncio.Event()
    received: list[int] = []

    async def consume() -> None:
        started.set()
        async for evt in sub:
            received.append(evt.message.root.params["i"])
            break

    task = asyncio.create_task(consume())
    await started.wait()
    await asyncio.sleep(0.05)

    # While subscribed: exactly one entry on the listeners list.
    assert sid in bus._listeners and len(bus._listeners[sid]) == 1

    await bus.publish(sid, _notif(1))
    await task

    # Explicit aclose runs the generator's finally and unregisters the queue.
    await sub.aclose()
    assert sid not in bus._listeners or not bus._listeners[sid]
    assert received == [1]


def test_events_after_helper():
    """Pure helper — exhaustive coverage of the cursor edge cases."""
    e1 = BusEvent(event_id="a", message=_notif(1))
    e2 = BusEvent(event_id="b", message=_notif(2))
    e3 = BusEvent(event_id="c", message=_notif(3))
    assert _events_after([e1, e2, e3], "a") == [e2, e3]
    assert _events_after([e1, e2, e3], "c") == []
    assert _events_after([e1, e2, e3], "missing") == [], "evicted/unknown cursor → no events (force resync)"
    # Codex P1 fix: None cursor replays the whole buffer so reconnects
    # without Last-Event-Id still receive pending server-initiated requests.
    assert _events_after([e1, e2, e3], None) == [e1, e2, e3]
    assert _events_after([], "a") == []
    assert _events_after([], None) == []


@pytest.mark.asyncio
async def test_factory_picks_in_memory_backend_for_non_redis_cache_type(monkeypatch):
    """When cache_type != 'redis', the factory binds InMemoryServerEventBus."""
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
    await reset_server_event_bus()
    bus = await get_server_event_bus()
    assert isinstance(bus, InMemoryServerEventBus)
    await reset_server_event_bus()


@pytest.mark.asyncio
async def test_factory_picks_redis_backend_for_redis_cache_type(monkeypatch):
    """When cache_type=='redis' AND redis_url is set, the factory binds RedisServerEventBus."""
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0", raising=False)
    await reset_server_event_bus()
    bus = await get_server_event_bus()
    assert isinstance(bus, RedisServerEventBus)
    await reset_server_event_bus()


@pytest.mark.asyncio
async def test_inmemory_close_signals_active_subscribers_with_sentinel():
    """Graceful shutdown path: close() must inject the None sentinel into every listener queue.

    Without this, an active subscriber blocked on ``queue.get()`` would
    wait forever after the bus was closed (e.g. on process shutdown
    before the SSE response had a chance to drain).
    """
    bus = InMemoryServerEventBus(max_events_per_stream=10)

    sub = bus.subscribe("sid-close-signal")
    # Pull once so the subscribe registers its queue under _listeners.
    await asyncio.sleep(0)

    # Track what the consumer sees after close().
    received: list[object] = []

    async def consume() -> None:
        try:
            async for evt in sub:
                received.append(evt)
        except Exception as exc:  # noqa: BLE001 — sentinel surfaces as ListenerBacklogOverflow
            received.append(exc)

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # let the iterator block on queue.get()

    await bus.close()
    await asyncio.wait_for(consumer, timeout=1.0)

    # The sentinel propagates as ListenerBacklogOverflow (the in-memory
    # backend's "queue closed by producer" signal).
    assert received, "consumer must wake up after bus.close()"
    # Either the iterator stopped cleanly or raised the backlog signal —
    # both are acceptable graceful-shutdown outcomes; a hung consumer
    # would have timed out above.


@pytest.mark.asyncio
async def test_factory_returns_singleton(monkeypatch):
    """Repeated calls return the same instance until reset_server_event_bus."""
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
    await reset_server_event_bus()
    bus_a = await get_server_event_bus()
    bus_b = await get_server_event_bus()
    assert bus_a is bus_b
    await reset_server_event_bus()
    bus_c = await get_server_event_bus()
    assert bus_c is not bus_a
    await reset_server_event_bus()


@pytest.mark.asyncio
async def test_redis_publish_uses_atomic_store_and_notify(monkeypatch):
    """Store + PUBLISH happen inside a single Lua eval — no separate ``redis.publish`` call path.

    Codex stop-hook escalation: even with best-effort rollback, a
    concurrent ``replay_after_with_ids`` could observe the event
    between ``store_event`` and the failing ``PUBLISH``/rollback
    window. Atomic Lua closes that race — Redis runs the script
    without any other client command interleaving.
    """
    # First-Party
    from mcp.types import JSONRPCMessage, JSONRPCNotification
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    store_and_notify_calls: list[dict] = []

    class FakeStore:
        async def store_event_with_notify(self, sid, _msg, *, channel, payload, event_id_override=None):
            store_and_notify_calls.append({"sid": sid, "channel": channel, "payload": payload, "event_id": event_id_override})
            return event_id_override or "generated-id"

        async def store_event(self, _sid, _msg):  # unused on atomic fast path
            raise AssertionError("atomic publish must NOT fall back to store_event")

    # A fake client that would raise on a standalone publish — proves
    # we never take that path.
    class SentinelRedis:
        async def publish(self, *_args, **_kwargs):
            raise AssertionError("atomic path must use the store's Lua, not redis.publish directly")

    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=SentinelRedis()),
    )

    bus = RedisServerEventBus(store=FakeStore())
    msg = JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/test"))
    event_id = await bus.publish("sid-atomic", msg)

    assert len(store_and_notify_calls) == 1
    call = store_and_notify_calls[0]
    assert call["sid"] == "sid-atomic"
    assert "sid-atomic" in call["channel"]
    assert call["event_id"] == event_id
    # Payload round-trips the event id for subscribers.
    import orjson  # local so the test doesn't pull orjson at import time for non-Redis runs

    assert orjson.loads(call["payload"]) == {"event_id": event_id}


@pytest.mark.asyncio
async def test_redis_publish_atomic_failure_evicts_when_server_side_completed(monkeypatch, caplog):
    """EVAL reply lost mid-network → best-effort evict uncovers the orphan and logs it.

    Codex stop-hook: atomic Lua protects concurrent readers, but it
    does NOT protect against "EVAL completed server-side, TCP drops,
    client sees an error." In that window the event IS in the buffer
    and the PUBLISH DID fire. Without best-effort eviction we'd
    orphan it for the next reconnect-without-cursor to replay.
    """
    # First-Party
    from mcp.types import JSONRPCMessage, JSONRPCNotification
    from mcpgateway.transports.server_event_bus import BusBackendError, RedisServerEventBus

    evict_calls: list[tuple[str, str]] = []

    class FakeStore:
        async def store_event_with_notify(self, *_args, **_kwargs):
            raise ConnectionError("EVAL reply lost")

        async def evict_event(self, sid, event_id):
            evict_calls.append((sid, event_id))
            return True  # simulates "server ran the script; our evict caught the orphan"

    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=object()),
    )

    bus = RedisServerEventBus(store=FakeStore())
    msg = JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/test"))
    with caplog.at_level("WARNING", logger="mcpgateway.transports.server_event_bus"):
        with pytest.raises(BusBackendError, match="Atomic store\\+publish failed"):
            await bus.publish("sid-reply-lost", msg)

    assert len(evict_calls) == 1, "must attempt eviction after a publish exception"
    assert evict_calls[0][0] == "sid-reply-lost"
    assert "rolled back event" in caplog.text


@pytest.mark.asyncio
async def test_redis_publish_atomic_failure_no_orphan_to_evict(monkeypatch):
    """EVAL never reached Redis → evict returns False → no noisy log, just raise."""
    # First-Party
    from mcp.types import JSONRPCMessage, JSONRPCNotification
    from mcpgateway.transports.server_event_bus import BusBackendError, RedisServerEventBus

    class FakeStore:
        async def store_event_with_notify(self, *_args, **_kwargs):
            raise ConnectionError("never reached Redis")

        async def evict_event(self, _sid, _event_id):
            return False  # nothing was stored → nothing to evict

    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=object()),
    )

    bus = RedisServerEventBus(store=FakeStore())
    msg = JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/test"))
    with pytest.raises(BusBackendError, match="Atomic store\\+publish failed"):
        await bus.publish("sid-never-sent", msg)


@pytest.mark.asyncio
async def test_redis_publish_eviction_failure_logs_error(monkeypatch, caplog):
    """If the eviction itself fails after a publish error, log at error so operators can investigate."""
    # First-Party
    from mcp.types import JSONRPCMessage, JSONRPCNotification
    from mcpgateway.transports.server_event_bus import BusBackendError, RedisServerEventBus

    class FakeStore:
        async def store_event_with_notify(self, *_args, **_kwargs):
            raise ConnectionError("publish failed")

        async def evict_event(self, _sid, _event_id):
            raise ConnectionError("and the evict is broken too")

    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=object()),
    )

    bus = RedisServerEventBus(store=FakeStore())
    msg = JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/test"))
    with caplog.at_level("ERROR", logger="mcpgateway.transports.server_event_bus"):
        with pytest.raises(BusBackendError):
            await bus.publish("sid-evict-broken", msg)
    assert "could not verify/evict event" in caplog.text


@pytest.mark.asyncio
async def test_redis_publish_missing_client_raises_without_eviction(monkeypatch, caplog):
    """When ``get_redis_client`` returns None, short-circuit with ``BusBackendError`` — no eviction attempt.

    Codex stop-hook escalation: the store's atomic Lua method also
    raises on missing-client, and evict_event ALSO raises on
    missing-client. Going through the eviction path would log
    "orphan may be in buffer" at error level even though the store
    never attempted a write. Pre-check at the bus layer so the
    missing-client case is crisp: raise ``BusBackendError``, no
    eviction, no misleading orphan warning.
    """
    # First-Party
    from mcp.types import JSONRPCMessage, JSONRPCNotification
    from mcpgateway.transports.server_event_bus import BusBackendError, RedisServerEventBus

    class SentinelStore:
        async def store_event_with_notify(self, *_args, **_kwargs):
            raise AssertionError("bus must short-circuit before calling the store")

        async def evict_event(self, *_args, **_kwargs):
            raise AssertionError("bus must NOT attempt eviction when client is missing")

    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=None),
    )

    bus = RedisServerEventBus(store=SentinelStore())
    msg = JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/test"))
    with caplog.at_level("WARNING", logger="mcpgateway.transports.server_event_bus"):
        with pytest.raises(BusBackendError, match="Redis client not available"):
            await bus.publish("sid-no-client", msg)
    # Crucially, no "orphan may be in buffer" chatter — nothing was written.
    assert "orphan may be in the buffer" not in caplog.text


# ---------------------------------------------------------------------------
# In-memory backend — edge cases for overflow drain / listener removal / close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inmemory_overflow_drain_handles_queueempty_race():
    """QueueEmpty mid-drain (lines 220-221) must break the drain loop cleanly.

    Simulated by substituting a queue whose ``empty()`` lies: reports
    False but ``get_nowait()`` raises QueueEmpty — mirrors a producer/
    consumer race where the consumer drains between our ``empty()``
    check and our ``get_nowait()``.
    """
    bus = InMemoryServerEventBus(max_events_per_stream=10, listener_queue_depth=1)
    sid = "sess-drain-race"

    class LyingQueue:
        def __init__(self) -> None:
            self._items: list[object] = []
            self._empty_calls = 0
            self.put_nowaits: list[object] = []

        def put_nowait(self, item):  # noqa: D401 — mimic asyncio.Queue API
            self.put_nowaits.append(item)
            if item is None:
                self._items.append(item)
                return
            # First put_nowait fills up; second raises QueueFull to hit overflow branch.
            if self._items:
                raise asyncio.QueueFull()
            self._items.append(item)

        def empty(self):
            # Lie once: report non-empty so the drain loop enters, then raise QueueEmpty.
            self._empty_calls += 1
            if self._empty_calls == 1:
                return False
            return len(self._items) == 0

        def get_nowait(self):
            raise asyncio.QueueEmpty()

    fake_q = LyingQueue()
    # Inject directly under the lock-free path; publish will hold the lock.
    bus._listeners[sid] = [fake_q]  # type: ignore[list-item]

    # First publish fills the fake queue; second triggers overflow → drain → QueueEmpty → break.
    await bus.publish(sid, _notif(1))
    await bus.publish(sid, _notif(2))

    # Sentinel must still have been enqueued after the break.
    assert None in fake_q.put_nowaits, "None sentinel must be enqueued after drain QueueEmpty break"


@pytest.mark.asyncio
async def test_inmemory_subscribe_finally_handles_valueerror_on_remove():
    """listener.remove raising ValueError (lines 254-255) must be swallowed.

    Replace the subscriber's registered queue with a different queue
    between the yield and the finally block. The finally's
    ``listeners.remove(queue)`` will then raise ValueError (the
    original queue is no longer in the list) — the contract is to
    swallow it and continue cleanup.
    """
    bus = InMemoryServerEventBus(max_events_per_stream=10, listener_queue_depth=4)
    sid = "sess-remove-race"

    async def consume() -> None:
        async for _evt in bus.subscribe(sid):
            pass  # pragma: no cover — we cancel before any events flow

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)

    # Swap the registered queue for a different object so remove() can't find it.
    # The list stays truthy (keeps the ``if listeners:`` branch live) so the
    # ValueError fallback is exercised.
    async with bus._lock:
        bus._listeners[sid] = [asyncio.Queue()]  # type: ignore[list-item]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The ValueError branch swallowed the error; our stand-in queue is still
    # there (remove() didn't touch it), proving the swallow-and-continue path.
    assert sid in bus._listeners
    assert len(bus._listeners[sid]) == 1


@pytest.mark.asyncio
async def test_inmemory_close_swallows_queuefull_when_sentinel_cant_enqueue():
    """close() with a full listener queue (lines 267-268) must swallow QueueFull.

    If a subscriber's queue is already full when ``close()`` runs, the
    None sentinel ``put_nowait`` raises QueueFull — the contract is to
    swallow and continue, since forcing a wake-up is best-effort at
    shutdown.
    """
    bus = InMemoryServerEventBus(max_events_per_stream=10, listener_queue_depth=1)
    sid = "sess-close-full"

    # Register a full queue directly so close() hits the QueueFull branch.
    full_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    full_queue.put_nowait(BusEvent(event_id="x", message=_notif(0)))
    bus._listeners[sid] = [full_queue]  # type: ignore[list-item]

    # Must not raise.
    await bus.close()

    # close() clears state even when the sentinel couldn't be enqueued.
    assert sid not in bus._listeners


# ---------------------------------------------------------------------------
# Redis backend — subscribe() paths
# ---------------------------------------------------------------------------


class _FakePubSub:
    """Controllable pubsub double for RedisServerEventBus tests.

    ``listen`` yields whatever dicts are put into ``_listen_queue``.
    A ``None`` item closes the async generator (clean exit). An
    ``Exception`` instance causes ``listen`` to raise it (simulates
    connection drops mid-stream).
    """

    def __init__(self) -> None:
        self._listen_queue: asyncio.Queue = asyncio.Queue()
        self.subscribe_calls: list[str] = []
        self.unsubscribe_calls: list[str] = []
        self.aclose_calls = 0
        self.subscribe_exc: Exception | None = None
        self.unsubscribe_exc: Exception | None = None
        self.aclose_exc: Exception | None = None

    async def subscribe(self, channel: str) -> None:
        self.subscribe_calls.append(channel)
        if self.subscribe_exc is not None:
            raise self.subscribe_exc

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribe_calls.append(channel)
        if self.unsubscribe_exc is not None:
            raise self.unsubscribe_exc

    async def aclose(self) -> None:
        self.aclose_calls += 1
        if self.aclose_exc is not None:
            raise self.aclose_exc

    async def listen(self):
        while True:
            item = await self._listen_queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    def feed(self, item) -> None:
        self._listen_queue.put_nowait(item)


class _FakeRedis:
    def __init__(self, pubsub_obj: _FakePubSub) -> None:
        self._pubsub = pubsub_obj

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


class _FakeStore:
    """Minimal RedisEventStore double for subscribe() tests."""

    def __init__(self, replay: list[tuple[str, JSONRPCMessage]] | None = None, fetch_map: dict[str, JSONRPCMessage] | None = None) -> None:
        self._replay = replay or []
        self._fetch_map = fetch_map or {}

    async def replay_after_with_ids(self, _sid: str, _last_event_id):
        for ev_id, msg in self._replay:
            yield ev_id, msg

    async def fetch_event(self, _sid: str, event_id: str):
        return self._fetch_map.get(event_id)


@pytest.mark.asyncio
async def test_redis_subscribe_missing_client_raises(monkeypatch):
    """subscribe() short-circuits with BusBackendError when get_redis_client is None."""
    # First-Party
    from mcpgateway.transports.server_event_bus import BusBackendError, RedisServerEventBus

    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=None),
    )
    bus = RedisServerEventBus(store=_FakeStore())
    sub = bus.subscribe("sid-nc")
    with pytest.raises(BusBackendError, match="Redis client not available"):
        await sub.__anext__()


@pytest.mark.asyncio
async def test_redis_subscribe_subscribe_failure_calls_aclose(monkeypatch):
    """pubsub.subscribe raising must propagate AND invoke aclose cleanup."""
    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    fake_pubsub.subscribe_exc = ConnectionError("subscribe boom")
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=_FakeStore())
    sub = bus.subscribe("sid-subfail")
    with pytest.raises(ConnectionError, match="subscribe boom"):
        await sub.__anext__()
    assert fake_pubsub.aclose_calls == 1


@pytest.mark.asyncio
async def test_redis_subscribe_subscribe_failure_aclose_also_raises(monkeypatch, caplog):
    """Subscribe-failure cleanup: aclose raising is logged at debug, original exc propagates."""
    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    fake_pubsub.subscribe_exc = ConnectionError("subscribe boom")
    fake_pubsub.aclose_exc = RuntimeError("aclose boom")
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=_FakeStore())
    sub = bus.subscribe("sid-subfail-acloseboom")
    with caplog.at_level("DEBUG", logger="mcpgateway.transports.server_event_bus"):
        with pytest.raises(ConnectionError, match="subscribe boom"):
            await sub.__anext__()
    assert fake_pubsub.aclose_calls == 1


@pytest.mark.asyncio
async def test_redis_subscribe_replay_then_tail_happy_path(monkeypatch):
    """Replay yields stored events (covers _iter_events_after 615-616), then tail via Pub/Sub."""
    # Standard
    import orjson

    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    m1 = _notif(1)
    m2 = _notif(2)
    fake_pubsub = _FakePubSub()
    store = _FakeStore(
        replay=[("ev-1", m1)],
        fetch_map={"ev-2": m2},
    )
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=store)
    sub = bus.subscribe("sid-happy", last_event_id="ev-0")

    received: list[str] = []

    async def consume() -> None:
        async for evt in sub:
            received.append(evt.event_id)
            if len(received) == 2:
                break

    task = asyncio.create_task(consume())
    # Give the consumer a chance to process the replay item and start tailing.
    await asyncio.sleep(0.05)
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-2"})})
    await asyncio.wait_for(task, timeout=1.0)
    await sub.aclose()

    assert received == ["ev-1", "ev-2"]
    assert fake_pubsub.subscribe_calls == ["mcp:session:sid-happy:events"]
    assert fake_pubsub.unsubscribe_calls == ["mcp:session:sid-happy:events"]
    assert fake_pubsub.aclose_calls == 1


@pytest.mark.asyncio
async def test_redis_subscribe_pump_discards_malformed_payloads(monkeypatch):
    """Pump discards non-JSON and non-string event_id payloads without dying."""
    # Standard
    import orjson

    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    good_msg = _notif(42)
    store = _FakeStore(fetch_map={"ev-good": good_msg})
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=store)
    sub = bus.subscribe("sid-malformed")

    received: list[str] = []

    async def consume() -> None:
        async for evt in sub:
            received.append(evt.event_id)
            break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)

    # 1) Non-"message" type — skipped by the ``if raw.get("type") != "message"`` branch.
    fake_pubsub.feed({"type": "subscribe", "data": b"ignored"})
    # 2) Invalid JSON — JSONDecodeError branch.
    fake_pubsub.feed({"type": "message", "data": b"{"})
    # 3) JSON without event_id key — KeyError branch.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"not_event": 1})})
    # 4) event_id present but wrong type — isinstance(event_id, str) branch.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": 12345})})
    # 5) event_id empty string — len check.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": ""})})
    # 6) event_id too long — len > 256 check.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "x" * 300})})
    # 7) Unknown event_id — _store.fetch_event returns None branch.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-missing"})})
    # 8) Good event.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-good"})})

    await asyncio.wait_for(task, timeout=1.0)
    await sub.aclose()
    assert received == ["ev-good"]


@pytest.mark.asyncio
async def test_redis_subscribe_pump_skips_duplicate_event_ids(monkeypatch):
    """event_id in seen → skip (covers seen-set branch)."""
    # Standard
    import orjson

    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    m1 = _notif(1)
    m2 = _notif(2)
    # Replay puts "ev-1" into seen, so a later pubsub message with "ev-1"
    # must be skipped by the ``if event_id in seen`` branch in pump.
    store = _FakeStore(replay=[("ev-1", m1)], fetch_map={"ev-2": m2})
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=store)
    sub = bus.subscribe("sid-dedup", last_event_id="ev-0")

    received: list[str] = []

    async def consume() -> None:
        async for evt in sub:
            received.append(evt.event_id)
            if len(received) == 2:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    # Duplicate of replay event — skipped.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-1"})})
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-2"})})
    await asyncio.wait_for(task, timeout=1.0)
    await sub.aclose()
    assert received == ["ev-1", "ev-2"]


@pytest.mark.asyncio
async def test_redis_subscribe_pump_queue_full_raises_overflow(monkeypatch):
    """queue_full inside pump → _force_sentinel → consumer raises ListenerBacklogOverflow."""
    # Standard
    import orjson

    # First-Party
    from mcpgateway.transports.server_event_bus import ListenerBacklogOverflow, RedisServerEventBus

    fake_pubsub = _FakePubSub()
    m1 = _notif(1)
    m2 = _notif(2)
    m3 = _notif(3)
    store = _FakeStore(fetch_map={"ev-1": m1, "ev-2": m2, "ev-3": m3})
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    # Queue depth 1: first event fills it, second triggers QueueFull → _force_sentinel.
    bus = RedisServerEventBus(store=store, listener_queue_depth=1)
    sub = bus.subscribe("sid-overflow")

    async def driver() -> None:
        # Start iteration but never drain the pump.
        agen = sub.__aiter__()
        await agen.__anext__()  # consume replay (none) → wait for queue
        # Consumer hasn't called get() again when we feed; the pump will
        # fill the queue and then get QueueFull on next feed.
        raise AssertionError("should not reach here — replay is empty")

    # Simpler approach: consume events until ListenerBacklogOverflow.
    async def consume() -> None:
        async for _evt in sub:
            # Stay around so queue depth fills up in pump.
            await asyncio.sleep(0.5)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    # Feed 3 messages; pump puts first in queue (consumer picks up), then
    # pump fills depth=1 and the next put_nowait raises QueueFull
    # → _force_sentinel() enqueues None → consumer sees None → ListenerBacklogOverflow.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-1"})})
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-2"})})
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-3"})})

    with pytest.raises(ListenerBacklogOverflow, match="Listener queue overflowed"):
        await asyncio.wait_for(task, timeout=2.0)
    await sub.aclose()


@pytest.mark.asyncio
async def test_redis_subscribe_pump_backend_failure_raises_bus_backend_error(monkeypatch):
    """listen() raising mid-stream → pump_failure set → consumer raises BusBackendError."""
    # First-Party
    from mcpgateway.transports.server_event_bus import BusBackendError, RedisServerEventBus

    fake_pubsub = _FakePubSub()
    store = _FakeStore()
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=store)
    sub = bus.subscribe("sid-backend-fail")

    async def consume() -> None:
        async for _evt in sub:
            pass  # pragma: no cover — no events will be delivered

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    # listen() raises mid-stream → pump's except Exception path fires.
    fake_pubsub.feed(ConnectionError("redis dropped"))

    with pytest.raises(BusBackendError, match="Bus backend failed"):
        await asyncio.wait_for(task, timeout=2.0)
    await sub.aclose()


@pytest.mark.asyncio
async def test_redis_subscribe_cancellation_path_force_sentinel(monkeypatch):
    """Consumer task cancelled while blocked on queue → subscribe finally cancels pump → CancelledError branch runs."""
    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    store = _FakeStore()
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=store)

    async def consume() -> None:
        async for _evt in bus.subscribe("sid-cancel"):
            pass  # pragma: no cover — no events

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    # Cancelling the consumer task unwinds subscribe's generator → finally block
    # cancels the pump → pump's CancelledError branch fires _force_sentinel →
    # teardown unsubscribes and acloses.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_pubsub.unsubscribe_calls == ["mcp:session:sid-cancel:events"]
    assert fake_pubsub.aclose_calls == 1


@pytest.mark.asyncio
async def test_redis_subscribe_teardown_unsubscribe_raises_logs_warning(monkeypatch, caplog):
    """pubsub.unsubscribe raising during teardown is logged at warning, exit is clean."""
    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    fake_pubsub.unsubscribe_exc = ConnectionError("unsubscribe boom")
    store = _FakeStore()
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=store)

    async def consume() -> None:
        async for _evt in bus.subscribe("sid-td-unsub"):
            pass  # pragma: no cover

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    with caplog.at_level("WARNING", logger="mcpgateway.transports.server_event_bus"):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    assert "pubsub.unsubscribe raised" in caplog.text


@pytest.mark.asyncio
async def test_redis_subscribe_teardown_aclose_raises_logs_warning(monkeypatch, caplog):
    """pubsub.aclose raising during teardown is logged at warning, exit is clean."""
    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    fake_pubsub.aclose_exc = ConnectionError("aclose boom")
    store = _FakeStore()
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=store)

    async def consume() -> None:
        async for _evt in bus.subscribe("sid-td-aclose"):
            pass  # pragma: no cover

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    with caplog.at_level("WARNING", logger="mcpgateway.transports.server_event_bus"):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    assert "pubsub.aclose raised" in caplog.text


@pytest.mark.asyncio
async def test_redis_subscribe_force_sentinel_fallback_logs_error(monkeypatch, caplog):
    """_force_sentinel fallback (lines 471-476): repeated QueueFull+QueueEmpty logs error.

    Pathological queue double: ``put_nowait`` always raises QueueFull,
    ``get_nowait`` always raises QueueEmpty. Both retries fall through
    to the forensic-trail error log. The normal single-producer
    contract can't reach this branch, but defensive code deserves a
    regression test for when it does.
    """
    # First-Party
    from mcpgateway.transports import server_event_bus as bus_mod

    class PathologicalQueue:
        def __init__(self, maxsize: int = 0) -> None:  # noqa: D401
            self._maxsize = maxsize

        def put_nowait(self, _item):
            raise asyncio.QueueFull()

        def get_nowait(self):
            raise asyncio.QueueEmpty()

        def qsize(self) -> int:
            return 0

        async def get(self):
            # Consumer blocks forever; we cancel the consumer task.
            await asyncio.Event().wait()

        def empty(self) -> bool:
            return True

    fake_pubsub = _FakePubSub()
    fake_pubsub.subscribe_exc = None
    store = _FakeStore()
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    # Swap asyncio.Queue in the module namespace so subscribe() uses our double.
    monkeypatch.setattr(bus_mod.asyncio, "Queue", PathologicalQueue)

    bus = bus_mod.RedisServerEventBus(store=store)

    async def consume() -> None:
        async for _evt in bus.subscribe("sid-force-sentinel"):
            pass  # pragma: no cover

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    with caplog.at_level("ERROR", logger="mcpgateway.transports.server_event_bus"):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    assert "could not enqueue cancel sentinel" in caplog.text


@pytest.mark.asyncio
async def test_redis_subscribe_consumer_skips_already_seen_event(monkeypatch):
    """Race: pump delivers an event the consumer will later add to ``seen`` during replay.

    The pump's ``if event_id in seen: continue`` short-circuit doesn't
    add to seen — only the consumer's replay loop does. So if the
    pump enqueues an event *before* replay yields it, the consumer
    yields the replay copy, then reads the pub/sub copy from its
    queue, sees it in ``seen`` and ``continue`` — that is the
    dedup branch at line 568.
    """
    # Standard
    import orjson

    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    m1 = _notif(1)
    m2 = _notif(2)
    # Replay will yield ev-1 FIRST; we'll also feed pubsub ev-1 before
    # replay consumer yields it so pump enqueues a duplicate into the
    # consumer queue. Consumer then reads ev-1 from queue after it's
    # already in seen → the line-568 ``continue`` branch fires.
    store = _FakeStore(replay=[("ev-1", m1)], fetch_map={"ev-1": m1, "ev-2": m2})
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )
    bus = RedisServerEventBus(store=store)

    received: list[str] = []

    async def consume() -> None:
        async for evt in bus.subscribe("sid-dedup-race", last_event_id="ev-0"):
            received.append(evt.event_id)
            if len(received) == 2:
                break

    # Prime the pump with ev-1 BEFORE starting the consumer so pump has it
    # queued by the time replay runs. Ordering is deterministic: pump
    # task is created and starts running when subscribe() enters its try
    # block, and its listen() generator yields from the pre-filled queue.
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-1"})})
    fake_pubsub.feed({"type": "message", "data": orjson.dumps({"event_id": "ev-2"})})

    # Slow down the replay iterator so the pump has time to enqueue the
    # duplicate ev-1 BEFORE the consumer yields it from replay.
    orig_replay = store.replay_after_with_ids

    async def slow_replay(sid, last_id):
        async for item in orig_replay(sid, last_id):
            await asyncio.sleep(0.05)
            yield item

    store.replay_after_with_ids = slow_replay  # type: ignore[assignment]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(task, timeout=2.0)
    assert received == ["ev-1", "ev-2"], "duplicate ev-1 must be skipped by consumer"


@pytest.mark.asyncio
async def test_redis_subscribe_teardown_pump_drain_exception_logs_warning(monkeypatch, caplog):
    """If awaiting the pump_task after cancel raises a non-CancelledError, it is logged at warning.

    We reach this branch by letting the pump's backend-failure path
    complete (recording pump_failure + _force_sentinel) and wrapping
    the pump task so ``await pump_task`` re-raises during teardown.
    The normal pump ``except Exception`` handler *absorbs* the error
    so the task exits normally — to hit the teardown-time re-raise
    branch we patch asyncio.create_task to wrap the pump coroutine in
    a task whose result will raise on await.
    """
    # First-Party
    from mcpgateway.transports.server_event_bus import RedisServerEventBus

    fake_pubsub = _FakePubSub()
    store = _FakeStore()
    monkeypatch.setattr(
        "mcpgateway.transports.server_event_bus.get_redis_client",
        AsyncMock(return_value=_FakeRedis(fake_pubsub)),
    )

    # Patch create_task so the pump coroutine is wrapped in a task that
    # raises a non-CancelledError when awaited.
    orig_create_task = asyncio.create_task
    marker = {"replaced": False}

    def spy_create_task(coro, *, name=None):
        if name and name.startswith("server-event-bus-pump:") and not marker["replaced"]:
            marker["replaced"] = True

            async def failing_pump():
                try:
                    await coro  # drive original pump so its finally/sentinel fires
                except BaseException:
                    pass
                raise RuntimeError("drain boom")

            return orig_create_task(failing_pump(), name=name)
        return orig_create_task(coro, name=name)

    monkeypatch.setattr(asyncio, "create_task", spy_create_task)

    bus = RedisServerEventBus(store=store)

    async def consume() -> None:
        async for _evt in bus.subscribe("sid-td-pump-drain"):
            pass  # pragma: no cover

    task = orig_create_task(consume())
    await asyncio.sleep(0.05)
    with caplog.at_level("WARNING", logger="mcpgateway.transports.server_event_bus"):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert "Pub/Sub pump drain raised" in caplog.text
