import json
import re
import os
from typing import Any
import aiofiles as aiof
from dotenv import load_dotenv
from langchain_openai import OpenAI
from langchain_core.utils.json import parse_json_markdown
from mcpgateway.services.mcp_client_chat_service import OpenAIConfig
from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)



'''
Using OpenAIProvider for LLM inferencing
'''
class OpenAIProvider:
    """
    OpenAI provider implementation (non-Azure).

    Manages connection and interaction with OpenAI API or OpenAI-compatible endpoints.

    Attributes:
        config: OpenAI configuration object.

    Examples:
        >>> config = OpenAIConfig(
        ...     api_key="sk-...",
        ...     model="gpt-4"
        ... )
        >>> provider = OpenAIProvider(config)
        >>> provider.get_model_name()
        'gpt-4'

    Note:
        The LLM instance is lazily initialized on first access for
        improved startup performance.
    """

    def __init__(self, config: OpenAIConfig):
        """
        Initialize OpenAI provider.

        Args:
            config: OpenAI configuration with API key and settings.

        Examples:
            >>> config = OpenAIConfig(
            ...     api_key="sk-...",
            ...     model="gpt-4"
            ... )
            >>> provider = OpenAIProvider(config)
        """
        self.config = config
        self._llm = None
        #logger.info(f"Initializing OpenAI provider with model: {config.model}")

    def get_llm(self) -> OpenAI:
        """
        Get OpenAI LLM instance with lazy initialization.

        Creates and caches the OpenAI chat model instance on first call.
        Subsequent calls return the cached instance.

        Returns:
            ChatOpenAI: Configured OpenAI chat model.

        Raises:
            Exception: If LLM initialization fails (e.g., invalid credentials).

        Examples:
            >>> config = OpenAIConfig(
            ...     api_key="sk-...",
            ...     model="gpt-4"
            ... )
            >>> provider = OpenAIProvider(config)
            >>> # llm = provider.get_llm()  # Returns ChatOpenAI instance
        """
        if self._llm is None:
            try:
                kwargs: dict[str, Any] = {
                    "openai_api_key": self.config.api_key,
                    "model": self.config.model,
                    "temperature": self.config.temperature,
                    "max_tokens": self.config.max_tokens,
                    "timeout": self.config.timeout,
                    "max_retries": self.config.max_retries,                    
                }
                    
                if self.config.base_url:
                    kwargs["base_url"] = self.config.base_url
                # add RITS API KEY in default headers only if LLM inference url is from RITS
                if type(self.config.base_url) == str and 'rits.fmaas.res.ibm.com' in self.config.base_url:
                    kwargs["default_headers"] = {'RITS_API_KEY': self.config.api_key}
                self._llm = OpenAI(**kwargs)
                #logger.info("OpenAI LLM instance created successfully")
            except Exception as e:
                logger.error(f"Failed to create OpenAI LLM: {e}")
                raise

        return self._llm

    def get_model_name(self) -> str:
        """
        Get the OpenAI model name.

        Returns:
            str: The model name configured for this provider.

        Examples:
            >>> config = OpenAIConfig(
            ...     api_key="sk-...",
            ...     model="gpt-4"
            ... )
            >>> provider = OpenAIProvider(config)
            >>> provider.get_model_name()
            'gpt-4'
        """
        return self.config.model



        

def execute_prompt(prompt, model_id = None, parameters=None, max_new_tokens=600, stop_sequences=["\n\n", "<|endoftext|>","###STOP###"]):
    try:
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "")
        model = os.getenv("OPENAI_MODEL", "")
        temperature= float(os.getenv("OPENAI_TEMPERATURE","0.7"))
        max_retries = int(os.getenv("OPENAI_MAX_RETRIES","2"))
        openai_config = OpenAIConfig(api_key=api_key, base_url = base_url, temperature = temperature, 
                    model=model, max_tokens=max_new_tokens, max_retries = max_retries ,timeout=None)
        openai_provider = OpenAIProvider(openai_config)
        llm_instance = openai_provider.get_llm()
        logger.info("Inferencing OpenAI provider LLM with the given prompt")
        llm_response = llm_instance.invoke(prompt, stop=stop_sequences)
        response = llm_response.replace("<|eom_id|>", "").strip()
        #logger.info("Successful - Inferencing OpenAI provider LLM")
        return response
    except Exception as e:
        logger.error('Error in configuring LLM using OpenAI service provider - '+json.dumps({'Error': str(e)}))
        return ""



if __name__=='__main__':
    load_dotenv(".env.example")
    print(os.getenv("OPENAI_BASE_URL"))
    print(execute_prompt("what is India capital city"))
