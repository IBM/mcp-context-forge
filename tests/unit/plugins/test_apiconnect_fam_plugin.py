# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_apiconnect_fam_plugin.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Unit tests for IBM API Connect Federated API Management Plugin.
Tests the main plugin class, configuration, initialization, and lifecycle.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.plugins.framework import PluginConfig
from plugins.apiconnect_fam.apiconnect_fam import APIConnectFAMPlugin, APIConnectFAMConfig


class TestAPIConnectFAMConfig:
    """Test configuration model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = APIConnectFAMConfig()
        
        assert config.interval_seconds == 60
        assert config.log_details is True
        assert config.fam_enabled is False
        assert config.fam_base_url is None
        assert config.fam_runtime_id is None
        assert config.fam_timeout == 30
        assert config.fam_verify_ssl is True
        assert config.fam_asset_sync_enabled is True
        assert config.fam_asset_sync_interval == 60
        assert config.metrics_sync_enabled is False
        assert config.metrics_sync_interval == 300

    def test_custom_config(self):
        """Test custom configuration values."""
        config = APIConnectFAMConfig(
            interval_seconds=120,
            fam_enabled=True,
            fam_base_url="https://fam.example.com",
            fam_runtime_id="test-runtime-123",
            fam_username="admin",
            fam_password="secret",
            fam_timeout=60,
            fam_verify_ssl=False,
            metrics_sync_enabled=True,
            metrics_sync_interval=600
        )
        
        assert config.interval_seconds == 120
        assert config.fam_enabled is True
        assert config.fam_base_url == "https://fam.example.com"
        assert config.fam_runtime_id == "test-runtime-123"
        assert config.fam_username == "admin"
        assert config.fam_password == "secret"
        assert config.fam_timeout == 60
        assert config.fam_verify_ssl is False
        assert config.metrics_sync_enabled is True
        assert config.metrics_sync_interval == 600


class TestAPIConnectFAMPlugin:
    """Test main plugin class."""

    def _make_plugin_config(self, **config_overrides):
        """Create a plugin config for testing."""
        config = {
            "fam_enabled": False,
            "interval_seconds": 60,
        }
        config.update(config_overrides)
        
        return PluginConfig(
            id="test-fam",
            kind="apiconnect_fam",
            name="Test FAM Plugin",
            enabled=True,
            order=0,
            config=config,
        )

    def test_plugin_initialization_disabled(self):
        """Test plugin initialization when FAM is disabled."""
        config = self._make_plugin_config(fam_enabled=False)
        plugin = APIConnectFAMPlugin(config)
        
        assert plugin._cfg.fam_enabled is False
        assert plugin._fam_client is None
        assert plugin._orchestrator is None

    @pytest.mark.asyncio
    async def test_initialize_when_disabled(self):
        """Test initialize does nothing when FAM is disabled."""
        config = self._make_plugin_config(fam_enabled=False)
        plugin = APIConnectFAMPlugin(config)
        
        await plugin.initialize()
        
        assert plugin._fam_client is None
        assert plugin._orchestrator is None

    @pytest.mark.asyncio
    async def test_initialize_fails_without_required_fields(self):
        """Test initialize fails when required fields are missing."""
        config = self._make_plugin_config(
            fam_enabled=True,
            fam_base_url="https://fam.example.com",
            # Missing: fam_username, fam_password, fam_runtime_id
        )
        plugin = APIConnectFAMPlugin(config)
        
        with pytest.raises(ValueError, match="required fields missing"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_success_with_all_fields(self):
        """Test successful initialization with all required fields."""
        config = self._make_plugin_config(
            fam_enabled=True,
            fam_base_url="https://fam.example.com",
            fam_runtime_id="test-runtime-123",
            fam_username="admin",
            fam_password="secret",
        )
        plugin = APIConnectFAMPlugin(config)
        
        with patch("plugins.apiconnect_fam.apiconnect_fam.FAMAssetCatalogClient") as mock_client_class, \
             patch("plugins.apiconnect_fam.apiconnect_fam.ActivityOrchestrator") as mock_orchestrator_class:
            
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            
            mock_orchestrator = AsyncMock()
            mock_orchestrator.start = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            
            await plugin.initialize()
            
            # Verify FAM client was created
            mock_client_class.assert_called_once_with(
                base_url="https://fam.example.com",
                runtime_id="test-runtime-123",
                username="admin",
                password="secret",
                timeout=30,
                verify_ssl=True
            )
            
            # Verify orchestrator was created and started
            mock_orchestrator_class.assert_called_once()
            mock_orchestrator.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_resources(self):
        """Test shutdown closes FAM client and orchestrator."""
        config = self._make_plugin_config(fam_enabled=False)
        plugin = APIConnectFAMPlugin(config)
        
        # Mock the resources with proper async mock objects
        mock_client = AsyncMock()
        mock_orchestrator = AsyncMock()
        
        plugin._fam_client = mock_client
        plugin._orchestrator = mock_orchestrator
        
        await plugin.shutdown()
        
        mock_orchestrator.stop.assert_awaited_once()
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_handles_none_resources(self):
        """Test shutdown handles None resources gracefully."""
        config = self._make_plugin_config(fam_enabled=False)
        plugin = APIConnectFAMPlugin(config)
        
        # No resources initialized
        await plugin.shutdown()  # Should not raise

    def test_runtime_metadata_configuration(self):
        """Test runtime metadata is properly configured."""
        config = self._make_plugin_config(
            fam_enabled=True,
            fam_runtime_name="Custom Gateway",
            fam_runtime_description="Custom Description",
            fam_runtime_type="CUSTOM_TYPE",
            fam_runtime_deployment_type="CLOUD",
            fam_runtime_region="us-west-2",
            fam_runtime_location="Oregon",
            fam_runtime_host="gateway-01",
            fam_runtime_tags=["prod", "api"],
            fam_runtime_capacity_value="200",
            fam_runtime_capacity_unit="requests/sec",
        )
        plugin = APIConnectFAMPlugin(config)
        
        assert plugin._cfg.fam_runtime_name == "Custom Gateway"
        assert plugin._cfg.fam_runtime_description == "Custom Description"
        assert plugin._cfg.fam_runtime_type == "CUSTOM_TYPE"
        assert plugin._cfg.fam_runtime_deployment_type == "CLOUD"
        assert plugin._cfg.fam_runtime_region == "us-west-2"
        assert plugin._cfg.fam_runtime_location == "Oregon"
        assert plugin._cfg.fam_runtime_host == "gateway-01"
        assert plugin._cfg.fam_runtime_tags == ["prod", "api"]
        assert plugin._cfg.fam_runtime_capacity_value == "200"
        assert plugin._cfg.fam_runtime_capacity_unit == "requests/sec"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])