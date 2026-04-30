# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_tenant_plugin_manager_tool_scoped.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for TenantPluginManagerFactory using tool_id as context scoping.

This test suite demonstrates that the factory can be used with any context identifier,
including tool IDs, to create isolated plugin manager instances per tool.
"""

# Standard
import asyncio
from typing import Optional

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory
from mcpgateway.plugins.framework.models import PluginConfigOverride, PluginMode


class ToolScopedPluginManagerFactory(TenantPluginManagerFactory):
    """Factory that uses tool_id as context for plugin configuration."""

    def __init__(self, yaml_path: str, tool_configs: Optional[dict[str, list[PluginConfigOverride]]] = None):
        """Initialize factory with tool-specific configurations.

        Args:
            yaml_path: Path to base plugin configuration.
            tool_configs: Dict mapping tool_id to list of plugin overrides.
        """
        super().__init__(yaml_path=yaml_path)
        self._tool_configs = tool_configs or {}

    async def get_config_from_db(self, context_id: str) -> Optional[list[PluginConfigOverride]]:
        """Get plugin configuration overrides for a specific tool.

        Args:
            context_id: The tool_id to fetch overrides for.

        Returns:
            List of plugin configuration overrides for this tool, or None.
        """
        return self._tool_configs.get(context_id)


@pytest.mark.asyncio
async def test_factory_with_tool_id_scoping():
    """Test that factory can use tool_id as context for isolated plugin managers."""
    # Define tool-specific plugin configurations
    tool_configs = {
        "tool_calculator": [
            PluginConfigOverride(
                name="ArgumentNormalizer",
                mode=PluginMode.ENFORCE,
                priority=10,
                config={"normalize_numbers": True},
            )
        ],
        "tool_file_reader": [
            PluginConfigOverride(
                name="ArgumentNormalizer",
                mode=PluginMode.PERMISSIVE,
                priority=50,
                config={"normalize_paths": True},
            )
        ],
    }

    # Create factory with tool-scoped configurations
    factory = ToolScopedPluginManagerFactory(
        yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        tool_configs=tool_configs,
    )

    try:
        # Get manager for calculator tool
        calc_manager = await factory.get_manager(context_id="tool_calculator")
        assert calc_manager is not None
        assert calc_manager.initialized

        # Get manager for file reader tool
        file_manager = await factory.get_manager(context_id="tool_file_reader")
        assert file_manager is not None
        assert file_manager.initialized

        # Verify they are different instances
        assert calc_manager is not file_manager

        # Get calculator manager again - should return cached instance
        calc_manager_2 = await factory.get_manager(context_id="tool_calculator")
        assert calc_manager_2 is calc_manager

    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_with_default_tool_context():
    """Test that factory uses default context when no tool_id is provided."""
    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Get manager without context_id - should use default
        default_manager = await factory.get_manager()
        assert default_manager is not None
        assert default_manager.initialized

        # Get manager with explicit None - should return same default
        default_manager_2 = await factory.get_manager(context_id=None)
        assert default_manager_2 is default_manager

    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_reload_tool_context():
    """Test that factory can reload a tool-specific manager."""
    tool_configs = {
        "tool_api_client": [
            PluginConfigOverride(
                name="ArgumentNormalizer",
                mode=PluginMode.ENFORCE,
                priority=20,
            )
        ],
    }

    factory = ToolScopedPluginManagerFactory(
        yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        tool_configs=tool_configs,
    )

    try:
        # Get initial manager
        manager1 = await factory.get_manager(context_id="tool_api_client")
        assert manager1 is not None

        # Reload the manager
        manager2 = await factory.reload_tenant(context_id="tool_api_client")
        assert manager2 is not None
        assert manager2 is not manager1  # Should be a new instance

        # Get manager again - should return the reloaded one
        manager3 = await factory.get_manager(context_id="tool_api_client")
        assert manager3 is manager2

    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_concurrent_tool_access():
    """Test that factory handles concurrent access to different tool contexts safely."""
    tool_configs = {
        f"tool_{i}": [
            PluginConfigOverride(
                name="ArgumentNormalizer",
                mode=PluginMode.ENFORCE,
                priority=i * 10,
            )
        ]
        for i in range(5)
    }

    factory = ToolScopedPluginManagerFactory(
        yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        tool_configs=tool_configs,
    )

    try:
        # Concurrently request managers for different tools
        tasks = [factory.get_manager(context_id=f"tool_{i}") for i in range(5)]
        managers = await asyncio.gather(*tasks)

        # Verify all managers were created
        assert len(managers) == 5
        assert all(m is not None for m in managers)
        assert all(m.initialized for m in managers)

        # Verify they are all different instances
        assert len(set(id(m) for m in managers)) == 5

    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_tool_without_overrides():
    """Test that factory works for tools without specific overrides."""
    tool_configs = {
        "tool_with_config": [
            PluginConfigOverride(
                name="ArgumentNormalizer",
                mode=PluginMode.ENFORCE,
            )
        ],
    }

    factory = ToolScopedPluginManagerFactory(
        yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        tool_configs=tool_configs,
    )

    try:
        # Get manager for tool without overrides - should use base config
        manager = await factory.get_manager(context_id="tool_without_config")
        assert manager is not None
        assert manager.initialized

    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_tenant_plugin_manager_with_config_object():
    """Test TenantPluginManager initialization with Config object instead of path."""
    # First-Party
    from mcpgateway.plugins.framework.loader.config import ConfigLoader

    # Load config from file
    config = ConfigLoader.load_config("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    # Create manager with Config object
    # First-Party
    from mcpgateway.plugins.framework.manager import TenantPluginManager

    manager = TenantPluginManager(config=config)
    try:
        await manager.initialize()
        assert manager.initialized
        assert manager._config_path is None
        assert manager._config is config
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_factory_observability_setter():
    """Test that observability setter updates the provider."""
    # Standard
    from unittest.mock import Mock

    # First-Party
    from mcpgateway.plugins.framework.observability import ObservabilityProvider

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Initially None
        assert factory.observability is None

        # Set observability provider (mock it since it's a Protocol)
        mock_provider = Mock(spec=ObservabilityProvider)
        factory.observability = mock_provider
        assert factory.observability is mock_provider

        # Clear observability
        factory.observability = None
        assert factory.observability is None
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_concurrent_same_context():
    """Test that concurrent requests for same context return same manager."""
    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Request same context concurrently
        tasks = [factory.get_manager(context_id="same_tool") for _ in range(5)]
        managers = await asyncio.gather(*tasks)

        # All should be the same instance
        assert len(set(id(m) for m in managers)) == 1
        assert all(m.initialized for m in managers)
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_build_manager_cancelled():
    """Test that cancelled build task properly cleans up."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Mock initialize to simulate cancellation
        with patch("mcpgateway.plugins.framework.manager.TenantPluginManager.initialize", new_callable=AsyncMock) as mock_init:
            mock_init.side_effect = asyncio.CancelledError()

            # Attempt to get manager - should raise CancelledError
            with pytest.raises(asyncio.CancelledError):
                await factory.get_manager(context_id="cancelled_tool")

            # Verify inflight was cleaned up
            assert "cancelled_tool" not in factory._inflight
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_build_manager_exception():
    """Test that exception during build properly cleans up."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Mock initialize to raise exception
        with patch("mcpgateway.plugins.framework.manager.TenantPluginManager.initialize", new_callable=AsyncMock) as mock_init:
            mock_init.side_effect = RuntimeError("Init failed")

            # Attempt to get manager - should raise RuntimeError
            with pytest.raises(RuntimeError, match="Init failed"):
                await factory.get_manager(context_id="error_tool")

            # Verify inflight was cleaned up
            assert "error_tool" not in factory._inflight
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_merge_tenant_config_none():
    """Test _merge_tenant_config with None override returns base config."""
    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Call with None should return base config
        merged = factory._merge_tenant_config(None)
        assert merged is factory._base_config
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_reload_shutdown_exception():
    """Test that reload handles old manager shutdown exception gracefully."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Get initial manager
        manager1 = await factory.get_manager(context_id="reload_error_tool")
        assert manager1 is not None

        # Mock shutdown to raise exception
        with patch.object(manager1, "shutdown", new_callable=AsyncMock) as mock_shutdown:
            mock_shutdown.side_effect = RuntimeError("Shutdown failed")

            # Reload should succeed despite shutdown error
            manager2 = await factory.reload_tenant(context_id="reload_error_tool")
            assert manager2 is not None
            assert manager2 is not manager1
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_reload_cancels_inflight():
    """Test that reload cancels any existing inflight build task."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Start a slow build
        with patch("mcpgateway.plugins.framework.manager.TenantPluginManager.initialize", new_callable=AsyncMock) as mock_init:
            # Make initialize slow
            async def slow_init():
                await asyncio.sleep(1)

            mock_init.side_effect = slow_init

            # Start build in background
            task = asyncio.create_task(factory.get_manager(context_id="slow_tool"))
            await asyncio.sleep(0.1)  # Let it start

            # Reload should cancel the inflight task
            manager = await factory.reload_tenant(context_id="slow_tool")
            assert manager is not None

            # Original task should be cancelled
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_shutdown_with_exceptions():
    """Test that shutdown handles manager shutdown exceptions gracefully."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    # Create multiple managers
    manager1 = await factory.get_manager(context_id="tool1")
    manager2 = await factory.get_manager(context_id="tool2")

    # Mock shutdown to raise exception for one manager
    with patch.object(manager1, "shutdown", new_callable=AsyncMock) as mock_shutdown1:
        mock_shutdown1.side_effect = RuntimeError("Shutdown failed")

        # Shutdown should complete despite exception
        await factory.shutdown()

        # Verify both managers were attempted to shutdown
        assert mock_shutdown1.called


