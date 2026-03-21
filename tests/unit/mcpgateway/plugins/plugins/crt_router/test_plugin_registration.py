# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/crt_router/test_plugin_registration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Johnston Zhao

Tests for CRTRouterPlugin registration and discovery.
"""

import pytest
from mcpgateway.plugins.framework import Plugin


class TestPluginImport:
    """Test plugin can be imported."""
    
    def test_plugin_class_exists(self):
        """Verify CRTRouterPlugin class is importable."""
        from plugins.crt_router.crt_router import CRTRouterPlugin
        
        assert CRTRouterPlugin is not None
        assert issubclass(CRTRouterPlugin, Plugin)
    
    def test_plugin_config_class_exists(self):
        """Verify CRTRouterConfig class is importable."""
        from plugins.crt_router.crt_router import CRTRouterConfig
        
        assert CRTRouterConfig is not None


class TestPluginInstantiation:
    """Test plugin can be instantiated."""
    
    def test_plugin_instantiation_with_config(self, crt_router_plugin_config):
        """Test plugin can be created with valid config."""
        from plugins.crt_router.crt_router import CRTRouterPlugin
        
        plugin = CRTRouterPlugin(crt_router_plugin_config)
        
        assert plugin is not None
        assert plugin.name == "CRTRouter"
        assert plugin.priority == 50
        assert "tool_pre_invoke" in plugin.hooks
    
    def test_plugin_config_parsed_correctly(self, crt_router_plugin_config):
        """Test plugin config is parsed into _cfg attribute."""
        from plugins.crt_router.crt_router import CRTRouterPlugin
        
        plugin = CRTRouterPlugin(crt_router_plugin_config)
        
        assert hasattr(plugin, '_cfg')
        assert plugin._cfg.default_k == 10
        assert plugin._cfg.default_threshold == 0.72
        assert plugin._cfg.cache_enabled is True
    
    def test_plugin_router_initially_none(self, crt_router_plugin_config):
        """Test _router is None before initialization."""
        from plugins.crt_router.crt_router import CRTRouterPlugin
        
        plugin = CRTRouterPlugin(crt_router_plugin_config)
        
        assert plugin._router is None


class TestPluginConfiguration:
    """Test plugin configuration validation."""
    
    def test_default_configuration_values(self):
        """Test plugin uses default values when config is empty."""
        from mcpgateway.plugins.framework import PluginConfig
        from plugins.crt_router.crt_router import CRTRouterPlugin
        
        minimal_config = PluginConfig(
            name="CRTRouterMinimal",
            kind="plugins.crt_router.crt_router.CRTRouterPlugin",
            hooks=["tool_pre_invoke"],
            config={}  # Empty config
        )
        
        plugin = CRTRouterPlugin(minimal_config)
        
        # Should use default values
        assert plugin._cfg.default_k == 10
        assert plugin._cfg.default_threshold == 0.72
        assert plugin._cfg.calibration_path == "data/calibration/crt_model.json"
        assert plugin._cfg.cache_enabled is True
    
    def test_custom_configuration_values(self, crt_router_calibration_file):
        """Test plugin respects custom config values."""
        from mcpgateway.plugins.framework import PluginConfig
        from plugins.crt_router.crt_router import CRTRouterPlugin
        
        custom_config = PluginConfig(
            name="CRTRouterCustom",
            kind="plugins.crt_router.crt_router.CRTRouterPlugin",
            hooks=["tool_pre_invoke"],
            config={
                "calibration_path": str(crt_router_calibration_file),
                "default_k": 5,
                "default_threshold": 0.85,
                "cache_enabled": False
            }
        )
        
        plugin = CRTRouterPlugin(custom_config)
        
        assert plugin._cfg.default_k == 5
        assert plugin._cfg.default_threshold == 0.85
        assert plugin._cfg.cache_enabled is False
        assert str(plugin._cfg.calibration_path) == str(crt_router_calibration_file)


class TestPluginHooks:
    """Test plugin hook implementations."""
    
    def test_tool_pre_invoke_hook_exists(self, crt_router_plugin_config):
        """Test tool_pre_invoke method exists."""
        from plugins.crt_router.crt_router import CRTRouterPlugin
        
        plugin = CRTRouterPlugin(crt_router_plugin_config)
        
        assert hasattr(plugin, 'tool_pre_invoke')
        assert callable(plugin.tool_pre_invoke)
    
    def test_tool_pre_invoke_is_async(self, crt_router_plugin_config):
        """Test tool_pre_invoke is an async method."""
        from plugins.crt_router.crt_router import CRTRouterPlugin
        import inspect
        
        plugin = CRTRouterPlugin(crt_router_plugin_config)
        
        assert inspect.iscoroutinefunction(plugin.tool_pre_invoke)

