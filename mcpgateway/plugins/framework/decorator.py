# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/decorator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Hook decorator for dynamically registering plugin hooks.

This module provides decorators for marking plugin methods as hook handlers.
Plugins can use these decorators to:
1. Override the default hook naming convention
2. Register custom hooks not in the standard framework

Examples:
    Override hook method name::

        class MyPlugin(Plugin):
            @hook(ToolHookType.TOOL_PRE_INVOKE)
            def custom_name_for_tool_hook(self, payload, context):
                # This gets called for tool_pre_invoke even though
                # the method name doesn't match
                return ToolPreInvokeResult(continue_processing=True)

    Register a completely new hook type::

        class MyPlugin(Plugin):
            @hook("custom_pre_process", CustomPayload, CustomResult)
            def my_custom_hook(self, payload, context):
                # This registers a new hook type dynamically
                return CustomResult(continue_processing=True)

    Use default convention (no decorator needed)::

        class MyPlugin(Plugin):
            def tool_pre_invoke(self, payload, context):
                # Automatically recognized by naming convention
                return ToolPreInvokeResult(continue_processing=True)
"""

# Standard
from typing import Callable, Optional, Type, TypeVar

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult

# Attribute name for storing hook metadata on functions
_HOOK_METADATA_ATTR = "_plugin_hook_metadata"

# Type vars for type hints
P = TypeVar("P", bound=PluginPayload)  # Payload type
R = TypeVar("R", bound=PluginResult)  # Result type


class HookMetadata:
    """Metadata stored on decorated hook methods.

    Attributes:
        hook_type: The hook type identifier (e.g., 'tool_pre_invoke')
        payload_type: Optional payload class for hook registration
        result_type: Optional result class for hook registration
    """

    def __init__(
        self,
        hook_type: str,
        payload_type: Optional[Type[BaseModel]] = None,
        result_type: Optional[Type[BaseModel]] = None,
    ):
        """Initialize hook metadata.

        Args:
            hook_type: The hook type identifier
            payload_type: Optional payload class for registering new hooks
            result_type: Optional result class for registering new hooks
        """
        self.hook_type = hook_type
        self.payload_type = payload_type
        self.result_type = result_type


def hook(
    hook_type: str,
    payload_type: Optional[Type[P]] = None,
    result_type: Optional[Type[R]] = None,
) -> Callable[[Callable], Callable]:
    """Decorator to mark a method as a plugin hook handler.

    This decorator attaches metadata to a method so the Plugin class can
    discover it during initialization and register it with the appropriate
    hook type.

    Args:
        hook_type: The hook type identifier (e.g., 'tool_pre_invoke')
        payload_type: Optional payload class for registering new hook types
        result_type: Optional result class for registering new hook types

    Returns:
        Decorator function that marks the method with hook metadata

    Examples:
        Override method name::

            @hook(ToolHookType.TOOL_PRE_INVOKE)
            def my_custom_method_name(self, payload, context):
                return ToolPreInvokeResult(continue_processing=True)

        Register new hook type::

            @hook("email_pre_send", EmailPayload, EmailResult)
            def handle_email(self, payload, context):
                return EmailResult(continue_processing=True)
    """

    def decorator(func: Callable) -> Callable:
        """Inner decorator that attaches metadata to the function.

        Args:
            func: The function to decorate

        Returns:
            The same function with metadata attached
        """
        # Store metadata on the function object
        metadata = HookMetadata(hook_type, payload_type, result_type)
        setattr(func, _HOOK_METADATA_ATTR, metadata)
        return func

    return decorator


def get_hook_metadata(func: Callable) -> Optional[HookMetadata]:
    """Get hook metadata from a decorated function.

    Args:
        func: The function to check

    Returns:
        HookMetadata if the function is decorated, None otherwise

    Examples:
        >>> @hook("test_hook")
        ... def test_func():
        ...     pass
        >>> metadata = get_hook_metadata(test_func)
        >>> metadata.hook_type
        'test_hook'
        >>> get_hook_metadata(lambda: None) is None
        True
    """
    return getattr(func, _HOOK_METADATA_ATTR, None)


def has_hook_metadata(func: Callable) -> bool:
    """Check if a function has hook metadata.

    Args:
        func: The function to check

    Returns:
        True if the function is decorated with @hook, False otherwise

    Examples:
        >>> @hook("test_hook")
        ... def decorated():
        ...     pass
        >>> has_hook_metadata(decorated)
        True
        >>> has_hook_metadata(lambda: None)
        False
    """
    return hasattr(func, _HOOK_METADATA_ATTR)
