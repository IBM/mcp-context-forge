"""MCP client for managing connections to MCP servers."""

import asyncio
import logging
from typing import List, Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

"""Main chat service orchestrating MCP client and LLM."""

import asyncio
import logging
from typing import AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.prebuilt import create_react_agent


logger = logging.getLogger(__name__)

"""LLM provider abstraction for different LLM backends."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import AzureChatOpenAI
from langchain_ollama import ChatOllama

from typing import Any, Dict, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

class MCPServerConfig(BaseModel):
    """Configuration for MCP server connection."""
    
    url: Optional[str] = Field(
        None,
        description="MCP server URL for streamable_http/sse transports"
    )
    command: Optional[str] = Field(
        None,
        description="Command to run for stdio transport"
    )
    args: Optional[list[str]] = Field(
        None,
        description="Arguments for stdio command"
    )
    transport: Literal["streamable_http", "sse", "stdio"] = Field(
        default="streamable_http",
        description="Transport type for MCP connection"
    )
    auth_token: Optional[str] = Field(
        None,
        description="Authentication token for the server"
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional headers for HTTP-based transports"
    )
    
    @model_validator(mode="before")
    @classmethod
    def add_auth_to_headers(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Automatically add auth token to headers if provided."""
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
        """Validate URL is provided for HTTP-based transports."""
        transport = info.data.get("transport")
        if transport in ["streamable_http", "sse"] and not v:
            raise ValueError(f"URL is required for {transport} transport")
        return v
    
    @field_validator("command")
    @classmethod
    def validate_command_for_stdio(cls, v: Optional[str], info) -> Optional[str]:
        """Validate command is provided for stdio transport."""
        transport = info.data.get("transport")
        if transport == "stdio" and not v:
            raise ValueError("Command is required for stdio transport")
        return v
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "url": "https://mcp-server.example.com/mcp",
                    "transport": "streamable_http",
                    "auth_token": "your-token-here"
                },
                {
                    "command": "python",
                    "args": ["server.py"],
                    "transport": "stdio"
                }
            ]
        }
    }


class AzureOpenAIConfig(BaseModel):
    """Configuration for Azure OpenAI provider."""
    
    api_key: str = Field(
        ...,
        description="Azure OpenAI API key"
    )
    azure_endpoint: str = Field(
        ...,
        description="Azure OpenAI endpoint URL"
    )
    api_version: str = Field(
        default="2024-05-01-preview",
        description="Azure OpenAI API version"
    )
    azure_deployment: str = Field(
        ...,
        description="Azure OpenAI deployment name"
    )
    model: str = Field(
        default="gpt-4",
        description="Model name for tracing"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    max_tokens: Optional[int] = Field(
        None,
        gt=0,
        description="Maximum tokens to generate"
    )
    timeout: Optional[float] = Field(
        None,
        gt=0,
        description="Request timeout in seconds"
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        description="Maximum number of retries"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "api_key": "your-api-key",
                "azure_endpoint": "https://your-resource.openai.azure.com/",
                "api_version": "2024-05-01-preview",
                "azure_deployment": "gpt-4",
                "model": "gpt-4",
                "temperature": 0.7
            }
        }
    }


class OllamaConfig(BaseModel):
    """Configuration for Ollama provider."""
    
    base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama base URL"
    )
    model: str = Field(
        default="llama2",
        description="Model name to use"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    timeout: Optional[float] = Field(
        None,
        gt=0,
        description="Request timeout in seconds"
    )
    num_ctx: Optional[int] = Field(
        None,
        gt=0,
        description="Context window size"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "base_url": "http://localhost:11434",
                "model": "llama2",
                "temperature": 0.7
            }
        }
    }


class LLMConfig(BaseModel):
    """Configuration for LLM provider."""
    
    provider: Literal["azure_openai", "ollama"] = Field(
        ...,
        description="LLM provider type"
    )
    config: Union[AzureOpenAIConfig, OllamaConfig] = Field(
        ...,
        description="Provider-specific configuration"
    )
    
    @field_validator("config", mode="before")
    @classmethod
    def validate_config_type(cls, v: Any, info) -> Union[AzureOpenAIConfig, OllamaConfig]:
        """Validate config matches provider type."""
        provider = info.data.get("provider")
        
        if isinstance(v, dict):
            if provider == "azure_openai":
                return AzureOpenAIConfig(**v)
            elif provider == "ollama":
                return OllamaConfig(**v)
        
        return v


