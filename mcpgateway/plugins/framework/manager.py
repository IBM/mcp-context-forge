# -*- coding: utf-8 -*-
"""Plugin manager.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Mihai Criveti

Module that manages and calls plugins at hookpoints throughout the gateway.

This module provides the core plugin management functionality including:
- Plugin lifecycle management (initialization, execution, shutdown)
- Timeout protection for plugin execution
- Context management with automatic cleanup
- Priority-based plugin ordering
- Conditional plugin execution based on prompts/servers/tenants

Examples:
    >>> # Initialize plugin manager with configuration
    >>> manager = PluginManager("plugins/config.yaml")
    >>> # await manager.initialize()  # Called in async context

    >>> # Create test payload and context
    >>> from mcpgateway.plugins.framework.plugin_types import PromptPrehookPayload, GlobalContext
    >>> payload = PromptPrehookPayload(name="test", args={"user": "input"})
    >>> context = GlobalContext(request_id="123")
    >>> # result, contexts = await manager.prompt_pre_fetch(payload, context)  # Called in async context
"""

# Standard
import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, Generic, Optional, Tuple, TypeVar

# First-Party
from mcpgateway.plugins.framework.base import PluginRef
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.models import Config, HookType, PluginCondition, PluginMode, PluginViolation
from mcpgateway.plugins.framework.plugin_types import (
    GlobalContext,
    PluginContext,
    PluginContextTable,
    PluginResult,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.plugins.framework.registry import PluginInstanceRegistry
from mcpgateway.plugins.framework.utils import post_prompt_matches, post_tool_matches, pre_prompt_matches, pre_tool_matches

# Use standard logging to avoid circular imports (plugins -> services -> plugins)
logger = logging.getLogger(__name__)

T = TypeVar("T")

# Configuration constants
DEFAULT_PLUGIN_TIMEOUT = 30  # seconds
MAX_PAYLOAD_SIZE = 1_000_000  # 1MB
CONTEXT_CLEANUP_INTERVAL = 300  # 5 minutes
CONTEXT_MAX_AGE = 3600  # 1 hour


class PluginTimeoutError(Exception):
    """Raised when a plugin execution exceeds the timeout limit."""


class PayloadSizeError(ValueError):
    """Raised when a payload exceeds the maximum allowed size."""


class PluginExecutor(Generic[T]):
    """Executes a list of plugins with timeout protection and error handling.

    This class manages the execution of plugins in priority order, handling:
    - Timeout protection for each plugin
    - Context management between plugins
    - Error isolation to prevent plugin failures from affecting the gateway
    - Metadata aggregation from multiple plugins

    Examples:
        >>> from mcpgateway.plugins.framework.plugin_types import PromptPrehookPayload
        >>> executor = PluginExecutor[PromptPrehookPayload]()
        >>> # In async context:
        >>> # result, contexts = await executor.execute(
        >>> #     plugins=[plugin1, plugin2],
        >>> #     payload=payload,
        >>> #     global_context=context,
        >>> #     plugin_run=pre_prompt_fetch,
        >>> #     compare=pre_prompt_matches
        >>> # )
    """

    def __init__(self, timeout: int = DEFAULT_PLUGIN_TIMEOUT):
        """Initialize the plugin executor.

        Args:
            timeout: Maximum execution time per plugin in seconds.
        """
        self.timeout = timeout

    async def execute(
        self,
        plugins: list[PluginRef],
        payload: T,
        global_context: GlobalContext,
        plugin_run: Callable[[PluginRef, T, PluginContext], Coroutine[Any, Any, PluginResult[T]]],
        compare: Callable[[T, list[PluginCondition], GlobalContext], bool],
        local_contexts: Optional[PluginContextTable] = None,
    ) -> tuple[PluginResult[T], PluginContextTable | None]:
        """Execute plugins in priority order with timeout protection.

        Args:
            plugins: List of plugins to execute, sorted by priority.
            payload: The payload to be processed by plugins.
            global_context: Shared context for all plugins containing request metadata.
            plugin_run: Async function to execute a specific plugin hook.
            compare: Function to check if plugin conditions match the current context.
            local_contexts: Optional existing contexts from previous hook executions.

        Returns:
            A tuple containing:
            - PluginResult with processing status, modified payload, and metadata
            - PluginContextTable with updated local contexts for each plugin

        Raises:
            PayloadSizeError: If the payload exceeds MAX_PAYLOAD_SIZE.

        Examples:
            >>> # Execute plugins with timeout protection
            >>> from mcpgateway.plugins.framework.models import HookType
            >>> executor = PluginExecutor(timeout=30)
            >>> # Assuming you have a registry instance:
            >>> # plugins = registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)
            >>> # In async context:
            >>> # result, contexts = await executor.execute(
            >>> #     plugins=plugins,
            >>> #     payload=PromptPrehookPayload(name="test", args={}),
            >>> #     global_context=GlobalContext(request_id="123"),
            >>> #     plugin_run=pre_prompt_fetch,
            >>> #     compare=pre_prompt_matches
            >>> # )
        """
        if not plugins:
            return (PluginResult[T](modified_payload=None), None)

        # Validate payload size
        self._validate_payload_size(payload)

        res_local_contexts = {}
        combined_metadata = {}
        current_payload: T | None = None

        for pluginref in plugins:
            # Check if plugin conditions match current context
            if pluginref.conditions and not compare(payload, pluginref.conditions, global_context):
                logger.debug(f"Skipping plugin {pluginref.name} - conditions not met")
                continue

            # Get or create local context for this plugin
            local_context_key = global_context.request_id + pluginref.uuid
            if local_contexts and local_context_key in local_contexts:
                local_context = local_contexts[local_context_key]
            else:
                local_context = PluginContext(global_context)
            res_local_contexts[local_context_key] = local_context

            try:
                # Execute plugin with timeout protection
                result = await self._execute_with_timeout(pluginref, plugin_run, current_payload or payload, local_context)

                # Aggregate metadata from all plugins
                if result.metadata:
                    combined_metadata.update(result.metadata)

                # Track payload modifications
                if result.modified_payload is not None:
                    current_payload = result.modified_payload

                # Set plugin name in violation if present
                if result.violation:
                    result.violation.plugin_name = pluginref.plugin.name

                # Handle plugin blocking the request
                if not result.continue_processing:
                    if pluginref.plugin.mode == PluginMode.ENFORCE:
                        logger.warning(f"Plugin {pluginref.plugin.name} blocked request in enforce mode")
                        return (PluginResult[T](continue_processing=False, modified_payload=current_payload, violation=result.violation, metadata=combined_metadata), res_local_contexts)
                    elif pluginref.plugin.mode == PluginMode.PERMISSIVE:
                        logger.warning(f"Plugin {pluginref.plugin.name} would block (permissive mode): {result.violation.description if result.violation else 'No description'}")

            except asyncio.TimeoutError:
                logger.error(f"Plugin {pluginref.name} timed out after {self.timeout}s")
                if pluginref.plugin.mode == PluginMode.ENFORCE:
                    violation = PluginViolation(
                        reason="Plugin timeout",
                        description=f"Plugin {pluginref.name} exceeded {self.timeout}s timeout",
                        code="PLUGIN_TIMEOUT",
                        details={"timeout": self.timeout, "plugin": pluginref.name},
                    )
                    return (PluginResult[T](continue_processing=False, violation=violation, modified_payload=current_payload, metadata=combined_metadata), res_local_contexts)
                # In permissive mode, continue with next plugin
                continue

            except Exception as e:
                logger.error(f"Plugin {pluginref.name} failed with error: {str(e)}", exc_info=True)
                if pluginref.plugin.mode == PluginMode.ENFORCE:
                    violation = PluginViolation(
                        reason="Plugin error", description=f"Plugin {pluginref.name} encountered an error: {str(e)}", code="PLUGIN_ERROR", details={"error": str(e), "plugin": pluginref.name}
                    )
                    return (PluginResult[T](continue_processing=False, violation=violation, modified_payload=current_payload, metadata=combined_metadata), res_local_contexts)
                # In permissive mode, continue with next plugin
                continue

        return (PluginResult[T](continue_processing=True, modified_payload=current_payload, violation=None, metadata=combined_metadata), res_local_contexts)

    async def _execute_with_timeout(self, pluginref: PluginRef, plugin_run: Callable, payload: T, context: PluginContext) -> PluginResult[T]:
        """Execute a plugin with timeout protection.

        Args:
            pluginref: Reference to the plugin to execute.
            plugin_run: Function to execute the plugin.
            payload: Payload to process.
            context: Plugin execution context.

        Returns:
            Result from plugin execution.

        Raises:
            asyncio.TimeoutError: If plugin exceeds timeout.
        """
        return await asyncio.wait_for(plugin_run(pluginref, payload, context), timeout=self.timeout)

    def _validate_payload_size(self, payload: Any) -> None:
        """Validate that payload doesn't exceed size limits.

        Args:
            payload: The payload to validate.

        Raises:
            PayloadSizeError: If payload exceeds MAX_PAYLOAD_SIZE.
        """
        # For PromptPrehookPayload, check args size
        if hasattr(payload, "args") and payload.args:
            total_size = sum(len(str(v)) for v in payload.args.values())
            if total_size > MAX_PAYLOAD_SIZE:
                raise PayloadSizeError(f"Payload size {total_size} exceeds limit of {MAX_PAYLOAD_SIZE} bytes")
        # For PromptPosthookPayload, check result size
        elif hasattr(payload, "result") and payload.result:
            # Estimate size of result messages
            total_size = len(str(payload.result))
            if total_size > MAX_PAYLOAD_SIZE:
                raise PayloadSizeError(f"Result size {total_size} exceeds limit of {MAX_PAYLOAD_SIZE} bytes")


async def pre_prompt_fetch(plugin: PluginRef, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
    """Call plugin's prompt pre-fetch hook.

    Args:
        plugin: The plugin to execute.
        payload: The prompt payload to be analyzed.
        context: Contextual information about the hook call.

    Returns:
        The result of the plugin execution.

    Examples:
        >>> from mcpgateway.plugins.framework.base import Plugin, PluginRef
        >>> from mcpgateway.plugins.framework.plugin_types import PromptPrehookPayload, PluginContext, GlobalContext
        >>> # Assuming you have a plugin instance:
        >>> # plugin_ref = PluginRef(my_plugin)
        >>> payload = PromptPrehookPayload(name="test", args={"key": "value"})
        >>> context = PluginContext(GlobalContext(request_id="123"))
        >>> # In async context:
        >>> # result = await pre_prompt_fetch(plugin_ref, payload, context)
    """
    return await plugin.plugin.prompt_pre_fetch(payload, context)


async def post_prompt_fetch(plugin: PluginRef, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
    """Call plugin's prompt post-fetch hook.

    Args:
        plugin: The plugin to execute.
        payload: The prompt payload to be analyzed.
        context: Contextual information about the hook call.

    Returns:
        The result of the plugin execution.

    Examples:
        >>> from mcpgateway.plugins.framework.base import Plugin, PluginRef
        >>> from mcpgateway.plugins.framework.plugin_types import PromptPosthookPayload, PluginContext, GlobalContext
        >>> from mcpgateway.models import PromptResult
        >>> # Assuming you have a plugin instance:
        >>> # plugin_ref = PluginRef(my_plugin)
        >>> result = PromptResult(messages=[])
        >>> payload = PromptPosthookPayload(name="test", result=result)
        >>> context = PluginContext(GlobalContext(request_id="123"))
        >>> # In async context:
        >>> # result = await post_prompt_fetch(plugin_ref, payload, context)
    """
    return await plugin.plugin.prompt_post_fetch(payload, context)


async def pre_tool_invoke(plugin: PluginRef, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
    """Call plugin's tool pre-invoke hook.

    Args:
        plugin: The plugin to execute.
        payload: The tool payload to be analyzed.
        context: Contextual information about the hook call.

    Returns:
        The result of the plugin execution.

    Examples:
        >>> from mcpgateway.plugins.framework.base import Plugin, PluginRef
        >>> from mcpgateway.plugins.framework.plugin_types import ToolPreInvokePayload, PluginContext, GlobalContext
        >>> # Assuming you have a plugin instance:
        >>> # plugin_ref = PluginRef(my_plugin)
        >>> payload = ToolPreInvokePayload(name="calculator", args={"operation": "add", "a": 5, "b": 3})
        >>> context = PluginContext(GlobalContext(request_id="123"))
        >>> # In async context:
        >>> # result = await pre_tool_invoke(plugin_ref, payload, context)
    """
    return await plugin.plugin.tool_pre_invoke(payload, context)


async def post_tool_invoke(plugin: PluginRef, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
    """Call plugin's tool post-invoke hook.

    Args:
        plugin: The plugin to execute.
        payload: The tool result payload to be analyzed.
        context: Contextual information about the hook call.

    Returns:
        The result of the plugin execution.

    Examples:
        >>> from mcpgateway.plugins.framework.base import Plugin, PluginRef
        >>> from mcpgateway.plugins.framework.plugin_types import ToolPostInvokePayload, PluginContext, GlobalContext
        >>> # Assuming you have a plugin instance:
        >>> # plugin_ref = PluginRef(my_plugin)
        >>> payload = ToolPostInvokePayload(name="calculator", result={"result": 8, "status": "success"})
        >>> context = PluginContext(GlobalContext(request_id="123"))
        >>> # In async context:
        >>> # result = await post_tool_invoke(plugin_ref, payload, context)
    """
    return await plugin.plugin.tool_post_invoke(payload, context)


class PluginManager:
    """Plugin manager for managing the plugin lifecycle.

    This class implements a singleton pattern to ensure consistent plugin
    management across the application. It handles:
    - Plugin discovery and loading from configuration
    - Plugin lifecycle management (initialization, execution, shutdown)
    - Context management with automatic cleanup
    - Hook execution orchestration

    Attributes:
        config: The loaded plugin configuration.
        plugin_count: Number of currently loaded plugins.
        initialized: Whether the manager has been initialized.

    Examples:
        >>> # Initialize plugin manager
        >>> manager = PluginManager("plugins/config.yaml")
        >>> # In async context:
        >>> # await manager.initialize()
        >>> # print(f"Loaded {manager.plugin_count} plugins")
        >>>
        >>> # Execute prompt hooks
        >>> from mcpgateway.plugins.framework.plugin_types import PromptPrehookPayload, GlobalContext
        >>> payload = PromptPrehookPayload(name="test", args={})
        >>> context = GlobalContext(request_id="req-123")
        >>> # In async context:
        >>> # result, contexts = await manager.prompt_pre_fetch(payload, context)
        >>>
        >>> # Shutdown when done
        >>> # await manager.shutdown()
    """

    __shared_state: dict[Any, Any] = {}
    _loader: PluginLoader = PluginLoader()
    _initialized: bool = False
    _registry: PluginInstanceRegistry = PluginInstanceRegistry()
    _config: Config | None = None
    _pre_prompt_executor: PluginExecutor[PromptPrehookPayload] = PluginExecutor[PromptPrehookPayload]()
    _post_prompt_executor: PluginExecutor[PromptPosthookPayload] = PluginExecutor[PromptPosthookPayload]()
    _pre_tool_executor: PluginExecutor[ToolPreInvokePayload] = PluginExecutor[ToolPreInvokePayload]()
    _post_tool_executor: PluginExecutor[ToolPostInvokePayload] = PluginExecutor[ToolPostInvokePayload]()

    # Context cleanup tracking
    _context_store: Dict[str, Tuple[PluginContextTable, float]] = {}
    _last_cleanup: float = 0

    def __init__(self, config: str = "", timeout: int = DEFAULT_PLUGIN_TIMEOUT):
        """Initialize plugin manager.

        Args:
            config: Path to plugin configuration file (YAML).
            timeout: Maximum execution time per plugin in seconds.

        Examples:
            >>> # Initialize with configuration file
            >>> manager = PluginManager("plugins/config.yaml")

            >>> # Initialize with custom timeout
            >>> manager = PluginManager("plugins/config.yaml", timeout=60)
        """
        self.__dict__ = self.__shared_state
        if config:
            self._config = ConfigLoader.load_config(config)

        # Update executor timeouts
        self._pre_prompt_executor.timeout = timeout
        self._post_prompt_executor.timeout = timeout
        self._pre_tool_executor.timeout = timeout
        self._post_tool_executor.timeout = timeout

        # Initialize context tracking if not already done
        if not hasattr(self, "_context_store"):
            self._context_store = {}
            self._last_cleanup = time.time()

    @property
    def config(self) -> Config | None:
        """Plugin manager configuration.

        Returns:
            The plugin configuration object or None if not configured.
        """
        return self._config

    @property
    def plugin_count(self) -> int:
        """Number of plugins loaded.

        Returns:
            The number of currently loaded plugins.
        """
        return self._registry.plugin_count

    @property
    def initialized(self) -> bool:
        """Plugin manager initialization status.

        Returns:
            True if the plugin manager has been initialized.
        """
        return self._initialized

    async def initialize(self) -> None:
        """Initialize the plugin manager and load all configured plugins.

        This method:
        1. Loads plugin configurations from the config file
        2. Instantiates each enabled plugin
        3. Registers plugins with the registry
        4. Validates plugin initialization

        Raises:
            ValueError: If a plugin cannot be initialized or registered.

        Examples:
            >>> manager = PluginManager("plugins/config.yaml")
            >>> # In async context:
            >>> # await manager.initialize()
            >>> # Manager is now ready to execute plugins
        """
        if self._initialized:
            logger.debug("Plugin manager already initialized")
            return

        plugins = self._config.plugins if self._config and self._config.plugins else []
        loaded_count = 0

        for plugin_config in plugins:
            if plugin_config.mode != PluginMode.DISABLED:
                try:
                    plugin = await self._loader.load_and_instantiate_plugin(plugin_config)
                    if plugin:
                        self._registry.register(plugin)
                        loaded_count += 1
                        logger.info(f"Loaded plugin: {plugin_config.name} (mode: {plugin_config.mode})")
                    else:
                        raise ValueError(f"Unable to instantiate plugin: {plugin_config.name}")
                except Exception as e:
                    logger.error(f"Failed to load plugin {plugin_config.name}: {str(e)}")
                    raise ValueError(f"Unable to register and initialize plugin: {plugin_config.name}") from e
            else:
                logger.debug(f"Skipping disabled plugin: {plugin_config.name}")

        self._initialized = True
        logger.info(f"Plugin manager initialized with {loaded_count} plugins")

    async def shutdown(self) -> None:
        """Shutdown all plugins and cleanup resources.

        This method:
        1. Shuts down all registered plugins
        2. Clears the plugin registry
        3. Cleans up stored contexts
        4. Resets initialization state

        Examples:
            >>> manager = PluginManager("plugins/config.yaml")
            >>> # In async context:
            >>> # await manager.initialize()
            >>> # ... use the manager ...
            >>> # await manager.shutdown()
        """
        logger.info("Shutting down plugin manager")

        # Shutdown all plugins
        await self._registry.shutdown()

        # Clear context store
        self._context_store.clear()

        # Reset state
        self._initialized = False
        logger.info("Plugin manager shutdown complete")

    async def _cleanup_old_contexts(self) -> None:
        """Remove contexts older than CONTEXT_MAX_AGE to prevent memory leaks.

        This method is called periodically during hook execution to clean up
        stale contexts that are no longer needed.
        """
        current_time = time.time()

        # Only cleanup every CONTEXT_CLEANUP_INTERVAL seconds
        if current_time - self._last_cleanup < CONTEXT_CLEANUP_INTERVAL:
            return

        # Find expired contexts
        expired_keys = [key for key, (_, timestamp) in self._context_store.items() if current_time - timestamp > CONTEXT_MAX_AGE]

        # Remove expired contexts
        for key in expired_keys:
            del self._context_store[key]

        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired plugin contexts")

        self._last_cleanup = current_time

    async def prompt_pre_fetch(
        self,
        payload: PromptPrehookPayload,
        global_context: GlobalContext,
        local_contexts: Optional[PluginContextTable] = None,
    ) -> tuple[PromptPrehookResult, PluginContextTable | None]:
        """Execute pre-fetch hooks before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload containing name and arguments.
            global_context: Shared context for all plugins with request metadata.
            local_contexts: Optional existing contexts from previous executions.

        Returns:
            A tuple containing:
            - PromptPrehookResult with processing status and modified payload
            - PluginContextTable with updated contexts for post-fetch hook

        Raises:
            PayloadSizeError: If payload exceeds size limits.

        Examples:
            >>> manager = PluginManager("plugins/config.yaml")
            >>> # In async context:
            >>> # await manager.initialize()
            >>>
            >>> from mcpgateway.plugins.framework.plugin_types import PromptPrehookPayload, GlobalContext
            >>> payload = PromptPrehookPayload(
            ...     name="greeting",
            ...     args={"user": "Alice"}
            ... )
            >>> context = GlobalContext(
            ...     request_id="req-123",
            ...     user="alice@example.com"
            ... )
            >>>
            >>> # In async context:
            >>> # result, contexts = await manager.prompt_pre_fetch(payload, context)
            >>> # if result.continue_processing:
            >>> #     # Proceed with prompt processing
            >>> #     modified_payload = result.modified_payload or payload
        """
        # Cleanup old contexts periodically
        await self._cleanup_old_contexts()

        # Get plugins configured for this hook
        plugins = self._registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)

        # Execute plugins
        result = await self._pre_prompt_executor.execute(plugins, payload, global_context, pre_prompt_fetch, pre_prompt_matches, local_contexts)

        # Store contexts for potential reuse
        if result[1]:
            self._context_store[global_context.request_id] = (result[1], time.time())

        return result

    async def prompt_post_fetch(
        self, payload: PromptPosthookPayload, global_context: GlobalContext, local_contexts: Optional[PluginContextTable] = None
    ) -> tuple[PromptPosthookResult, PluginContextTable | None]:
        """Execute post-fetch hooks after a prompt is rendered.

        Args:
            payload: The prompt result payload containing rendered messages.
            global_context: Shared context for all plugins with request metadata.
            local_contexts: Optional contexts from pre-fetch hook execution.

        Returns:
            A tuple containing:
            - PromptPosthookResult with processing status and modified result
            - PluginContextTable with final contexts

        Raises:
            PayloadSizeError: If payload exceeds size limits.

        Examples:
            >>> # Continuing from prompt_pre_fetch example
            >>> from mcpgateway.models import PromptResult, Message, TextContent, Role
            >>> from mcpgateway.plugins.framework.plugin_types import PromptPosthookPayload, GlobalContext
            >>>
            >>> # Create a proper Message with TextContent
            >>> message = Message(
            ...     role=Role.USER,
            ...     content=TextContent(type="text", text="Hello")
            ... )
            >>> prompt_result = PromptResult(messages=[message])
            >>>
            >>> post_payload = PromptPosthookPayload(
            ...     name="greeting",
            ...     result=prompt_result
            ... )
            >>>
            >>> manager = PluginManager("plugins/config.yaml")
            >>> context = GlobalContext(request_id="req-123")
            >>>
            >>> # In async context:
            >>> # result, _ = await manager.prompt_post_fetch(
            >>> #     post_payload,
            >>> #     context,
            >>> #     contexts  # From pre_fetch
            >>> # )
            >>> # if result.modified_payload:
            >>> #     # Use modified result
            >>> #     final_result = result.modified_payload.result
        """
        # Get plugins configured for this hook
        plugins = self._registry.get_plugins_for_hook(HookType.PROMPT_POST_FETCH)

        # Execute plugins
        result = await self._post_prompt_executor.execute(plugins, payload, global_context, post_prompt_fetch, post_prompt_matches, local_contexts)

        # Clean up stored context after post-fetch
        if global_context.request_id in self._context_store:
            del self._context_store[global_context.request_id]

        return result

    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        global_context: GlobalContext,
        local_contexts: Optional[PluginContextTable] = None,
    ) -> tuple[ToolPreInvokeResult, PluginContextTable | None]:
        """Execute pre-invoke hooks before a tool is invoked.

        Args:
            payload: The tool payload containing name and arguments.
            global_context: Shared context for all plugins with request metadata.
            local_contexts: Optional existing contexts from previous executions.

        Returns:
            A tuple containing:
            - ToolPreInvokeResult with processing status and modified payload
            - PluginContextTable with updated contexts for post-invoke hook

        Raises:
            PayloadSizeError: If payload exceeds size limits.

        Examples:
            >>> manager = PluginManager("plugins/config.yaml")
            >>> # In async context:
            >>> # await manager.initialize()
            >>>
            >>> from mcpgateway.plugins.framework.plugin_types import ToolPreInvokePayload, GlobalContext
            >>> payload = ToolPreInvokePayload(
            ...     name="calculator",
            ...     args={"operation": "add", "a": 5, "b": 3}
            ... )
            >>> context = GlobalContext(
            ...     request_id="req-123",
            ...     user="alice@example.com"
            ... )
            >>>
            >>> # In async context:
            >>> # result, contexts = await manager.tool_pre_invoke(payload, context)
            >>> # if result.continue_processing:
            >>> #     # Proceed with tool invocation
            >>> #     modified_payload = result.modified_payload or payload
        """
        # Cleanup old contexts periodically
        await self._cleanup_old_contexts()

        # Get plugins configured for this hook
        plugins = self._registry.get_plugins_for_hook(HookType.TOOL_PRE_INVOKE)

        # Execute plugins
        result = await self._pre_tool_executor.execute(plugins, payload, global_context, pre_tool_invoke, pre_tool_matches, local_contexts)

        # Store contexts for potential reuse
        if result[1]:
            self._context_store[global_context.request_id] = (result[1], time.time())

        return result

    async def tool_post_invoke(
        self, payload: ToolPostInvokePayload, global_context: GlobalContext, local_contexts: Optional[PluginContextTable] = None
    ) -> tuple[ToolPostInvokeResult, PluginContextTable | None]:
        """Execute post-invoke hooks after a tool is invoked.

        Args:
            payload: The tool result payload containing invocation results.
            global_context: Shared context for all plugins with request metadata.
            local_contexts: Optional contexts from pre-invoke hook execution.

        Returns:
            A tuple containing:
            - ToolPostInvokeResult with processing status and modified result
            - PluginContextTable with final contexts

        Raises:
            PayloadSizeError: If payload exceeds size limits.

        Examples:
            >>> # Continuing from tool_pre_invoke example
            >>> from mcpgateway.plugins.framework.plugin_types import ToolPostInvokePayload, GlobalContext
            >>>
            >>> post_payload = ToolPostInvokePayload(
            ...     name="calculator",
            ...     result={"result": 8, "status": "success"}
            ... )
            >>>
            >>> manager = PluginManager("plugins/config.yaml")
            >>> context = GlobalContext(request_id="req-123")
            >>>
            >>> # In async context:
            >>> # result, _ = await manager.tool_post_invoke(
            >>> #     post_payload,
            >>> #     context,
            >>> #     contexts  # From pre_invoke
            >>> # )
            >>> # if result.modified_payload:
            >>> #     # Use modified result
            >>> #     final_result = result.modified_payload.result
        """
        # Get plugins configured for this hook
        plugins = self._registry.get_plugins_for_hook(HookType.TOOL_POST_INVOKE)

        # Execute plugins
        result = await self._post_tool_executor.execute(plugins, payload, global_context, post_tool_invoke, post_tool_matches, local_contexts)

        # Clean up stored context after post-invoke
        if global_context.request_id in self._context_store:
            del self._context_store[global_context.request_id]

        return result
