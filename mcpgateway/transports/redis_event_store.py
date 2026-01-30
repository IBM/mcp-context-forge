"""
Redis-backed event store for Streamable HTTP stateful sessions.

Provides distributed event storage across multiple gateway workers using Redis,
enabling stateful MCP sessions to work correctly behind load balancers.

Architecture:
- Uses Redis Sorted Sets for ordered event storage with ring buffer semantics
- Events indexed by event_id for O(1) lookup during replay
- Automatic eviction when exceeding max_events_per_stream
- TTL-based cleanup for expired streams
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

if TYPE_CHECKING:
    # Third-Party
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RedisEventStore(EventStore):
    """
    Redis-backed event store for multi-worker deployments.

    Data Model:
        Per Stream:
        - Hash: mcpgw:eventstore:{stream_id}:meta
          - start_seq: Oldest sequence number (for eviction detection)
          - next_seq: Next sequence number to assign
          - count: Current event count

        - Sorted Set: mcpgw:eventstore:{stream_id}:events
          - Score: sequence number
          - Value: JSON {event_id, message, seq_num}

        Global:
        - Hash: mcpgw:eventstore:event_index
          - Key: event_id -> Value: JSON {stream_id, seq_num}

    Examples:
        >>> # Create event store with custom settings
        >>> store = RedisEventStore(max_events_per_stream=200, ttl=7200)

        >>> # Store an event
        >>> event_id = await store.store_event("stream-123", message)

        >>> # Replay events after a specific event_id
        >>> async def callback(msg):
        ...     print(f"Replayed: {msg}")
        >>> stream_id = await store.replay_events_after(event_id, callback)
    """

    def __init__(self, max_events_per_stream: int = 100, ttl: int = 3600):
        """
        Initialize Redis event store.

        Args:
            max_events_per_stream: Maximum events per stream (ring buffer size)
            ttl: Stream TTL in seconds (default 1 hour)
        """
        self.max_events = max_events_per_stream
        self.ttl = ttl
        logger.info(f"RedisEventStore initialized: max_events={max_events_per_stream}, ttl={ttl}s")

    def _get_stream_meta_key(self, stream_id: str) -> str:
        """Get Redis key for stream metadata."""
        return f"mcpgw:eventstore:{stream_id}:meta"

    def _get_stream_events_key(self, stream_id: str) -> str:
        """Get Redis key for stream events sorted set."""
        return f"mcpgw:eventstore:{stream_id}:events"

    def _get_event_index_key(self) -> str:
        """Get Redis key for global event index."""
        return "mcpgw:eventstore:event_index"

    async def store_event(self, stream_id: str, message: JSONRPCMessage | None) -> str:
        """
        Store an event in Redis.

        Args:
            stream_id: Unique stream identifier
            message: JSON-RPC message to store (None for priming events)

        Returns:
            Unique event_id for this event

        Examples:
            >>> event_id = await store.store_event("stream-123", {"jsonrpc": "2.0", "method": "test"})
            >>> isinstance(event_id, str)
            True
        """
        redis: Redis = await get_redis_client()
        event_id = str(uuid.uuid4())

        logger.info(f"[REDIS_EVENTSTORE] Storing event | stream_id={stream_id} | event_id={event_id} | message_type={type(message).__name__ if message else 'None'}")

        meta_key = self._get_stream_meta_key(stream_id)
        events_key = self._get_stream_events_key(stream_id)
        index_key = self._get_event_index_key()

        # Atomically increment sequence number
        seq_num = await redis.hincrby(meta_key, "next_seq", 1)

        # Convert message to dict for serialization (Pydantic model -> dict)
        message_dict = None if message is None else (message.model_dump() if hasattr(message, "model_dump") else dict(message))

        # Serialize event data
        event_data = orjson.dumps({"event_id": event_id, "message": message_dict, "seq_num": seq_num})

        # Store event in sorted set (score = seq_num)
        await redis.zadd(events_key, {event_data: seq_num})

        # Index event_id for lookup
        index_data = orjson.dumps({"stream_id": stream_id, "seq_num": seq_num})
        await redis.hset(index_key, event_id, index_data)

        # Increment count
        count = await redis.hincrby(meta_key, "count", 1)

        # Handle eviction if exceeding max_events
        if count > self.max_events:
            # Calculate how many to evict
            to_evict = count - self.max_events

            # Get events to evict (oldest by rank)
            evicted = await redis.zrange(events_key, 0, to_evict - 1)

            # Remove from sorted set
            await redis.zremrangebyrank(events_key, 0, to_evict - 1)

            # Remove from event index and update start_seq
            for event_bytes in evicted:
                evicted_event = orjson.loads(event_bytes)
                await redis.hdel(index_key, evicted_event["event_id"])

            # Update start_seq to first remaining event
            remaining = await redis.zrange(events_key, 0, 0, withscores=True)
            if remaining:
                _, start_seq = remaining[0]
                await redis.hset(meta_key, "start_seq", int(start_seq))

            # Update count
            await redis.hset(meta_key, "count", self.max_events)

        # Set TTL on stream keys
        await redis.expire(meta_key, self.ttl)
        await redis.expire(events_key, self.ttl)

        logger.debug(f"Stored event {event_id} in stream {stream_id} (seq={seq_num})")
        return event_id

    async def replay_events_after(self, last_event_id: str, send_callback: EventCallback) -> str | None:
        """
        Replay events after a specific event_id.

        Args:
            last_event_id: Event ID to replay from
            send_callback: Async callback to receive replayed messages

        Returns:
            stream_id if found, None if event not found or evicted

        Examples:
            >>> messages = []
            >>> async def callback(msg):
            ...     messages.append(msg)
            >>> stream_id = await store.replay_events_after(event_id, callback)
            >>> len(messages) > 0
            True
        """
        redis: Redis = await get_redis_client()
        index_key = self._get_event_index_key()

        logger.info(f"[REDIS_EVENTSTORE] Replaying events | last_event_id={last_event_id}")

        # Lookup event in index
        index_data = await redis.hget(index_key, last_event_id)
        if not index_data:
            logger.warning(f"[REDIS_EVENTSTORE] Event not found in index | last_event_id={last_event_id}")
            return None

        event_info = orjson.loads(index_data)
        stream_id = event_info["stream_id"]
        last_seq = event_info["seq_num"]

        meta_key = self._get_stream_meta_key(stream_id)
        events_key = self._get_stream_events_key(stream_id)

        # Check if event still in buffer (not evicted)
        start_seq_bytes = await redis.hget(meta_key, "start_seq")
        if start_seq_bytes:
            start_seq = int(start_seq_bytes)
            if last_seq < start_seq:
                logger.warning(f"Event {last_event_id} evicted from stream {stream_id} (seq {last_seq} < start {start_seq})")
                return None

        # Get all events after last_seq
        events = await redis.zrangebyscore(events_key, last_seq + 1, "+inf")

        # Replay events
        for event_bytes in events:
            event_data = orjson.loads(event_bytes)
            message = event_data["message"]
            await send_callback(message)

        logger.info(f"[REDIS_EVENTSTORE] Replayed events | stream_id={stream_id} | last_event_id={last_event_id} | count={len(events)}")
        return stream_id
