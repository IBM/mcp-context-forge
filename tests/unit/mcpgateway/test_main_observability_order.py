# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_main_observability_order.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the observability middleware registration order in main.py.

Issue #6473: observability_traces.user_email was NULL on every row because
ObservabilityMiddleware was registered after AuthContextMiddleware. Starlette's
add_middleware() inserts at position 0, so the later-registered middleware is
outermost and executes FIRST — observability ran before auth and start_trace()
read request.state.user before any authentication had set it.
"""

import importlib
from unittest.mock import patch


def test_observability_middleware_registered_inside_auth_context():
    """AuthContextMiddleware must execute before ObservabilityMiddleware.

    user_middleware[0] is the outermost, first-running middleware (reverse
    registration order), so AuthContextMiddleware must sit closer to the front
    of the list than ObservabilityMiddleware: start_trace() reads the identity
    AuthContextMiddleware has already set on request.state.
    """
    with (
        patch("mcpgateway.main.settings.observability_enabled", True),
        patch("mcpgateway.main.settings.security_logging_enabled", True),
    ):
        main = importlib.reload(importlib.import_module("mcpgateway.main"))

    middleware_classes = [mw.cls.__name__ for mw in main.app.user_middleware]
    assert "AuthContextMiddleware" in middleware_classes
    assert "ObservabilityMiddleware" in middleware_classes
    assert middleware_classes.index("AuthContextMiddleware") < middleware_classes.index("ObservabilityMiddleware")
