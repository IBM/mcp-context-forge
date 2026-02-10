# -*- coding: utf-8 -*-
"""A plugin that leverages the capabilities of llmguard library to apply guardrails on input and output prompts.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins.
"""

# Third-Party
from llmguardplugin.cache import CacheTTLDict
from llmguardplugin.llmguard import LLMGuardBase
from llmguardplugin.schema import LLMGuardConfig

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginError,
    PluginErrorModel,
    PluginViolation,
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

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class LLMGuardPlugin(Plugin):
    """A plugin that leverages the capabilities of llmguard library to apply guardrails on input and output prompts.

    Attributes:
        lgconfig: Configuration for guardrails.
        cache: Cache object of class CacheTTLDict for plugins.
        guardrails_context_key: Key to set in context for any guardrails related processing and information storage.
    """

    def __init__(self, config: PluginConfig) -> None:
        """Entry init block for plugin. Validates the configuration of plugin and initializes an instance of LLMGuardBase with the config

        Args:
            config: the skill configuration

        Raises:
            PluginError: If the configuration is invalid for plugin initialization.
        """
        super().__init__(config)
        self.lgconfig = LLMGuardConfig.model_validate(self._config.config)
        self.cache = CacheTTLDict(ttl=self.lgconfig.cache_ttl)
        self.guardrails_context_key = "guardrails"
        if self.__verify_lgconfig():
            self.llmguard_instance = LLMGuardBase(config=self._config.config)
        else:
            raise PluginError(error=PluginErrorModel(message="Invalid configuration for plugin initilialization", plugin_name=self.name))

    def __verify_lgconfig(self):
        """Checks if the configuration provided for plugin is valid or not. It should either have input or output key atleast

        Returns:
            bool: True if configuration is valid (has input or output), False otherwise.
        """
        return self.lgconfig.input or self.lgconfig.output

    def __update_context(self, context, key, value):
        """Update Context implementation.

        Args:
            context: The plugin context to update.
            key: The key to set in context.
            value: The value to set for the key.
        """

        def update_context(context):
            """Update Context implementation.

            Args:
                context: The plugin context to update.
            """

            plugin_name = self.__class__.__name__
            if plugin_name not in context.state[self.guardrails_context_key]:
                context.state[self.guardrails_context_key][plugin_name] = {}
            if key not in context.state[self.guardrails_context_key][plugin_name]:
                context.state[self.guardrails_context_key][plugin_name][key] = value
            else:
                if isinstance(value, dict):
                    for k, v in value.items():
                        if k not in context.state[self.guardrails_context_key][plugin_name][key]:
                            context.state[self.guardrails_context_key][plugin_name][key][k] = v
                        else:
                            if isinstance(v, dict):
                                for k_sub, v_sub in v.items():
                                    context.state[self.guardrails_context_key][plugin_name][key][k][k_sub] = v_sub

        if key == "context":
            update_context(context)
            update_context(context.global_context)
        else:
            if key not in context.state[self.guardrails_context_key]:
                context.state[self.guardrails_context_key][key] = value
            if key not in context.global_context.state[self.guardrails_context_key]:
                context.global_context.state[self.guardrails_context_key][key] = value

    def _create_filter_violation(self, decision: tuple) -> PluginViolation:
        """Create a violation object for filter failures.

        Args:
            decision: Tuple containing (success, reason, details) from policy decision.

        Returns:
            PluginViolation object with appropriate error details.
        """
        return PluginViolation(
            reason=decision[1],
            description=f"{list(decision[2].keys())[0]} detected in the prompt",
            code="deny",
            details=decision[2],
        )

    def _create_sanitizer_violation(self) -> PluginViolation:
        """Create a violation object for sanitizer failures (vault breach attempts).

        Returns:
            PluginViolation object for vault leak detection.
        """
        return PluginViolation(
            reason="Attempt to breach vault",
            description="vault_leak detected in the prompt",
            code="deny",
            details={},
        )

    async def _handle_vault_caching(self, context: PluginContext) -> None:
        """Handle vault caching if vault data is available.

        Args:
            context: The plugin context to update with vault cache ID.
        """
        _, vault_id, vault_tuples = self.llmguard_instance._retreive_vault()
        if vault_id and vault_tuples:
            success, _ = await self.cache.update_cache(vault_id, vault_tuples)
            if success and self.lgconfig.set_guardrails_context:
                self.__update_context(context, "vault_cache_id", vault_id)

    def _initialize_guardrails_context(self, context: PluginContext) -> None:
        """Initialize guardrails context in both local and global state.

        Args:
            context: The plugin context to initialize.
        """
        context.state[self.guardrails_context_key] = {}
        context.global_context.state[self.guardrails_context_key] = {}

    async def _process_input_filters(self, prompt_text: str, context: PluginContext) -> tuple[bool, PluginViolation | None]:
        """Apply input filters and return processing result.

        Args:
            prompt_text: The prompt text to filter.
            context: The plugin context for storing filter results.

        Returns:
            Tuple of (should_continue, violation_if_any).
        """
        filters_context = {"input": {"filters": []}}
        logger.debug("Applying input guardrail filters on %s", prompt_text)

        result = await self.llmguard_instance._apply_input_filters(prompt_text)
        filters_context["input"]["filters"].append(result)
        logger.debug("Result of input guardrail filters: %s", result)

        decision = self.llmguard_instance._apply_policy_input(result)
        logger.debug("Result of policy decision: %s", decision)

        if self.lgconfig.set_guardrails_context:
            self.__update_context(context, "context", filters_context)

        if not decision[0]:
            violation = self._create_filter_violation(decision)
            return False, violation

        return True, None

    async def _process_input_sanitizers(self, prompt_text: str, context: PluginContext) -> tuple[bool, str | None, PluginViolation | None]:
        """Apply input sanitizers and return processing result.

        Args:
            prompt_text: The prompt text to sanitize.
            context: The plugin context for storing sanitizer results.

        Returns:
            Tuple of (should_continue, sanitized_text, violation_if_any).
        """
        sanitizers_context = {"input": {"sanitizers": []}}
        logger.debug("Applying input guardrail sanitizers on %s", prompt_text)

        result = await self.llmguard_instance._apply_input_sanitizers(prompt_text)
        sanitizers_context["input"]["sanitizers"].append(result)
        logger.debug("Result of input guardrail sanitizers on %s", result)

        if self.lgconfig.set_guardrails_context:
            self.__update_context(context, "context", sanitizers_context)

        if not result:
            violation = self._create_sanitizer_violation()
            logger.info("violation %s", violation)
            return False, None, violation

        # Handle vault caching
        await self._handle_vault_caching(context)

        return True, result[0], None

    def _get_guardrails_state(self, context: PluginContext) -> tuple[str, str | None]:
        """Retrieve original_prompt and vault_id from context state.

        Args:
            context: The plugin context to query.

        Returns:
            Tuple of (original_prompt, vault_cache_id).
        """
        original_prompt = ""
        vault_id = None

        # Check local context state
        if self.guardrails_context_key in context.state:
            state = context.state[self.guardrails_context_key]
            original_prompt = state.get("original_prompt", "")
            vault_id = state.get("vault_cache_id")
        else:
            context.state[self.guardrails_context_key] = {}

        # Check global context state (overrides local if present)
        if self.guardrails_context_key in context.global_context.state:
            global_state = context.global_context.state[self.guardrails_context_key]
            original_prompt = global_state.get("original_prompt", original_prompt)
            vault_id = global_state.get("vault_cache_id", vault_id)
        else:
            context.global_context.state[self.guardrails_context_key] = {}

        return original_prompt, vault_id

    async def _process_output_sanitizers(self, original_prompt: str, text: str, vault_id: str | None, context: PluginContext) -> tuple[bool, str]:
        """Apply output sanitizers and return processing result.

        Args:
            original_prompt: The original input prompt.
            text: The output text to sanitize.
            vault_id: Optional vault cache ID for deanonymization.
            context: The plugin context for storing sanitizer results.

        Returns:
            Tuple of (should_continue, sanitized_text).
        """
        sanitizers_context = {"output": {"sanitizers": []}}
        logger.debug("Applying output sanitizers on %s", text)

        # Update sanitizer config with vault data if available
        if vault_id:
            vault_obj = await self.cache.retrieve_cache(vault_id)
            scanner_config = {"Deanonymize": vault_obj}
            self.llmguard_instance._update_output_sanitizers(scanner_config)

        result = await self.llmguard_instance._apply_output_sanitizers(original_prompt, text)
        sanitizers_context["output"]["sanitizers"].append(result)

        if self.lgconfig.set_guardrails_context:
            self.__update_context(context, "context", sanitizers_context)

        logger.debug("Result of output sanitizers:  %s", result)
        return True, result[0]

    async def _process_output_filters(self, original_prompt: str, text: str, context: PluginContext) -> tuple[bool, PluginViolation | None]:
        """Apply output filters and return processing result.

        Args:
            original_prompt: The original input prompt.
            text: The output text to filter.
            context: The plugin context for storing filter results.

        Returns:
            Tuple of (should_continue, violation_if_any).
        """
        filters_context = {"output": {"filters": []}}
        logger.debug("Applying output guardrails on %s", text)

        result = await self.llmguard_instance._apply_output_filters(original_prompt, text)
        filters_context["output"]["filters"].append(result)

        decision = self.llmguard_instance._apply_policy_output(result)
        logger.debug("Policy decision on output guardrails: %s", decision)

        if self.lgconfig.set_guardrails_context:
            self.__update_context(context, "context", filters_context)

        if not decision[0]:
            violation = self._create_filter_violation(decision)
            logger.info("violation %s", violation)
            return False, violation

        return True, None

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook to apply input guardrails on using llmguard.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        logger.debug("Processing payload %s", payload)

        # Early return if no args to process
        if not payload.args:
            return PromptPrehookResult(continue_processing=True, modified_payload=payload)

        for key in payload.args:
            # Set context to pass original prompt within and across plugins
            if self.lgconfig.input.filters or self.lgconfig.input.sanitizers:
                self._initialize_guardrails_context(context)
                self.__update_context(context, "original_prompt", payload.args[key])

            # Apply input filters if set in config
            if self.lgconfig.input.filters:
                should_continue, violation = await self._process_input_filters(payload.args[key], context)
                if not should_continue:
                    return PromptPrehookResult(violation=violation, continue_processing=False)

            # Apply input sanitizers if set in config
            if self.lgconfig.input.sanitizers:
                should_continue, sanitized_text, violation = await self._process_input_sanitizers(payload.args[key], context)
                if not should_continue:
                    return PromptPrehookResult(violation=violation, continue_processing=False)
                payload.args[key] = sanitized_text

        return PromptPrehookResult(continue_processing=True, modified_payload=payload)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook to apply output guardrails on output.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        logger.info("Processing result %s", payload.result)
        if not payload.result.messages:
            return PromptPosthookResult()

        # Retrieve context state once before processing messages
        if self.lgconfig.output.filters or self.lgconfig.output.sanitizers:
            original_prompt, vault_id = self._get_guardrails_state(context)
        else:
            return PromptPosthookResult(continue_processing=True, modified_payload=payload)

        # Process each message
        for message in payload.result.messages:
            if not (message.content and hasattr(message.content, "text")):
                continue

            text = message.content.text

            # Apply output sanitizers if configured
            if self.lgconfig.output.sanitizers:
                _, sanitized_text = await self._process_output_sanitizers(original_prompt, text, vault_id, context)
                message.content.text = sanitized_text
                text = sanitized_text

            # Apply output filters if configured
            if self.lgconfig.output.filters:
                should_continue, violation = await self._process_output_filters(original_prompt, text, context)
                if not should_continue:
                    return PromptPosthookResult(violation=violation, continue_processing=False)

        return PromptPosthookResult(continue_processing=True, modified_payload=payload)

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
