"""Unit tests for rate limiter Redis client initialization in auth.py."""

import time
from unittest.mock import MagicMock, patch

import pytest
import redis

from mcpgateway.auth import _get_ratelimiter_redis_client


@pytest.fixture(autouse=True)
def reset_redis_globals():
    """Reset global Redis client state before each test."""
    import mcpgateway.auth as auth_module

    auth_module._RATELIMITER_REDIS_CLIENT = None
    auth_module._RATELIMITER_REDIS_FAILURE_TIME = None
    yield
    auth_module._RATELIMITER_REDIS_CLIENT = None
    auth_module._RATELIMITER_REDIS_FAILURE_TIME = None


def test_get_ratelimiter_redis_fallback_to_main():
    """Test fallback to main Redis when no dedicated URL configured."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = None

        with patch("mcpgateway.auth._get_sync_redis_client") as mock_main:
            mock_main.return_value = MagicMock()
            result = _get_ratelimiter_redis_client()
            assert result == mock_main.return_value
            mock_main.assert_called_once()


def test_get_ratelimiter_redis_returns_cached_client():
    """Test returns cached client on subsequent calls."""
    import mcpgateway.auth as auth_module

    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://localhost:6380/1"

        mock_client = MagicMock()
        auth_module._RATELIMITER_REDIS_CLIENT = mock_client

        result = _get_ratelimiter_redis_client()
        assert result is mock_client


def test_get_ratelimiter_redis_backoff_after_failure():
    """Test backoff prevents reconnection attempts after recent failure."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://localhost:6380/1"

        with patch("mcpgateway.auth._RATELIMITER_REDIS_FAILURE_TIME", time.time()):
            result = _get_ratelimiter_redis_client()
            assert result is None


def test_get_ratelimiter_redis_rediss_warning(caplog):
    """Test warning when rediss:// used but SSL disabled."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "rediss://localhost:6380/1"
        mock_settings.redis_ssl = False
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        with patch("redis.from_url", return_value=mock_client), patch("mcpgateway.auth._build_ssl_kwargs", return_value={}):
            _get_ratelimiter_redis_client()
            assert "rediss:// but REDIS_SSL=false" in caplog.text


def test_get_ratelimiter_redis_ssl_kwargs_applied():
    """Test that build_reatelimiter_ssl_kwargs result is spread into redis.from_url call."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "rediss://localhost:6380/1"
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5
        mock_settings.ratelimiter_redis_ssl = False

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        with patch("redis.from_url", return_value=mock_client) as mock_from_url:
            result = _get_ratelimiter_redis_client()
            assert result is mock_client
            mock_from_url.assert_called_once()
            # Verify base parameters are passed correctly
            call_kwargs = mock_from_url.call_args[1]
            assert call_kwargs["decode_responses"] is True
            assert call_kwargs["max_connections"] == 10
            assert call_kwargs["socket_timeout"] == 5
            assert call_kwargs["socket_connect_timeout"] == 5


def test_get_ratelimiter_redis_connection_test():
    """Test connection is tested with ping()."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://localhost:6380/1"
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5
        mock_settings.ratelimiter_redis_ssl = False

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        with patch("redis.from_url", return_value=mock_client), patch("mcpgateway.utils.redis_client.build_reatelimiter_ssl_kwargs", return_value={}):
            result = _get_ratelimiter_redis_client()
            assert result is mock_client
            mock_client.ping.assert_called_once()


def test_get_ratelimiter_redis_url_sanitization(caplog):
    """Test credentials are stripped from logged URL."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://user:password@localhost:6380/1"
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5
        mock_settings.ratelimiter_redis_ssl = False

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        with patch("redis.from_url", return_value=mock_client), patch("mcpgateway.utils.redis_client.build_reatelimiter_ssl_kwargs", return_value={}):
            _get_ratelimiter_redis_client()
            assert "***@localhost:6380" in caplog.text
            assert "password" not in caplog.text


