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
from llmguardplugin.cache import CacheTTLDict


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
        self.cache = CacheTTLDict(ttl=self.lgconfig.cache_ttl)
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
                if self.lgconfig.input.filters:
                    logger.info(f"Applying input guardrail filters on {payload.args[key]}")
                    result = self.llmguard_instance._apply_input_filters(payload.args[key])
                    logger.info(f"Result of input guardrail filters: {result}")
                    decision = self.llmguard_instance._apply_policy_input(result)
                    logger.info(f"Result of policy decision: {decision}")
                    context.state["original_prompt"] = payload.args[key]
                    if not decision[0]:
                        violation = PluginViolation(
                        reason=decision[1],
                        description="{threat} detected in the prompt".format(threat=list(decision[2].keys())[0]),
                        code="deny",
                        details=decision[2],)
                        return PromptPrehookResult(violation=violation, continue_processing=False)
                    
                if self.lgconfig.input.sanitizers:
                    context.state["guardrails"] = {}
                    context.global_context.state["guardrails"] = {}
                    logger.info(f"Applying input guardrail sanitizers on {payload.args[key]}")
                    result = self.llmguard_instance._apply_input_sanitizers(payload.args[key])
                    logger.info(f"Result of input guardrail sanitizers: {result}")

                    # Set context for the original prompt to be passed further                  
                    context.state["guardrails"]["original_prompt"] = payload.args[key]
                    context.global_context.state["guardrails"]["original_prompt"] = payload.args[key]
                    
                    # Set context for the vault if used
                    if hasattr(self.llmguard_instance, "vault"):
                        vault_id = id(self.llmguard_instance.vault)
                        self.cache.update_cache(vault_id,self.llmguard_instance.vault._tuples)
                        context.global_context.state["guardrails"]["vault_cache_id"] = vault_id
                        context.state["guardrails"]["vault_cache_id"] = vault_id
                    payload.args[key] = result[0] 
        
        return PromptPrehookResult(continue_processing=True,modified_payload=payload)

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

        original_prompt = ""
        vault_id = None
        # Process each message
        for message in payload.result.messages:
            if message.content and hasattr(message.content, 'text'):
                if self.lgconfig.output.sanitizers:
                    text = message.content.text
                    logger.info(f"Applying output sanitizers on {text}")
                    if "guardrails" in context.state:
                        if "original_prompt" in context.state["guardrails"]:
                            original_prompt = context.state["guardrails"]["original_prompt"]
                        if "vault_cache_id" in context.state["guardrails"]:
                            vault_id = context.state["guardrails"]["vault_cache_id"]
                    if "guardrails" in context.global_context.state:
                        if "original_prompt" in context.global_context.state["guardrails"]:
                            original_prompt = context.global_context.state["guardrails"]["original_prompt"]
                        if "vault_cache_id" in context.global_context.state["guardrails"]:
                            vault_id = context.global_context.state["guardrails"]["vault_cache_id"]
                    if vault_id:
                        vault_obj = self.cache.retrieve_cache(vault_id)
                        scanner_config = {"Deanonymize" : vault_obj}                        
                        self.llmguard_instance._update_output_sanitizers(scanner_config)
                    result = self.llmguard_instance._apply_output_sanitizers(original_prompt,text)
                    logger.info(f"Result of output sanitizers: {result}")
                    message.content.text = result[0]
                
                if self.lgconfig.output.filters:
                    text = message.content.text
                    logger.info(f"Applying output guardrails on {text}")
                    original_prompt = context.state["original_prompt"] if "original_prompt" in context.state else ""
                    result = self.llmguard_instance._apply_output_filters(original_prompt,text)
                    decision = self.llmguard_instance._apply_policy_output(result)
                    logger.info(f"Policy decision on output guardrails: {decision}")
                    if not decision[0]:
                            violation = PluginViolation(
                            reason=decision[1],
                            description="{threat} detected in the prompt".format(threat=list(decision[2].keys())[0]),
                            code="deny",
                            details=decision[2],)
                            return PromptPosthookResult(violation=violation, continue_processing=False)           
        # destroy any cache
        self.cache.delete_cache()
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
