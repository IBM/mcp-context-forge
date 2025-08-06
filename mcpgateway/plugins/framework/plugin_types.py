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
    """A prompt payload for a prompt prehook."""

    def __init__(self, name: str, args: Optional[dict[str, str]]):
        """Initialize a prompt prehook payload.

        Args:
            name: The prompt name.
            args: The prompt arguments for rendering.
        """
        self.name = name
        self.args = args or {}


class PromptPosthookPayload:
    """A prompt payload for a prompt posthook."""

    def __init__(self, name: str, result: PromptResult):
        """Initialize a prompt posthook payload.

        Args:
            name: The prompt name.
            result: The prompt Prompt Result.
        """
        self.name = name
        self.result = result


class PluginResult(Generic[T]):
    """A plugin result."""

    def __init__(self, continue_processing: bool = True, modified_payload: Optional[T] = None, violation: Optional[PluginViolation] = None, metadata: Optional[dict[str, Any]] = None):
        """Initialize a plugin result object.

        Args:
            continue_processing (bool): Whether to stop processing.
            modified_payload (Optional[Any]): The modified payload if the plugin is a transformer.
            violation (Optional[PluginViolation]): violation object.
            metadata (Optional[dict[str, Any]]): additional metadata.
        """
        self.continue_processing = continue_processing
        self.modified_payload = modified_payload
        self.violation = violation
        self.metadata = metadata or {}


PromptPrehookResult = PluginResult[PromptPrehookPayload]
PromptPosthookResult = PluginResult[PromptPosthookPayload]


class GlobalContext:
    """The global context, which shared across all plugins."""

    def __init__(self, request_id: str, user: Optional[str] = None, tenant_id: Optional[str] = None, server_id: Optional[str] = None) -> None:
        """Initialize a global context.

        Args:
            request_id (str): ID of the HTTP request.
            user (str): user ID associated with the request.
            tenant_id (str): tenant ID.
            server_id (str): server ID.
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
