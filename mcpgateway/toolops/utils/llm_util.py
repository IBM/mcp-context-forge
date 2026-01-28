# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/utils/llm_util.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

MCP Gateway - Main module for using and supporting MCP-CF LLM providers in toolops modules.

This module defines the utility funtions to use MCP-CF supported LLM providers in toolops.
"""
# Standard
import os

# Third-Party
from dotenv import load_dotenv
import orjson

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.mcp_client_chat_service import (
    AnthropicConfig,
    AnthropicProvider,
    AWSBedrockConfig,
    AWSBedrockProvider,
    AzureOpenAIConfig,
    AzureOpenAIProvider,
    OllamaConfig,
    OllamaProvider,
    OpenAIConfig,
    OpenAIProvider,
    WatsonxConfig,
    WatsonxProvider,
)

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

load_dotenv()

# set LLM temperature for toolops modules as low to produce minimally variable model outputs.
TOOLOPS_TEMPERATURE = 0.1


def get_llm_instance(model_type="completion"):
    """
    Method to get MCP-CF provider type llm instance based on model type

    Args:
        model_type : LLM instance type such as chat model or token completion model, accepted values: 'completion', 'chat'

    Returns:
        llm_instance : LLM model instance used for inferencing the prompts/user inputs
        llm_config: LLM provider configuration provided in the environment variables

    Examples:
        >>> import os
        >>> from unittest.mock import patch, MagicMock
        >>> # Setup: Define the global variable used in the function for the test context
        >>> global TOOLOPS_TEMPERATURE
        >>> TOOLOPS_TEMPERATURE = 0.7

        >>> # Case 1: OpenAI Provider Configuration
        >>> # We patch os.environ to simulate specific provider settings
        >>> env_vars = {
        ...     "LLM_PROVIDER": "openai",
        ...     "OPENAI_API_KEY": "sk-mock-key",
        ...     "OPENAI_BASE_URL": "https://api.openai.com",
        ...     "OPENAI_MODEL": "gpt-4"
        ... }
        >>> with patch.dict(os.environ, env_vars):
        ...     # Assuming OpenAIProvider and OpenAIConfig are available in the module scope
        ...     # We simulate the function call. Note: This tests the Config creation logic.
        ...     llm_instance, llm_config = get_llm_instance("completion")
        ...     llm_config.__class__.__name__
        'OpenAIConfig'

        >>> # Case 2: Azure OpenAI Provider Configuration
        >>> env_vars = {
        ...     "LLM_PROVIDER": "azure_openai",
        ...     "AZURE_OPENAI_API_KEY": "az-mock-key",
        ...     "AZURE_OPENAI_ENDPOINT": "https://mock.azure.com",
        ...     "AZURE_OPENAI_MODEL": "gpt-35-turbo"
        ... }
        >>> with patch.dict(os.environ, env_vars):
        ...     llm_instance, llm_config = get_llm_instance("chat")
        ...     llm_config.__class__.__name__
        'AzureOpenAIConfig'

        >>> # Case 3: AWS Bedrock Provider Configuration
        >>> env_vars = {
        ...     "LLM_PROVIDER": "aws_bedrock",
        ...     "AWS_BEDROCK_MODEL_ID": "anthropic.claude-v2",
        ...     "AWS_BEDROCK_REGION": "us-east-1",
        ...     "AWS_ACCESS_KEY_ID": "mock-access",
        ...     "AWS_SECRET_ACCESS_KEY": "mock-secret"
        ... }
        >>> with patch.dict(os.environ, env_vars):
        ...     llm_instance, llm_config = get_llm_instance("chat")
        ...     llm_config.__class__.__name__
        'AWSBedrockConfig'

        >>> # Case 4: WatsonX Provider Configuration
        >>> env_vars = {
        ...     "LLM_PROVIDER": "watsonx",
        ...     "WATSONX_APIKEY": "wx-mock-key",
        ...     "WATSONX_URL": "https://us-south.ml.cloud.ibm.com",
        ...     "WATSONX_PROJECT_ID": "mock-project-id",
        ...     "WATSONX_MODEL_ID": "ibm/granite-13b"
        ... }
        >>> with patch.dict(os.environ, env_vars):
        ...     llm_instance, llm_config = get_llm_instance("completion")
        ...     llm_config.__class__.__name__
        'WatsonxConfig'
    """
    llm_provider = os.getenv("LLM_PROVIDER", "")
    llm_instance, llm_config = None, None
    logger.info("Configuring LLM instance for ToolOps , and LLM provider - " + llm_provider)
    try:
        provider_map = {
            "azure_openai": AzureOpenAIProvider,
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "aws_bedrock": AWSBedrockProvider,
            "ollama": OllamaProvider,
            "watsonx": WatsonxProvider,
        }
        provider_class = provider_map.get(llm_provider)

        # getting LLM configs from environment variables
        llm_config = None
        if llm_provider == "openai":
            oai_api_key = os.getenv("OPENAI_API_KEY", "")
            oai_base_url = os.getenv("OPENAI_BASE_URL", "")
            oai_model = os.getenv("OPENAI_MODEL", "")
            # oai_temperature= float(os.getenv("OPENAI_TEMPERATURE","0.7"))
            oai_temperature = TOOLOPS_TEMPERATURE
            oai_max_retries = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
            oai_max_tokens = int(os.getenv("OPENAI_MAX_TOEKNS", "600"))
            # adding default headers for RITS LLM platform as required
            if isinstance(oai_base_url, str) and "rits.fmaas.res.ibm.com" in oai_base_url:
                default_headers = {"RITS_API_KEY": oai_api_key}
            else:
                default_headers = None
            llm_config = OpenAIConfig(
                api_key=oai_api_key,
                base_url=oai_base_url,
                temperature=oai_temperature,
                model=oai_model,
                max_tokens=oai_max_tokens,
                max_retries=oai_max_retries,
                default_headers=default_headers,
                timeout=None,
            )
        elif llm_provider == "azure_openai":
            az_api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
            az_url = os.getenv("AZURE_OPENAI_ENDPOINT", "")
            az_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "")
            az_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
            az_model = os.getenv("AZURE_OPENAI_MODEL", "")
            # az_temperature= float(os.getenv("AZURE_OPENAI_TEMPERATURE",0.7))
            az_temperature = TOOLOPS_TEMPERATURE
            az_max_retries = int(os.getenv("AZURE_OPENAI_MAX_RETRIES", "2"))
            az_max_tokens = int(os.getenv("AZURE_OPENAI_MAX_TOEKNS", "600"))
            llm_config = AzureOpenAIConfig(
                api_key=az_api_key,
                azure_endpoint=az_url,
                api_version=az_api_version,
                azure_deployment=az_deployment,
                model=az_model,
                temperature=az_temperature,
                max_retries=az_max_retries,
                max_tokens=az_max_tokens,
                timeout=None,
            )
        elif llm_provider == "anthropic":
            ant_api_key = os.getenv("ANTHROPIC_API_KEY", "")
            ant_model = os.getenv("ANTHROPIC_MODEL", "")
            # ant_temperature= float(os.getenv("ANTHROPIC_TEMPERATURE",0.7))
            ant_temperature = TOOLOPS_TEMPERATURE
            ant_max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
            ant_max_retries = int(os.getenv("ANTHROPIC_MAX_RETRIES", "2"))
            llm_config = AnthropicConfig(api_key=ant_api_key, model=ant_model, temperature=ant_temperature, max_tokens=ant_max_tokens, max_retries=ant_max_retries, timeout=None)

        elif llm_provider == "aws_bedrock":
            aws_model = os.getenv("AWS_BEDROCK_MODEL_ID", "")
            aws_region = os.getenv("AWS_BEDROCK_REGION", "")
            # aws_temperatute=float(os.getenv("AWS_BEDROCK_TEMPERATURE",0.7))
            aws_temperatute = TOOLOPS_TEMPERATURE
            aws_max_tokens = int(os.getenv("AWS_BEDROCK_MAX_TOKENS", "4096"))
            aws_key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
            aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
            aws_session_token = os.getenv("AWS_SESSION_TOKEN", "")
            llm_config = AWSBedrockConfig(
                model_id=aws_model,
                region_name=aws_region,
                temperature=aws_temperatute,
                max_tokens=aws_max_tokens,
                aws_access_key_id=aws_key_id,
                aws_secret_access_key=aws_secret,
                aws_session_token=aws_session_token,
            )
        elif llm_provider == "ollama":
            ollama_model = os.getenv("OLLAMA_MODEL", "")
            ollama_url = os.getenv("OLLAMA_BASE_URL", "")
            # ollama_temeperature=float(os.getenv("OLLAMA_TEMPERATURE",0.7))
            ollama_temeperature = TOOLOPS_TEMPERATURE
            llm_config = OllamaConfig(base_url=ollama_url, model=ollama_model, temperature=ollama_temeperature, timeout=None, num_ctx=None)
        elif llm_provider == "watsonx":
            wx_api_key = os.getenv("WATSONX_APIKEY", "")
            wx_base_url = os.getenv("WATSONX_URL", "")
            wx_model = os.getenv("WATSONX_MODEL_ID", "")
            wx_project_id = os.getenv("WATSONX_PROJECT_ID", "")
            wx_temperature = TOOLOPS_TEMPERATURE
            wx_max_tokens = int(os.getenv("WATSONX_MAX_NEW_TOKENS", "1000"))
            wx_decoding_method = os.getenv("WATSONX_DECODING_METHOD", "greedy")
            llm_config = WatsonxConfig(
                api_key=wx_api_key,
                url=wx_base_url,
                project_id=wx_project_id,
                model_id=wx_model,
                temperature=wx_temperature,
                max_new_tokens=wx_max_tokens,
                decoding_method=wx_decoding_method,
            )
        else:
            return None, None

        llm_service = provider_class(llm_config)
        llm_instance = llm_service.get_llm(model_type=model_type)
        logger.info("Successfully configured LLM instance for ToolOps , and LLM provider - " + llm_provider)
    except Exception as e:
        logger.info("Error in configuring LLM instance for ToolOps -" + str(e))
    return llm_instance, llm_config


def execute_prompt(prompt):
    """
    Method for LLM inferencing using a prompt/user input

    Args:
        prompt: used specified prompt or inputs for LLM inferecning

    Returns:
        response: LLM output response for the given prompt
    """
    try:
        logger.info("Inferencing OpenAI provider LLM with the given prompt")

        completion_llm_instance, _ = get_llm_instance(model_type="completion")
        llm_response = completion_llm_instance.invoke(prompt, stop=["\n\n", "<|endoftext|>", "###STOP###"])
        response = llm_response.replace("<|eom_id|>", "").strip()
        # logger.info("Successful - Inferencing OpenAI provider LLM")
        return response
    except Exception as e:
        logger.error("Error in configuring LLM using OpenAI service provider - " + orjson.dumps({"Error": str(e)}).decode())
        return ""


# if __name__ == "__main__":
#     chat_llm_instance, _ = get_llm_instance(model_type="chat")
#     completion_llm_instance, _ = get_llm_instance(model_type="completion")
#     prompt = "what is India capital city?"
#     print("Prompt : ", prompt)
#     print("Text completion output : ")
#     print(execute_prompt(prompt))
#     response = chat_llm_instance.invoke(prompt)
#     print("Chat completion output : ")
#     print(response.content)
