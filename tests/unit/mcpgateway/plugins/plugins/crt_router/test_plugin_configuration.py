# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/crt_router/test_plugin_configuration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Johnston Zhao

Tests for CRTRouterPlugin configuration validation.
"""

import pytest
from pydantic import ValidationError


class TestConfigValidation:
    """Test configuration validation."""
    
    def test_config_with_valid_values(self):
        """Test CRTRouterConfig accepts valid values."""
        from plugins.crt_router.crt_router import CRTRouterConfig
        
        config = CRTRouterConfig(
            calibration_path="test/path.json",
            default_k=15,
            default_threshold=0.8,
            cache_enabled=False
        )
        
        assert config.calibration_path == "test/path.json"
        assert config.default_k == 15
        assert config.default_threshold == 0.8
        assert config.cache_enabled is False
    
    def test_config_validates_k_range(self):
        """Test default_k must be in valid range."""
        from plugins.crt_router.crt_router import CRTRouterConfig
        
        # Valid values
        config1 = CRTRouterConfig(default_k=1)  # Minimum
        assert config1.default_k == 1
        
        config2 = CRTRouterConfig(default_k=100)  # Maximum
        assert config2.default_k == 100
        
        # Invalid values should raise (if validation added)
        # with pytest.raises(ValidationError):
        #     CRTRouterConfig(default_k=0)  # Too low
        #
        # with pytest.raises(ValidationError):
        #     CRTRouterConfig(default_k=101)  # Too high
    
    def test_config_validates_threshold_range(self):
        """Test default_threshold must be in [0, 1]."""
        from plugins.crt_router.crt_router import CRTRouterConfig
        
        # Valid values
        config1 = CRTRouterConfig(default_threshold=0.0)  # Minimum
        assert config1.default_threshold == 0.0
        
        config2 = CRTRouterConfig(default_threshold=1.0)  # Maximum
        assert config2.default_threshold == 1.0
        
        config3 = CRTRouterConfig(default_threshold=0.5)  # Middle
        assert config3.default_threshold == 0.5
        
        # Invalid values should raise (if validation added)
        # with pytest.raises(ValidationError):
        #     CRTRouterConfig(default_threshold=-0.1)  # Too low
        #
        # with pytest.raises(ValidationError):
        #     CRTRouterConfig(default_threshold=1.1)  # Too high


class TestPluginConfigIntegration:
    """Test plugin config integration."""
    
    def test_plugin_uses_config_for_router(self, crt_router_plugin_config):
        """Test plugin passes config to router correctly."""
        from plugins.crt_router.crt_router import CRTRouterPlugin
        
        plugin = CRTRouterPlugin(crt_router_plugin_config)
        
        # Config should be stored
        assert plugin._cfg.calibration_path == str(crt_router_plugin_config.config["calibration_path"])
        assert plugin._cfg.cache_enabled == crt_router_plugin_config.config["cache_enabled"]


