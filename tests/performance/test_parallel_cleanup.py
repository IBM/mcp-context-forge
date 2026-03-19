#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify parallel session cleanup performance improvement.
"""

import asyncio
import time
import os
import sys

# Add repo root to PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

from mcpgateway.cache.session_registry import SessionRegistry


class MockTransport:
    """Mock transport to simulate session connectivity and delay."""

    def __init__(self, connected=True, delay=0.05):
        self.connected = connected
        self.delay = delay

    async def is_connected(self):
        """Simulate connection check with delay."""
        await asyncio.sleep(0.001)  # small async delay
        return self.connected

    async def disconnect(self):
        pass


async def test_parallel_cleanup_performance():
    print("Testing parallel session cleanup performance...")

    # Create registry (memory backend for testing)
    registry = SessionRegistry(backend="memory")

    num_sessions = 100
    db_delay = 0.05  # Simulated DB latency per session (seconds)
    sessions = {}

    # Create mock sessions
    for i in range(num_sessions):
        session_id = f"session_{i:03d}"
        transport = MockTransport(connected=True, delay=db_delay)
        sessions[session_id] = transport

    registry._sessions = sessions.copy()
    print(f"Created {num_sessions} mock sessions")

    # Patch _refresh_session_db to simulate blocking DB operation
    def slow_refresh_session_db(self, session_id: str) -> bool:
        import time
        time.sleep(self._sessions[session_id].delay)  # simulate DB latency
        return True

    registry._refresh_session_db = slow_refresh_session_db.__get__(registry)

    # Theoretical sequential time
    sequential_time = num_sessions * db_delay
    max_concurrent = 20  # Default semaphore limit in _cleanup_database_sessions
    expected_parallel = (num_sessions / max_concurrent) * db_delay
    print(f"\nExpected sequential time: {sequential_time:.2f} seconds")
    print(f"Expected parallel time: ~{expected_parallel:.2f} seconds ({max_concurrent} concurrent)")

    # Run parallel cleanup
    start_time = time.time()
    await registry._cleanup_database_sessions()
    actual_parallel_time = time.time() - start_time

    speedup = sequential_time / actual_parallel_time if actual_parallel_time > 0 else float("inf")

    print(f"\nActual parallel cleanup time: {actual_parallel_time:.3f} seconds")
    print(f"Speedup: {speedup:.1f}x faster than sequential")

    # Pass/fail criteria
    if speedup > 10:
        print("✅ PASS: Parallel cleanup is significantly faster")
    else:
        print("❌ FAIL: Parallel cleanup not fast enough")

    # Verify sessions still exist (they are all connected)
    remaining_sessions = len(registry._sessions)
    print(f"Sessions remaining after cleanup: {remaining_sessions}")


if __name__ == "__main__":
    asyncio.run(test_parallel_cleanup_performance())
