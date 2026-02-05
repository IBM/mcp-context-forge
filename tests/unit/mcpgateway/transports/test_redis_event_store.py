# -*- coding: utf-8 -*-
"""
Unit tests for RedisEventStore.

Tests the Redis-backed event store implementation for multi-worker
stateful Streamable HTTP sessions.
"""

import asyncio
import os
import time

import pytest

from mcpgateway.transports.redis_event_store import RedisEventStore
from mcpgateway.utils.redis_client import get_redis_client


@pytest.fixture
async def redis_event_store(monkeypatch):
    """Create a RedisEventStore instance for testing."""
    # Enable Redis for this test
    monkeypatch.setenv("CACHE_TYPE", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    # Reset Redis client to pick up new settings
    from mcpgateway.utils.redis_client import _reset_client
    from mcpgateway.config import settings

    _reset_client()
    # Force settings reload by directly setting attributes
    settings.cache_type = "redis"
    settings.redis_url = "redis://localhost:6379"

    # Check if Redis is available
    redis = await get_redis_client()
    if redis is None:
        pytest.skip("Redis not available - skipping Redis event store tests")

    store = RedisEventStore(max_events_per_stream=10, ttl=60)
    yield store

    # Cleanup: delete all test keys
    redis = await get_redis_client()
    if redis:
        keys = await redis.keys("mcpgw:eventstore:*")
        if keys:
            await redis.delete(*keys)

    # Reset client after test
    _reset_client()


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

    async def test_ttl_expiration(self, redis_event_store):
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
        redis = await get_redis_client()
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
        large_store = RedisEventStore(max_events_per_stream=30, ttl=60)

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
