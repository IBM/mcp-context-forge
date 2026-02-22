# -*- coding: utf-8 -*-
"""Location: ./plugins/deny_filter/deny_ac.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Aho-Corasick implementation for searching and replacing text.
This module uses the aho-corasick package for efficient multi-pattern string matching.
"""

# Third-Party
import ahocorasick  # pyahocorasick package

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPrehookPayload,
    PromptPrehookResult,
)
from mcpgateway.services.logging_service import LoggingService

from plugins.deny_filter.deny import DenyListConfig
from plugins.deny_filter.deny_violation import deny_violation

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)



class DenyListAcPlugin(Plugin):
    """Aho-Corasick based deny list plugin."""

    def __init__(self, config: PluginConfig):
        """Initialize the deny list plugin with Aho-Corasick automaton.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        dconfig = DenyListConfig.model_validate(self._config.config)
        self._automaton = self._build_automaton(dconfig.words)

    def _build_automaton(self, words: list[str]) -> ahocorasick.Automaton | None:
        """Build the Aho-Corasick automaton for efficient pattern matching.

        Args:
            words: List of words to search for.

        Returns:
            Configured Aho-Corasick automaton, or None if no words provided.
        """
        if not words:
            return None
        automaton = ahocorasick.Automaton(ahocorasick.STORE_ANY, ahocorasick.KEY_STRING)
        for word in words:
            # Add lowercase version for case-insensitive matching
            automaton.add_word(word.lower(), word)
        automaton.make_automaton()
        return automaton

    def _contains_deny_word(self, text: str) -> bool:
        """Check if text contains any deny words using Aho-Corasick.

        Args:
            text: Text to search.

        Returns:
            True if a deny word is found, False otherwise.
        """
        if not text or self._automaton is None:
            return False
        # Convert to lowercase for case-insensitive matching
        text_lower = text.lower()
        for _ in self._automaton.iter(text_lower):
            return True
        return False

    async def prompt_pre_fetch(
        self, payload: PromptPrehookPayload, _context: PluginContext
    ) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        if payload.args:
            for key, value in payload.args.items():
                if isinstance(value, str) and self._contains_deny_word(value):
                    logger.warning("Deny word detected in prompt argument '%s'", key)
                    return deny_violation(payload)
        return PromptPrehookResult(modified_payload=payload)

    async def shutdown(self) -> None:
        """Cleanup when plugin shuts down."""
        logger.info("Deny list Aho-Corasick plugin shutting down")
