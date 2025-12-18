# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin_smoke.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Adrian Popa

Smoke tests for Vault Plugin - verifies plugin interface integrity.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginMode,
    ToolHookType,
)

# Import the Vault plugin
from plugins.vault.vault_plugin import Vault


class TestVaultPluginSmoke:
    """Smoke tests to verify the Vault plugin interface is intact."""

    @pytest.fixture
    def plugin_config(self) -> PluginConfig:
        """Create a minimal test plugin configuration."""
        return PluginConfig(
            name="TestVault",
            description="Test Vault Plugin",
            author="Test",
            kind="plugins.vault.vault_plugin.Vault",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test", "vault"],
            mode=PluginMode.ENFORCE,
            priority=10,
            config={},
        )

    def test_plugin_can_be_instantiated(self, plugin_config):
        """Test that the Vault plugin can be instantiated."""
        plugin = Vault(plugin_config)
        assert plugin is not None
        assert isinstance(plugin, Vault)

    def test_plugin_has_required_interface(self, plugin_config):
        """Test that the plugin has the required tool_pre_invoke method."""
        plugin = Vault(plugin_config)

        # Check that required hook method exists
        assert hasattr(plugin, "tool_pre_invoke")
        assert callable(plugin.tool_pre_invoke)

        # Check that shutdown method exists
        assert hasattr(plugin, "shutdown")
        assert callable(plugin.shutdown)

    @pytest.mark.asyncio
    async def test_shutdown_method_works(self, plugin_config):
        """Test that the shutdown method can be called without errors."""
        plugin = Vault(plugin_config)
        result = await plugin.shutdown()
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
