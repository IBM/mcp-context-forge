# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_main_client_disconnect.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for client disconnect middleware registration in main.py.
"""

import importlib
from unittest.mock import patch


def test_client_disconnect_middleware_registered_when_enabled():
    """ClientDisconnectMiddleware is added when feature flag is enabled."""
    with patch("mcpgateway.main.settings.client_disconnect_middleware_enabled", True):
        main = importlib.reload(importlib.import_module("mcpgateway.main"))

    middleware_classes = [mw.cls.__name__ for mw in main.app.user_middleware]
    assert "ClientDisconnectMiddleware" in middleware_classes


def test_client_disconnect_middleware_not_registered_when_disabled():
    """ClientDisconnectMiddleware is NOT added when feature flag is disabled."""
    with patch("mcpgateway.main.settings.client_disconnect_middleware_enabled", False):
        main = importlib.reload(importlib.import_module("mcpgateway.main"))

    middleware_classes = [mw.cls.__name__ for mw in main.app.user_middleware]
    assert "ClientDisconnectMiddleware" not in middleware_classes
