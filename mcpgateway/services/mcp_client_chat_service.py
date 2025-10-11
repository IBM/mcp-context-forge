# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/mcp_client_chat_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

MCP Client Service Module.

This module provides a comprehensive client implementation for interacting with
MCP servers, managing LLM providers, and orchestrating conversational AI agents.
It supports multiple transport protocols and LLM providers

The module consists of several key components:
- Configuration classes for MCP servers and LLM providers
- LLM provider factory and implementations
- MCP client for tool management
- Chat service for conversational interactions

"""

# Standard
from datetime import datetime, timezone
import time
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional, Union
from uuid import uuid4

try:
    # Third-Party
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
    from langchain_core.tools import BaseTool
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_ollama import ChatOllama
    from langchain_openai import AzureChatOpenAI, ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    _LLMCHAT_AVAILABLE = True
except ImportError:
    # Optional dependencies for LLM chat feature not installed
    # These are only needed if LLMCHAT_ENABLED=true
    _LLMCHAT_AVAILABLE = False
    AIMessage = None  # type: ignore
    BaseMessage = None  # type: ignore
    HumanMessage = None  # type: ignore
    BaseTool = None  # type: ignore
    MultiServerMCPClient = None  # type: ignore
    ChatOllama = None  # type: ignore
    AzureChatOpenAI = None  # type: ignore
    ChatOpenAI = None  # type: ignore
    create_react_agent = None  # type: ignore

# Try to import Anthropic and Bedrock providers (they may not be installed)
try:
    # Third-Party
    from langchain_anthropic import ChatAnthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False
    ChatAnthropic = None  # type: ignore

try:
    # Third-Party
    from langchain_aws import ChatBedrock

    _BEDROCK_AVAILABLE = True
except ImportError:
    _BEDROCK_AVAILABLE = False
    ChatBedrock = None  # type: ignore

# Third-Party
from pydantic import BaseModel, Field, field_validator, model_validator

# First-Party
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class MCPServerConfig(BaseModel):
    """
    Configuration for MCP server connection.

    This class defines the configuration parameters required to connect to an
    MCP (Model Context Protocol) server using various transport mechanisms.

    Attributes:
        url: MCP server URL for streamable_http/sse transports.
        command: Command to run for stdio transport.
        args: Command-line arguments for stdio command.
        transport: Transport type (streamable_http, sse, or stdio).
        auth_token: Authentication token for HTTP-based transports.
        headers: Additional HTTP headers for request customization.

    Examples:
        >>> # HTTP-based transport
        >>> config = MCPServerConfig(
        ...     url="https://mcp-server.example.com/mcp",
        ...     transport="streamable_http",
        ...     auth_token="secret-token"
        ... )
        >>> config.transport
        'streamable_http'

        >>> # Stdio transport
        >>> config = MCPServerConfig(
        ...     command="python",
        ...     args=["server.py"],
        ...     transport="stdio"
        ... )
        >>> config.command
        'python'

    Note:
        The auth_token is automatically added to headers as a Bearer token
        for HTTP-based transports.
    """

    url: Optional[str] = Field(None, description="MCP server URL for streamable_http/sse transports")
    command: Optional[str] = Field(None, description="Command to run for stdio transport")
    args: Optional[list[str]] = Field(None, description="Arguments for stdio command")
    transport: Literal["streamable_http", "sse", "stdio"] = Field(default="streamable_http", description="Transport type for MCP connection")
    auth_token: Optional[str] = Field(None, description="Authentication token for the server")
    headers: Optional[Dict[str, str]] = Field(default=None, description="Additional headers for HTTP-based transports")

    @model_validator(mode="before")
    @classmethod
    def add_auth_to_headers(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically add authentication token to headers if provided.

        This validator ensures that if an auth_token is provided for HTTP-based
        transports, it's automatically added to the headers as a Bearer token.

        Args:
            values: Dictionary of field values before validation.

        Returns:
            Dict[str, Any]: Updated values with auth token in headers.

        Examples:
            >>> values = {
            ...     "url": "https://api.example.com",
            ...     "transport": "streamable_http",
            ...     "auth_token": "token123"
            ... }
            >>> result = MCPServerConfig.add_auth_to_headers(values)
            >>> result['headers']['Authorization']
            'Bearer token123'
        """
        auth_token = values.get("auth_token")
        transport = values.get("transport")
        headers = values.get("headers") or {}

        if auth_token and transport in ["streamable_http", "sse"]:
            if "Authorization" not in headers:
                headers["Authorization"] = f"Bearer {auth_token}"
            values["headers"] = headers

        return values

    @field_validator("url")
    @classmethod
    def validate_url_for_transport(cls, v: Optional[str], info) -> Optional[str]:
        """
        Validate that URL is provided for HTTP-based transports.

        Args:
            v: The URL value to validate.
            info: Validation context containing other field values.

        Returns:
            Optional[str]: The validated URL.

        Raises:
            ValueError: If URL is missing for streamable_http or sse transport.

        Examples:
            >>> from pydantic import ValidationInfo
            >>> # Valid case
            >>> MCPServerConfig(
            ...     url="https://example.com",
            ...     transport="streamable_http"
            ... ).url
            'https://example.com'
        """
        transport = info.data.get("transport")
        if transport in ["streamable_http", "sse"] and not v:
            raise ValueError(f"URL is required for {transport} transport")
        return v

    @field_validator("command")
    @classmethod
    def validate_command_for_stdio(cls, v: Optional[str], info) -> Optional[str]:
        """
        Validate that command is provided for stdio transport.

        Args:
            v: The command value to validate.
            info: Validation context containing other field values.

        Returns:
            Optional[str]: The validated command.

        Raises:
            ValueError: If command is missing for stdio transport.

        Examples:
            >>> config = MCPServerConfig(
            ...     command="python",
            ...     args=["server.py"],
            ...     transport="stdio"
            ... )
            >>> config.command
            'python'
        """
        transport = info.data.get("transport")
        if transport == "stdio" and not v:
            raise ValueError("Command is required for stdio transport")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"url": "https://mcp-server.example.com/mcp", "transport": "streamable_http", "auth_token": "your-token-here"},
                {"command": "python", "args": ["server.py"], "transport": "stdio"},
            ]
        }
    }


class AzureOpenAIConfig(BaseModel):
    """
    Configuration for Azure OpenAI provider.

    Defines all necessary parameters to connect to and use Azure OpenAI services,
    including API credentials, endpoints, model settings, and request parameters.

    Attributes:
        api_key: Azure OpenAI API authentication key.
        azure_endpoint: Azure OpenAI service endpoint URL.
        api_version: API version to use for requests.
        azure_deployment: Name of the deployed model.
        model: Model identifier for logging and tracing.
        temperature: Sampling temperature for response generation (0.0-2.0).
        max_tokens: Maximum number of tokens to generate.
        timeout: Request timeout duration in seconds.
        max_retries: Maximum number of retry attempts for failed requests.

    Examples:
        >>> config = AzureOpenAIConfig(
        ...     api_key="your-api-key",
        ...     azure_endpoint="https://your-resource.openai.azure.com/",
        ...     azure_deployment="gpt-4",
        ...     temperature=0.7
        ... )
        >>> config.model
        'gpt-4'
        >>> config.temperature
        0.7
    """

    api_key: str = Field(..., description="Azure OpenAI API key")
    azure_endpoint: str = Field(..., description="Azure OpenAI endpoint URL")
    api_version: str = Field(default="2024-05-01-preview", description="Azure OpenAI API version")
    azure_deployment: str = Field(..., description="Azure OpenAI deployment name")
    model: str = Field(default="gpt-4", description="Model name for tracing")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, gt=0, description="Maximum tokens to generate")
    timeout: Optional[float] = Field(None, gt=0, description="Request timeout in seconds")
    max_retries: int = Field(default=2, ge=0, description="Maximum number of retries")

    model_config = {
        "json_schema_extra": {
            "example": {
                "api_key": "your-api-key",
                "azure_endpoint": "https://your-resource.openai.azure.com/",
                "api_version": "2024-05-01-preview",
                "azure_deployment": "gpt-4",
                "model": "gpt-4",
                "temperature": 0.7,
            }
        }
    }


