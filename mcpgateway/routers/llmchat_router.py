# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/llmchat_router.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
import socket
import time
from typing import Any, Dict, Optional
from uuid import uuid4

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request
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
from mcpgateway.auth_context import get_user_email
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.mcp_client_chat_service import (
    ChatProcessingError,
    GatewayConfig,
    LLMConfig,
    MCPChatService,
    MCPClientConfig,
    MCPServerConfig,
)
from mcpgateway.utils.redis_client import get_redis_client
from mcpgateway.utils.services_auth import decode_auth, encode_auth

# Initialize router
llmchat_router = APIRouter(prefix="/llmchat", tags=["llmchat"])

# Redis client (initialized via init_redis() during app startup)
redis_client = None


async def init_redis() -> None:
    """Initialize Redis client using the shared factory and rebind WORKER_ID.

    Should be called during application startup from main.py lifespan, which
    runs post-fork under gunicorn/UvicornWorker (and once under plain
    uvicorn/``make dev``). This is where ``WORKER_ID`` must be (re)computed:
    the module-level default is captured at *import* time, and because
    ``run-gunicorn.sh`` enables ``--preload`` by default on Linux, gunicorn
    imports this module once in the master process before forking — every
    worker would otherwise inherit the master's PID as its ``WORKER_ID`` and
    the ownership/lock compare-and-delete Lua scripts would compare a value
    against itself, letting any worker delete or release another's lock.
    Rebinding here, after fork, gives each process a distinct, host-qualified
    identifier that also survives PID reuse across worker recycling.

    Returns:
        None.
    """
    global redis_client, WORKER_ID  # pylint: disable=global-statement
    WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    if getattr(settings, "cache_type", None) == "redis" and getattr(settings, "redis_url", None):
        redis_client = await get_redis_client()
        if redis_client:
            logger.info("LLMChat router connected to shared Redis client")
    if redis_client is None and getattr(settings, "llmchat_enabled", False):
        logger.warning(
            "LLM Chat is enabled but Redis is not configured (CACHE_TYPE=redis + REDIS_URL). "
            "Chat sessions and config are per-process only; with more than one worker, requests "
            "routed to a different worker may not find the session."
        )


# Fallback in-memory stores (used when Redis unavailable)
# Store active chat sessions per user
active_sessions: Dict[str, MCPChatService] = {}

# Monotonic timestamp of last use per user_id, keyed the same as active_sessions.
# Used by the idle reaper (see _reap_idle_sessions) to bound local session
# lifetime once any worker may materialize a session via takeover.
active_sessions_last_used: Dict[str, float] = {}

# Store configuration per user
user_configs: Dict[str, tuple[bytes, float]] = {}

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


def _get_user_id_from_context(user: Dict[str, Any]) -> str:
    """Extract a stable user identifier from the authenticated user context.

    Args:
        user: Authenticated user context from RBAC dependency.

    Returns:
        User identifier string or "unknown" if missing.
    """
    if isinstance(user, dict):
        return user.get("id") or user.get("user_id") or get_user_email(user)
    return "unknown" if user is None else str(getattr(user, "id", user))


def _resolve_user_id(input_user_id: Optional[str], user: Dict[str, Any]) -> str:
    """Resolve the authenticated user ID and reject mismatched requests.

    Args:
        input_user_id: User ID provided by the client (optional).
        user: Authenticated user context from RBAC dependency.

    Returns:
        Resolved authenticated user identifier.

    Raises:
        HTTPException: When authentication is missing or user ID mismatches.
    """
    user_id = _get_user_id_from_context(user)
    if user_id == "unknown":
        raise HTTPException(status_code=401, detail="Authentication required.")
    if input_user_id and input_user_id != user_id:
        raise HTTPException(status_code=403, detail="User ID mismatch.")
    return user_id


# ---------- SESSION STORAGE HELPERS ----------

# Identify this worker uniquely (used for sticky session ownership)
WORKER_ID = str(os.getpid())

# Tunables (can set via environment)
SESSION_TTL = settings.llmchat_session_ttl  # seconds for active_session key TTL
LOCK_TTL = settings.llmchat_session_lock_ttl  # seconds for lock expiry
LOCK_RETRIES = settings.llmchat_session_lock_retries  # how many times to poll while waiting
LOCK_WAIT = settings.llmchat_session_lock_wait  # seconds between polls
USER_CONFIG_TTL = settings.llmchat_session_ttl

