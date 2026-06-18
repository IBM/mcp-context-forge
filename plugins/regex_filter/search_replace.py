# -*- coding: utf-8 -*-
"""Location: ./plugins/regex_filter/search_replace.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Simple example plugin for searching and replacing text.
This module loads configurations for plugins.
"""

# Standard
import copy
import re
from typing import Any

# Third-Party
from pydantic import BaseModel

# First-Party
from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Maximum recursion depth to prevent stack overflow
MAX_RECURSION_DEPTH = 100


class SearchReplace(BaseModel):
    """Search and replace pattern configuration.

    Attributes:
        search: Regular expression pattern to search for.
        replace: Replacement text.
    """

    search: str
    replace: str


class SearchReplaceConfig(BaseModel):
    """Configuration for search and replace plugin.

    Attributes:
        words: List of search and replace patterns to apply.
    """

    words: list[SearchReplace]


def _scan_and_replace_recursive(value: Any, patterns: list[tuple], depth: int = 0) -> Any:
    """Recursively scan and replace patterns in nested structures.

    This function walks through nested dictionaries, lists, and strings,
    applying regex patterns to all string values regardless of nesting depth.
    Includes protection against excessive recursion depth.

    Args:
        value: The value to scan (can be str, dict, list, or other types).
        patterns: List of (compiled_pattern, replacement) tuples.
        depth: Current recursion depth (internal use).

    Returns:
        Modified value with patterns replaced in all nested strings.

    Raises:
        RecursionError: If maximum recursion depth is exceeded.
    """
    if depth >= MAX_RECURSION_DEPTH:
        logger.error(
            f"regex_filter: Maximum recursion depth ({MAX_RECURSION_DEPTH}) reached. "
            f"Payload structure is too deeply nested. Returning value unchanged to prevent stack overflow."
        )
        raise RecursionError(f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) reached in regex_filter")

    try:
        if isinstance(value, str):
            # Apply all patterns to this string
            result = value
            for pattern, replacement in patterns:
                result = pattern.sub(replacement, result)
            return result
        elif isinstance(value, dict):
            # Recursively process dictionary values
            return {k: _scan_and_replace_recursive(v, patterns, depth + 1) for k, v in value.items()}
        elif isinstance(value, list):
            # Recursively process list items
            return [_scan_and_replace_recursive(item, patterns, depth + 1) for item in value]
        else:
            # Return other types unchanged
            return value
    except RecursionError:
        # Re-raise RecursionError from nested calls
        raise
    except Exception as e:
        logger.error(f"regex_filter: Unexpected error during recursive scanning at depth {depth}: {e}")
        # Return value unchanged on error to fail safely
        return value


class SearchReplacePlugin(Plugin):
    """Example search replace plugin."""

    def __init__(self, config: PluginConfig):
        """Initialize the search and replace plugin.

        Args:
            config: Plugin configuration containing search/replace patterns.
        """
        super().__init__(config)
        self._srconfig = SearchReplaceConfig.model_validate(self._config.config)
        # Precompile regex patterns at initialization
        self.__patterns = []
        for word in self._srconfig.words:
            try:
                compiled_pattern = re.compile(word.search)
                self.__patterns.append((compiled_pattern, word.replace))
            except re.error:
                # Skip invalid regex patterns
                pass

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        if payload.args:
            modified_args = _scan_and_replace_recursive(payload.args, self.__patterns)
            payload = payload.model_copy(update={"args": modified_args})
        return PromptPrehookResult(modified_payload=payload)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """

        if payload.result.messages:
            modified_result = copy.deepcopy(payload.result)
            for index, message in enumerate(modified_result.messages):
                for pattern, replacement in self.__patterns:
                    modified_result.messages[index].content.text = pattern.sub(replacement, message.content.text)
            payload = payload.model_copy(update={"result": modified_result})
        return PromptPosthookResult(modified_payload=payload)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        if payload.args:
            modified_args = _scan_and_replace_recursive(payload.args, self.__patterns)
            payload = payload.model_copy(update={"args": modified_args})
        return ToolPreInvokeResult(modified_payload=payload)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        if payload.result and isinstance(payload.result, dict):
            modified_result = _scan_and_replace_recursive(payload.result, self.__patterns)
            payload = payload.model_copy(update={"result": modified_result})
        elif payload.result and isinstance(payload.result, str):
            result = payload.result
            for pattern, replacement in self.__patterns:
                result = pattern.sub(replacement, result)
            payload = payload.model_copy(update={"result": result})
        return ToolPostInvokeResult(modified_payload=payload)
