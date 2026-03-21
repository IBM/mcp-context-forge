"""
CRT Router Plugin Test Fixtures

This module provides reusable test fixtures for CRT Router plugin tests.
All fixtures are scoped to tests/plugins/crt_router/ and use the
crt_router_* naming prefix to avoid conflicts with other plugin fixtures.

Fixture Categories:
    1. Test Data Fixtures: Raw calibration data
    2. File Fixtures: Temporary calibration files
    3. Configuration Fixtures: Plugin configuration objects
    4. Instance Fixtures: Plugin instances (initialized and uninitialized)
    5. Payload/Context Fixtures: Test inputs for hook testing

Usage:
    def test_something(crt_router_plugin_instance):
        assert crt_router_plugin_instance.name == "CRTRouter"
"""

import pytest
import json
from pathlib import Path
from typing import Dict, Any


# ============================================================================
# CATEGORY 1: Test Data Fixtures
# Provide raw test data (dicts, strings, etc.)
# ============================================================================

@pytest.fixture
def crt_router_calibration_data() -> Dict[str, Any]:
    """
    Minimal calibration data for testing CRT Router.
    
    Returns a dictionary containing all required calibration fields:
    - version
    - created_at
    - difficulty_bins
    - prime_list
    - prior_distribution
    - calibrated_success_tables
    - tool_embeddings
    
    This fixture loads data from fixtures/test_calibration.json if it exists,
    otherwise returns inline test data.
    
    Returns:
        Dict[str, Any]: Valid calibration data dictionary
        
    Example:
        def test_calibration_format(crt_router_calibration_data):
            assert "version" in crt_router_calibration_data
            assert "difficulty_bins" in crt_router_calibration_data
    """
    fixture_path = Path(__file__).parent / "fixtures" / "test_calibration.json"
    
    if fixture_path.exists():
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    # Fallback inline data if fixture file doesn't exist
    return {
        "version": "1.0.0",
        "created_at": "2026-02-20T00:00:00Z",
        "difficulty_bins": [0.2, 0.5, 0.8],
        "prime_list": [3, 5, 7],
        "prior_distribution": {
            "s0": 0.33,
            "s1": 0.34,
            "s2": 0.33
        },
        "calibrated_success_tables": {
            "m0": {
                "s0_0": 0.9, "s0_1": 0.6, "s0_2": 0.3,
                "s1_0": 0.6, "s1_1": 0.7, "s1_2": 0.6,
                "s2_0": 0.3, "s2_1": 0.6, "s2_2": 0.9
            },
            "m1": {
                "s0_0": 0.85, "s0_1": 0.55, "s0_2": 0.25,
                "s0_3": 0.20, "s0_4": 0.15,
                "s1_0": 0.50, "s1_1": 0.60, "s1_2": 0.70,
                "s1_3": 0.60, "s1_4": 0.50,
                "s2_0": 0.25, "s2_1": 0.55, "s2_2": 0.85,
                "s2_3": 0.80, "s2_4": 0.75
            },
            "m2": {
                "s0_0": 0.88, "s0_1": 0.58, "s0_2": 0.28,
                "s0_3": 0.23, "s0_4": 0.18, "s0_5": 0.13, "s0_6": 0.10,
                "s1_0": 0.52, "s1_1": 0.62, "s1_2": 0.72,
                "s1_3": 0.62, "s1_4": 0.52, "s1_5": 0.42, "s1_6": 0.35,
                "s2_0": 0.22, "s2_1": 0.52, "s2_2": 0.82,
                "s2_3": 0.77, "s2_4": 0.72, "s2_5": 0.67, "s2_6": 0.62
            }
        },
        "tool_embeddings": {
            "test_tool_a": [0.1] * 10,
            "test_tool_b": [0.2] * 10,
            "test_tool_c": [0.3] * 10
        },
        "metadata": {
            "training_dataset": "test_suite_v1",
            "notes": "Inline test calibration data"
        }
    }


