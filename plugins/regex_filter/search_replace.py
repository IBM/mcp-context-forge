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


def _scan_and_replace_recursive(value: Any, patterns: list[tuple]) -> Any:
    """Recursively scan and replace patterns in nested structures.

    This function walks through nested dictionaries, lists, and strings,
    applying regex patterns to all string values regardless of nesting depth.

    Args:
        value: The value to scan (can be str, dict, list, or other types).
        patterns: List of (compiled_pattern, replacement) tuples.

    Returns:
        Modified value with patterns replaced in all nested strings.

    Raises:
        RecursionError: Propagated naturally if the payload structure exceeds
            Python's recursion limit (~950 levels on CPython).
    """
    if isinstance(value, str):
        result = value
        for pattern, replacement in patterns:
            result = pattern.sub(replacement, result)
        return result
    elif isinstance(value, dict):
        return {k: _scan_and_replace_recursive(v, patterns) for k, v in value.items()}
    elif isinstance(value, list):
        return [_scan_and_replace_recursive(item, patterns) for item in value]
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
            try:
                modified_args = _scan_and_replace_recursive(payload.args, self.__patterns)
            except RecursionError:
                logger.error("regex_filter: RecursionError scanning prompt args — payload is pathologically nested; aborting hook")
                raise
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
            try:
                modified_args = _scan_and_replace_recursive(payload.args, self.__patterns)
            except RecursionError:
                logger.error("regex_filter: RecursionError scanning tool args — payload is pathologically nested; aborting hook")
                raise
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
            try:
                modified_result = _scan_and_replace_recursive(payload.result, self.__patterns)
            except RecursionError:
                logger.error("regex_filter: RecursionError scanning tool result — payload is pathologically nested; aborting hook")
                raise
            payload = payload.model_copy(update={"result": modified_result})
        elif payload.result and isinstance(payload.result, str):
            result = payload.result
            for pattern, replacement in self.__patterns:
                result = pattern.sub(replacement, result)
            payload = payload.model_copy(update={"result": result})
        return ToolPostInvokeResult(modified_payload=payload)