def test_get_ratelimiter_redis_ssl_misconfiguration_error(caplog):
    """Test ValueError from SSL config is caught and logged."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://localhost:6380/1"
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5

        with patch("mcpgateway.auth._build_ssl_kwargs", side_effect=ValueError("SSL error")):
            result = _get_ratelimiter_redis_client()
            assert result is None
            assert "SSL misconfiguration" in caplog.text


def test_get_ratelimiter_redis_connection_failure(caplog):
    """Test connection failure sets failure time and returns None."""
    import logging

    with caplog.at_level(logging.WARNING):
        with patch("mcpgateway.auth.settings") as mock_settings:
            mock_settings.ratelimiter_redis_url = "redis://localhost:6380/1"
            mock_settings.ratelimiter_redis_max_connections = 10
            mock_settings.ratelimiter_redis_socket_timeout = 5
            mock_settings.ratelimiter_redis_socket_connect_timeout = 5
            mock_settings.ratelimiter_redis_ssl = False

            with patch("redis.from_url", side_effect=redis.ConnectionError("Connection failed")), patch(
                "mcpgateway.utils.redis_client.build_reatelimiter_ssl_kwargs", return_value={}
            ):
                result = _get_ratelimiter_redis_client()
                assert result is None
                assert "unavailable" in caplog.text

            # Verify failure time was set
            import mcpgateway.auth as auth_module

            assert auth_module._RATELIMITER_REDIS_FAILURE_TIME is not None


def test_get_ratelimiter_redis_double_check_lock():
    """Test double-check locking pattern prevents race conditions."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://localhost:6380/1"
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5
        mock_settings.ratelimiter_redis_ssl = False

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        call_count = 0

        def from_url_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_client

        with patch("redis.from_url", side_effect=from_url_side_effect), patch("mcpgateway.utils.redis_client.build_reatelimiter_ssl_kwargs", return_value={}):
            # First call initializes
            result1 = _get_ratelimiter_redis_client()
            assert result1 is mock_client
            assert call_count == 1

            # Second call uses cached client
            result2 = _get_ratelimiter_redis_client()
            assert result2 is mock_client
            assert call_count == 1  # No additional call


def test_get_ratelimiter_redis_ssl_valueerror_no_backoff():
    """Test SSL misconfiguration doesn't set backoff timer."""
    import mcpgateway.auth as auth_module

    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://localhost:6380/1"
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5

        with patch("mcpgateway.auth._build_ssl_kwargs", side_effect=ValueError("SSL error")):
            result = _get_ratelimiter_redis_client()
            assert result is None

            # Verify backoff timer NOT set
            assert auth_module._RATELIMITER_REDIS_FAILURE_TIME is None


def test_get_ratelimiter_redis_success_log_sanitization(caplog):
    """Test credentials sanitized in success log message."""
    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://user:password@localhost:6380/1"
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5
        mock_settings.ratelimiter_redis_ssl = False

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        with patch("redis.from_url", return_value=mock_client), patch("mcpgateway.utils.redis_client.build_reatelimiter_ssl_kwargs", return_value={}):
            _get_ratelimiter_redis_client()

            # Verify success log contains sanitized URL
            assert "Rate limiter using dedicated Redis" in caplog.text
            assert "***@localhost:6380" in caplog.text
            assert "password" not in caplog.text


def test_get_ratelimiter_redis_backoff_expiry_retry():
    """Test reconnection attempt after backoff expires."""
    import mcpgateway.auth as auth_module

    with patch("mcpgateway.auth.settings") as mock_settings:
        mock_settings.ratelimiter_redis_url = "redis://localhost:6380/1"
        mock_settings.ratelimiter_redis_max_connections = 10
        mock_settings.ratelimiter_redis_socket_timeout = 5
        mock_settings.ratelimiter_redis_socket_connect_timeout = 5
        mock_settings.ratelimiter_redis_ssl = False

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        # Set failure time to 31 seconds ago (past backoff window)
        with patch("time.time", return_value=1000.0):
            auth_module._RATELIMITER_REDIS_FAILURE_TIME = 969.0  # 31 seconds ago

            with patch("redis.from_url", return_value=mock_client), patch("mcpgateway.utils.redis_client.build_reatelimiter_ssl_kwargs", return_value={}):
                result = _get_ratelimiter_redis_client()

                # Should retry and succeed
                assert result is mock_client
                assert auth_module._RATELIMITER_REDIS_FAILURE_TIME is None