class OllamaConfig(BaseModel):
    """
    Configuration for Ollama provider.

    Defines parameters for connecting to a local or remote Ollama instance
    for running open-source language models.

    Attributes:
        base_url: Ollama server base URL.
        model: Name of the Ollama model to use.
        temperature: Sampling temperature for response generation (0.0-2.0).
        timeout: Request timeout duration in seconds.
        num_ctx: Context window size for the model.

    Examples:
        >>> config = OllamaConfig(
        ...     base_url="http://localhost:11434",
        ...     model="llama2",
        ...     temperature=0.5
        ... )
        >>> config.model
        'llama2'
        >>> config.base_url
        'http://localhost:11434'
    """

    base_url: str = Field(default="http://localhost:11434", description="Ollama base URL")
    model: str = Field(default="llama2", description="Model name to use")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    timeout: Optional[float] = Field(None, gt=0, description="Request timeout in seconds")
    num_ctx: Optional[int] = Field(None, gt=0, description="Context window size")

    model_config = {"json_schema_extra": {"example": {"base_url": "http://localhost:11434", "model": "llama2", "temperature": 0.7}}}


class OpenAIConfig(BaseModel):
    """
    Configuration for OpenAI provider (non-Azure).

    Defines parameters for connecting to OpenAI API (or OpenAI-compatible endpoints).

    Attributes:
        api_key: OpenAI API authentication key.
        base_url: Optional base URL for OpenAI-compatible endpoints.
        model: Model identifier (e.g., gpt-4, gpt-3.5-turbo).
        temperature: Sampling temperature for response generation (0.0-2.0).
        max_tokens: Maximum number of tokens to generate.
        timeout: Request timeout duration in seconds.
        max_retries: Maximum number of retry attempts for failed requests.

    Examples:
        >>> config = OpenAIConfig(
        ...     api_key="sk-...",
        ...     model="gpt-4",
        ...     temperature=0.7
        ... )
        >>> config.model
        'gpt-4'
    """

    api_key: str = Field(..., description="OpenAI API key")
    base_url: Optional[str] = Field(None, description="Base URL for OpenAI-compatible endpoints")
    model: str = Field(default="gpt-4o-mini", description="Model name (e.g., gpt-4, gpt-3.5-turbo)")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, gt=0, description="Maximum tokens to generate")
    timeout: Optional[float] = Field(None, gt=0, description="Request timeout in seconds")
    max_retries: int = Field(default=2, ge=0, description="Maximum number of retries")

    model_config = {
        "json_schema_extra": {
            "example": {
                "api_key": "sk-...",
                "model": "gpt-4o-mini",
                "temperature": 0.7,
            }
        }
    }


class AnthropicConfig(BaseModel):
    """
    Configuration for Anthropic Claude provider.

    Defines parameters for connecting to Anthropic's Claude API.

    Attributes:
        api_key: Anthropic API authentication key.
        model: Claude model identifier (e.g., claude-3-5-sonnet-20241022, claude-3-opus).
        temperature: Sampling temperature for response generation (0.0-1.0).
        max_tokens: Maximum number of tokens to generate.
        timeout: Request timeout duration in seconds.
        max_retries: Maximum number of retry attempts for failed requests.

    Examples:
        >>> config = AnthropicConfig(
        ...     api_key="sk-ant-...",
        ...     model="claude-3-5-sonnet-20241022",
        ...     temperature=0.7
        ... )
        >>> config.model
        'claude-3-5-sonnet-20241022'
    """

    api_key: str = Field(..., description="Anthropic API key")
    model: str = Field(default="claude-3-5-sonnet-20241022", description="Claude model name")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="Sampling temperature")
    max_tokens: int = Field(default=4096, gt=0, description="Maximum tokens to generate")
    timeout: Optional[float] = Field(None, gt=0, description="Request timeout in seconds")
    max_retries: int = Field(default=2, ge=0, description="Maximum number of retries")

    model_config = {
        "json_schema_extra": {
            "example": {
                "api_key": "sk-ant-...",
                "model": "claude-3-5-sonnet-20241022",
                "temperature": 0.7,
                "max_tokens": 4096,
            }
        }
    }


class AWSBedrockConfig(BaseModel):
    """
    Configuration for AWS Bedrock provider.

    Defines parameters for connecting to AWS Bedrock LLM services.

    Attributes:
        model_id: Bedrock model identifier (e.g., anthropic.claude-v2, amazon.titan-text-express-v1).
        region_name: AWS region name (e.g., us-east-1, us-west-2).
        aws_access_key_id: Optional AWS access key ID (uses default credential chain if not provided).
        aws_secret_access_key: Optional AWS secret access key.
        aws_session_token: Optional AWS session token for temporary credentials.
        temperature: Sampling temperature for response generation (0.0-1.0).
        max_tokens: Maximum number of tokens to generate.

    Examples:
        >>> config = AWSBedrockConfig(
        ...     model_id="anthropic.claude-v2",
        ...     region_name="us-east-1",
        ...     temperature=0.7
        ... )
        >>> config.model_id
        'anthropic.claude-v2'
    """

    model_id: str = Field(..., description="Bedrock model ID")
    region_name: str = Field(default="us-east-1", description="AWS region name")
    aws_access_key_id: Optional[str] = Field(None, description="AWS access key ID")
    aws_secret_access_key: Optional[str] = Field(None, description="AWS secret access key")
    aws_session_token: Optional[str] = Field(None, description="AWS session token")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="Sampling temperature")
    max_tokens: int = Field(default=4096, gt=0, description="Maximum tokens to generate")

    model_config = {
        "json_schema_extra": {
            "example": {
                "model_id": "anthropic.claude-v2",
                "region_name": "us-east-1",
                "temperature": 0.7,
                "max_tokens": 4096,
            }
        }
    }


