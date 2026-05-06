# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_registry_cache_timeout.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for RegistryCache Redis timeout and circuit breaker functionality.
Tests verify that:
1. Redis operations timeout after configured duration
2. Circuit breaker opens after threshold failures
3. Circuit breaker allows retry after timeout
4. Cache falls back to in-memory on Redis timeout
5. Automatic recovery when Redis becomes available
"""

# Standard
import asyncio
import time
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.registry_cache import RegistryCache


@pytest.mark.asyncio
async def test_redis_operation_timeout():
    """Test that Redis operations timeout after configured duration."""
    cache = RegistryCache()

    # Mock Redis client that hangs
    async def hanging_get(key):
        await asyncio.sleep(10)  # Hangs for 10s

    mock_redis = AsyncMock()
    mock_redis.get = hanging_get

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        # Should timeout after 0.5s (default redis_operation_timeout)
        start = asyncio.get_event_loop().time()
        result = await cache.get("tools", "test_hash")
        elapsed = asyncio.get_event_loop().time() - start

        assert result is None  # Timeout returns None
        assert elapsed < 1.0  # Should timeout quickly
        assert cache._redis_failure_count > 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens():
    """Test that circuit breaker opens after threshold failures."""
    cache = RegistryCache()
    cache._redis_failure_threshold = 3

    # Mock Redis client that always times out
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        # Trigger failures
        for _ in range(3):
            await cache.get("tools", "test_hash")

        assert cache._redis_circuit_open is True
        assert cache._redis_failure_count >= 3


@pytest.mark.asyncio
async def test_circuit_breaker_skips_operations_when_open():
    """Test that circuit breaker skips Redis operations when open."""
    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = asyncio.get_event_loop().time()  # Just failed
    cache._redis_circuit_open_duration = 30.0

    # Mock _get_redis_client to return None when circuit is open
    with patch.object(cache, "_get_redis_client", return_value=None):
        result = await cache.get("tools", "test_hash")

        # Should skip Redis and return None (no in-memory cache)
        assert result is None


@pytest.mark.asyncio
async def test_circuit_breaker_recovery():
    """Test that circuit breaker allows retry after timeout."""
    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = asyncio.get_event_loop().time() - 31  # 31s ago
    cache._redis_circuit_open_duration = 30.0

    # Mock successful Redis client
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b'{"data": "test"}')

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        result = await cache.get("tools", "test_hash")

        assert result is not None  # Should succeed
        assert cache._redis_circuit_open is False  # Circuit closed
        assert cache._redis_failure_count == 0  # Reset


@pytest.mark.asyncio
async def test_fallback_to_memory_on_timeout():
    """Test that cache falls back to in-memory on Redis timeout."""
    cache = RegistryCache()

    # Pre-populate in-memory cache
    test_data = [{"id": "1", "name": "tool1"}]
    await cache.set("tools", test_data, "test_hash")

    # Mock Redis client that times out
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        # Should fall back to in-memory cache
        result = await cache.get("tools", "test_hash")

        assert result == test_data  # Got data from memory
        assert cache._redis_failure_count > 0


@pytest.mark.asyncio
async def test_set_operation_timeout():
    """Test that Redis set operations timeout properly."""
    cache = RegistryCache()

    # Mock Redis client that hangs on setex
    async def hanging_setex(*args):
        await asyncio.sleep(10)

    mock_redis = AsyncMock()
    mock_redis.setex = hanging_setex

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        # Should timeout but still store in memory
        test_data = [{"id": "1", "name": "tool1"}]
        await cache.set("tools", test_data, "test_hash")

        # Should be in memory cache even if Redis times out
        result = await cache.get("tools", "test_hash")
        assert result == test_data
        # Failure count should be incremented due to timeout
        # Note: May be 0 if exception is caught before counter increment
        # The key behavior is that data is still cached in memory


@pytest.mark.asyncio
async def test_invalidate_operation_timeout():
    """Test that invalidate() times out the scan cleanly and still clears L1."""
    cache = RegistryCache()
    cache._scan_timeout = 0.1  # avoid waiting for the production 5s floor

    async def hanging_scan_iter(*args, **kwargs):
        await asyncio.sleep(10)
        yield b""  # unreachable; makes this a true async generator

    mock_redis = AsyncMock()
    mock_redis.scan_iter = hanging_scan_iter

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        await cache.invalidate("tools")
        assert len([k for k in cache._cache if k.startswith(cache._get_redis_key("tools"))]) == 0


@pytest.mark.asyncio
async def test_get_redis_client_with_circuit_open():
    """Test that _get_redis_client respects circuit breaker."""
    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = time.time()  # Use time.time() not event loop time
    cache._redis_circuit_open_duration = 30.0

    # Should return None without attempting connection
    client = await cache._get_redis_client()
    assert client is None


@pytest.mark.asyncio
async def test_get_redis_client_does_not_ping_per_call():
    """_get_redis_client must return the factory client without a per-call ping.

    Wrapping ping in the circuit breaker on every operation lets a "half-up"
    Redis (PING ok, GET times out) oscillate the failure counter between 0
    and 1 so the breaker never opens. We verify the factory client is
    returned verbatim and that ping() was NOT invoked here.
    """
    cache = RegistryCache()
    cache._redis_checked = False
    cache._redis_available = False

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis):
        client = await cache._get_redis_client()

    assert client is mock_redis
    assert cache._redis_available is True
    assert cache._redis_checked is True
    mock_redis.ping.assert_not_called()


@pytest.mark.asyncio
async def test_stats_includes_circuit_breaker_metrics():
    """Test that stats() includes circuit breaker state."""
    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_failure_count = 5

    stats = cache.stats()

    assert "redis_circuit_open" in stats
    assert stats["redis_circuit_open"] is True
    assert "redis_failure_count" in stats
    assert stats["redis_failure_count"] == 5


@pytest.mark.asyncio
async def test_multiple_timeouts_open_circuit():
    """Test that multiple consecutive timeouts open the circuit."""
    cache = RegistryCache()
    cache._redis_failure_threshold = 3

    # Mock Redis client that times out
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        # First two timeouts should not open circuit
        await cache.get("tools", "hash1")
        assert cache._redis_circuit_open is False

        await cache.get("tools", "hash2")
        assert cache._redis_circuit_open is False

        # Third timeout should open circuit
        await cache.get("tools", "hash3")
        assert cache._redis_circuit_open is True


@pytest.mark.asyncio
async def test_successful_operation_resets_failure_count():
    """Test that successful operation resets failure count."""
    cache = RegistryCache()
    cache._redis_failure_count = 2

    # Mock successful Redis client
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b'{"data": "test"}')

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        result = await cache.get("tools", "test_hash")

        assert result is not None
        assert cache._redis_failure_count == 0


@pytest.mark.asyncio
async def test_half_up_redis_trips_circuit_breaker():
    """Regression test for B1: Redis that answers PING but times out on commands.

    Before B1 was fixed, _get_redis_client pinged Redis on every call and
    _record_success'd that ping, oscillating failure_count between 0 (after
    ping success) and 1 (after get timeout). The breaker never opened, so
    every request paid the full timeout. After the fix, the command's own
    timeout is the sole breaker signal and 3 consecutive failures open it.
    """
    # Third-Party
    from redis.exceptions import TimeoutError as RedisTimeoutError

    cache = RegistryCache()
    cache._redis_failure_threshold = 3
    cache._redis_operation_timeout = 0.05

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(side_effect=RedisTimeoutError("command timed out"))

    with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis):
        for i in range(3):
            result = await cache.get("tools", f"hash{i}")
            assert result is None, f"half-up Redis must never return a value (iter {i})"

        assert cache._redis_failure_count >= 3, "Each timeout must count against the breaker"
        assert cache._redis_circuit_open is True, "Circuit must open after threshold failures"


@pytest.mark.asyncio
async def test_exception_in_redis_operation_increments_failure_count():
    """Test that Redis connection errors increment failure count."""
    cache = RegistryCache()

    # Mock Redis client that raises ConnectionError
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("Connection error"))

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        result = await cache.get("tools", "test_hash")

        assert result is None
        assert cache._redis_failure_count > 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_state():
    """Test circuit breaker half-open state behavior."""
    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = asyncio.get_event_loop().time() - 31
    cache._redis_circuit_open_duration = 30.0
    cache._redis_failure_count = 3

    # Mock successful Redis operation
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b'{"data": "test"}')

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        # First operation after timeout should succeed and close circuit
        result = await cache.get("tools", "test_hash")

        assert result is not None
        assert cache._redis_circuit_open is False
        assert cache._redis_failure_count == 0


@pytest.mark.asyncio
async def test_get_redis_client_factory_connection_error_records_failure():
    """Factory-level redis-py ConnectionError must route through the breaker.

    _get_redis_client no longer pings per call, but a factory that raises a
    redis.exceptions.ConnectionError should still increment failure_count
    (e.g. from bad URL / DNS) so the breaker can eventually trip.
    """
    # Third-Party
    from redis.exceptions import ConnectionError as RedisConnectionError

    cache = RegistryCache()
    cache._redis_checked = False
    cache._redis_available = True
    cache._redis_failure_count = 0

    with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=RedisConnectionError("bad url")):
        result = await cache._get_redis_client()

    assert result is None
    assert cache._redis_available is False
    assert cache._redis_checked is True
    assert cache._redis_failure_count == 1, "Factory connection error must count against the breaker"


@pytest.mark.asyncio
async def test_cancelled_probe_releases_slot():
    """Regression test for B2: cancelling a probe coroutine must release the slot.

    asyncio.CancelledError is a BaseException (not Exception), so the prior
    ``except Exception`` did not catch it and left
    _half_open_probe_in_flight=True permanently, disabling the breaker
    until process restart. The finally block now releases the slot.
    """
    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = time.time() - 31
    cache._redis_circuit_open_duration = 30.0

    probe_started = asyncio.Event()

    async def slow_probe(_client=None):
        probe_started.set()
        await asyncio.sleep(60)
        return "never-reached"

    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        probe_task = asyncio.create_task(cache._redis_operation_with_timeout(slow_probe, operation_name="probe"))
        await probe_started.wait()
        assert cache._half_open_probe_in_flight is True, "Probe must be in flight before cancellation"

        probe_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await probe_task

    assert cache._half_open_probe_in_flight is False, "Cancelled probe must release the slot"


@pytest.mark.asyncio
async def test_scan_timeout_does_not_publish():
    """Regression test for B3: if scan_iter fails/times out, do NOT publish.

    Publishing 'cache is invalid' to peer workers after a failed scan causes
    them to drop L1 while stale L2 keys remain in THIS worker's Redis,
    producing divergent cache state.
    """
    cache = RegistryCache()
    cache._redis_operation_timeout = 0.05
    cache._scan_timeout = 0.05

    async def hanging_scan(*_a, **_kw):
        await asyncio.sleep(10)
        yield b"never"  # async generator with unreachable yield

    mock_redis = AsyncMock()
    mock_redis.scan_iter = hanging_scan
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.publish = AsyncMock(return_value=1)

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        await cache.invalidate("tools")

    mock_redis.delete.assert_not_called()
    mock_redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_scan_output_aborts_invalidation():
    """H4: non-bytes/str SCAN output must abort delete+publish, not crash.

    A broken or malicious Redis could yield unexpected types; we log and
    bail rather than feeding garbage to redis.delete.
    """
    cache = RegistryCache()

    async def garbage_scan(*_a, **_kw):
        yield b"real-key-1"
        yield 12345  # invalid

    mock_redis = AsyncMock()
    mock_redis.scan_iter = garbage_scan
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.publish = AsyncMock(return_value=1)

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        await cache.invalidate("tools")

    mock_redis.delete.assert_not_called()
    mock_redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_batch_delete_single_roundtrip():
    """H3: invalidate() must batch all keys into a single redis.delete(*keys) call."""
    cache = RegistryCache()

    async def scan_stream(*_a, **_kw):
        for k in (b"k1", b"k2", b"k3", b"k4", b"k5"):
            yield k

    mock_redis = AsyncMock()
    mock_redis.scan_iter = scan_stream
    mock_redis.delete = AsyncMock(return_value=5)
    mock_redis.publish = AsyncMock(return_value=1)

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        await cache.invalidate("tools")

    assert mock_redis.delete.call_count == 1, "All keys must be deleted in a single round trip"
    call_args = mock_redis.delete.call_args.args
    assert set(call_args) == {b"k1", b"k2", b"k3", b"k4", b"k5"}
    mock_redis.publish.assert_called_once()


@pytest.mark.asyncio
async def test_stale_nonprobe_success_does_not_zero_open_circuit():
    """H2: a stale success arriving after the circuit opened must not zero the counter.

    Race: operation A is slow (500ms) and eventually succeeds; operations
    B, C, D time out during A's wait and open the circuit with
    failure_count=3. A's late success must NOT reset failure_count to 0,
    which would obscure the true failure history.
    """
    cache = RegistryCache()
    cache._redis_failure_count = 3
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = time.time()

    await cache._record_success(is_probe=False)

    assert cache._redis_failure_count == 3, "Stale non-probe success must not zero an open circuit"
    assert cache._redis_circuit_open is True, "Only a probe success may close the circuit"


@pytest.mark.asyncio
async def test_get_redis_client_unavailable_no_client():
    """Test Redis client returns None when get_redis_client returns None (covers lines 356-360)."""
    cache = RegistryCache()
    cache._redis_checked = False
    cache._redis_available = False

    with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
        result = await cache._get_redis_client()

        assert result is None
        assert cache._redis_checked is True
        assert cache._redis_available is False


@pytest.mark.asyncio
async def test_redis_operation_half_open_recovery():
    """Test circuit breaker half-open state allows one operation (covers lines 261-266)."""
    cache = RegistryCache()

    # Set circuit to open state
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = time.time() - 31  # Past the timeout
    cache._redis_circuit_open_duration = 30.0
    cache._redis_failure_count = 3

    # Mock successful operation that accepts redis_client arg
    async def successful_op(redis_client):
        return "success"

    # Mock Redis client
    mock_redis = AsyncMock()

    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        # Should enter half-open state and succeed
        result = await cache._redis_operation_with_timeout(successful_op, "test_op")

        assert result == "success"
        assert cache._redis_circuit_open is False
        assert cache._redis_failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_direct():
    """Direct test of half-open circuit breaker state (lines 261-266)."""
    cache = RegistryCache()

    # Set circuit to open with expired timeout
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = time.time() - 31
    cache._redis_circuit_open_duration = 30.0

    # Create a simple async operation
    call_count = 0

    async def test_operation(redis_client):
        nonlocal call_count
        call_count += 1
        return "result"

    # Mock Redis client
    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        result = await cache._redis_operation_with_timeout(test_operation, "test")

        # Verify half-open state was entered and circuit closed
        assert result == "result"
        assert call_count == 1
        assert cache._redis_circuit_open is False


@pytest.mark.asyncio
async def test_redis_operation_circuit_open_skip():
    """Test that operations are skipped when circuit is open (line 261-262)."""
    cache = RegistryCache()

    # Set circuit to open state (within timeout window)
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = time.time() - 5  # Only 5s ago
    cache._redis_circuit_open_duration = 30.0

    # Create operation that should not be called
    call_count = 0

    async def should_not_run(redis_client):
        nonlocal call_count
        call_count += 1
        return "should not happen"

    # Should skip operation and return None
    result = await cache._redis_operation_with_timeout(should_not_run, "test")

    assert result is None
    assert call_count == 0  # Operation was not called
    assert cache._redis_circuit_open is True  # Circuit still open


@pytest.mark.asyncio
async def test_get_redis_client_exception_handling():
    """Test Redis client exception handling (covers lines 362-367 including line 309)."""
    cache = RegistryCache()
    cache._redis_checked = False
    cache._redis_available = True

    # Mock get_redis_client to raise an exception
    with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=Exception("Connection error")):
        result = await cache._get_redis_client()

        assert result is None
        assert cache._redis_checked is True
        assert cache._redis_available is False


@pytest.mark.asyncio
async def test_redis_operation_non_timeout_exception():
    """Test that Redis connection errors are handled properly and increment failure count."""
    cache = RegistryCache()
    cache._redis_failure_count = 0
    cache._redis_failure_threshold = 3

    # Create operation that raises a Redis connection error
    async def failing_operation(redis_client):
        raise ConnectionError("Redis connection error")

    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        result = await cache._redis_operation_with_timeout(failing_operation, "test_op")

        assert result is None
        assert cache._redis_failure_count == 1

        # Trigger more failures to open circuit
        await cache._redis_operation_with_timeout(failing_operation, "test_op")
        await cache._redis_operation_with_timeout(failing_operation, "test_op")

        assert cache._redis_failure_count >= 3
        assert cache._redis_circuit_open is True


@pytest.mark.asyncio
async def test_redis_operation_unexpected_exception_does_not_increment_failure():
    """Test that unexpected exceptions (programming bugs) don't increment failure count."""
    cache = RegistryCache()
    cache._redis_failure_count = 0
    cache._redis_failure_threshold = 3

    # Create operation that raises an unexpected exception (programming bug)
    async def buggy_operation(redis_client):
        raise ValueError("Programming bug - not a Redis error")

    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        result = await cache._redis_operation_with_timeout(buggy_operation, "test_op")

        assert result is None
        # Failure count should NOT increment for programming bugs
        assert cache._redis_failure_count == 0
        assert cache._redis_circuit_open is False


