# -*- coding: utf-8 -*-
"""
Redis-backed event store for Streamable HTTP stateful sessions.

Design goals:
- Multi-worker safe: store+evict is atomic (Lua), so concurrent writers do not corrupt meta/count.
- Bounded memory: per-stream ring buffer with eviction.
- Bounded index growth: event_id index entries expire with the stream TTL.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import AsyncIterator, Optional, TYPE_CHECKING
import uuid

# Third-Party
from mcp.server.streamable_http import EventCallback, EventStore
from mcp.types import JSONRPCMessage
import orjson

# First-Party
from mcpgateway.utils.redis_client import get_redis_client

if TYPE_CHECKING:  # pragma: no cover
    # Third-Party
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


_STORE_EVENT_LUA = r"""
-- KEYS:
--  1) meta_key
--  2) events_key (zset: member=event_id, score=seq_num)
--  3) messages_key (hash: event_id -> message_json)
-- ARGV:
--  1) event_id
--  2) message_json (orjson encoded; "null" for priming)
--  3) ttl_seconds
--  4) max_events
--  5) index_prefix (string, eg "mcpgw:eventstore:event_index:")
--  6) stream_id

local meta_key = KEYS[1]
local events_key = KEYS[2]
local messages_key = KEYS[3]

local event_id = ARGV[1]
local message_json = ARGV[2]
local ttl = tonumber(ARGV[3])
local max_events = tonumber(ARGV[4])
local index_prefix = ARGV[5]
local stream_id = ARGV[6]

local seq_num = redis.call('HINCRBY', meta_key, 'next_seq', 1)
local count = redis.call('HINCRBY', meta_key, 'count', 1)
if count == 1 then
  redis.call('HSET', meta_key, 'start_seq', seq_num)
end

redis.call('ZADD', events_key, seq_num, event_id)
redis.call('HSET', messages_key, event_id, message_json)

local index_key = index_prefix .. event_id
redis.call('SET', index_key, cjson.encode({stream_id=stream_id, seq_num=seq_num}), 'EX', ttl)

if count > max_events then
  local to_evict = count - max_events
  local evicted_ids = redis.call('ZRANGE', events_key, 0, to_evict - 1)
  redis.call('ZREMRANGEBYRANK', events_key, 0, to_evict - 1)

  if #evicted_ids > 0 then
    redis.call('HDEL', messages_key, unpack(evicted_ids))
    for _, ev_id in ipairs(evicted_ids) do
      redis.call('DEL', index_prefix .. ev_id)
    end
  end

  redis.call('HSET', meta_key, 'count', max_events)
  local first = redis.call('ZRANGE', events_key, 0, 0, 'WITHSCORES')
  if #first >= 2 then
    redis.call('HSET', meta_key, 'start_seq', tonumber(first[2]))
  else
    redis.call('HSET', meta_key, 'start_seq', seq_num)
  end
end

redis.call('EXPIRE', meta_key, ttl)
redis.call('EXPIRE', events_key, ttl)
redis.call('EXPIRE', messages_key, ttl)

return seq_num
"""


# Same as ``_STORE_EVENT_LUA`` but appends a ``PUBLISH`` to a supplied
# channel (ARGV[7]) with a payload (ARGV[8]). Because Redis runs Lua
# atomically (no other client commands execute while the script runs),
# the store and publish are atomic from a reader's perspective — a
# concurrent ``replay_after_with_ids`` can't observe the stored event
# without the Pub/Sub wake-up also having fired. Returns the same
# seq_num as ``_STORE_EVENT_LUA``.
#
# Built by replacing the final ``return seq_num`` of the base script
# with ``PUBLISH`` + ``return seq_num``. Use ``str.replace`` with
# ``count=-1`` so a drift in the base script is noticed (wrong number
# of replacements would produce an obviously-broken script).
_STORE_AND_NOTIFY_EVENT_LUA = _STORE_EVENT_LUA.replace(
    "return seq_num",
    "redis.call('PUBLISH', ARGV[7], ARGV[8])\nreturn seq_num",
    1,  # exactly one occurrence expected
)


# Best-effort atomic eviction of a single event. Used by the event bus
# after a failed ``store_event_with_notify`` EVAL: even with atomic
# Lua on the server side, the client-visible failure might mean the
# script ran server-side but the reply was lost (network drop between
# Redis completing execution and the TCP ack). ``evict_event`` is
# idempotent — if the event never landed, ZREM returns 0 and the
# script is a no-op.
_EVICT_EVENT_LUA = r"""
-- KEYS:
--  1) meta_key
--  2) events_key
--  3) messages_key
-- ARGV:
--  1) event_id
--  2) index_prefix