class LLMConfig(BaseModel):
    """
    Configuration for LLM provider.

    Unified configuration class that supports multiple LLM providers through
    a discriminated union pattern.

    Attributes:
        provider: Type of LLM provider (azure_openai, openai, anthropic, aws_bedrock, or ollama).
        config: Provider-specific configuration object.

    Examples:
        >>> # Azure OpenAI configuration
        >>> config = LLMConfig(
        ...     provider="azure_openai",
        ...     config=AzureOpenAIConfig(
        ...         api_key="key",
        ...         azure_endpoint="https://example.com/",
        ...         azure_deployment="gpt-4"
        ...     )
        ... )
        >>> config.provider
        'azure_openai'

        >>> # OpenAI configuration
        >>> config = LLMConfig(
        ...     provider="openai",
        ...     config=OpenAIConfig(
        ...         api_key="sk-...",
        ...         model="gpt-4"
        ...     )
        ... )
        >>> config.provider
        'openai'

        >>> # Ollama configuration
        >>> config = LLMConfig(
        ...     provider="ollama",
        ...     config=OllamaConfig(model="llama2")
        ... )
        >>> config.provider
        'ollama'
    """

    provider: Literal["azure_openai", "openai", "anthropic", "aws_bedrock", "ollama"] = Field(..., description="LLM provider type")
    config: Union[AzureOpenAIConfig, OpenAIConfig, AnthropicConfig, AWSBedrockConfig, OllamaConfig] = Field(..., description="Provider-specific configuration")

    @field_validator("config", mode="before")
    @classmethod
    def validate_config_type(cls, v: Any, info) -> Union[AzureOpenAIConfig, OpenAIConfig, AnthropicConfig, AWSBedrockConfig, OllamaConfig]:
        """
        Validate and convert config dictionary to appropriate provider type.

        Args:
            v: Configuration value (dict or config object).
            info: Validation context containing provider information.

        Returns:
            Union[AzureOpenAIConfig, OpenAIConfig, AnthropicConfig, AWSBedrockConfig, OllamaConfig]: Validated configuration object.

        Examples:
            >>> # Automatically converts dict to appropriate config type
            >>> config_dict = {
            ...     "api_key": "key",
            ...     "azure_endpoint": "https://example.com/",
            ...     "azure_deployment": "gpt-4"
            ... }
            >>> # Used internally by Pydantic during validation
        """
        provider = info.data.get("provider")

        if isinstance(v, dict):
            if provider == "azure_openai":
                return AzureOpenAIConfig(**v)
            if provider == "openai":
                return OpenAIConfig(**v)
            if provider == "anthropic":
                return AnthropicConfig(**v)
            if provider == "aws_bedrock":
                return AWSBedrockConfig(**v)
            if provider == "ollama":
                return OllamaConfig(**v)

        return v


class MCPClientConfig(BaseModel):
    """
    Main configuration for MCP client service.

    Aggregates all configuration parameters required for the complete MCP client
    service, including server connection, LLM provider, and operational settings.

    Attributes:
        mcp_server: MCP server connection configuration.
        llm: LLM provider configuration.
        chat_history_max_messages: Maximum messages to retain in chat history.
        enable_streaming: Whether to enable streaming responses.

    Examples:
        >>> config = MCPClientConfig(
        ...     mcp_server=MCPServerConfig(
        ...         url="https://mcp-server.example.com/mcp",
        ...         transport="streamable_http"
        ...     ),
        ...     llm=LLMConfig(
        ...         provider="ollama",
        ...         config=OllamaConfig(model="llama2")
        ...     ),
        ...     chat_history_max_messages=100,
        ...     enable_streaming=True
        ... )
        >>> config.chat_history_max_messages
        100
        >>> config.enable_streaming
        True
    """

    mcp_server: MCPServerConfig = Field(..., description="MCP server configuration")
    llm: LLMConfig = Field(..., description="LLM provider configuration")
    chat_history_max_messages: int = Field(default=50, gt=0, description="Maximum messages to keep in chat history")
    enable_streaming: bool = Field(default=True, description="Enable streaming responses")

    model_config = {
        "json_schema_extra": {
            "example": {
                "mcp_server": {"url": "https://mcp-server.example.com/mcp", "transport": "streamable_http", "auth_token": "your-token"},
                "llm": {
                    "provider": "azure_openai",
                    "config": {"api_key": "your-key", "azure_endpoint": "https://your-resource.openai.azure.com/", "azure_deployment": "gpt-4", "api_version": "2024-05-01-preview"},
                },
            }
        }
    }


class AzureOpenAIProvider:
    """
    Azure OpenAI provider implementation.

    Manages connection and interaction with Azure OpenAI services.

    Attributes:
        config: Azure OpenAI configuration object.

    Examples:
        >>> config = AzureOpenAIConfig(
        ...     api_key="key",
        ...     azure_endpoint="https://example.openai.azure.com/",
        ...     azure_deployment="gpt-4"
        ... )
        >>> provider = AzureOpenAIProvider(config)
        >>> provider.get_model_name()
        'gpt-4'

    Note:
        The LLM instance is lazily initialized on first access for
        improved startup performance.
    """

    def __init__(self, config: AzureOpenAIConfig):
        """
        Initialize Azure OpenAI provider.

        Args:
            config: Azure OpenAI configuration with API credentials and settings.

        Examples:
            >>> config = AzureOpenAIConfig(
            ...     api_key="key",
            ...     azure_endpoint="https://example.openai.azure.com/",
            ...     azure_deployment="gpt-4"
            ... )
            >>> provider = AzureOpenAIProvider(config)
        """
        self.config = config
        self._llm = None
        logger.info(f"Initializing Azure OpenAI provider with deployment: {config.azure_deployment}")

    def get_llm(self) -> AzureChatOpenAI:
        """
        Get Azure OpenAI LLM instance with lazy initialization.

        Creates and caches the Azure OpenAI chat model instance on first call.
        Subsequent calls return the cached instance.

        Returns:
            AzureChatOpenAI: Configured Azure OpenAI chat model.

        Raises:
            Exception: If LLM initialization fails (e.g., invalid credentials).

        Examples:
            >>> config = AzureOpenAIConfig(
            ...     api_key="key",
            ...     azure_endpoint="https://example.openai.azure.com/",
            ...     azure_deployment="gpt-4"
            ... )
            >>> provider = AzureOpenAIProvider(config)
            >>> # llm = provider.get_llm()  # Returns AzureChatOpenAI instance
        """
        if self._llm is None:
            try:
                self._llm = AzureChatOpenAI(
                    api_key=self.config.api_key,
                    azure_endpoint=self.config.azure_endpoint,
                    api_version=self.config.api_version,
                    azure_deployment=self.config.azure_deployment,
                    model=self.config.model,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    timeout=self.config.timeout,
                    max_retries=self.config.max_retries,
                )
                logger.info("Azure OpenAI LLM instance created successfully")
            except Exception as e:
                logger.error(f"Failed to create Azure OpenAI LLM: {e}")
                raise

        return self._llm

    def get_model_name(self) -> str:
        """
        Get the Azure OpenAI model name.

        Returns:
            str: The model name configured for this provider.

        Examples:
            >>> config = AzureOpenAIConfig(
            ...     api_key="key",
            ...     azure_endpoint="https://example.openai.azure.com/",
            ...     azure_deployment="gpt-4",
            ...     model="gpt-4"
            ... )
            >>> provider = AzureOpenAIProvider(config)
            >>> provider.get_model_name()
            'gpt-4'
        """
        return self.config.model