class MCPClientConfig(BaseModel):
    """Main configuration for MCP client."""
    
    mcp_server: MCPServerConfig = Field(
        ...,
        description="MCP server configuration"
    )
    llm: LLMConfig = Field(
        ...,
        description="LLM provider configuration"
    )
    chat_history_max_messages: int = Field(
        default=50,
        gt=0,
        description="Maximum messages to keep in chat history"
    )
    enable_streaming: bool = Field(
        default=True,
        description="Enable streaming responses"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "mcp_server": {
                    "url": "https://mcp-server.example.com/mcp",
                    "transport": "streamable_http",
                    "auth_token": "your-token"
                },
                "llm": {
                    "provider": "azure_openai",
                    "config": {
                        "api_key": "your-key",
                        "azure_endpoint": "https://your-resource.openai.azure.com/",
                        "azure_deployment": "gpt-4",
                        "api_version": "2024-05-01-preview"
                    }
                }
            }
        }
    }


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def get_llm(self) -> BaseChatModel:
        """Get the LLM instance.
        
        Returns:
            BaseChatModel: The LLM instance
        """
        pass
    
    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model name.
        
        Returns:
            str: The model name
        """
        pass


class AzureOpenAIProvider(BaseLLMProvider):
    """Azure OpenAI provider implementation."""
    
    def __init__(self, config: AzureOpenAIConfig):
        """Initialize Azure OpenAI provider.
        
        Args:
            config: Azure OpenAI configuration
        """
        self.config = config
        self._llm = None
        logger.info(
            f"Initializing Azure OpenAI provider with deployment: {config.azure_deployment}"
        )
    
    def get_llm(self) -> AzureChatOpenAI:
        """Get Azure OpenAI LLM instance.
        
        Returns:
            AzureChatOpenAI: The Azure OpenAI chat model
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
        """Get the model name.
        
        Returns:
            str: The model name
        """
        return self.config.model


class OllamaProvider(BaseLLMProvider):
    """Ollama provider implementation."""
    
    def __init__(self, config: OllamaConfig):
        """Initialize Ollama provider.
        
        Args:
            config: Ollama configuration
        """
        self.config = config
        self._llm = None
        logger.info(f"Initializing Ollama provider with model: {config.model}")
    
    def get_llm(self) -> ChatOllama:
        """Get Ollama LLM instance.
        
        Returns:
            ChatOllama: The Ollama chat model
        """
        if self._llm is None:
            try:
                # Build model kwargs
                model_kwargs = {}
                if self.config.num_ctx is not None:
                    model_kwargs["num_ctx"] = self.config.num_ctx
                
                self._llm = ChatOllama(
                    base_url=self.config.base_url,
                    model=self.config.model,
                    temperature=self.config.temperature,
                    timeout=self.config.timeout,
                    **model_kwargs
                )
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


class LLMProviderFactory:
    """Factory for creating LLM providers."""
    
    @staticmethod
    def create(llm_config: LLMConfig) -> BaseLLMProvider:
        """Create an LLM provider based on configuration.
        
        Args:
            llm_config: LLM configuration
        
        Returns:
            BaseLLMProvider: The LLM provider instance
        
        Raises:
            ValueError: If provider type is not supported
        """
        provider_map = {
            "azure_openai": AzureOpenAIProvider,
            "ollama": OllamaProvider,
        }
        
        provider_class = provider_map.get(llm_config.provider)
        if not provider_class:
            raise ValueError(
                f"Unsupported LLM provider: {llm_config.provider}. "
                f"Supported providers: {list(provider_map.keys())}"
            )
        
        logger.info(f"Creating LLM provider: {llm_config.provider}")
        return provider_class(llm_config.config)



