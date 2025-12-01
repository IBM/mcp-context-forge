# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/base.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
-Authors: Teryl Taylor, Mihai Criveti

Base plugin implementation.
This module implements the base plugin object.
"""

# Standard
from abc import ABC
from typing import Awaitable, Callable, Optional, Union
import uuid

# First-Party
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.models import PluginCondition, PluginConfig, PluginContext, PluginErrorModel, PluginMode, PluginPayload, PluginResult

# pylint: disable=import-outside-toplevel


class Plugin(ABC):
    """Base plugin object for pre/post processing of inputs and outputs at various locations throughout the server.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginConfig, PluginMode
        >>> from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
        >>> config = PluginConfig(
        ...     name="test_plugin",
        ...     description="Test plugin",
        ...     author="test",
        ...     kind="mcpgateway.plugins.framework.Plugin",
        ...     version="1.0.0",
        ...     hooks=[PromptHookType.PROMPT_PRE_FETCH],
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
        >>> PromptHookType.PROMPT_PRE_FETCH in plugin.hooks
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
            >>> from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
            >>> config = PluginConfig(
            ...     name="simple_plugin",
            ...     description="Simple test",
            ...     author="test",
            ...     kind="test.Plugin",
            ...     version="1.0.0",
            ...     hooks=[PromptHookType.PROMPT_POST_FETCH],
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
            from mcpgateway.plugins.framework.hooks.registry import get_hook_registry

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
            from mcpgateway.plugins.framework.hooks.registry import get_hook_registry

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
        >>> from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
        >>> config = PluginConfig(
        ...     name="ref_test",
        ...     description="Reference test",
        ...     author="test",
        ...     kind="test.Plugin",
        ...     version="1.0.0",
        ...     hooks=[PromptHookType.PROMPT_PRE_FETCH],
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
            >>> from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
            >>> config = PluginConfig(
            ...     name="plugin_ref",
            ...     description="Test",
            ...     author="test",
            ...     kind="test.Plugin",
            ...     version="1.0.0",
            ...     hooks=[PromptHookType.PROMPT_POST_FETCH],
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

        Discovers the hook method using either:
        1. Convention-based naming (method name matches hook type)
        2. Decorator-based (@hook decorator with matching hook_type)

        Args:
            hook: name of the hook point (e.g., 'tool_pre_invoke').
            plugin_ref: The reference to the plugin to hook.

        Raises:
            PluginError: If no method is found for the specified hook.

        Examples:
            >>> from mcpgateway.plugins.framework import PluginConfig
            >>> config = PluginConfig(name="test", kind="test", version="1.0", author="test", hooks=["tool_pre_invoke"])
            >>> plugin = Plugin(config)
            >>> plugin_ref = PluginRef(plugin)
            >>> # This would work if plugin has tool_pre_invoke method or @hook("tool_pre_invoke") decorator
        """
        # Standard
        import inspect

        # First-Party
        from mcpgateway.plugins.framework.decorator import get_hook_metadata

        self._plugin_ref = plugin_ref
        self._hook = hook

        # Try convention-based lookup first (method name matches hook type)
        self._func: Callable[[PluginPayload, PluginContext], Awaitable[PluginResult]] | None = getattr(plugin_ref.plugin, hook, None)

        # If not found by convention, scan for @hook decorated methods
        if self._func is None:
            for name, method in inspect.getmembers(plugin_ref.plugin, predicate=inspect.ismethod):
                # Skip private/magic methods
                if name.startswith("_"):
                    continue

                # Check for @hook decorator metadata
                metadata = get_hook_metadata(method)
                if metadata and metadata.hook_type == hook:
                    self._func = method
                    break

        # Raise error if hook method not found by either approach
        if not self._func:
            raise PluginError(
                error=PluginErrorModel(
                    message=f"Plugin '{plugin_ref.plugin.name}' has no hook: '{hook}'. " f"Method must either be named '{hook}' or decorated with @hook('{hook}')",
                    plugin_name=plugin_ref.plugin.name,
                )
            )

        # Validate hook method signature (parameter count and async)
        self._validate_hook_signature(hook, self._func, plugin_ref.plugin.name)

    def _validate_hook_signature(self, hook: str, func: Callable, plugin_name: str) -> None:
        """Validate that the hook method has the correct signature.

        Checks:
        1. Method accepts correct number of parameters (self, payload, context)
        2. Method is async (returns coroutine)

        Args:
            hook: The hook type being validated
            func: The hook method to validate
            plugin_name: Name of the plugin (for error messages)

        Raises:
            PluginError: If the signature is invalid
        """
        # Standard
        import inspect

        sig = inspect.signature(func)
        params = list(sig.parameters.values())

        # Check parameter count (should be: payload, context)
        # Note: 'self' is not included in bound method signatures
        if len(params) != 2:
            raise PluginError(
                error=PluginErrorModel(
                    message=f"Plugin '{plugin_name}' hook '{hook}' has invalid signature. "
                    f"Expected 2 parameters (payload, context), got {len(params)}: {list(sig.parameters.keys())}. "
                    f"Correct signature: async def {hook}(self, payload: PayloadType, context: PluginContext) -> ResultType",
                    plugin_name=plugin_name,
                )
            )

        # Check that method is async
        if not inspect.iscoroutinefunction(func):
            raise PluginError(
                error=PluginErrorModel(
                    message=f"Plugin '{plugin_name}' hook '{hook}' must be async. "
                    f"Method '{func.__name__}' is not a coroutine function. "
                    f"Use 'async def {func.__name__}(...)' instead of 'def {func.__name__}(...)'.",
                    plugin_name=plugin_name,
                )
            )

        # ========== OPTIONAL: Type Hint Validation ==========
        # Uncomment to enable strict type checking of payload and return types.
        # This validates that type hints match the expected types from the hook registry.
        # Pros: Catches type errors at plugin load time instead of runtime
        # Cons: Requires all plugins to have type hints, adds validation overhead
        #
        # self._validate_type_hints(hook, func, params, plugin_name)

    def _validate_type_hints(self, hook: str, func: Callable, params: list, plugin_name: str) -> None:
        """Validate that type hints match expected payload and result types.

        This is an optional validation that can be enabled to enforce type safety.

        Args:
            hook: The hook type being validated
            func: The hook method to validate
            params: List of function parameters
            plugin_name: Name of the plugin (for error messages)

        Raises:
            PluginError: If type hints are missing or don't match expected types
        """
        # Standard
        from typing import get_type_hints

        # First-Party
        from mcpgateway.plugins.framework.hooks.registry import get_hook_registry

        # Get expected types from registry
        registry = get_hook_registry()
        expected_payload_type = registry.get_payload_type(hook)
        expected_result_type = registry.get_result_type(hook)

        # If hook is not registered in global registry, we can't validate types
        if not expected_payload_type or not expected_result_type:
            return

        # Get type hints from the function
        try:
            hints = get_type_hints(func)
        except Exception as e:
            # Type hints might use forward references or unavailable types
            # We'll skip validation rather than fail
            # Standard
            import logging

            logger = logging.getLogger(__name__)
            logger.debug("Could not extract type hints for plugin '%s' hook '%s': %s", plugin_name, hook, e)
            return

        # Validate payload parameter type (first parameter, since 'self' is not in params)
        payload_param_name = params[0].name
        if payload_param_name not in hints:
            raise PluginError(
                error=PluginErrorModel(
                    message=f"Plugin '{plugin_name}' hook '{hook}' missing type hint for parameter '{payload_param_name}'. " f"Expected: {payload_param_name}: {expected_payload_type.__name__}",
                    plugin_name=plugin_name,
                )
            )

        actual_payload_type = hints[payload_param_name]

        # Check if types match (exact match or subclass)
        if actual_payload_type != expected_payload_type:
            # Check for generic types or complex type hints
            actual_type_str = str(actual_payload_type)
            expected_type_str = expected_payload_type.__name__

            # If the expected type name is in the string representation, it's probably OK
            if expected_type_str not in actual_type_str:
                raise PluginError(
                    error=PluginErrorModel(
                        message=f"Plugin '{plugin_name}' hook '{hook}' parameter '{payload_param_name}' " f"has incorrect type hint. Expected: {expected_type_str}, Got: {actual_type_str}",
                        plugin_name=plugin_name,
                    )
                )

        # Validate return type
        if "return" not in hints:
            raise PluginError(
                error=PluginErrorModel(
                    message=f"Plugin '{plugin_name}' hook '{hook}' missing return type hint. " f"Expected: -> {expected_result_type.__name__}",
                    plugin_name=plugin_name,
                )
            )

        actual_return_type = hints["return"]
        return_type_str = str(actual_return_type)
        expected_return_str = expected_result_type.__name__

        # For async functions, the return type might be wrapped in Coroutine or Awaitable
        # We just check if the expected type is mentioned in the return type
        if expected_return_str not in return_type_str and actual_return_type != expected_result_type:
            raise PluginError(
                error=PluginErrorModel(
                    message=f"Plugin '{plugin_name}' hook '{hook}' has incorrect return type hint. " f"Expected: {expected_return_str}, Got: {return_type_str}",
                    plugin_name=plugin_name,
                )
            )

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
    def hook(self) -> Callable[[PluginPayload, PluginContext], Awaitable[PluginResult]] | None:
        """The hooking function that can be invoked within the reference.

        Returns:
            An awaitable hook function reference.
        """
        return self._func
