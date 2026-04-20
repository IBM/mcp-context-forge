# -*- coding: utf-8 -*-
"""Server-to-client event bus for the MCP GET /mcp stream (ADR-052).

Backs the spec-defined "Listening for messages from the server" SSE stream.
Server-initiated JSON-RPC messages (notifications and requests) are
``publish``-ed by whichever worker holds the upstream MCP session and
``subscribe``-d by the GET /mcp handler on whichever node the client landed.

Two interchangeable backends sit behind ``ServerEventBus``:

* ``RedisServerEventBus`` (selected when ``cache_type == "redis"``) — durable
  per-session ring buffer via :class:`RedisEventStore` + Pub/Sub fanout on
  ``mcp:session:{sid}:events`` so any node can serve the stream.

* ``InMemoryServerEventBus`` (default) — process-local ring buffer with
  ``asyncio.Queue`` per subscriber. Single-process semantics are identical
  to Redis for one process; cross-worker delivery is intentionally absent
  because that is a multi-node concern.

The factory ``get_server_event_bus()`` reads ``cache_type`` once at first
call and binds the singleton; switching backends requires a restart.

SPDX-License-Identifier: Apache-2.0
"""

# Standard
from __future__ import annotations

import abc
import asyncio
from collections import deque
from dataclasses import dataclass
import logging
from typing import AsyncIterator, Optional
import uuid

# Third-Party
from mcp.types import JSONRPCMessage
import orjson

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.metrics import server_event_bus_overflow_counter
from mcpgateway.transports.redis_event_store import RedisEventStore
from mcpgateway.utils.redis_client import get_redis_client

logger = logging.getLogger(__name__)


_PUBSUB_CHANNEL_PREFIX = "mcp:session:"
_PUBSUB_CHANNEL_SUFFIX = ":events"


def _channel(session_id: str) -> str:
    """Return the Pub/Sub channel name for a downstream session.

    Args:
        session_id: Downstream MCP session id.

    Returns:
        Redis channel name used for live-event fanout.
    """
    return f"{_PUBSUB_CHANNEL_PREFIX}{session_id}{_PUBSUB_CHANNEL_SUFFIX}"


@dataclass(frozen=True)
class BusEvent:
    """One event delivered to a GET /mcp listener.

    ``event_id`` is what becomes the SSE ``id:`` field and the value the
    client echoes in ``Last-Event-Id`` on reconnect. ``message`` is the
    JSON-RPC envelope (notification or server-initiated request) the
    listener serializes into the SSE ``data:`` field.
    """

    event_id: str
    message: JSONRPCMessage


class ListenerBacklogOverflow(RuntimeError):
    """Raised when a subscriber's queue overflows.

    The GET handler treats this as a signal to close the SSE stream so the
    client reconnects with ``Last-Event-Id`` and replays from the durable
    buffer, rather than continuing to silently drop messages. The
    distinction from :class:`BusBackendError` is what callers care about;
    the message string carries the session id for log lines.
    """


class BusBackendError(RuntimeError):
    """Raised when the bus backend itself fails (Redis Pub/Sub pump dies, etc.).

    Distinct from ``ListenerBacklogOverflow`` so the GET handler can log
    "backend outage" separately from "consumer too slow" — operators
    chasing reconnect storms otherwise look at queue-depth metrics for
    what is really a Redis hiccup. The message string carries session id
    and reason for log lines.
    """


