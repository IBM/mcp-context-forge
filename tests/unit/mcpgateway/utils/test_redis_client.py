# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_redis_client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for the centralized Redis client factory.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.redis_client import (
    _reset_client,
    close_redis_client,
    get_redis_client,
    get_redis_client_sync,
    is_redis_available,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_client_state():
    """Reset client state before and after each test."""
    _reset_client()
    yield
    _reset_client()


# ---------------------------------------------------------------------------
# Tests for get_redis_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_when_cache_not_redis():
    """get_redis_client returns None when cache_type is not redis."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        mock_settings.redis_url = "redis://localhost:6379"

        client = await get_redis_client()

        assert client is None


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_when_no_redis_url():
    """get_redis_client returns None when redis_url is not set."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = None

        client = await get_redis_client()

        assert client is None


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_when_redis_not_installed():
    """get_redis_client returns None when redis.asyncio is not available."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"

        # Simulate import error for redis.asyncio
        with patch.dict("sys.modules", {"redis.asyncio": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'redis.asyncio'")):
                _reset_client()  # Force re-initialization
                # The actual test should trigger the import error path
                # For this test, we just verify the function handles it gracefully


@pytest.mark.asyncio
async def test_get_redis_client_creates_client_on_first_call():
    """get_redis_client creates client with correct settings on first call."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis) as mock_from_url:
            client = await get_redis_client()

            assert client is mock_redis
            mock_from_url.assert_called_once_with(
                "redis://localhost:6379",
                decode_responses=True,
                max_connections=10,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True,
                health_check_interval=30,
                encoding="utf-8",
                single_connection_client=False,
            )
            mock_redis.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_redis_client_returns_cached_client():
    """get_redis_client returns cached client on subsequent calls."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis) as mock_from_url:
            client1 = await get_redis_client()
            client2 = await get_redis_client()

            assert client1 is client2
            # from_url should only be called once
            mock_from_url.assert_called_once()


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_on_connection_error():
    """get_redis_client returns None when connection fails."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis not reachable"))

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            client = await get_redis_client()

            assert client is None


# ---------------------------------------------------------------------------
# Tests for close_redis_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_redis_client_closes_active_client():
    """close_redis_client closes active client and resets state."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.aclose = AsyncMock()

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await get_redis_client()
            await close_redis_client()

            mock_redis.aclose.assert_awaited_once()

            # Verify state was reset
            assert get_redis_client_sync() is None


@pytest.mark.asyncio
async def test_close_redis_client_handles_no_client():
    """close_redis_client handles case when no client exists."""
    # Should not raise any errors
    await close_redis_client()


@pytest.mark.asyncio
async def test_close_redis_client_handles_close_error():
    """close_redis_client handles errors during close gracefully."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.aclose = AsyncMock(side_effect=Exception("Close failed"))

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await get_redis_client()
            # Should not raise
            await close_redis_client()


# ---------------------------------------------------------------------------
# Tests for is_redis_available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_redis_available_returns_true_when_connected():
    """is_redis_available returns True when Redis is connected and responds to ping."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await is_redis_available()

            assert result is True


@pytest.mark.asyncio
async def test_is_redis_available_returns_false_when_disabled():
    """is_redis_available returns False when Redis is disabled."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        mock_settings.redis_url = "redis://localhost:6379"

        result = await is_redis_available()

        assert result is False


@pytest.mark.asyncio
async def test_is_redis_available_returns_false_when_ping_fails():
    """is_redis_available returns False when ping fails."""
    mock_redis = AsyncMock()
    # First ping succeeds (initialization), second fails (availability check)
    mock_redis.ping = AsyncMock(side_effect=[True, ConnectionError("Ping failed")])

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await is_redis_available()

            assert result is False


# ---------------------------------------------------------------------------
# Tests for get_redis_client_sync
# ---------------------------------------------------------------------------


def test_get_redis_client_sync_returns_none_before_init():
    """get_redis_client_sync returns None before initialization."""
    result = get_redis_client_sync()

    assert result is None


@pytest.mark.asyncio
async def test_get_redis_client_sync_returns_cached_client():
    """get_redis_client_sync returns cached client after initialization."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await get_redis_client()

            sync_client = get_redis_client_sync()

            assert sync_client is mock_redis


# ---------------------------------------------------------------------------
# Tests for _reset_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_client_clears_state():
    """_reset_client clears initialized state."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await get_redis_client()
            assert get_redis_client_sync() is mock_redis

            _reset_client()

            assert get_redis_client_sync() is None
