# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/llmchat_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

LLM Chat Router Module

This module provides FastAPI endpoints for managing LLM-based chat sessions
with MCP (Model Context Protocol) server integration. LLM providers are
configured via the Admin UI's LLM Settings and accessed through the gateway
provider.

The module handles user session management, configuration, and real-time
streaming responses for conversational AI applications with unified chat
history management via ChatHistoryManager from mcp_client_chat_service.

"""

# Standard
import asyncio
import os
from typing import Any, Dict, Optional

# Third-Party
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import orjson
from pydantic import BaseModel, Field

try:
    # Third-Party
    import redis.asyncio  # noqa: F401 - availability check only

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.mcp_client_chat_service import (
    GatewayConfig,
    LLMConfig,
    MCPChatService,
    MCPClientConfig,
    MCPServerConfig,
)
from mcpgateway.utils.redis_client import get_redis_client

# Initialize router
llmchat_router = APIRouter(prefix="/llmchat", tags=["llmchat"])

# Redis client (initialized via init_redis() during app startup)
redis_client = None


async def init_redis() -> None:
    """Initialize Redis client using the shared factory.

    Should be called during application startup from main.py lifespan.
    """
    global redis_client
    if getattr(settings, "cache_type", None) == "redis" and getattr(settings, "redis_url", None):
        redis_client = await get_redis_client()
        if redis_client:
            logger.info("LLMChat router connected to shared Redis client")


# Fallback in-memory stores (used when Redis unavailable)
# Store active chat sessions per user
active_sessions: Dict[str, MCPChatService] = {}

# Store configuration per user
user_configs: Dict[str, MCPClientConfig] = {}

# Logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# ---------- MODELS ----------


class LLMInput(BaseModel):
    """Input configuration for LLM provider selection.

    This model specifies which gateway-configured model to use.
    Models must be configured via Admin UI -> LLM Settings.

    Attributes:
        model: Model ID from the gateway's LLM Settings (UUID or model_id).
        temperature: Optional sampling temperature (0.0-2.0).
        max_tokens: Optional maximum tokens to generate.

    Examples:
        >>> llm_input = LLMInput(model='gpt-4o')
        >>> llm_input.model
        'gpt-4o'

        >>> llm_input = LLMInput(model='abc123-uuid', temperature=0.5)
        >>> llm_input.temperature
        0.5
    """

    model: str = Field(..., description="Model ID from gateway LLM Settings (UUID or model_id)")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, gt=0, description="Maximum tokens to generate")


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
        llm: LLM configuration specifying which gateway model to use. Required.
        streaming: Whether to enable streaming responses. Defaults to False.

    Examples:
        >>> connect = ConnectInput(user_id='user123', llm=LLMInput(model='gpt-4o'))
        >>> connect.streaming
        False

        >>> connect = ConnectInput(user_id='user456', llm=LLMInput(model='gpt-4o'), streaming=True)
        >>> connect.user_id
        'user456'
    """

    user_id: str
    server: Optional[ServerInput] = None
    llm: LLMInput = Field(..., description="LLM configuration with model from gateway LLM Settings")
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


def build_llm_config(llm: LLMInput) -> LLMConfig:
    """Construct an LLMConfig object from input parameters.

    Creates a gateway provider configuration that routes requests through
    the gateway's LLM Settings. Models must be configured via Admin UI.

    Args:
        llm: LLMInput containing model ID and optional temperature/max_tokens.

    Returns:
        LLMConfig: Gateway provider configuration.

    Examples:
        >>> llm_input = LLMInput(model='gpt-4o')
        >>> config = build_llm_config(llm_input)
        >>> config.provider
        'gateway'

    Note:
        All LLM configuration is done via Admin UI -> Settings -> LLM Settings.
        The gateway provider looks up models from the database and creates
        the appropriate LLM instance based on provider type.
    """
    return LLMConfig(
        provider="gateway",
        config=GatewayConfig(
            model=llm.model,
            temperature=llm.temperature if llm.temperature is not None else 0.7,
            max_tokens=llm.max_tokens,
        ),
    )