_ENCRYPTED_CONFIG_PAYLOAD_KEY = "_encrypted_payload"
_ENCRYPTED_CONFIG_VERSION_KEY = "_version"
_ENCRYPTED_CONFIG_VERSION = "1"
_CONFIG_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "auth_token",
        "authorization",
        "access_token",
        "refresh_token",
        "client_secret",
        "secret_access_key",
        "session_token",
        "credentials_json",
        "password",
        "private_key",
    }
)


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


def _cfg_version_key(user_id: str) -> str:
    """Generate Redis key for the user config's generation marker.

    A fresh random token is written here on every `/connect`, alongside the
    config itself. A local `MCPChatService` stamps the token it was built
    from onto itself (`config_version`); comparing that stamp against the
    current value of this key is how a takeover/reclaim detects that the
    user reconnected with a different config while the stale local copy was
    still cached, instead of silently serving it.

    Args:
        user_id: User identifier.

    Returns:
        str: Redis key for the config generation marker.
    """
    return f"user_config_version:{user_id}"


def _lock_key(user_id: str) -> str:
    """Generate Redis key for session initialization lock.

    Args:
        user_id: User identifier.

    Returns:
        str: Redis key for session locks.
    """
    return f"session_lock:{user_id}"


def _serialize_user_config_for_storage(config: MCPClientConfig) -> bytes:
    """Serialize and encrypt user config for storage backends.

    Args:
        config: User MCP client configuration.

    Returns:
        Serialized bytes containing encrypted config envelope.
    """
    payload = encode_auth({"config": config.model_dump()})
    return orjson.dumps(
        {
            _ENCRYPTED_CONFIG_VERSION_KEY: _ENCRYPTED_CONFIG_VERSION,
            _ENCRYPTED_CONFIG_PAYLOAD_KEY: payload,
        }
    )


def _deserialize_user_config_from_storage(data: bytes | str) -> Optional[MCPClientConfig]:
    """Deserialize user config from encrypted or legacy plaintext payloads.

    Args:
        data: Serialized config payload from storage.

    Returns:
        Parsed ``MCPClientConfig`` when data is valid, otherwise ``None``.
    """
    try:
        parsed = orjson.loads(data)
    except Exception:
        logger.warning("Failed to parse stored LLM chat config payload")
        return None

    # New encrypted envelope
    if isinstance(parsed, dict) and _ENCRYPTED_CONFIG_PAYLOAD_KEY in parsed:
        encrypted_payload = parsed.get(_ENCRYPTED_CONFIG_PAYLOAD_KEY)
        if not encrypted_payload:
            return None
        decoded = decode_auth(encrypted_payload)
        config_data = decoded.get("config") if isinstance(decoded, dict) else None
        if not isinstance(config_data, dict):
            logger.warning("Decoded encrypted LLM chat config is invalid")
            return None
        return MCPClientConfig(**config_data)

    # Legacy plaintext payload compatibility
    if isinstance(parsed, dict):
        return MCPClientConfig(**parsed)

    return None


def _is_sensitive_config_key(key: str) -> bool:
    """Return whether a config key should be masked in responses.

    Args:
        key: Config field name.

    Returns:
        ``True`` when key is in the sensitive-key allowlist.
    """
    return str(key).strip().lower() in _CONFIG_SENSITIVE_KEYS


def _mask_sensitive_config_values(value: Any) -> Any:
    """Recursively mask sensitive config values in API responses.

    Args:
        value: Arbitrary nested config value.

    Returns:
        Value with sensitive fields replaced by configured mask marker.
    """
    if isinstance(value, dict):
        masked: Dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_config_key(key):
                masked[key] = settings.masked_auth_value if item not in (None, "") else item
            else:
                masked[key] = _mask_sensitive_config_values(item)
        return masked
    if isinstance(value, list):
        return [_mask_sensitive_config_values(item) for item in value]
    return value


# ---------- CONFIG HELPERS ----------


