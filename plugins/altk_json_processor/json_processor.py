# -*- coding: utf-8 -*-
"""Uses JSON Processor from ALTK to extract data from long JSON responses.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jason Tsay

This module loads configurations for plugins.
"""

# Standard
import os
from typing import cast, TYPE_CHECKING

# Third-Party
import orjson

# ALTK imports - optional dependency
ALTK_AVAILABLE = False
try:
    # Third-Party
    from altk.core.llm import get_llm
    from altk.core.toolkit import AgentPhase
    from altk.post_tool.code_generation.code_generation import CodeGenerationComponent, CodeGenerationComponentConfig
    from altk.post_tool.core.toolkit import CodeGenerationRunInput, CodeGenerationRunOutput

    ALTK_AVAILABLE = True
except ImportError:
    # ALTK is an optional dependency - will be handled gracefully at runtime
    if TYPE_CHECKING:
        from altk.core.llm import get_llm
        from altk.core.toolkit import AgentPhase
        from altk.post_tool.code_generation.code_generation import CodeGenerationComponent, CodeGenerationComponentConfig
        from altk.post_tool.core.toolkit import CodeGenerationRunInput, CodeGenerationRunOutput

# First-Party
from mcpgateway.plugins.framework import (  # noqa: E402  # pylint: disable=wrong-import-position
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService  # noqa: E402  # pylint: disable=wrong-import-position

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ALTKJsonProcessor(Plugin):
    """Uses JSON Processor from ALTK to extract data from long JSON responses."""

    def __init__(self, config: PluginConfig):
        """Entry init block for plugin.

        Args:
            config: the plugin configuration
        """
        super().__init__(config)
        if config.config:
            self._cfg = config.config
        else:
            self._cfg = {}

        if not ALTK_AVAILABLE:
            logger.warning("ALTKJsonProcessor: ALTK is not installed. Plugin will skip JSON processing.")

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Raises:
            ValueError: if a provider api key is not provided in either config or env var

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        if not ALTK_AVAILABLE:
            logger.debug("ALTKJsonProcessor: ALTK not available, skipping JSON processing.")
            return ToolPostInvokeResult(continue_processing=True)

        provider = self._cfg["llm_provider"]
        llm_client = None
        if provider == "watsonx":
            watsonx_client = get_llm("watsonx")
            if len(self._cfg["watsonx"]["wx_api_key"]) > 0:
                api_key = self._cfg["watsonx"]["wx_api_key"]
            else:
                api_key = os.getenv("WX_API_KEY")
                if not api_key:
                    raise ValueError("WatsonX api key not found, provide WX_API_KEY either in the plugin config or as an env var.")
            if len(self._cfg["watsonx"]["wx_project_id"]) > 0:
                project_id = self._cfg["watsonx"]["wx_project_id"]
            else:
                project_id = os.getenv("WX_PROJECT_ID")
                if not project_id:
                    raise ValueError("WatsonX project id not found, project WX_PROJECT_ID either in the plugin config or as an env var.")
            llm_client = watsonx_client(model_id=self._cfg["model_id"], api_key=api_key, project_id=project_id, url=self._cfg["watsonx"]["wx_url"])
        elif provider == "openai":
            openai_client = get_llm("openai.sync")
            if len(self._cfg["openai"]["api_key"]) > 0:
                api_key = self._cfg["openai"]["api_key"]
            else:
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    raise ValueError("OpenAI api key not found, provide OPENAI_API_KEY either in the plugin config or as an env var.")
            llm_client = openai_client(api_key=api_key, model=self._cfg["model_id"])
        elif provider == "ollama":
            ollama_client = get_llm("litellm.ollama")
            llm_client = ollama_client(api_url=self._cfg["ollama"]["ollama_url"], model_name=self._cfg["model_id"])
        elif provider == "anthropic":
            anthropic_client = get_llm("litellm")
            model_path = f"anthropic/{self._cfg['model_id']}"
            if len(self._cfg["anthropic"]["api_key"]) > 0:
                api_key = self._cfg["anthropic"]["api_key"]
            else:
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("Anthropic api key not found, provide ANTHROPIC_API_KEY either in the plugin config or as an env var.")
            llm_client = anthropic_client(model_name=model_path, api_key=api_key)
        elif provider == "pytestmock":
            # only meant to be used for unit tests
            llm_client = None
        else:
            raise ValueError("Unknown provider given for 'llm_provider' in plugin config!")

        config = CodeGenerationComponentConfig(llm_client=llm_client, use_docker_sandbox=False)

        response_json = None
        response_str = None
        if "content" in payload.result:
            if len(payload.result["content"]) > 0:
                content = payload.result["content"][0]
                if "type" in content and content["type"] == "text":
                    response_str = content["text"]

                    if len(response_str) > self._cfg["length_threshold"]:
                        try:
                            response_json = orjson.loads(response_str)
                        except orjson.JSONDecodeError:
                            # ignore anything that's not json
                            pass

        # Should only get here if response is long enough and is valid JSON
        if response_json:
            logger.info("Long JSON response detected, using ALTK JSON Processor...")
            if provider == "pytestmock":
                # only meant for unit testing
                payload.result["content"][0]["text"] = "(filtered response)"
            else:
                codegen = CodeGenerationComponent(config=config)
                nl_query = self._cfg.get("jsonprocessor_query", "")
                input_data = CodeGenerationRunInput(messages=[], nl_query=nl_query, tool_response=response_json)
                output = codegen.process(input_data, AgentPhase.RUNTIME)
                output = cast(CodeGenerationRunOutput, output)
                payload.result["content"][0]["text"] = output.result
                logger.debug(f"ALTK processed response: {output.result}")
            return ToolPostInvokeResult(continue_processing=True, modified_payload=payload)

        return ToolPostInvokeResult(continue_processing=True)