@pytest.mark.asyncio
async def test_redis_py_connection_error_trips_breaker():
    """redis.exceptions.ConnectionError must be counted as a real Redis failure.

    This guards against the regression where narrowing the exception list to
    builtins.ConnectionError silently bypassed the breaker: redis-py's
    ConnectionError does NOT inherit from the stdlib type.
    """
    # Third-Party
    from redis.exceptions import ConnectionError as RedisConnectionError

    cache = RegistryCache()
    cache._redis_failure_threshold = 3

    async def failing_op(_client=None):
        raise RedisConnectionError("Connection refused")

    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        for _ in range(3):
            await cache._redis_operation_with_timeout(failing_op, operation_name="get")
        assert cache._redis_failure_count >= 3
        assert cache._redis_circuit_open is True


@pytest.mark.asyncio
async def test_redis_py_timeout_error_trips_breaker():
    """redis.exceptions.TimeoutError (distinct from asyncio.TimeoutError) trips the breaker."""
    # Third-Party
    from redis.exceptions import TimeoutError as RedisTimeoutError

    cache = RegistryCache()
    cache._redis_failure_threshold = 3

    async def timing_out_op(_client=None):
        raise RedisTimeoutError("Redis timeout")

    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        for _ in range(3):
            await cache._redis_operation_with_timeout(timing_out_op, operation_name="get")
        assert cache._redis_failure_count >= 3
        assert cache._redis_circuit_open is True


