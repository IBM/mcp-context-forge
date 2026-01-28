# -*- coding: utf-8 -*-
"""Tests for request context caching helpers."""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock

# First-Party
from mcpgateway.middleware.request_context import get_request_path


def test_get_request_path_caches_value():
    request = MagicMock()
    request.state = SimpleNamespace()
    request.url.path = "/api/tools"

    first = get_request_path(request)
    request.url.path = "/other"
    second = get_request_path(request)

    assert first == "/api/tools"
    assert second == "/api/tools"
    assert request.state._cached_path == "/api/tools"
