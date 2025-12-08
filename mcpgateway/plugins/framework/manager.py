# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Mihai Criveti

Plugin manager.
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
    >>> from mcpgateway.plugins.framework.models import GlobalContext
    >>> from mcpgateway.plugins.framework.hooks.prompts import PromptPrehookPayload
    >>> payload = PromptPrehookPayload(prompt_id="123", name="test", args={"user": "input"})
    >>> context = GlobalContext(request_id="123")
    >>> # result, contexts = await manager.prompt_pre_fetch(payload, context)  # Called in async context
"""

# Standard
import asyncio
from copy import deepcopy
import logging
from typing import Any, Optional, Union

# First-Party
from mcpgateway.plugins.framework.base import HookRef, Plugin
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError, PluginViolationError
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.models import Config, GlobalContext, PluginContext, PluginContextTable, PluginErrorModel, PluginMode, PluginPayload, PluginResult
from mcpgateway.plugins.framework.registry import PluginInstanceRegistry
from mcpgateway.plugins.framework.utils import payload_matches

# Use standard logging to avoid circular imports (plugins -> services -> plugins)
logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_PLUGIN_TIMEOUT = 30  # seconds
MAX_PAYLOAD_SIZE = 1_000_000  # 1MB
CONTEXT_CLEANUP_INTERVAL = 300  # 5 minutes
CONTEXT_MAX_AGE = 3600  # 1 hour


class PluginTimeoutError(Exception):
    """Raised when a plugin execution exceeds the timeout limit."""


class PayloadSizeError(ValueError):
    """Raised when a payload exceeds the maximum allowed size."""


class PluginExecutor:
    """Executes a list of plugins with timeout protection and error handling.

    This class manages the execution of plugins in priority order, handling:
    - Timeout protection for each plugin
    - Context management between plugins
    - Error isolation to prevent plugin failures from affecting the gateway
    - Metadata aggregation from multiple plugins

    Examples:
        >>> executor = PluginExecutor()
        >>> # In async context:
        >>> # result, contexts = await executor.execute(
        >>> #     plugins=[plugin1, plugin2],
        >>> #     payload=payload,
        >>> #     global_context=context,
        >>> #     plugin_run=pre_prompt_fetch,
        >>> #     compare=pre_prompt_matches
        >>> # )
    """

    def __init__(self, config: Optional[Config] = None, timeout: int = DEFAULT_PLUGIN_TIMEOUT):
        """Initialize the plugin executor.

        Args:
            timeout: Maximum execution time per plugin in seconds.
            config: the plugin manager configuration.
        """
        self.timeout = timeout
        self.config = config

    async def execute(
        self,
        hook_refs: list[HookRef],
        payload: PluginPayload,
        global_context: GlobalContext,
        hook_type: str,
        local_contexts: Optional[PluginContextTable] = None,
        violations_as_exceptions: bool = False,
    ) -> tuple[PluginResult, PluginContextTable | None]:
        """Execute plugins in priority order with timeout protection.

        Args:
            hook_refs: List of hook references to execute, sorted by priority.
            payload: The payload to be processed by plugins.
            global_context: Shared context for all plugins containing request metadata.
            hook_type: The hook type identifier (e.g., "tool_pre_invoke").
            local_contexts: Optional existing contexts from previous hook executions.
            violations_as_exceptions: Raise violations as exceptions rather than as returns.

        Returns:
            A tuple containing:
            - PluginResult with processing status, modified payload, and metadata
            - PluginContextTable with updated local contexts for each plugin

        Raises:
            PayloadSizeError: If the payload exceeds MAX_PAYLOAD_SIZE.
            PluginError: If there is an error inside a plugin.
            PluginViolationError: If a violation occurs and violation_as_exceptions is set.

        Examples:
            >>> # Execute plugins with timeout protection
            >>> from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
            >>> executor = PluginExecutor(timeout=30)
            >>> # Assuming you have a registry instance:
            >>> # plugins = registry.get_plugins_for_hook(PromptHookType.PROMPT_PRE_FETCH)
            >>> # In async context:
            >>> # result, contexts = await executor.execute(
            >>> #     plugins=plugins,
            >>> #     payload=PromptPrehookPayload(prompt_id="123", name="test", args={}),
            >>> #     global_context=GlobalContext(request_id="123"),
            >>> #     plugin_run=pre_prompt_fetch,
            >>> #     compare=pre_prompt_matches
            >>> # )
        """
        if not hook_refs:
            return (PluginResult(modified_payload=None), None)

        # Validate payload size
        self._validate_payload_size(payload)

        res_local_contexts = {}
        combined_metadata: dict[str, Any] = {}
        current_payload: PluginPayload | None = None

        for hook_ref in hook_refs:
            # Skip disabled plugins
            if hook_ref.plugin_ref.mode == PluginMode.DISABLED:
                continue

            # Check if plugin conditions match current context
            if hook_ref.plugin_ref.conditions and not payload_matches(payload, hook_type, hook_ref.plugin_ref.conditions, global_context):
                logger.debug("Skipping plugin %s - conditions not met", hook_ref.plugin_ref.name)
                continue

            tmp_global_context = GlobalContext(
                request_id=global_context.request_id,
                user=global_context.user,
                tenant_id=global_context.tenant_id,
                server_id=global_context.server_id,
                state={} if not global_context.state else deepcopy(global_context.state),
                metadata={} if not global_context.metadata else deepcopy(global_context.metadata),
            )
            # Get or create local context for this plugin
            local_context_key = global_context.request_id + hook_ref.plugin_ref.uuid
            if local_contexts and local_context_key in local_contexts:
                local_context = local_contexts[local_context_key]
                local_context.global_context = tmp_global_context
            else:
                local_context = PluginContext(global_context=tmp_global_context)
            res_local_contexts[local_context_key] = local_context

            # Execute plugin with timeout protection
            result = await self.execute_plugin(
                hook_ref,
                current_payload or payload,
                local_context,
                violations_as_exceptions,
                global_context,
                combined_metadata,
            )
            # Track payload modifications
            if result.modified_payload is not None:
                current_payload = result.modified_payload
            if not result.continue_processing and hook_ref.plugin_ref.plugin.mode == PluginMode.ENFORCE:
                return (result, res_local_contexts)

        return (
            PluginResult(continue_processing=True, modified_payload=current_payload, violation=None, metadata=combined_metadata),
            res_local_contexts,
        )

    async def execute_plugin(
        self,
        hook_ref: HookRef,
        payload: PluginPayload,
        local_context: PluginContext,
        violations_as_exceptions: bool,
        global_context: Optional[GlobalContext] = None,
        combined_metadata: Optional[dict[str, Any]] = None,
    ) -> PluginResult:
        """Execute a single plugin with timeout protection.

        Args:
            hook_ref: Hooking structure that contains the plugin and hook.
            payload: The payload to be processed by plugins.
            local_context: local context.
            violations_as_exceptions: Raise violations as exceptions rather than as returns.
            global_context: Shared context for all plugins containing request metadata.
            combined_metadata: combination of the metadata of all plugins.

        Returns:
            A tuple containing:
            - PluginResult with processing status, modified payload, and metadata
            - PluginContextTable with updated local contexts for each plugin

        Raises:
            PayloadSizeError: If the payload exceeds MAX_PAYLOAD_SIZE.
            PluginError: If there is an error inside a plugin.
            PluginViolationError: If a violation occurs and violation_as_exceptions is set.
        """
        try:
            # Execute plugin with timeout protection
            result = await self._execute_with_timeout(hook_ref, payload, local_context)
            if local_context.global_context and global_context:
                global_context.state.update(local_context.global_context.state)
                global_context.metadata.update(local_context.global_context.metadata)
            # Aggregate metadata from all plugins
            if result.metadata and combined_metadata is not None:
                combined_metadata.update(result.metadata)

            # Track payload modifications
            # if result.modified_payload is not None:
            #    current_payload = result.modified_payload

            # Set plugin name in violation if present
            if result.violation:
                result.violation.plugin_name = hook_ref.plugin_ref.plugin.name

            # Handle plugin blocking the request
            if not result.continue_processing:
                if hook_ref.plugin_ref.plugin.mode == PluginMode.ENFORCE:
                    logger.warning("Plugin %s blocked request in enforce mode", hook_ref.plugin_ref.plugin.name)
                    if violations_as_exceptions:
                        if result.violation:
                            plugin_name = result.violation.plugin_name
                            violation_reason = result.violation.reason
                            violation_desc = result.violation.description
                            violation_code = result.violation.code
                            raise PluginViolationError(
                                f"{hook_ref.name} blocked by plugin {plugin_name}: {violation_code} - {violation_reason} ({violation_desc})",
                                violation=result.violation,
                            )
                        raise PluginViolationError(f"{hook_ref.name} blocked by plugin")
                    return PluginResult(
                        continue_processing=False,
                        modified_payload=payload,
                        violation=result.violation,
                        metadata=combined_metadata,
                    )
                if hook_ref.plugin_ref.plugin.mode == PluginMode.PERMISSIVE:
                    logger.warning(
                        "Plugin %s would block (permissive mode): %s",
                        hook_ref.plugin_ref.plugin.name,
                        result.violation.description if result.violation else "No description",
                    )
            return result
        except asyncio.TimeoutError as exc:
            logger.error("Plugin %s timed out after %ds", hook_ref.plugin_ref.name, self.timeout)
            if (self.config and self.config.plugin_settings.fail_on_plugin_error) or hook_ref.plugin_ref.plugin.mode == PluginMode.ENFORCE:
                raise PluginError(
                    error=PluginErrorModel(
                        message=f"Plugin {hook_ref.plugin_ref.name} exceeded {self.timeout}s timeout",
                        plugin_name=hook_ref.plugin_ref.name,
                    )
                ) from exc
            # In permissive or enforce_ignore_error mode, continue with next plugin
        except PluginViolationError:
            raise
        except PluginError as pe:
            logger.error("Plugin %s failed with error: %s", hook_ref.plugin_ref.name, str(pe), exc_info=True)
            if (self.config and self.config.plugin_settings.fail_on_plugin_error) or hook_ref.plugin_ref.plugin.mode == PluginMode.ENFORCE:
                raise
        except Exception as e:
            logger.error("Plugin %s failed with error: %s", hook_ref.plugin_ref.name, str(e), exc_info=True)
            if (self.config and self.config.plugin_settings.fail_on_plugin_error) or hook_ref.plugin_ref.plugin.mode == PluginMode.ENFORCE:
                raise PluginError(error=convert_exception_to_error(e, hook_ref.plugin_ref.name)) from e
            # In permissive or enforce_ignore_error mode, continue with next plugin
        # Return a result indicating processing should continue despite the error
        return PluginResult(continue_processing=True)

    async def _execute_with_timeout(self, hook_ref: HookRef, payload: PluginPayload, context: PluginContext) -> PluginResult:
        """Execute a plugin with timeout protection.

        Args:
            hook_ref: Reference to the hook and plugin to execute.
            payload: Payload to process.
            context: Plugin execution context.

        Returns:
            Result from plugin execution.

        Raises:
            asyncio.TimeoutError: If plugin exceeds timeout.
        """
        # Add observability tracing for plugin execution
        try:
            # First-Party
            # pylint: disable=import-outside-toplevel
            from mcpgateway.db import SessionLocal
            from mcpgateway.services.observability_service import current_trace_id, ObservabilityService

            # pylint: enable=import-outside-toplevel

            trace_id = current_trace_id.get()
            if trace_id:
                db = SessionLocal()
                try:
                    service = ObservabilityService()
                    span_id = service.start_span(
                        db=db,
                        trace_id=trace_id,
                        name=f"plugin.execute.{hook_ref.plugin_ref.name}",
                        kind="internal",
                        resource_type="plugin",
                        resource_name=hook_ref.plugin_ref.name,
                        attributes={
                            "plugin.name": hook_ref.plugin_ref.name,
                            "plugin.uuid": hook_ref.plugin_ref.uuid,
                            "plugin.mode": hook_ref.plugin_ref.mode.value if hasattr(hook_ref.plugin_ref.mode, "value") else str(hook_ref.plugin_ref.mode),
                            "plugin.priority": hook_ref.plugin_ref.priority,
                            "plugin.timeout": self.timeout,
                        },
                    )

                    # Execute plugin
                    result = await asyncio.wait_for(hook_ref.hook(payload, context), timeout=self.timeout)

                    # End span with success
                    service.end_span(
                        db=db,
                        span_id=span_id,
                        status="ok",
                        attributes={
                            "plugin.had_violation": result.violation is not None,
                            "plugin.modified_payload": result.modified_payload is not None,
                        },
                    )
                    return result
                finally:
                    db.close()
            else:
                # No active trace, execute without instrumentation
                return await asyncio.wait_for(hook_ref.hook(payload, context), timeout=self.timeout)

        except Exception as e:
            # If observability setup fails, continue without instrumentation
            logger.debug(f"Plugin observability setup failed: {e}")
            return await asyncio.wait_for(hook_ref.hook(payload, context), timeout=self.timeout)

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
        >>> from mcpgateway.plugins.framework.models import GlobalContext
        >>> from mcpgateway.plugins.framework.hooks.prompts import PromptPrehookPayload
        >>> payload = PromptPrehookPayload(prompt_id="123", name="test", args={})
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
    _executor: PluginExecutor = PluginExecutor()

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
        self._executor.config = self._config
        self._executor.timeout = timeout

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

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get a plugin by name.

        Args:
            name: the name of the plugin to return.

        Returns:
            A plugin.
        """
        plugin_ref = self._registry.get_plugin(name)
        return plugin_ref.plugin if plugin_ref else None

    async def initialize(self) -> None:
        """Initialize the plugin manager and load all configured plugins.

        This method:
        1. Loads plugin configurations from the config file
        2. Instantiates each enabled plugin
        3. Registers plugins with the registry
        4. Validates plugin initialization

        Raises:
            RuntimeError: If plugin initialization fails with an exception.
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
            try:
                # For disabled plugins, create a stub plugin without full instantiation
                if plugin_config.mode != PluginMode.DISABLED:
                    # Fully instantiate enabled plugins
                    plugin = await self._loader.load_and_instantiate_plugin(plugin_config)
                    if plugin:
                        self._registry.register(plugin)
                        loaded_count += 1
                        logger.info("Loaded plugin: %s (mode: %s)", plugin_config.name, plugin_config.mode)
                    else:
                        raise ValueError(f"Unable to instantiate plugin: {plugin_config.name}")
                else:
                    logger.info("Plugin: %s is disabled. Ignoring.", plugin_config.name)

            except Exception as e:
                # Clean error message without stack trace spam
                logger.error("Failed to load plugin %s: {%s}", plugin_config.name, str(e))
                # Let it crash gracefully with a clean error
                raise RuntimeError(f"Plugin initialization failed: {plugin_config.name} - {str(e)}") from e

        self._initialized = True
        logger.info("Plugin manager initialized with %s plugins", loaded_count)

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

        # Reset state
        self._initialized = False
        logger.info("Plugin manager shutdown complete")

    async def invoke_hook(
        self,
        hook_type: str,
        payload: PluginPayload,
        global_context: GlobalContext,
        local_contexts: Optional[PluginContextTable] = None,
        violations_as_exceptions: bool = False,
    ) -> tuple[PluginResult, PluginContextTable | None]:
        """Invoke a set of plugins configured for the hook point in priority order.

        Args:
            hook_type: The type of hook to execute.
            payload: The plugin payload for which the plugins will analyze and modify.
            global_context: Shared context for all plugins with request metadata.
            local_contexts: Optional existing contexts from previous hook executions.
            violations_as_exceptions: Raise violations as exceptions rather than as returns.

        Returns:
            A tuple containing:
            - PluginResult with processing status and modified payload
            - PluginContextTable with plugin contexts for state management

        Examples:
            >>> manager = PluginManager("plugins/config.yaml")
            >>> # In async context:
            >>> # await manager.initialize()
            >>> # payload = ResourcePreFetchPayload("file:///data.txt")
            >>> # context = GlobalContext(request_id="123", server_id="srv1")
            >>> # result, contexts = await manager.resource_pre_fetch(payload, context)
            >>> # if result.continue_processing:
            >>> #     # Use modified payload
            >>> #     uri = result.modified_payload.uri
        """
        # Get plugins configured for this hook
        hook_refs = self._registry.get_hook_refs_for_hook(hook_type=hook_type)

        # Execute plugins
        result = await self._executor.execute(hook_refs, payload, global_context, hook_type, local_contexts, violations_as_exceptions)

        return result

    async def invoke_hook_for_plugin(
        self,
        name: str,
        hook_type: str,
        payload: Union[PluginPayload, dict[str, Any], str],
        context: PluginContext,
        violations_as_exceptions: bool = False,
        payload_as_json: bool = False,
    ) -> PluginResult:
        """Invoke a specific hook for a single named plugin.

        This method allows direct invocation of a particular plugin's hook by name,
        bypassing the normal priority-ordered execution. Useful for testing individual
        plugins or when specific plugin behavior needs to be triggered independently.

        Args:
            name: The name of the plugin to invoke.
            hook_type: The type of hook to execute (e.g., "prompt_pre_fetch").
            payload: The plugin payload to be processed by the hook.
            context: Plugin execution context with local and global state.
            violations_as_exceptions: Raise violations as exceptions rather than returns.
            payload_as_json: payload passed in as json rather than pydantic.

        Returns:
            PluginResult with processing status, modified payload, and metadata.

        Raises:
            PluginError: If the plugin or hook type cannot be found in the registry.
            ValueError: If payload type does not match payload_as_json setting.

        Examples:
            >>> manager = PluginManager("plugins/config.yaml")
            >>> # In async context:
            >>> # await manager.initialize()
            >>> # payload = PromptPrehookPayload(name="test", args={})
            >>> # context = PluginContext(global_context=GlobalContext(request_id="123"))
            >>> # result = await manager.invoke_hook_for_plugin(
            >>> #     name="auth_plugin",
            >>> #     hook_type="prompt_pre_fetch",
            >>> #     payload=payload,
            >>> #     context=context
            >>> # )
        """
        hook_ref = self._registry.get_plugin_hook_by_name(name, hook_type)
        if not hook_ref:
            raise PluginError(
                error=PluginErrorModel(
                    message=f"Unable to find {hook_type} for plugin {name}.  Make sure the plugin is registered.",
                    plugin_name=name,
                )
            )
        if payload_as_json:
            plugin = hook_ref.plugin_ref.plugin
            # When payload_as_json=True, payload should be str or dict
            if isinstance(payload, (str, dict)):
                pydantic_payload = plugin.json_to_payload(hook_type, payload)
                return await self._executor.execute_plugin(hook_ref, pydantic_payload, context, violations_as_exceptions)
            raise ValueError(f"When payload_as_json=True, payload must be str or dict, got {type(payload)}")
        # When payload_as_json=False, payload should already be a PluginPayload
        if not isinstance(payload, PluginPayload):
            raise ValueError(f"When payload_as_json=False, payload must be a PluginPayload, got {type(payload)}")
        return await self._executor.execute_plugin(hook_ref, payload, context, violations_as_exceptions)
