# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/base.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
-Authors: Teryl Taylor, Mihai Criveti

Base plugin implementation.
This module implements the base plugin object.
It supports pre and post hooks AI safety, security and business processing
for the following locations in the server:
server_pre_register / server_post_register - for virtual server verification
tool_pre_invoke / tool_post_invoke - for guardrails
prompt_pre_fetch / prompt_post_fetch - for prompt filtering
resource_pre_fetch / resource_post_fetch - for content filtering
auth_pre_check / auth_post_check - for custom auth logic
federation_pre_sync / federation_post_sync - for gateway federation
"""

# Standard
from typing import Awaitable, Callable, Optional, Union
import uuid

# First-Party
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.models import (
    PluginCondition,
    PluginConfig,
    PluginContext,
    PluginErrorModel,
    PluginMode,
    PluginPayload,
    PluginResult,
)


class Plugin:
    """Base plugin object for pre/post processing of inputs and outputs at various locations throughout the server.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginConfig, PluginMode
        >>> from mcpgateway.plugins.mcp.entities import HookType
        >>> config = PluginConfig(
        ...     name="test_plugin",
        ...     description="Test plugin",
        ...     author="test",
        ...     kind="mcpgateway.plugins.framework.Plugin",
        ...     version="1.0.0",
        ...     hooks=[HookType.PROMPT_PRE_FETCH],
        ...     tags=["test"],
        ...     mode=PluginMode.ENFORCE,
        ...     priority=50
        ... )
        >>> plugin = Plugin(config)
        >>> plugin.name
        'test_plugin'
        >>> plugin.priority
        50
        >>> plugin.mode
        <PluginMode.ENFORCE: 'enforce'>
        >>> HookType.PROMPT_PRE_FETCH in plugin.hooks
        True
    """

    def __init__(
        self,
        config: PluginConfig,
        hook_payloads: Optional[dict[str, PluginPayload]] = None,
        hook_results: Optional[dict[str, PluginResult]] = None,
    ) -> None:
        """Initialize a plugin with a configuration and context.

        Args:
            config: The plugin configuration
            hook_payloads: optional mapping of hookpoints to payloads for the plugin.
                            Used for external plugins for converting json to pydantic.
            hook_results: optional mapping of hookpoints to result types for the plugin.
                            Used for external plugins for converting json to pydantic.

        Examples:
            >>> from mcpgateway.plugins.framework import PluginConfig
            >>> from mcpgateway.plugins.mcp.entities import HookType
            >>> config = PluginConfig(
            ...     name="simple_plugin",
            ...     description="Simple test",
            ...     author="test",
            ...     kind="test.Plugin",
            ...     version="1.0.0",
            ...     hooks=[HookType.PROMPT_POST_FETCH],
            ...     tags=["simple"]
            ... )
            >>> plugin = Plugin(config)
            >>> plugin._config.name
            'simple_plugin'
        """
        self._config = config
        self._hook_payloads = hook_payloads
        self._hook_results = hook_results

    @property
    def priority(self) -> int:
        """Return the plugin's priority.

        Returns:
            Plugin's priority.
        """
        return self._config.priority

    @property
    def config(self) -> PluginConfig:
        """Return the plugin's configuration.

        Returns:
            Plugin's configuration.
        """
        return self._config

    @property
    def mode(self) -> PluginMode:
        """Return the plugin's mode.

        Returns:
            Plugin's mode.
        """
        return self._config.mode

    @property
    def name(self) -> str:
        """Return the plugin's name.

        Returns:
            Plugin's name.
        """
        return self._config.name

    @property
    def hooks(self) -> list[str]:
        """Return the plugin's currently configured hooks.

        Returns:
            Plugin's configured hooks.
        """
        return self._config.hooks

    @property
    def tags(self) -> list[str]:
        """Return the plugin's tags.

        Returns:
            Plugin's tags.
        """
        return self._config.tags

    @property
    def conditions(self) -> list[PluginCondition] | None:
        """Return the plugin's conditions for operation.

        Returns:
            Plugin's conditions for executing.
        """
        return self._config.conditions

    async def initialize(self) -> None:
        """Initialize the plugin."""

    async def shutdown(self) -> None:
        """Plugin cleanup code."""

    def json_to_payload(self, hook: str, payload: Union[str | dict]) -> PluginPayload:
        """Converts a json payload to the proper pydantic payload object given a hook type. Used
           mainly for serialization/deserialization of external plugin payloads.

        Args:
            hook: the hook type for which the payload needs converting.
            payload: the payload as a string or dict.

        Returns:
            A pydantic payload object corresponding to the hook type.

        Raises:
            PluginError: if no payload type is defined.
        """
        hook_payload_type: type[PluginPayload] | None = None

        # First try instance-level hook_payloads
        if self._hook_payloads:
            hook_payload_type = self._hook_payloads.get(hook, None)  # type: ignore[assignment]

        # Fall back to global registry
        if not hook_payload_type:
            # First-Party
            from mcpgateway.plugins.framework.hook_registry import get_hook_registry  # pylint: disable=import-outside-toplevel

            registry = get_hook_registry()
            hook_payload_type = registry.get_payload_type(hook)

        if not hook_payload_type:
            raise PluginError(error=PluginErrorModel(message=f"No payload defined for hook {hook}.", plugin_name=self.name))

        if isinstance(payload, str):
            return hook_payload_type.model_validate_json(payload)
        return hook_payload_type.model_validate(payload)

    def json_to_result(self, hook: str, result: Union[str | dict]) -> PluginResult:
        """Converts a json result to the proper pydantic result object given a hook type. Used
           mainly for serialization/deserialization of external plugin results.

        Args:
            hook: the hook type for which the result needs converting.
            result: the result as a string or dict.

        Returns:
            A pydantic result object corresponding to the hook type.

        Raises:
            PluginError: if no result type is defined.
        """
        hook_result_type: type[PluginResult] | None = None

        # First try instance-level hook_results
        if self._hook_results:
            hook_result_type = self._hook_results.get(hook, None)  # type: ignore[assignment]

        # Fall back to global registry
        if not hook_result_type:
            # First-Party
            from mcpgateway.plugins.framework.hook_registry import get_hook_registry  # pylint: disable=import-outside-toplevel

            registry = get_hook_registry()
            hook_result_type = registry.get_result_type(hook)

        if not hook_result_type:
            raise PluginError(error=PluginErrorModel(message=f"No result defined for hook {hook}.", plugin_name=self.name))

        if isinstance(result, str):
            return hook_result_type.model_validate_json(result)
        return hook_result_type.model_validate(result)


class PluginRef:
    """Plugin reference which contains a uuid.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginConfig, PluginMode
        >>> from mcpgateway.plugins.mcp.entities import HookType
        >>> config = PluginConfig(
        ...     name="ref_test",
        ...     description="Reference test",
        ...     author="test",
        ...     kind="test.Plugin",
        ...     version="1.0.0",
        ...     hooks=[HookType.PROMPT_PRE_FETCH],
        ...     tags=["ref", "test"],
        ...     mode=PluginMode.PERMISSIVE,
        ...     priority=100
        ... )
        >>> plugin = Plugin(config)
        >>> ref = PluginRef(plugin)
        >>> ref.name
        'ref_test'
        >>> ref.priority
        100
        >>> ref.mode
        <PluginMode.PERMISSIVE: 'permissive'>
        >>> len(ref.uuid)  # UUID is a 32-character hex string
        32
        >>> ref.tags
        ['ref', 'test']
    """

    def __init__(self, plugin: Plugin):
        """Initialize a plugin reference.

        Args:
            plugin: The plugin to reference.

        Examples:
            >>> from mcpgateway.plugins.framework import PluginConfig
            >>> from mcpgateway.plugins.mcp.entities import HookType
            >>> config = PluginConfig(
            ...     name="plugin_ref",
            ...     description="Test",
            ...     author="test",
            ...     kind="test.Plugin",
            ...     version="1.0.0",
            ...     hooks=[HookType.PROMPT_POST_FETCH],
            ...     tags=[]
            ... )
            >>> plugin = Plugin(config)
            >>> ref = PluginRef(plugin)
            >>> ref._plugin.name
            'plugin_ref'
            >>> isinstance(ref._uuid, uuid.UUID)
            True
        """
        self._plugin = plugin
        self._uuid = uuid.uuid4()

    @property
    def plugin(self) -> Plugin:
        """Return the underlying plugin.

        Returns:
            The underlying plugin.
        """
        return self._plugin

    @property
    def uuid(self) -> str:
        """Return the plugin's UUID.

        Returns:
            Plugin's UUID.
        """
        return self._uuid.hex

    @property
    def priority(self) -> int:
        """Returns the plugin's priority.

        Returns:
            Plugin's priority.
        """
        return self._plugin.priority

    @property
    def name(self) -> str:
        """Return the plugin's name.

        Returns:
            Plugin's name.
        """
        return self._plugin.name

    @property
    def hooks(self) -> list[str]:
        """Returns the plugin's currently configured hooks.

        Returns:
            Plugin's configured hooks.
        """
        return self._plugin.hooks

    @property
    def tags(self) -> list[str]:
        """Return the plugin's tags.

        Returns:
            Plugin's tags.
        """
        return self._plugin.tags

    @property
    def conditions(self) -> list[PluginCondition] | None:
        """Return the plugin's conditions for operation.

        Returns:
            Plugin's conditions for operation.
        """
        return self._plugin.conditions

    @property
    def mode(self) -> PluginMode:
        """Return the plugin's mode.

        Returns:
            Plugin's mode.
        """
        return self.plugin.mode


class HookRef:
    """A Hook reference point with plugin and function."""

    def __init__(self, hook: str, plugin_ref: PluginRef):
        """Initialize a hook reference point.

        Args:
            hook: name of the hook point.
            plugin_ref: The reference to the plugin to hook.
        """
        self._plugin_ref = plugin_ref
        self._hook = hook
        self._func: Callable[[PluginPayload, PluginContext], Awaitable[PluginResult]] = getattr(plugin_ref.plugin, hook)
        if not self._func:
            raise PluginError(error=PluginErrorModel(message=f"Plugin: {plugin_ref.plugin.name} has no hook: {hook}", plugin_name=plugin_ref.plugin.name))

    @property
    def plugin_ref(self) -> PluginRef:
        """The reference to the plugin object.

        Returns:
            A plugin reference.
        """
        return self._plugin_ref

    @property
    def name(self) -> str:
        """The name of the hooking function.

        Returns:
            A plugin name.
        """
        return self._hook

    @property
    def hook(self) -> Callable[[PluginPayload, PluginContext], Awaitable[PluginResult]]:
        """The hooking function that can be invoked within the reference.

        Returns:
            An awaitable hook function reference.
        """
        return self._func
