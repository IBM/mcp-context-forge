# -*- coding: utf-8 -*-
"""A plugin that leverages the capabilities of llmguard library to apply guardrails on input and output prompts.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins.
"""

# First-Party
from llmguardplugin.schema import LLMGuardConfig
from llmguardplugin.llmguard import LLMGuardBase
from mcpgateway.plugins.framework import (
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
from mcpgateway.plugins.framework.models import PluginConfig, PluginViolation
from mcpgateway.plugins.framework import PluginError, PluginErrorModel
from mcpgateway.services.logging_service import LoggingService


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class LLMGuardPlugin(Plugin):
    """A plugin that leverages the capabilities of llmguard library to apply guardrails on input and output prompts."""

    def __init__(self, config: PluginConfig) -> None:
        """Entry init block for plugin. Validates the configuration of plugin and initializes an instance of LLMGuardBase with the config

        Args:
          config: the skill configuration
        """
        super().__init__(config)
        self.lgconfig = LLMGuardConfig.model_validate(self._config.config) 
        if self.__verify_lgconfig():
            self.llmguard_instance = LLMGuardBase(config=self._config.config)
        else:
            raise PluginError(error=PluginErrorModel(message="Invalid configuration for plugin initilialization", plugin_name=self.name))
        
    def __verify_lgconfig(self):
        """Checks if the configuration provided for plugin is valid or not"""
        return self.lgconfig.input or self.lgconfig.output
            
    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook to apply input guardrails on using llmguard.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        logger.info(f"Processing payload {payload}")
        if payload.args:
            for key in payload.args:
                if self.lgconfig.input.sanitizers:
                    logger.info(f"Applying input guardrail sanitizers on {payload.args[key]}")
                    result = self.llmguard_instance._apply_input_sanitizers(payload.args[key])
                    logger.info(f"Result of input guardrail sanitizers: {result}")
                    payload.args[key] = result[0]
                    context.state["original_prompt"] = payload.args[key]
        logger.info(f"context.state {context.state}")
        return PromptPrehookResult(modified_payload=payload,continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook to apply output guardrails on output.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        logger.info(f"Processing result {payload.result}")
        if not payload.result.messages:
            return PromptPosthookResult()

        # Process each message
        for message in payload.result.messages:
            if message.content and hasattr(message.content, 'text'):
                if self.lgconfig.output:
                    text = message.content.text
                    logger.info(f"Applying output sanitizers on {text}")
                    original_prompt = context.state["original_prompt"] if "original_prompt" in context.state else ""
                    result = self.llmguard_instance._apply_output_sanitizers(original_prompt,text)
                    logger.info(f"Result of output sanitizers: {result}")
                    message.content.text = result[0]
        return PromptPosthookResult(continue_processing=True,modified_payload=payload)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        return ToolPostInvokeResult(continue_processing=True)