@pytest.fixture
def crt_router_invalid_calibration_data() -> Dict[str, Any]:
    """
    Invalid calibration data for error testing.
    
    This fixture provides calibration data that violates validation rules
    (e.g., prior distribution doesn't sum to 1.0) to test error handling.
    
    Returns:
        Dict[str, Any]: Invalid calibration data dictionary
        
    Example:
        def test_rejects_invalid_calibration(crt_router_invalid_calibration_data):
            with pytest.raises(ValidationError):
                calibration = CalibrationArtifact(**crt_router_invalid_calibration_data)
    """
    return {
        "version": "1.0.0",
        "created_at": "2026-02-20T00:00:00Z",
        "difficulty_bins": [0.2, 0.5, 0.8],
        "prime_list": [3, 5, 7],
        "prior_distribution": {
            "s0": 0.5,  # Invalid: Only sums to 0.5, should be 1.0
        },
        "calibrated_success_tables": {},
        "tool_embeddings": {}
    }


# ============================================================================
# CATEGORY 2: File Fixtures
# Create temporary files for testing
# ============================================================================

@pytest.fixture
def crt_router_calibration_file(crt_router_calibration_data, tmp_path) -> Path:
    """
    Create a temporary calibration JSON file.
    
    This fixture creates a temporary calibration file in tmp_path that
    is automatically cleaned up after the test completes. The file contains
    valid calibration data from crt_router_calibration_data fixture.
    
    Args:
        crt_router_calibration_data: Calibration data to write to file
        tmp_path: Pytest's built-in temporary directory fixture
        
    Returns:
        Path: Path to the temporary calibration file
        
    Example:
        def test_loads_calibration(crt_router_calibration_file):
            assert crt_router_calibration_file.exists()
            with open(crt_router_calibration_file) as f:
                data = json.load(f)
            assert data["version"] == "1.0.0"
    """
    cal_dir = tmp_path / "data" / "calibration"
    cal_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = cal_dir / "test_crt_model.json"
    with open(file_path, 'w') as f:
        json.dump(crt_router_calibration_data, f, indent=2)
    
    return file_path


@pytest.fixture
def crt_router_invalid_calibration_file(crt_router_invalid_calibration_data, tmp_path) -> Path:
    """
    Create a temporary INVALID calibration JSON file.
    
    This fixture creates a calibration file with invalid data to test
    error handling and validation logic. The file is automatically
    cleaned up after the test.
    
    Args:
        crt_router_invalid_calibration_data: Invalid calibration data
        tmp_path: Pytest's built-in temporary directory fixture
        
    Returns:
        Path: Path to the invalid calibration file
        
    Example:
        def test_handles_invalid_file(crt_router_invalid_calibration_file):
            with pytest.raises(ValidationError):
                router = CRTRouter(str(crt_router_invalid_calibration_file))
                await router.load_calibration()
    """
    cal_dir = tmp_path / "data" / "calibration"
    cal_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = cal_dir / "invalid_crt_model.json"
    with open(file_path, 'w') as f:
        json.dump(crt_router_invalid_calibration_data, f, indent=2)
    
    return file_path


@pytest.fixture
def crt_router_nonexistent_calibration_path(tmp_path) -> Path:
    """
    Provide a path to a non-existent calibration file.
    
    This fixture returns a path that does NOT exist, useful for testing
    error handling when calibration files are missing.
    
    Args:
        tmp_path: Pytest's built-in temporary directory fixture
        
    Returns:
        Path: Path to a file that doesn't exist
        
    Example:
        def test_handles_missing_file(crt_router_nonexistent_calibration_path):
            with pytest.raises(FileNotFoundError):
                router = CRTRouter(str(crt_router_nonexistent_calibration_path))
                await router.load_calibration()
    """
    return tmp_path / "nonexistent" / "calibration.json"


# ============================================================================
# CATEGORY 3: Configuration Fixtures
# Create plugin configuration objects
# ============================================================================

