# -*- coding: utf-8 -*-
"""Pydantic models for plugins.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

This module implements the pydantic models associated with
the base plugin layer including configurations, and contexts.
"""

# Standard
from typing import Any, Generic, Optional, TypeVar

# First-Party
from mcpgateway.models import PromptResult
from mcpgateway.plugins.framework.models import PluginViolation

T = TypeVar("T")


class PromptPrehookPayload:
    """A prompt payload for a prompt prehook.

    Examples:
        >>> payload = PromptPrehookPayload("test_prompt", {"user": "alice"})
        >>> payload.name
        'test_prompt'
        >>> payload.args
        {'user': 'alice'}
        >>> payload2 = PromptPrehookPayload("empty", None)
        >>> payload2.args
        {}
    """

    def __init__(self, name: str, args: Optional[dict[str, str]]):
        """Initialize a prompt prehook payload.

        Args:
            name: The prompt name.
            args: The prompt arguments for rendering.

        Examples:
            >>> p = PromptPrehookPayload("greeting", {"name": "Bob", "time": "morning"})
            >>> p.name
            'greeting'
            >>> p.args["name"]
            'Bob'
        """
        self.name = name
        self.args = args or {}


class PromptPosthookPayload:
    """A prompt payload for a prompt posthook.

    Examples:
        >>> from mcpgateway.models import PromptResult, Message, TextContent
        >>> msg = Message(role="user", content=TextContent(type="text", text="Hello World"))
        >>> result = PromptResult(messages=[msg])
        >>> payload = PromptPosthookPayload("greeting", result)
        >>> payload.name
        'greeting'
        >>> payload.result.messages[0].content.text
        'Hello World'
    """

    def __init__(self, name: str, result: PromptResult):
        """Initialize a prompt posthook payload.

        Args:
            name: The prompt name.
            result: The prompt Prompt Result.

        Examples:
            >>> from mcpgateway.models import PromptResult, Message, TextContent
            >>> msg = Message(role="assistant", content=TextContent(type="text", text="Test output"))
            >>> r = PromptResult(messages=[msg])
            >>> p = PromptPosthookPayload("test", r)
            >>> p.name
            'test'
        """
        self.name = name
        self.result = result


class PluginResult(Generic[T]):
    """A plugin result.

    Examples:
        >>> result = PluginResult()
        >>> result.continue_processing
        True
        >>> result.metadata
        {}
        >>> from mcpgateway.plugins.framework.models import PluginViolation
        >>> violation = PluginViolation(
        ...     reason="Test", description="Test desc", code="TEST", details={}
        ... )
        >>> result2 = PluginResult(continue_processing=False, violation=violation)
        >>> result2.continue_processing
        False
        >>> result2.violation.code
        'TEST'
    """

    def __init__(self, continue_processing: bool = True, modified_payload: Optional[T] = None, violation: Optional[PluginViolation] = None, metadata: Optional[dict[str, Any]] = None):
        """Initialize a plugin result object.

        Args:
            continue_processing (bool): Whether to stop processing.
            modified_payload (Optional[Any]): The modified payload if the plugin is a transformer.
            violation (Optional[PluginViolation]): violation object.
            metadata (Optional[dict[str, Any]]): additional metadata.

        Examples:
            >>> r = PluginResult(metadata={"key": "value"})
            >>> r.metadata["key"]
            'value'
            >>> r2 = PluginResult(continue_processing=False)
            >>> r2.continue_processing
            False
        """
        self.continue_processing = continue_processing
        self.modified_payload = modified_payload
        self.violation = violation
        self.metadata = metadata or {}


PromptPrehookResult = PluginResult[PromptPrehookPayload]
PromptPosthookResult = PluginResult[PromptPosthookPayload]