async def set_user_config(user_id: str, config: MCPClientConfig, version: Optional[str] = None):
    """Store user configuration in Redis or memory.

    Args:
        user_id: User identifier.
        config: Complete MCP client configuration.
        version: Optional generation marker for this config (Redis-only). Callers
            that need takeover/reclaim to detect a config change should pass a
            fresh unique value (e.g. ``uuid4().hex``) here and stamp the same
            value onto the resulting `MCPChatService.config_version`.
    """
    serialized = _serialize_user_config_for_storage(config)
    if redis_client:
        await redis_client.set(_cfg_key(user_id), serialized, ex=USER_CONFIG_TTL)
        if version is not None:
            await redis_client.set(_cfg_version_key(user_id), version, ex=USER_CONFIG_TTL)
    else:
        user_configs[user_id] = (serialized, time.monotonic())


async def get_config_version(user_id: str) -> Optional[str]:
    """Retrieve the current config generation marker for a user (Redis-only).

    Local in-memory fallback (no Redis) never reaches cross-worker takeover
    logic, so there is nothing to compare against and this always returns
    None in that mode.

    Args:
        user_id: User identifier.

    Returns:
        Optional[str]: Current version token if present, else None.
    """
    if not redis_client:
        return None
    data = await redis_client.get(_cfg_version_key(user_id))
    if isinstance(data, bytes):
        return data.decode()
    return data


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
        return _deserialize_user_config_from_storage(data)

    cached_entry = user_configs.get(user_id)
    if not cached_entry:
        return None
    cached, cached_at = cached_entry
    if (time.monotonic() - cached_at) > USER_CONFIG_TTL:
        user_configs.pop(user_id, None)
        return None
    return _deserialize_user_config_from_storage(cached)


async def delete_user_config(user_id: str):
    """Delete user configuration from Redis or memory.

    Args:
        user_id: User identifier.
    """
    if redis_client:
        await redis_client.delete(_cfg_key(user_id))
        await redis_client.delete(_cfg_version_key(user_id))
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
    active_sessions_last_used.pop(user_id, None)
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
            logger.warning(f"Failed to delete active session for user {SecurityValidator.sanitize_log_message(user_id)}: {e}")


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
        logger.warning(f"Failed to release lock for user {SecurityValidator.sanitize_log_message(user_id)}: {e}")


