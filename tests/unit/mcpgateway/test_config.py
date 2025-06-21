# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

"""

from unittest.mock import MagicMock, patch

from mcpgateway.config import Settings, get_settings


def test_settings_default_values():
    """
    Verify the class defaults only, independent of anything in the
    developer's local .env file. Passing ``_env_file=None`` tells
    Pydantic not to load any environment file.
    """
    settings = Settings(_env_file=None)

    assert settings.app_name == "MCP_Gateway"
    assert settings.host == "127.0.0.1"
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
    """
    Ensure get_settings() calls the Settings constructor exactly once and
    then serves the cached object on every additional call.
    """
    # Clear the cache created at import-time.
    get_settings.cache_clear()

    # Two distinct mock Settings instances, each with the methods that
    # get_settings() invokes (validate_transport / validate_database).
    settings_instance_1 = MagicMock()
    settings_instance_2 = MagicMock()

    # Each mock must expose these methods so AttributeError is not raised.
    settings_instance_1.validate_transport.return_value = None
    settings_instance_1.validate_database.return_value = None
    settings_instance_2.validate_transport.return_value = None
    settings_instance_2.validate_database.return_value = None

    # First call should return instance_1; any further constructor calls
    # would return instance_2 (but they shouldn't happen).
    mock_settings.side_effect = [settings_instance_1, settings_instance_2]

    result1 = get_settings()
    assert result1 is settings_instance_1

    # Even after we change what the constructor would return, the cached
    # object must still be served.
    result2 = get_settings()
    assert result2 is settings_instance_1

    # The constructor should have been invoked exactly once.
    assert mock_settings.call_count == 1
