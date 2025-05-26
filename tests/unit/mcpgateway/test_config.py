# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

"""
from unittest.mock import patch

import pytest

from mcpgateway.config import Settings, get_settings


def test_settings_default_values():
    """Test that Settings has expected default values."""
    settings = Settings()
    assert settings.app_name == "MCP Gateway"
    assert settings.host == "0.0.0.0"
    assert settings.port == 4444
    assert settings.database_url == "sqlite:///./mcp.db"
    assert settings.basic_auth_user == "admin"
    assert settings.basic_auth_password == "changeme"
    assert settings.auth_required is True


def test_api_key_property():
    """Test the api_key property."""
    settings = Settings(basic_auth_user="test_user", basic_auth_password="test_pass")
    assert settings.api_key == "test_user:test_pass"


def test_supports_transport_properties():
    """Test the transport support properties."""
    # Test 'all' transport type
    settings = Settings(transport_type="all")
    assert settings.supports_http is True
    assert settings.supports_websocket is True
    assert settings.supports_sse is True

    # Test 'http' transport type
    settings = Settings(transport_type="http")
    assert settings.supports_http is True
    assert settings.supports_websocket is False
    assert settings.supports_sse is False

    # Test 'ws' transport type
    settings = Settings(transport_type="ws")
    assert settings.supports_http is False
    assert settings.supports_websocket is True
    assert settings.supports_sse is False


@patch("mcpgateway.config.Settings")
def test_get_settings_caching(mock_settings):
    """Test that get_settings caches the result."""
    mock_settings.return_value = "test_settings"

    # First call should create settings
    result1 = get_settings()
    assert result1 == "test_settings"

    # Second call should use cached value
    mock_settings.return_value = "new_settings"
    result2 = get_settings()
    assert result2 == "test_settings"  # Should still be the first value

    # Settings should only be created once
    assert mock_settings.call_count == 1