class ToolPreInvokePayload:
    """A tool payload for a tool pre-invoke hook.

    Examples:
        >>> payload = ToolPreInvokePayload("test_tool", {"input": "data"})
        >>> payload.name
        'test_tool'
        >>> payload.args
        {'input': 'data'}
        >>> payload2 = ToolPreInvokePayload("empty", None)
        >>> payload2.args
        {}
    """

    def __init__(self, name: str, args: Optional[dict[str, Any]]):
        """Initialize a tool pre-invoke payload.

        Args:
            name: The tool name.
            args: The tool arguments for invocation.

        Examples:
            >>> p = ToolPreInvokePayload("calculator", {"operation": "add", "a": 5, "b": 3})
            >>> p.name
            'calculator'
            >>> p.args["operation"]
            'add'
        """
        self.name = name
        self.args = args or {}


class ToolPostInvokePayload:
    """A tool payload for a tool post-invoke hook.

    Examples:
        >>> payload = ToolPostInvokePayload("calculator", {"result": 8, "status": "success"})
        >>> payload.name
        'calculator'
        >>> payload.result
        {'result': 8, 'status': 'success'}
    """

    def __init__(self, name: str, result: Any):
        """Initialize a tool post-invoke payload.

        Args:
            name: The tool name.
            result: The tool invocation result.

        Examples:
            >>> p = ToolPostInvokePayload("analyzer", {"confidence": 0.95, "sentiment": "positive"})
            >>> p.name
            'analyzer'
            >>> p.result["confidence"]
            0.95
        """
        self.name = name
        self.result = result


ToolPreInvokeResult = PluginResult[ToolPreInvokePayload]
ToolPostInvokeResult = PluginResult[ToolPostInvokePayload]


class GlobalContext:
    """The global context, which shared across all plugins.

    Examples:
        >>> ctx = GlobalContext("req-123")
        >>> ctx.request_id
        'req-123'
        >>> ctx.user is None
        True
        >>> ctx2 = GlobalContext("req-456", user="alice", tenant_id="tenant1")
        >>> ctx2.user
        'alice'
        >>> ctx2.tenant_id
        'tenant1'
    """

    def __init__(self, request_id: str, user: Optional[str] = None, tenant_id: Optional[str] = None, server_id: Optional[str] = None) -> None:
        """Initialize a global context.

        Args:
            request_id (str): ID of the HTTP request.
            user (str): user ID associated with the request.
            tenant_id (str): tenant ID.
            server_id (str): server ID.

        Examples:
            >>> c = GlobalContext("123", server_id="srv1")
            >>> c.request_id
            '123'
            >>> c.server_id
            'srv1'
        """
        self.request_id = request_id
        self.user = user
        self.tenant_id = tenant_id
        self.server_id = server_id


class PluginContext(GlobalContext):
    """The plugin's context, which lasts a request lifecycle.

    Attributes:
       metadata: context metadata.
       state:  the inmemory state of the request.
    """

    def __init__(self, gcontext: Optional[GlobalContext] = None) -> None:
        """Initialize a plugin context.

        Args:
            gcontext: the global context object.
        """
        if gcontext:
            super().__init__(gcontext.request_id, gcontext.user, gcontext.tenant_id, gcontext.server_id)
        self.state: dict[str, Any] = {}  # In-memory state
        self.metadata: dict[str, Any] = {}

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get value from shared state.

        Args:
            key: The key to access the shared state.
            default: A default value if one doesn't exist.

        Returns:
            The state value.
        """
        return self.state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        """Set value in shared state.

        Args:
            key: the key to add to the state.
            value: the value to add to the state.
        """
        self.state[key] = value

    async def cleanup(self) -> None:
        """Cleanup context resources."""
        self.state.clear()
        self.metadata.clear()


PluginContextTable = dict[str, PluginContext]


class PluginViolationError(Exception):
    """A plugin violation error.

    Attributes:
        violation (PluginViolation): the plugin violation.
        message (str): the plugin violation reason.
    """

    def __init__(self, message: str, violation: PluginViolation | None = None):
        """Initialize a plugin violation error.

        Args:
            message: the reason for the violation error.
            violation: the plugin violation object details.
        """
        self.message = message
        self.violation = violation
        super().__init__(self.message)