async def _create_local_session_from_config(user_id: str) -> Optional[MCPChatService]:
    """Create MCPChatService locally from stored config.

    The build is bounded by ``LOCK_TTL``: this call only ever runs while the
    caller holds the per-user init lock, and that lock expires after
    ``LOCK_TTL`` seconds. ``MCPChatService.initialize()`` performs real
    network I/O (MCP transport connect plus tool discovery) that can exceed
    the default 30s on a slow or large server; without a bound, the lock
    could expire mid-build and let a second worker start building a
    duplicate session for the same user. Timing out is treated the same as
    any other initialization failure: partial state is cleaned up and the
    caller sees a clean ``None``.

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
        # Stamp the config generation this build came from so a later
        # takeover/reclaim can detect the user reconnected with a different
        # config in the meantime (see get_active_session).
        chat_service.config_version = await get_config_version(user_id)
        await asyncio.wait_for(chat_service.initialize(), timeout=LOCK_TTL)
        await set_active_session(user_id, chat_service)
        return chat_service
    except Exception as e:
        # If initialization fails (including a LOCK_TTL timeout), ensure nothing partial remains
        logger.error(f"Failed to initialize MCPChatService for {SecurityValidator.sanitize_log_message(user_id)}: {e}", exc_info=True)
        # cleanup local state and redis ownership (if we set it)
        await delete_active_session(user_id)
        return None


def _touch_last_used(user_id: str) -> None:
    """Stamp the idle clock for a user's active session.

    Called whenever a session is served or created so the idle reaper
    (`_reap_idle_sessions`) does not treat it as eligible for eviction.

    Args:
        user_id: User identifier whose session was just used.

    Returns:
        None.
    """
    active_sessions_last_used[user_id] = time.monotonic()


async def _refresh_session_ttls(user_id: str) -> None:
    """Refresh both the ownership and config Redis keys' TTLs for a user.

    The ownership key (`_active_key`) has always had its TTL renewed on
    every `get_active_session` hit; the config key (`_cfg_key`) previously
    was not, so a long conversation's stored config could silently expire
    after `USER_CONFIG_TTL` seconds even though the conversation was still
    active. That gap was masked as long as the owning worker always served
    from its never-expiring local `active_sessions` dict; takeover makes the
    gap reachable from any worker, so both keys must be kept alive together
    (§3b of the multi-worker session fix). No-op when Redis is disabled.

    Args:
        user_id: User identifier whose Redis-backed keys should be renewed.

    Returns:
        None.
    """
    if not redis_client:
        return
    try:
        await redis_client.expire(_active_key(user_id), SESSION_TTL)
        await redis_client.expire(_cfg_key(user_id), USER_CONFIG_TTL)
        await redis_client.expire(_cfg_version_key(user_id), USER_CONFIG_TTL)
    except Exception as e:  # nosec B110
        logger.debug(f"Failed to refresh session TTLs for {SecurityValidator.sanitize_log_message(user_id)}: {e}")


async def _reap_idle_sessions() -> None:
    """Evict and shut down local sessions that are idle and foreign-owned.

    Once any worker may take over a session from Redis-backed config, an
    old owner's local `MCPChatService` becomes orphaned after takeover and
    would otherwise never be cleaned up (a connection/fd leak). This scans
    `active_sessions` for entries whose `active_sessions_last_used` stamp is
    older than `SESSION_TTL` seconds *and* whose Redis ownership key no
    longer names this worker, and shuts those down.

    An entry with no recorded `last_used` (never touched via
    `get_active_session`/`_touch_last_used`) is left alone rather than
    treated as maximally idle. An entry that is idle but still owned by this
    worker in Redis is also left alone -- the conversation may simply be
    paused. Long-running streamed responses re-stamp `last_used` per chunk
    (see `token_streamer`), so an in-flight stream can never look idle
    mid-response.

    Only runs when Redis is configured; without Redis there is no concept
    of cross-worker ownership to reap against.

    Returns:
        None.
    """
    if not redis_client:
        return
    now = time.monotonic()
    for uid in list(active_sessions.keys()):
        last_used = active_sessions_last_used.get(uid)
        if last_used is None or (now - last_used) <= SESSION_TTL:
            continue
        try:
            owner = await redis_client.get(_active_key(uid))
            if isinstance(owner, bytes):
                owner = owner.decode()
        except Exception as e:  # nosec B110
            logger.debug(f"Reaper failed to check ownership for {SecurityValidator.sanitize_log_message(uid)}: {e}")
            continue
        if owner == WORKER_ID:
            continue
        session = active_sessions.pop(uid, None)
        active_sessions_last_used.pop(uid, None)
        if session is not None:
            try:
                await session.shutdown()
            except Exception as e:
                logger.warning(f"Reaper failed to shut down idle session for {SecurityValidator.sanitize_log_message(uid)}: {e}")


async def _acquire_and_create_session(user_id: str) -> Optional[MCPChatService]:
    """Acquire the per-user init lock and materialize a session from config.

    On failure to acquire the lock, polls for the *lock key itself* to
    clear (not the local `active_sessions` dict -- another worker's process
    can never fill this worker's own dict, so waiting on it is a guaranteed
    timeout) and retries acquisition exactly once before giving up.

    Args:
        user_id: User identifier.

    Returns:
        Optional[MCPChatService]: Newly created local session, or None if
        the lock could not be acquired (even after the retry) or the build
        itself failed (see `_create_local_session_from_config`).
    """
    acquired = await _try_acquire_lock(user_id)
    if acquired:
        try:
            return await _create_local_session_from_config(user_id)
        finally:
            await _release_lock_safe(user_id)

    # Someone else (another worker, or a concurrent request on this one) is
    # already (re)building the session. Wait for the lock to clear.
    for _ in range(LOCK_RETRIES):
        await asyncio.sleep(LOCK_WAIT)
        if redis_client and not await redis_client.get(_lock_key(user_id)):
            break
    else:
        return None

    acquired = await _try_acquire_lock(user_id)
    if acquired:
        try:
            return await _create_local_session_from_config(user_id)
        finally:
            await _release_lock_safe(user_id)
    return None


async def _discard_stale_session(user_id: str, session: MCPChatService) -> None:
    """Shut down and remove a locally-held session that no longer matches the current config.

    Args:
        user_id: User identifier.
        session: The stale locally-held session to discard.

    Returns:
        None.
    """
    try:
        await session.shutdown()
    except Exception as e:
        logger.warning(f"Failed to cleanly shut down stale session for {SecurityValidator.sanitize_log_message(user_id)}: {e}")
    await delete_active_session(user_id)


async def _local_session_is_stale(user_id: str, session: MCPChatService) -> bool:
    """Return True when a locally-held session no longer matches the stored config.

    Compares the version stamped on `session` (from whichever config build
    produced it) against the current `_cfg_version_key` in Redis. A user who
    reconnects on a different worker overwrites the Redis-backed config and
    ownership, but cannot reach into another worker's `active_sessions` dict
    to evict the now-outdated local copy -- without this check, a later
    request that lands back on the stale worker within `SESSION_TTL` could
    silently reclaim/serve a session built from a superseded server/model
    config instead of rebuilding from the current one.

    Args:
        user_id: User identifier.
        session: Locally-held session being considered for reuse.

    Returns:
        bool: True if the session should be discarded and rebuilt.
    """
    current_version = await get_config_version(user_id)
    if current_version is None:
        # Nothing to compare against (e.g. version key expired/never set) --
        # do not force a needless rebuild off missing data.
        return False
    return getattr(session, "config_version", None) != current_version


async def get_active_session(user_id: str, recreate: bool = True) -> Optional[MCPChatService]:
    """Retrieve, and optionally take over or (re)create, the active session for user_id.

    Behavior:
    - If Redis is disabled, or `recreate` is False: return the locally-held
      session, or None. `recreate=False` is for callers that are about to
      replace or tear down the session (`/connect`, `/disconnect`) -- they
      must not pay the cost of rebuilding a foreign worker's session (a full
      MCP handshake) just to immediately discard it.
    - If Redis is enabled and `recreate` is True (the default, used by
      `/chat`):
      * If owner == WORKER_ID and a local session exists -> return it,
        refreshing both the ownership and config key TTLs.
      * If owner == WORKER_ID but the local session is missing (process
        restart) -> acquire the lock and recreate it.
      * If there is no owner -> acquire the lock and create the session here.
      * If another worker owns it -> take over: return a local session if
        this worker happens to already have one (reclaiming ownership),
        otherwise acquire the lock and materialize a new local session from
        the Redis-backed config. This is a deliberate takeover, not a shared
        session -- the previous owner's local copy becomes orphaned and is
        reclaimed by the idle reaper (`_reap_idle_sessions`).
      In all cases, if the stored config is absent or expired, this
      returns None (the correct outcome: the user never connected, or the
      config TTL lapsed).

    Args:
        user_id: User identifier.
        recreate: Whether to allow rebuilding the session from Redis-backed
            config when it is not already held locally. Defaults to True.

    Returns:
        Optional[MCPChatService]: Active session if available, None otherwise.
    """
    # Local-only fast path: no Redis backing, or the caller explicitly wants
    # the local session without triggering a cross-worker takeover/rebuild.
    if not redis_client or not recreate:
        local = active_sessions.get(user_id)
        if local:
            _touch_last_used(user_id)
        return local

    await _reap_idle_sessions()

    active_key = _active_key(user_id)
    owner = await redis_client.get(active_key)
    if isinstance(owner, bytes):
        owner = owner.decode()

    # 1) Owned by this worker
    if owner == WORKER_ID:
        local = active_sessions.get(user_id)
        if local and not await _local_session_is_stale(user_id, local):
            # refresh both TTLs so ownership and config persist while active
            try:
                await redis_client.expire(active_key, SESSION_TTL)
                await redis_client.expire(_cfg_key(user_id), USER_CONFIG_TTL)
                await redis_client.expire(_cfg_version_key(user_id), USER_CONFIG_TTL)
            except Exception as e:  # nosec B110
                # non-fatal if expire fails, just log the error
                logger.debug(f"Failed to refresh session TTL for {SecurityValidator.sanitize_log_message(user_id)}: {e}")
            _touch_last_used(user_id)
            return local

        if local:
            # Config changed since this local session was built (or this
            # worker regained ownership after losing it) -- discard rather
            # than serve a session built from a superseded config.
            await _discard_stale_session(user_id, local)

        # Owner in Redis points to this worker but local session is missing
        # (discarded as stale above, or process restart/lost).
        session = await _acquire_and_create_session(user_id)
        if session:
            _touch_last_used(user_id)
        return session

    # 2) No owner -> try to claim & create session locally
    if owner is None:
        session = await _acquire_and_create_session(user_id)
        if session:
            _touch_last_used(user_id)
        return session

    # 3) Owned by another worker -> take over rather than reject.
    local = active_sessions.get(user_id)
    if local and not await _local_session_is_stale(user_id, local):
        # Ownership drifted away from us (e.g. a TTL/reaper race) while we
        # still hold a live, current session locally; reclaim ownership
        # instead of paying to rebuild.
        await set_active_session(user_id, local)
        _touch_last_used(user_id)
        return local

    if local:
        # Stale local copy (user reconnected elsewhere with a different
        # config while this worker still cached the old session) -- discard
        # it instead of reclaiming, then rebuild from the current config.
        await _discard_stale_session(user_id, local)

    session = await _acquire_and_create_session(user_id)
    if session:
        _touch_last_used(user_id)
    return session


# ---------- ROUTES ----------


@llmchat_router.post("/connect")
@require_permission("llm.invoke")
async def connect(input_data: ConnectInput, request: Request, user=Depends(get_current_user_with_permissions)):
    """Create or refresh a chat session for a user.

    Initializes a new MCPChatService instance for the specified user, establishing
    connections to both the MCP server and the configured LLM provider. If a session
    already exists for the user, it is gracefully shutdown before creating a new one.

    Authentication is handled via JWT token from cookies if not explicitly provided
    in the request body.

    Args:
        input_data: ConnectInput containing user_id, optional server/LLM config, and streaming preference.
        request: FastAPI Request object for accessing cookies and headers.
        user: Authenticated user context.

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
    user_id = _resolve_user_id(input_data.user_id, user)

    try:
        # Validate user_id
        if not user_id or not isinstance(user_id, str):
            raise HTTPException(status_code=400, detail="Invalid user ID provided")

        # Validate user-supplied server URLs with SSRF protections before any outbound connection setup.
        if input_data.server and input_data.server.url:
            try:
                input_data.server.url = SecurityValidator.validate_url(str(input_data.server.url), "MCP server URL")
            except ValueError as e:
                logger.warning("LLM chat connect URL validation failed for user %s and URL %s: %s", user_id, input_data.server.url, e)
                raise HTTPException(status_code=400, detail="Invalid server URL")

        # Handle authentication token
        empty_token = ""  # nosec B105
        if input_data.server and (input_data.server.auth_token is None or input_data.server.auth_token == empty_token):
            jwt_token = request.cookies.get("jwt_token")
            if not jwt_token:
                raise HTTPException(status_code=401, detail="Authentication required. Please ensure you are logged in.")
            input_data.server.auth_token = jwt_token

        # Close old session if it exists. Local-only lookup (recreate=False):
        # a session owned by another worker is about to be superseded anyway,
        # so there is no reason to pay for a full takeover rebuild (network +
        # tool discovery) just to immediately shut it back down. The Redis
        # ownership key for a foreign copy is left to expire naturally / be
        # cleaned up by the idle reaper.
        existing = await get_active_session(user_id, recreate=False)
        if existing:
            try:
                logger.debug(f"Disconnecting existing session for {SecurityValidator.sanitize_log_message(user_id)} before reconnecting")
                await existing.shutdown()
            except Exception as shutdown_error:
                logger.warning(f"Failed to cleanly shutdown existing session for {SecurityValidator.sanitize_log_message(user_id)}: {shutdown_error}")
            finally:
                # Always remove the session from active sessions, even if shutdown failed
                await delete_active_session(user_id)

        # Build and validate configuration
        try:
            config = build_config(input_data)
        except ValueError:
            logger.debug("Invalid chat configuration for user %s", SecurityValidator.sanitize_log_message(user_id))
            raise HTTPException(status_code=400, detail="Invalid configuration")
        except Exception:
            logger.error("Chat configuration error for user %s", SecurityValidator.sanitize_log_message(user_id), exc_info=True)
            raise HTTPException(status_code=400, detail="Configuration error")

        # Store user configuration, stamped with a fresh generation marker so
        # a stale local session cached on another worker can detect this
        # reconnect and rebuild instead of being silently reclaimed/served
        # (see get_active_session / _local_session_is_stale).
        config_version = uuid4().hex
        await set_user_config(user_id, config, version=config_version)

        # Initialize chat service
        try:
            chat_service = MCPChatService(config, user_id=user_id, redis_client=redis_client)
            chat_service.config_version = config_version
            await chat_service.initialize()

            # Clear chat history on new connection
            await chat_service.clear_history()
        except ConnectionError:
            # Clean up partial state
            logger.error("Failed to connect to MCP server for user %s", SecurityValidator.sanitize_log_message(user_id), exc_info=True)
            await delete_user_config(user_id)
            raise HTTPException(status_code=503, detail="Failed to connect to MCP server. Please verify the server URL and authentication.")
        except ValueError:
            # Clean up partial state
            logger.warning("Invalid LLM configuration for user %s", SecurityValidator.sanitize_log_message(user_id))
            await delete_user_config(user_id)
            raise HTTPException(status_code=400, detail="Invalid LLM configuration")
        except Exception:
            # Clean up partial state
            logger.error("Service initialization failed for user %s", SecurityValidator.sanitize_log_message(user_id), exc_info=True)
            await delete_user_config(user_id)
            raise HTTPException(status_code=500, detail="Service initialization failed")

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
        raise HTTPException(status_code=500, detail="Unexpected connection error")


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
        Each emitted event re-stamps the session's idle clock (see
        `_touch_last_used`), so a long-running stream can never be reaped as
        idle mid-response even if the stream as a whole outlives `SESSION_TTL`.
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
        yield f"data: {orjson.dumps(data).decode()}\n\n".encode("utf-8")

    try:
        async for ev in chat_service.chat_events(message):
            # Re-stamp idle clock per chunk so the reaper never evicts a
            # session that is still actively streaming (§4 of the
            # multi-worker session fix).
            _touch_last_used(user_id)
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
    except ChatProcessingError as cpe:
        # ChatProcessingError wraps tool/parsing/model errors —
        # the session is still valid, so the frontend can retry.
        error_event = {"type": "error", "error": f"Service error: {str(cpe)}", "recoverable": True}
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
@require_permission("llm.invoke")
async def chat(input_data: ChatInput, user=Depends(get_current_user_with_permissions)):
    """Send a message to the user's active chat session and receive a response.

    Processes user messages through the configured LLM with MCP tool integration.
    Supports both streaming (SSE) and non-streaming response modes. Chat history
    is managed automatically via the unified ChatHistoryManager.

    Args:
        input_data: ChatInput containing user_id, message, and streaming preference.
        user: Authenticated user context.

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
    user_id = _resolve_user_id(input_data.user_id, user)

    # Validate input
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")

    if not input_data.message or not input_data.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Check for active session (recreate=True default: any worker may take
    # over the session from Redis-backed config)
    chat_service = await get_active_session(user_id)
    if not chat_service:
        raise HTTPException(status_code=400, detail="No active session found. Please connect to a server first.")

    # Successful hit -- refresh the config TTL alongside the ownership TTL
    # (§3b): a freshly-recreated session's config was just read, not
    # re-written, so without this it keeps counting down from /connect time.
    await _refresh_session_ttls(user_id)

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
            except RuntimeError:
                logger.error("Chat service runtime error for user %s", SecurityValidator.sanitize_log_message(user_id), exc_info=True)
                raise HTTPException(status_code=503, detail="Chat service error")

    except ConnectionError:
        logger.error("Lost connection to MCP server for user %s", SecurityValidator.sanitize_log_message(user_id), exc_info=True)
        raise HTTPException(status_code=503, detail="Lost connection to MCP server. Please reconnect.")
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Request timed out. The LLM took too long to respond.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint for user {SecurityValidator.sanitize_log_message(user_id)}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@llmchat_router.post("/disconnect")
@require_permission("llm.invoke")
async def disconnect(input_data: DisconnectInput, user=Depends(get_current_user_with_permissions)):
    """End the chat session for a user and clean up resources.

    Gracefully shuts down the MCPChatService instance, closes connections,
    and removes session data from active storage. Safe to call even if
    no active session exists.

    Args:
        input_data: DisconnectInput containing the user_id to disconnect.
        user: Authenticated user context.

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
    user_id = _resolve_user_id(input_data.user_id, user)

    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")

    # Remove and shut down chat service. Local-only lookup (recreate=False):
    # this call is about to tear the session down, so there is no reason to
    # rebuild a foreign worker's copy first just to immediately shut it back
    # down; the reaper and Redis key deletion below handle that copy.
    chat_service = await get_active_session(user_id, recreate=False)
    await delete_active_session(user_id)

    # Remove user config
    await delete_user_config(user_id)

    if not chat_service:
        return {"status": "no_active_session", "user_id": user_id, "message": "No active session to disconnect"}

    try:
        # Clear chat history on disconnect
        await chat_service.clear_history()
        logger.info(f"Chat session disconnected for {SecurityValidator.sanitize_log_message(user_id)}")

        await chat_service.shutdown()
        return {"status": "disconnected", "user_id": user_id, "message": "Successfully disconnected"}
    except Exception as e:
        logger.error(f"Error during disconnect for user {SecurityValidator.sanitize_log_message(user_id)}: {e}", exc_info=True)
        # Session already removed, so return success with warning
        return {"status": "disconnected_with_errors", "user_id": user_id, "message": "Disconnected but cleanup encountered errors", "warning": str(e)}


