#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_container_scanner/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Shared fixtures for container scanner integration tests.

The container scanner is an external plugin server (not a mcpgateway router).
Tests build a minimal Starlette app from the server's route handlers directly,
bypassing the MCP transport layer.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

# Local
import plugins.container_scanner.server as _server_module
from plugins.container_scanner.storage.repository import container_scan_repo


def _make_test_app() -> Starlette:
    """Build a minimal Starlette app from the server's HTTP route handlers."""
    return Starlette(
        routes=[
            Route("/", _server_module._serve_ui, methods=["GET"]),  # pylint: disable=protected-access
            Route("/health", _server_module._health, methods=["GET"]),  # pylint: disable=protected-access
            Route("/scans", _server_module._list_scans, methods=["GET"]),  # pylint: disable=protected-access
            Route("/scan", _server_module._trigger_scan, methods=["POST"]),  # pylint: disable=protected-access
        ]
    )


@pytest.fixture
def clean_repo():
    """Clear the shared singleton before and after each test."""
    container_scan_repo.clear()
    yield container_scan_repo
    container_scan_repo.clear()


@pytest.fixture
def client(clean_repo):  # noqa: F811
    """TestClient wrapping the plugin server's HTTP routes."""
    yield TestClient(_make_test_app(), raise_server_exceptions=False)


@pytest.fixture
def mock_plugin():
    """A mock ContainerScannerPlugin instance for POST /scan tests."""
    plugin = MagicMock()
    plugin.scan = AsyncMock()
    return plugin


@pytest.fixture
def client_with_plugin(clean_repo, mock_plugin):  # noqa: F811
    """TestClient with a mock plugin server wired into the _trigger_scan handler."""
    mock_server = MagicMock()
    mock_server._plugin_manager.get_plugin.return_value = mock_plugin  # pylint: disable=protected-access

    original = _server_module._server  # pylint: disable=protected-access
    _server_module._server = mock_server  # pylint: disable=protected-access
    try:
        yield TestClient(_make_test_app(), raise_server_exceptions=False), mock_plugin
    finally:
        _server_module._server = original  # pylint: disable=protected-access
