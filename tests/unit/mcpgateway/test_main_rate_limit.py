import importlib
from unittest.mock import patch


def test_rate_limit_middleware_registered_when_enabled():
    """Test RateLimitMiddleware is added when enabled."""
    with patch("mcpgateway.main.settings.rate_limiting_enabled", True), patch(
        "mcpgateway.main.settings.rate_limiting_redis_enabled", False
    ), patch("mcpgateway.main.settings.rate_limit_critical_rpm", 10), patch("mcpgateway.main.settings.rate_limit_critical_burst", 0), patch(
        "mcpgateway.main.settings.rate_limit_high_rpm", 30
    ), patch("mcpgateway.main.settings.rate_limit_high_burst", 0), patch(
        "mcpgateway.main.settings.rate_limit_medium_rpm", 100
    ), patch("mcpgateway.main.settings.rate_limit_medium_burst", 20), patch(
        "mcpgateway.main.settings.rate_limit_low_rpm", 500
    ), patch("mcpgateway.main.settings.rate_limit_low_burst", 100), patch(
        "mcpgateway.main.settings.rate_limit_lockout_enabled", True
    ), patch("mcpgateway.main.settings.rate_limit_lockout_threshold", 5), patch(
        "mcpgateway.main.settings.rate_limit_lockout_duration_minutes", 15
    ):
        main = importlib.reload(importlib.import_module("mcpgateway.main"))

    middleware_classes = [mw.cls.__name__ for mw in main.app.user_middleware]
    assert "RateLimitMiddleware" in middleware_classes