@pytest.mark.asyncio
async def test_factory_shutdown_cancels_inflight():
    """Test that shutdown cancels all inflight build tasks."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    # Start multiple slow builds
    with patch("mcpgateway.plugins.framework.manager.TenantPluginManager.initialize", new_callable=AsyncMock) as mock_init:
        # Make initialize slow
        async def slow_init():
            await asyncio.sleep(2)


@pytest.mark.asyncio
async def test_tenant_plugin_manager_with_string_path():
    """Test TenantPluginManager initialization with string path."""
    # First-Party
    from mcpgateway.plugins.framework.manager import TenantPluginManager

    # Create manager with string path (not Config object)
    manager = TenantPluginManager(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")
    try:
        await manager.initialize()
        assert manager.initialized
        assert manager._config_path == "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml"
        assert manager._config is not None
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_factory_merge_with_overrides():
    """Test _merge_tenant_config with actual overrides."""
    tool_configs = {
        "tool_with_override": [
            PluginConfigOverride(
                name="TestPlugin",
                mode=PluginMode.PERMISSIVE,
                priority=99,
                config={"new_setting": "value"},
            )
        ],
    }

    factory = ToolScopedPluginManagerFactory(
        yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        tool_configs=tool_configs,
    )

    try:
        # Get manager which will trigger merge
        manager = await factory.get_manager(context_id="tool_with_override")
        assert manager is not None
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_build_manager_old_shutdown_fails():
    """Test that _build_manager handles old manager shutdown failure."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Get initial manager
        manager1 = await factory.get_manager(context_id="test_old_shutdown")
        assert manager1 is not None

        # Mock shutdown to fail
        with patch.object(manager1, "shutdown", new_callable=AsyncMock) as mock_shutdown:
            mock_shutdown.side_effect = RuntimeError("Shutdown failed")

            # Get manager again with different config to trigger replacement
            # This should handle the shutdown exception gracefully
            manager2 = await factory.get_manager(context_id="test_old_shutdown")
            assert manager2 is not None
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_reload_inflight_cleanup():
    """Test that reload properly cleans up inflight tasks."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Start a slow build
        with patch("mcpgateway.plugins.framework.manager.TenantPluginManager.initialize", new_callable=AsyncMock) as mock_init:
            # Make initialize slow
            async def slow_init():
                await asyncio.sleep(0.5)

            mock_init.side_effect = slow_init

            # Start build in background
            task = asyncio.create_task(factory.get_manager(context_id="slow_reload"))
            await asyncio.sleep(0.05)  # Let it start

            # Reload should cancel and clean up
            manager = await factory.reload_tenant(context_id="slow_reload")
            assert manager is not None

            # Verify inflight was cleaned up in finally block
            assert "slow_reload" not in factory._inflight
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_shutdown_empty_inflight():
    """Test shutdown with no inflight tasks."""
    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    # Create some managers
    await factory.get_manager(context_id="tool1")
    await factory.get_manager(context_id="tool2")

    # Shutdown should handle empty inflight list
    await factory.shutdown()

    # Verify cleanup
    assert len(factory._managers) == 0
    assert len(factory._inflight) == 0


@pytest.mark.asyncio
async def test_factory_shutdown_with_active_inflight():
    """Test shutdown cancels active inflight build tasks."""
    # Standard
    from unittest.mock import AsyncMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    # Start multiple slow builds
    with patch("mcpgateway.plugins.framework.manager.TenantPluginManager.initialize", new_callable=AsyncMock) as mock_init:
        # Make initialize slow
        async def slow_init():
            await asyncio.sleep(0.5)

        mock_init.side_effect = slow_init

        # Start builds in background
        tasks = [asyncio.create_task(factory.get_manager(context_id=f"tool{i}")) for i in range(3)]
        await asyncio.sleep(0.05)  # Let them start

        # Shutdown should cancel all inflight tasks
        await factory.shutdown()

        # All tasks should be cancelled or done
        for task in tasks:
            assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_factory_merge_with_plugin_config_override():
    """Test _merge_tenant_config properly merges plugin configurations."""
    # First-Party
    from mcpgateway.plugins.framework.loader.config import ConfigLoader

    # Create a base config with a plugin
    base_yaml = "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml"
    ConfigLoader.load_config(base_yaml)

    factory = ToolScopedPluginManagerFactory(yaml_path=base_yaml)

    try:
        # Create override with config merge
        override = PluginConfigOverride(
            name="TestPlugin",
            mode=PluginMode.PERMISSIVE,
            priority=99,
            config={"new_key": "new_value"},
        )

        # Test merge
        merged = factory._merge_tenant_config([override])
        assert merged is not None
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_build_manager_cancelled_with_shutdown_error():
    """Test _build_manager handles CancelledError with shutdown exception."""
    # Standard
    from unittest.mock import AsyncMock, MagicMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Create a manager mock that will fail on shutdown
        manager_mock = MagicMock()
        manager_mock.shutdown = AsyncMock(side_effect=RuntimeError("Shutdown failed"))

        with patch("mcpgateway.plugins.framework.manager.TenantPluginManager") as MockManager:
            # Make the constructor return our mock
            MockManager.return_value = manager_mock

            # Make initialize raise CancelledError
            manager_mock.initialize = AsyncMock(side_effect=asyncio.CancelledError())

            # Attempt to get manager - should raise CancelledError
            with pytest.raises(asyncio.CancelledError):
                await factory.get_manager(context_id="cancelled_with_error")

            # Verify shutdown was attempted despite the error
            manager_mock.shutdown.assert_called_once()
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_build_manager_exception_with_shutdown_error():
    """Test _build_manager handles Exception with shutdown exception."""
    # Standard
    from unittest.mock import AsyncMock, MagicMock, patch

    factory = ToolScopedPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Create a manager mock that will fail on shutdown
        manager_mock = MagicMock()
        manager_mock.shutdown = AsyncMock(side_effect=RuntimeError("Shutdown failed"))

        with patch("mcpgateway.plugins.framework.manager.TenantPluginManager") as MockManager:
            # Make the constructor return our mock
            MockManager.return_value = manager_mock

            # Make initialize raise a regular exception
            manager_mock.initialize = AsyncMock(side_effect=ValueError("Init failed"))

            # Attempt to get manager - should raise ValueError
            with pytest.raises(ValueError, match="Init failed"):
                await factory.get_manager(context_id="error_with_shutdown_error")

            # Verify shutdown was attempted despite the error
            manager_mock.shutdown.assert_called_once()
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_merge_config_with_mode_and_priority():
    """Test _merge_tenant_config properly handles mode and priority overrides."""
    # First-Party
    from mcpgateway.plugins.framework.loader.config import ConfigLoader
    from mcpgateway.plugins.framework.models import PluginConfig

    # Create a base config with a plugin
    base_yaml = "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml"
    base_config = ConfigLoader.load_config(base_yaml)

    # Add a plugin to base config for testing
    test_plugin = PluginConfig(
        name="TestPlugin",
        kind="test.plugin.TestPlugin",
        hooks=["prompt_pre_fetch"],
        mode=PluginMode.ENFORCE,
        priority=50,
        config={"base_key": "base_value"},
    )
    base_config.plugins = [test_plugin]

    factory = ToolScopedPluginManagerFactory(yaml_path=base_yaml)
    factory._base_config = base_config

    try:
        # Create override with mode, priority, and config
        override = PluginConfigOverride(
            name="TestPlugin",
            mode=PluginMode.PERMISSIVE,
            priority=99,
            config={"override_key": "override_value"},
        )

        # Test merge
        merged = factory._merge_tenant_config([override])
        assert merged is not None
        assert len(merged.plugins) == 1

        merged_plugin = merged.plugins[0]
        assert merged_plugin.mode == PluginMode.PERMISSIVE
        assert merged_plugin.priority == 99
        assert "base_key" in merged_plugin.config
        assert "override_key" in merged_plugin.config
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_merge_config_no_override_for_plugin():
    """Test _merge_tenant_config keeps original plugin when no override exists."""
    # First-Party
    from mcpgateway.plugins.framework.loader.config import ConfigLoader
    from mcpgateway.plugins.framework.models import PluginConfig

    # Create a base config with a plugin
    base_yaml = "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml"
    base_config = ConfigLoader.load_config(base_yaml)

    # Add a plugin to base config for testing
    test_plugin = PluginConfig(
        name="TestPlugin",
        kind="test.plugin.TestPlugin",
        hooks=["prompt_pre_fetch"],
        mode=PluginMode.ENFORCE,
        priority=50,
        config={"base_key": "base_value"},
    )
    base_config.plugins = [test_plugin]

    factory = ToolScopedPluginManagerFactory(yaml_path=base_yaml)
    factory._base_config = base_config

    try:
        # Create override for a different plugin
        override = PluginConfigOverride(
            name="DifferentPlugin",
            mode=PluginMode.PERMISSIVE,
            priority=99,
        )

        # Test merge - TestPlugin should remain unchanged
        merged = factory._merge_tenant_config([override])
        assert merged is not None
        assert len(merged.plugins) == 1

        merged_plugin = merged.plugins[0]
        assert merged_plugin.name == "TestPlugin"
        assert merged_plugin.mode == PluginMode.ENFORCE
        assert merged_plugin.priority == 50
    finally:
        await factory.shutdown()


@pytest.mark.asyncio
async def test_factory_get_config_from_db_default():
    """Test that default get_config_from_db returns None."""
    factory = TenantPluginManagerFactory(yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")

    try:
        # Default implementation should return None
        result = await factory.get_config_from_db("any_context")
        assert result is None
    finally:
        await factory.shutdown()
