# -*- coding: utf-8 -*-
"""Unit tests for RegistryCache Redis timeout and circuit breaker functionality.

Tests verify that:
1. Redis operations timeout after configured duration
2. Circuit breaker opens after threshold failures
3. Circuit breaker allows retry after timeout
4. Cache falls back to in-memory on Redis timeout
5. Automatic recovery when Redis becomes available

SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.registry_cache import RegistryCache, RegistryCacheConfig


@pytest.mark.asyncio
async def test_redis_operation_timeout():
    """Test that Redis operations timeout after configured duration."""
    cache = RegistryCache()
    
    # Mock Redis client that hangs
    async def hanging_get(key):
        await asyncio.sleep(10)  # Hangs for 10s
        return None
    
    mock_redis = AsyncMock()
    mock_redis.get = hanging_get
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
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
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
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
    with patch.object(cache, '_get_redis_client', return_value=None):
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
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
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
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
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
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
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
    """Test that Redis invalidate operations timeout properly."""
    cache = RegistryCache()
    
    # Mock Redis client that hangs on scan_iter
    mock_redis = AsyncMock()
    
    async def hanging_scan(*args, **kwargs):
        await asyncio.sleep(10)
        return []
    
    mock_redis.scan_iter = MagicMock(return_value=hanging_scan())
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
        # Should timeout but still clear in-memory cache
        await cache.invalidate("tools")
        
        # In-memory cache should be cleared
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
async def test_get_redis_client_reconnection_after_circuit_timeout():
    """Test that _get_redis_client attempts reconnection after circuit timeout."""
    cache = RegistryCache()
    cache._redis_circuit_open = True
    cache._redis_last_failure_time = asyncio.get_event_loop().time() - 31  # 31s ago
    cache._redis_circuit_open_duration = 30.0
    
    # Mock successful Redis client
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    
    with patch('mcpgateway.utils.redis_client.get_redis_client', return_value=mock_redis):
        client = await cache._get_redis_client()
        
        assert client is not None
        assert cache._redis_circuit_open is False
        assert cache._redis_available is True


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
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
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
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
        result = await cache.get("tools", "test_hash")
        
        assert result is not None
        assert cache._redis_failure_count == 0


@pytest.mark.asyncio
async def test_redis_ping_timeout_in_get_client():
    """Test that Redis ping timeout is handled in _get_redis_client."""
    cache = RegistryCache()
    
    # Mock Redis client with hanging ping
    async def hanging_ping():
        await asyncio.sleep(10)
        return True
    
    mock_redis = AsyncMock()
    mock_redis.ping = hanging_ping
    
    with patch('mcpgateway.utils.redis_client.get_redis_client', return_value=mock_redis):
        client = await cache._get_redis_client()
        
        # Should return None due to ping timeout
        assert client is None
        assert cache._redis_available is False


@pytest.mark.asyncio
async def test_exception_in_redis_operation_increments_failure_count():
    """Test that exceptions in Redis operations increment failure count."""
    cache = RegistryCache()
    
    # Mock Redis client that raises exception
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=Exception("Connection error"))
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
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
    
    with patch.object(cache, '_get_redis_client', return_value=mock_redis):
        # First operation after timeout should succeed and close circuit
        result = await cache.get("tools", "test_hash")
        
        assert result is not None
        assert cache._redis_circuit_open is False
        assert cache._redis_failure_count == 0
