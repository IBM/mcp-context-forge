# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/unit/mcpgateway/test_main_rate_limit.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

import importlib
from unittest.mock import patch

from starlette.applications import Starlette

from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware


def test_rate_limit_middleware_registered_when_enabled():
    """Test RateLimitMiddleware is added when enabled."""
    with (
        patch("mcpgateway.main.settings.rate_limiting_enabled", True),
        patch("mcpgateway.main.settings.rate_limiting_redis_enabled", False),
        patch("mcpgateway.main.settings.rate_limit_critical_rpm", 10),
        patch("mcpgateway.main.settings.rate_limit_critical_burst", 0),
        patch("mcpgateway.main.settings.rate_limit_high_rpm", 30),
        patch("mcpgateway.main.settings.rate_limit_high_burst", 0),
        patch("mcpgateway.main.settings.rate_limit_medium_rpm", 100),
        patch("mcpgateway.main.settings.rate_limit_medium_burst", 20),
        patch("mcpgateway.main.settings.rate_limit_low_rpm", 500),
        patch("mcpgateway.main.settings.rate_limit_low_burst", 100),
        patch("mcpgateway.main.settings.rate_limit_lockout_enabled", True),
        patch("mcpgateway.main.settings.rate_limit_lockout_threshold", 5),
        patch("mcpgateway.main.settings.rate_limit_lockout_duration_minutes", 15),
    ):
        main = importlib.reload(importlib.import_module("mcpgateway.main"))

    middleware_classes = [mw.cls.__name__ for mw in main.app.user_middleware]
    assert "RateLimitMiddleware" in middleware_classes


def test_appbridge_paths_use_high_rate_limit_tier(monkeypatch):
    """AppBridge session and RPC endpoints should not fall through to the broad MCP tier."""
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "rate_limiting_enabled", True)
    monkeypatch.setattr(settings, "rate_limiting_redis_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_high_rpm", 30)
    monkeypatch.setattr(settings, "rate_limit_high_burst", 5)
    monkeypatch.setattr(settings, "rate_limit_medium_rpm", 100)
    monkeypatch.setattr(settings, "rate_limit_medium_burst", 20)

    middleware = RateLimitMiddleware(Starlette())

    assert middleware.get_endpoint_tier("/appbridge/sessions") == {"pattern": r"^/appbridge/sessions(/|$)", "limit": 30, "burst": 5}
    assert middleware.get_endpoint_tier("/appbridge/sessions/app-session/rpc") == {"pattern": r"^/appbridge/sessions(/|$)", "limit": 30, "burst": 5}
    assert middleware.get_endpoint_tier("/mcp")["limit"] == 100
