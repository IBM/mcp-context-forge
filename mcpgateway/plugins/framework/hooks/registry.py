# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/hook_registry.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Hook Registry.
This module provides a global registry for mapping hook types to their
corresponding payload and result Pydantic models. This enables external
plugins to properly serialize/deserialize payloads without needing direct
access to the specific plugin implementations.
"""

# Standard
from typing import Dict, Optional, Type, Union

# First-Party
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class HookRegistry:
    """Global registry for hook type metadata.

    This singleton registry maintains mappings between hook type names and their
    associated Pydantic models for payloads and results. It enables dynamic
    serialization/deserialization for external plugins.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
        >>> registry = HookRegistry()
        >>> registry.register_hook("test_hook", PluginPayload, PluginResult)
        >>> registry.get_payload_type("test_hook")
        <class 'mcpgateway.plugins.framework.models.PluginPayload'>
        >>> registry.get_result_type("test_hook")
        <class 'mcpgateway.plugins.framework.models.PluginResult'>
    """

    _instance: Optional["HookRegistry"] = None
    _hook_payloads: Dict[str, Type[PluginPayload]] = {}
    _hook_results: Dict[str, Type[PluginResult]] = {}

    def __new__(cls) -> "HookRegistry":
        """Ensure singleton pattern for the registry.

        Returns:
            The singleton HookRegistry instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register_hook(
        self,
        hook_type: str,
        payload_class: Type[PluginPayload],
        result_class: Type[PluginResult],
    ) -> None:
        """Register a hook type with its payload and result classes.

        Args:
            hook_type: The hook type identifier (e.g., "prompt_pre_fetch").
            payload_class: The Pydantic model class for the hook's payload.
            result_class: The Pydantic model class for the hook's result.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> registry.register_hook("custom_hook", PluginPayload, PluginResult)
        """
        self._hook_payloads[hook_type] = payload_class
        self._hook_results[hook_type] = result_class

    def get_payload_type(self, hook_type: str) -> Optional[Type[PluginPayload]]:
        """Get the payload class for a hook type.

        Args:
            hook_type: The hook type identifier.

        Returns:
            The Pydantic payload class, or None if not registered.

        Examples:
            >>> registry = HookRegistry()
            >>> registry.get_payload_type("unknown_hook")
        """
        return self._hook_payloads.get(hook_type)

    def get_result_type(self, hook_type: str) -> Optional[Type[PluginResult]]:
        """Get the result class for a hook type.

        Args:
            hook_type: The hook type identifier.

        Returns:
            The Pydantic result class, or None if not registered.

        Examples:
            >>> registry = HookRegistry()
            >>> registry.get_result_type("unknown_hook")
        """
        return self._hook_results.get(hook_type)

    def json_to_payload(self, hook_type: str, payload: Union[str, dict]) -> PluginPayload:
        """Convert JSON to the appropriate payload Pydantic model.

        Args:
            hook_type: The hook type identifier.
            payload: The payload as JSON string or dictionary.

        Returns:
            The deserialized Pydantic payload object.

        Raises:
            ValueError: If the hook type is not registered.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework.hooks.prompts import PromptPrehookPayload, PromptPrehookResult
            >>> registry.register_hook("test", PromptPrehookPayload, PromptPrehookResult)
            >>> payload = registry.json_to_payload("test", {"prompt_id": "123"})
        """
        payload_class = self.get_payload_type(hook_type)
        if not payload_class:
            raise ValueError(f"No payload type registered for hook: {hook_type}")

        if isinstance(payload, str):
            return payload_class.model_validate_json(payload)
        return payload_class.model_validate(payload)

    def json_to_result(self, hook_type: str, result: Union[str, dict]) -> PluginResult:
        """Convert JSON to the appropriate result Pydantic model.

        Args:
            hook_type: The hook type identifier.
            result: The result as JSON string or dictionary.

        Returns:
            The deserialized Pydantic result object.

        Raises:
            ValueError: If the hook type is not registered.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> registry.register_hook("test", PluginPayload, PluginResult)
            >>> result = registry.json_to_result("test", '{"continue_processing": true}')
        """
        result_class = self.get_result_type(hook_type)
        if not result_class:
            raise ValueError(f"No result type registered for hook: {hook_type}")

        if isinstance(result, str):
            return result_class.model_validate_json(result)
        return result_class.model_validate(result)

    def is_registered(self, hook_type: str) -> bool:
        """Check if a hook type is registered.

        Args:
            hook_type: The hook type identifier.

        Returns:
            True if the hook is registered, False otherwise.

        Examples:
            >>> registry = HookRegistry()
            >>> registry.is_registered("unknown")
            False
        """
        return hook_type in self._hook_payloads and hook_type in self._hook_results

    def get_registered_hooks(self) -> list[str]:
        """Get all registered hook types.

        Returns:
            List of registered hook type identifiers.

        Examples:
            >>> registry = HookRegistry()
            >>> hooks = registry.get_registered_hooks()
            >>> isinstance(hooks, list)
            True
        """
        return list(self._hook_payloads.keys())


# Global singleton instance
_global_registry = HookRegistry()


def get_hook_registry() -> HookRegistry:
    """Get the global hook registry instance.

    Returns:
        The singleton HookRegistry instance.

    Examples:
        >>> registry = get_hook_registry()
        >>> isinstance(registry, HookRegistry)
        True
    """
    return _global_registry