class MCPClient:
    """Manages MCP server connections and tool loading."""
    
    def __init__(self, config: MCPServerConfig):
        """Initialize MCP client.
        
        Args:
            config: MCP server configuration
        """
        self.config = config
        self._client: Optional[MultiServerMCPClient] = None
        self._tools: Optional[List[BaseTool]] = None
        self._connected = False
        logger.info(f"MCP client initialized with transport: {config.transport}")
    
    async def connect(self) -> None:
        """Connect to the MCP server.
        
        Raises:
            ConnectionError: If connection fails
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
            self._client = MultiServerMCPClient(
                {"default": server_config}
            )
            
            self._connected = True
            logger.info("Successfully connected to MCP server")
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            self._connected = False
            raise ConnectionError(f"Failed to connect to MCP server: {e}") from e
    
    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
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
        """Get tools from the MCP server.
        
        Args:
            force_reload: Force reload tools even if cached
        
        Returns:
            List[BaseTool]: List of available tools
        
        Raises:
            ConnectionError: If not connected to server
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
        """Check if the MCP server connection is healthy.
        
        Returns:
            bool: True if connection is healthy, False otherwise
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
        """Check if client is connected.
        
        Returns:
            bool: True if connected, False otherwise
        """
        return self._connected


class MCPChatService:
    """Main chat service for MCP client backend.
    
    Orchestrates MCP client, LLM provider, and conversation management.
    """
    
    def __init__(self, config: MCPClientConfig):
        """Initialize chat service.
        
        Args:
            config: MCP client configuration
        """
        self.config = config
        self.mcp_client = MCPClient(config.mcp_server)
        self.llm_provider = LLMProviderFactory.create(config.llm)
        self._agent = None
        self._conversation_history: List[BaseMessage] = []
        self._initialized = False
        
        logger.info("MCPChatService initialized")
    
    async def initialize(self) -> None:
        """Initialize the chat service by connecting to MCP server and creating agent.
        
        Raises:
            ConnectionError: If MCP connection fails
            ValueError: If agent creation fails
        """
        if self._initialized:
            logger.warning("Chat service already initialized")
            return
        
        try:
            # Connect to MCP server
            await self.mcp_client.connect()
            
            # Load tools from MCP server
            tools = await self.mcp_client.get_tools()
            
            if not tools:
                logger.warning("No tools loaded from MCP server")
            
            # Get LLM instance
            llm = self.llm_provider.get_llm()
            
            # Create ReAct agent
            logger.info("Creating ReAct agent...")
            self._agent = create_react_agent(llm, tools)
            print("LLM DETAILS:",llm)
            
            self._initialized = True
            logger.info(
                f"Chat service initialized successfully with "
                f"{len(tools)} tools and {self.llm_provider.get_model_name()} model"
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize chat service: {e}")
            await self.shutdown()
            raise
    
    async def chat(self, message: str) -> str:
        """Send a message and get a response.
        
        Args:
            message: User message
        
        Returns:
            str: AI response
        
        Raises:
            RuntimeError: If service not initialized
        """
        if not self._initialized or not self._agent:
            raise RuntimeError("Chat service not initialized. Call initialize() first.")
        
        try:
            logger.info(f"Processing chat message: {message[:50]}...")
            
            # Add user message to history
            user_message = HumanMessage(content=message)
            self._conversation_history.append(user_message)
            
            # Invoke agent
            response = await self._agent.ainvoke(
                {"messages": self._conversation_history}
            )
            
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
                    
                    logger.info("Chat message processed successfully")
                    return ai_content
            
            logger.warning("No response from agent")
            return "I apologize, but I couldn't generate a response."
            
        except Exception as e:
            logger.error(f"Error processing chat message: {e}")
            raise
    
    async def chat_stream(self, message: str) -> AsyncGenerator[str, None]:
        """Send a message and stream the response.
        
        Args:
            message: User message
        
        Yields:
            str: Chunks of AI response
        
        Raises:
            RuntimeError: If service not initialized or streaming not enabled
        """
        if not self._initialized or not self._agent:
            raise RuntimeError("Chat service not initialized. Call initialize() first.")
        
        if not self.config.enable_streaming:
            # Fall back to non-streaming
            response = await self.chat(message)
            yield response
            return
        
        try:
            logger.info(f"Processing streaming chat message...")
            
            # Add user message to history
            user_message = HumanMessage(content=message)
            self._conversation_history.append(user_message)
            
            # Stream agent response
            full_response = ""
            async for event in self._agent.astream_events(
                {"messages": self._conversation_history},
                version="v2"
            ):
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
            
            logger.info("Streaming chat message processed successfully")
            
        except Exception as e:
            logger.error(f"Error processing streaming chat message: {e}")
            raise
    
    def _trim_history(self) -> None:
        """Trim conversation history to max messages."""
        max_messages = self.config.chat_history_max_messages
        if len(self._conversation_history) > max_messages:
            # Keep the most recent messages
            self._conversation_history = self._conversation_history[-max_messages:]
            logger.debug(f"Trimmed conversation history to {max_messages} messages")
    
    async def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get conversation history.
        
        Returns:
            List[Dict[str, str]]: Conversation history with role and content
        """
        history = []
        for msg in self._conversation_history:
            if isinstance(msg, HumanMessage):
                history.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                history.append({"role": "assistant", "content": msg.content})
        
        return history
    
    async def clear_history(self) -> None:
        """Clear conversation history."""
        self._conversation_history.clear()
        logger.info("Conversation history cleared")
    
    async def shutdown(self) -> None:
        """Shutdown the chat service and cleanup resources."""
        logger.info("Shutting down chat service...")
        
        try:
            # Disconnect from MCP server
            if self.mcp_client.is_connected:
                await self.mcp_client.disconnect()
            
            # Clear state
            self._agent = None
            self._conversation_history.clear()
            self._initialized = False
            
            logger.info("Chat service shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            raise
    
    @property
    def is_initialized(self) -> bool:
        """Check if service is initialized.
        
        Returns:
            bool: True if initialized, False otherwise
        """
        return self._initialized
    
    async def reload_tools(self) -> int:
        """Reload tools from MCP server.
        
        Returns:
            int: Number of tools loaded
        
        Raises:
            RuntimeError: If service not initialized
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
