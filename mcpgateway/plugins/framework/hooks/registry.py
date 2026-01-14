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
from enum import Enum
from typing import Dict, Optional, Type, Union

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class HookPhase(str, Enum):
    """Phase when a hook executes.

    Attributes:
        PRE: Hook executes before the operation (pre-invoke, pre-fetch, etc.).
        POST: Hook executes after the operation (post-invoke, post-fetch, etc.).

    Examples:
        >>> HookPhase.PRE
        <HookPhase.PRE: 'pre'>
        >>> HookPhase.POST
        <HookPhase.POST: 'post'>
    """

    PRE = "pre"
    POST = "post"


class HookMetadata(BaseModel):
    """Metadata for a registered hook.

    Attributes:
        payload_class: The Pydantic payload model class.
        result_class: The Pydantic result model class.
        phase: Whether this is a pre or post hook.
        entity_type: Optional entity type this hook applies to (tool, prompt, resource, http, agent, etc.).

    Examples:
        >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
        >>> meta = HookMetadata(
        ...     payload_class=PluginPayload,
        ...     result_class=PluginResult,
        ...     phase=HookPhase.PRE,
        ...     entity_type="tool"
        ... )
        >>> meta.phase
        <HookPhase.PRE: 'pre'>
        >>> meta.entity_type
        'tool'
    """

    payload_class: Type[PluginPayload]
    result_class: Type[PluginResult]
    phase: HookPhase
    entity_type: Optional[str] = None

    class Config:
        """Pydantic config."""

        arbitrary_types_allowed = True


