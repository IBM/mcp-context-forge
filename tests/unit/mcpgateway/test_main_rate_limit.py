# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_main_rate_limit.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Module Description.
Module documentation...
"""

# Third-Party
from fastapi import FastAPI
from starlette.applications import Starlette

# First-Party
import mcpgateway.main as main_module
from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware


def test_rate_limit_middleware_registered_when_enabled(monkeypatch):
    """Test RateLimitMiddleware is added when enabled."""
    monkeypatch.setattr(main_module.settings, "rate_limiting_enabled", True)

    app = FastAPI()
    main_module._register_middleware(app)  # pylint: disable=protected-access

    middleware_classes = [mw.cls.__name__ for mw in app.user_middleware]
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