def build_config(input_data: ConnectInput) -> MCPClientConfig:
    """Build complete MCP client configuration from connection input.

    Constructs a comprehensive configuration object combining MCP server settings
    and LLM configuration.

    Args:
        input_data: ConnectInput object containing server, LLM, and streaming settings.

    Returns:
        MCPClientConfig: Complete client configuration ready for service initialization.

    Examples:
        >>> from mcpgateway.routers.llmchat_router import ConnectInput, LLMInput, build_config
        >>> connect = ConnectInput(user_id='user123', llm=LLMInput(model='gpt-4o'))
        >>> config = build_config(connect)
        >>> config.mcp_server.transport
        'streamable_http'

    Note:
        MCP server settings use defaults if not provided.
        LLM configuration routes through the gateway provider.
    """
    server = input_data.server

    return MCPClientConfig(
        mcp_server=MCPServerConfig(
            url=server.url if server and server.url else "http://localhost:8000/mcp",
            transport=server.transport if server and server.transport else "streamable_http",
            auth_token=server.auth_token if server else None,
        ),
        llm=build_llm_config(input_data.llm),
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
        await redis_client.set(_cfg_key(user_id), orjson.dumps(config.model_dump()))
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
        return MCPClientConfig(**orjson.loads(data))
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
    """Remove active session locally and from Redis atomically.

    Uses a Lua script to ensure we only delete the Redis key if we own it,
    preventing race conditions where another worker's session marker could
    be deleted if our session expired and was recreated by another worker.

    Args:
        user_id: User identifier.
    """
    active_sessions.pop(user_id, None)
    if redis_client:
        try:
            # Lua script for atomic check-and-delete (only delete if we own the key)
            release_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await redis_client.eval(release_script, 1, _active_key(user_id), WORKER_ID)
        except Exception as e:
            logger.warning(f"Failed to delete active session for user {user_id}: {e}")


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
    """Release the lock atomically only if we own it.

    Uses a Lua script to ensure atomic check-and-delete, preventing
    the TOCTOU race condition where another worker's lock could be
    deleted if the original lock expired between get() and delete().

    Args:
        user_id: User identifier.
    """
    if not redis_client:
        return
    try:
        # Lua script for atomic check-and-delete (only delete if we own the key)
        release_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        await redis_client.eval(release_script, 1, _lock_key(user_id), WORKER_ID)
    except Exception as e:
        logger.warning(f"Failed to release lock for user {user_id}: {e}")


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

    def json_default(obj):
        """
        Default JSON serializer helper for non-serializable Python objects.

        Intended for use as the `default` parameter of `json.dumps`. The
        function tries common serialization patterns in the following order:

        1. model_dump() for Pydantic v2 models
        2. dict() for Pydantic v1 models
        3. __dict__ for plain Python objects
        4. Fallback to str(obj)

        Args:
            obj: An object that is not JSON serializable by default.

        Returns:
            A JSON-serializable representation of ``obj``.

        Examples:
            >>> class Simple:
            ...     def __init__(self):
            ...         self.x = 1
            ...         self.y = 2
            ...
            >>> json_default(Simple())
            {'x': 1, 'y': 2}

            >>> class WithStr:
            ...     def __str__(self):
            ...         return "custom"
            ...
            >>> json_default(WithStr())
            'custom'

            >>> class PydanticV1Like:
            ...     def dict(self):
            ...         return {"a": 1}
            ...
            >>> json_default(PydanticV1Like())
            {'a': 1}

            >>> class PydanticV2Like:
            ...     def model_dump(self):
            ...         return {"b": 2}
            ...
            >>> json_default(PydanticV2Like())
            {'b': 2}
        """
        # Try common patterns first
        if hasattr(obj, "model_dump"):  # pydantic v2
            return obj.model_dump()
        if hasattr(obj, "dict"):  # pydantic v1
            return obj.dict()
        if hasattr(obj, "__dict__"):
            return obj.__dict__

        # Fallback: string representation
        return str(obj)

    async def sse(event_type: str, data: Dict[str, Any]):
        """Format data as Server-Sent Event.

        Args:
            event_type: SSE event type identifier.
            data: Payload dictionary to serialize as JSON.

        Yields:
            bytes: UTF-8 encoded SSE formatted lines.
        """
        yield f"event: {event_type}\n".encode("utf-8")
        yield f"data: {orjson.dumps(data).decode()}\n\n".encode("utf-8")

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
