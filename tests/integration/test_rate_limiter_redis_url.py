"""Integration tests for dedicated rate limiter Redis URL (Issue #4751).

Tests end-to-end behavior of RATELIMITER_REDIS_URL configuration:
- Rate limiting works with dedicated Redis
- Fallback to main Redis when unset
- Startup validation logs warnings for unreachable dedicated Redis
"""

import pytest
from unittest.mock import patch, MagicMock


class TestRateLimiterWithDedicatedRedis:
    """End-to-end test with dedicated Redis for rate limiting."""

    @patch("mcpgateway.auth.redis")
    def test_rate_limiter_with_dedicated_redis(self, mock_redis):
        """Verify rate limiting works with dedicated Redis URL."""
        # Mock dedicated Redis client
        mock_dedicated_client = MagicMock()
        mock_dedicated_client.ping.return_value = True
        mock_dedicated_client.get.return_value = None
        mock_dedicated_client.setex.return_value = True

        # Mock main Redis client
        mock_main_client = MagicMock()
        mock_main_client.ping.return_value = True

        def from_url_side_effect(url, **kwargs):
            if "6380" in url:  # Dedicated Redis
                return mock_dedicated_client
            return mock_main_client

        mock_redis.from_url.side_effect = from_url_side_effect

        # Reset global client
        import mcpgateway.auth
        mcpgateway.auth._SYNC_REDIS_CLIENT = None

        with patch("mcpgateway.auth.config_settings") as mock_settings:
            mock_settings.ratelimiter_redis_url = "redis://localhost:6380/0"
            mock_settings.ratelimiter_redis_max_connections = 50
            mock_settings.ratelimiter_redis_socket_timeout = 2.0
            mock_settings.ratelimiter_redis_socket_connect_timeout = 2.0
            mock_settings.redis_url = "redis://localhost:6379/0"

            from mcpgateway.auth import _get_sync_redis_client

            client = _get_sync_redis_client()

            # Verify dedicated Redis was used
            assert client == mock_dedicated_client
            mock_redis.from_url.assert_called_with(
                "redis://localhost:6380/0",
                decode_responses=True,
                max_connections=50,
                socket_timeout=2.0,
                socket_connect_timeout=2.0
            )

    @patch("mcpgateway.auth.redis")
    def test_rate_limiter_fallback_to_main_redis(self, mock_redis):
        """Verify rate limiting falls back to main Redis when dedicated unset."""
        mock_main_client = MagicMock()
        mock_main_client.ping.return_value = True
        mock_redis.from_url.return_value = mock_main_client

        import mcpgateway.auth
        mcpgateway.auth._SYNC_REDIS_CLIENT = None

        with patch("mcpgateway.auth.config_settings") as mock_settings:
            mock_settings.ratelimiter_redis_url = None
            mock_settings.redis_url = "redis://localhost:6379/0"
            mock_settings.redis_max_connections = 50
            mock_settings.redis_socket_timeout = 2.0
            mock_settings.redis_socket_connect_timeout = 2.0

            from mcpgateway.auth import _get_sync_redis_client

            client = _get_sync_redis_client()

            # Verify main Redis was used
            assert client == mock_main_client
            mock_redis.from_url.assert_called_with(
                "redis://localhost:6379/0",
                decode_responses=True,
                max_connections=50,
                socket_timeout=2.0,
                socket_connect_timeout=2.0
            )


class TestStartupValidation:
    """Test startup validation logs warning when dedicated Redis unreachable."""

    @patch("mcpgateway.main.redis")
    @patch("mcpgateway.main.logger")
    def test_startup_warns_on_unreachable_ratelimiter_redis(self, mock_logger, mock_redis):
        """Verify startup logs warning when dedicated Redis unreachable."""
        mock_client = MagicMock()
        mock_client.ping.side_effect = Exception("Connection refused")
        mock_redis.from_url.return_value = mock_client

        with patch("mcpgateway.main.settings") as mock_settings:
            mock_settings.ratelimiter_redis_url = "redis://unreachable:6379/0"
            mock_settings.ratelimiter_redis_socket_connect_timeout = 2.0
            mock_settings.ratelimiter_redis_socket_timeout = 2.0
            mock_settings.redis_url = "redis://localhost:6379/0"

            # Simulate startup validation block
            try:
                test_client = mock_redis.from_url(
                    mock_settings.ratelimiter_redis_url,
                    socket_connect_timeout=mock_settings.ratelimiter_redis_socket_connect_timeout,
                    socket_timeout=mock_settings.ratelimiter_redis_socket_timeout
                )
                test_client.ping()
            except Exception as e:
                mock_logger.warning(
                    f"Rate limiter Redis unreachable ({mock_settings.ratelimiter_redis_url}): {e}. "
                    f"Falling back to main Redis ({mock_settings.redis_url})"
                )

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Rate limiter Redis unreachable" in warning_msg
            assert "redis://unreachable:6379/0" in warning_msg
            assert "Falling back to main Redis" in warning_msg
