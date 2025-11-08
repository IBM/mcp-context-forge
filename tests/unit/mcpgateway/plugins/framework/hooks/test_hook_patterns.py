# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/hooks/test_hook_patterns.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests demonstrating three hook patterns in the plugin framework:
1. Convention-based: method name matches hook type
2. Decorator-based: @hook decorator with custom method name
3. Custom hook: @hook decorator with new hook type + payload/result types
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginContext,
    GlobalContext,
    PluginManager,
    PluginPayload,
    PluginResult,
    ToolHookType,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)
from mcpgateway.plugins.framework.decorator import hook


# ========== Custom Hook Definition ==========
class EmailPayload(PluginPayload):
    """Payload for email hook."""

    recipient: str
    subject: str
    body: str


class EmailResult(PluginResult[EmailPayload]):
    """Result for email hook."""

    pass


# ========== Demo Plugin with All Three Patterns ==========
class DemoPlugin(Plugin):
    """Demo plugin showing all three hook patterns."""

    # Pattern 1: Convention-based (method name matches hook type)
    async def tool_pre_invoke(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> ToolPreInvokeResult:
        """Pattern 1: Convention-based hook.

        This method is found automatically because its name matches
        the hook type 'tool_pre_invoke'.
        """
        # Modify the payload
        modified_payload = ToolPreInvokePayload(
            name=payload.name,
            args={**payload.args, "pattern": "convention"},
            headers=payload.headers,
        )

        return ToolPreInvokeResult(
            modified_payload=modified_payload,
            metadata={"pattern": "convention", "hook": "tool_pre_invoke"}
        )

    # Pattern 2: Decorator-based with custom method name
    @hook(ToolHookType.TOOL_POST_INVOKE)
    async def my_custom_tool_post_handler(
        self, payload: ToolPostInvokePayload, context: PluginContext
    ) -> ToolPostInvokeResult:
        """Pattern 2: Decorator-based hook with custom method name.

        This method is found via the @hook decorator even though
        the method name doesn't match the hook type.
        """
        # Modify the result
        modified_result = {**payload.result, "pattern": "decorator"} if isinstance(payload.result, dict) else payload.result

        modified_payload = ToolPostInvokePayload(
            name=payload.name,
            result=modified_result,
        )

        return ToolPostInvokeResult(
            modified_payload=modified_payload,
            metadata={"pattern": "decorator", "hook": "tool_post_invoke"}
        )

    # Pattern 3: Custom hook with payload and result types
    @hook("email_pre_send", EmailPayload, EmailResult)
    async def validate_email(
        self, payload: EmailPayload, context: PluginContext
    ) -> EmailResult:
        """Pattern 3: Custom hook with new hook type.

        This registers a completely new hook type 'email_pre_send'
        with its own payload and result types.
        """
        # Validate email
        if "@" not in payload.recipient:
            modified_payload = EmailPayload(
                recipient=f"{payload.recipient}@example.com",
                subject=payload.subject,
                body=payload.body,
            )
            return EmailResult(
                modified_payload=modified_payload,
                metadata={"pattern": "custom", "hook": "email_pre_send", "fixed_email": True}
            )

        return EmailResult(
            continue_processing=True,
            metadata={"pattern": "custom", "hook": "email_pre_send"}
        )


# ========== Pytest Tests ==========
@pytest.mark.asyncio
async def test_pattern_1_convention_based_hook():
    """Test Pattern 1: Convention-based hook (method name matches hook type)."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/test_hook_patterns_config.yaml")
    await manager.initialize()

    # Create payload for tool_pre_invoke
    payload = ToolPreInvokePayload(
        name="my_calculator",
        args={"operation": "add", "a": 5, "b": 3}
    )

    global_context = GlobalContext(request_id="test-1")

    # Invoke the hook
    result, contexts = await manager.invoke_hook(
        ToolHookType.TOOL_PRE_INVOKE,
        payload,
        global_context=global_context
    )

    # Assertions
    assert result is not None
    assert result.continue_processing is True
    assert result.modified_payload is not None
    assert result.modified_payload.name == "my_calculator"
    assert result.modified_payload.args["operation"] == "add"
    assert result.modified_payload.args["a"] == 5
    assert result.modified_payload.args["b"] == 3
    assert result.modified_payload.args["pattern"] == "convention"  # Added by hook
    assert result.metadata is not None
    assert result.metadata["pattern"] == "convention"
    assert result.metadata["hook"] == "tool_pre_invoke"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_pattern_2_decorator_based_hook():
    """Test Pattern 2: Decorator-based hook with custom method name."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/test_hook_patterns_config.yaml")
    await manager.initialize()

    # Create payload for tool_post_invoke
    payload = ToolPostInvokePayload(
        name="my_calculator",
        result={"sum": 8, "status": "success"}
    )

    global_context = GlobalContext(request_id="test-2")

    # Invoke the hook
    result, contexts = await manager.invoke_hook(
        ToolHookType.TOOL_POST_INVOKE,
        payload,
        global_context=global_context
    )

    # Assertions
    assert result is not None
    assert result.continue_processing is True
    assert result.modified_payload is not None
    assert result.modified_payload.name == "my_calculator"
    assert result.modified_payload.result["sum"] == 8
    assert result.modified_payload.result["status"] == "success"
    assert result.modified_payload.result["pattern"] == "decorator"  # Added by hook
    assert result.metadata is not None
    assert result.metadata["pattern"] == "decorator"
    assert result.metadata["hook"] == "tool_post_invoke"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_pattern_3_custom_hook_valid_email():
    """Test Pattern 3: Custom hook with new hook type (valid email)."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/test_hook_patterns_config.yaml")
    await manager.initialize()

    # Test with valid email
    payload = EmailPayload(
        recipient="user@example.com",
        subject="Test Email",
        body="This is a test."
    )

    global_context = GlobalContext(request_id="test-3a")

    result, contexts = await manager.invoke_hook(
        "email_pre_send",
        payload,
        global_context=global_context
    )

    # Assertions
    assert result is not None
    assert result.continue_processing is True
    assert result.modified_payload is None  # No modification needed for valid email
    assert result.metadata is not None
    assert result.metadata["pattern"] == "custom"
    assert result.metadata["hook"] == "email_pre_send"
    assert "fixed_email" not in result.metadata  # Email was already valid

    await manager.shutdown()


@pytest.mark.asyncio
async def test_pattern_3_custom_hook_invalid_email():
    """Test Pattern 3: Custom hook with new hook type (invalid email gets fixed)."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/test_hook_patterns_config.yaml")
    await manager.initialize()

    # Test with invalid email (missing @)
    payload = EmailPayload(
        recipient="invalid-email",
        subject="Test Email 2",
        body="This email address needs fixing."
    )

    global_context = GlobalContext(request_id="test-3b")

    result, contexts = await manager.invoke_hook(
        "email_pre_send",
        payload,
        global_context=global_context
    )

    # Assertions
    assert result is not None
    assert result.continue_processing is True
    assert result.modified_payload is not None
    assert result.modified_payload.recipient == "invalid-email@example.com"  # Fixed by hook
    assert result.modified_payload.subject == "Test Email 2"
    assert result.modified_payload.body == "This email address needs fixing."
    assert result.metadata is not None
    assert result.metadata["pattern"] == "custom"
    assert result.metadata["hook"] == "email_pre_send"
    assert result.metadata["fixed_email"] is True  # Hook fixed the email

    await manager.shutdown()


