"""Unit tests for dedicated rate limiter Redis URL.

Tests RATELIMITER_REDIS_URL configuration behavior:
- Rate limiting works with dedicated Redis
- Fallback to main Redis when unset
"""

from unittest.mock import patch, MagicMock


class TestRateLimiterWithDedicatedRedis:
    """Unit tests for rate limiter Redis client initialization."""

    @patch("mcpgateway.auth.redis.from_url")
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
            mock_settings.ratelimiter_redis_ssl = False

            from mcpgateway.auth import _get_ratelimiter_redis_client

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
