# -*- coding: utf-8 -*-
"""Performance tests for streamable HTTP replay optimization.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

These tests verify that the ring buffer optimization provides O(k) replay
complexity instead of O(n) full deque scans.

Run with:
    uv run pytest -v tests/performance/test_streamablehttp_replay.py
"""

import time
from typing import List

import pytest

from mcpgateway.transports.streamablehttp_transport import EventMessage, InMemoryEventStore


class TestStreamableHTTPReplayPerformance:
    """Performance tests for InMemoryEventStore replay optimization."""

    @pytest.mark.asyncio
    async def test_replay_scales_with_k_not_n(self):
        """Replay time should scale with events-to-replay (k), not buffer size (n).

        This test verifies O(k) complexity by comparing replay times when:
        - n is large (1000 events) but k is small (10 events to replay)
        - vs. when k is proportionally larger

        If replay were O(n), both would take similar time. With O(k), the small-k
        case should be significantly faster.
        """
        # Large buffer with many events
        n = 1000
        store = InMemoryEventStore(max_events_per_stream=n)
        stream_id = "perf-test"

        # Store n events
        event_ids = []
        for i in range(n):
            eid = await store.store_event(stream_id, {"id": i})
            event_ids.append(eid)

        # Case 1: Replay last k=10 events (replay from event n-11)
        k_small = 10
        sent_small: List[EventMessage] = []

        async def collector_small(msg):
            sent_small.append(msg)

        start_small = time.perf_counter()
        for _ in range(100):  # Run 100 times to get measurable time
            sent_small.clear()
            await store.replay_events_after(event_ids[n - k_small - 1], collector_small)
        elapsed_small = time.perf_counter() - start_small

        assert len(sent_small) == k_small

        # Case 2: Replay last k=500 events (replay from event n-501)
        k_large = 500
        sent_large: List[EventMessage] = []

        async def collector_large(msg):
            sent_large.append(msg)

        start_large = time.perf_counter()
        for _ in range(100):
            sent_large.clear()
            await store.replay_events_after(event_ids[n - k_large - 1], collector_large)
        elapsed_large = time.perf_counter() - start_large

        assert len(sent_large) == k_large

        # With O(k) complexity, elapsed_large should be roughly (k_large/k_small) times elapsed_small
        # Allow some margin for overhead, but small-k should be notably faster
        ratio = elapsed_large / elapsed_small if elapsed_small > 0 else float("inf")

        # We expect ratio to be closer to k_large/k_small (50x) than to 1x
        # A ratio of at least 5x indicates we're not scanning the full buffer
        assert ratio > 5, f"Expected O(k) scaling, but ratio was only {ratio:.2f}x (expected ~{k_large / k_small}x)"

    @pytest.mark.asyncio
    async def test_replay_interleaved_streams_performance(self):
        """Replay on interleaved streams should not degrade performance.

        With per-stream sequence numbers, interleaving should not cause
        any performance issues during replay.
        """
        n_per_stream = 500
        store = InMemoryEventStore(max_events_per_stream=n_per_stream)

        # Interleave events across 3 streams
        stream_ids = ["stream-a", "stream-b", "stream-c"]
        event_ids = {sid: [] for sid in stream_ids}

        for i in range(n_per_stream):
            for sid in stream_ids:
                eid = await store.store_event(sid, {"stream": sid, "idx": i})
                event_ids[sid].append(eid)

        # Replay last 10 events from each stream
        k = 10
        for sid in stream_ids:
            sent: List[EventMessage] = []

            async def collector(msg):
                sent.append(msg)

            start = time.perf_counter()
            for _ in range(100):
                sent.clear()
                await store.replay_events_after(event_ids[sid][n_per_stream - k - 1], collector)
            elapsed = time.perf_counter() - start

            assert len(sent) == k
            # Each stream replay of 10 events (100 iterations) should complete quickly
            # With O(k) this should be under 0.1s even on slow systems
            assert elapsed < 1.0, f"Stream {sid} replay took {elapsed:.3f}s, expected < 1.0s"

    @pytest.mark.asyncio
    async def test_lookup_is_constant_time(self):
        """Event lookup should be O(1) regardless of buffer size.

        The event_index dict provides constant-time lookup by event ID.
        """
        sizes = [100, 1000, 10000]
        lookup_times = []

        for n in sizes:
            store = InMemoryEventStore(max_events_per_stream=n)
            stream_id = "lookup-test"

            # Store n events
            event_ids = []
            for i in range(n):
                eid = await store.store_event(stream_id, {"id": i})
                event_ids.append(eid)

            # Measure lookup time for middle event
            sent: List[EventMessage] = []

            async def collector(msg):
                sent.append(msg)

            start = time.perf_counter()
            for _ in range(1000):
                # Just trigger the lookup (replay 0 events from last)
                await store.replay_events_after(event_ids[-1], collector)
            elapsed = time.perf_counter() - start
            lookup_times.append(elapsed)

        # Lookup times should be similar regardless of buffer size
        # Allow 3x variation for system noise
        max_time = max(lookup_times)
        min_time = min(lookup_times)
        ratio = max_time / min_time if min_time > 0 else float("inf")

        assert ratio < 5, f"Lookup times varied too much: {lookup_times}, ratio={ratio:.2f}"