@pytest.mark.asyncio
async def test_all_three_patterns_in_sequence():
    """Test all three patterns work together in the same plugin manager."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/test_hook_patterns_config.yaml")
    await manager.initialize()

    global_context = GlobalContext(request_id="test-all")

    # Test Pattern 1: Convention-based
    payload1 = ToolPreInvokePayload(
        name="test_tool",
        args={"param": "value"}
    )
    result1, _ = await manager.invoke_hook(
        ToolHookType.TOOL_PRE_INVOKE,
        payload1,
        global_context=global_context
    )
    assert result1.modified_payload.args["pattern"] == "convention"

    # Test Pattern 2: Decorator-based
    payload2 = ToolPostInvokePayload(
        name="test_tool",
        result={"data": "output"}
    )
    result2, _ = await manager.invoke_hook(
        ToolHookType.TOOL_POST_INVOKE,
        payload2,
        global_context=global_context
    )
    assert result2.modified_payload.result["pattern"] == "decorator"

    # Test Pattern 3: Custom hook
    payload3 = EmailPayload(
        recipient="test",
        subject="Test",
        body="Test"
    )
    result3, _ = await manager.invoke_hook(
        "email_pre_send",
        payload3,
        global_context=global_context
    )
    assert result3.modified_payload.recipient == "test@example.com"

    await manager.shutdown()
