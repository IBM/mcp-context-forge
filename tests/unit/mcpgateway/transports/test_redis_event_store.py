# -*- coding: utf-8 -*-
"""
Unit tests for RedisEventStore.

Tests the Redis-backed event store implementation for multi-worker
stateful Streamable HTTP sessions.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

import orjson
import pytest

from mcpgateway.transports.redis_event_store import RedisEventStore


class InMemoryRedisClient:
    """Minimal async Redis simulation for RedisEventStore unit tests."""

    def __init__(self) -> None:
        self._meta: dict[str, dict[str, int]] = {}
        self._events: dict[str, list[tuple[int, str]]] = {}
        self._messages: dict[str, dict[str, bytes]] = {}
        self._kv: dict[str, bytes] = {}
        self._expires_at: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    def _purge_expired_key(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is not None and expires_at <= self._now():
            self._meta.pop(key, None)
            self._events.pop(key, None)
            self._messages.pop(key, None)
            self._kv.pop(key, None)
            self._expires_at.pop(key, None)

    def _purge_all_expired(self) -> None:
        for key in list(self._expires_at):
            self._purge_expired_key(key)

    def _set_expiry(self, key: str, ttl: int) -> None:
        self._expires_at[key] = self._now() + ttl

    def _has_key(self, key: str) -> bool:
        self._purge_expired_key(key)
        return key in self._meta or key in self._events or key in self._messages or key in self._kv

    async def eval(
        self,
        _script: str,
        _num_keys: int,
        meta_key: str,
        events_key: str,
        messages_key: str,
        event_id: str,
        message_json: bytes,
        ttl: int,
        max_events: int,
        index_prefix: str,
        stream_id: str,
    ) -> int:
        async with self._lock:
            self._purge_expired_key(meta_key)
            self._purge_expired_key(events_key)
            self._purge_expired_key(messages_key)

            meta = self._meta.setdefault(meta_key, {"next_seq": 0, "count": 0})
            events = self._events.setdefault(events_key, [])
            messages = self._messages.setdefault(messages_key, {})

            seq_num = int(meta.get("next_seq", 0)) + 1
            count = int(meta.get("count", 0)) + 1
            meta["next_seq"] = seq_num
            meta["count"] = count

            if count == 1:
                meta["start_seq"] = seq_num

            events.append((seq_num, event_id))
            messages[event_id] = bytes(message_json)

            index_key = f"{index_prefix}{event_id}"
            self._kv[index_key] = orjson.dumps({"stream_id": stream_id, "seq_num": seq_num})
            self._set_expiry(index_key, int(ttl))

            if count > int(max_events):
                to_evict = count - int(max_events)
                evicted = events[:to_evict]
                del events[:to_evict]

                for _, evicted_id in evicted:
                    messages.pop(evicted_id, None)
                    evicted_index_key = f"{index_prefix}{evicted_id}"
                    self._kv.pop(evicted_index_key, None)
                    self._expires_at.pop(evicted_index_key, None)

                meta["count"] = int(max_events)
                if events:
                    meta["start_seq"] = events[0][0]
                else:
                    meta["start_seq"] = seq_num

            self._set_expiry(meta_key, int(ttl))
            self._set_expiry(events_key, int(ttl))
            self._set_expiry(messages_key, int(ttl))
            return seq_num

    async def get(self, key: str):
        async with self._lock:
            self._purge_expired_key(key)
            return self._kv.get(key)

    async def hget(self, key: str, field: str):
        async with self._lock:
            self._purge_expired_key(key)
            if key in self._meta:
                value = self._meta[key].get(field)
                if value is None:
                    return None
                return str(value).encode("utf-8")
            if key in self._messages:
                return self._messages[key].get(field)
            return None

    async def zrangebyscore(self, key: str, min_score, max_score):
        async with self._lock:
            self._purge_expired_key(key)
            events = self._events.get(key, [])
            minimum = float(min_score)
            maximum = float("inf") if max_score == "+inf" else float(max_score)
            return [event_id.encode("utf-8") for seq_num, event_id in events if minimum <= seq_num <= maximum]

    async def exists(self, key: str) -> int:
        async with self._lock:
            return int(self._has_key(key))

    async def keys(self, pattern: str):
        async with self._lock:
            self._purge_all_expired()
            all_keys = set(self._meta) | set(self._events) | set(self._messages) | set(self._kv)
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                return [key for key in all_keys if key.startswith(prefix)]
            return [key for key in all_keys if key == pattern]

    async def delete(self, *keys: str) -> int:
        async with self._lock:
            deleted = 0
            for key in keys:
                key_existed = self._has_key(key)
                self._meta.pop(key, None)
                self._events.pop(key, None)
                self._messages.pop(key, None)
                self._kv.pop(key, None)
                self._expires_at.pop(key, None)
                deleted += int(key_existed)
            return deleted


@pytest.fixture
def fake_redis_client():
    """In-memory Redis client used by unit tests."""
    return InMemoryRedisClient()


@pytest.fixture
async def redis_event_store(monkeypatch, fake_redis_client):
    """Create a RedisEventStore instance for testing."""
    monkeypatch.setattr(
        "mcpgateway.transports.redis_event_store.get_redis_client",
        AsyncMock(return_value=fake_redis_client),
    )

    # Use a per-test prefix to avoid cross-test interference under xdist.
    key_prefix = f"mcpgw:eventstore:test:{uuid.uuid4().hex}"
    store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix=key_prefix)
    yield store


@pytest.fixture
async def messages():
    """Sample JSON-RPC messages for testing."""
    return [
        {"jsonrpc": "2.0", "method": "initialize", "id": 1},
        {"jsonrpc": "2.0", "method": "tools/list", "id": 2},
        {"jsonrpc": "2.0", "result": {"tools": []}, "id": 2},
        {"jsonrpc": "2.0", "method": "resources/list", "id": 3},
        {"jsonrpc": "2.0", "result": {"resources": []}, "id": 3},
    ]


class TestRedisEventStore:
    """Test suite for RedisEventStore."""

    async def test_store_and_replay_basic(self, redis_event_store, messages):
        """Store events and replay from event_id."""
        stream_id = "test-stream-1"
        event_ids = []

        # Store events
        for msg in messages:
            event_id = await redis_event_store.store_event(stream_id, msg)
            event_ids.append(event_id)

        # Replay from second event
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result_stream_id = await redis_event_store.replay_events_after(event_ids[1], callback)

        # Should replay events 3, 4, 5 (after event 2)
        assert result_stream_id == stream_id
        assert len(replayed) == 3
        assert replayed[0] == messages[2]
        assert replayed[1] == messages[3]
        assert replayed[2] == messages[4]

    async def test_eviction(self, redis_event_store):
        """Ring buffer evicts oldest when exceeding max_events."""
        stream_id = "test-stream-eviction"
        event_ids = []

        # Store 15 events (max is 10)
        for i in range(15):
            msg = {"jsonrpc": "2.0", "method": f"test_{i}", "id": i}
            event_id = await redis_event_store.store_event(stream_id, msg)
            event_ids.append(event_id)

        # Try to replay from first event (should be evicted)
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await redis_event_store.replay_events_after(event_ids[0], callback)

        # First event evicted, should return None
        assert result is None

        # Replay from 6th event (should still exist)
        replayed.clear()
        result = await redis_event_store.replay_events_after(event_ids[5], callback)

        assert result == stream_id
        # Should get events 7-15 (9 events)
        assert len(replayed) == 9

    async def test_replay_evicted_event(self, redis_event_store):
        """Return None when trying to replay evicted event."""
        stream_id = "test-stream-evicted"

        # Store 15 events (max is 10)
        event_ids = []
        for i in range(15):
            msg = {"jsonrpc": "2.0", "method": f"test_{i}", "id": i}
            event_id = await redis_event_store.store_event(stream_id, msg)
            event_ids.append(event_id)

        # First 5 events should be evicted
        for i in range(5):
            result = await redis_event_store.replay_events_after(event_ids[i], lambda msg: None)
            assert result is None, f"Event {i} should be evicted"

    async def test_multiple_streams(self, redis_event_store):
        """Independent streams don't interfere."""
        stream1 = "test-stream-1"
        stream2 = "test-stream-2"

        # Store events in stream 1
        msg1 = {"jsonrpc": "2.0", "method": "stream1_test", "id": 1}
        event1 = await redis_event_store.store_event(stream1, msg1)

        # Store events in stream 2
        msg2 = {"jsonrpc": "2.0", "method": "stream2_test", "id": 2}
        event2 = await redis_event_store.store_event(stream2, msg2)

        # Replay stream 1
        replayed1 = []

        async def callback1(msg):
            replayed1.append(msg)

        result1 = await redis_event_store.replay_events_after(event1, callback1)

        # Replay stream 2
        replayed2 = []

        async def callback2(msg):
            replayed2.append(msg)

        result2 = await redis_event_store.replay_events_after(event2, callback2)

        # Should get correct stream IDs back
        assert result1 == stream1
        assert result2 == stream2

        # No cross-contamination
        assert len(replayed1) == 0  # No events after event1 in stream1
        assert len(replayed2) == 0  # No events after event2 in stream2

    async def test_ttl_expiration(self, redis_event_store, fake_redis_client):
        """Streams expire after TTL."""
        # Create store with very short TTL
        short_ttl_store = RedisEventStore(max_events_per_stream=10, ttl=1)

        stream_id = "test-stream-ttl"
        msg = {"jsonrpc": "2.0", "method": "test", "id": 1}
        event_id = await short_ttl_store.store_event(stream_id, msg)

        # Should exist immediately
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await short_ttl_store.replay_events_after(event_id, callback)
        assert result == stream_id

        # Wait for TTL to expire
        await asyncio.sleep(2)

        # Verify stream keys expired in Redis
        redis = fake_redis_client
        meta_key = f"mcpgw:eventstore:{stream_id}:meta"
        events_key = f"mcpgw:eventstore:{stream_id}:events"
        messages_key = f"mcpgw:eventstore:{stream_id}:messages"
        index_key = f"mcpgw:eventstore:event_index:{event_id}"
        meta_exists = await redis.exists(meta_key)
        events_exists = await redis.exists(events_key)
        messages_exists = await redis.exists(messages_key)
        index_exists = await redis.exists(index_key)

        # Keys should be expired
        assert meta_exists == 0
        assert events_exists == 0
        assert messages_exists == 0
        # Index entries expire with the stream TTL to prevent unbounded growth.
        assert index_exists == 0

    async def test_concurrent_workers(self, redis_event_store):
        """Multiple workers can store/replay to same stream."""
        stream_id = "test-stream-concurrent"

        # Store a marker event first to get a baseline event_id
        marker_msg = {"jsonrpc": "2.0", "method": "marker", "id": 0}
        marker_event_id = await redis_event_store.store_event(stream_id, marker_msg)

        # Simulate 3 workers storing events concurrently
        async def worker_store(worker_id, count):
            event_ids = []
            for i in range(count):
                msg = {"jsonrpc": "2.0", "method": f"worker_{worker_id}_msg_{i}", "id": i}
                event_id = await redis_event_store.store_event(stream_id, msg)
                event_ids.append(event_id)
                await asyncio.sleep(0.01)  # Small delay to simulate real work
            return event_ids

        # Run 3 workers in parallel
        results = await asyncio.gather(worker_store(1, 3), worker_store(2, 3), worker_store(3, 3))

        # All workers should have stored events
        all_event_ids = [event_id for worker_events in results for event_id in worker_events]
        assert len(all_event_ids) == 9

        # Replay from marker event - should get all 9 worker events
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await redis_event_store.replay_events_after(marker_event_id, callback)

        # Should replay all events after marker
        assert result == stream_id
        assert len(replayed) == 9  # All worker events

    async def test_none_message(self, redis_event_store):
        """Handle priming events (None messages)."""
        stream_id = "test-stream-none"

        # Store None message (priming event)
        event_id = await redis_event_store.store_event(stream_id, None)
        assert event_id is not None

        # Store real message
        msg = {"jsonrpc": "2.0", "method": "test", "id": 1}
        event_id2 = await redis_event_store.store_event(stream_id, msg)

        # Replay from None event
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await redis_event_store.replay_events_after(event_id, callback)

        # Should replay the real message
        assert result == stream_id
        assert len(replayed) == 1
        assert replayed[0] == msg

    async def test_replay_nonexistent_event(self, redis_event_store):
        """Return None when event_id doesn't exist."""
        fake_event_id = "00000000-0000-0000-0000-000000000000"

        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await redis_event_store.replay_events_after(fake_event_id, callback)

        assert result is None
        assert len(replayed) == 0

    async def test_empty_stream_replay(self, redis_event_store):
        """Replay from last event in stream returns empty."""
        stream_id = "test-stream-empty-replay"

        # Store single event
        msg = {"jsonrpc": "2.0", "method": "test", "id": 1}
        event_id = await redis_event_store.store_event(stream_id, msg)

        # Replay from the only event
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await redis_event_store.replay_events_after(event_id, callback)

        # Should return stream_id but with no events to replay
        assert result == stream_id
        assert len(replayed) == 0

    async def test_sequence_ordering(self, redis_event_store):
        """Events are replayed in correct sequence order."""
        # Create store with larger capacity to avoid eviction during this test
        large_store = RedisEventStore(max_events_per_stream=30, ttl=60, key_prefix=redis_event_store.key_prefix)

        stream_id = "test-stream-ordering"
        messages = [{"jsonrpc": "2.0", "method": f"msg_{i}", "id": i} for i in range(20)]

        event_ids = []
        for msg in messages:
            event_id = await large_store.store_event(stream_id, msg)
            event_ids.append(event_id)

        # Replay from 5th event
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await large_store.replay_events_after(event_ids[4], callback)

        # Should get messages 5-19 in order
        assert result == stream_id
        assert len(replayed) == 15
        for i, msg in enumerate(replayed):
            assert msg["method"] == f"msg_{i + 5}"

    async def test_store_event_raises_when_redis_client_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:mocked")
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=None),
        )

        with pytest.raises(RuntimeError, match="Redis client not available"):
            await store.store_event("stream", {"jsonrpc": "2.0", "method": "test", "id": 1})

    async def test_replay_events_after_returns_none_when_redis_client_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:mocked")
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=None),
        )

        callback = AsyncMock()
        assert await store.replay_events_after("event-id", callback) is None
        callback.assert_not_awaited()

    async def test_replay_events_after_returns_none_for_invalid_index_data(self, monkeypatch: pytest.MonkeyPatch):
        class DummyRedis:
            def __init__(self) -> None:
                self.get = AsyncMock(return_value=b"{")  # invalid JSON

        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:mocked")
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        callback = AsyncMock()
        assert await store.replay_events_after("event-id", callback) is None
        callback.assert_not_awaited()

    async def test_replay_events_after_returns_none_when_index_missing_fields(self, monkeypatch: pytest.MonkeyPatch):
        import orjson

        class DummyRedis:
            def __init__(self) -> None:
                self.get = AsyncMock(return_value=orjson.dumps({"stream_id": "s"}))  # seq_num missing

        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:mocked")
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        callback = AsyncMock()
        assert await store.replay_events_after("event-id", callback) is None
        callback.assert_not_awaited()

    async def test_replay_events_after_handles_bad_start_seq_and_bad_messages(self, monkeypatch: pytest.MonkeyPatch):
        import orjson

        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:mocked")
        stream_id = "s"
        meta_key = store._get_stream_meta_key(stream_id)
        messages_key = store._get_stream_messages_key(stream_id)

        class DummyRedis:
            def __init__(self) -> None:
                self.get = AsyncMock(return_value=orjson.dumps({"stream_id": stream_id, "seq_num": 1}))
                self.zrangebyscore = AsyncMock(return_value=[b"ev-1", b"ev-2"])
                self.hget = AsyncMock(side_effect=self._hget)

            async def _hget(self, key: str, field: str):
                if key == meta_key and field == "start_seq":
                    return b"not-int"
                if key == messages_key and field == "ev-1":
                    return None
                if key == messages_key and field == "ev-2":
                    return b"{"  # invalid JSON -> replay None
                raise AssertionError(f"Unexpected hget: {key=} {field=}")

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        callback = AsyncMock()
        assert await store.replay_events_after("event-id", callback) == stream_id
        callback.assert_awaited_once_with(None)

    async def test_replay_events_after_returns_none_when_event_evicted_by_start_seq(self, monkeypatch: pytest.MonkeyPatch):
        import orjson

        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:mocked")
        stream_id = "s"
        meta_key = store._get_stream_meta_key(stream_id)

        class DummyRedis:
            def __init__(self) -> None:
                self.get = AsyncMock(return_value=orjson.dumps({"stream_id": stream_id, "seq_num": 1}))
                self.hget = AsyncMock(side_effect=self._hget)
                self.zrangebyscore = AsyncMock()

            async def _hget(self, key: str, field: str):
                if key == meta_key and field == "start_seq":
                    return b"10"  # start_seq > last_seq -> evicted
                raise AssertionError(f"Unexpected hget: {key=} {field=}")

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        callback = AsyncMock()
        assert await store.replay_events_after("event-id", callback) is None
        callback.assert_not_awaited()

    async def test_replay_events_after_with_missing_start_seq_still_replays(self, monkeypatch: pytest.MonkeyPatch):
        import orjson

        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:mocked")
        stream_id = "s"
        messages_key = store._get_stream_messages_key(stream_id)

        class DummyRedis:
            def __init__(self) -> None:
                self.get = AsyncMock(return_value=orjson.dumps({"stream_id": stream_id, "seq_num": 1}))
                self.zrangebyscore = AsyncMock(return_value=[b"ev-2"])
                self.hget = AsyncMock(side_effect=self._hget)

            async def _hget(self, key: str, field: str):
                if field == "start_seq":
                    return None
                if key == messages_key and field == "ev-2":
                    return orjson.dumps({"jsonrpc": "2.0", "id": 2})
                raise AssertionError(f"Unexpected hget: {key=} {field=}")

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        callback = AsyncMock()
        assert await store.replay_events_after("event-id", callback) == stream_id
        callback.assert_awaited_once()