class HookRegistry:
    """Global registry for hook type metadata.

    This singleton registry maintains mappings between hook type names and their
    associated Pydantic models for payloads and results, plus metadata like
    hook phase (pre/post). It enables dynamic serialization/deserialization
    for external plugins and proper handling of post-hook priority ordering.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
        >>> registry = HookRegistry()
        >>> registry.register_hook("test_pre_hook", PluginPayload, PluginResult, HookPhase.PRE)
        >>> registry.get_payload_type("test_pre_hook")
        <class 'pydantic.main.BaseModel'>
        >>> registry.get_result_type("test_pre_hook")
        <class 'mcpgateway.plugins.framework.models.PluginResult'>
        >>> registry.get_phase("test_pre_hook")
        <HookPhase.PRE: 'pre'>
        >>> registry.is_post_hook("test_pre_hook")
        False
    """

    _instance: Optional["HookRegistry"] = None
    _hook_metadata: Dict[str, HookMetadata] = {}

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
        phase: Optional[HookPhase] = None,
        entity_type: Optional[str] = None,
    ) -> None:
        """Register a hook type with its payload, result classes, phase, and entity type.

        The phase is auto-detected from the hook_type name if not provided:
        - Names containing "_pre_" or ending with "_pre" are PRE hooks
        - Names containing "_post_" or ending with "_post" are POST hooks
        - Raises PluginError if phase cannot be detected and not explicitly provided

        The entity_type is auto-detected from the hook_type prefix if not provided:
        - "tool_*" hooks -> entity_type="tool"
        - "prompt_*" hooks -> entity_type="prompt"
        - "resource_*" hooks -> entity_type="resource"
        - "http_*" hooks -> entity_type="http"
        - "agent_*" hooks -> entity_type="agent"
        - "server_*" hooks -> entity_type="server"

        Args:
            hook_type: The hook type identifier (e.g., "tool_pre_invoke").
            payload_class: The Pydantic model class for the hook's payload.
            result_class: The Pydantic model class for the hook's result.
            phase: Optional hook phase (PRE or POST). Auto-detected if not provided.
            entity_type: Optional entity type (tool, prompt, resource, http, agent, server).
                Auto-detected from hook_type prefix if not provided.

        Raises:
            ValueError: If phase cannot be auto-detected and not explicitly provided.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> # Explicit phase and entity type
            >>> registry.register_hook("custom_pre", PluginPayload, PluginResult, HookPhase.PRE, "tool")
            >>> registry.get_phase("custom_pre")
            <HookPhase.PRE: 'pre'>
            >>> registry.get_entity_type("custom_pre")
            'tool'

            >>> # Auto-detect from name
            >>> registry.register_hook("tool_pre_invoke", PluginPayload, PluginResult)
            >>> registry.get_phase("tool_pre_invoke")
            <HookPhase.PRE: 'pre'>
            >>> registry.get_entity_type("tool_pre_invoke")
            'tool'
        """
        # Auto-detect phase from hook_type name if not provided
        if phase is None:
            if "_pre_" in hook_type or hook_type.endswith("_pre"):
                phase = HookPhase.PRE
            elif "_post_" in hook_type or hook_type.endswith("_post"):
                phase = HookPhase.POST
            else:
                # Error if can't detect
                raise ValueError(
                    f"Cannot auto-detect phase for hook '{hook_type}'. " "Hook name must contain '_pre_', '_post_', or end with '_pre' or '_post', " "or phase must be explicitly provided."
                )

        # Auto-detect entity_type from hook_type prefix if not provided
        if entity_type is None:
            for prefix in ["tool", "prompt", "resource", "http", "agent", "server"]:
                if hook_type.startswith(f"{prefix}_"):
                    entity_type = prefix
                    break

        # Store in metadata dict
        self._hook_metadata[hook_type] = HookMetadata(payload_class=payload_class, result_class=result_class, phase=phase, entity_type=entity_type)

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
        metadata = self._hook_metadata.get(hook_type)
        return metadata.payload_class if metadata else None

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
        metadata = self._hook_metadata.get(hook_type)
        return metadata.result_class if metadata else None

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
            >>> registry.register_hook("test_pre", PromptPrehookPayload, PromptPrehookResult)
            >>> payload = registry.json_to_payload("test_pre", {"prompt_id": "123"})
            >>> payload.prompt_id
            '123'
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
            >>> registry.register_hook("test_pre", PluginPayload, PluginResult)
            >>> result = registry.json_to_result("test_pre", '{"continue_processing": true}')
            >>> result.continue_processing
            True
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
        return hook_type in self._hook_metadata

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
        return list(self._hook_metadata.keys())

    def get_phase(self, hook_type: str) -> Optional[HookPhase]:
        """Get the phase (PRE/POST) for a hook type.

        Args:
            hook_type: The hook type identifier.

        Returns:
            The hook phase, or None if not registered.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> registry.register_hook("test_pre", PluginPayload, PluginResult, HookPhase.PRE)
            >>> registry.get_phase("test_pre")
            <HookPhase.PRE: 'pre'>
            >>> registry.get_phase("unknown")
        """
        metadata = self._hook_metadata.get(hook_type)
        return metadata.phase if metadata else None

    def is_post_hook(self, hook_type: str) -> bool:
        """Check if a hook is a POST hook.

        Args:
            hook_type: The hook type identifier.

        Returns:
            True if hook is a POST hook, False otherwise.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> registry.register_hook("test_post", PluginPayload, PluginResult, HookPhase.POST)
            >>> registry.is_post_hook("test_post")
            True
            >>> registry.register_hook("test_pre", PluginPayload, PluginResult, HookPhase.PRE)
            >>> registry.is_post_hook("test_pre")
            False
        """
        phase = self.get_phase(hook_type)
        return phase == HookPhase.POST if phase else False

    def is_pre_hook(self, hook_type: str) -> bool:
        """Check if a hook is a PRE hook.

        Args:
            hook_type: The hook type identifier.

        Returns:
            True if hook is a PRE hook, False otherwise.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> registry.register_hook("test_pre", PluginPayload, PluginResult, HookPhase.PRE)
            >>> registry.is_pre_hook("test_pre")
            True
            >>> registry.register_hook("test_post", PluginPayload, PluginResult, HookPhase.POST)
            >>> registry.is_pre_hook("test_post")
            False
        """
        phase = self.get_phase(hook_type)
        return phase == HookPhase.PRE if phase else False

    def get_metadata(self, hook_type: str) -> Optional[HookMetadata]:
        """Get the complete metadata for a hook type.

        Args:
            hook_type: The hook type identifier.

        Returns:
            The hook metadata, or None if not registered.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> registry.register_hook("test", PluginPayload, PluginResult, HookPhase.PRE)
            >>> meta = registry.get_metadata("test")
            >>> meta.phase
            <HookPhase.PRE: 'pre'>
        """
        return self._hook_metadata.get(hook_type)

    def get_entity_type(self, hook_type: str) -> Optional[str]:
        """Get the entity type for a hook.

        Args:
            hook_type: The hook type identifier.

        Returns:
            The entity type (tool, prompt, resource, http, etc.), or None if not set.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> registry.register_hook("tool_pre_invoke", PluginPayload, PluginResult)
            >>> registry.get_entity_type("tool_pre_invoke")
            'tool'
        """
        metadata = self._hook_metadata.get(hook_type)
        return metadata.entity_type if metadata else None

    def get_hooks_for_entity_type(self, entity_type: str, phase: Optional[HookPhase] = None) -> list[str]:
        """Get all hook types for a specific entity type and optional phase.

        Args:
            entity_type: The entity type (tool, prompt, resource, http, agent, server).
            phase: Optional phase filter (PRE or POST). If None, returns all hooks.

        Returns:
            List of hook type identifiers matching the criteria.

        Examples:
            >>> registry = HookRegistry()
            >>> from mcpgateway.plugins.framework import PluginPayload, PluginResult
            >>> from mcpgateway.plugins.framework.hooks.tools import ToolHookType
            >>> registry.register_hook(ToolHookType.TOOL_PRE_INVOKE, PluginPayload, PluginResult)
            >>> registry.register_hook(ToolHookType.TOOL_POST_INVOKE, PluginPayload, PluginResult)
            >>> registry.register_hook("prompt_pre_fetch", PluginPayload, PluginResult)
            >>> # Get all tool hooks
            >>> tool_hooks = registry.get_hooks_for_entity_type("tool")
            >>> sorted([str(h.value) if hasattr(h, 'value') else h for h in tool_hooks])
            ['tool_post_invoke', 'tool_pre_invoke']
            >>> # Get only tool PRE hooks
            >>> pre_hooks = registry.get_hooks_for_entity_type("tool", HookPhase.PRE)
            >>> [str(h.value) if hasattr(h, 'value') else h for h in pre_hooks]
            ['tool_pre_invoke']
        """
        hooks = []
        for hook_name, metadata in self._hook_metadata.items():
            if metadata.entity_type == entity_type:
                if phase is None or metadata.phase == phase:
                    hooks.append(hook_name)
        return hooks


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
