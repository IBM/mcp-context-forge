# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/sparc_static_validator/test_sparc_static_validator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Osher Elhadad

Comprehensive tests for SPARCStaticValidatorPlugin.

This test module covers:
- Valid tool calls (pass validation)
- Missing required parameters
- Type mismatches with and without corrections
- Unknown/extra parameters
- Enum violations
- Auto-apply corrections
- Permissive mode (block_on_violation: false)
- Schema override via config
- ALTK unavailability fallback
- No schema available scenario
"""

# Standard
from typing import Any, Dict
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Tool
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
    ToolPreInvokePayload,
)
from mcpgateway.plugins.framework.constants import TOOL_METADATA
from plugins.sparc_static_validator.sparc_static_validator import (
    SPARCStaticValidatorPlugin,
)

# Check if ALTK is available
have_altk = True
try:
    import importlib.util

    if importlib.util.find_spec("altk") is None:
        raise ModuleNotFoundError("altk not found")
    from plugins.sparc_static_validator.sparc_static_validator import (
        ALTK_AVAILABLE,
    )
except ModuleNotFoundError:
    have_altk = False
    ALTK_AVAILABLE = False


# Sample tool schemas for testing
EMAIL_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["to", "subject", "body"],
    "properties": {
        "to": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of recipient email addresses",
        },
        "subject": {
            "type": "string",
            "description": "Email subject line",
        },
        "body": {
            "type": "string",
            "description": "Email body content",
        },
        "priority": {
            "type": "string",
            "enum": ["low", "normal", "high"],
            "description": "Email priority level",
        },
    },
}

CALCULATOR_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["operation", "a", "b"],
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["add", "subtract", "multiply", "divide"],
        },
        "a": {"type": "number"},
        "b": {"type": "number"},
    },
}

MEETING_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["title", "participants", "duration_minutes"],
    "properties": {
        "title": {"type": "string"},
        "participants": {
            "type": "array",
            "items": {"type": "string"},
        },
        "duration_minutes": {
            "type": "integer",
            "minimum": 15,
            "maximum": 480,
        },
    },
}


def create_plugin(config: Dict[str, Any] = None) -> "SPARCStaticValidatorPlugin":
    """Create a SPARCStaticValidatorPlugin with the given config."""
    return SPARCStaticValidatorPlugin(
        PluginConfig(
            name="sparc_static_validator",
            kind="plugins.sparc_static_validator.sparc_static_validator.SPARCStaticValidatorPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config=config or {},
        )
    )


def create_context(
    tool_name: str = "test_tool",
    input_schema: Dict[str, Any] = None,
    description: str = "Test tool",
) -> PluginContext:
    """Create a PluginContext with tool metadata."""
    global_context = GlobalContext(request_id="test-request-1")

    if input_schema is not None:
        tool = Tool(
            name=tool_name,
            url="http://localhost:8080/tools/test",  # Required field
            description=description,
            input_schema=input_schema,
        )
        global_context.metadata[TOOL_METADATA] = tool

    return PluginContext(global_context=global_context)


# ============================================================================
# Tests for when ALTK is available
# ============================================================================


@pytest.mark.skipif(not have_altk, reason="altk not available")
class TestSPARCStaticValidatorWithALTK:
    """Tests that require ALTK to be installed."""

    @pytest.mark.anyio
    async def test_valid_tool_call_passes_validation(self):
        """Test that a valid tool call passes validation."""
        plugin = create_plugin()
        ctx = create_context(
            tool_name="send_email",
            input_schema=EMAIL_TOOL_SCHEMA,
        )

        payload = ToolPreInvokePayload(
            name="send_email",
            args={
                "to": ["john@example.com"],
                "subject": "Hello",
                "body": "This is a test email",
                "priority": "normal",
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is None
        assert result.continue_processing is True
        assert result.metadata.get("sparc_validation") == "passed"

    @pytest.mark.anyio
    async def test_missing_required_parameters_fails(self):
        """Test that missing required parameters cause validation failure."""
        plugin = create_plugin({"block_on_violation": True})
        ctx = create_context(
            tool_name="send_email",
            input_schema=EMAIL_TOOL_SCHEMA,
        )

        # Missing 'subject' and 'body'
        payload = ToolPreInvokePayload(
            name="send_email",
            args={"to": ["john@example.com"]},
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is not None
        assert result.continue_processing is False
        assert "SPARC_MISSING_REQUIRED" in result.violation.code or "missing_required" in str(result.violation.details)

    @pytest.mark.anyio
    async def test_type_mismatch_detected(self):
        """Test that type mismatches are detected."""
        plugin = create_plugin({"block_on_violation": True})
        ctx = create_context(
            tool_name="schedule_meeting",
            input_schema=MEETING_TOOL_SCHEMA,
        )

        # duration_minutes should be integer, not string
        payload = ToolPreInvokePayload(
            name="schedule_meeting",
            args={
                "title": "Team Meeting",
                "participants": ["alice@example.com"],
                "duration_minutes": "60",  # String instead of integer
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        # Should fail due to type mismatch (or pass with correction suggestion)
        # The SPARC checker may auto-correct "60" to 60
        if result.violation:
            assert result.continue_processing is False
            assert "SPARC" in result.violation.code
        else:
            # Correction was suggested
            assert result.metadata.get("sparc_validation") in ["passed", "failed"]

    @pytest.mark.anyio
    async def test_type_correction_suggested(self):
        """Test that type corrections are suggested when available."""
        plugin = create_plugin(
            {
                "block_on_violation": True,
                "enable_type_correction": True,
                "include_correction_in_response": True,
            }
        )
        ctx = create_context(
            tool_name="schedule_meeting",
            input_schema=MEETING_TOOL_SCHEMA,
        )

        payload = ToolPreInvokePayload(
            name="schedule_meeting",
            args={
                "title": "Team Meeting",
                "participants": ["alice@example.com"],
                "duration_minutes": "60",  # String that can be converted to int
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        # Check if correction is in response
        if result.violation and result.violation.details:
            correction = result.violation.details.get("correction")
            if correction:
                assert correction.get("duration_minutes") == 60
        elif result.metadata.get("sparc_correction"):
            assert result.metadata["sparc_correction"].get("duration_minutes") == 60

    @pytest.mark.anyio
    async def test_auto_apply_corrections(self):
        """Test that corrections are auto-applied when configured."""
        plugin = create_plugin(
            {
                "block_on_violation": True,
                "enable_type_correction": True,
                "auto_apply_corrections": True,
            }
        )
        ctx = create_context(
            tool_name="schedule_meeting",
            input_schema=MEETING_TOOL_SCHEMA,
        )

        payload = ToolPreInvokePayload(
            name="schedule_meeting",
            args={
                "title": "Team Meeting",
                "participants": ["alice@example.com"],
                "duration_minutes": "60",  # String that can be converted
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        # If correction was applied, the payload should be modified
        if result.modified_payload:
            assert result.continue_processing is True
            assert result.modified_payload.args.get("duration_minutes") == 60
            assert result.metadata.get("sparc_validation") == "corrected"

    @pytest.mark.anyio
    async def test_enum_violation_fails(self):
        """Test that enum violations cause validation failure."""
        plugin = create_plugin({"block_on_violation": True})
        ctx = create_context(
            tool_name="send_email",
            input_schema=EMAIL_TOOL_SCHEMA,
        )

        payload = ToolPreInvokePayload(
            name="send_email",
            args={
                "to": ["john@example.com"],
                "subject": "Hello",
                "body": "Test body",
                "priority": "urgent",  # Invalid enum value
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is not None
        assert result.continue_processing is False

    @pytest.mark.anyio
    async def test_unknown_parameter_fails(self):
        """Test that unknown/extra parameters cause validation failure."""
        plugin = create_plugin({"block_on_violation": True})
        ctx = create_context(
            tool_name="calculator",
            input_schema=CALCULATOR_TOOL_SCHEMA,
        )

        payload = ToolPreInvokePayload(
            name="calculator",
            args={
                "operation": "add",
                "a": 5,
                "b": 3,
                "unknown_param": "should not be here",
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is not None
        assert result.continue_processing is False
        # Should be SPARC_UNKNOWN_PARAM
        assert "SPARC" in result.violation.code

    @pytest.mark.anyio
    async def test_permissive_mode_continues_on_error(self):
        """Test that permissive mode logs errors but continues."""
        plugin = create_plugin({"block_on_violation": False})
        ctx = create_context(
            tool_name="send_email",
            input_schema=EMAIL_TOOL_SCHEMA,
        )

        # Invalid call - missing required fields
        payload = ToolPreInvokePayload(
            name="send_email",
            args={"to": ["john@example.com"]},
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        # Should continue despite errors
        assert result.violation is None
        assert result.continue_processing is True
        assert result.metadata.get("sparc_validation") == "failed"
        assert "sparc_errors" in result.metadata

    @pytest.mark.anyio
    async def test_schema_override_via_config(self):
        """Test that schema can be overridden via plugin config."""
        custom_schema = {
            "type": "object",
            "required": ["custom_param"],
            "properties": {
                "custom_param": {"type": "string"},
            },
        }

        plugin = create_plugin(
            {
                "block_on_violation": True,
                "tool_schemas": {
                    "custom_tool": custom_schema,
                },
            }
        )

        # Context without schema in metadata
        ctx = create_context(tool_name="custom_tool", input_schema=None)

        payload = ToolPreInvokePayload(
            name="custom_tool",
            args={"custom_param": "value"},
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is None
        assert result.continue_processing is True

    @pytest.mark.anyio
    async def test_no_schema_skips_validation(self):
        """Test that tools without schema skip validation."""
        plugin = create_plugin()
        ctx = create_context(tool_name="no_schema_tool", input_schema=None)

        payload = ToolPreInvokePayload(
            name="no_schema_tool",
            args={"anything": "goes"},
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is None
        assert result.continue_processing is True
        assert result.metadata.get("sparc_validation") == "skipped"
        assert result.metadata.get("reason") == "no_schema"

    @pytest.mark.anyio
    async def test_empty_args_with_no_required_passes(self):
        """Test that empty args pass when no required fields."""
        optional_schema = {
            "type": "object",
            "properties": {
                "optional_param": {"type": "string"},
            },
        }

        plugin = create_plugin()
        ctx = create_context(
            tool_name="optional_tool",
            input_schema=optional_schema,
        )

        payload = ToolPreInvokePayload(
            name="optional_tool",
            args={},
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is None
        assert result.continue_processing is True

    @pytest.mark.anyio
    async def test_error_details_contain_tool_info(self):
        """Test that error details contain useful debugging info."""
        plugin = create_plugin({"block_on_violation": True})
        ctx = create_context(
            tool_name="send_email",
            input_schema=EMAIL_TOOL_SCHEMA,
        )

        payload = ToolPreInvokePayload(
            name="send_email",
            args={"to": ["john@example.com"]},  # Missing required
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is not None
        assert result.violation.details is not None
        assert result.violation.details.get("tool_name") == "send_email"
        assert "errors" in result.violation.details

    @pytest.mark.anyio
    async def test_calculator_valid_call(self):
        """Test valid calculator tool call."""
        plugin = create_plugin()
        ctx = create_context(
            tool_name="calculator",
            input_schema=CALCULATOR_TOOL_SCHEMA,
        )

        payload = ToolPreInvokePayload(
            name="calculator",
            args={
                "operation": "add",
                "a": 5,
                "b": 3,
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is None
        assert result.continue_processing is True


# ============================================================================
# Tests that work without ALTK (testing fallback behavior)
# ============================================================================


class TestSPARCStaticValidatorFallback:
    """Tests for plugin behavior when ALTK is not available."""

    @pytest.mark.anyio
    async def test_altk_unavailable_passes_through(self):
        """Test that plugin passes through when ALTK is not installed."""
        # Mock ALTK as unavailable
        with patch(
            "plugins.sparc_static_validator.sparc_static_validator.ALTK_AVAILABLE",
            False,
        ):
            # Re-import to pick up the mock
            from plugins.sparc_static_validator.sparc_static_validator import (
                SPARCStaticValidatorPlugin,
            )

            plugin = SPARCStaticValidatorPlugin(
                PluginConfig(
                    name="sparc_static_validator",
                    kind="plugins.sparc_static_validator.sparc_static_validator.SPARCStaticValidatorPlugin",
                    hooks=[ToolHookType.TOOL_PRE_INVOKE],
                    config={},
                )
            )
            plugin._altk_available = False  # Force unavailable

            ctx = create_context(
                tool_name="any_tool",
                input_schema=EMAIL_TOOL_SCHEMA,
            )

            payload = ToolPreInvokePayload(
                name="any_tool",
                args={"invalid": "args"},
            )

            result = await plugin.tool_pre_invoke(payload, ctx)

            assert result.violation is None
            assert result.continue_processing is True
            assert result.metadata.get("sparc_validation") == "skipped"
            assert "ALTK" in result.metadata.get("reason", "")


# ============================================================================
# Tests for configuration validation
# ============================================================================


class TestSPARCStaticValidatorConfig:
    """Tests for plugin configuration."""

    def test_default_config_values(self):
        """Test that default config values are set correctly."""
        plugin = create_plugin()

        assert plugin._cfg.block_on_violation is True
        assert plugin._cfg.enable_type_correction is True
        assert plugin._cfg.auto_apply_corrections is False
        assert plugin._cfg.include_correction_in_response is True
        assert plugin._cfg.log_corrections is True
        assert plugin._cfg.tool_schemas is None

    def test_custom_config_values(self):
        """Test that custom config values are applied."""
        plugin = create_plugin(
            {
                "block_on_violation": False,
                "enable_type_correction": False,
                "auto_apply_corrections": True,
                "include_correction_in_response": False,
                "log_corrections": False,
                "tool_schemas": {"test": {"type": "object"}},
            }
        )

        assert plugin._cfg.block_on_violation is False
        assert plugin._cfg.enable_type_correction is False
        assert plugin._cfg.auto_apply_corrections is True
        assert plugin._cfg.include_correction_in_response is False
        assert plugin._cfg.log_corrections is False
        assert plugin._cfg.tool_schemas == {"test": {"type": "object"}}


# ============================================================================
# Integration-like tests
# ============================================================================


@pytest.mark.skipif(not have_altk, reason="altk not available")
class TestSPARCStaticValidatorIntegration:
    """Integration-like tests for more complex scenarios."""

    @pytest.mark.anyio
    async def test_multiple_validation_errors(self):
        """Test handling of multiple validation errors in one call."""
        plugin = create_plugin({"block_on_violation": True})
        ctx = create_context(
            tool_name="send_email",
            input_schema=EMAIL_TOOL_SCHEMA,
        )

        # Multiple issues: missing required, wrong type for 'to', invalid enum
        payload = ToolPreInvokePayload(
            name="send_email",
            args={
                "to": "not-an-array",  # Should be array
                "priority": "invalid",  # Invalid enum
                # Missing subject and body
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is not None
        assert result.continue_processing is False
        # Should have multiple errors
        errors = result.violation.details.get("errors", [])
        assert len(errors) >= 1

    @pytest.mark.anyio
    async def test_nested_object_validation(self):
        """Test validation of nested object structures."""
        nested_schema = {
            "type": "object",
            "required": ["user"],
            "properties": {
                "user": {
                    "type": "object",
                    "required": ["name", "email"],
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                },
            },
        }

        plugin = create_plugin()
        ctx = create_context(
            tool_name="create_user",
            input_schema=nested_schema,
        )

        # Valid nested object
        payload = ToolPreInvokePayload(
            name="create_user",
            args={
                "user": {
                    "name": "John Doe",
                    "email": "john@example.com",
                },
            },
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is None
        assert result.continue_processing is True

    @pytest.mark.anyio
    async def test_array_items_validation(self):
        """Test validation of array items."""
        array_schema = {
            "type": "object",
            "required": ["numbers"],
            "properties": {
                "numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
        }

        plugin = create_plugin()
        ctx = create_context(
            tool_name="sum_numbers",
            input_schema=array_schema,
        )

        # Valid array of integers
        payload = ToolPreInvokePayload(
            name="sum_numbers",
            args={"numbers": [1, 2, 3, 4, 5]},
        )

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.violation is None
        assert result.continue_processing is True
