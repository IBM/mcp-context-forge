# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/utils/llm_util.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

MCP Gateway - Main module for using and supporting MCP-CF LLM providers in toolops modules.

This module defines the utility funtions to use MCP-CF supported LLM providers in toolops.
"""

# Third-Party
import orjson

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.mcp_client_chat_service import GatewayConfig, GatewayProvider, LLMConfig

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# set LLM temperature for toolops modules as low to produce minimally variable model outputs.
TOOLOPS_TEMPERATURE = 0.1
TOOLOPS_MAX_TOKENS = 1000
TOOLOPS_MODEL_TYPE = "chat"


def get_llm_instance(model_id, model_type=TOOLOPS_MODEL_TYPE):
    """
    Method to get MCP-CF provider type llm instance based on model type

    Args:
        model_id : LLM model used for toolops functionality
        model_type : LLM instance type such as chat model or token completion model, accepted values: 'completion', 'chat'

    Returns:
        llm_model_instance : LLM model instance used for inferencing the prompts/user inputs
        llm_config: LLM provider configuration provided in the environment variables

    Examples:
        >>> import os
        >>> from unittest.mock import patch, MagicMock
        >>> # Setup: Define the global variable used in the function for the test context
        >>> global TOOLOPS_TEMPERATURE
        >>> TOOLOPS_TEMPERATURE = 0.7
        >>> global TOOLOPS_MAX_TOKENS
        >>> TOOLOPS_MAX_TOKENS = 1000
        >>> global TOOLOPS_MODEL_TYPE
        >>> TOOLOPS_MODEL_TYPE = "chat"

        >>> # Case 1: Gateway Provider Configuration
        >>> # Configure Gateway Provider LLM model via Admin UI -> Settings -> LLM Settings.
        >>> # Assuming Gateway Provider Configuration and are available in the module scope
        >>> llm_model_instance, llm_config = get_llm_instance(model_id="global/ibm-granite-8b")
        >>> llm_config.__class__.__name__
        'LLMConfig'

    """
    llm_model_instance, llm_config = None, None
    try:
        logger.info("Configuring LLM instance for ToolOps , and LLM model - " + model_id)
        config = GatewayConfig(model=model_id, temperature=TOOLOPS_TEMPERATURE, max_tokens=TOOLOPS_MAX_TOKENS)  # doctest: +SKIP
        llm_config = LLMConfig(provider="gateway", config=config)
        provider = GatewayProvider(config)
        llm_model_instance = provider.get_llm(model_type)
        logger.info("Successfully configured LLM instance for ToolOps , and LLM model - " + model_id)
    except Exception as e:
        logger.info("Error in configuring LLM instance for ToolOps -" + str(e))
    return llm_model_instance, llm_config


def execute_prompt(prompt, model_id, model_type):
    """
    Method for LLM inferencing using a prompt/user input

    Args:
        prompt: used specified prompt or inputs for LLM inferecning
        model_id : LLM model used for toolops functionality
        model_type : LLM instance type such as chat model or token completion model, accepted values: 'completion', 'chat'

    Returns:
        response: LLM output response for the given prompt
    """
    try:
        logger.info("Inferencing OpenAI provider LLM with the given prompt")
        completion_llm_instance, _ = get_llm_instance(model_id, model_type)
        llm_response = completion_llm_instance.invoke(prompt, stop=["\n\n", "<|endoftext|>", "###STOP###"])
        response = llm_response.replace("<|eom_id|>", "").strip()
        # logger.info("Successful - Inferencing OpenAI provider LLM")
        return response
    except Exception as e:
        logger.error("Error in configuring LLM using gateway provider - " + orjson.dumps({"Error": str(e)}).decode())
        return ""


# if __name__ == "__main__":
#     model_id = "global/meta-llama/llama-3-3-70b-instruct"
#     model_type = 'completion'
#     chat_llm_instance, _ = get_llm_instance(model_id=model_id)
#     completion_llm_instance, _ = get_llm_instance(model_id=model_id)
#     prompt = "what is India capital city?"
#     print("Prompt : ", prompt)
#     print("Text completion output : ")
#     print(execute_prompt(prompt,model_id,model_type))
#     response = chat_llm_instance.invoke(prompt)
#     print("Chat completion output : ")
#     print(response.content)