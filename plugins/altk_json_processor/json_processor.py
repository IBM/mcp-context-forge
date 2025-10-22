# -*- coding: utf-8 -*-
"""Uses JSON Processor from ALTK to extract data from long JSON responses.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jason Tsay

This module loads configurations for plugins.
"""

# Standard
import json
import os
from typing import cast

# Third-Party
from altk.core.llm import get_llm

# Third-party
from altk.core.toolkit import AgentPhase
from altk.post_tool.code_generation.code_generation import CodeGenerationComponent, CodeGenerationComponentConfig
from altk.post_tool.core.toolkit import CodeGenerationRunInput, CodeGenerationRunOutput

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService

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
        provider = self._cfg["llm_provider"]
        llm_client = None
        if provider == "watsonx":
            watsonx_client = get_llm("watsonx")
            if len(self._cfg["watsonx"]["wx_api_key"]) > 0:
                api_key = self._cfg["watsonx"]["wx_api_key"]
            else:
                # Note that we assume here this env var exists and should throw an error if not
                api_key = os.environ["WX_API_KEY"]
            if len(self._cfg["watsonx"]["wx_project_id"]) > 0:
                project_id = self._cfg["watsonx"]["wx_project_id"]
            else:
                # Note that we assume here this env var exists and should throw an error if not
                project_id = os.environ["WX_PROJECT_ID"]
            llm_client = watsonx_client(model_id=self._cfg["model_id"], api_key=api_key, project_id=project_id, url=self._cfg["watsonx"]["wx_url"])
        elif provider == "openai":
            openai_client = get_llm("openai.sync")
            if len(self._cfg["openai"]["api_key"]) > 0:
                api_key = self._cfg["openai"]["api_key"]
            else:
                # Note that we assume here this env var exists and should throw an error if not
                api_key = os.environ["OPENAI_API_KEY"]
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
                # Note that we assume here this env var exists and should throw an error if not
                api_key = os.environ["ANTHROPIC_API_KEY"]
            llm_client = anthropic_client(model_name=model_path, api_key=api_key)
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
                    try:
                        response_json = json.loads(response_str)
                    except json.decoder.JSONDecodeError:
                        # ignore anything that's not json
                        pass

        if response_json and response_str and len(response_str) > self._cfg["length_threshold"]:
            logger.info("Long JSON response detected, using ALTK JSON Processor...")
            codegen = CodeGenerationComponent(config=config)
            nl_query = self._cfg["jsonprocessor_query"]
            input_data = CodeGenerationRunInput(messages=[], nl_query=nl_query, tool_response=response_json)
            output = codegen.process(input_data, AgentPhase.RUNTIME)
            output = cast(CodeGenerationRunOutput, output)
            payload.result["content"][0]["text"] = output.result
            logger.debug(f"ALTK processed response: {output.result}")
            return ToolPostInvokeResult(continue_processing=True, modified_payload=payload)

        return ToolPostInvokeResult(continue_processing=True)
