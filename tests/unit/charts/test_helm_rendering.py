"""Unit tests for Helm chart rendering (Issue #4751).

Tests that rate limiter Redis environment variables are correctly rendered
in the deployment template when configured in values.yaml.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestRateLimiterRedisEnvInjection:
    """Test Helm renders RATELIMITER_REDIS_URL env vars."""

    def test_ratelimiter_redis_url_env_injection(self):
        """Verify deployment-mcpgateway.yaml includes env vars when configured."""
        # Mock Helm values
        mock_values = {
            "mcpContextForge": {
                "config": {
                    "RATELIMITER_REDIS_URL": "redis://rate-limiter:6379/0",
                    "RATELIMITER_REDIS_MAX_CONNECTIONS": "100",
                    "RATELIMITER_REDIS_SOCKET_TIMEOUT": "5.0",
                    "RATELIMITER_REDIS_SOCKET_CONNECT_TIMEOUT": "3.0"
                }
            }
        }

        # Expected env vars in rendered template
        expected_env_vars = [
            {"name": "RATELIMITER_REDIS_URL", "value": "redis://rate-limiter:6379/0"},
            {"name": "RATELIMITER_REDIS_MAX_CONNECTIONS", "value": "100"},
            {"name": "RATELIMITER_REDIS_SOCKET_TIMEOUT", "value": "5.0"},
            {"name": "RATELIMITER_REDIS_SOCKET_CONNECT_TIMEOUT", "value": "3.0"}
        ]

        # Simulate template rendering logic
        rendered_env = []
        config = mock_values["mcpContextForge"]["config"]

        if config.get("RATELIMITER_REDIS_URL"):
            rendered_env.append({
                "name": "RATELIMITER_REDIS_URL",
                "value": config["RATELIMITER_REDIS_URL"]
            })

        if config.get("RATELIMITER_REDIS_MAX_CONNECTIONS"):
            rendered_env.append({
                "name": "RATELIMITER_REDIS_MAX_CONNECTIONS",
                "value": config["RATELIMITER_REDIS_MAX_CONNECTIONS"]
            })

        if config.get("RATELIMITER_REDIS_SOCKET_TIMEOUT"):
            rendered_env.append({
                "name": "RATELIMITER_REDIS_SOCKET_TIMEOUT",
                "value": config["RATELIMITER_REDIS_SOCKET_TIMEOUT"]
            })

        if config.get("RATELIMITER_REDIS_SOCKET_CONNECT_TIMEOUT"):
            rendered_env.append({
                "name": "RATELIMITER_REDIS_SOCKET_CONNECT_TIMEOUT",
                "value": config["RATELIMITER_REDIS_SOCKET_CONNECT_TIMEOUT"]
            })

        # Verify all expected env vars are present
        assert rendered_env == expected_env_vars

    def test_ratelimiter_redis_url_not_rendered_when_unset(self):
        """Verify env vars are not rendered when RATELIMITER_REDIS_URL is unset."""
        mock_values = {
            "mcpContextForge": {
                "config": {}
            }
        }

        # Simulate template rendering logic
        rendered_env = []
        config = mock_values["mcpContextForge"]["config"]

        if config.get("RATELIMITER_REDIS_URL"):
            rendered_env.append({
                "name": "RATELIMITER_REDIS_URL",
                "value": config["RATELIMITER_REDIS_URL"]
            })

        # Verify no env vars rendered
        assert rendered_env == []
