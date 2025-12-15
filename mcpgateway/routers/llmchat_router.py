# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/llmchat_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

LLM Chat Router Module

This module provides FastAPI endpoints for managing LLM-based chat sessions
with MCP (Model Context Protocol) server integration. It supports multiple
LLM providers including Azure OpenAI, OpenAI, Anthropic, AWS Bedrock, and Ollama.

The module handles user session management, configuration, and real-time
streaming responses for conversational AI applications with unified chat
history management via ChatHistoryManager from mcp_client_chat_service.

"""

# Standard
import asyncio
import json
import os
from typing import Any, Dict, Optional

# Third-Party
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    # Third-Party
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.mcp_client_chat_service import (
    AnthropicConfig,
    AWSBedrockConfig,
    AzureOpenAIConfig,
    GatewayConfig,
    LLMConfig,
    MCPChatService,
    MCPClientConfig,
    MCPServerConfig,
    OllamaConfig,
    OpenAIConfig,
    WatsonxConfig,
)

# Load environment variables
load_dotenv()

# Initialize router
llmchat_router = APIRouter(prefix="/llmchat", tags=["llmchat"])

# Redis client initialization
redis_client = None
if getattr(settings, "cache_type", None) == "redis" and getattr(settings, "redis_url", None):
    if aioredis is None:
        raise RuntimeError("Redis support requires 'redis' package. Install with: pip install redis[async]")
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

# Fallback in-memory stores (used when Redis unavailable)
# Store active chat sessions per user
active_sessions: Dict[str, MCPChatService] = {}

# Store configuration per user
user_configs: Dict[str, MCPClientConfig] = {}

# Logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# ---------- Utility ----------


def fallback(value, env_var_name: str, default: Optional[Any] = None):
    """Return the provided value or fall back to environment variable or default.

    This utility function implements a cascading fallback mechanism for configuration
    values, checking the provided value first, then environment variables, and finally
    a default value.

    Args:
        value: The primary value to use if not None.
        env_var_name: Name of the environment variable to check as fallback.
        default: Default value to return if both value and env var are None/empty.

    Returns:
        The first non-None value from: value, environment variable, or default.

    Examples:
        >>> import os
        >>> os.environ['TEST_VAR'] = 'env_value'
        >>> fallback('direct_value', 'TEST_VAR', 'default')
        'direct_value'

        >>> fallback(None, 'TEST_VAR', 'default')
        'env_value'

        >>> fallback(None, 'NONEXISTENT_VAR', 'default')
        'default'

        >>> fallback(None, 'NONEXISTENT_VAR')

    Note:
        Environment variables are retrieved using os.getenv(), which returns
        None if the variable doesn't exist.
    """
    return value if value is not None else os.getenv(env_var_name, default)


# ---------- MODELS ----------


class LLMInput(BaseModel):
    """Input configuration for Language Learning Model providers.

    This model encapsulates the provider type and associated configuration
    parameters for initializing LLM connections.

    Attributes:
        provider: LLM provider identifier (e.g., 'azure_openai', 'openai', 'ollama').
        config: Dictionary containing provider-specific configuration parameters
                such as API keys, endpoints, models, and temperature settings.

    Examples:
        >>> llm_input = LLMInput(provider='azure_openai', config={'api_key': 'test_key'})
        >>> llm_input.provider
        'azure_openai'

        >>> llm_input = LLMInput(provider='ollama')
        >>> llm_input.config
        {}
    """

    provider: str
    config: Dict[str, Any] = {}


class ServerInput(BaseModel):
    """Input configuration for MCP server connection.

    Defines the connection parameters required to establish communication
    with an MCP (Model Context Protocol) server.

    Attributes:
        url: Optional MCP server URL endpoint. Defaults to environment variable
             or 'http://localhost:8000/mcp'.
        transport: Communication transport protocol. Defaults to 'streamable_http'.
        auth_token: Optional authentication token for secure server access.

    Examples:
        >>> server = ServerInput(url='http://example.com/mcp')
        >>> server.transport
        'streamable_http'

        >>> server = ServerInput()
        >>> server.url is None
        True
    """

    url: Optional[str] = None
    transport: Optional[str] = "streamable_http"
    auth_token: Optional[str] = None


class ConnectInput(BaseModel):
    """Request model for establishing a new chat session.

    Contains all necessary parameters to initialize a user's chat session
    including server connection details, LLM configuration, and streaming preferences.

    Attributes:
        user_id: Unique identifier for the user session. Required for session management.
        server: Optional MCP server configuration. Uses defaults if not provided.
        llm: Optional LLM provider configuration. Uses environment defaults if not provided.
        streaming: Whether to enable streaming responses. Defaults to False.

    Examples:
        >>> connect = ConnectInput(user_id='user123')
        >>> connect.streaming
        False

        >>> connect = ConnectInput(user_id='user456', streaming=True)
        >>> connect.user_id
        'user456'
    """

    user_id: str
    server: Optional[ServerInput] = None
    llm: Optional[LLMInput] = None
    streaming: bool = False


class ChatInput(BaseModel):
    """Request model for sending chat messages.

    Encapsulates user message data for processing by the chat service.

    Attributes:
        user_id: Unique identifier for the active user session.
        message: The chat message content to be processed.
        streaming: Whether to stream the response. Defaults to False.

    Examples:
        >>> chat = ChatInput(user_id='user123', message='Hello, AI!')
        >>> len(chat.message) > 0
        True

        >>> chat = ChatInput(user_id='user456', message='Tell me a story', streaming=True)
        >>> chat.streaming
        True
    """

    user_id: str
    message: str
    streaming: bool = False


class DisconnectInput(BaseModel):
    """Request model for terminating a chat session.

    Simple model containing only the user identifier for session cleanup.

    Attributes:
        user_id: Unique identifier of the session to disconnect.

    Examples:
        >>> disconnect = DisconnectInput(user_id='user123')
        >>> disconnect.user_id
        'user123'
    """

    user_id: str


# ---------- HELPERS ----------


def build_llm_config(llm: Optional[LLMInput]) -> LLMConfig:
    """Construct an LLMConfig object from input parameters and environment variables.

    This function builds a complete LLM configuration by combining explicit input
    parameters with environment variable fallbacks. It validates required fields
    and constructs provider-specific configuration objects.

    Args:
        llm: Optional LLMInput containing provider type and configuration parameters.
             If None, defaults are retrieved from environment variables.

    Returns:
        LLMConfig: Fully configured LLM configuration object with provider-specific settings.

    Raises:
        ValueError: If the provider is unsupported, or if required credentials
                   (API keys, endpoints) are missing for the specified provider.

    Supported Providers:
        - azure_openai: Requires api_key and azure_endpoint
        - openai: Requires api_key
        - anthropic: Requires api_key
        - aws_bedrock: Requires model_id
        - ollama: Requires model name

    Examples:
        >>> import os
        >>> os.environ['LLM_PROVIDER'] = 'ollama'
        >>> os.environ['OLLAMA_MODEL'] = 'llama3'
        >>> config = build_llm_config(None)
        >>> config.provider
        'ollama'

        >>> llm_input = LLMInput(provider='invalid_provider')
        >>> build_llm_config(llm_input)
        Traceback (most recent call last):
        ...
        ValueError: Unsupported LLM provider: invalid_provider...

    Note:
        API keys and sensitive credentials are retrieved from environment variables
        for security. Never hardcode credentials in the configuration dict.
    """
    provider = fallback(llm.provider if llm else None, "LLM_PROVIDER", "azure_openai")
    cfg = llm.config if llm else {}

    # Validate provider
    valid_providers = ["azure_openai", "openai", "anthropic", "aws_bedrock", "ollama", "watsonx", "gateway"]
    if provider not in valid_providers:
        raise ValueError(f"Unsupported LLM provider: {provider}. Supported providers: {', '.join(valid_providers)}")

    if provider == "azure_openai":
        # Validate required fields
        api_key = fallback(cfg.get("api_key"), "AZURE_OPENAI_API_KEY")
        azure_endpoint = fallback(cfg.get("azure_endpoint"), "AZURE_OPENAI_ENDPOINT")

        if not api_key:
            raise ValueError("Azure OpenAI API key is required but not provided")
        if not azure_endpoint:
            raise ValueError("Azure OpenAI endpoint is required but not provided")

        return LLMConfig(
            provider="azure_openai",
            config=AzureOpenAIConfig(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=fallback(cfg.get("api_version"), "AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
                azure_deployment=fallback(cfg.get("azure_deployment"), "AZURE_OPENAI_DEPLOYMENT", "gpt-4"),
                model=fallback(cfg.get("model"), "AZURE_OPENAI_MODEL", "gpt-4"),
                temperature=fallback(cfg.get("temperature"), "AZURE_OPENAI_TEMPERATURE", 0.7),
            ),
        )

    elif provider == "openai":
        api_key = fallback(cfg.get("api_key"), "OPENAI_API_KEY")

        if not api_key:
            raise ValueError("OpenAI API key is required but not provided")

        return LLMConfig(
            provider="openai",
            config=OpenAIConfig(
                api_key=api_key,
                model=fallback(cfg.get("model"), "OPENAI_MODEL", "gpt-4o-mini"),
                temperature=fallback(cfg.get("temperature"), "OPENAI_TEMPERATURE", 0.7),
                base_url=fallback(cfg.get("base_url"), "OPENAI_BASE_URL"),
                max_tokens=cfg.get("max_tokens"),
                timeout=cfg.get("timeout"),
                max_retries=fallback(cfg.get("max_retries"), "OPENAI_MAX_RETRIES", 2),
            ),
        )

    elif provider == "anthropic":
        api_key = fallback(cfg.get("api_key"), "ANTHROPIC_API_KEY")

        if not api_key:
            raise ValueError("Anthropic API key is required but not provided")

        return LLMConfig(
            provider="anthropic",
            config=AnthropicConfig(
                api_key=api_key,
                model=fallback(cfg.get("model"), "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
                temperature=fallback(cfg.get("temperature"), "ANTHROPIC_TEMPERATURE", 0.7),
                max_tokens=fallback(cfg.get("max_tokens"), "ANTHROPIC_MAX_TOKENS", 4096),
                timeout=cfg.get("timeout"),
                max_retries=fallback(cfg.get("max_retries"), "ANTHROPIC_MAX_RETRIES", 2),
            ),
        )

    elif provider == "aws_bedrock":
        model_id = fallback(cfg.get("model_id"), "AWS_BEDROCK_MODEL_ID")

        if not model_id:
            raise ValueError("AWS Bedrock model_id is required but not provided")

        return LLMConfig(
            provider="aws_bedrock",
            config=AWSBedrockConfig(
                model_id=model_id,
                region_name=fallback(cfg.get("region_name"), "AWS_BEDROCK_REGION", "us-east-1"),
                aws_access_key_id=fallback(cfg.get("aws_access_key_id"), "AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=fallback(cfg.get("aws_secret_access_key"), "AWS_SECRET_ACCESS_KEY"),
                aws_session_token=fallback(cfg.get("aws_session_token"), "AWS_SESSION_TOKEN"),
                temperature=fallback(cfg.get("temperature"), "AWS_BEDROCK_TEMPERATURE", 0.7),
                max_tokens=fallback(cfg.get("max_tokens"), "AWS_BEDROCK_MAX_TOKENS", 4096),
            ),
        )

    elif provider == "ollama":
        model = fallback(cfg.get("model"), "OLLAMA_MODEL", "llama3")

        if not model:
            raise ValueError("Ollama model name is required but not provided")

        return LLMConfig(
            provider="ollama",
            config=OllamaConfig(
                model=model,
                temperature=fallback(cfg.get("temperature"), "OLLAMA_TEMPERATURE", 0.7),
                base_url=fallback(cfg.get("base_url"), "OLLAMA_BASE_URL", "http://localhost:11434"),
                timeout=cfg.get("timeout"),
                num_ctx=cfg.get("num_ctx"),
            ),
        )

    elif provider == "watsonx":
        apikey = fallback(cfg.get("apikey"), "WATSONX_APIKEY")
        project_id = fallback(cfg.get("projectid"), "WATSONX_PROJECT_ID")

        if not apikey:
            raise ValueError("IBM watsonx.ai API key is required but not provided")
        if not project_id:
            raise ValueError("IBM watsonx.ai project ID is required but not provided")

        return LLMConfig(
            provider="watsonx",
            config=WatsonxConfig(
                apikey=apikey,
                url=fallback(cfg.get("url"), "WATSONX_URL", "https://us-south.ml.cloud.ibm.com"),
                project_id=project_id,
                model_id=fallback(cfg.get("model_id"), "WATSONX_MODEL_ID", "ibm/granite-13b-chat-v2"),
                temperature=fallback(cfg.get("temperature"), "WATSONX_TEMPERATURE", 0.7),
                max_new_tokens=cfg.get("max_tokens", 1024),
                min_new_tokens=cfg.get("min_tokens", 1),
                decoding_method=fallback(cfg.get("decoding_method"), "WATSONX_DECODING_METHOD", "sample"),
                top_k=cfg.get("top_k", 50),
                top_p=cfg.get("top_p", 1.0),
                timeout=cfg.get("timeout"),
            ),
        )

    elif provider == "gateway":
        model = fallback(cfg.get("model"), "GATEWAY_MODEL")

        if not model:
            raise ValueError("Gateway model ID is required but not provided")

        return LLMConfig(
            provider="gateway",
            config=GatewayConfig(
                model=model,
                base_url=fallback(cfg.get("base_url"), "GATEWAY_BASE_URL"),
                temperature=fallback(cfg.get("temperature"), "GATEWAY_TEMPERATURE", 0.7),
                max_tokens=cfg.get("max_tokens"),
                timeout=cfg.get("timeout"),
            ),
        )


def build_config(input_data: ConnectInput) -> MCPClientConfig:
    """Build complete MCP client configuration from connection input.

    Constructs a comprehensive configuration object combining MCP server settings
    and LLM configuration, with environment variable fallbacks for missing values.

    Args:
        input_data: ConnectInput object containing server, LLM, and streaming settings.

    Returns:
        MCPClientConfig: Complete client configuration ready for service initialization.

    Raises:
        ValueError: If LLM configuration validation fails (propagated from build_llm_config).

    Examples:
        >>> import os
        >>> os.environ['MCP_SERVER_URL'] = 'http://test.com/mcp'
        >>> os.environ['LLM_PROVIDER'] = 'ollama'
        >>> os.environ['OLLAMA_MODEL'] = 'llama3'
        >>> connect = ConnectInput(user_id='user123')
        >>> config = build_config(connect)
        >>> config.mcp_server.transport
        'streamable_http'

    Note:
        This function orchestrates the creation of nested configuration objects
        for both server and LLM components.
    """
    server = input_data.server
    llm = input_data.llm

    return MCPClientConfig(
        mcp_server=MCPServerConfig(
            url=fallback(server.url if server else None, "MCP_SERVER_URL", "http://localhost:8000/mcp"),
            transport=fallback(server.transport if server else None, "MCP_SERVER_TRANSPORT", "streamable_http"),
            auth_token=fallback(server.auth_token if server else None, "MCP_SERVER_AUTH_TOKEN"),
        ),
        llm=build_llm_config(llm),
        enable_streaming=input_data.streaming,
    )


# ---------- SESSION STORAGE HELPERS ----------

# Identify this worker uniquely (used for sticky session ownership)
WORKER_ID = str(os.getpid())

# Tunables (can set via environment)
SESSION_TTL = settings.llmchat_session_ttl  # seconds for active_session key TTL
LOCK_TTL = settings.llmchat_session_lock_ttl  # seconds for lock expiry
LOCK_RETRIES = settings.llmchat_session_lock_retries  # how many times to poll while waiting
LOCK_WAIT = settings.llmchat_session_lock_wait  # seconds between polls


# Redis key helpers
def _cfg_key(user_id: str) -> str:
    """Generate Redis key for user configuration storage.

    Args:
        user_id: User identifier.

    Returns:
        str: Redis key for storing user configuration.
    """
    return f"user_config:{user_id}"


def _active_key(user_id: str) -> str:
    """Generate Redis key for active session tracking.

    Args:
        user_id: User identifier.

    Returns:
        str: Redis key for tracking active sessions.
    """
    return f"active_session:{user_id}"


def _lock_key(user_id: str) -> str:
    """Generate Redis key for session initialization lock.

    Args:
        user_id: User identifier.

    Returns:
        str: Redis key for session locks.
    """
    return f"session_lock:{user_id}"


# ---------- CONFIG HELPERS ----------


async def set_user_config(user_id: str, config: MCPClientConfig):
    """Store user configuration in Redis or memory.

    Args:
        user_id: User identifier.
        config: Complete MCP client configuration.
    """
    if redis_client:
        await redis_client.set(_cfg_key(user_id), json.dumps(config.model_dump()))
    else:
        user_configs[user_id] = config


async def get_user_config(user_id: str) -> Optional[MCPClientConfig]:
    """Retrieve user configuration from Redis or memory.

    Args:
        user_id: User identifier.

    Returns:
        Optional[MCPClientConfig]: User configuration if found, None otherwise.
    """
    if redis_client:
        data = await redis_client.get(_cfg_key(user_id))
        if not data:
            return None
        return MCPClientConfig(**json.loads(data))
    return user_configs.get(user_id)


async def delete_user_config(user_id: str):
    """Delete user configuration from Redis or memory.

    Args:
        user_id: User identifier.
    """
    if redis_client:
        await redis_client.delete(_cfg_key(user_id))
    else:
        user_configs.pop(user_id, None)


# ---------- SESSION (active) HELPERS with locking & recreate ----------


async def set_active_session(user_id: str, session: MCPChatService):
    """Register an active session locally and mark ownership in Redis with TTL.

    Args:
        user_id: User identifier.
        session: Initialized MCPChatService instance.
    """
    active_sessions[user_id] = session
    if redis_client:
        # set owner with TTL so dead workers eventually lose ownership
        await redis_client.set(_active_key(user_id), WORKER_ID, ex=SESSION_TTL)


async def delete_active_session(user_id: str):
    """Remove active session locally and from Redis.

    Args:
        user_id: User identifier.
    """
    active_sessions.pop(user_id, None)
    if redis_client:
        await redis_client.delete(_active_key(user_id))


async def _try_acquire_lock(user_id: str) -> bool:
    """Attempt to acquire the initialization lock for a user session.

    Args:
        user_id: User identifier.

    Returns:
        bool: True if lock acquired, False otherwise.
    """
    if not redis_client:
        return True  # no redis -> local only, no lock required
    return await redis_client.set(_lock_key(user_id), WORKER_ID, nx=True, ex=LOCK_TTL)


async def _release_lock_safe(user_id: str):
    """Release the lock only if we own it (best-effort).

    Args:
        user_id: User identifier.
    """
    if not redis_client:
        return
    val = await redis_client.get(_lock_key(user_id))
    if val == WORKER_ID:
        await redis_client.delete(_lock_key(user_id))


async def _create_local_session_from_config(user_id: str) -> Optional[MCPChatService]:
    """Create MCPChatService locally from stored config.

    Args:
        user_id: User identifier.

    Returns:
        Optional[MCPChatService]: Initialized service or None if creation fails.
    """
    config = await get_user_config(user_id)
    if not config:
        return None

    # create and initialize with unified history manager
    try:
        chat_service = MCPChatService(config, user_id=user_id, redis_client=redis_client)
        await chat_service.initialize()
        await set_active_session(user_id, chat_service)
        return chat_service
    except Exception as e:
        # If initialization fails, ensure nothing partial remains
        logger.error(f"Failed to initialize MCPChatService for {user_id}: {e}", exc_info=True)
        # cleanup local state and redis ownership (if we set it)
        await delete_active_session(user_id)
        return None


async def get_active_session(user_id: str) -> Optional[MCPChatService]:
    """
    Retrieve or (if possible) create the active session for user_id.

    Behavior:
    - If Redis is disabled: return local session or None.
    - If Redis enabled:
      * If owner == WORKER_ID and local session exists -> return it (and refresh TTL)
      * If owner == WORKER_ID but local missing -> try to acquire lock and recreate
      * If no owner -> try to acquire lock and create session here
      * If owner != WORKER_ID -> wait a short time for owner to appear or return None

    Args:
        user_id: User identifier.

    Returns:
        Optional[MCPChatService]: Active session if available, None otherwise.
    """
    # Fast path: no redis => purely local
    if not redis_client:
        return active_sessions.get(user_id)

    active_key = _active_key(user_id)
    # _lock_key = _lock_key(user_id)
    owner = await redis_client.get(active_key)

    # 1) Owned by this worker
    if owner == WORKER_ID:
        local = active_sessions.get(user_id)
        if local:
            # refresh TTL so ownership persists while active
            try:
                await redis_client.expire(active_key, SESSION_TTL)
            except Exception as e:  # nosec B110
                # non-fatal if expire fails, just log the error
                logger.debug(f"Failed to refresh session TTL for {user_id}: {e}")
            return local

        # Owner in Redis points to this worker but local session missing (process restart or lost).
        # Try to recreate it (acquire lock).
        acquired = await _try_acquire_lock(user_id)
        if acquired:
            try:
                # create new local session
                session = await _create_local_session_from_config(user_id)
                return session
            finally:
                await _release_lock_safe(user_id)
        else:
            # someone else is (re)creating; wait a bit for them to finish
            for _ in range(LOCK_RETRIES):
                await asyncio.sleep(LOCK_WAIT)
                if active_sessions.get(user_id):
                    return active_sessions.get(user_id)
            return None

    # 2) No owner -> try to claim & create session locally
    if owner is None:
        acquired = await _try_acquire_lock(user_id)
        if acquired:
            try:
                session = await _create_local_session_from_config(user_id)
                return session
            finally:
                await _release_lock_safe(user_id)

        # if we couldn't acquire lock, someone else is creating; wait a short time
        for _ in range(LOCK_RETRIES):
            await asyncio.sleep(LOCK_WAIT)
            owner2 = await redis_client.get(active_key)
            if owner2 == WORKER_ID and active_sessions.get(user_id):
                return active_sessions.get(user_id)
            if owner2 is not None and owner2 != WORKER_ID:
                # some other worker now owns it
                return None

        # final attempt to acquire lock (last resort)
        acquired = await _try_acquire_lock(user_id)
        if acquired:
            try:
                session = await _create_local_session_from_config(user_id)
                return session
            finally:
                await _release_lock_safe(user_id)
        return None

    # 3) Owned by another worker -> we don't have it locally
    # Optionally we could attempt to "steal" if owner is stale, but TTL expiry handles that.
    return None


# ---------- ROUTES ----------


@llmchat_router.post("/connect")
async def connect(input_data: ConnectInput, request: Request):
    """Create or refresh a chat session for a user.

    Initializes a new MCPChatService instance for the specified user, establishing
    connections to both the MCP server and the configured LLM provider. If a session
    already exists for the user, it is gracefully shutdown before creating a new one.

    Authentication is handled via JWT token from cookies if not explicitly provided
    in the request body.

    Args:
        input_data: ConnectInput containing user_id, optional server/LLM config, and streaming preference.
        request: FastAPI Request object for accessing cookies and headers.

    Returns:
        dict: Connection status response containing:
            - status: 'connected'
            - user_id: The connected user's identifier
            - provider: The LLM provider being used
            - tool_count: Number of available MCP tools
            - tools: List of tool names

    Raises:
        HTTPException: If an error occurs.
            400: Invalid user_id, invalid configuration, or LLM config error.
            401: Missing authentication token.
            503: Failed to connect to MCP server.
            500: Service initialization failure or unexpected error.

    Examples:
        This endpoint is called via HTTP POST and cannot be directly tested with doctest.
        Example request body:

        {
            "user_id": "user123",
            "server": {
                "url": "http://localhost:8000/mcp",
                "auth_token": "jwt_token_here"
            },
            "llm": {
                "provider": "ollama",
                "config": {"model": "llama3"}
            },
            "streaming": false
        }

        Example response:

        {
            "status": "connected",
            "user_id": "user123",
            "provider": "ollama",
            "tool_count": 5,
            "tools": ["search", "calculator", "weather", "translate", "summarize"]
        }

    Note:
        Existing sessions are automatically terminated before establishing new ones.
        All configuration values support environment variable fallbacks.
    """
    user_id = input_data.user_id

    try:
        # Validate user_id
        if not user_id or not isinstance(user_id, str):
            raise HTTPException(status_code=400, detail="Invalid user ID provided")

        # Handle authentication token
        empty_token = ""  # nosec B105
        if input_data.server and (input_data.server.auth_token is None or input_data.server.auth_token == empty_token):
            jwt_token = request.cookies.get("jwt_token")
            if not jwt_token:
                raise HTTPException(status_code=401, detail="Authentication required. Please ensure you are logged in.")
            input_data.server.auth_token = jwt_token

        # Close old session if it exists
        existing = await get_active_session(user_id)
        if existing:
            try:
                logger.debug(f"Disconnecting existing session for {user_id} before reconnecting")
                await existing.shutdown()
            except Exception as shutdown_error:
                logger.warning(f"Failed to cleanly shutdown existing session for {user_id}: {shutdown_error}")
            finally:
                # Always remove the session from active sessions, even if shutdown failed
                await delete_active_session(user_id)

        # Build and validate configuration
        try:
            config = build_config(input_data)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=f"Invalid configuration: {str(ve)}")
        except Exception as config_error:
            raise HTTPException(status_code=400, detail=f"Configuration error: {str(config_error)}")

        # Store user configuration
        await set_user_config(user_id, config)

        # Initialize chat service
        try:
            chat_service = MCPChatService(config, user_id=user_id, redis_client=redis_client)
            await chat_service.initialize()

            # Clear chat history on new connection
            await chat_service.clear_history()
        except ConnectionError as ce:
            # Clean up partial state
            await delete_user_config(user_id)
            raise HTTPException(status_code=503, detail=f"Failed to connect to MCP server: {str(ce)}. Please verify the server URL and authentication.")
        except ValueError as ve:
            # Clean up partial state
            await delete_user_config(user_id)
            raise HTTPException(status_code=400, detail=f"Invalid LLM configuration: {str(ve)}")
        except Exception as init_error:
            # Clean up partial state
            await delete_user_config(user_id)
            raise HTTPException(status_code=500, detail=f"Service initialization failed: {str(init_error)}")

        await set_active_session(user_id, chat_service)

        # Extract tool names
        tool_names = []
        try:
            if hasattr(chat_service, "_tools") and chat_service._tools:
                for tool in chat_service._tools:
                    tool_name = getattr(tool, "name", None)
                    if tool_name:
                        tool_names.append(tool_name)
        except Exception as tool_error:
            logger.warning(f"Failed to extract tool names: {tool_error}")
            # Continue without tools list

        return {"status": "connected", "user_id": user_id, "provider": config.llm.provider, "tool_count": len(tool_names), "tools": tool_names}

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error in connect endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Unexpected connection error: {str(e)}")


async def token_streamer(chat_service: MCPChatService, message: str, user_id: str):
    """Stream chat response tokens as Server-Sent Events (SSE).

    Asynchronous generator that yields SSE-formatted chunks containing tokens,
    tool invocation updates, and final response data from the chat service.
    Uses the unified ChatHistoryManager for history persistence.

    Args:
        chat_service: MCPChatService instance configured for the user session.
        message: User's chat message to process.
        user_id: User identifier for logging.

    Yields:
        bytes: SSE-formatted event data containing:
            - token events: Incremental content chunks
            - tool_start: Tool invocation beginning
            - tool_end: Tool invocation completion
            - tool_error: Tool execution failure
            - final: Complete response with metadata
            - error: Error information with recovery status

        Event Types:
        - token: {"content": "text chunk"}
        - tool_start: {"type": "tool_start", "tool": "name", ...}
        - tool_end: {"type": "tool_end", "tool": "name", ...}
        - tool_error: {"type": "tool_error", "tool": "name", "error": "message"}
        - final: {"type": "final", "text": "complete response", "metadata": {...}}
        - error: {"type": "error", "error": "message", "recoverable": bool}

    Examples:
        This is an async generator used internally by the chat endpoint.
        It cannot be directly tested with standard doctest.

        Example event stream:

        event: token
        data: {"content": "Hello"}

        event: token
        data: {"content": ", how"}

        event: final
        data: {"type": "final", "text": "Hello, how can I help?"}

    Note:
        SSE format requires 'event: <type>\\ndata: <json>\\n\\n' structure.
        All exceptions are caught and converted to error events for client handling.
    """

    async def sse(event_type: str, data: Dict[str, Any]):
        """Format data as Server-Sent Event.

        Args:
            event_type: SSE event type identifier.
            data: Payload dictionary to serialize as JSON.

        Yields:
            bytes: UTF-8 encoded SSE formatted lines.
        """
        yield f"event: {event_type}\n".encode("utf-8")
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    try:
        async for ev in chat_service.chat_events(message):
            et = ev.get("type")
            if et == "token":
                content = ev.get("content", "")
                async for part in sse("token", {"content": content}):
                    yield part
            elif et in ("tool_start", "tool_end", "tool_error"):
                async for part in sse(et, ev):
                    yield part
            elif et == "final":
                async for part in sse("final", ev):
                    yield part

    except ConnectionError as ce:
        error_event = {"type": "error", "error": f"Connection lost: {str(ce)}", "recoverable": False}
        async for part in sse("error", error_event):
            yield part
    except TimeoutError:
        error_event = {"type": "error", "error": "Request timed out waiting for LLM response", "recoverable": True}
        async for part in sse("error", error_event):
            yield part
    except RuntimeError as re:
        error_event = {"type": "error", "error": f"Service error: {str(re)}", "recoverable": False}
        async for part in sse("error", error_event):
            yield part
    except Exception as e:
        logger.error(f"Unexpected streaming error: {e}", exc_info=True)
        error_event = {"type": "error", "error": f"Unexpected error: {str(e)}", "recoverable": False}
        async for part in sse("error", error_event):
            yield part


@llmchat_router.post("/chat")
async def chat(input_data: ChatInput):
    """Send a message to the user's active chat session and receive a response.

    Processes user messages through the configured LLM with MCP tool integration.
    Supports both streaming (SSE) and non-streaming response modes. Chat history
    is managed automatically via the unified ChatHistoryManager.

    Args:
        input_data: ChatInput containing user_id, message, and streaming preference.

    Returns:
        For streaming=False:
            dict: Response containing:
                - user_id: Session identifier
                - response: Complete LLM response text
                - tool_used: Boolean indicating if tools were invoked
                - tools: List of tool names used
                - tool_invocations: Detailed tool call information
                - elapsed_ms: Processing time in milliseconds
        For streaming=True:
            StreamingResponse: SSE stream of token and event data.

    Raises:
        HTTPException: Raised when an HTTP-related error occurs.
            400: Missing user_id, empty message, or no active session.
            503: Session not initialized, chat service error, or connection lost.
            504: Request timeout.
            500: Unexpected error.

        Examples:
        This endpoint is called via HTTP POST and cannot be directly tested with doctest.

        Example non-streaming request:

        {
            "user_id": "user123",
            "message": "What's the weather like?",
            "streaming": false
        }

        Example non-streaming response:

        {
            "user_id": "user123",
            "response": "The weather is sunny and 72°F.",
            "tool_used": true,
            "tools": ["weather"],
            "tool_invocations": 1,
            "elapsed_ms": 450
        }

        Example streaming request:

        {
            "user_id": "user123",
            "message": "Tell me a story",
            "streaming": true
        }

    Note:
        Streaming responses use Server-Sent Events (SSE) with 'text/event-stream' MIME type.
        Client must maintain persistent connection for streaming.
    """
    user_id = input_data.user_id

    # Validate input
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")

    if not input_data.message or not input_data.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Check for active session
    chat_service = await get_active_session(user_id)
    if not chat_service:
        raise HTTPException(status_code=400, detail="No active session found. Please connect to a server first.")

    # Verify session is initialized
    if not chat_service.is_initialized:
        raise HTTPException(status_code=503, detail="Session is not properly initialized. Please reconnect.")

    try:
        if input_data.streaming:
            return StreamingResponse(
                token_streamer(chat_service, input_data.message, user_id),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # Disable proxy buffering
            )
        else:
            try:
                result = await chat_service.chat_with_metadata(input_data.message)

                return {
                    "user_id": user_id,
                    "response": result["text"],
                    "tool_used": result["tool_used"],
                    "tools": result["tools"],
                    "tool_invocations": result["tool_invocations"],
                    "elapsed_ms": result["elapsed_ms"],
                }
            except RuntimeError as re:
                raise HTTPException(status_code=503, detail=f"Chat service error: {str(re)}")

    except ConnectionError as ce:
        raise HTTPException(status_code=503, detail=f"Lost connection to MCP server: {str(ce)}. Please reconnect.")
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Request timed out. The LLM took too long to respond.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


@llmchat_router.post("/disconnect")
async def disconnect(input_data: DisconnectInput):
    """End the chat session for a user and clean up resources.

    Gracefully shuts down the MCPChatService instance, closes connections,
    and removes session data from active storage. Safe to call even if
    no active session exists.

    Args:
        input_data: DisconnectInput containing the user_id to disconnect.

    Returns:
        dict: Disconnection status containing:
            - status: One of 'disconnected', 'no_active_session', or 'disconnected_with_errors'
            - user_id: The user identifier
            - message: Human-readable status description
            - warning: (Optional) Error details if cleanup encountered issues

    Raises:
        HTTPException: Raised when an HTTP-related error occurs.
            400: Missing user_id.

    Examples:
        This endpoint is called via HTTP POST and cannot be directly tested with doctest.

        Example request:

        {
            "user_id": "user123"
        }

        Example successful response:

        {
            "status": "disconnected",
            "user_id": "user123",
            "message": "Successfully disconnected"
        }

        Example response when no session exists:

        {
            "status": "no_active_session",
            "user_id": "user123",
            "message": "No active session to disconnect"
        }

    Note:
        This operation is idempotent - calling it multiple times for the same
        user_id is safe and will not raise errors.
    """
    user_id = input_data.user_id

    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")

    # Remove and shut down chat service
    chat_service = await get_active_session(user_id)
    await delete_active_session(user_id)

    # Remove user config
    await delete_user_config(user_id)

    if not chat_service:
        return {"status": "no_active_session", "user_id": user_id, "message": "No active session to disconnect"}

    try:
        # Clear chat history on disconnect
        await chat_service.clear_history()
        logger.info(f"Chat session disconnected for {user_id}")

        await chat_service.shutdown()
        return {"status": "disconnected", "user_id": user_id, "message": "Successfully disconnected"}
    except Exception as e:
        logger.error(f"Error during disconnect for user {user_id}: {e}", exc_info=True)
        # Session already removed, so return success with warning
        return {"status": "disconnected_with_errors", "user_id": user_id, "message": "Disconnected but cleanup encountered errors", "warning": str(e)}


@llmchat_router.get("/status/{user_id}")
async def status(user_id: str):
    """Check if an active chat session exists for the specified user.

    Lightweight endpoint for verifying session state without modifying data.
    Useful for health checks and UI state management.

    Args:
        user_id: User identifier to check session status for.

    Returns:
        dict: Status information containing:
            - user_id: The queried user identifier
            - connected: Boolean indicating if an active session exists

    Examples:
        This endpoint is called via HTTP GET and cannot be directly tested with doctest.

        Example request:
        GET /llmchat/status/user123

        Example response (connected):

        {
            "user_id": "user123",
            "connected": true
        }

        Example response (not connected):

        {
            "user_id": "user456",
            "connected": false
        }

    Note:
        This endpoint does not validate that the session is properly initialized,
        only that it exists in the active_sessions dictionary.
    """
    connected = bool(await get_active_session(user_id))
    return {"user_id": user_id, "connected": connected}


@llmchat_router.get("/config/{user_id}")
async def get_config(user_id: str):
    """Retrieve the stored configuration for a user's session.

    Returns sanitized configuration data with sensitive information (API keys,
    auth tokens) removed for security. Useful for debugging and configuration
    verification.

    Args:
        user_id: User identifier whose configuration to retrieve.

    Returns:
        dict: Sanitized configuration dictionary containing:
            - mcp_server: Server connection settings (without auth_token)
            - llm: LLM provider configuration (without api_key)
            - enable_streaming: Boolean streaming preference

    Raises:
        HTTPException: Raised when an HTTP-related error occurs.
            404: No configuration found for the specified user_id.


    Examples:
        This endpoint is called via HTTP GET and cannot be directly tested with doctest.

        Example request:
        GET /llmchat/config/user123

        Example response:

        {
            "mcp_server": {
                "url": "http://localhost:8000/mcp",
                "transport": "streamable_http"
            },
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": "llama3",
                    "temperature": 0.7
                }
            },
            "enable_streaming": false
        }

    Security:
        API keys and authentication tokens are explicitly removed before returning.
        Never log or expose these values in responses.
    """
    config = await get_user_config(user_id)

    if not config:
        raise HTTPException(status_code=404, detail="No config found for this user.")

    # Sanitize and return config (remove secrets)
    config_dict = config.model_dump()

    if "config" in config_dict.get("llm", {}):
        config_dict["llm"]["config"].pop("api_key", None)
        config_dict["llm"]["config"].pop("auth_token", None)

    return config_dict


@llmchat_router.get("/gateway/models")
async def get_gateway_models():
    """Get available models from configured LLM providers.

    Returns a list of enabled models from enabled providers configured
    in the gateway's LLM Settings. These models can be used with the
    "gateway" provider type in /connect requests.

    Returns:
        dict: Response containing:
            - models: List of available models with provider info
            - count: Total number of available models

    Examples:
        GET /llmchat/gateway/models

        Response:
        {
            "models": [
                {
                    "id": "abc123",
                    "model_id": "gpt-4o",
                    "model_name": "GPT-4o",
                    "provider_id": "def456",
                    "provider_name": "OpenAI",
                    "provider_type": "openai",
                    "supports_streaming": true,
                    "supports_function_calling": true,
                    "supports_vision": true
                }
            ],
            "count": 1
        }

    Raises:
        HTTPException: If there is an error retrieving gateway models.
    """
    # Import here to avoid circular dependency
    # First-Party
    from mcpgateway.db import SessionLocal
    from mcpgateway.services.llm_provider_service import LLMProviderService

    llm_service = LLMProviderService()

    try:
        with SessionLocal() as db:
            models = llm_service.get_gateway_models(db)
            return {
                "models": [m.model_dump() for m in models],
                "count": len(models),
            }
    except Exception as e:
        logger.error(f"Failed to get gateway models: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve gateway models: {str(e)}")