@pytest.fixture
def crt_router_plugin_config(crt_router_calibration_file):
    """
    Create a valid PluginConfig for CRTRouterPlugin.
    
    This fixture provides a complete PluginConfig with all required fields
    set to valid test values. The config points to a valid calibration file.
    
    Args:
        crt_router_calibration_file: Path to temporary calibration file
        
    Returns:
        PluginConfig: Valid plugin configuration object
        
    Example:
        def test_plugin_config(crt_router_plugin_config):
            assert crt_router_plugin_config.name == "CRTRouter"
            assert "tool_pre_invoke" in crt_router_plugin_config.hooks
    """
    from mcpgateway.plugins.framework import PluginConfig
    
    return PluginConfig(
        name="CRTRouter",
        kind="plugins.crt_router.crt_router.CRTRouterPlugin",
        description="CRT-based semantic tool router",
        author="test",
        version="1.0.0",
        hooks=["tool_pre_invoke"],
        mode="permissive",
        priority=50,
        enabled=True,
        tags=["routing", "semantic"],
        config={
            "calibration_path": str(crt_router_calibration_file),
            "default_k": 10,
            "default_threshold": 0.72,
            "cache_enabled": True
        }
    )


@pytest.fixture
def crt_router_minimal_plugin_config():
    """
    Create a minimal PluginConfig with only required fields.
    
    This fixture tests that the plugin works with minimal configuration,
    relying on default values for optional settings.
    
    Returns:
        PluginConfig: Minimal plugin configuration
        
    Example:
        def test_plugin_defaults(crt_router_minimal_plugin_config):
            plugin = CRTRouterPlugin(crt_router_minimal_plugin_config)
            assert plugin._cfg.default_k == 10  # Uses default
    """
    from mcpgateway.plugins.framework import PluginConfig
    
    return PluginConfig(
        name="CRTRouterMinimal",
        kind="plugins.crt_router.crt_router.CRTRouterPlugin",
        hooks=["tool_pre_invoke"],
        config={}  # Empty config to test defaults
    )


