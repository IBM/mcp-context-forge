# -*- coding: utf-8 -*-
"""Plugin manager.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Module that manages and calls plugins at hookpoints throughout the gateway.
"""

# Standard
import logging
from typing import Optional

# First-Party
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.models import Config, HookType, PluginMode
from mcpgateway.plugins.framework.registry import PluginInstanceRegistry
from mcpgateway.plugins.framework.types import (
    GlobalContext,
    PluginContext,
    PluginContextTable,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
)
from mcpgateway.plugins.framework.utils import pre_prompt_matches

logger = logging.getLogger(__name__)


class PluginManager:
    """Plugin manager for managing the plugin lifecycle."""

    def __init__(self, config: str):
        """Initialize plugin manager.

        Args:
            config: plugin configuration path.
        """
        self._config: Config = ConfigLoader.load_config(config)
        self._initialized: bool = False
        self._loader: PluginLoader = PluginLoader()
        self._registry: PluginInstanceRegistry = PluginInstanceRegistry()

    @property
    def config(self) -> Config:
        """Plugin manager configuration.

        Returns:
            The plugin configuration.
        """
        return self._config

    async def initialize(self) -> None:
        """Initialize the plugin manager.

        Raises:
            ValueError: if it cannot initialize the plugin.
        """
        if self._initialized:
            return

        for plugin_config in self._config.plugins:
            if plugin_config.mode != PluginMode.DISABLED:
                plugin = await self._loader.load_and_instantiate_plugin(plugin_config)
                if plugin:
                    self._registry.register(plugin)
                else:
                    raise ValueError(f"Unable to register and initialize plugin: {plugin_config.name}")
        self._initialized = True
        logger.info(f"Plugin manager initialized with {len(self._registry.get_all_plugins())} plugins")

    async def prompt_pre_fetch(
        self,
        payload: PromptPrehookPayload,
        global_context: GlobalContext,
        local_contexts: Optional[PluginContextTable] = None,
    ) -> tuple[PromptPrehookResult | None, PluginContextTable | None]:
        """Plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            global_context: contextual information for all plugins.
            local_contexts: context local to a single plugin.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        plugins = self._registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)

        if not plugins:
            return (PromptPrehookResult(modified_payload=payload), None)

        res_local_contexts = {}
        combined_metadata = {}
        current_payload: PromptPrehookPayload | None = None
        for pluginref in plugins:
            if not pluginref.conditions or not pre_prompt_matches(payload, pluginref.conditions, global_context):
                continue
            local_context_key = global_context.request_id + pluginref.uuid
            if local_contexts and local_context_key in local_contexts:
                local_context = local_contexts[local_context_key]
            else:
                local_context = PluginContext(global_context)
            res_local_contexts[local_context_key] = local_context
            result = await pluginref.plugin.prompt_pre_fetch(payload, local_context)

            if result.metadata:
                combined_metadata.update(result.metadata)

            if result.modified_payload is not None:
                current_payload = result.modified_payload

            if not result.continue_processing:
                # Check execution mode
                if pluginref.plugin.mode == PluginMode.ENFORCE:
                    return (PromptPrehookResult(continue_processing=False, modified_payload=current_payload, error=result.error, metadata=combined_metadata), None)
                elif pluginref.plugin.mode == PluginMode.PERMISSIVE:
                    logger.warning(f"Plugin {pluginref.plugin.name} would block (permissive mode): {result.error}")

        return (PromptPrehookResult(continue_processing=True, modified_payload=current_payload, error=None, metadata=combined_metadata), res_local_contexts)

    async def prompt_post_fetch(
        self, payload: PromptPosthookPayload, global_context: GlobalContext, local_contexts: Optional[PluginContextTable] = None
    ) -> tuple[PromptPosthookResult | None, PluginContextTable | None]:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            global_context: contextual information for all plugins.
            local_contexts: context local to a single plugin.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        return (None, None)
