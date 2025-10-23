# -*- coding: utf-8 -*-
"""Location: ./plugins/deny_filter/deny.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Simple example plugin for searching and replacing text.
This module loads configurations for plugins.
"""

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    PassthroughPreRequestPayload,
    PassthroughPreRequestResult,
    PassthroughPostResponsePayload,
    PassthroughPostResponseResult,
)
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class DenyListConfig(BaseModel):
    """Configuration for deny list plugin.

    Attributes:
        words: List of words to deny.
    """

    words: list[str]


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
            for key in payload.args:
                if any(word in payload.args[key] for word in self._deny_list):
                    violation = PluginViolation(
                        reason="Prompt not allowed",
                        description="A deny word was found in the prompt",
                        code="deny",
                        details={},
                    )
                    logger.warning(f"Deny word detected in prompt argument '{key}'")
                    return PromptPrehookResult(modified_payload=payload, violation=violation, continue_processing=False)
        return PromptPrehookResult(modified_payload=payload)

    async def shutdown(self) -> None:
        """Cleanup when plugin shuts down."""
        logger.info("Deny list plugin shutting down")

    async def passthrough_pre_request(self, payload: PassthroughPreRequestPayload, context: PluginContext) -> PassthroughPreRequestResult:
        """Inspect passthrough request and block when deny words are present.

        This will scan URL, headers, params and body (stringified) for deny words.
        """
        # Helper to test a value for deny words
        def _contains_deny(value: object) -> bool:
            if value is None:
                return False
            try:
                s = value if isinstance(value, str) else str(value)
            except Exception:
                return False
            for word in self._deny_list:
                if word in s:
                    return True
            return False

        # Check URL
        if _contains_deny(payload.url):
            violation = PluginViolation(reason="Deny word in URL", description="A deny word was found in the request URL", code="deny", details={})
            logger.warning("Deny word detected in passthrough request URL")
            return PassthroughPreRequestResult(modified_payload=payload, violation=violation, continue_processing=False)

        # Check headers
        for _, v in (payload.headers or {}).items():
            if _contains_deny(v):
                violation = PluginViolation(reason="Deny word in header", description="A deny word was found in request headers", code="deny", details={})
                logger.warning("Deny word detected in passthrough request headers")
                return PassthroughPreRequestResult(modified_payload=payload, violation=violation, continue_processing=False)

        # Check params
        for _, v in (payload.params or {}).items():
            if _contains_deny(v):
                violation = PluginViolation(reason="Deny word in params", description="A deny word was found in query parameters", code="deny", details={})
                logger.warning("Deny word detected in passthrough request params")
                return PassthroughPreRequestResult(modified_payload=payload, violation=violation, continue_processing=False)

        # Check body (stringify non-None values)
        if _contains_deny(payload.body):
            violation = PluginViolation(reason="Deny word in body", description="A deny word was found in request body", code="deny", details={})
            logger.warning("Deny word detected in passthrough request body")
            return PassthroughPreRequestResult(modified_payload=payload, violation=violation, continue_processing=False)

        return PassthroughPreRequestResult(modified_payload=payload)

    async def passthrough_post_response(self, payload: PassthroughPostResponsePayload, context: PluginContext) -> PassthroughPostResponseResult:
        """Inspect passthrough response content for deny words and optionally block.

        Scans the response content (string/bytes) and returns a violation if a deny word is found.
        """
        content = payload.content
        if content is None and hasattr(payload.response, "text"):
            try:
                content = payload.response.text
            except Exception:
                content = None

        try:
            s = content if isinstance(content, str) else (content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content))
        except Exception:
            s = ""

        for word in self._deny_list:
            if word in s:
                violation = PluginViolation(reason="Deny word in response", description="A deny word was found in response content", code="deny", details={})
                logger.warning("Deny word detected in passthrough response content")
                return PassthroughPostResponseResult(modified_payload=payload, violation=violation, continue_processing=False)

        return PassthroughPostResponseResult(modified_payload=payload)
