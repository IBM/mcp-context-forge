# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Mihai Criveti, Fred Araujo

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
import logging
import threading
from typing import Any, Optional, Union

# First-Party
from mcpgateway.plugins.framework.base import AttachedHookRef, HookRef, Plugin
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError, PluginViolationError
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.memory import copyonwrite
from mcpgateway.plugins.framework.models import (
    Config,
    EntityType,
    GlobalContext,
    PluginConfig,
    PluginContext,
    PluginContextTable,
    PluginErrorModel,
    PluginMode,
    PluginPayload,
    PluginResult,
)
from mcpgateway.plugins.framework.registry import PluginInstanceRegistry
from mcpgateway.plugins.framework.routing import EvaluationContext
from mcpgateway.plugins.framework.routing.rule_resolver import RuleBasedResolver, RuleMatchContext
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
        hook_refs: list[AttachedHookRef],
        payload: PluginPayload,
        global_context: GlobalContext,
        hook_type: str,
        local_contexts: Optional[PluginContextTable] = None,
        violations_as_exceptions: bool = False,
    ) -> tuple[PluginResult, PluginContextTable | None]:
        """Execute plugins in priority order with timeout protection.

        Args:
            hook_refs: List of AttachedHookRef to execute, sorted by priority.
                      AttachedHookRef.attachment may be None for non-routed plugins.
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

        for attached_hook_ref in hook_refs:
            # Extract the actual HookRef
            hook_ref = attached_hook_ref.hook_ref

            # Skip disabled plugins
            if hook_ref.plugin_ref.mode == PluginMode.DISABLED:
                continue

            # Check if plugin conditions match current context
            if hook_ref.plugin_ref.conditions and not payload_matches(payload, hook_type, hook_ref.plugin_ref.conditions, global_context):
                logger.debug("Skipping plugin %s - conditions not met", hook_ref.plugin_ref.name)
                continue

            # Build metadata combining global context metadata + attachment metadata
            merged_metadata = {} if not global_context.metadata else copyonwrite(global_context.metadata)

            # Merge attachment config/metadata if present
            if attached_hook_ref.attachment and attached_hook_ref.attachment.config:
                # Add attachment metadata with prefix to avoid conflicts
                attachment_meta = {
                    "_attachment": {
                        "name": attached_hook_ref.attachment.name,
                        "priority": attached_hook_ref.attachment.priority,
                        "config": attached_hook_ref.attachment.config,
                    }
                }
                merged_metadata.update(attachment_meta)

            tmp_global_context = GlobalContext(
                request_id=global_context.request_id,
                user=global_context.user,
                tenant_id=global_context.tenant_id,
                server_id=global_context.server_id,
                entity_type=global_context.entity_type,
                entity_id=global_context.entity_id,
                entity_name=global_context.entity_name,
                attachment_config=attached_hook_ref.attachment,  # Will be None for old system
                state={} if not global_context.state else copyonwrite(global_context.state),
                metadata=merged_metadata,
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

    This class implements a thread-safe Borg singleton pattern to ensure consistent
    plugin management across the application. It handles:
    - Plugin discovery and loading from configuration
    - Plugin lifecycle management (initialization, execution, shutdown)
    - Context management with automatic cleanup
    - Hook execution orchestration
    - Cached plugin routing resolution

    Thread Safety:
        Uses double-checked locking to prevent race conditions when multiple threads
        create PluginManager instances simultaneously. The first instance to acquire
        the lock loads the configuration; subsequent instances reuse the shared state.

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
    __lock: threading.Lock = threading.Lock()  # Thread safety for synchronous init
    _async_lock: asyncio.Lock | None = None  # Async lock for initialize/shutdown
    _loader: PluginLoader = PluginLoader()
    _initialized: bool = False
    _registry: PluginInstanceRegistry = PluginInstanceRegistry()
    _config: Config | None = None
    _config_path: str | None = None
    _executor: PluginExecutor = PluginExecutor()
    _resolver: RuleBasedResolver = RuleBasedResolver()
    # Cache for resolved AttachedHookRefs: (entity_type, entity_name, hook_type) -> list[AttachedHookRef]
    _routing_cache: dict[tuple[str, str, str], list[AttachedHookRef]] = {}

    def __init__(self, config: str = "", timeout: int = DEFAULT_PLUGIN_TIMEOUT):
        """Initialize plugin manager.

        PluginManager implements a thread-safe Borg singleton:
            - Shared state is initialized only once across all instances.
            - Subsequent instantiations reuse same state and skip config reload.
            - Uses double-checked locking to prevent race conditions in multi-threaded environments.

        Thread Safety:
            The initialization uses a double-checked locking pattern to ensure that
            config loading only happens once, even when multiple threads create
            PluginManager instances simultaneously.

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

        # Only initialize once (first instance when shared state is empty)
        # Use lock to prevent race condition in multi-threaded environments
        if not self.__shared_state:
            with self.__lock:
                # Double-check after acquiring lock (another thread may have initialized)
                if not self.__shared_state:
                    if config:
                        self._config = ConfigLoader.load_config(config)
                        self._config_path = config

                    # Update executor timeouts
                    self._executor.config = self._config
                    self._executor.timeout = timeout

    @classmethod
    def reset(cls) -> None:
        """Reset the Borg pattern shared state.

        This method clears all shared state, allowing a fresh PluginManager
        instance to be created with new configuration. Primarily used for testing.

        Thread-safe: Uses lock to ensure atomic reset operation.

        Examples:
            >>> # Between tests, reset shared state
            >>> PluginManager.reset()
            >>> manager = PluginManager("new_config.yaml")
        """
        with cls.__lock:
            cls.__shared_state.clear()
            cls._initialized = False
            cls._config = None
            cls._config_path = None
            cls._async_lock = None

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

    def has_hooks_for(self, hook_type: str) -> bool:
        """Check if there are any hooks registered for a specific hook type.

        Args:
            hook_type: The type of hook to check for.

        Returns:
            True if there are hooks registered for the specified type, False otherwise.
        """
        return self._registry.has_hooks_for(hook_type)

    def get_plugin_names(self) -> list[str]:
        """Get list of all configured plugin names.

        Returns:
            List of plugin names from the configuration (includes disabled plugins).
        """
        if not self._config or not self._config.plugins:
            return []
        return [plugin.name for plugin in self._config.plugins]

    def get_plugins_for_entity_type(self, entity_type: str) -> list:
        """Get plugins that have hooks for the specified entity type.

        Uses the hook registry to determine which hooks belong to the entity type.

        Args:
            entity_type: Entity type ('tool', 'prompt', 'resource', 'http', etc.)

        Returns:
            List of PluginConfig objects that have hooks for this entity type.
        """
        if not self._config or not self._config.plugins:
            return []

        # First-Party
        from mcpgateway.plugins.framework.hooks.registry import get_hook_registry

        registry = get_hook_registry()
        entity_hooks = set(registry.get_hooks_for_entity_type(entity_type))

        if not entity_hooks:
            return []

        return [plugin for plugin in self._config.plugins if any(hook in entity_hooks for hook in plugin.hooks)]

    def get_tool_plugins(self) -> list:
        """Get all plugins that have tool hooks.

        Returns:
            List of PluginConfig objects with tool hooks.
        """
        return self.get_plugins_for_entity_type("tool")

    def get_plugins_with_hook_info(self, entity_type: str) -> list:
        """Get plugins for entity type with hook phase information.

        Args:
            entity_type: Entity type ('tool', 'prompt', 'resource', etc.)

        Returns:
            List of PluginWithHookInfo objects with hook details.
        """
        # First-Party
        from mcpgateway.plugins.framework.hooks.registry import get_hook_registry
        from mcpgateway.plugins.framework.models import PluginWithHookInfo

        registry = get_hook_registry()
        plugins = self.get_plugins_for_entity_type(entity_type)
        entity_hooks = set(registry.get_hooks_for_entity_type(entity_type))

        result = []
        for plugin in plugins:
            # Filter to only hooks for this entity type
            plugin_entity_hooks = [h for h in plugin.hooks if h in entity_hooks]

            pre_hooks = []
            post_hooks = []
            for hook in plugin_entity_hooks:
                if registry.is_pre_hook(hook):
                    pre_hooks.append(hook)
                elif registry.is_post_hook(hook):
                    post_hooks.append(hook)

            result.append(PluginWithHookInfo(name=plugin.name, description=plugin.description, pre_hooks=pre_hooks, post_hooks=post_hooks, all_hooks=plugin_entity_hooks))

        return result

    def get_tool_plugins_with_hooks(self) -> list:
        """Get tool plugins with hook phase information.

        Returns:
            List of PluginWithHookInfo objects for tools.
        """
        return self.get_plugins_with_hook_info("tool")

    def get_prompt_plugins(self) -> list:
        """Get all plugins that have prompt hooks.

        Returns:
            List of PluginConfig objects with prompt hooks.
        """
        return self.get_plugins_for_entity_type("prompt")

    def get_resource_plugins(self) -> list:
        """Get all plugins that have resource hooks.

        Returns:
            List of PluginConfig objects with resource hooks.
        """
        return self.get_plugins_for_entity_type("resource")

    def get_http_plugins(self) -> list:
        """Get all plugins that have HTTP-level hooks.

        Returns:
            List of PluginConfig objects with HTTP hooks.
        """
        return self.get_plugins_for_entity_type("http")

    async def initialize(self) -> None:
        """Initialize the plugin manager and load all configured plugins.

        This method:
        1. Loads plugin configurations from the config file
        2. Instantiates each enabled plugin
        3. Registers plugins with the registry
        4. Validates plugin initialization

        Thread Safety:
            Uses asyncio.Lock to prevent concurrent initialization from multiple
            coroutines or async tasks. Combined with threading.Lock in __init__
            for full multi-threaded safety.

        Raises:
            RuntimeError: If plugin initialization fails with an exception.
            ValueError: If a plugin cannot be initialized or registered.

        Examples:
            >>> manager = PluginManager("plugins/config.yaml")
            >>> # In async context:
            >>> # await manager.initialize()
            >>> # Manager is now ready to execute plugins
        """
        # Initialize async lock lazily (can't create asyncio.Lock in class definition)
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()

        async with self._async_lock:
            # Double-check after acquiring lock
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

        Thread Safety:
            Uses asyncio.Lock to prevent concurrent shutdown with initialization
            or with another shutdown call.

        Note: The config is preserved to allow modifying settings and re-initializing.
        To fully reset for a new config, create a new PluginManager instance.

        Examples:
            >>> manager = PluginManager("plugins/config.yaml")
            >>> # In async context:
            >>> # await manager.initialize()
            >>> # ... use the manager ...
            >>> # await manager.shutdown()
        """
        # Initialize async lock lazily if needed
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()

        async with self._async_lock:
            if not self._initialized:
                logger.debug("Plugin manager not initialized, nothing to shutdown")
                return

            logger.info("Shutting down plugin manager")

            # Shutdown all plugins
            await self._registry.shutdown()

            # Clear routing cache
            self.clear_routing_cache()

            # Reset state to allow re-initialization
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

        Automatically uses resource-centric routing if:
        - enable_plugin_routing is True in config
        - global_context has entity_type and entity_name set

        Args:
            hook_type: The type of hook to execute.
            payload: The plugin payload for which the plugins will analyze and modify.
            global_context: Shared context for all plugins with request metadata.
                           Include entity_type and entity_name for resource-centric routing.
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
            >>> # With resource-centric routing:
            >>> # context = GlobalContext(
            >>> #     request_id="123",
            >>> #     server_id="srv1",
            >>> #     entity_type="tool",
            >>> #     entity_name="my_tool"
            >>> # )
            >>> # result, contexts = await manager.invoke_hook("tool_pre_invoke", payload, context)
        """
        # Determine which plugin resolution system to use
        use_routing = self._config and self._config.plugin_settings.enable_plugin_routing and global_context.entity_type and global_context.entity_name

        if use_routing:
            # New resource-centric routing system (returns list[AttachedHookRef])
            # Pass payload for enhanced runtime filtering (creates plugin instances as needed)
            attached_refs = await self._resolve_with_routing(hook_type, global_context, payload)
        else:
            # Old condition-based system (returns list[HookRef], wrap them)
            hook_refs = self._registry.get_hook_refs_for_hook(hook_type=hook_type)
            # Wrap in AttachedHookRef with attachment=None
            attached_refs = [AttachedHookRef(hook_ref, attachment=None) for hook_ref in hook_refs]

        # Execute plugins
        result = await self._executor.execute(attached_refs, payload, global_context, hook_type, local_contexts, violations_as_exceptions)

        return result

    async def _resolve_with_routing(
        self,
        hook_type: str,
        global_context: GlobalContext,
        payload: Optional[PluginPayload] = None,
    ) -> list[AttachedHookRef]:
        """Resolve plugins using the resource-centric routing system with caching.

        Uses two-level resolution:
        1. Static resolution (cached): Match rules, look up HookRefs, create AttachedHookRefs
           - Creates plugin instances with merged configs as needed
        2. Runtime filtering: Evaluate 'when' clauses from PluginAttachments with actual payload

        Args:
            hook_type: The type of hook to execute.
            global_context: Shared context with entity_type and entity_name.
            payload: Optional plugin payload for enhanced runtime filtering.

        Returns:
            List of AttachedHookRef objects (HookRef + PluginAttachment) sorted by priority,
            filtered by runtime 'when' clause evaluation.
        """
        if not self._config or not global_context.entity_type or not global_context.entity_name:
            return []

        # Map string entity_type to EntityType enum
        try:
            entity_type = EntityType(global_context.entity_type)
        except ValueError:
            logger.warning(f"Unknown entity_type: {global_context.entity_type}. Falling back to registry.")
            # Return empty list since we can't do routing without valid entity_type
            return []

        # Check cache first
        # Include infrastructure filters in cache key since rules can match based on these
        cache_key = (
            global_context.entity_type,
            global_context.entity_name,
            hook_type,
            global_context.server_name,
            global_context.server_id,
            global_context.gateway_id,
        )

        if cache_key in self._routing_cache:
            static_refs = self._routing_cache[cache_key]
            logger.debug(f"Using cached routing for {global_context.entity_type}:{global_context.entity_name} " f"hook={hook_type} ({len(static_refs)} refs)")
        else:
            # Perform static resolution (no 'when' evaluation, creates instances as needed)
            static_refs = await self._resolve_static(hook_type, global_context, entity_type)

            # Cache the result
            self._routing_cache[cache_key] = static_refs
            logger.debug(f"Cached routing for {global_context.entity_type}:{global_context.entity_name} " f"hook={hook_type} ({len(static_refs)} refs)")

        # Apply runtime filtering (evaluate 'when' clauses from attachments with actual payload)
        filtered_refs = self._filter_attachments_runtime(static_refs, global_context, payload)

        return filtered_refs

    def _get_base_plugin_config_dict(self, plugin_name: str) -> dict:
        """Get base configuration dict for a plugin by name from registry.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            Base plugin config dict, or empty dict if not found.
        """
        plugin_ref = self._registry.get_plugin(plugin_name)
        if plugin_ref and plugin_ref.plugin.config:
            # plugin.config is a PluginConfig model, get the config dict from it
            return plugin_ref.plugin.config.config or {}
        return {}

    def _get_plugin_config(self, plugin_name: str) -> Optional[PluginConfig]:
        """Get full PluginConfig for a plugin by name.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            PluginConfig or None if not found.
        """
        if not self._config or not self._config.plugins:
            return None

        for plugin_config in self._config.plugins:
            if plugin_config.name == plugin_name:
                return plugin_config

        return None

    async def _resolve_static(
        self,
        hook_type: str,
        global_context: GlobalContext,
        entity_type: EntityType,
    ) -> list[AttachedHookRef]:
        """Resolve AttachedHookRefs statically (no 'when' evaluation).

        Creates plugin instances with merged configs as needed.

        Args:
            hook_type: The type of hook to execute.
            global_context: Shared context with entity info.
            entity_type: Entity type enum.

        Returns:
            List of AttachedHookRef objects with 'when' clauses preserved for runtime eval.
        """
        # Build rule match context for resolver
        match_context = RuleMatchContext(
            name=global_context.entity_name or "",
            entity_type=global_context.entity_type or "",
            entity_id=global_context.entity_id,
            tags=global_context.tags or [],
            metadata=global_context.metadata or {},
            server_name=global_context.server_name,
            server_id=global_context.server_id,
            gateway_id=global_context.gateway_id,
            payload={},  # Will be populated during runtime filtering if needed
        )

        # Get rules from config
        rules = self._config.routes if self._config else []

        # Get merge strategy from plugin settings
        merge_strategy = "most_specific"  # default
        if self._config and self._config.plugin_settings:
            merge_strategy = self._config.plugin_settings.rule_merge_strategy

        # Use resolver to get sorted plugin attachments (with 'when' clauses preserved)
        plugin_attachments = self._resolver.resolve_for_entity(
            rules=rules,
            context=match_context,
            hook_type=hook_type,
            eval_context=None,  # Don't evaluate 'when' clauses during static resolution
            merge_strategy=merge_strategy,
        )

        # Convert PluginAttachment + HookRef -> AttachedHookRef
        # with config merging and instance key creation
        # First-Party
        from mcpgateway.plugins.framework.utils import deep_merge, hash_config

        attached_refs: list[AttachedHookRef] = []
        for attachment in plugin_attachments:
            # Merge configs and create instance key
            base_config = self._get_base_plugin_config_dict(attachment.name)

            if attachment.override:
                # Replace base config entirely
                merged_config = attachment.config
            else:
                # Deep merge rule config with base config
                merged_config = deep_merge(base_config, attachment.config)

            # Create instance key that includes hooks and mode overrides
            # This ensures different instances are created when hooks or mode differ
            instance_data = {
                "config": merged_config,
                "hooks": attachment.hooks if attachment.hooks else None,
                "mode": attachment.mode if attachment.mode else None,
            }
            config_hash = hash_config(instance_data)
            instance_key = f"{attachment.name}:{config_hash}"

            # Store instance key in attachment for caching
            attachment.instance_key = instance_key

            # Check if instance exists, if not create it
            if not self._registry.get_plugin(instance_key):
                # Get base plugin config to create new instance
                base_plugin_config = self._get_plugin_config(attachment.name)
                if base_plugin_config:
                    try:
                        # Build update dict with all available overrides from PluginAttachment
                        updates: dict[str, Any] = {"config": merged_config}
                        if attachment.hooks:
                            updates["hooks"] = attachment.hooks
                        if attachment.mode:
                            updates["mode"] = attachment.mode

                        # Create new PluginConfig with all overrides
                        # Pydantic v2: use model_copy with update
                        new_config = base_plugin_config.model_copy(update=updates)

                        # Instantiate plugin with merged config (async)
                        plugin = await self._loader.load_and_instantiate_plugin(new_config)

                        if plugin:
                            # Register with instance key
                            self._registry.register(plugin, instance_key)
                            logger.info(f"Created plugin instance {instance_key} with merged config")
                        else:
                            logger.warning(f"Failed to instantiate plugin {instance_key}, falling back to base")
                            instance_key = attachment.name
                    except Exception as e:
                        logger.error(f"Error instantiating plugin {instance_key}: {e}, falling back to base")
                        instance_key = attachment.name
                else:
                    logger.warning(f"Base plugin config not found for {attachment.name}, falling back to base")
                    instance_key = attachment.name

            # Look up plugin hook by instance key
            hook_ref = self._registry.get_plugin_hook_by_name(instance_key, hook_type)
            if hook_ref:
                # Create composite object pairing HookRef with its attachment config
                attached_ref = AttachedHookRef(hook_ref, attachment)
                attached_refs.append(attached_ref)
            else:
                logger.warning(
                    f"Plugin '{attachment.name}' (instance: {instance_key}) configured for {global_context.entity_type}:{global_context.entity_name} " f"but not found in registry. Skipping."
                )

        return attached_refs

    def _filter_attachments_runtime(
        self,
        attached_refs: list[AttachedHookRef],
        global_context: GlobalContext,
        payload: Optional[PluginPayload] = None,
    ) -> list[AttachedHookRef]:
        """Filter AttachedHookRefs at runtime by evaluating 'when' clauses.

        Extracts args, payload dict, and other data from the actual payload for
        enhanced 'when' clause evaluation.

        Args:
            attached_refs: Pre-resolved AttachedHookRefs from cache.
            global_context: Runtime context for evaluation.
            payload: Optional plugin payload for extracting args/payload dict.

        Returns:
            Filtered list of AttachedHookRefs.
        """
        # First-Party
        from mcpgateway.plugins.framework.routing.evaluator import PolicyEvaluator

        filtered = []
        evaluator = PolicyEvaluator()

        # Extract data from payload for evaluation context
        args_dict = {}
        payload_dict = {}
        tags_list = []

        if payload:
            # Extract args if available (tools, prompts, agents)
            if hasattr(payload, "args") and payload.args:
                args_dict = payload.args if isinstance(payload.args, dict) else {}

            # Extract tags if available
            if hasattr(payload, "tags") and payload.tags:
                tags_list = payload.tags if isinstance(payload.tags, list) else []

            # Convert payload to dict for full access
            try:
                payload_dict = payload.model_dump() if hasattr(payload, "model_dump") else {}
            except Exception as e:
                logger.debug(f"Could not convert payload to dict: {e}")
                payload_dict = {}

        for attached_ref in attached_refs:
            # Check if attachment has a 'when' clause
            if attached_ref.attachment and attached_ref.attachment.when:
                # Build evaluation context from global_context + payload
                eval_context = EvaluationContext(
                    name=global_context.entity_name or "",
                    entity_type=global_context.entity_type or "",
                    entity_id=global_context.entity_id,
                    tags=tags_list,
                    metadata=global_context.metadata or {},
                    server_name=None,  # TODO: Resolve server name from server_id
                    server_id=global_context.server_id,
                    gateway_id=None,  # TODO: Get gateway_id if available
                    args=args_dict,
                    payload=payload_dict,
                    user=global_context.user,
                    tenant_id=global_context.tenant_id,
                )

                try:
                    if not evaluator.evaluate(attached_ref.attachment.when, eval_context):
                        logger.debug(f"Skipping plugin {attached_ref.hook_ref.plugin_ref.name}: " f"when clause '{attached_ref.attachment.when}' evaluated to False")
                        continue
                except Exception as e:
                    logger.error(f"Failed to evaluate when clause for plugin {attached_ref.hook_ref.plugin_ref.name}: {e}. " "Skipping plugin.")
                    continue

            filtered.append(attached_ref)

        return filtered

    def clear_routing_cache(self):
        """Clear the plugin routing resolution cache.

        Use this when configuration changes at runtime or plugins are reloaded.

        Examples:
            >>> manager = PluginManager()
            >>> manager.clear_routing_cache()
        """
        self._routing_cache.clear()
        logger.info("Cleared plugin routing cache")

    def reload_config(self):
        """Reload plugin configuration from disk and update manager state.

        This reloads the configuration from the stored config path, updates the executor
        with the fresh config, and clears the routing cache. Use this when the config
        file has been modified externally (e.g., by another worker process).

        Examples:
            >>> manager = PluginManager()
            >>> manager.reload_config()
        """
        if not self._config_path:
            logger.warning("Cannot reload config: no config path stored")
            return

        self._config = ConfigLoader.load_config(self._config_path)
        self._executor.config = self._config
        self.clear_routing_cache()
        logger.info("Reloaded plugin configuration from %s", self._config_path)

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
