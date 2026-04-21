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
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any, Optional, Union

# Third-Party
from pydantic import BaseModel, RootModel, ValidationError

# First-Party
from mcpgateway.observability import create_span
from mcpgateway.plugins.framework.base import HookRef, Plugin
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError, PluginViolationError
from mcpgateway.plugins.framework.hooks.policies import apply_policy, DefaultHookPolicy, HookPayloadPolicy
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.memory import copyonwrite
from mcpgateway.plugins.framework.models import Config, GlobalContext, PluginConfigOverride, PluginContext, PluginContextTable, PluginErrorModel, PluginMode, PluginPayload, PluginResult
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
HTTP_AUTH_CHECK_PERMISSION_HOOK = "http_auth_check_permission"
DECISION_PLUGIN_METADATA_KEY = "_decision_plugin"
RESERVED_INTERNAL_METADATA_KEYS = frozenset({DECISION_PLUGIN_METADATA_KEY})
_DEFAULT_CONTEXT_ID = "__global__"


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
            hook_refs: list of hook references to execute, sorted by priority.
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
        decision_plugin_name: Optional[str] = None
        max_retry_delay_ms: int = 0
        executed_plugins = 0
        skipped_plugins = 0
        stopped_by_plugin: Optional[str] = None

        with create_span(
            "plugin.hook.invoke",
            {
                "plugin.hook.type": hook_type,
                "plugin.chain.length": len(hook_refs),
            },
        ) as hook_chain_span:
            for hook_ref in hook_refs:
                # Skip disabled plugins
                if hook_ref.plugin_ref.mode == PluginMode.DISABLED:
                    skipped_plugins += 1
                    continue

                # Check if plugin conditions match current context
                if hook_ref.plugin_ref.conditions and not payload_matches(payload, hook_type, hook_ref.plugin_ref.conditions, global_context):
                    logger.debug("Skipping plugin %s - conditions not met", hook_ref.plugin_ref.name)
                    skipped_plugins += 1
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
                # payload before handing it to the plugin. The plugin operates on
                # the copy, so in-place nested mutations cannot pollute the live chain.
                effective_payload = current_payload if current_payload is not None else payload
                needs_isolation = policy or self.default_hook_policy == DefaultHookPolicy.DENY or isinstance(effective_payload, RootModel)
                if needs_isolation:
                    plugin_input = effective_payload.model_copy(deep=True) if isinstance(effective_payload, BaseModel) else copy.deepcopy(effective_payload)
                else:
                    plugin_input = effective_payload

                result = await self.execute_plugin(
                    hook_ref,
                    plugin_input,
                    local_context,
                    violations_as_exceptions,
                    global_context,
                    combined_metadata,
                )
                executed_plugins += 1

                # Propagate retry signal — take the largest delay requested by any plugin
                max_retry_delay_ms = max(max_retry_delay_ms, result.retry_delay_ms)

                # Apply policy-based controlled merge (per-plugin)
                if result.modified_payload is not None:
                    if policy:
                        if isinstance(result.modified_payload, type(effective_payload)) and isinstance(effective_payload, BaseModel):
                            filtered = apply_policy(
                                effective_payload,
                                result.modified_payload,
                                policy,
                            )
                            if filtered is not None:
                                current_payload = filtered
                                decision_plugin_name = hook_ref.plugin_ref.name
                        else:
                            if isinstance(result.modified_payload, (PluginPayload, dict)):
                                logger.debug(
                                    "Plugin %s returned cross-type payload (%s -> %s) on hook %s; accepting without field filtering",
                                    hook_ref.plugin_ref.name,
                                    type(effective_payload).__name__,
                                    type(result.modified_payload).__name__,
                                    hook_type,
                                )
                                current_payload = result.modified_payload
                                decision_plugin_name = hook_ref.plugin_ref.name
                            else:
                                logger.warning(
                                    "Plugin %s returned unexpected type %s on hook %s; ignoring modification",
                                    hook_ref.plugin_ref.name,
                                    type(result.modified_payload).__name__,
                                    hook_type,
                                )
                    elif self.default_hook_policy == DefaultHookPolicy.ALLOW:
                        current_payload = result.modified_payload
                        decision_plugin_name = hook_ref.plugin_ref.name
                    else:
                        logger.warning(
                            "Plugin %s attempted payload modification on hook %s but no policy is defined and default is deny",
                            hook_ref.plugin_ref.name,
                            hook_type,
                        )

                # Both ENFORCE and ENFORCE_IGNORE_ERROR honour continue_processing=False
                # and halt the chain. They differ only in error handling.
                if not result.continue_processing and hook_ref.plugin_ref.mode in (PluginMode.ENFORCE, PluginMode.ENFORCE_IGNORE_ERROR):
                    stopped_by_plugin = hook_ref.plugin_ref.name
                    if hook_chain_span is not None:
                        hook_chain_span.set_attribute("plugin.chain.stopped", True)
                        hook_chain_span.set_attribute("plugin.chain.stopped_by", hook_ref.plugin_ref.name)
                        hook_chain_span.set_attribute("plugin.executed_count", executed_plugins)
                        hook_chain_span.set_attribute("plugin.skipped_count", skipped_plugins)
                    if hook_type == HTTP_AUTH_CHECK_PERMISSION_HOOK and decision_plugin_name:
                        combined_metadata[DECISION_PLUGIN_METADATA_KEY] = decision_plugin_name
                    return (
                        PluginResult(
                            continue_processing=False,
                            modified_payload=current_payload,
                            violation=result.violation,
                            metadata=combined_metadata,
                        ),
                        res_local_contexts,
                    )

            if hook_chain_span is not None:
                hook_chain_span.set_attribute("plugin.executed_count", executed_plugins)
                hook_chain_span.set_attribute("plugin.skipped_count", skipped_plugins)
                hook_chain_span.set_attribute("plugin.chain.stopped", stopped_by_plugin is not None)

        if hook_type == HTTP_AUTH_CHECK_PERMISSION_HOOK and decision_plugin_name:
            combined_metadata[DECISION_PLUGIN_METADATA_KEY] = decision_plugin_name

        return (PluginResult(continue_processing=True, modified_payload=current_payload, violation=None, metadata=combined_metadata, retry_delay_ms=max_retry_delay_ms), res_local_contexts)

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
                combined_metadata.update({k: v for k, v in result.metadata.items() if k not in RESERVED_INTERNAL_METADATA_KEYS})

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
                # Build base plugin span attributes
                base_attributes = {
                    "plugin.name": hook_ref.plugin_ref.name,
                    "plugin.uuid": hook_ref.plugin_ref.uuid,
                    "plugin.mode": hook_ref.plugin_ref.mode.value if hasattr(hook_ref.plugin_ref.mode, "value") else str(hook_ref.plugin_ref.mode),
                    "plugin.priority": hook_ref.plugin_ref.priority,
                    "plugin.timeout": self.timeout,
                }

                # Apply attribute name mapping if configured (from SpanAttributeCustomizerPlugin)
                # First-Party
                from mcpgateway.plugins.framework.utils import apply_attribute_mapping

                attribute_mapping = context.global_context.state.get("span_attribute_mapping", {})
                if attribute_mapping:
                    base_attributes = apply_attribute_mapping(base_attributes, attribute_mapping)

                span_id = self.observability.start_span(
                    trace_id=trace_id,
                    name=f"plugin.execute.{hook_ref.plugin_ref.name}",
                    kind="internal",
                    resource_type="plugin",
                    resource_name=hook_ref.plugin_ref.name,
                    attributes=base_attributes,
                )
            except Exception as e:
                logger.debug("Plugin observability start_span failed: %s", e)

        # Build OTEL span attributes with optional mapping
        otel_attributes = {
            "plugin.name": hook_ref.plugin_ref.name,
            "plugin.uuid": hook_ref.plugin_ref.uuid,
            "plugin.mode": hook_ref.plugin_ref.mode.value if hasattr(hook_ref.plugin_ref.mode, "value") else str(hook_ref.plugin_ref.mode),
            "plugin.priority": hook_ref.plugin_ref.priority,
            "plugin.timeout": self.timeout,
            "plugin.hook.type": hook_ref.name,
            "plugin.kind": getattr(getattr(hook_ref.plugin_ref.plugin, "config", None), "kind", None),
            "contextforge.runtime": "python",
        }

        # Apply attribute name mapping if configured
        attribute_mapping = context.global_context.state.get("span_attribute_mapping", {})
        if attribute_mapping:
            renamed_otel_attributes = {}
            for old_name, value in otel_attributes.items():
                new_name = attribute_mapping.get(old_name, old_name)
                renamed_otel_attributes[new_name] = value
            otel_attributes = renamed_otel_attributes

        with create_span("plugin.execute", otel_attributes) as otel_span:
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

            if otel_span is not None:
                otel_span.set_attribute("plugin.had_violation", result.violation is not None)
                otel_span.set_attribute("plugin.modified_payload", result.modified_payload is not None)
                otel_span.set_attribute("plugin.continue_processing", result.continue_processing)
                otel_span.set_attribute("plugin.stopped_chain", not result.continue_processing)

            # End span with success
            if span_id is not None:
                try:
                    self.observability.end_span(
                        span_id=span_id,
                        status="ok",
                        attributes={
                            "plugin.had_violation": result.violation is not None,
                            "plugin.modified_payload": result.modified_payload is not None,
                            "plugin.continue_processing": result.continue_processing,
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
        self.enable_borg()

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

    def enable_borg(self) -> None:
        """Activate Borg singleton — share state dict across all PluginManager instances."""
        self.__dict__ = self.__shared_state

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
        """Set the plugin executor instance.

        Args:
            value: The plugin executor to assign.
        """
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
                    if self._config and not self._config.plugin_settings.fail_on_plugin_error:
                        logger.warning("Skipping plugin %s because fail_on_plugin_error is disabled", plugin_config.name)
                        continue
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


class TenantPluginManager(PluginManager):
    """
    PluginManager with per-server configuration overrides.
    Each instance has independent state (Borg pattern is disabled).
    Fully compatible with PluginManager API.
    """

    def enable_borg(self) -> None:
        """Opt out of Borg singleton — each tenant instance manages its own state."""

    def __init__(  # pylint: disable=super-init-not-called
        self,
        config: Union[str, Config],
        timeout: int = DEFAULT_PLUGIN_TIMEOUT,
        observability: Optional[ObservabilityProvider] = None,
        hook_policies: Optional[dict[str, HookPayloadPolicy]] = None,
    ):
        """Initialize a TenantPluginManager with independent state.

        Bypasses PluginManager.__init__ entirely — Borg logic doesn't apply here.
        Each TenantPluginManager is fully independent.

        Args:
            config: Plugin configuration (path or Config object).
            timeout: Per-plugin call timeout in seconds.
            observability: Optional observability provider.
            hook_policies: Optional hook payload policy map.
        """
        if isinstance(config, Config):
            self._config_path = None
            self._config = config
        else:
            self._config_path = config
            self._config = ConfigLoader.load_config(config)

        self._executor = PluginExecutor(
            config=self._config,
            timeout=timeout,
            observability=observability,
            hook_policies=hook_policies,
        )
        self._initialized = False
        self._registry = PluginInstanceRegistry()
        self._loader = PluginLoader()
        self._async_lock: asyncio.Lock | None = None


@dataclass(frozen=True, slots=True)
class _CachedManager:
    """A cached tenant manager paired with the monotonic timestamp of its build.

    The frozen dataclass replaces an ad-hoc ``(manager, created_at)`` tuple so
    every access site uses ``is_expired`` instead of destructuring the pair.
    """

    manager: "TenantPluginManager"
    created_at: float

    def is_expired(self, ttl: float) -> bool:
        """Return True when ``ttl > 0`` and the entry is older than ``ttl`` seconds."""
        return ttl > 0 and (time.monotonic() - self.created_at) > ttl


class TenantPluginManagerFactory:
    """
    Factory for context-scoped TenantPluginManager instances.

    Caches per-context instances and ensures async-safe initialization.
    The context can represent any scoping mechanism: server, tenant, user,
    organization, or any other identifier requiring isolated plugin configuration.
    """

    # Bounds cross-pod drift after a DB upsert without a broadcast. The listener
    # invalidates faster; this is the safety net.
    DEFAULT_CACHE_TTL = 30
    # Default team/tool separator used by context IDs. Subclasses (e.g. the
    # gateway factory) keep this constant so invalidation broadcasts don't
    # need to carry the separator on the wire.
    CONTEXT_ID_SEPARATOR = "::"

    def __init__(
        self,
        yaml_path: str,
        timeout: int = DEFAULT_PLUGIN_TIMEOUT,
        observability: Optional[ObservabilityProvider] = None,
        hook_policies: Optional[dict[str, HookPayloadPolicy]] = None,
        cache_ttl: Optional[int] = None,
    ):
        """Initialize the TenantPluginManagerFactory.

        Args:
            yaml_path: Path to the base plugin configuration YAML file.
            timeout: Per-plugin call timeout in seconds.
            observability: Optional observability provider.
            hook_policies: Optional hook payload policy map.
            cache_ttl: TTL in seconds for cached managers. Defaults to DEFAULT_CACHE_TTL.
                Set to 0 to disable TTL (cache forever until explicit eviction).
        """
        self._base_config = ConfigLoader.load_config(yaml_path)
        self._timeout = timeout
        self._observability = observability
        self._hook_policies = hook_policies
        self._managers: dict[str, _CachedManager] = {}
        self._inflight: dict[str, asyncio.Task[TenantPluginManager]] = {}
        self._lock = asyncio.Lock()
        self._cache_ttl = cache_ttl if cache_ttl is not None else self.DEFAULT_CACHE_TTL

    @property
    def observability(self) -> Optional[ObservabilityProvider]:
        """Get the current observability provider.

        Returns:
            Optional[ObservabilityProvider]: The current observability provider, or None if not set.
        """
        return self._observability

    @observability.setter
    def observability(self, value: Optional[ObservabilityProvider]) -> None:
        """Set the observability provider for all future tenant managers.

        Args:
            value: The observability provider to set, or None to clear.
        """
        self._observability = value

    async def get_manager(self, context_id: Optional[str] = None) -> TenantPluginManager:
        """Return the cached manager for ``context_id``, rebuilding when expired.

        Args:
            context_id: Context identifier (server, tenant, etc.). Defaults to __global__.

        Returns:
            TenantPluginManager: The manager instance for this context.
        """
        context_id = context_id or _DEFAULT_CONTEXT_ID

        async with self._lock:
            entry = self._managers.get(context_id)
            if entry is not None:
                if entry.is_expired(self._cache_ttl):
                    self._managers.pop(context_id, None)
                    logger.debug("Cache TTL expired for context_id=%s, rebuilding", context_id)
                else:
                    return entry.manager

            inflight = self._inflight.get(context_id)
            if inflight is None:
                inflight = asyncio.create_task(self._build_manager(context_id))
                self._inflight[context_id] = inflight

        try:
            manager = await inflight

            # reload_tenant may have evicted and replaced the entry between the
            # await finishing and re-entering the lock. Always prefer the current
            # cache entry so we don't hand out a shut-down manager.
            async with self._lock:
                entry = self._managers.get(context_id)
                return entry.manager if entry is not None else manager

        finally:
            async with self._lock:
                if self._inflight.get(context_id) is inflight:
                    self._inflight.pop(context_id, None)

    async def _build_manager(self, context_id: str) -> TenantPluginManager:
        """Build, initialise, and cache a TenantPluginManager for ``context_id``.

        Args:
            context_id: Identifier for the tenant/server context.

        Returns:
            TenantPluginManager: Manager for ``context_id``.

        Raises:
            asyncio.CancelledError: If the manager build task is cancelled.
            Exception: If manager initialization fails, the manager is shut down before re-raising.
        """
        manager = None
        try:
            new_config = await self.get_config_from_db(context_id)
            config = self._merge_tenant_config(new_config)
            config = await self._apply_redis_mode_overrides(config)

            manager = TenantPluginManager(
                config=config,
                timeout=self._timeout,
                observability=self._observability,
                hook_policies=self._hook_policies,
            )
            await manager.initialize()

            async with self._lock:
                old_entry = self._managers.get(context_id)
                self._managers[context_id] = _CachedManager(manager=manager, created_at=time.monotonic())

            old = old_entry.manager if old_entry is not None else None
            if old is not None and old is not manager:
                try:
                    await old.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown old manager for context_id=%s", context_id)

            return manager

        except asyncio.CancelledError:
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown cancelled manager for context_id=%s", context_id)
            raise
        except Exception:
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown manager after error for context_id=%s", context_id)
            raise

    async def _apply_redis_mode_overrides(self, config: Config) -> Config:
        """Apply per-plugin mode overrides. Redis is authoritative; the in-process map is the fallback."""
        # pylint: disable=import-outside-toplevel
        # First-Party
        from mcpgateway.plugins.framework._redis import get_shared_redis_client
        from mcpgateway.plugins.framework._state import active_local_mode_overrides, prune_expired_local_overrides

        if not config.plugins:
            return config

        # Prune expired entries from the backing dict (so workers that never hit
        # the admin GET /plugins path don't accumulate one entry per plugin name
        # ever overridden), then snapshot the still-active {name: mode} map.
        now = time.monotonic()
        prune_expired_local_overrides(now)
        local_overrides = active_local_mode_overrides(now)

        redis_values: list[Optional[Any]] = [None] * len(config.plugins)
        try:
            client = await get_shared_redis_client()
        except Exception as exc:
            logger.warning("Redis mode overrides skipped — client error (%s)", exc, exc_info=True)
            client = None

        if client is not None:
            keys = [f"plugin:{p.name}:mode" for p in config.plugins]
            try:
                redis_values = list(await client.mget(keys))
            except Exception as exc:
                logger.warning("Redis MGET for plugin modes failed (%s)", exc, exc_info=True)
                redis_values = [None] * len(config.plugins)

        modified = False
        updated_plugins = []
        for plugin, redis_raw in zip(config.plugins, redis_values):
            # Build an ordered candidate list: Redis first (cluster-authoritative),
            # local map second (fallback when Redis is quiet or the Redis value
            # is corrupt). A corrupt Redis entry must not shadow a valid local
            # override — previously the loop fell straight to the YAML default.
            candidates: list[tuple[str, str]] = []
            if redis_raw is not None:
                redis_str = redis_raw.decode() if isinstance(redis_raw, bytes) else str(redis_raw)
                candidates.append(("redis", redis_str))
            if plugin.name in local_overrides:
                candidates.append(("local", local_overrides[plugin.name]))

            applied = False
            for source, mode_str in candidates:
                try:
                    mode = PluginMode(mode_str)
                except ValueError:
                    logger.warning(
                        "Ignoring invalid %s mode override %r for plugin %s — value not in PluginMode",
                        source,
                        mode_str,
                        plugin.name,
                    )
                    continue
                try:
                    updated_plugins.append(plugin.model_copy(update={"mode": mode}))
                    modified = True
                    applied = True
                    break
                except ValidationError as exc:
                    logger.warning(
                        "Ignoring %s mode override for plugin %s — validation failed (%s)",
                        source,
                        plugin.name,
                        exc,
                    )

            if not applied:
                updated_plugins.append(plugin)

        if modified:
            return config.model_copy(update={"plugins": updated_plugins}, deep=True)
        return config

    async def invalidate_all(self) -> None:
        """Reload every cached manager, logging failures instead of aborting the sweep."""
        async with self._lock:
            context_ids = list(self._managers.keys())
        for ctx_id in context_ids:
            try:
                await self.reload_tenant(ctx_id)
            except Exception as exc:
                logger.warning("invalidate_all: reload failed for context_id=%s (%s)", ctx_id, exc)

    async def invalidate_team(self, team_id: str, separator: Optional[str] = None) -> None:
        """Reload every cached manager whose ``context_id`` starts with ``team_id`` plus the class separator."""
        sep = separator if separator is not None else self.CONTEXT_ID_SEPARATOR
        prefix = f"{team_id}{sep}"
        async with self._lock:
            context_ids = [cid for cid in self._managers if cid.startswith(prefix)]
        for ctx_id in context_ids:
            try:
                await self.reload_tenant(ctx_id)
            except Exception as exc:
                logger.warning("invalidate_team: reload failed for context_id=%s (%s)", ctx_id, exc)

    def iter_context_ids(self) -> list[str]:
        """Return a snapshot of the cached context IDs; safe to iterate without the lock."""
        return list(self._managers.keys())

    def _merge_tenant_config(self, tenant_cfg_override: Optional[list[PluginConfigOverride]]) -> Config:
        """Merge context-specific plugin configuration overrides with base configuration.

        Args:
            tenant_cfg_override: List of plugin configuration overrides for this context
                (server, tenant, user, organization, etc.).

        Returns:
            Config: Merged configuration with context-specific overrides applied.
        """
        if tenant_cfg_override is None:
            return self._base_config

        override_map = {p.name: p for p in tenant_cfg_override}
        merged_plugins = []

        for plugin in self._base_config.plugins or []:
            override = override_map.get(plugin.name)
            if not override:
                merged_plugins.append(plugin)
                continue
            merged_config = {**(plugin.config or {}), **(override.config or {})}
            merged_plugins.append(
                plugin.model_copy(
                    update={
                        "config": merged_config,
                        "mode": override.mode if override.mode is not None else plugin.mode,
                        "priority": override.priority if override.priority is not None else plugin.priority,
                    }
                )
            )
        return self._base_config.model_copy(update={"plugins": merged_plugins}, deep=True)

    async def reload_tenant(self, context_id: str) -> TenantPluginManager:
        """Evict and rebuild the cached manager for ``context_id``.

        Args:
            context_id: Identifier for the tenant/server context to reload.

        Returns:
            TenantPluginManager: Rebuilt manager for ``context_id``.
        """
        async with self._lock:
            old_entry = self._managers.pop(context_id, None)

            existing = self._inflight.get(context_id)
            if existing is not None:
                existing.cancel()
                self._inflight.pop(context_id, None)

            inflight = asyncio.create_task(self._build_manager(context_id))
            self._inflight[context_id] = inflight

        old = old_entry.manager if old_entry is not None else None
        if old is not None:
            try:
                await old.shutdown()
            except Exception:
                logger.exception("Failed to shutdown old manager for context_id=%s", context_id)

        try:
            return await inflight
        finally:
            async with self._lock:
                if self._inflight.get(context_id) is inflight:
                    self._inflight.pop(context_id, None)

    async def shutdown(self) -> None:
        """Shut down all cached managers and cancel any in-flight build tasks."""
        async with self._lock:
            entries = list(self._managers.values())
            inflight = list(self._inflight.values())
            self._managers.clear()
            self._inflight.clear()

        for task in inflight:
            task.cancel()

        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)

        for entry in entries:
            try:
                await entry.manager.shutdown()
            except Exception:
                logger.exception("Failed to shutdown plugin manager")

    async def get_config_from_db(self, context_id: str) -> Optional[list[PluginConfigOverride]]:  # pylint: disable=unused-argument
        """Get plugin configuration overrides from database for a specific context.

        This method should be overridden by subclasses to fetch context-specific
        plugin configuration overrides from the database. The returned overrides will
        be merged with the base configuration.

        The context_id can represent any scoping mechanism: server, tenant, user,
        organization, or any other identifier that requires isolated plugin configuration.

        Args:
            context_id: The context identifier to fetch overrides for (e.g., server ID,
                tenant ID, user ID, organization ID).

        Returns:
            Optional[list[PluginConfigOverride]]: List of plugin configuration overrides,
                or None if no overrides exist for this context.
        """
        return None