async def _has_active_session_state(user_id: str) -> bool:
    """Check whether active session state exists for a user without building one.

    A pure existence check -- a local dict lookup, plus a Redis `EXISTS` on
    the ownership/config keys when Redis is configured -- so a read-only
    status poll never triggers a cross-worker takeover or the cost of
    deserializing and decrypting the stored config
    (`_deserialize_user_config_from_storage`) just to produce a boolean.

    Args:
        user_id: User identifier to check.

    Returns:
        bool: True when an active session (local, or Redis-backed on any
        worker) exists for the user.
    """
    if user_id in active_sessions:
        return True
    if not redis_client:
        return False
    try:
        exists = await redis_client.exists(_active_key(user_id), _cfg_key(user_id))
        return bool(exists)
    except Exception as e:  # nosec B110
        logger.debug(f"Failed to check active session state for {SecurityValidator.sanitize_log_message(user_id)}: {e}")
        return False


@llmchat_router.get("/status/{user_id}")
@require_permission("llm.read")
async def status(user_id: str, user=Depends(get_current_user_with_permissions)):
    """Check if an active chat session exists for the specified user.

    Lightweight endpoint for verifying session state without modifying data.
    Useful for health checks and UI state management. This performs a pure
    existence check -- it never calls `get_active_session()` -- so a
    read-only status poll cannot trigger a cross-worker takeover or pay the
    network/tool-discovery cost of rebuilding a session as a side effect of
    a GET (see `_has_active_session_state`).

    Args:
        user_id: User identifier to check session status for.
        user: Authenticated user context.

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
        This endpoint does not validate that the session is properly
        initialized, only that active state (local or Redis-backed) exists
        for the user.
    """
    resolved_user_id = _resolve_user_id(user_id, user)
    connected = await _has_active_session_state(resolved_user_id)
    return {"user_id": resolved_user_id, "connected": connected}


@llmchat_router.get("/config/{user_id}")
@require_permission("llm.read")
async def get_config(user_id: str, user=Depends(get_current_user_with_permissions)):
    """Retrieve the stored configuration for a user's session.

    Returns sanitized configuration data with sensitive information (API keys,
    auth tokens) removed for security. Useful for debugging and configuration
    verification.

    Args:
        user_id: User identifier whose configuration to retrieve.
        user: Authenticated user context.

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
    resolved_user_id = _resolve_user_id(user_id, user)
    config = await get_user_config(resolved_user_id)

    if not config:
        raise HTTPException(status_code=404, detail="No config found for this user.")

    config_dict = config.model_dump()
    return _mask_sensitive_config_values(config_dict)


@llmchat_router.get("/gateway/models")
@require_permission("llm.read")
async def get_gateway_models(_user=Depends(get_current_user_with_permissions)):
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

    Args:
        _user: Authenticated user context.
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
        raise HTTPException(status_code=500, detail="Failed to retrieve gateway models")