class OllamaProvider:
    """
    Ollama provider implementation.

    Manages connection and interaction with Ollama instances for running
    open-source language models locally or remotely.

    Attributes:
        config: Ollama configuration object.

    Examples:
        >>> config = OllamaConfig(
        ...     base_url="http://localhost:11434",
        ...     model="llama2"
        ... )
        >>> provider = OllamaProvider(config)
        >>> provider.get_model_name()
        'llama2'

    Note:
        Requires Ollama to be running and accessible at the configured base_url.
    """

    def __init__(self, config: OllamaConfig):
        """
        Initialize Ollama provider.

        Args:
            config: Ollama configuration with server URL and model settings.

        Examples:
            >>> config = OllamaConfig(model="llama2")
            >>> provider = OllamaProvider(config)
        """
        self.config = config
        self._llm = None
        logger.info(f"Initializing Ollama provider with model: {config.model}")

    def get_llm(self) -> ChatOllama:
        """
        Get Ollama LLM instance with lazy initialization.

        Creates and caches the Ollama chat model instance on first call.
        Subsequent calls return the cached instance.

        Returns:
            ChatOllama: Configured Ollama chat model.

        Raises:
            Exception: If LLM initialization fails (e.g., Ollama not running).

        Examples:
            >>> config = OllamaConfig(model="llama2")
            >>> provider = OllamaProvider(config)
            >>> # llm = provider.get_llm()  # Returns ChatOllama instance
        """
        if self._llm is None:
            try:
                # Build model kwargs
                model_kwargs = {}
                if self.config.num_ctx is not None:
                    model_kwargs["num_ctx"] = self.config.num_ctx

                self._llm = ChatOllama(base_url=self.config.base_url, model=self.config.model, temperature=self.config.temperature, timeout=self.config.timeout, **model_kwargs)
                logger.info("Ollama LLM instance created successfully")
            except Exception as e:
                logger.error(f"Failed to create Ollama LLM: {e}")
                raise

        return self._llm

    def get_model_name(self) -> str:
        """Get the model name.

        Returns:
            str: The model name
        """
        return self.config.model


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
        logger.info(f"Initializing OpenAI provider with model: {config.model}")

    def get_llm(self) -> ChatOpenAI:
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
                kwargs = {
                    "api_key": self.config.api_key,
                    "model": self.config.model,
                    "temperature": self.config.temperature,
                    "max_tokens": self.config.max_tokens,
                    "timeout": self.config.timeout,
                    "max_retries": self.config.max_retries,
                }
                if self.config.base_url:
                    kwargs["base_url"] = self.config.base_url

                self._llm = ChatOpenAI(**kwargs)
                logger.info("OpenAI LLM instance created successfully")
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


class AnthropicProvider:
    """
    Anthropic Claude provider implementation.

    Manages connection and interaction with Anthropic's Claude API.

    Attributes:
        config: Anthropic configuration object.

    Examples:
        >>> config = AnthropicConfig(  # doctest: +SKIP
        ...     api_key="sk-ant-...",
        ...     model="claude-3-5-sonnet-20241022"
        ... )
        >>> provider = AnthropicProvider(config)  # doctest: +SKIP
        >>> provider.get_model_name()  # doctest: +SKIP
        'claude-3-5-sonnet-20241022'

    Note:
        Requires langchain-anthropic package to be installed.
    """

    def __init__(self, config: AnthropicConfig):
        """
        Initialize Anthropic provider.

        Args:
            config: Anthropic configuration with API key and settings.

        Raises:
            ImportError: If langchain-anthropic is not installed.

        Examples:
            >>> config = AnthropicConfig(  # doctest: +SKIP
            ...     api_key="sk-ant-...",
            ...     model="claude-3-5-sonnet-20241022"
            ... )
            >>> provider = AnthropicProvider(config)  # doctest: +SKIP
        """
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic provider requires langchain-anthropic package. Install it with: pip install langchain-anthropic")
        self.config = config
        self._llm = None
        logger.info(f"Initializing Anthropic provider with model: {config.model}")

    def get_llm(self) -> ChatAnthropic:
        """
        Get Anthropic LLM instance with lazy initialization.

        Creates and caches the Anthropic chat model instance on first call.
        Subsequent calls return the cached instance.

        Returns:
            ChatAnthropic: Configured Anthropic chat model.

        Raises:
            Exception: If LLM initialization fails (e.g., invalid credentials).

        Examples:
            >>> config = AnthropicConfig(  # doctest: +SKIP
            ...     api_key="sk-ant-...",
            ...     model="claude-3-5-sonnet-20241022"
            ... )
            >>> provider = AnthropicProvider(config)  # doctest: +SKIP
            >>> # llm = provider.get_llm()  # Returns ChatAnthropic instance
        """
        if self._llm is None:
            try:
                self._llm = ChatAnthropic(
                    api_key=self.config.api_key,
                    model=self.config.model,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    timeout=self.config.timeout,
                    max_retries=self.config.max_retries,
                )
                logger.info("Anthropic LLM instance created successfully")
            except Exception as e:
                logger.error(f"Failed to create Anthropic LLM: {e}")
                raise

        return self._llm

    def get_model_name(self) -> str:
        """
        Get the Anthropic model name.

        Returns:
            str: The model name configured for this provider.

        Examples:
            >>> config = AnthropicConfig(  # doctest: +SKIP
            ...     api_key="sk-ant-...",
            ...     model="claude-3-5-sonnet-20241022"
            ... )
            >>> provider = AnthropicProvider(config)  # doctest: +SKIP
            >>> provider.get_model_name()  # doctest: +SKIP
            'claude-3-5-sonnet-20241022'
        """
        return self.config.model


class AWSBedrockProvider:
    """
    AWS Bedrock provider implementation.

    Manages connection and interaction with AWS Bedrock LLM services.

    Attributes:
        config: AWS Bedrock configuration object.

    Examples:
        >>> config = AWSBedrockConfig(  # doctest: +SKIP
        ...     model_id="anthropic.claude-v2",
        ...     region_name="us-east-1"
        ... )
        >>> provider = AWSBedrockProvider(config)  # doctest: +SKIP
        >>> provider.get_model_name()  # doctest: +SKIP
        'anthropic.claude-v2'

    Note:
        Requires langchain-aws package and boto3 to be installed.
        Uses AWS default credential chain if credentials not explicitly provided.
    """

    def __init__(self, config: AWSBedrockConfig):
        """
        Initialize AWS Bedrock provider.

        Args:
            config: AWS Bedrock configuration with model ID and settings.

        Raises:
            ImportError: If langchain-aws is not installed.

        Examples:
            >>> config = AWSBedrockConfig(  # doctest: +SKIP
            ...     model_id="anthropic.claude-v2",
            ...     region_name="us-east-1"
            ... )
            >>> provider = AWSBedrockProvider(config)  # doctest: +SKIP
        """
        if not _BEDROCK_AVAILABLE:
            raise ImportError("AWS Bedrock provider requires langchain-aws package. Install it with: pip install langchain-aws boto3")
        self.config = config
        self._llm = None
        logger.info(f"Initializing AWS Bedrock provider with model: {config.model_id}")

    def get_llm(self) -> ChatBedrock:
        """
        Get AWS Bedrock LLM instance with lazy initialization.

        Creates and caches the Bedrock chat model instance on first call.
        Subsequent calls return the cached instance.

        Returns:
            ChatBedrock: Configured AWS Bedrock chat model.

        Raises:
            Exception: If LLM initialization fails (e.g., invalid credentials, permissions).

        Examples:
            >>> config = AWSBedrockConfig(  # doctest: +SKIP
            ...     model_id="anthropic.claude-v2",
            ...     region_name="us-east-1"
            ... )
            >>> provider = AWSBedrockProvider(config)  # doctest: +SKIP
            >>> # llm = provider.get_llm()  # Returns ChatBedrock instance
        """
        if self._llm is None:
            try:
                # Build credentials dict if provided
                credentials_kwargs = {}
                if self.config.aws_access_key_id:
                    credentials_kwargs["aws_access_key_id"] = self.config.aws_access_key_id
                if self.config.aws_secret_access_key:
                    credentials_kwargs["aws_secret_access_key"] = self.config.aws_secret_access_key
                if self.config.aws_session_token:
                    credentials_kwargs["aws_session_token"] = self.config.aws_session_token

                self._llm = ChatBedrock(
                    model_id=self.config.model_id,
                    region_name=self.config.region_name,
                    model_kwargs={
                        "temperature": self.config.temperature,
                        "max_tokens": self.config.max_tokens,
                    },
                    **credentials_kwargs,
                )
                logger.info("AWS Bedrock LLM instance created successfully")
            except Exception as e:
                logger.error(f"Failed to create AWS Bedrock LLM: {e}")
                raise

        return self._llm

    def get_model_name(self) -> str:
        """
        Get the AWS Bedrock model ID.

        Returns:
            str: The model ID configured for this provider.

        Examples:
            >>> config = AWSBedrockConfig(  # doctest: +SKIP
            ...     model_id="anthropic.claude-v2",
            ...     region_name="us-east-1"
            ... )
            >>> provider = AWSBedrockProvider(config)  # doctest: +SKIP
            >>> provider.get_model_name()  # doctest: +SKIP
            'anthropic.claude-v2'
        """
        return self.config.model_id


