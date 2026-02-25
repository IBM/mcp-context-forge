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
import copy
import logging
import threading
from typing import Any, Optional, Union

# Third-Party
from pydantic import BaseModel, RootModel

# First-Party
from mcpgateway.plugins.framework.base import HookRef, Plugin
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError, PluginViolationError
from mcpgateway.plugins.framework.hooks.policies import apply_policy, DefaultHookPolicy, HookPayloadPolicy
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.memory import copyonwrite
from mcpgateway.plugins.framework.models import Config, GlobalContext, PluginContext, PluginContextTable, PluginErrorModel, PluginMode, PluginPayload, PluginResult
from mcpgateway.plugins.framework.observability import current_trace_id, ObservabilityProvider
from mcpgateway.plugins.framework.registry import PluginInstanceRegistry
from mcpgateway.plugins.framework.settings import settings
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

    def __init__(
        self,
        config: Optional[Config] = None,
        timeout: int = DEFAULT_PLUGIN_TIMEOUT,
        observability: Optional[ObservabilityProvider] = None,
        hook_policies: Optional[dict[str, HookPayloadPolicy]] = None,
    ):
        """Initialize the plugin executor.

        Args:
            config: the plugin manager configuration.
            timeout: Maximum execution time per plugin in seconds.
            observability: Optional observability provider implementing ObservabilityProvider protocol.
            hook_policies: Per-hook-type payload modification policies.
        """
        self.timeout = timeout
        self.config = config
        self.observability = observability
        self.hook_policies: dict[str, HookPayloadPolicy] = hook_policies or {}
        self.default_hook_policy = DefaultHookPolicy(settings.default_hook_policy)

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

        # Look up the policy for this hook type (may be None)
        policy = self.hook_policies.get(hook_type)

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
                state={} if not global_context.state else copyonwrite(global_context.state),
                metadata={} if not global_context.metadata else copyonwrite(global_context.metadata),
            )
            # Get or create local context for this plugin
            local_context_key = global_context.request_id + hook_ref.plugin_ref.uuid
            if local_contexts and local_context_key in local_contexts:
                local_context = local_contexts[local_context_key]
                local_context.global_context = tmp_global_context
            else:
                local_context = PluginContext(global_context=tmp_global_context)
            res_local_contexts[local_context_key] = local_context

            # When a policy exists or default=deny is active, deep-copy the
            # payload before handing it to the plugin.  The plugin operates on
            # the copy, so in-place nested mutations (e.g. payload.args[k]=v)
            # cannot pollute the live chain.  model_copy(deep=True) is used
            # for Pydantic models; copy.deepcopy handles plain dicts that
            # arrive via cross-type hooks (e.g. http_auth_resolve_user).
            effective_payload = current_payload if current_payload is not None else payload
            # RootModel subclasses (e.g. HttpHeaderPayload) wrap mutable containers
            # that bypass the frozen=True constraint via __setitem__, so they must
            # always be deep-copied to prevent in-place corruption of the live chain.
            needs_isolation = policy or self.default_hook_policy == DefaultHookPolicy.DENY or isinstance(effective_payload, RootModel)
            if needs_isolation:
                plugin_input = effective_payload.model_copy(deep=True) if isinstance(effective_payload, BaseModel) else copy.deepcopy(effective_payload)
            else:
                plugin_input = effective_payload

            # Execute plugin with timeout protection
            result = await self.execute_plugin(
                hook_ref,
                plugin_input,
                local_context,
                violations_as_exceptions,
                global_context,
                combined_metadata,
            )

            # Apply policy-based controlled merge (per-plugin)
            if result.modified_payload is not None:
                if policy:
                    if isinstance(result.modified_payload, type(effective_payload)) and isinstance(effective_payload, BaseModel):
                        # Same-type BaseModel payload — apply field-level policy filtering
                        filtered = apply_policy(
                            effective_payload,
                            result.modified_payload,
                            policy,
                        )
                        if filtered is not None:
                            current_payload = filtered
                    else:
                        # Cross-type payload (e.g. HTTP hooks returning a different
                        # result type than the input).  Field-level filtering is not
                        # applicable; the policy's presence authorises the hook.
                        # Guard: only accept PluginPayload subtypes or dict (used
                        # by http_auth_resolve_user and similar hooks).
                        if isinstance(result.modified_payload, (PluginPayload, dict)):
                            logger.debug(
                                "Plugin %s returned cross-type payload (%s -> %s) on hook %s; accepting without field filtering",
                                hook_ref.plugin_ref.name,
                                type(effective_payload).__name__,
                                type(result.modified_payload).__name__,
                                hook_type,
                            )
                            current_payload = result.modified_payload
                        else:
                            logger.warning(
                                "Plugin %s returned unexpected type %s on hook %s; ignoring modification",
                                hook_ref.plugin_ref.name,
                                type(result.modified_payload).__name__,
                                hook_type,
                            )
                elif self.default_hook_policy == DefaultHookPolicy.ALLOW:
                    # No explicit policy + default=allow -- accept all modifications
                    current_payload = result.modified_payload
                else:
                    # No explicit policy + default=deny -- reject all modifications
                    logger.warning(
                        "Plugin %s attempted payload modification on hook %s but no policy is defined and default is deny",
                        hook_ref.plugin_ref.name,
                        hook_type,
                    )

            # Both ENFORCE and ENFORCE_IGNORE_ERROR honour continue_processing=False
            # and halt the chain.  They differ only in error handling: ENFORCE raises
            # on plugin errors/timeouts, while ENFORCE_IGNORE_ERROR swallows them and
            # lets the chain continue (see execute_plugin exception handlers).
            if not result.continue_processing and hook_ref.plugin_ref.mode in (PluginMode.ENFORCE, PluginMode.ENFORCE_IGNORE_ERROR):
                return (
                    PluginResult(
                        continue_processing=False,
                        modified_payload=current_payload,
                        violation=result.violation,
                        metadata=combined_metadata,
                    ),
                    res_local_contexts,
                )

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
            # Only merge global state for enforce modes; permissive plugins
            # operate on copy-on-write snapshots and should not mutate shared state.
            if local_context.global_context and global_context and hook_ref.plugin_ref.mode in (PluginMode.ENFORCE, PluginMode.ENFORCE_IGNORE_ERROR):
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
                if hook_ref.plugin_ref.mode == PluginMode.ENFORCE:
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
                if hook_ref.plugin_ref.mode == PluginMode.PERMISSIVE:
                    logger.warning(
                        "Plugin %s would block (permissive mode): %s",
                        hook_ref.plugin_ref.plugin.name,
                        result.violation.description if result.violation else "No description",
                    )
            return result
        except asyncio.TimeoutError as exc:
            logger.error("Plugin %s timed out after %ds", hook_ref.plugin_ref.name, self.timeout)
            if (self.config and self.config.plugin_settings.fail_on_plugin_error) or hook_ref.plugin_ref.mode == PluginMode.ENFORCE:
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
            logger.error("Plugin %s failed with error: %s", hook_ref.plugin_ref.name, str(pe))
            if (self.config and self.config.plugin_settings.fail_on_plugin_error) or hook_ref.plugin_ref.mode == PluginMode.ENFORCE:
                raise
        except Exception as e:
            logger.error("Plugin %s failed with error: %s", hook_ref.plugin_ref.name, str(e))
            if (self.config and self.config.plugin_settings.fail_on_plugin_error) or hook_ref.plugin_ref.mode == PluginMode.ENFORCE:
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
            asyncio.CancelledError: If plugin execution is cancelled.
            Exception: Re-raised from plugin hook execution failures.
        """
        # Start observability span if tracing is active
        trace_id = current_trace_id.get()
        span_id = None

        if trace_id and self.observability:
            try:
                span_id = self.observability.start_span(
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
            except Exception as e:
                logger.debug("Plugin observability start_span failed: %s", e)

        # Execute plugin
        try:
            result = await asyncio.wait_for(hook_ref.hook(payload, context), timeout=self.timeout)
        except Exception:
            if span_id is not None:
                try:
                    self.observability.end_span(span_id=span_id, status="error")
                except Exception:  # nosec B110
                    pass
            raise

        # End span with success
        if span_id is not None:
            try:
                self.observability.end_span(
                    span_id=span_id,
                    status="ok",
                    attributes={
                        "plugin.had_violation": result.violation is not None,
                        "plugin.modified_payload": result.modified_payload is not None,
                    },
                )
            except Exception as e:
                logger.debug("Plugin observability end_span failed: %s", e)

        return result

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
    _executor: PluginExecutor | None = None

    def __init__(
        self,
        config: str = "",
        timeout: int = DEFAULT_PLUGIN_TIMEOUT,
        observability: Optional[ObservabilityProvider] = None,
        hook_policies: Optional[dict[str, HookPayloadPolicy]] = None,
    ):
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
            observability: Optional observability provider implementing ObservabilityProvider protocol.
            hook_policies: Per-hook-type payload modification policies (injected by gateway).

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

                    # Update executor with timeout, observability, and policies
                    self._executor = PluginExecutor(
                        config=self._config,
                        timeout=timeout,
                        observability=observability,
                        hook_policies=hook_policies,
                    )
        elif hook_policies:
            # Allow hook policies to be injected after initial Borg creation.
            # This handles the case where the first PluginManager instantiation
            # (e.g. from a service) didn't have policies, but a later one does.
            with self.__lock:
                executor = self._get_executor()
                # Only update timeout if caller provided a non-default value
                if timeout != DEFAULT_PLUGIN_TIMEOUT:
                    executor.timeout = timeout
                if not executor.hook_policies:
                    executor.hook_policies = hook_policies
                elif executor.hook_policies != hook_policies:
                    logger.warning("PluginManager: hook_policies already set; ignoring new policies (call reset() first to replace them)")
                if observability and not executor.observability:
                    executor.observability = observability
        elif self._executor is None:
            # Defensive initialization for unusual state transitions in tests.
            with self.__lock:
                if self._executor is None:
                    self._executor = PluginExecutor(config=self._config, timeout=timeout, observability=observability)

    def _get_executor(self) -> PluginExecutor:
        """Get plugin executor, creating it lazily if necessary.

        Returns:
            PluginExecutor: The plugin executor instance.
        """
        if self._executor is None:
            self._executor = PluginExecutor(config=self._config)
        return self._executor

    @property
    def executor(self) -> PluginExecutor:
        """Expose executor for tests and internal callers.

        Returns:
            PluginExecutor: The plugin executor instance.
        """
        return self._get_executor()

    @executor.setter
    def executor(self, value: PluginExecutor) -> None:
        """Set the plugin executor instance."""
        self._executor = value

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
            cls._registry = PluginInstanceRegistry()
            cls._executor = None
            cls._loader = PluginLoader()

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

    @property
    def observability(self) -> Optional[ObservabilityProvider]:
        """Current observability provider.

        Returns:
            The observability provider or None if not configured.
        """
        return self._executor.observability

    @observability.setter
    def observability(self, provider: Optional[ObservabilityProvider]) -> None:
        """Set the observability provider.

        Thread-safe: uses lock to prevent races with concurrent readers.

        Args:
            provider: ObservabilityProvider to inject into the executor.
        """
        with self.__lock:
            self._executor.observability = provider

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
        with self.__lock:
            if self._async_lock is None:
                self._async_lock = asyncio.Lock()

        async with self._async_lock:
            # Double-check after acquiring lock
            if self._initialized:
                logger.debug("Plugin manager already initialized")
                return

            # Defensive cleanup: registry should be empty when not initialized
            if self._registry.plugin_count:
                logger.debug("Plugin registry not empty before initialize; clearing stale plugins")
                await self._registry.shutdown()

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
        with self.__lock:
            if self._async_lock is None:
                self._async_lock = asyncio.Lock()

        async with self._async_lock:
            if not self._initialized:
                logger.debug("Plugin manager not initialized, nothing to shutdown")
                return

            logger.info("Shutting down plugin manager")

            # Shutdown all plugins
            await self._registry.shutdown()

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
        result = await self._get_executor().execute(hook_refs, payload, global_context, hook_type, local_contexts, violations_as_exceptions)

        return result

    async def invoke_hook_for_plugin(
        self,
        name: str,
        hook_type: str,
        payload: Union[PluginPayload, dict[str, Any], str],
        context: Union[PluginContext, GlobalContext],
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
            context: Plugin execution context (PluginContext) or GlobalContext (will be wrapped).
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
        # Auto-wrap GlobalContext in PluginContext for convenience
        if isinstance(context, GlobalContext):
            context = PluginContext(global_context=context)

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
                return await self._get_executor().execute_plugin(hook_ref, pydantic_payload, context, violations_as_exceptions)
            raise ValueError(f"When payload_as_json=True, payload must be str or dict, got {type(payload)}")
        # When payload_as_json=False, payload should already be a PluginPayload
        if not isinstance(payload, PluginPayload):
            raise ValueError(f"When payload_as_json=False, payload must be a PluginPayload, got {type(payload)}")
        return await self._get_executor().execute_plugin(hook_ref, payload, context, violations_as_exceptions)