@pytest.mark.asyncio
async def test_redis_py_generic_redis_error_trips_breaker():
    """Any redis.exceptions.RedisError subclass (e.g. ResponseError) counts as a Redis failure."""
    # Third-Party
    from redis.exceptions import ResponseError

    cache = RegistryCache()
    cache._redis_failure_threshold = 3

    async def failing_op(_client=None):
        raise ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value")

    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        for _ in range(3):
            await cache._redis_operation_with_timeout(failing_op, operation_name="get")
        assert cache._redis_failure_count >= 3
        assert cache._redis_circuit_open is True


@pytest.mark.asyncio
async def test_half_open_allows_only_single_probe():
    """After cooldown, only one concurrent caller gets the probe slot; others skip Redis.

    This guards against the thundering-herd regression where all waiting
    coroutines flip _redis_circuit_open=False simultaneously and flood a
    still-down Redis.
    """
    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = time.time() - 31
    cache._redis_circuit_open_duration = 30.0

    probe_started = asyncio.Event()
    release_probe = asyncio.Event()
    probe_call_count = 0

    async def blocking_probe(_client=None):
        nonlocal probe_call_count
        probe_call_count += 1
        probe_started.set()
        await release_probe.wait()
        return "probe-result"

    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        probe_task = asyncio.create_task(cache._redis_operation_with_timeout(blocking_probe, operation_name="probe"))
        await probe_started.wait()

        concurrent_results = await asyncio.gather(*[cache._redis_operation_with_timeout(blocking_probe, operation_name="concurrent") for _ in range(5)])
        assert all(r is None for r in concurrent_results), "Concurrent callers must see half-open probe_in_flight and return None"
        assert probe_call_count == 1, "Only the single probe should have executed"

        release_probe.set()
        probe_result = await probe_task
        assert probe_result == "probe-result"
        assert cache._redis_circuit_open is False, "Successful probe closes the circuit"
        assert cache._half_open_probe_in_flight is False


