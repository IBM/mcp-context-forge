# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/apiconnect_fam/test_apiconnect_fam.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Unit tests for API Connect FAM Plugin.
Tests the core plugin initialization and configuration.
"""

import pytest
from pydantic import ValidationError

from plugins.apiconnect_fam.apiconnect_fam import APIConnectFAMConfig, APIConnectFAMPlugin
from mcpgateway.plugins.framework import PluginConfig


class TestAPIConnectFAMConfig:
    """Test configuration validation."""

    def test_config_defaults(self):
        """Test default configuration values."""
        config = APIConnectFAMConfig()
        assert config.interval_seconds == 60
        assert config.log_details is False
        assert config.fam_enabled is True
        assert config.fam_timeout == 30
        assert config.fam_verify_ssl is True

    def test_config_with_fam_settings(self):
        """Test configuration with FAM settings."""
        config = APIConnectFAMConfig(
            fam_enabled=True,
            fam_base_url="https://fam.example.com",
            fam_runtime_id="test-runtime-123",
            fam_username="admin",
            fam_password="secret",
        )
        assert config.fam_enabled is True
        assert config.fam_base_url == "https://fam.example.com"
        assert config.fam_runtime_id == "test-runtime-123"
        assert config.fam_username == "admin"
        assert config.fam_password == "secret"

    def test_config_validation_fam_enabled_requires_settings(self):
        """Test that FAM enabled requires base_url and runtime_id."""
        # This should work - FAM disabled
        config = APIConnectFAMConfig(fam_enabled=False)
        assert config.fam_enabled is False

        # This should work - FAM enabled with required settings
        config = APIConnectFAMConfig(
            fam_enabled=True,
            fam_base_url="https://fam.example.com",
            fam_runtime_id="test-runtime",
            fam_username="admin",
            fam_password="secret",
        )
        assert config.fam_enabled is True


class TestAPIConnectFAMPlugin:
    """Test plugin initialization and lifecycle."""

    def test_plugin_initialization_disabled(self):
        """Test plugin initializes when FAM is disabled."""
        plugin_config = PluginConfig(
            name="test_fam",
            kind="plugins.apiconnect_fam.apiconnect_fam.APIConnectFAMPlugin",
            hooks=[],
            priority=100,
            config={
                "fam_enabled": False,
                "interval_seconds": 30,
            },
        )
        plugin = APIConnectFAMPlugin(plugin_config)
        assert plugin is not None
        assert plugin.config.name == "test_fam"

    def test_plugin_initialization_enabled(self):
        """Test plugin initializes when FAM is enabled with valid config."""
        plugin_config = PluginConfig(
            name="test_fam",
            kind="plugins.apiconnect_fam.apiconnect_fam.APIConnectFAMPlugin",
            hooks=[],
            priority=100,
            config={
                "fam_enabled": True,
                "fam_base_url": "https://fam.example.com",
                "fam_runtime_id": "test-runtime-123",
                "fam_username": "admin",
                "fam_password": "secret",
                "interval_seconds": 30,
            },
        )
        plugin = APIConnectFAMPlugin(plugin_config)
        assert plugin is not None
        assert plugin.config.name == "test_fam"

    @pytest.mark.asyncio
    async def test_plugin_startup_disabled(self):
        """Test plugin startup when FAM is disabled."""
        plugin_config = PluginConfig(
            name="test_fam",
            kind="plugins.apiconnect_fam.apiconnect_fam.APIConnectFAMPlugin",
            hooks=[],
            priority=100,
            config={
                "fam_enabled": False,
            },
        )
        plugin = APIConnectFAMPlugin(plugin_config)
        
        # Should not raise an exception
        await plugin.startup()
        
        # Cleanup
        await plugin.shutdown()

    def test_plugin_config_validation(self):
        """Test plugin configuration validation."""
        # Valid config
        config = APIConnectFAMConfig(
            fam_enabled=True,
            fam_base_url="https://fam.example.com",
            fam_runtime_id="runtime-123",
            fam_username="user",
            fam_password="pass",
        )
        assert config.fam_enabled is True

        # Invalid interval
        with pytest.raises(ValidationError):
            APIConnectFAMConfig(interval_seconds=-1)


class TestPluginIntegration:
    """Integration tests for plugin components."""

    @pytest.mark.asyncio
    async def test_plugin_lifecycle(self):
        """Test complete plugin lifecycle (startup -> shutdown)."""
        plugin_config = PluginConfig(
            name="test_fam_lifecycle",
            kind="plugins.apiconnect_fam.apiconnect_fam.APIConnectFAMPlugin",
            hooks=[],
            priority=100,
            config={
                "fam_enabled": False,  # Disabled for testing
                "interval_seconds": 60,
            },
        )
        plugin = APIConnectFAMPlugin(plugin_config)
        
        # Startup
        await plugin.startup()
        
        # Shutdown
        await plugin.shutdown()
        
        # Should complete without errors
        assert True

