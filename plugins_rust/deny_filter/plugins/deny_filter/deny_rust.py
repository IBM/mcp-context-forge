# -*- coding: utf-8 -*-
"""Location: ./plugins/deny_filter/deny.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo, Dmitry Zakharov

Simple example plugin for searching and replacing text.
"""

# First-Party
from typing import Any

from deny_filter import DenyList
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


class DenyListPluginRust(Plugin):
    """Example deny list plugin."""

    def __init__(self, config: PluginConfig):
        """Initialize the deny list plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        dconfig = DenyListConfig.model_validate(self._config.config)
        self._deny_list: Any = DenyList(dconfig.words)

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
        if payload.args and self._deny_list.scan_any(payload.args):
            logger.warning("Deny word detected in prompt")
            return deny_violation(payload)
        return PromptPrehookResult(modified_payload=payload)
