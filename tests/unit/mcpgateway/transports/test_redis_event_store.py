# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_redis_event_store.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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

    async def test_ttl_expiration(self, redis_event_store, fake_redis_client, monkeypatch):
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

        # Advance the fake redis clock past the TTL instead of sleeping
        original_now = fake_redis_client._now
        monkeypatch.setattr(fake_redis_client, "_now", lambda: original_now() + 2)

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

    async def test_replay_after_with_ids_drops_cross_stream_index_entry(self, monkeypatch: pytest.MonkeyPatch):
        """Tenancy guard: a stale Last-Event-Id whose index points at another session must NOT replay.

        Without this gate, a forged or collision-recycled Last-Event-Id could be used
        to read another session's buffered events.
        """
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:cross")

        class DummyRedis:
            def __init__(self) -> None:
                # Index says event "ev-victim" lives on stream "victim", but the caller
                # asks to replay it on stream "attacker".
                self.get = AsyncMock(return_value=orjson.dumps({"stream_id": "victim", "seq_num": 5}))
                self.hget = AsyncMock(side_effect=AssertionError("must NOT touch any data after the cross-stream check"))
                self.zrangebyscore = AsyncMock(side_effect=AssertionError("must NOT enumerate the buffer"))

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        results = [item async for item in store.replay_after_with_ids("attacker", "ev-victim")]
        assert results == [], "cross-stream index entry must yield no events"

    async def test_replay_after_with_ids_returns_empty_when_cursor_evicted(self, monkeypatch: pytest.MonkeyPatch):
        """Codex P2 regression: stale Last-Event-Id below start_seq must NOT replay only the surviving tail.

        Without the start_seq check, a reconnect with an evicted cursor would
        silently miss the gap between the cursor and the buffer head.
        """
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:evict")
        stream_id = "s"
        meta_key = store._get_stream_meta_key(stream_id)

        class DummyRedis:
            def __init__(self) -> None:
                self.get = AsyncMock(return_value=orjson.dumps({"stream_id": stream_id, "seq_num": 1}))
                self.hget = AsyncMock(side_effect=self._hget)
                self.zrangebyscore = AsyncMock(side_effect=AssertionError("must NOT enumerate the buffer when cursor evicted"))

            async def _hget(self, key: str, field: str):
                if key == meta_key and field == "start_seq":
                    return b"10"  # cursor seq=1 < start_seq=10 → evicted
                raise AssertionError(f"Unexpected hget: {key=} {field=}")

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        results = [item async for item in store.replay_after_with_ids(stream_id, "ev-stale")]
        assert results == [], "evicted cursor must yield no events (caller treats as 'too old')"

    async def test_replay_after_with_ids_replays_entire_buffer_when_cursor_is_none(self, monkeypatch: pytest.MonkeyPatch):
        """Codex P1 regression: ``last_event_id=None`` must yield every buffered event.

        Reconnect-without-cursor path: a client whose connection dropped
        before any event ids reached it has no Last-Event-Id, but the
        ring buffer holds events (most importantly server-initiated
        requests) that we MUST deliver — otherwise the gateway-side
        ``RequestResponder`` TTLs out and the request silently disappears.
        """
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:nocursor")
        stream_id = "s"
        events_key = store._get_stream_events_key(stream_id)
        messages_key = store._get_stream_messages_key(stream_id)

        class DummyRedis:
            def __init__(self) -> None:
                # No index lookup — None cursor skips that path entirely.
                self.get = AsyncMock(side_effect=AssertionError("must NOT touch the event-id index when cursor is None"))
                self.zrangebyscore = AsyncMock(return_value=[b"ev-1", b"ev-2"])
                self.hget = AsyncMock(side_effect=self._hget)

            async def _hget(self, key: str, field: str):
                if key == messages_key and field == "ev-1":
                    return orjson.dumps({"jsonrpc": "2.0", "method": "notifications/before"})
                if key == messages_key and field == "ev-2":
                    return orjson.dumps({"jsonrpc": "2.0", "method": "notifications/after"})
                raise AssertionError(f"Unexpected hget: {key=} {field=}")

        dummy = DummyRedis()
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=dummy),
        )

        results = [item async for item in store.replay_after_with_ids(stream_id, None)]
        assert len(results) == 2
        assert [eid for eid, _ in results] == ["ev-1", "ev-2"]
        # Used the -inf score range, not the cursor index.
        dummy.zrangebyscore.assert_awaited_once_with(events_key, "-inf", "+inf")

    async def test_replay_after_with_ids_replays_when_start_seq_missing(self, monkeypatch: pytest.MonkeyPatch):
        """Missing start_seq (no metadata yet) is treated as 'no eviction recorded' — replay proceeds."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:nostart")
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
                    return orjson.dumps({"jsonrpc": "2.0", "method": "notifications/test"})
                raise AssertionError(f"Unexpected hget: {key=} {field=}")

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        results = [item async for item in store.replay_after_with_ids(stream_id, "ev-stale")]
        assert len(results) == 1
        assert results[0][0] == "ev-2"

    # ----------------------------------------------------------------------
    # store_event_with_notify
    # ----------------------------------------------------------------------

    async def test_store_event_with_notify_raises_when_redis_client_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        """RuntimeError when Redis client is unavailable on the notify path."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:notify-nored")
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=None),
        )

        with pytest.raises(RuntimeError, match="Redis client not available"):
            await store.store_event_with_notify(
                "stream",
                {"jsonrpc": "2.0", "method": "notifications/test"},
                channel="chan",
                payload=b"evid",
            )

    async def test_store_event_with_notify_happy_path_generates_event_id(self, monkeypatch: pytest.MonkeyPatch):
        """Happy path: EVAL is invoked with the 12-arg store-and-notify signature and a UUID event id."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:notify-gen")

        class DummyRedis:
            def __init__(self) -> None:
                self.eval = AsyncMock(return_value=1)

        dummy = DummyRedis()
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=dummy),
        )

        stream_id = "stream-notify"
        msg = {"jsonrpc": "2.0", "method": "notifications/test"}
        event_id = await store.store_event_with_notify(stream_id, msg, channel="ch", payload=b"pl")

        # Generated event ids are uuid4 hex-with-dashes; just validate shape.
        uuid.UUID(event_id)

        # Inspect EVAL call: 3 keys + 8 argv = 11 positional args after the script.
        dummy.eval.assert_awaited_once()
        call_args = dummy.eval.call_args
        script = call_args.args[0]
        assert "PUBLISH" in script, "must use the store-and-notify Lua variant"
        num_keys = call_args.args[1]
        assert num_keys == 3
        meta_key = call_args.args[2]
        events_key = call_args.args[3]
        messages_key = call_args.args[4]
        assert meta_key == store._get_stream_meta_key(stream_id)
        assert events_key == store._get_stream_events_key(stream_id)
        assert messages_key == store._get_stream_messages_key(stream_id)
        argv_event_id = call_args.args[5]
        assert argv_event_id == event_id
        argv_message_json = call_args.args[6]
        assert orjson.loads(argv_message_json) == msg
        assert call_args.args[7] == 60  # ttl
        assert call_args.args[8] == 10  # max_events
        assert call_args.args[9] == store._event_index_prefix()
        assert call_args.args[10] == stream_id
        assert call_args.args[11] == "ch"
        assert call_args.args[12] == b"pl"

    async def test_store_event_with_notify_uses_event_id_override(self, monkeypatch: pytest.MonkeyPatch):
        """event_id_override is passed through to the EVAL ARGV."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:notify-override")

        class DummyRedis:
            def __init__(self) -> None:
                self.eval = AsyncMock(return_value=1)

        dummy = DummyRedis()
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=dummy),
        )

        forced = "00000000-0000-0000-0000-0000000000aa"
        returned = await store.store_event_with_notify(
            "stream-x",
            {"jsonrpc": "2.0", "method": "notifications/test"},
            channel="chan",
            payload=b"pl",
            event_id_override=forced,
        )
        assert returned == forced
        # ARGV[1] must be the override
        assert dummy.eval.call_args.args[5] == forced

    async def test_store_event_with_notify_handles_dict_like_message_without_model_dump(self, monkeypatch: pytest.MonkeyPatch):
        """Messages that don't expose model_dump fall back to dict(message)."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:notify-dict")

        class DummyRedis:
            def __init__(self) -> None:
                self.eval = AsyncMock(return_value=1)

        dummy = DummyRedis()
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=dummy),
        )

        # Plain dict has no model_dump; dict() of a dict returns a copy.
        msg = {"jsonrpc": "2.0", "method": "notifications/plain"}
        await store.store_event_with_notify("s", msg, channel="c", payload=b"p")

        assert orjson.loads(dummy.eval.call_args.args[6]) == msg

    # ----------------------------------------------------------------------
    # replay_after_with_ids: remaining edge cases
    # ----------------------------------------------------------------------

    async def test_replay_after_with_ids_returns_when_redis_client_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        """Line 430: redis=None yields nothing."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:ri-nored")
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=None),
        )
        results = [item async for item in store.replay_after_with_ids("s", "evid")]
        assert results == []

        # None cursor path also short-circuits cleanly with no Redis.
        results = [item async for item in store.replay_after_with_ids("s", None)]
        assert results == []

    async def test_replay_after_with_ids_none_cursor_skips_missing_and_malformed_entries(self, monkeypatch: pytest.MonkeyPatch):
        """Line 441 (hget returns None → continue) and 444-446 (malformed JSON → log + continue)."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:ri-none-edge")
        stream_id = "s"
        messages_key = store._get_stream_messages_key(stream_id)

        class DummyRedis:
            def __init__(self) -> None:
                self.zrangebyscore = AsyncMock(return_value=[b"gone", b"bad", b"ok"])
                self.hget = AsyncMock(side_effect=self._hget)

            async def _hget(self, key: str, field: str):
                assert key == messages_key
                if field == "gone":
                    return None  # 441 continue
                if field == "bad":
                    return b"{"  # malformed JSON -> 444-446
                if field == "ok":
                    return orjson.dumps({"jsonrpc": "2.0", "method": "notifications/ok"})
                raise AssertionError("unexpected field")

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        results = [item async for item in store.replay_after_with_ids(stream_id, None)]
        assert len(results) == 1
        assert results[0][0] == "ok"

    async def test_replay_after_with_ids_returns_when_index_missing(self, monkeypatch: pytest.MonkeyPatch):
        """Line 451: index lookup returns nothing → yield nothing."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:ri-idx-missing")

        class DummyRedis:
            def __init__(self) -> None:
                self.get = AsyncMock(return_value=None)
                self.hget = AsyncMock(side_effect=AssertionError("must not read meta/messages"))
                self.zrangebyscore = AsyncMock(side_effect=AssertionError("must not enumerate"))

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        results = [item async for item in store.replay_after_with_ids("s", "evid")]
        assert results == []

    async def test_replay_after_with_ids_returns_when_index_malformed(self, monkeypatch: pytest.MonkeyPatch):
        """Lines 456-463: malformed index JSON is logged and yields nothing."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:ri-idx-bad")

        class DummyRedis:
            def __init__(self) -> None:
                # Non-JSON bytes triggers orjson.loads failure -> warning path
                self.get = AsyncMock(return_value=b"{not json")
                self.hget = AsyncMock(side_effect=AssertionError("must not read meta/messages"))
                self.zrangebyscore = AsyncMock(side_effect=AssertionError("must not enumerate"))

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        results = [item async for item in store.replay_after_with_ids("s", "evid")]
        assert results == []

    async def test_replay_after_with_ids_handles_bad_start_seq_and_edge_messages(self, monkeypatch: pytest.MonkeyPatch):
        """Lines 489-490 (start_seq parse error), 504 (hget None), 507-509 (malformed JSON)."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:ri-badstart")
        stream_id = "s"
        meta_key = store._get_stream_meta_key(stream_id)
        messages_key = store._get_stream_messages_key(stream_id)

        class DummyRedis:
            def __init__(self) -> None:
                self.get = AsyncMock(return_value=orjson.dumps({"stream_id": stream_id, "seq_num": 1}))
                self.zrangebyscore = AsyncMock(return_value=[b"gone", b"bad", b"ok"])
                self.hget = AsyncMock(side_effect=self._hget)

            async def _hget(self, key: str, field: str):
                if key == meta_key and field == "start_seq":
                    return b"not-an-int"  # 489-490: except TypeError/ValueError
                if key == messages_key and field == "gone":
                    return None  # 504 continue
                if key == messages_key and field == "bad":
                    return b"{"  # 507-509 warning path
                if key == messages_key and field == "ok":
                    return orjson.dumps({"jsonrpc": "2.0", "method": "notifications/ok"})
                raise AssertionError(f"Unexpected hget: {key=} {field=}")

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        results = [item async for item in store.replay_after_with_ids(stream_id, "ev-cursor")]
        assert len(results) == 1
        assert results[0][0] == "ok"

    # ----------------------------------------------------------------------
    # evict_event
    # ----------------------------------------------------------------------

    async def test_evict_event_raises_when_redis_client_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        """Line 538-540: missing Redis client raises RuntimeError so callers can log the orphan."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:evict-nored")
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=None),
        )
        with pytest.raises(RuntimeError, match="Redis client not available"):
            await store.evict_event("s", "evid")

    async def test_evict_event_returns_true_when_event_removed(self, monkeypatch: pytest.MonkeyPatch):
        """Line 544-553 happy path: EVAL returns 1 → True."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:evict-hit")

        class DummyRedis:
            def __init__(self) -> None:
                self.eval = AsyncMock(return_value=1)

        dummy = DummyRedis()
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=dummy),
        )

        stream_id = "s"
        event_id = "evid"
        result = await store.evict_event(stream_id, event_id)
        assert result is True

        dummy.eval.assert_awaited_once()
        call_args = dummy.eval.call_args
        # 3 keys + 2 argv
        assert call_args.args[1] == 3
        assert call_args.args[2] == store._get_stream_meta_key(stream_id)
        assert call_args.args[3] == store._get_stream_events_key(stream_id)
        assert call_args.args[4] == store._get_stream_messages_key(stream_id)
        assert call_args.args[5] == event_id
        assert call_args.args[6] == store._event_index_prefix()

    async def test_evict_event_returns_false_when_event_absent(self, monkeypatch: pytest.MonkeyPatch):
        """EVAL returns 0 → False (idempotent no-op)."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:evict-miss")

        class DummyRedis:
            def __init__(self) -> None:
                self.eval = AsyncMock(return_value=0)

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        assert await store.evict_event("s", "evid") is False

    # ----------------------------------------------------------------------
    # fetch_event
    # ----------------------------------------------------------------------

    async def test_fetch_event_returns_none_when_redis_client_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        """Line 568-570: redis=None returns None, no exception."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:fetch-nored")
        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=None),
        )
        assert await store.fetch_event("s", "evid") is None

    async def test_fetch_event_returns_none_when_hash_entry_missing(self, monkeypatch: pytest.MonkeyPatch):
        """Line 573-574: hget returns None → returns None."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:fetch-miss")

        class DummyRedis:
            def __init__(self) -> None:
                self.hget = AsyncMock(return_value=None)

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )
        assert await store.fetch_event("s", "evid") is None

    async def test_fetch_event_returns_none_when_payload_is_malformed(self, monkeypatch: pytest.MonkeyPatch):
        """Lines 575-579: orjson/model_validate failure returns None and logs a warning."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:fetch-bad")

        class DummyRedis:
            def __init__(self) -> None:
                self.hget = AsyncMock(return_value=b"{")  # invalid JSON

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )
        assert await store.fetch_event("s", "evid") is None

    async def test_fetch_event_returns_validated_message(self, monkeypatch: pytest.MonkeyPatch):
        """Happy path: valid JSON-RPC payload validates into a JSONRPCMessage."""
        store = RedisEventStore(max_events_per_stream=10, ttl=60, key_prefix="mcpgw:eventstore:test:fetch-ok")
        stream_id = "s"
        event_id = "evid"
        messages_key = store._get_stream_messages_key(stream_id)

        class DummyRedis:
            def __init__(self) -> None:
                self.hget = AsyncMock(side_effect=self._hget)

            async def _hget(self, key: str, field: str):
                assert key == messages_key
                assert field == event_id
                return orjson.dumps({"jsonrpc": "2.0", "method": "notifications/ok"})

        monkeypatch.setattr(
            "mcpgateway.transports.redis_event_store.get_redis_client",
            AsyncMock(return_value=DummyRedis()),
        )

        result = await store.fetch_event(stream_id, event_id)
        assert result is not None
        # JSONRPCMessage wraps the underlying model; confirm it round-trips.
        dumped = result.model_dump(by_alias=True, exclude_none=True)
        assert dumped["jsonrpc"] == "2.0"
        assert dumped["method"] == "notifications/ok"