class LLMProviderFactory:
    """
    Factory for creating LLM providers.

    Implements the Factory pattern to instantiate the appropriate LLM provider
    based on configuration, abstracting away provider-specific initialization.

    Examples:
        >>> config = LLMConfig(
        ...     provider="ollama",
        ...     config=OllamaConfig(model="llama2")
        ... )
        >>> provider = LLMProviderFactory.create(config)
        >>> provider.get_model_name()
        'llama2'

    Note:
        This factory supports dynamic provider registration and ensures
        type safety through the LLMConfig discriminated union.
    """

    @staticmethod
    def create(llm_config: LLMConfig) -> Union[AzureOpenAIProvider, OpenAIProvider, AnthropicProvider, AWSBedrockProvider, OllamaProvider]:
        """
        Create an LLM provider based on configuration.

        Args:
            llm_config: LLM configuration specifying provider type and settings.

        Returns:
            Union[AzureOpenAIProvider, OpenAIProvider, AnthropicProvider, AWSBedrockProvider, OllamaProvider]: Instantiated provider.

        Raises:
            ValueError: If provider type is not supported.
            ImportError: If required provider package is not installed.

        Examples:
            >>> # Create Azure OpenAI provider
            >>> config = LLMConfig(
            ...     provider="azure_openai",
            ...     config=AzureOpenAIConfig(
            ...         api_key="key",
            ...         azure_endpoint="https://example.com/",
            ...         azure_deployment="gpt-4"
            ...     )
            ... )
            >>> provider = LLMProviderFactory.create(config)
            >>> isinstance(provider, AzureOpenAIProvider)
            True

            >>> # Create OpenAI provider
            >>> config = LLMConfig(
            ...     provider="openai",
            ...     config=OpenAIConfig(
            ...         api_key="sk-...",
            ...         model="gpt-4"
            ...     )
            ... )
            >>> provider = LLMProviderFactory.create(config)
            >>> isinstance(provider, OpenAIProvider)
            True

            >>> # Create Ollama provider
            >>> config = LLMConfig(
            ...     provider="ollama",
            ...     config=OllamaConfig(model="llama2")
            ... )
            >>> provider = LLMProviderFactory.create(config)
            >>> isinstance(provider, OllamaProvider)
            True
        """
        provider_map = {
            "azure_openai": AzureOpenAIProvider,
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "aws_bedrock": AWSBedrockProvider,
            "ollama": OllamaProvider,
        }

        provider_class = provider_map.get(llm_config.provider)
        if not provider_class:
            raise ValueError(f"Unsupported LLM provider: {llm_config.provider}. Supported providers: {list(provider_map.keys())}")

        logger.info(f"Creating LLM provider: {llm_config.provider}")
        return provider_class(llm_config.config)


class MCPClient:
    """
    Manages MCP server connections and tool loading.

    Provides a high-level interface for connecting to MCP servers, retrieving
    available tools, and managing connection health. Supports multiple transport
    protocols including HTTP, SSE, and stdio.

    Attributes:
        config: MCP server configuration.

    Examples:
        >>> import asyncio
        >>> config = MCPServerConfig(
        ...     url="https://mcp-server.example.com/mcp",
        ...     transport="streamable_http"
        ... )
        >>> client = MCPClient(config)
        >>> client.is_connected
        False
        >>> # asyncio.run(client.connect())
        >>> # tools = asyncio.run(client.get_tools())

    Note:
        All methods are async and should be called using asyncio or within
        an async context.
    """

    def __init__(self, config: MCPServerConfig):
        """
        Initialize MCP client.

        Args:
            config: MCP server configuration with connection parameters.

        Examples:
            >>> config = MCPServerConfig(
            ...     url="https://example.com/mcp",
            ...     transport="streamable_http"
            ... )
            >>> client = MCPClient(config)
            >>> client.config.transport
            'streamable_http'
        """
        self.config = config
        self._client: Optional[MultiServerMCPClient] = None
        self._tools: Optional[List[BaseTool]] = None
        self._connected = False
        logger.info(f"MCP client initialized with transport: {config.transport}")

    async def connect(self) -> None:
        """
        Connect to the MCP server.

        Establishes connection to the configured MCP server using the specified
        transport protocol. Subsequent calls are no-ops if already connected.

        Raises:
            ConnectionError: If connection to MCP server fails.

        Examples:
            >>> import asyncio
            >>> config = MCPServerConfig(
            ...     url="https://example.com/mcp",
            ...     transport="streamable_http"
            ... )
            >>> client = MCPClient(config)
            >>> # asyncio.run(client.connect())
            >>> # client.is_connected -> True

        Note:
            Connection is idempotent - calling multiple times is safe.
        """
        if self._connected:
            logger.warning("MCP client already connected")
            return

        try:
            logger.info(f"Connecting to MCP server via {self.config.transport}...")

            # Build server configuration for MultiServerMCPClient
            server_config = {
                "transport": self.config.transport,
            }

            if self.config.transport in ["streamable_http", "sse"]:
                server_config["url"] = self.config.url
                if self.config.headers:
                    server_config["headers"] = self.config.headers
            elif self.config.transport == "stdio":
                server_config["command"] = self.config.command
                if self.config.args:
                    server_config["args"] = self.config.args
            # Create MultiServerMCPClient with single server
            self._client = MultiServerMCPClient({"default": server_config})

            self._connected = True
            logger.info("Successfully connected to MCP server")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            self._connected = False
            raise ConnectionError(f"Failed to connect to MCP server: {e}") from e

    async def disconnect(self) -> None:
        """
        Disconnect from the MCP server.

        Cleanly closes the connection and releases resources. Safe to call
        even if not connected.

        Raises:
            Exception: If cleanup operations fail.

        Examples:
            >>> import asyncio
            >>> config = MCPServerConfig(
            ...     url="https://example.com/mcp",
            ...     transport="streamable_http"
            ... )
            >>> client = MCPClient(config)
            >>> # asyncio.run(client.connect())
            >>> # asyncio.run(client.disconnect())
            >>> # client.is_connected -> False

        Note:
            Clears cached tools upon disconnection.
        """
        if not self._connected:
            logger.warning("MCP client not connected")
            return

        try:
            if self._client:
                # MultiServerMCPClient manages connections internally
                self._client = None

            self._connected = False
            self._tools = None
            logger.info("Disconnected from MCP server")

        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
            raise

    async def get_tools(self, force_reload: bool = False) -> List[BaseTool]:
        """
        Get tools from the MCP server.

        Retrieves available tools from the connected MCP server. Results are
        cached unless force_reload is True.

        Args:
            force_reload: Force reload tools even if cached (default: False).

        Returns:
            List[BaseTool]: List of available tools from the server.

        Raises:
            ConnectionError: If not connected to MCP server.
            Exception: If tool loading fails.

        Examples:
            >>> import asyncio
            >>> config = MCPServerConfig(
            ...     url="https://example.com/mcp",
            ...     transport="streamable_http"
            ... )
            >>> client = MCPClient(config)
            >>> # asyncio.run(client.connect())
            >>> # tools = asyncio.run(client.get_tools())
            >>> # len(tools) >= 0 -> True

        Note:
            Tools are cached after first successful load for performance.
        """
        if not self._connected or not self._client:
            raise ConnectionError("Not connected to MCP server. Call connect() first.")

        if self._tools and not force_reload:
            logger.debug(f"Returning {len(self._tools)} cached tools")
            return self._tools

        try:
            logger.info("Loading tools from MCP server...")
            self._tools = await self._client.get_tools()
            logger.info(f"Successfully loaded {len(self._tools)} tools")

            # Log tool names for debugging
            if self._tools:
                tool_names = [tool.name for tool in self._tools]
                logger.debug(f"Available tools: {tool_names}")

            return self._tools

        except Exception as e:
            logger.error(f"Failed to load tools from MCP server: {e}")
            raise

    async def health_check(self) -> bool:
        """
        Check if the MCP server connection is healthy.

        Performs a lightweight health check by attempting to reload tools
        from the server.

        Returns:
            bool: True if connection is healthy, False otherwise.

        Examples:
            >>> import asyncio
            >>> config = MCPServerConfig(
            ...     url="https://example.com/mcp",
            ...     transport="streamable_http"
            ... )
            >>> client = MCPClient(config)
            >>> # asyncio.run(client.connect())
            >>> # is_healthy = asyncio.run(client.health_check())
            >>> # isinstance(is_healthy, bool) -> True

        Note:
            Returns False if not connected or if tool loading fails.
        """
        if not self._connected or not self._client:
            return False

        try:
            # Try to load tools as a health check
            await self.get_tools(force_reload=True)
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    @property
    def is_connected(self) -> bool:
        """
        Check if client is connected.

        Returns:
            bool: True if connected to MCP server, False otherwise.

        Examples:
            >>> config = MCPServerConfig(
            ...     url="https://example.com/mcp",
            ...     transport="streamable_http"
            ... )
            >>> client = MCPClient(config)
            >>> client.is_connected
            False
        """
        return self._connected


