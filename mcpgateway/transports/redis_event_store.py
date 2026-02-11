# -*- coding: utf-8 -*-
"""
Redis-backed event store for Streamable HTTP stateful sessions.

Design goals:
- Multi-worker safe: store+evict is atomic (Lua), so concurrent writers do not corrupt meta/count.
- Bounded memory: per-stream ring buffer with eviction.
- Bounded index growth: event_id index entries expire with the stream TTL.
"""

# Standard
import logging
from typing import TYPE_CHECKING
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