class ServerEventBus(abc.ABC):
    """Abstract bus for server→client messages on a downstream session."""

    @abc.abstractmethod
    async def publish(self, session_id: str, message: JSONRPCMessage) -> str:
        """Append ``message`` to the session's stream and signal listeners.

        Args:
            session_id: Downstream MCP session id.
            message: JSON-RPC envelope to deliver.

        Returns:
            The event id assigned to this message.
        """

    @abc.abstractmethod
    def subscribe(
        self,
        session_id: str,
        *,
        last_event_id: Optional[str] = None,
    ) -> AsyncIterator[BusEvent]:
        """Yield events for ``session_id`` until the caller stops iterating.

        Replays from ``last_event_id`` if provided (and still in the
        backlog), then tails new events. The async iterator is the unit
        of cancellation — closing it releases all backend resources.

        Implementations are async generators (``async def`` with ``yield``).
        The ABC method is declared as a plain ``def`` returning
        ``AsyncIterator[BusEvent]`` so the call signature reads
        ``it = bus.subscribe(sid)`` — same shape as the implementations'
        ``async def`` + ``yield`` (which Python evaluates to a generator
        without entering the coroutine). Type checkers see consistent
        return shapes on both sides.

        Args:
            session_id: Downstream MCP session id.
            last_event_id: Resume from this event id (exclusive). When
                ``None`` or evicted, only new events are delivered.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def close(self) -> None:
        """Release any backend resources held by the bus."""


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


# How deep a per-listener queue grows before we treat the consumer as too slow
# and force a reconnect. Conservative — server-initiated traffic is sparse.
_DEFAULT_LISTENER_QUEUE_DEPTH = 256


class InMemoryServerEventBus(ServerEventBus):
    """Process-local bus.

    Per session we keep a bounded ring buffer (for replay) and a list of
    subscriber ``asyncio.Queue`` objects (for live tail). All state is
    confined to this process — operators running multiple workers should
    use :class:`RedisServerEventBus` so events fan out across nodes.
    """

    def __init__(
        self,
        max_events_per_stream: int = 100,
        listener_queue_depth: int = _DEFAULT_LISTENER_QUEUE_DEPTH,
    ) -> None:
        """Initialize the in-memory bus.

        Args:
            max_events_per_stream: Per-session ring-buffer depth.
            listener_queue_depth: Per-subscriber queue depth before
                ``ListenerBacklogOverflow`` is signaled.
        """
        self._max_events = max_events_per_stream
        self._queue_depth = listener_queue_depth
        self._buffers: dict[str, deque[BusEvent]] = {}
        self._listeners: dict[str, list[asyncio.Queue[BusEvent | None]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, session_id: str, message: JSONRPCMessage) -> str:
        """Append the message to the session's ring buffer and signal listeners.

        The queue puts run *under* ``_lock`` so two concurrent
        publishers cannot interleave drain-on-overflow with normal
        puts. Without that atomicity, the ``None`` sentinel can be
        silently swallowed by ``QueueFull`` — the consumer then stops
        receiving events but never raises ``ListenerBacklogOverflow``.
        """
        event = BusEvent(event_id=str(uuid.uuid4()), message=message)
        async with self._lock:
            buf = self._buffers.setdefault(session_id, deque(maxlen=self._max_events))
            buf.append(event)
            queues = list(self._listeners.get(session_id, ()))
            for queue in queues:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Subscriber too slow. Drain whatever is already
                    # buffered and inject the ``None`` sentinel so the
                    # subscriber sees the overflow on its next ``get()``
                    # and raises ``ListenerBacklogOverflow``. Dropped
                    # events are recoverable: the client reconnects with
                    # ``Last-Event-Id`` and replays from the backlog
                    # (which still holds them).
                    logger.warning(
                        "In-memory listener queue overflow for session %s — closing stream",
                        session_id,
                    )
                    server_event_bus_overflow_counter.inc()
                    while not queue.empty():
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    queue.put_nowait(None)
        return event.event_id

    async def subscribe(  # pylint: disable=invalid-overridden-method
        self,
        session_id: str,
        *,
        last_event_id: Optional[str] = None,
    ) -> AsyncIterator[BusEvent]:
        """Yield events for the session — replay from ``last_event_id`` then tail."""
        queue: asyncio.Queue[BusEvent | None] = asyncio.Queue(maxsize=self._queue_depth)
        # Snapshot replay candidates and register the queue atomically so we
        # don't miss events that arrive between snapshot and registration.
        async with self._lock:
            buf = self._buffers.get(session_id)
            replay = list(buf) if buf else []
            self._listeners.setdefault(session_id, []).append(queue)

        try:
            for event in _events_after(replay, last_event_id):
                yield event
            while True:
                event = await queue.get()
                if event is None:
                    raise ListenerBacklogOverflow(f"Listener queue overflowed for session {session_id}")
                yield event
        finally:
            async with self._lock:
                listeners = self._listeners.get(session_id)
                if listeners:
                    try:
                        listeners.remove(queue)
                    except ValueError:
                        pass
                    if not listeners:
                        self._listeners.pop(session_id, None)

    async def close(self) -> None:
        """Drop all session state and signal every listener to terminate."""
        async with self._lock:
            self._buffers.clear()
            for queues in self._listeners.values():
                for queue in queues:
                    try:
                        queue.put_nowait(None)
                    except asyncio.QueueFull:
                        pass
            self._listeners.clear()


def _events_after(events: list[BusEvent], last_event_id: Optional[str]) -> list[BusEvent]:
    """Return events strictly after ``last_event_id``.

    When ``last_event_id`` is ``None`` the caller is reconnecting without
    a cursor — return every buffered event so a client that dropped
    before receiving any event ids still gets the buffered
    server-initiated requests it missed. (For brand-new sessions the
    buffer is empty so this is a no-op.)

    When ``last_event_id`` is set but unknown to this buffer the cursor
    has been evicted; return nothing rather than silently delivering
    only the surviving tail.
    """
    if last_event_id is None:
        return list(events)
    for idx, event in enumerate(events):
        if event.event_id == last_event_id:
            return events[idx + 1 :]
    return []


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


class RedisServerEventBus(ServerEventBus):
    """Redis-backed bus.

    Events are persisted in a per-session :class:`RedisEventStore` ring
    buffer (Lua-atomic, TTL-bounded) and a wake-up signal is published on
    a per-session Pub/Sub channel. The combination — durable store for
    correctness, Pub/Sub for latency — is the standard ``LISTEN/NOTIFY``
    pattern adapted to Redis.
    """

    def __init__(
        self,
        store: Optional[RedisEventStore] = None,
        listener_queue_depth: int = _DEFAULT_LISTENER_QUEUE_DEPTH,
    ) -> None:
        """Initialize the Redis-backed bus.

        Args:
            store: Optional pre-built event store; defaults to one keyed
                from the streamable-http settings.
            listener_queue_depth: Per-subscriber queue depth before
                ``ListenerBacklogOverflow`` is signaled.
        """
        self._store = store or RedisEventStore(
            max_events_per_stream=settings.streamable_http_max_events_per_stream,
            ttl=settings.streamable_http_event_ttl,
        )
        self._queue_depth = listener_queue_depth

    async def publish(self, session_id: str, message: JSONRPCMessage) -> str:
        """Persist the event and fire the Pub/Sub wake-up atomically.

        Store + ``PUBLISH`` happen inside a single Redis Lua script
        (``RedisEventStore.store_event_with_notify``). Redis runs Lua
        atomically (no other client command executes during a script),
        so a concurrent ``replay_after_with_ids`` cannot observe the
        event between the store and the notify — either nothing is
        visible or both the event is in the buffer AND the wake-up has
        been dispatched.

        The tricky part is client-visible failure: an exception from
        ``store_event_with_notify`` does **not** prove "nothing was
        written." Redis's Lua atomicity protects other clients, but
        the network between our client and Redis can drop AFTER the
        script executed fully server-side but BEFORE the reply
        reaches us. In that window the event is in the buffer, the
        PUBLISH has fired, and yet the caller sees an error. Leaving
        the stored event behind would orphan it on the next
        reconnect-without-cursor (Codex stop-hook finding).

        So after any exception, best-effort evict by the pre-bound
        event id. ``evict_event`` is idempotent — returns ``False``
        when the event never landed, ``True`` when the orphan was
        removed. Either way we raise ``BusBackendError`` so the
        caller cancels the holder immediately.
        """
        # Pre-check the client at the bus layer so the
        # missing-client case short-circuits without an eviction
        # attempt. Without this, the store raises
        # ``RuntimeError("Redis client not available ...")``, the
        # eviction raises the same, and the recovery path would
        # mistakenly log "orphan may be in buffer" when nothing was
        # actually written.
        redis = await get_redis_client()
        if redis is None:
            raise BusBackendError(f"Redis client not available — cannot publish event for session {session_id}")
        # Pre-generate the event id so the Pub/Sub payload can
        # reference it, and so we have a fixed id to evict if the
        # EVAL reply never reaches us (EVAL completed server-side but
        # the reply was lost).
        event_id = str(uuid.uuid4())
        payload = orjson.dumps({"event_id": event_id})
        try:
            await self._store.store_event_with_notify(
                session_id,
                message,
                channel=_channel(session_id),
                payload=payload,
                event_id_override=event_id,
            )
        except Exception as exc:  # noqa: BLE001 — re-raise as typed bus error for the caller
            await self._evict_after_publish_failure(session_id, event_id, exc)
            raise BusBackendError(f"Atomic store+publish failed for session {session_id}: {exc}") from exc
        return event_id

    async def _evict_after_publish_failure(self, session_id: str, event_id: str, exc: BaseException) -> None:
        """Best-effort eviction of an event the EVAL may have written server-side.

        Three outcomes, three log levels:

        * ``evict_event`` returns ``True`` → we found and removed an
          orphan (EVAL completed server-side; reply was lost). Log at
          warning so operators can correlate with the upstream
          failure.
        * ``evict_event`` returns ``False`` → the event never landed.
          Silent; the raise downstream tells the caller.
        * ``evict_event`` raises → we couldn't verify state. That's
          NOT "nothing to clean up" — the EVAL may have landed and we
          just can't reach Redis to find out. Log at error so the
          operator sees the potential orphan.
        """
        try:
            evicted = await self._store.evict_event(session_id, event_id)
        except Exception as evict_exc:  # noqa: BLE001 — already recovering from a publish failure
            logger.error(
                "Server-event-bus could not verify/evict event %s for session %s after publish error (%s): %s — orphan may be in the buffer; operator should investigate",
                event_id,
                session_id,
                exc,
                evict_exc,
                exc_info=evict_exc,
            )
            return
        if evicted:
            logger.warning(
                "Server-event-bus rolled back event %s for session %s (publish EVAL reply lost: %s)",
                event_id,
                session_id,
                exc,
            )

    async def subscribe(  # pylint: disable=invalid-overridden-method
        self,
        session_id: str,
        *,
        last_event_id: Optional[str] = None,
    ) -> AsyncIterator[BusEvent]:
        """Replay from ``last_event_id`` then tail the session's Pub/Sub channel."""
        redis = await get_redis_client()
        if redis is None:
            raise BusBackendError(f"Redis client not available for session {session_id}")

        # Distinct sentinel for backend failure, separate from the overflow
        # ``None`` sentinel — lets the consumer raise ``BusBackendError``
        # instead of misleadingly raising ``ListenerBacklogOverflow`` when
        # the real cause is a Redis hiccup.
        pump_failure: dict[str, str] = {}
        queue: asyncio.Queue[BusEvent | None] = asyncio.Queue(maxsize=self._queue_depth)
        seen: set[str] = set()

        # Subscribe BEFORE replay so events landed between the replay's last
        # seq and the live tail's first message aren't dropped.
        # The ``await pubsub.subscribe(...)`` lives inside its own
        # try/aclose because a transient disconnect, auth rotation or
        # eval failure during subscribe would otherwise leak the
        # ``pubsub`` connection — the cleanup below only fires once we
        # enter the outer try/finally.
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(_channel(session_id))
        except Exception:
            try:
                await pubsub.aclose()
            except Exception as close_exc:  # noqa: BLE001 — best-effort cleanup; preserve original
                logger.debug("pubsub.aclose during subscribe-failure cleanup raised for %s: %s", session_id, close_exc)
            raise

        def _force_sentinel() -> None:
            """Guarantee the consumer wakes up by enqueueing ``None``.

            Without a sentinel reaching the queue, a consumer blocked on
            ``queue.get()`` waits forever for a pump task that has already
            exited. If the queue is full we drop the oldest event to make
            room — losing one event is strictly better than wedging the
            stream until the client times out and reconnects.
            """
            for _ in range(2):
                try:
                    queue.put_nowait(None)
                    return
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        # Consumer drained between our check and now — retry put.
                        continue
            # Should never reach here for a single-producer queue, but log
            # if it does so the wedge has a forensic trail.
            logger.error(
                "Pub/Sub pump for %s could not enqueue cancel sentinel (queue depth=%d)",
                session_id,
                queue.qsize(),
            )

        async def pump() -> None:
            """Read Pub/Sub notifications and feed event ids into the subscriber's queue."""
            try:
                async for raw in pubsub.listen():
                    if raw.get("type") != "message":
                        continue
                    data = raw.get("data") or b""
                    try:
                        info = orjson.loads(data)
                        event_id = info["event_id"]
                    except (orjson.JSONDecodeError, KeyError, TypeError) as exc:
                        # Malformed payload (schema drift, foreign publisher, encoding bug).
                        # Log so a payload-format regression doesn't silently nuke every
                        # event for every session.
                        logger.debug(
                            "Discarding malformed Pub/Sub payload for %s: %s (%r)",
                            session_id,
                            exc,
                            data[:128],
                        )
                        continue
                    # Validate event_id type and length BEFORE letting it
                    # become a Redis hash key. An attacker with Redis-write
                    # could otherwise pass non-strings or pathological
                    # values into ``_fetch_event`` → ``redis.hget``.
                    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
                        logger.debug(
                            "Discarding malformed Pub/Sub event_id for %s: %r",
                            session_id,
                            event_id,
                        )
                        continue
                    if event_id in seen:
                        continue
                    msg = await self._store.fetch_event(session_id, event_id)
                    if msg is None:
                        continue
                    try:
                        queue.put_nowait(BusEvent(event_id=event_id, message=msg))
                    except asyncio.QueueFull:
                        # Subscriber too slow — overflow path (NOT backend failure).
                        # Force a sentinel through so the consumer wakes and
                        # raises ListenerBacklogOverflow instead of blocking
                        # forever after draining the (now sentinel-less) queue.
                        _force_sentinel()
                        return
            except asyncio.CancelledError:
                # External cancellation (subscribe() finally cancels us on
                # consumer exit). Wake the consumer if it's blocked on
                # queue.get(); without a sentinel it would wait forever
                # for a pump that's gone.
                _force_sentinel()
                raise
            except Exception as exc:
                # Backend failure (Redis dropped, listen() raised, etc.).
                # Record reason so the consumer can raise BusBackendError.
                logger.warning("Pub/Sub pump for session %s exited: %s", session_id, exc)
                pump_failure["reason"] = f"{type(exc).__name__}: {exc}"
                _force_sentinel()

        pump_task = asyncio.create_task(pump(), name=f"server-event-bus-pump:{session_id[:8]}")

        try:
            # Replay buffered events regardless of whether a Last-Event-Id
            # was supplied. With a cursor we yield events strictly after
            # it; without a cursor we yield everything in the surviving
            # ring buffer. The latter case matters for reconnects that
            # drop before any event id reached the client — the buffered
            # server-initiated requests would otherwise be silently lost
            # and the gateway-side ``RequestResponder`` would TTL out.
            async for event in self._iter_events_after(session_id, last_event_id):
                seen.add(event.event_id)
                yield event
            while True:
                event = await queue.get()
                if event is None:
                    # Distinguish backend failure (typed BusBackendError)
                    # from overflow (ListenerBacklogOverflow). The GET
                    # handler logs each case differently — operators
                    # tracing reconnect storms would otherwise chase
                    # queue-depth metrics for what is really a Redis
                    # outage.
                    if pump_failure:
                        raise BusBackendError(f"Bus backend failed for session {session_id}: {pump_failure['reason']}")
                    raise ListenerBacklogOverflow(f"Listener queue overflowed for session {session_id}")
                if event.event_id in seen:
                    continue
                seen.add(event.event_id)
                yield event
        finally:
            # Cancel pump first, then await it so its `pubsub.listen()`
            # await unwinds before we close the pubsub. Without this
            # ordering, some redis-py versions raise teardown-time
            # RuntimeErrors because aclose() runs while listen() still
            # holds the connection.
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 — connection-pool leak indicator; log at warning so default LOG_LEVEL=ERROR operators still see it
                logger.warning(
                    "Pub/Sub pump drain raised for %s during teardown: %s",
                    session_id,
                    exc,
                )
            try:
                await pubsub.unsubscribe(_channel(session_id))
            except Exception as exc:  # noqa: BLE001 — leak indicator; see rationale above
                logger.warning(
                    "pubsub.unsubscribe raised for %s during teardown: %s",
                    session_id,
                    exc,
                )
            try:
                await pubsub.aclose()
            except Exception as exc:  # noqa: BLE001 — leak indicator; see rationale above
                logger.warning(
                    "pubsub.aclose raised for %s during teardown: %s",
                    session_id,
                    exc,
                )

    async def _iter_events_after(
        self,
        session_id: str,
        last_event_id: str,
    ) -> AsyncIterator[BusEvent]:
        """Yield stored events after ``last_event_id`` with original ids preserved.

        Delegates to ``RedisEventStore.replay_after_with_ids`` so the
        Redis-key schema stays encapsulated in the event store.
        """
        async for ev_id, msg in self._store.replay_after_with_ids(session_id, last_event_id):
            yield BusEvent(event_id=ev_id, message=msg)

    async def close(self) -> None:
        """No-op; Pub/Sub subscriptions and queues are scoped to ``subscribe()``."""
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_bus_singleton: Optional[ServerEventBus] = None
_bus_lock = asyncio.Lock()


async def get_server_event_bus() -> ServerEventBus:
    """Return the process-wide singleton bus.

    Backend is chosen on first call from ``settings.cache_type`` and reused
    for the lifetime of the process. Multi-node deployments
    (``cache_type == "redis"``) get the Redis bus; everything else gets the
    in-memory bus.

    Returns:
        The singleton ``ServerEventBus``.
    """
    global _bus_singleton  # pylint: disable=global-statement
    if _bus_singleton is not None:
        return _bus_singleton
    async with _bus_lock:
        if _bus_singleton is None:
            if settings.cache_type == "redis" and settings.redis_url:
                logger.info("ServerEventBus: using Redis backend")
                _bus_singleton = RedisServerEventBus()
            else:
                logger.info(
                    "ServerEventBus: using in-memory backend (cache_type=%s)",
                    settings.cache_type,
                )
                _bus_singleton = InMemoryServerEventBus(
                    max_events_per_stream=settings.streamable_http_max_events_per_stream,
                )
    return _bus_singleton


async def reset_server_event_bus() -> None:
    """Drop the singleton — for tests only."""
    global _bus_singleton  # pylint: disable=global-statement
    async with _bus_lock:
        if _bus_singleton is not None:
            await _bus_singleton.close()
        _bus_singleton = None
