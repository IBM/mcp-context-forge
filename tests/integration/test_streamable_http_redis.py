# -*- coding: utf-8 -*-
"""
Integration tests for multi-worker Streamable HTTP with RedisEventStore.

Tests that stateful sessions work correctly across multiple gateway workers
using Redis as the shared event store backend.
"""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock

import pytest

from mcpgateway.transports.redis_event_store import RedisEventStore
from mcpgateway.utils.redis_client import get_redis_client


@pytest.fixture
async def redis_cleanup(monkeypatch):
    """Clean up Redis keys before and after tests."""
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

    redis = await get_redis_client()
    key_prefix = f"mcpgw:eventstore:itest:{uuid.uuid4().hex}"

    # Clean before
    if redis:
        keys = await redis.keys(f"{key_prefix}:*")
        if keys:
            await redis.delete(*keys)

    yield key_prefix

    # Clean after
    if redis:
        keys = await redis.keys(f"{key_prefix}:*")
        if keys:
            await redis.delete(*keys)

    # Reset client after test
    _reset_client()


class TestMultiWorkerStatefulSessions:
    """Test stateful sessions across multiple workers."""

    async def test_multi_worker_event_sharing(self, redis_cleanup):
        """
        Simulate multiple workers accessing the same stream.

        Worker 1 stores events, Worker 2 replays them.
        """
        # Create two event stores (simulating two workers)
        worker1_store = RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup)
        worker2_store = RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup)

        stream_id = "session-abc123"

        # Worker 1: Store initialize event
        init_msg = {"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}, "id": 1}
        event1 = await worker1_store.store_event(stream_id, init_msg)

        # Worker 1: Store tools/list request
        tools_req = {"jsonrpc": "2.0", "method": "tools/list", "id": 2}
        event2 = await worker1_store.store_event(stream_id, tools_req)

        # Worker 1: Store tools/list response
        tools_resp = {"jsonrpc": "2.0", "result": {"tools": [{"name": "test_tool", "description": "A test tool"}]}, "id": 2}
        event3 = await worker1_store.store_event(stream_id, tools_resp)

        # Worker 2: Replay from event1 (should see events 2 and 3)
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await worker2_store.replay_events_after(event1, callback)

        # Verify Worker 2 sees all events stored by Worker 1
        assert result == stream_id
        assert len(replayed) == 2
        assert replayed[0] == tools_req
        assert replayed[1] == tools_resp

    async def test_concurrent_worker_writes(self, redis_cleanup):
        """
        Multiple workers writing to different streams simultaneously.
        """
        num_workers = 5
        events_per_worker = 10

        async def worker_task(worker_id):
            """Simulate a worker storing events."""
            store = RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup)
            stream_id = f"worker-{worker_id}-stream"
            event_ids = []

            for i in range(events_per_worker):
                msg = {"jsonrpc": "2.0", "method": f"worker_{worker_id}_method_{i}", "id": i}
                event_id = await store.store_event(stream_id, msg)
                event_ids.append(event_id)
                # Small delay to simulate real processing
                await asyncio.sleep(0.01)

            return stream_id, event_ids

        # Run all workers concurrently
        results = await asyncio.gather(*[worker_task(i) for i in range(num_workers)])

        # Verify each worker's stream
        for worker_id, (stream_id, event_ids) in enumerate(results):
            assert len(event_ids) == events_per_worker

            # Create new store to verify persistence
            verify_store = RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup)

            # Replay from first event
            replayed = []

            async def callback(msg):
                replayed.append(msg)

            result = await verify_store.replay_events_after(event_ids[0], callback)

            assert result == stream_id
            assert len(replayed) == events_per_worker - 1  # All except first

    async def test_worker_crash_recovery(self, redis_cleanup):
        """
        Worker 1 stores events, crashes, Worker 2 continues from same stream.
        """
        stream_id = "resilient-session"

        # Worker 1: Store some events
        worker1_store = RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup)
        msg1 = {"jsonrpc": "2.0", "method": "initialize", "id": 1}
        event1 = await worker1_store.store_event(stream_id, msg1)

        msg2 = {"jsonrpc": "2.0", "method": "tools/list", "id": 2}
        event2 = await worker1_store.store_event(stream_id, msg2)

        # Simulate Worker 1 crash (delete the object)
        del worker1_store

        # Worker 2: Takes over the stream
        worker2_store = RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup)

        # Worker 2 can replay existing events
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await worker2_store.replay_events_after(event1, callback)

        assert result == stream_id
        assert len(replayed) == 1
        assert replayed[0] == msg2

        # Worker 2 can continue adding events
        msg3 = {"jsonrpc": "2.0", "result": {"tools": []}, "id": 2}
        event3 = await worker2_store.store_event(stream_id, msg3)

        # Verify all events are there
        replayed.clear()
        result = await worker2_store.replay_events_after(event1, callback)

        assert len(replayed) == 2
        assert replayed[0] == msg2
        assert replayed[1] == msg3

    async def test_round_robin_load_balancing(self, redis_cleanup):
        """
        Simulate round-robin load balancing where requests alternate between workers.
        """
        stream_id = "load-balanced-session"

        # Create 3 workers
        workers = [RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup) for _ in range(3)]

        # Simulate 12 requests round-robin across workers
        event_ids = []
        messages = []

        for i in range(12):
            worker = workers[i % 3]  # Round-robin
            msg = {"jsonrpc": "2.0", "method": f"request_{i}", "id": i}
            messages.append(msg)
            event_id = await worker.store_event(stream_id, msg)
            event_ids.append(event_id)

        # Any worker can replay the full history
        for worker_idx, worker in enumerate(workers):
            replayed = []

            async def callback(msg):
                replayed.append(msg)

            result = await worker.replay_events_after(event_ids[0], callback)

            assert result == stream_id
            assert len(replayed) == 11  # All messages after first
            # Verify order is preserved
            for i, msg in enumerate(replayed):
                assert msg == messages[i + 1]

    async def test_eviction_across_workers(self, redis_cleanup):
        """
        Test that eviction works correctly when multiple workers write to same stream.
        """
        stream_id = "eviction-test-stream"
        max_events = 10

        # Create two workers
        worker1 = RedisEventStore(max_events_per_stream=max_events, ttl=300, key_prefix=redis_cleanup)
        worker2 = RedisEventStore(max_events_per_stream=max_events, ttl=300, key_prefix=redis_cleanup)

        # Worker 1 stores 5 events
        event_ids = []
        for i in range(5):
            msg = {"jsonrpc": "2.0", "method": f"worker1_msg_{i}", "id": i}
            event_id = await worker1.store_event(stream_id, msg)
            event_ids.append(event_id)

        # Worker 2 stores 10 more events (total 15, should evict first 5)
        for i in range(5, 15):
            msg = {"jsonrpc": "2.0", "method": f"worker2_msg_{i}", "id": i}
            event_id = await worker2.store_event(stream_id, msg)
            event_ids.append(event_id)

        # Try to replay from first event (should be evicted)
        replayed = []

        async def callback(msg):
            replayed.append(msg)

        result = await worker1.replay_events_after(event_ids[0], callback)
        assert result is None  # First event evicted

        # Replay from 6th event (should exist)
        replayed.clear()
        result = await worker2.replay_events_after(event_ids[5], callback)

        assert result == stream_id
        assert len(replayed) == 9  # Events 7-15

    async def test_session_isolation(self, redis_cleanup):
        """
        Ensure different sessions don't interfere with each other.
        """
        # Create multiple workers
        workers = [RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup) for _ in range(3)]

        # Create 3 different sessions
        sessions = ["session-alice", "session-bob", "session-charlie"]

        # Each worker manages one session
        session_events = {}
        for i, (worker, session_id) in enumerate(zip(workers, sessions)):
            events = []
            for j in range(5):
                msg = {"jsonrpc": "2.0", "method": f"session_{i}_msg_{j}", "id": j}
                event_id = await worker.store_event(session_id, msg)
                events.append(event_id)
            session_events[session_id] = events

        # Verify each session has only its own events
        for session_id, event_ids in session_events.items():
            store = RedisEventStore(max_events_per_stream=100, ttl=300, key_prefix=redis_cleanup)
            replayed = []

            async def callback(msg):
                replayed.append(msg)

            result = await store.replay_events_after(event_ids[0], callback)

            assert result == session_id
            assert len(replayed) == 4  # Events after first

            # Verify no cross-contamination
            for msg in replayed:
                # Extract session index from method name
                session_idx = int(msg["method"].split("_")[1])
                assert sessions[session_idx] == session_id

    async def test_high_throughput(self, redis_cleanup):
        """
        Test event store under high throughput scenario.
        """
        stream_id = "high-throughput-stream"
        num_workers = 10
        events_per_worker = 50

        async def worker_task(worker_id):
            """Worker that rapidly stores events."""
            store = RedisEventStore(max_events_per_stream=1000, ttl=300, key_prefix=redis_cleanup)
            for i in range(events_per_worker):
                msg = {"jsonrpc": "2.0", "method": f"w{worker_id}_msg{i}", "id": f"{worker_id}-{i}"}
                await store.store_event(stream_id, msg)

        # Start all workers simultaneously
        await asyncio.gather(*[worker_task(i) for i in range(num_workers)])

        # Verify total event count
        store = RedisEventStore(max_events_per_stream=1000, ttl=300, key_prefix=redis_cleanup)
        redis = await get_redis_client()

        # Get event count
        count = await redis.hget(store._get_stream_meta_key(stream_id), "count")
        assert count is not None
        total_events = int(count)

        # Should have all events (or max if eviction occurred)
        expected_total = num_workers * events_per_worker
        assert total_events == min(expected_total, 1000)
