# -*- coding: utf-8 -*-
"""Base plugin implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

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
import uuid

# First-Party
from mcpgateway.plugins.framework.models import HookType, PluginCondition, PluginConfig, PluginMode
from mcpgateway.plugins.framework.plugin_types import (
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
)


class Plugin:
    """Base plugin object for pre/post processing of inputs and outputs at various locations throughout the server."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize a plugin with a configuration and context.

        Args:
            config: The plugin configuration
        """
        self._config = config

    @property
    def priority(self) -> int:
        """Return the plugin's priority.

        Returns:
            Plugin's priority.
        """
        return self._config.priority

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
    def hooks(self) -> list[HookType]:
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

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Raises:
            NotImplementedError: needs to be implemented by sub class.
        """
        raise NotImplementedError(
            f"""'prompt_pre_fetch' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Raises:
            NotImplementedError: needs to be implemented by sub class.
        """
        raise NotImplementedError(
            f"""'prompt_post_fetch' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )

    async def shutdown(self) -> None:
        """Plugin cleanup code."""


class PluginRef:
    """Plugin reference which contains a uuid."""

    def __init__(self, plugin: Plugin):
        """Initialize a plugin reference.

        Args:
            plugin: The plugin to reference.
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
    def hooks(self) -> list[HookType]:
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
