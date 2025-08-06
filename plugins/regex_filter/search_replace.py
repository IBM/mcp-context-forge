# -*- coding: utf-8 -*-
"""Simple example plugin for searching and replacing text.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

This module loads configurations for plugins.
"""
# Standard
import re

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig
from mcpgateway.plugins.framework.plugin_types import PluginContext, PromptPosthookPayload, PromptPosthookResult, PromptPrehookPayload, PromptPrehookResult


class SearchReplace(BaseModel):
    search: str
    replace: str

class SearchReplaceConfig(BaseModel):
    words: list[SearchReplace]



class SearchReplacePlugin(Plugin):
    """Example search replace plugin."""
    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self._srconfig = SearchReplaceConfig.model_validate(self._config.config)
        self.__patterns = []
        for word in self._srconfig.words:
            self.__patterns.append((r'{}'.format(word.search), word.replace))




    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        if payload.args:
            for pattern in self.__patterns:
                for key in payload.args:
                  value = re.sub(
                            pattern[0],
                            pattern[1],
                            payload.args[key]
                        )
                  payload.args[key] = value
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
            for index, message in enumerate(payload.result.messages):
                for pattern in self.__patterns:
                  value = re.sub(
                            pattern[0],
                            pattern[1],
                            message.content.text
                        )
                  payload.result.messages[index].content.text = value
        return PromptPosthookResult(modified_payload=payload)