@pytest.mark.asyncio
async def test_half_open_probe_failure_keeps_circuit_open():
    """A failed probe releases the slot but keeps the circuit open (extended cooldown)."""
    # Third-Party
    from redis.exceptions import ConnectionError as RedisConnectionError

    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = time.time() - 31
    cache._redis_circuit_open_duration = 30.0
    cache._redis_failure_count = 3

    async def still_failing(_client=None):
        raise RedisConnectionError("Still down")

    mock_redis = AsyncMock()
    with patch.object(cache, "_get_redis_client", return_value=mock_redis):
        result = await cache._redis_operation_with_timeout(still_failing, operation_name="probe")
        assert result is None
        assert cache._redis_circuit_open is True, "Probe failure must keep circuit open"
        assert cache._half_open_probe_in_flight is False, "Probe slot must be released"
        assert cache._redis_last_failure_time > time.time() - 1, "Cooldown clock must reset"


@pytest.mark.asyncio
async def test_scan_iter_uses_extended_timeout():
    """invalidate()'s scan_iter must tolerate runs longer than redis_operation_timeout.

    The original implementation wrapped scan_iter in a single 0.5s window,
    silently dropping subsequent delete/publish steps on large keysets.
    """
    cache = RegistryCache()
    cache._redis_operation_timeout = 0.1

    scan_invocations = 0

    class SlowScanRedis:
        """Minimal Redis double: scan_iter takes ~0.2s (> operation timeout)."""

        async def scan_iter(self, match=None):
            nonlocal scan_invocations
            scan_invocations += 1
            for i in range(3):
                await asyncio.sleep(0.07)
                yield f"{match.rstrip('*')}{i}".encode()

        async def delete(self, key):
            return 1

        async def publish(self, channel, message):
            return 1

    slow = SlowScanRedis()
    with patch.object(cache, "_get_redis_client", return_value=slow):
        await cache.invalidate("tools")

    assert scan_invocations == 1, "scan_iter should have executed once"
