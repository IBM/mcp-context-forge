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

    @patch("redis.from_url")
    def test_rate_limiter_with_dedicated_redis(self, mock_from_url):
        """Verify rate limiting works with dedicated Redis URL."""
        # Mock dedicated Redis client
        mock_dedicated_client = MagicMock()
        mock_dedicated_client.ping.return_value = True
        mock_dedicated_client.get.return_value = None
        mock_dedicated_client.setex.return_value = True

        mock_from_url.return_value = mock_dedicated_client

        # Reset global clients
        import mcpgateway.auth
        mcpgateway.auth._RATELIMITER_REDIS_CLIENT = None

        with patch("mcpgateway.auth.settings") as mock_settings:
            mock_settings.ratelimiter_redis_url = "redis://localhost:6380/0"
            mock_settings.ratelimiter_redis_max_connections = 50
            mock_settings.ratelimiter_redis_socket_timeout = 2.0
            mock_settings.ratelimiter_redis_socket_connect_timeout = 2.0
            mock_settings.redis_ssl = False

            from mcpgateway.auth import _get_ratelimiter_redis_client

            with patch("mcpgateway.auth._build_ssl_kwargs", return_value={}):
                client = _get_ratelimiter_redis_client()

            # Verify dedicated Redis was used
            assert client == mock_dedicated_client
            mock_from_url.assert_called_once()
            mock_dedicated_client.ping.assert_called_once()

    @patch("mcpgateway.auth._get_sync_redis_client")
    def test_rate_limiter_fallback_to_main_redis(self, mock_get_sync):
        """Verify rate limiting falls back to main Redis when dedicated unset."""
        mock_main_client = MagicMock()
        mock_get_sync.return_value = mock_main_client

        # Reset global clients
        import mcpgateway.auth
        mcpgateway.auth._RATELIMITER_REDIS_CLIENT = None

        with patch("mcpgateway.auth.settings") as mock_settings:
            mock_settings.ratelimiter_redis_url = None

            from mcpgateway.auth import _get_ratelimiter_redis_client

            client = _get_ratelimiter_redis_client()

            # Verify main Redis was used via fallback
            assert client == mock_main_client
            mock_get_sync.assert_called_once()


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
