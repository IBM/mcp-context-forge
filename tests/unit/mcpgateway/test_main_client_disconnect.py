# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_main_client_disconnect.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for client disconnect middleware registration in main.py.
"""

# Third-Party
from fastapi import FastAPI

# First-Party
import mcpgateway.main as main_module


def test_client_disconnect_middleware_registered_when_enabled(monkeypatch):
    """ClientDisconnectMiddleware is added when feature flag is enabled."""
    monkeypatch.setattr(main_module.settings, "client_disconnect_middleware_enabled", True)

    app = FastAPI()
    main_module._register_middleware(app)  # pylint: disable=protected-access

    middleware_classes = [mw.cls.__name__ for mw in app.user_middleware]
    assert "ClientDisconnectMiddleware" in middleware_classes


def test_client_disconnect_middleware_not_registered_when_disabled(monkeypatch):
    """ClientDisconnectMiddleware is NOT added when feature flag is disabled."""
    monkeypatch.setattr(main_module.settings, "client_disconnect_middleware_enabled", False)

    app = FastAPI()
    main_module._register_middleware(app)  # pylint: disable=protected-access

    middleware_classes = [mw.cls.__name__ for mw in app.user_middleware]
    assert "ClientDisconnectMiddleware" not in middleware_classes
