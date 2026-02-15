# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/hooks/prompts.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Fred Araujo

Pydantic models for prompt plugins.
This module implements the pydantic models associated with
the base plugin layer including configurations, and contexts.
"""

# Standard
from enum import Enum
from typing import Any, Optional

# Third-Party
from pydantic import Field, field_validator

# First-Party
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class PromptHookType(str, Enum):
    """MCP Forge Gateway hook points.

    Attributes:
        prompt_pre_fetch: The prompt pre hook.
        prompt_post_fetch: The prompt post hook.
        tool_pre_invoke: The tool pre invoke hook.
        tool_post_invoke: The tool post invoke hook.
        resource_pre_fetch: The resource pre fetch hook.
        resource_post_fetch: The resource post fetch hook.

    Examples:
        >>> PromptHookType.PROMPT_PRE_FETCH
        <PromptHookType.PROMPT_PRE_FETCH: 'prompt_pre_fetch'>
        >>> PromptHookType.PROMPT_PRE_FETCH.value
        'prompt_pre_fetch'
        >>> PromptHookType('prompt_post_fetch')
        <PromptHookType.PROMPT_POST_FETCH: 'prompt_post_fetch'>
        >>> list(PromptHookType)
        [<PromptHookType.PROMPT_PRE_FETCH: 'prompt_pre_fetch'>, <PromptHookType.PROMPT_POST_FETCH: 'prompt_post_fetch'>]
    """

    PROMPT_PRE_FETCH = "prompt_pre_fetch"
    PROMPT_POST_FETCH = "prompt_post_fetch"


class PromptPrehookPayload(PluginPayload):
    """A prompt payload for a prompt prehook.

    Attributes:
        prompt_id (str): The ID of the prompt template.
        args (dic[str,str]): The prompt template arguments.

    Examples:
        >>> payload = PromptPrehookPayload(prompt_id="123", args={"user": "alice"})
        >>> payload.prompt_id
        '123'
        >>> payload.args
        {'user': 'alice'}
        >>> payload2 = PromptPrehookPayload(prompt_id="empty")
        >>> payload2.args
        {}
        >>> p = PromptPrehookPayload(prompt_id="123", args={"name": "Bob", "time": "morning"})
        >>> p.prompt_id
        '123'
        >>> p.args["name"]
        'Bob'
    """

    prompt_id: str
    args: Optional[dict[str, str]] = Field(default_factory=dict)


class PromptPosthookPayload(PluginPayload):
    """A prompt payload for a prompt posthook.

    Attributes:
        prompt_id (str): The prompt ID.
        result (Any): The prompt result (accepts any PromptResultLike-satisfying object).

    Examples:
        >>> from types import SimpleNamespace
        >>> result = SimpleNamespace(messages=[], description=None)
        >>> payload = PromptPosthookPayload(prompt_id="123", result=result)
        >>> payload.prompt_id
        '123'
    """

    prompt_id: str
    result: Any

    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, v: Any) -> Any:
        """Convert nested dicts to objects with attribute access.

        When deserializing from JSON (external server flows), ``result``
        arrives as a plain dict.  This validator converts it to a
        :class:`~mcpgateway.plugins.framework.utils.StructuredData` so
        that plugin code like ``payload.result.messages[0].content.text``
        works regardless of the transport.

        Args:
            v: The raw value for the ``result`` field.

        Returns:
            The coerced value with attribute access, or the original value.
        """
        if isinstance(v, dict):
            # First-Party
            from mcpgateway.plugins.framework.utils import coerce_nested  # pylint: disable=import-outside-toplevel

            return coerce_nested(v)
        return v


PromptPrehookResult = PluginResult[PromptPrehookPayload]
PromptPosthookResult = PluginResult[PromptPosthookPayload]


def _register_prompt_hooks() -> None:
    """Register prompt hooks in the global registry.

    This is called lazily to avoid circular import issues.
    """
    # Import here to avoid circular dependency at module load time
    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    # Only register if not already registered (idempotent)
    if not registry.is_registered(PromptHookType.PROMPT_PRE_FETCH):
        registry.register_hook(PromptHookType.PROMPT_PRE_FETCH, PromptPrehookPayload, PromptPrehookResult)
        registry.register_hook(PromptHookType.PROMPT_POST_FETCH, PromptPosthookPayload, PromptPosthookResult)


_register_prompt_hooks()