class MCPChatService:
    """
    Main chat service for MCP client backend.

    Orchestrates MCP client, LLM provider, and conversation management to provide
    a complete conversational AI service. Supports both streaming and non-streaming
    responses, maintains conversation history, and provides detailed event tracking.

    Attributes:
        config: Complete MCP client configuration.
        mcp_client: MCP server client instance.
        llm_provider: LLM provider instance.

    Examples:
        >>> import asyncio
        >>> config = MCPClientConfig(
        ...     mcp_server=MCPServerConfig(
        ...         url="https://example.com/mcp",
        ...         transport="streamable_http"
        ...     ),
        ...     llm=LLMConfig(
        ...         provider="ollama",
        ...         config=OllamaConfig(model="llama2")
        ...     )
        ... )
        >>> service = MCPChatService(config)
        >>> service.is_initialized
        False
        >>> # asyncio.run(service.initialize())
        >>> # response = asyncio.run(service.chat("Hello!"))

    Note:
        Must call initialize() before using chat functionality.
    """

    def __init__(self, config: MCPClientConfig):
        """
        Initialize chat service.

        Args:
            config: Complete MCP client configuration including server and LLM settings.

        Examples:
            >>> config = MCPClientConfig(
            ...     mcp_server=MCPServerConfig(
            ...         url="https://example.com/mcp",
            ...         transport="streamable_http"
            ...     ),
            ...     llm=LLMConfig(
            ...         provider="ollama",
            ...         config=OllamaConfig(model="llama2")
            ...     )
            ... )
            >>> service = MCPChatService(config)
            >>> service.config.enable_streaming
            True
        """
        self.config = config
        self.mcp_client = MCPClient(config.mcp_server)
        self.llm_provider = LLMProviderFactory.create(config.llm)
        self._agent = None
        self._conversation_history: List[BaseMessage] = []
        self._initialized = False
        self._tools: Optional[List[BaseTool]] = None

        logger.info("MCPChatService initialized")

    async def initialize(self) -> None:
        """
        Initialize the chat service.

        Connects to MCP server, loads tools, initializes LLM, and creates the
        conversational agent. Must be called before using chat functionality.

        Raises:
            ConnectionError: If MCP server connection fails.
            ValueError: If LLM initialization fails.
            RuntimeError: If agent creation or tool loading fails.

        Examples:
            >>> import asyncio
            >>> config = MCPClientConfig(
            ...     mcp_server=MCPServerConfig(
            ...         url="https://example.com/mcp",
            ...         transport="streamable_http"
            ...     ),
            ...     llm=LLMConfig(
            ...         provider="ollama",
            ...         config=OllamaConfig(model="llama2")
            ...     )
            ... )
            >>> service = MCPChatService(config)
            >>> # asyncio.run(service.initialize())
            >>> # service.is_initialized -> True

        Note:
            Subsequent calls to initialize() when already initialized will log
            a warning but won't re-initialize.
        """
        if self._initialized:
            logger.warning("Chat service already initialized")
            return

        try:
            # Connect to MCP server
            try:
                await self.mcp_client.connect()
            except ConnectionError as ce:
                logger.error(f"MCP server connection failed: {ce}")
                raise ConnectionError(f"Unable to connect to MCP server at {self.config.mcp_server.url}. Please verify the server is running and the URL is correct. Details: {ce}") from ce
            except Exception as conn_error:
                logger.error(f"Unexpected error connecting to MCP server: {conn_error}")
                raise ConnectionError(f"MCP server connection error: {conn_error}") from conn_error

            # Load tools from MCP server
            try:
                tools = await self.mcp_client.get_tools()
                self._tools = tools

                if not tools:
                    logger.warning("No tools loaded from MCP server - service will have limited functionality")
            except Exception as tool_error:
                logger.error(f"Failed to load tools from MCP server: {tool_error}")
                await self.shutdown()
                raise RuntimeError(f"Failed to load tools: {tool_error}") from tool_error

            # Get LLM instance
            try:
                llm = self.llm_provider.get_llm()
            except Exception as llm_error:
                logger.error(f"Failed to initialize LLM provider: {llm_error}")
                await self.shutdown()
                raise ValueError(f"LLM initialization failed. Please check your API credentials and configuration. Details: {llm_error}") from llm_error

            # Create ReAct agent
            try:
                logger.info("Creating ReAct agent...")
                self._agent = create_react_agent(llm, tools)
            except Exception as agent_error:
                logger.error(f"Failed to create ReAct agent: {agent_error}")
                await self.shutdown()
                raise RuntimeError(f"Agent creation failed: {agent_error}") from agent_error

            self._initialized = True
            logger.info(f"Chat service initialized successfully with {len(tools)} tools and {self.llm_provider.get_model_name()} model")

        except (ConnectionError, ValueError, RuntimeError):
            # Re-raise expected exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error during initialization: {e}", exc_info=True)
            await self.shutdown()
            raise RuntimeError(f"Service initialization failed: {e}") from e

    async def chat(self, message: str) -> str:
        """
        Send a message and get a response (non-streaming).

        Processes a user message through the agent and returns the complete
        response. Maintains conversation history automatically.

        Args:
            message: User's message text.

        Returns:
            str: AI assistant's complete response.

        Raises:
            RuntimeError: If service not initialized.
            Exception: If message processing fails.

        Examples:
            >>> import asyncio
            >>> # Assuming service is initialized
            >>> # response = asyncio.run(service.chat("What is 2+2?"))
            >>> # isinstance(response, str) -> True

        Note:
            For streaming responses, use chat_stream() instead.
        """
        if not self._initialized or not self._agent:
            raise RuntimeError("Chat service not initialized. Call initialize() first.")

        try:
            logger.debug("Processing chat message:...")

            # Add user message to history
            user_message = HumanMessage(content=message)
            self._conversation_history.append(user_message)

            # Invoke agent
            response = await self._agent.ainvoke({"messages": self._conversation_history})

            # Extract AI response
            ai_messages = response.get("messages", [])
            if ai_messages:
                last_message = ai_messages[-1]
                if isinstance(last_message, AIMessage):
                    ai_content = last_message.content

                    # Add AI response to history
                    self._conversation_history.append(last_message)

                    # Trim history if needed
                    self._trim_history()

                    logger.debug("Chat message processed successfully")
                    return ai_content

            logger.warning("No response from agent")
            return "I apologize, but I couldn't generate a response."

        except Exception as e:
            logger.error(f"Error processing chat message: {e}")
            raise

    async def chat_with_metadata(self, message: str) -> dict[str, Any]:
        """
        Send a message and get response with detailed metadata.

        Provides complete information about the chat interaction including
        full text, tool usage, and performance metrics.

        Args:
            message: User's message text.

        Returns:
            dict[str, Any]: Dictionary containing:
                - text (str): Complete response text
                - tool_used (bool): Whether any tools were invoked
                - tools (List[str]): Names of tools that were used
                - tool_invocations (List[dict]): Detailed tool invocation data
                - elapsed_ms (int): Processing time in milliseconds

        Raises:
            RuntimeError: If service not initialized.
            ValueError: If message is empty.

        Examples:
            >>> import asyncio
            >>> # Assuming service is initialized
            >>> # result = asyncio.run(service.chat_with_metadata("Hello"))
            >>> # 'text' in result -> True
            >>> # 'tool_used' in result -> True
            >>> # isinstance(result['elapsed_ms'], int) -> True

        Note:
            This method collects all events and returns them as a single response,
            making it suitable for batch processing or logging scenarios.
        """
        text = ""
        tool_invocations: list[dict[str, Any]] = []
        final: dict[str, Any] = {}
        async for ev in self.chat_events(message):
            t = ev.get("type")
            if t == "token":
                text += ev.get("content", "")
            elif t in ("tool_start", "tool_end", "tool_error"):
                tool_invocations.append(ev)
            elif t == "final":
                final = ev
        return {
            "text": text,
            "tool_used": final.get("tool_used", False),
            "tools": final.get("tools", []),
            "tool_invocations": tool_invocations,
            "elapsed_ms": final.get("elapsed_ms"),
        }

    async def chat_stream(self, message: str) -> AsyncGenerator[str, None]:
        """
        Send a message and stream the response.

        Yields response chunks as they're generated, enabling real-time display
        of the AI's response.

        Args:
            message: User's message text.

        Yields:
            str: Chunks of AI response text.

        Raises:
            RuntimeError: If service not initialized.
            Exception: If streaming fails.

        Examples:
            >>> import asyncio
            >>> async def stream_example():
            ...     # Assuming service is initialized
            ...     chunks = []
            ...     async for chunk in service.chat_stream("Hello"):
            ...         chunks.append(chunk)
            ...     return ''.join(chunks)
            >>> # full_response = asyncio.run(stream_example())

        Note:
            Falls back to non-streaming if enable_streaming is False in config.
        """
        if not self._initialized or not self._agent:
            raise RuntimeError("Chat service not initialized. Call initialize() first.")

        if not self.config.enable_streaming:
            # Fall back to non-streaming
            response = await self.chat(message)
            yield response
            return

        try:
            logger.debug("Processing streaming chat message...")

            # Add user message to history
            user_message = HumanMessage(content=message)
            self._conversation_history.append(user_message)

            # Stream agent response
            full_response = ""
            async for event in self._agent.astream_events({"messages": self._conversation_history}, version="v2"):
                kind = event["event"]

                # Stream LLM tokens
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content"):
                        content = chunk.content
                        if content:
                            full_response += content
                            yield content

            # Add complete response to history
            if full_response:
                ai_message = AIMessage(content=full_response)
                self._conversation_history.append(ai_message)
                self._trim_history()

            logger.debug("Streaming chat message processed successfully")

        except Exception as e:
            logger.error(f"Error processing streaming chat message: {e}")
            raise

    async def chat_events(self, message: str):
        """
        Stream structured events during chat processing.

        Provides granular visibility into the chat processing pipeline by yielding
        structured events for tokens, tool invocations, errors, and final results.

        Args:
            message: User's message text.

        Yields:
            dict: Event dictionaries with type-specific fields:
                - token: {"type": "token", "content": str}
                - tool_start: {"type": "tool_start", "id": str, "name": str,
                              "input": Any, "start": str}
                - tool_end: {"type": "tool_end", "id": str, "name": str,
                            "output": Any, "end": str}
                - tool_error: {"type": "tool_error", "id": str, "error": str,
                              "time": str}
                - final: {"type": "final", "content": str, "tool_used": bool,
                         "tools": List[str], "elapsed_ms": int}

        Raises:
            RuntimeError: If service not initialized.
            ValueError: If message is empty or whitespace only.
            ConnectionError: If connection to MCP server is lost.
            TimeoutError: If LLM request times out.

        Examples:
            >>> import asyncio
            >>> async def event_example():
            ...     # Assuming service is initialized
            ...     events = []
            ...     async for event in service.chat_events("Hello"):
            ...         events.append(event['type'])
            ...     return events
            >>> # event_types = asyncio.run(event_example())
            >>> # 'final' in event_types -> True

        Note:
            This is the most detailed chat method, suitable for building
            interactive UIs or detailed logging systems.
        """
        if not self._initialized or not self._agent:
            raise RuntimeError("Chat service not initialized. Call initialize() first.")

        # Validate message
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")

        # Append user message
        user_message = HumanMessage(content=message)
        self._conversation_history.append(user_message)

        full_response = ""
        start_ts = time.time()
        tool_runs: dict[str, dict[str, Any]] = {}

        try:
            async for event in self._agent.astream_events({"messages": self._conversation_history}, version="v2"):
                kind = event.get("event")
                now_iso = datetime.now(timezone.utc).isoformat()

                try:
                    if kind == "on_tool_start":
                        run_id = str(event.get("run_id") or uuid4())
                        name = event.get("name") or event.get("data", {}).get("name") or event.get("data", {}).get("tool")
                        input_data = event.get("data", {}).get("input")

                        # Serialize input safely
                        if hasattr(input_data, "dict"):
                            input_data = input_data.dict()
                        elif hasattr(input_data, "__dict__"):
                            input_data = str(input_data)

                        rec = {"id": run_id, "name": name, "input": input_data, "start": now_iso}
                        tool_runs[run_id] = rec
                        yield {"type": "tool_start", **rec}

                    elif kind == "on_tool_end":
                        run_id = str(event.get("run_id") or uuid4())
                        name = event.get("name") or event.get("data", {}).get("name") or event.get("data", {}).get("tool")
                        output = event.get("data", {}).get("output")

                        # Serialize output safely
                        if hasattr(output, "content"):
                            output = output.content
                        elif hasattr(output, "dict"):
                            output = output.dict()
                        elif not isinstance(output, (str, int, float, bool, list, dict, type(None))):
                            output = str(output)

                        rec = tool_runs.get(run_id, {"id": run_id, "name": name, "start": now_iso})
                        rec["end"] = now_iso
                        rec["output"] = output
                        tool_runs[run_id] = rec
                        yield {"type": "tool_end", **rec}

                    elif kind == "on_tool_error":
                        run_id = str(event.get("run_id") or uuid4())
                        err = event.get("data", {}).get("error")
                        yield {"type": "tool_error", "id": run_id, "error": str(err) if err else "Tool execution failed", "time": now_iso}

                    elif kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            content = chunk.content
                            full_response += content
                            yield {"type": "token", "content": content}

                except Exception as event_error:
                    logger.warning(f"Error processing event {kind}: {event_error}")
                    # Continue processing other events
                    continue

            # Append AI message and trim
            if full_response:
                ai_message = AIMessage(content=full_response)
                self._conversation_history.append(ai_message)
                self._trim_history()

            used_tools_list = list({rec.get("name") for rec in tool_runs.values() if rec.get("name")})
            yield {
                "type": "final",
                "content": full_response,
                "tool_used": len(used_tools_list) > 0,
                "tools": used_tools_list,
                "elapsed_ms": int((time.time() - start_ts) * 1000),
            }

        except ConnectionError as ce:
            logger.error(f"Connection error during chat: {ce}")
            raise ConnectionError(f"Lost connection to MCP server: {ce}") from ce
        except TimeoutError as te:
            logger.error(f"Timeout during chat: {te}")
            raise TimeoutError("LLM request timed out") from te
        except Exception as e:
            logger.error(f"Error in chat_events: {e}", exc_info=True)
            raise RuntimeError(f"Chat processing error: {e}") from e

    def _trim_history(self) -> None:
        """
        Trim conversation history to maximum configured messages.

        Maintains conversation history within the configured limit by keeping
        only the most recent messages. Called automatically after each chat interaction.

        Examples:
            >>> config = MCPClientConfig(
            ...     mcp_server=MCPServerConfig(
            ...         url="https://example.com/mcp",
            ...         transport="streamable_http"
            ...     ),
            ...     llm=LLMConfig(
            ...         provider="ollama",
            ...         config=OllamaConfig(model="llama2")
            ...     ),
            ...     chat_history_max_messages=3
            ... )
            >>> service = MCPChatService(config)
            >>> # After multiple chat interactions, history is automatically trimmed

        Note:
            This is an internal method called automatically; manual invocation
            is typically not necessary.
        """
        max_messages = self.config.chat_history_max_messages
        if len(self._conversation_history) > max_messages:
            # Keep the most recent messages
            self._conversation_history = self._conversation_history[-max_messages:]
            logger.debug(f"Trimmed conversation history to {max_messages} messages")

    async def get_conversation_history(self) -> List[Dict[str, str]]:
        """
        Get conversation history.

        Retrieves the current conversation history as a list of message dictionaries
        with role and content fields.

        Returns:
            List[Dict[str, str]]: Conversation messages with keys:
                - role (str): "user" or "assistant"
                - content (str): Message text

        Examples:
            >>> import asyncio
            >>> # Assuming service is initialized and has chat history
            >>> # history = asyncio.run(service.get_conversation_history())
            >>> # all('role' in msg and 'content' in msg for msg in history) -> True

        Note:
            Returns empty list if no conversation has occurred yet.
        """
        history = []
        for msg in self._conversation_history:
            if isinstance(msg, HumanMessage):
                history.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                history.append({"role": "assistant", "content": msg.content})

        return history

    async def clear_history(self) -> None:
        """
        Clear conversation history.

        Removes all messages from the conversation history. Useful for starting
        fresh conversations or managing memory usage.

        Examples:
            >>> import asyncio
            >>> # Assuming service is initialized
            >>> # asyncio.run(service.clear_history())
            >>> # history = asyncio.run(service.get_conversation_history())
            >>> # len(history) -> 0

        Note:
            This action cannot be undone. Consider saving history before clearing
            if needed for logging or analysis.
        """
        self._conversation_history.clear()
        logger.info("Conversation history cleared")

    async def shutdown(self) -> None:
        """
        Shutdown the chat service and cleanup resources.

        Performs graceful shutdown by disconnecting from MCP server, clearing
        agent and history, and resetting initialization state.

        Raises:
            Exception: If cleanup operations fail.

        Examples:
            >>> import asyncio
            >>> config = MCPClientConfig(
            ...     mcp_server=MCPServerConfig(
            ...         url="https://example.com/mcp",
            ...         transport="streamable_http"
            ...     ),
            ...     llm=LLMConfig(
            ...         provider="ollama",
            ...         config=OllamaConfig(model="llama2")
            ...     )
            ... )
            >>> service = MCPChatService(config)
            >>> # asyncio.run(service.initialize())
            >>> # asyncio.run(service.shutdown())
            >>> # service.is_initialized -> False

        Note:
            Should be called when service is no longer needed to properly
            release resources and connections.
        """
        logger.info("Shutting down chat service...")

        try:
            # Disconnect from MCP server
            if self.mcp_client.is_connected:
                await self.mcp_client.disconnect()

            # Clear state
            self._agent = None
            self._conversation_history.clear()
            self._initialized = False
            self._tools = []

            logger.info("Chat service shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            raise

    @property
    def is_initialized(self) -> bool:
        """
        Check if service is initialized.

        Returns:
            bool: True if service is initialized and ready, False otherwise.

        Examples:
            >>> config = MCPClientConfig(
            ...     mcp_server=MCPServerConfig(
            ...         url="https://example.com/mcp",
            ...         transport="streamable_http"
            ...     ),
            ...     llm=LLMConfig(
            ...         provider="ollama",
            ...         config=OllamaConfig(model="llama2")
            ...     )
            ... )
            >>> service = MCPChatService(config)
            >>> service.is_initialized
            False

        Note:
            Service must be initialized before calling chat methods.
        """
        return self._initialized

    async def reload_tools(self) -> int:
        """
        Reload tools from MCP server.

        Forces a reload of tools from the MCP server and recreates the agent
        with the updated tool set. Useful when MCP server tools have changed.

        Returns:
            int: Number of tools successfully loaded.

        Raises:
            RuntimeError: If service not initialized.
            Exception: If tool reloading or agent recreation fails.

        Examples:
            >>> import asyncio
            >>> # Assuming service is initialized
            >>> # tool_count = asyncio.run(service.reload_tools())
            >>> # tool_count >= 0 -> True

        Note:
            This operation recreates the agent, so it may briefly interrupt
            ongoing conversations. Conversation history is preserved.
        """
        if not self._initialized:
            raise RuntimeError("Chat service not initialized")

        try:
            logger.info("Reloading tools from MCP server...")
            tools = await self.mcp_client.get_tools(force_reload=True)

            # Recreate agent with new tools
            llm = self.llm_provider.get_llm()
            self._agent = create_react_agent(llm, tools)

            logger.info(f"Reloaded {len(tools)} tools successfully")
            return len(tools)

        except Exception as e:
            logger.error(f"Failed to reload tools: {e}")
            raise
