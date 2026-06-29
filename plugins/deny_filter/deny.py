# -*- coding: utf-8 -*-
"""Location: ./plugins/deny_filter/deny.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Simple example plugin for searching and replacing text.
This module loads configurations for plugins.
"""

# Standard
from typing import Any

# Third-Party
from pydantic import BaseModel

# First-Party
from cpex.framework import Plugin, PluginConfig, PluginContext, PluginViolation, PromptPrehookPayload, PromptPrehookResult
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class DenyListConfig(BaseModel):
    """Configuration for deny list plugin.

    Attributes:
        words: List of words to deny.
    """

    words: list[str]


def _scan_for_denied_words(value: Any, deny_list: list[str], path: str = "") -> list[str]:
    """Recursively scan for denied words in nested structures.

    This function walks through nested dictionaries, lists, and strings,
    checking all string values for denied words regardless of nesting depth.

    Args:
        value: The value to scan (can be str, dict, list, or other types).
        deny_list: List of denied words to check for.
        path: Current path in the structure (for error reporting).

    Returns:
        List of paths where denied words were found.

    Raises:
        RecursionError: Propagated naturally if the payload structure exceeds
            Python's recursion limit (~950 levels on CPython).
    """
    violations: list[str] = []
    if isinstance(value, str):
        for word in deny_list:
            if word.lower() in value.lower():
                violations.append(f"{path}: contains '{word}'")
    elif isinstance(value, dict):
        for k, v in value.items():
            new_path = f"{path}.{k}" if path else k
            violations.extend(_scan_for_denied_words(v, deny_list, new_path))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            new_path = f"{path}[{i}]"
            violations.extend(_scan_for_denied_words(item, deny_list, new_path))
    return violations


class DenyListPlugin(Plugin):
    """Example deny list plugin."""

    def __init__(self, config: PluginConfig):
        """Initialize the deny list plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._dconfig = DenyListConfig.model_validate(self._config.config)
        self._deny_list = []
        for word in self._dconfig.words:
            self._deny_list.append(word)

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
                violations = _scan_for_denied_words(payload.args, self._deny_list)
            except RecursionError:
                logger.error("deny_filter: RecursionError scanning prompt args — payload is pathologically nested; aborting hook")
                raise
            if violations:
                violation = PluginViolation(
                    reason="Prompt not allowed",
                    description="Denied words found in prompt",
                    code="deny",
                    details={"violations": violations},
                )
                logger.warning(f"Denied words detected: {violations}")
                return PromptPrehookResult(
                    modified_payload=payload,
                    violation=violation,
                    continue_processing=False,
                )
        return PromptPrehookResult(modified_payload=payload)

    async def shutdown(self) -> None:
        """Cleanup when plugin shuts down."""
        logger.info("Deny list plugin shutting down")