@pytest.fixture
def crt_router_custom_plugin_config(crt_router_calibration_file):
    """
    Create a PluginConfig with custom (non-default) values.
    
    This fixture tests that custom configuration values override defaults.
    
    Args:
        crt_router_calibration_file: Path to temporary calibration file
        
    Returns:
        PluginConfig: Plugin configuration with custom values
        
    Example:
        def test_custom_config(crt_router_custom_plugin_config):
            plugin = CRTRouterPlugin(crt_router_custom_plugin_config)
            assert plugin._cfg.default_k == 5  # Custom value
    """
    from mcpgateway.plugins.framework import PluginConfig
    
    return PluginConfig(
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


# ============================================================================
# CATEGORY 4: Plugin Instance Fixtures
# Create actual plugin instances
# ============================================================================

@pytest.fixture
def crt_router_plugin_instance(crt_router_plugin_config):
    """
    Create a CRTRouterPlugin instance (NOT initialized).
    
    This fixture creates a plugin instance but does NOT call initialize().
    Use this for tests that need to control the initialization process
    or test pre-initialization state.
    
    Args:
        crt_router_plugin_config: Plugin configuration
        
    Returns:
        CRTRouterPlugin: Uninitialized plugin instance
        
    Example:
        def test_plugin_before_init(crt_router_plugin_instance):
            assert crt_router_plugin_instance._router is None
    """
    from plugins.crt_router.crt_router import CRTRouterPlugin
    
    return CRTRouterPlugin(crt_router_plugin_config)


@pytest.fixture
async def crt_router_plugin_initialized(crt_router_plugin_config):
    """
    Create and initialize a CRTRouterPlugin instance.
    
    This is an async fixture that creates a plugin, calls initialize(),
    and automatically calls shutdown() after the test completes.
    
    Args:
        crt_router_plugin_config: Plugin configuration
        
    Yields:
        CRTRouterPlugin: Initialized plugin instance
        
    Example:
        @pytest.mark.asyncio
        async def test_initialized_plugin(crt_router_plugin_initialized):
            assert crt_router_plugin_initialized._router is not None
    """
    from plugins.crt_router.crt_router import CRTRouterPlugin
    
    plugin = CRTRouterPlugin(crt_router_plugin_config)
    await plugin.initialize()
    
    yield plugin
    
    # Cleanup: shutdown plugin
    await plugin.shutdown()


# ============================================================================
# CATEGORY 5: Test Payload/Context Fixtures
# Create test inputs for hook testing
# ============================================================================

@pytest.fixture
def crt_router_test_payload():
    """
    Create a sample ToolPreInvokePayload for testing.
    
    This fixture provides a valid payload that can be passed to the
    tool_pre_invoke hook for testing.
    
    Returns:
        ToolPreInvokePayload: Test payload object
        
    Example:
        async def test_hook(crt_router_plugin_initialized, crt_router_test_payload, crt_router_test_context):
            result = await crt_router_plugin_initialized.tool_pre_invoke(
                crt_router_test_payload,
                crt_router_test_context
            )
            assert result.continue_processing
    """
    from mcpgateway.plugins.framework import ToolPreInvokePayload
    
    return ToolPreInvokePayload(
        tool_name="test_tool",
        arguments={"arg1": "value1", "arg2": 42}
    )


@pytest.fixture
def crt_router_test_context():
    """
    Create a sample PluginContext for testing.
    
    This fixture provides a valid context that can be passed to plugin
    hooks for testing.
    
    Returns:
        PluginContext: Test context object
        
    Example:
        async def test_hook_with_context(crt_router_test_context):
            assert crt_router_test_context.global_context.request_id == "test-request-123"
    """
    from mcpgateway.plugins.framework import PluginContext, GlobalContext
    
    return PluginContext(
        global_context=GlobalContext(
            request_id="test-request-123",
            server_id="test-server-456",
            tenant_id="test-tenant-789"
        )
    )


@pytest.fixture
def crt_router_multiple_test_payloads():
    """
    Create multiple test payloads for batch testing.
    
    This fixture provides a list of different payloads to test various
    scenarios in a single test.
    
    Returns:
        List[ToolPreInvokePayload]: List of test payloads
        
    Example:
        async def test_multiple_tools(crt_router_multiple_test_payloads):
            for payload in crt_router_multiple_test_payloads:
                result = await plugin.tool_pre_invoke(payload, context)
                assert result is not None
    """
    from mcpgateway.plugins.framework import ToolPreInvokePayload
    
    return [
        ToolPreInvokePayload(
            tool_name="test_tool_a",
            arguments={"query": "simple search"}
        ),
        ToolPreInvokePayload(
            tool_name="test_tool_b",
            arguments={"data": [1, 2, 3], "operation": "analyze"}
        ),
        ToolPreInvokePayload(
            tool_name="test_tool_c",
            arguments={}  # No arguments
        ),
    ]


# ============================================================================
# CATEGORY 6: Helper Fixtures
# Utility fixtures for common test operations
# ============================================================================

@pytest.fixture
def crt_router_assert_valid_calibration():
    """
    Provide a helper function to assert calibration data is valid.
    
    Returns:
        Callable: Function that validates calibration structure
        
    Example:
        def test_calibration(crt_router_calibration_data, crt_router_assert_valid_calibration):
            crt_router_assert_valid_calibration(crt_router_calibration_data)
    """
    def _assert_valid(calibration_data: Dict[str, Any]) -> None:
        """Assert calibration data has all required fields."""
        required_fields = [
            "version",
            "created_at",
            "difficulty_bins",
            "prime_list",
            "prior_distribution",
            "calibrated_success_tables",
            "tool_embeddings"
        ]
        
        for field in required_fields:
            assert field in calibration_data, f"Missing required field: {field}"
        
        # Additional checks
        assert len(calibration_data["difficulty_bins"]) > 0
        assert len(calibration_data["prime_list"]) > 0
        
        # Prior should sum to ~1.0
        prior_sum = sum(calibration_data["prior_distribution"].values())
        assert 0.99 <= prior_sum <= 1.01, f"Prior sum {prior_sum} != 1.0"
    
    return _assert_valid


@pytest.fixture
def crt_router_mock_semantic_router():
    """
    Provide a mock CRTRouter for testing without real calibration.
    
    This fixture creates a mock router that can be used for testing
    plugin logic without needing actual calibration data or inference.
    
    Returns:
        MagicMock: Mock CRTRouter instance
        
    Example:
        def test_plugin_uses_router(crt_router_plugin_instance, crt_router_mock_semantic_router, monkeypatch):
            monkeypatch.setattr(crt_router_plugin_instance, '_router', crt_router_mock_semantic_router)
            # Now test plugin behavior with mock router
    """
    from unittest.mock import MagicMock
    
    mock_router = MagicMock()
    mock_router.calibration = {"version": "1.0.0", "loaded": True}
    mock_router.rank_tools.return_value = []
    
    return mock_router

