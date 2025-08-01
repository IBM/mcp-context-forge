# -*- coding: utf-8 -*-
"""Plugin manager.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Module that manages and calls plugins at hookpoints throughout the gateway.
"""

# Standard
import logging
from typing import Any, Callable, Coroutine, Generic, Optional, TypeVar

# First-Party
from mcpgateway.plugins.framework.base import PluginRef
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.models import Config, HookType, PluginCondition, PluginMode
from mcpgateway.plugins.framework.registry import PluginInstanceRegistry
from mcpgateway.plugins.framework.types import (
    GlobalContext,
    PluginContext,
    PluginContextTable,
    PluginResult,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
)
from mcpgateway.plugins.framework.utils import post_prompt_matches, pre_prompt_matches

logger = logging.getLogger(__name__)

T = TypeVar('T')


class PluginExecutor(Generic[T]):
    """Executes a list of plugins."""
    async def execute(
        self,
        plugins: list[PluginRef],
        payload: T,
        global_context: GlobalContext,
        plugin_run: Callable[[PluginRef, T, PluginContext], Coroutine[Any, Any, PluginResult[T]]],
        compare: Callable[[T, list[PluginCondition], GlobalContext], bool],
        local_contexts: Optional[PluginContextTable] = None,
    ) -> tuple[PluginResult[T] | None, PluginContextTable | None]:
        """Execute a plugins hook run before a prompt is retrieved and rendered.

        Args:
            plugins: the list of plugins to execute.
            payload: the payload to be analyzed.
            global_context: contextual information for all plugins.
            plugin_run: async function for executing plugin hook.
            compare: function for comparing conditional information with context and payload 
            local_contexts: context local to a single plugin.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        if not plugins:
            return (PluginResult[T](modified_payload=None), None)

        res_local_contexts = {}
        combined_metadata = {}
        current_payload: T | None = None
        for pluginref in plugins:
            if not pluginref.conditions or not compare(payload, pluginref.conditions, global_context):
                continue
            local_context_key = global_context.request_id + pluginref.uuid
            if local_contexts and local_context_key in local_contexts:
                local_context = local_contexts[local_context_key]
            else:
                local_context = PluginContext(global_context)
            res_local_contexts[local_context_key] = local_context
            result = await plugin_run(pluginref, payload, local_context)

            if result.metadata:
                combined_metadata.update(result.metadata)

            if result.modified_payload is not None:
                current_payload = result.modified_payload

            if not result.continue_processing:
                # Check execution mode
                if pluginref.plugin.mode == PluginMode.ENFORCE:
                    return (PluginResult[T](continue_processing=False, modified_payload=current_payload, error=result.error, metadata=combined_metadata), None)
                elif pluginref.plugin.mode == PluginMode.PERMISSIVE:
                    logger.warning(f"Plugin {pluginref.plugin.name} would block (permissive mode): {result.error}")

        return (PluginResult[T](continue_processing=True, modified_payload=current_payload, error=None, metadata=combined_metadata), res_local_contexts)


async def pre_prompt_fetch(plugin: PluginRef, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
    """Call plugin's prompt pre-fetch hook.

    Args:
        plugin:  the plugin to execute.
        payload: the prompt payload to be analyzed.
        context: contextual information about the hook call. Including why it was called.

    Returns:
        The result of the plugin execution.
    """
    return await plugin.plugin.prompt_pre_fetch(payload, context)


async def post_prompt_fetch(plugin: PluginRef, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
    """Call plugin's prompt post-fetch hook.

    Args:
        plugin:  the plugin to execute.
        payload: the prompt payload to be analyzed.
        context: contextual information about the hook call. Including why it was called.

    Returns:
        The result of the plugin execution.
    """
    return await plugin.plugin.prompt_post_fetch(payload, context)


class PluginManager:
    """Plugin manager for managing the plugin lifecycle."""

    __shared_state: dict[Any, Any] = {}
    _loader: PluginLoader = PluginLoader()
    _initialized: bool = False
    _registry: PluginInstanceRegistry = PluginInstanceRegistry()
    _config: Config | None = None
    _pre_prompt_executor: PluginExecutor[PromptPrehookPayload] = PluginExecutor[PromptPrehookPayload]()
    _post_prompt_executor: PluginExecutor[PromptPosthookPayload] = PluginExecutor[PromptPosthookPayload]()

    def __init__(self, config: str = ""):
        """Initialize plugin manager.

        Args:
            config: plugin configuration path.
        """
        self.__dict__ = self.__shared_state
        if config:
            self._config = ConfigLoader.load_config(config)

    @property
    def config(self) -> Config | None:
        """Plugin manager configuration.

        Returns:
            The plugin configuration.
        """
        return self._config

    @property
    def plugin_count(self) -> int:
        """Number of plugins loaded.

        Returns:
            The number of plugins loaded.
        """
        return self._registry.plugin_count

    @property
    def initialized(self) -> bool:
        """Plugin manager initialized.

        Returns:
            True if the plugin manager is initialized.
        """
        return self._initialized

    async def initialize(self) -> None:
        """Initialize the plugin manager.

        Raises:
            ValueError: if it cannot initialize the plugin.
        """
        if self._initialized:
            return
        
        plugins = self._config.plugins if self._config else []

        for plugin_config in plugins:
            if plugin_config.mode != PluginMode.DISABLED:
                plugin = await self._loader.load_and_instantiate_plugin(plugin_config)
                if plugin:
                    self._registry.register(plugin)
                else:
                    raise ValueError(f"Unable to register and initialize plugin: {plugin_config.name}")
        self._initialized = True
        logger.info(f"Plugin manager initialized with {len(self._registry.get_all_plugins())} plugins")

    async def shutdown(self) -> None:
        """Shutdown all plugins."""
        for plugin_ref in self._registry.get_all_plugins():
            try:
                await plugin_ref.plugin.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down plugin {plugin_ref.plugin.name}: {e}")

        self._initialized = False

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
        return await self._pre_prompt_executor.execute(plugins, payload, global_context, pre_prompt_fetch, pre_prompt_matches, local_contexts)



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
        plugins = self._registry.get_plugins_for_hook(HookType.PROMPT_POST_FETCH)
        return await self._post_prompt_executor.execute(plugins, payload, global_context, post_prompt_fetch, post_prompt_matches, local_contexts)