local meta_key = KEYS[1]
local events_key = KEYS[2]
local messages_key = KEYS[3]
local event_id = ARGV[1]
local index_prefix = ARGV[2]

-- Only evict if the event is actually present. Returning 0 tells the
-- caller the entry was already gone (idempotent).
local removed = redis.call('ZREM', events_key, event_id)
if removed == 0 then
  return 0
end
redis.call('HDEL', messages_key, event_id)
redis.call('DEL', index_prefix .. event_id)
local count = redis.call('HINCRBY', meta_key, 'count', -1)
if count < 0 then
  redis.call('HSET', meta_key, 'count', 0)
end
local first = redis.call('ZRANGE', events_key, 0, 0, 'WITHSCORES')
if #first >= 2 then
  redis.call('HSET', meta_key, 'start_seq', tonumber(first[2]))
end
return 1
"""


class RedisEventStore(EventStore):
    """Redis-backed event store for multi-worker Streamable HTTP."""

    def __init__(self, max_events_per_stream: int = 100, ttl: int = 3600, key_prefix: str = "mcpgw:eventstore"):
        """Initialize Redis event store.

        Args:
            max_events_per_stream: Maximum events per stream (ring buffer size).
            ttl: Stream TTL in seconds.
            key_prefix: Redis key prefix for namespacing this store's data. Primarily useful for test isolation.
        """
        self.max_events = max_events_per_stream
        self.ttl = ttl
        self.key_prefix = key_prefix.rstrip(":")
        logger.debug("RedisEventStore initialized: max_events=%s ttl=%ss", max_events_per_stream, ttl)

    def _get_stream_meta_key(self, stream_id: str) -> str:
        """Return Redis key for stream metadata hash.

        Args:
            stream_id: Unique stream identifier.

        Returns:
            Redis key string.
        """
        return f"{self.key_prefix}:{stream_id}:meta"

    def _get_stream_events_key(self, stream_id: str) -> str:
        """Return Redis key for stream events sorted set.

        Args:
            stream_id: Unique stream identifier.

        Returns:
            Redis key string.
        """
        return f"{self.key_prefix}:{stream_id}:events"

    def _get_stream_messages_key(self, stream_id: str) -> str:
        """Return Redis key for stream messages hash.

        Args:
            stream_id: Unique stream identifier.

        Returns:
            Redis key string.
        """
        return f"{self.key_prefix}:{stream_id}:messages"

    def _event_index_prefix(self) -> str:
        """Return prefix for per-event index keys.

        Returns:
            Prefix string for index keys.
        """
        return f"{self.key_prefix}:event_index:"

    def _event_index_key(self, event_id: str) -> str:
        """Return Redis key for event index lookup.

        Args:
            event_id: Unique event identifier.

        Returns:
            Redis key string.
        """
        return f"{self._event_index_prefix()}{event_id}"

    async def store_event(self, stream_id: str, message: JSONRPCMessage | None) -> str:
        """Store an event in Redis atomically.

        Args:
            stream_id: Unique stream identifier.
            message: JSON-RPC message to store (None for priming events).

        Returns:
            Unique event_id for this event.

        Raises:
            RuntimeError: If Redis client is not available.
        """
        redis: Redis = await get_redis_client()
        if redis is None:
            raise RuntimeError("Redis client not available - cannot store event")

        event_id = str(uuid.uuid4())

        # Convert message to dict for serialization (Pydantic model -> dict)
        message_dict = None if message is None else (message.model_dump() if hasattr(message, "model_dump") else dict(message))
        message_json = orjson.dumps(message_dict)

        meta_key = self._get_stream_meta_key(stream_id)
        events_key = self._get_stream_events_key(stream_id)
        messages_key = self._get_stream_messages_key(stream_id)

        await redis.eval(
            _STORE_EVENT_LUA,
            3,
            meta_key,
            events_key,
            messages_key,
            event_id,
            message_json,
            int(self.ttl),
            int(self.max_events),
            self._event_index_prefix(),
            stream_id,
        )

        return event_id

    async def store_event_with_notify(
        self,
        stream_id: str,
        message: JSONRPCMessage,
        *,
        channel: str,
        payload: bytes,
        event_id_override: Optional[str] = None,
    ) -> str:
        """Store an event and fire a ``PUBLISH`` wake-up in one atomic Lua script.

        Redis runs Lua atomically, so this eliminates the race window
        where a concurrent ``replay_after_with_ids`` could observe the
        stored event between ``store_event`` and a follow-up ``publish``
        (which could later fail and rollback) — the reader either sees
        nothing or sees the event *and* the wake-up has already been
        dispatched.

        Args:
            stream_id: Stream to store on.
            message: JSON-RPC message (non-None — priming events use
                the plain ``store_event`` path).
            channel: Pub/Sub channel to notify.
            payload: Pub/Sub payload bytes (typically references the
                returned event id, which callers pre-bind via
                ``event_id_override``).
            event_id_override: When supplied, use this as the event
                id instead of generating a fresh UUID. Lets callers
                that need the id inside ``payload`` construct both in
                one atomic step.

        Returns:
            Event id for the stored event (matches
            ``event_id_override`` when provided).

        Raises:
            RuntimeError: If the Redis client is unavailable.
        """
        redis: Redis = await get_redis_client()
        if redis is None:
            raise RuntimeError("Redis client not available - cannot store+notify event")

        event_id = event_id_override if event_id_override is not None else str(uuid.uuid4())
        message_dict = message.model_dump() if hasattr(message, "model_dump") else dict(message)
        message_json = orjson.dumps(message_dict)

        meta_key = self._get_stream_meta_key(stream_id)
        events_key = self._get_stream_events_key(stream_id)
        messages_key = self._get_stream_messages_key(stream_id)

        await redis.eval(
            _STORE_AND_NOTIFY_EVENT_LUA,
            3,
            meta_key,
            events_key,
            messages_key,
            event_id,
            message_json,
            int(self.ttl),
            int(self.max_events),
            self._event_index_prefix(),
            stream_id,
            channel,
            payload,
        )

        return event_id

    async def replay_events_after(self, last_event_id: str, send_callback: EventCallback) -> str | None:
        """Replay events after a specific event_id.

        Args:
            last_event_id: Event ID to replay from.
            send_callback: Async callback to receive replayed messages.

        Returns:
            stream_id if found, None if event not found or evicted.
        """
        redis: Redis = await get_redis_client()
        if redis is None:
            logger.debug("Redis client not available - cannot replay events")
            return None

        index_data = await redis.get(self._event_index_key(last_event_id))
        if not index_data:
            return None

        try:
            info = orjson.loads(index_data)
        except Exception:
            return None

        stream_id = info.get("stream_id")
        last_seq = info.get("seq_num")
        if not stream_id or last_seq is None:
            return None

        meta_key = self._get_stream_meta_key(stream_id)
        events_key = self._get_stream_events_key(stream_id)
        messages_key = self._get_stream_messages_key(stream_id)

        # Eviction detection: if last_seq < start_seq, the event is gone.
        start_seq_bytes = await redis.hget(meta_key, "start_seq")
        if start_seq_bytes:
            try:
                start_seq = int(start_seq_bytes)
            except Exception:
                start_seq = None
            if start_seq is not None and int(last_seq) < start_seq:
                return None

        event_ids = await redis.zrangebyscore(events_key, int(last_seq) + 1, "+inf")
        for event_id_bytes in event_ids:
            ev_id = event_id_bytes.decode("latin-1") if isinstance(event_id_bytes, (bytes, bytearray)) else str(event_id_bytes)
            msg_json = await redis.hget(messages_key, ev_id)
            if msg_json is None:
                continue
            try:
                msg = orjson.loads(msg_json)
            except Exception:
                msg = None
            await send_callback(msg)

        return stream_id

    async def replay_after_with_ids(
        self,
        stream_id: str,
        last_event_id: Optional[str],
    ) -> AsyncIterator[tuple[str, JSONRPCMessage]]:
        """Yield ``(event_id, message)`` for events strictly after ``last_event_id``.

        Unlike :meth:`replay_events_after` (the SDK contract), this preserves
        the original event id alongside the message — needed by callers that
        re-emit SSE frames where the ``id:`` field must round-trip end to
        end (ADR-052 GET stream).

        When ``last_event_id`` is ``None``, yields every event still in the
        ring buffer for ``stream_id``. This handles the reconnect-without-
        cursor case: a client that drops before receiving any event ids
        still needs the buffered server-initiated requests delivered, or
        the ``RequestResponder`` on the gateway side just times out.

        Yields nothing when:
            * the Redis client is unavailable,
            * the index entry for ``last_event_id`` has expired or never
              existed (the event was evicted from the ring buffer),
            * the index points at a different stream id than requested
              (defense against cross-session id collision).

        Args:
            stream_id: The stream to replay from.
            last_event_id: Resume cursor (exclusive). ``None`` means
                "replay everything in the buffer".

        Yields:
            ``(event_id, message)`` tuples in stream order.
        """
        redis: Redis = await get_redis_client()
        if redis is None:
            return
        if last_event_id is None:
            # Reconnect without cursor: yield everything currently in the
            # ring buffer. Use ``-inf`` as the lower bound of the score range.
            events_key = self._get_stream_events_key(stream_id)
            messages_key = self._get_stream_messages_key(stream_id)
            event_ids_all = await redis.zrangebyscore(events_key, "-inf", "+inf")
            for ev_bytes in event_ids_all:
                ev_id = ev_bytes.decode("latin-1") if isinstance(ev_bytes, (bytes, bytearray)) else str(ev_bytes)
                raw = await redis.hget(messages_key, ev_id)
                if raw is None:
                    continue
                try:
                    msg = JSONRPCMessage.model_validate(orjson.loads(raw))
                except Exception as exc:
                    logger.warning("Discarding malformed event %s for %s: %s", ev_id, stream_id, exc)
                    continue
                yield ev_id, msg
            return
        index_raw = await redis.get(self._event_index_key(last_event_id))
        if not index_raw:
            return
        try:
            info = orjson.loads(index_raw)
            cursor_stream_id = info["stream_id"]
            last_seq = int(info["seq_num"])
        except Exception as exc:  # noqa: BLE001 — log so corruption is visible to operators
            logger.warning(
                "Malformed event-index entry for %s on stream %s: %s",
                last_event_id,
                stream_id,
                exc,
            )
            return
        if cursor_stream_id != stream_id:
            # Could be benign (event id collision after eviction) or a
            # security signal (cross-tenant injection). Log so operators
            # can spot patterns without it being silently swallowed.
            logger.warning(
                "Cross-stream event-index mismatch for %s: index points at %s, requested %s",
                last_event_id,
                cursor_stream_id,
                stream_id,
            )
            return
        meta_key = self._get_stream_meta_key(stream_id)
        events_key = self._get_stream_events_key(stream_id)
        messages_key = self._get_stream_messages_key(stream_id)
        # Eviction detection: the index key TTLs out separately from the
        # ring-buffer entry, so a cursor whose seq < the buffer's
        # current start_seq is pointing past the surviving tail. Without
        # this guard, the GET stream would silently replay only the
        # post-eviction events and the client would never learn that
        # a gap was lost — exactly what Last-Event-Id resume is meant
        # to surface.
        start_seq_bytes = await redis.hget(meta_key, "start_seq")
        if start_seq_bytes:
            try:
                start_seq = int(start_seq_bytes)
            except (TypeError, ValueError):
                start_seq = None
            if start_seq is not None and last_seq < start_seq:
                logger.warning(
                    "Last-Event-Id %s on %s is older than buffer start_seq=%s; cursor evicted",
                    last_event_id,
                    stream_id,
                    start_seq,
                )
                return
        event_ids = await redis.zrangebyscore(events_key, last_seq + 1, "+inf")
        for ev_bytes in event_ids:
            ev_id = ev_bytes.decode("latin-1") if isinstance(ev_bytes, (bytes, bytearray)) else str(ev_bytes)
            raw = await redis.hget(messages_key, ev_id)
            if raw is None:
                continue
            try:
                msg = JSONRPCMessage.model_validate(orjson.loads(raw))
            except Exception as exc:
                logger.warning("Discarding malformed event %s for %s: %s", ev_id, stream_id, exc)
                continue
            yield ev_id, msg

    async def evict_event(self, stream_id: str, event_id: str) -> bool:
        """Best-effort removal of a single event from the ring buffer.

        Idempotent on data: returns ``True`` when the event was
        present and removed, ``False`` when it was already gone.
        Raises ``RuntimeError`` when the Redis client is unavailable
        — callers need to distinguish "nothing to clean up" from "we
        couldn't even check" (the latter is a potential orphan the
        operator should see in the logs).

        Used by ``RedisServerEventBus.publish`` after a failed
        ``store_event_with_notify`` EVAL: the Lua may have completed
        server-side even when the client saw an error, so we try to
        evict the event to prevent an orphan in the replay buffer.

        Args:
            stream_id: Stream the event belongs to.
            event_id: Event id passed to ``store_event_with_notify``.

        Returns:
            ``True`` if an event was removed, ``False`` if none was
            present to remove.

        Raises:
            RuntimeError: If the Redis client is unavailable.
        """
        redis: Redis = await get_redis_client()
        if redis is None:
            raise RuntimeError("Redis client not available - cannot verify/evict event")
        meta_key = self._get_stream_meta_key(stream_id)
        events_key = self._get_stream_events_key(stream_id)
        messages_key = self._get_stream_messages_key(stream_id)
        result = await redis.eval(
            _EVICT_EVENT_LUA,
            3,
            meta_key,
            events_key,
            messages_key,
            event_id,
            self._event_index_prefix(),
        )
        return bool(result)

    async def fetch_event(self, stream_id: str, event_id: str) -> Optional[JSONRPCMessage]:
        """Look up a single message body by event id on this stream.

        Returns ``None`` when the Redis client is unavailable, the event
        has been evicted, or the stored payload fails to validate.

        Args:
            stream_id: Stream the event belongs to.
            event_id: Event id assigned at ``store_event`` time.

        Returns:
            The validated JSON-RPC message, or ``None``.
        """
        redis: Redis = await get_redis_client()
        if redis is None:
            return None
        messages_key = self._get_stream_messages_key(stream_id)
        raw = await redis.hget(messages_key, event_id)
        if raw is None:
            return None
        try:
            return JSONRPCMessage.model_validate(orjson.loads(raw))
        except Exception as exc:
            logger.warning("Discarding malformed event %s for %s: %s", event_id, stream_id, exc)
            return None
