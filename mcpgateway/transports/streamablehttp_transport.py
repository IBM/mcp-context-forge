# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/streamablehttp_transport.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

Streamable HTTP Transport Implementation.
This module implements Streamable Http transport for MCP

Key components include:
- SessionManagerWrapper: Manages the lifecycle of streamable HTTP sessions
- Configuration options for:
        1. stateful/stateless operation
        2. JSON response mode or SSE streams
- InMemoryEventStore: A simple in-memory event storage system for maintaining session state

Examples:
    >>> # Test module imports
    >>> from mcpgateway.transports.streamablehttp_transport import (
    ...     EventEntry, StreamBuffer, InMemoryEventStore, SessionManagerWrapper
    ... )
    >>>
    >>> # Verify classes are available
    >>> EventEntry.__name__
    'EventEntry'
    >>> StreamBuffer.__name__
    'StreamBuffer'
    >>> InMemoryEventStore.__name__
    'InMemoryEventStore'
    >>> SessionManagerWrapper.__name__
    'SessionManagerWrapper'
"""

# Standard
import asyncio
from contextlib import asynccontextmanager, AsyncExitStack
import contextvars
from dataclasses import dataclass
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Pattern, Tuple, Union
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

# Third-Party
import anyio
from fastapi import HTTPException
from fastapi.security.utils import get_authorization_scheme_param
import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import EventCallback, EventId, EventMessage, EventStore, StreamId
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import JSONRPCMessage, PaginatedRequestParams, ReadResourceRequest, ReadResourceRequestParams
import orjson
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND
from starlette.types import Receive, Scope, Send

# First-Party
from mcpgateway.common.models import LogLevel
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG
from mcpgateway.services.completion_service import CompletionService
from mcpgateway.services.http_client_service import get_http_client, get_http_limits
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics import mcp_auth_cache_events_counter
from mcpgateway.services.oauth_manager import OAuthEnforcementUnavailableError, OAuthRequiredError
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.transports.redis_event_store import RedisEventStore
from mcpgateway.utils.gateway_access import build_gateway_auth_headers, check_gateway_access, extract_gateway_id_from_headers, GATEWAY_ID_HEADER
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.verify_credentials import is_proxy_auth_trust_active, require_auth_header_first, verify_credentials

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


def _record_mcp_auth_cache_event(outcome: str) -> None:
    """Best-effort Prometheus counter update for MCP auth cache flow.

    Args:
        outcome: Cache-flow outcome label to emit.
    """
    try:
        mcp_auth_cache_events_counter.labels(outcome=outcome).inc()
    except Exception:
        pass  # nosec B110 - Metrics must not break auth flow


# Precompiled regex for server ID extraction from path
_SERVER_ID_RE: Pattern[str] = re.compile(r"/servers/(?P<server_id>[a-fA-F0-9\-]+)/mcp")

# ASGI scope key for propagating gateway context from middleware to MCP handlers
_MCPGATEWAY_CONTEXT_KEY = "_mcpgateway_context"

# Initialize ToolService, PromptService, ResourceService, CompletionService and MCP Server
tool_service: ToolService = ToolService()
prompt_service: PromptService = PromptService()
resource_service: ResourceService = ResourceService()
completion_service: CompletionService = CompletionService()

mcp_app: Server[Any] = Server("mcp-streamable-http")

server_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("server_id", default="default_server_id")
request_headers_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("request_headers", default={})
user_context_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("user_context", default={})
_oauth_checked_var: contextvars.ContextVar[bool] = contextvars.ContextVar("_oauth_checked", default=False)
_shared_session_registry: Optional[Any] = None
_rust_event_store_client: Optional[httpx.AsyncClient] = None
_rust_event_store_client_lock = asyncio.Lock()
_RUST_EVENT_STORE_DEFAULT_KEY_PREFIX = "mcpgw:eventstore"

# ------------------------------ Event store ------------------------------


@dataclass
class EventEntry:
    """
    Represents an event entry in the event store.

    Examples:
        >>> # Create an event entry
        >>> from mcp.types import JSONRPCMessage
        >>> message = JSONRPCMessage(jsonrpc="2.0", method="test", id=1)
        >>> entry = EventEntry(event_id="test-123", stream_id="stream-456", message=message, seq_num=0)
        >>> entry.event_id
        'test-123'
        >>> entry.stream_id
        'stream-456'
        >>> entry.seq_num
        0
        >>> # Access message attributes through model_dump() for Pydantic v2
        >>> message_dict = message.model_dump()
        >>> message_dict['jsonrpc']
        '2.0'
        >>> message_dict['method']
        'test'
        >>> message_dict['id']
        1
    """

    event_id: EventId
    stream_id: StreamId
    message: JSONRPCMessage
    seq_num: int


@dataclass
class StreamBuffer:
    """
    Ring buffer for per-stream event storage with O(1) position lookup.

    Tracks sequence numbers to enable efficient replay without scanning.
    Events are stored at position (seq_num % capacity) in the entries list.

    Examples:
        >>> # Create a stream buffer with capacity 3
        >>> buffer = StreamBuffer(entries=[None, None, None])
        >>> buffer.start_seq
        0
        >>> buffer.next_seq
        0
        >>> buffer.count
        0
        >>> len(buffer)
        0

        >>> # Simulate adding an entry
        >>> buffer.next_seq = 1
        >>> buffer.count = 1
        >>> len(buffer)
        1
    """

    entries: list[EventEntry | None]
    start_seq: int = 0  # oldest seq still buffered
    next_seq: int = 0  # seq assigned to next insert
    count: int = 0

    def __len__(self) -> int:
        """Return the number of events currently in the buffer.

        Returns:
            int: The count of events in the buffer.
        """
        return self.count


class InMemoryEventStore(EventStore):
    """
    Simple in-memory implementation of the EventStore interface for resumability.
    This is primarily intended for examples and testing, not for production use
    where a persistent storage solution would be more appropriate.

    This implementation keeps only the last N events per stream for memory efficiency.
    Uses a ring buffer with per-stream sequence numbers for O(1) event lookup and O(k) replay.

    Examples:
        >>> # Create event store with default max events
        >>> store = InMemoryEventStore()
        >>> store.max_events_per_stream
        100
        >>> len(store.streams)
        0
        >>> len(store.event_index)
        0

        >>> # Create event store with custom max events
        >>> store = InMemoryEventStore(max_events_per_stream=50)
        >>> store.max_events_per_stream
        50

        >>> # Test event store initialization
        >>> store = InMemoryEventStore()
        >>> hasattr(store, 'streams')
        True
        >>> hasattr(store, 'event_index')
        True
        >>> isinstance(store.streams, dict)
        True
        >>> isinstance(store.event_index, dict)
        True
    """

    def __init__(self, max_events_per_stream: int = 100):
        """Initialize the event store.

        Args:
            max_events_per_stream: Maximum number of events to keep per stream

        Examples:
            >>> # Test initialization with default value
            >>> store = InMemoryEventStore()
            >>> store.max_events_per_stream
            100
            >>> store.streams == {}
            True
            >>> store.event_index == {}
            True

            >>> # Test initialization with custom value
            >>> store = InMemoryEventStore(max_events_per_stream=25)
            >>> store.max_events_per_stream
            25
        """
        self.max_events_per_stream = max_events_per_stream
        # Per-stream ring buffers for O(1) position lookup
        self.streams: dict[StreamId, StreamBuffer] = {}
        # event_id -> EventEntry for quick lookup
        self.event_index: dict[EventId, EventEntry] = {}

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage) -> EventId:
        """
        Stores an event with a generated event ID.

        Args:
            stream_id (StreamId): The ID of the stream.
            message (JSONRPCMessage): The message to store.

        Returns:
            EventId: The ID of the stored event.

        Examples:
            >>> # Test storing an event
            >>> import asyncio
            >>> from mcp.types import JSONRPCMessage
            >>> store = InMemoryEventStore(max_events_per_stream=5)
            >>> message = JSONRPCMessage(jsonrpc="2.0", method="test", id=1)
            >>> event_id = asyncio.run(store.store_event("stream-1", message))
            >>> isinstance(event_id, str)
            True
            >>> len(event_id) > 0
            True
            >>> len(store.streams)
            1
            >>> len(store.event_index)
            1
            >>> "stream-1" in store.streams
            True
            >>> event_id in store.event_index
            True

            >>> # Test storing multiple events in same stream
            >>> message2 = JSONRPCMessage(jsonrpc="2.0", method="test2", id=2)
            >>> event_id2 = asyncio.run(store.store_event("stream-1", message2))
            >>> len(store.streams["stream-1"])
            2
            >>> len(store.event_index)
            2

            >>> # Test ring buffer overflow
            >>> store2 = InMemoryEventStore(max_events_per_stream=2)
            >>> msg1 = JSONRPCMessage(jsonrpc="2.0", method="m1", id=1)
            >>> msg2 = JSONRPCMessage(jsonrpc="2.0", method="m2", id=2)
            >>> msg3 = JSONRPCMessage(jsonrpc="2.0", method="m3", id=3)
            >>> id1 = asyncio.run(store2.store_event("stream-2", msg1))
            >>> id2 = asyncio.run(store2.store_event("stream-2", msg2))
            >>> # Now buffer is full, adding third will remove first
            >>> id3 = asyncio.run(store2.store_event("stream-2", msg3))
            >>> len(store2.streams["stream-2"])
            2
            >>> id1 in store2.event_index  # First event removed
            False
            >>> id2 in store2.event_index and id3 in store2.event_index
            True
        """
        # Get or create ring buffer for this stream
        buffer = self.streams.get(stream_id)
        if buffer is None:
            buffer = StreamBuffer(entries=[None] * self.max_events_per_stream)
            self.streams[stream_id] = buffer

        # Assign per-stream sequence number
        seq_num = buffer.next_seq
        buffer.next_seq += 1
        idx = seq_num % self.max_events_per_stream

        # Handle eviction if buffer is full
        if buffer.count == self.max_events_per_stream:
            evicted = buffer.entries[idx]
            if evicted is not None:
                self.event_index.pop(evicted.event_id, None)
            buffer.start_seq += 1
        else:
            if buffer.count == 0:
                buffer.start_seq = seq_num
            buffer.count += 1

        # Create and store the new event entry
        event_id = str(uuid4())
        event_entry = EventEntry(event_id=event_id, stream_id=stream_id, message=message, seq_num=seq_num)
        buffer.entries[idx] = event_entry
        self.event_index[event_id] = event_entry

        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> Union[StreamId, None]:
        """
        Replays events that occurred after the specified event ID.

        Uses O(1) lookup via event_index and O(k) replay where k is the number
        of events to replay, avoiding the previous O(n) full scan.

        Args:
            last_event_id (EventId): The ID of the last received event. Replay starts after this event.
            send_callback (EventCallback): Async callback to send each replayed event.

        Returns:
            StreamId | None: The stream ID if the event is found and replayed, otherwise None.

        Examples:
            >>> # Test replaying events
            >>> import asyncio
            >>> from mcp.types import JSONRPCMessage
            >>> store = InMemoryEventStore()
            >>> message1 = JSONRPCMessage(jsonrpc="2.0", method="test1", id=1)
            >>> message2 = JSONRPCMessage(jsonrpc="2.0", method="test2", id=2)
            >>> message3 = JSONRPCMessage(jsonrpc="2.0", method="test3", id=3)
            >>>
            >>> # Store events
            >>> event_id1 = asyncio.run(store.store_event("stream-1", message1))
            >>> event_id2 = asyncio.run(store.store_event("stream-1", message2))
            >>> event_id3 = asyncio.run(store.store_event("stream-1", message3))
            >>>
            >>> # Test replay after first event
            >>> replayed_events = []
            >>> async def mock_callback(event_message):
            ...     replayed_events.append(event_message)
            >>>
            >>> result = asyncio.run(store.replay_events_after(event_id1, mock_callback))
            >>> result
            'stream-1'
            >>> len(replayed_events)
            2

            >>> # Test replay with non-existent event
            >>> result = asyncio.run(store.replay_events_after("non-existent", mock_callback))
            >>> result is None
            True
        """
        # O(1) lookup in event_index
        last_event = self.event_index.get(last_event_id)
        if last_event is None:
            logger.warning("Event ID %s not found in store", last_event_id)
            return None

        buffer = self.streams.get(last_event.stream_id)
        if buffer is None:
            return None

        # Validate that the event's seq_num is still within the buffer range
        if last_event.seq_num < buffer.start_seq or last_event.seq_num >= buffer.next_seq:
            return None

        # O(k) replay: iterate from last_event.seq_num + 1 to buffer.next_seq - 1
        for seq in range(last_event.seq_num + 1, buffer.next_seq):
            entry = buffer.entries[seq % self.max_events_per_stream]
            # Guard: skip if slot is empty or has been overwritten by a different seq
            if entry is None or entry.seq_num != seq:
                continue
            await send_callback(EventMessage(entry.message, entry.event_id))

        return last_event.stream_id


class RustEventStore(EventStore):
    """Rust-backed event store that delegates resumable stream state to the sidecar."""

    def __init__(self, max_events_per_stream: int = 100, ttl: int = 3600, key_prefix: str = _RUST_EVENT_STORE_DEFAULT_KEY_PREFIX):
        """Initialize the Rust-backed event store wrapper.

        Args:
            max_events_per_stream: Maximum number of events retained per stream.
            ttl: Event retention time in seconds.
            key_prefix: Redis key prefix shared with the Rust sidecar.
        """
        self.max_events_per_stream = max_events_per_stream
        self.ttl = ttl
        self.key_prefix = key_prefix.rstrip(":")

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        """Store an event in the Rust-backed resumable event store.

        Args:
            stream_id: Stream that owns the event.
            message: JSON-RPC payload to persist for replay.

        Returns:
            The generated event identifier returned by the Rust sidecar.

        Raises:
            RuntimeError: If the Rust sidecar event store is unavailable or returns invalid data.
        """
        client = await _get_rust_event_store_client()
        message_dict = None if message is None else (message.model_dump() if hasattr(message, "model_dump") else dict(message))
        response = await client.post(
            _build_rust_runtime_internal_url("/_internal/event-store/store"),
            json={
                "streamId": stream_id,
                "message": message_dict,
                "keyPrefix": self.key_prefix,
                "maxEventsPerStream": self.max_events_per_stream,
                "ttlSeconds": self.ttl,
            },
            timeout=httpx.Timeout(settings.experimental_rust_mcp_runtime_timeout_seconds),
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        event_id = payload.get("eventId")
        if not isinstance(event_id, str) or not event_id:
            raise RuntimeError("Rust event store returned an invalid eventId")
        return event_id

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> Union[StreamId, None]:
        """Replay events newer than ``last_event_id`` through the provided callback.

        Args:
            last_event_id: Last event acknowledged by the reconnecting client.
            send_callback: Callback invoked for each replayed event payload.

        Returns:
            The associated stream identifier when replay succeeds, else ``None``.
        """
        client = await _get_rust_event_store_client()
        response = await client.post(
            _build_rust_runtime_internal_url("/_internal/event-store/replay"),
            json={
                "lastEventId": last_event_id,
                "keyPrefix": self.key_prefix,
            },
            timeout=httpx.Timeout(settings.experimental_rust_mcp_runtime_timeout_seconds),
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        stream_id = payload.get("streamId")
        if not isinstance(stream_id, str) or not stream_id:
            return None
        for event in payload.get("events", []):
            if not isinstance(event, dict):
                continue
            await send_callback(event.get("message"))
        return stream_id


async def _get_rust_event_store_client() -> httpx.AsyncClient:
    """Return the HTTP client used for Python -> Rust event-store calls.

    Returns:
        An async HTTP client configured for Rust event-store access.
    """
    global _rust_event_store_client  # pylint: disable=global-statement

    uds_path = settings.experimental_rust_mcp_runtime_uds
    if not uds_path:
        return await get_http_client()

    if _rust_event_store_client is not None:
        return _rust_event_store_client

    async with _rust_event_store_client_lock:
        if _rust_event_store_client is None:
            _rust_event_store_client = httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=uds_path),
                limits=get_http_limits(),
                timeout=httpx.Timeout(settings.experimental_rust_mcp_runtime_timeout_seconds),
                follow_redirects=False,
            )
        return _rust_event_store_client


def _build_rust_runtime_internal_url(path: str) -> str:
    """Build a Rust sidecar internal URL for UDS or loopback HTTP transport.

    Args:
        path: Internal Rust runtime path to append to the configured base URL.

    Returns:
        Absolute URL targeting the Rust sidecar over HTTP or UDS-backed transport.
    """
    base = urlsplit(settings.experimental_rust_mcp_runtime_url)
    base_path = base.path.rstrip("/")
    target_path = f"{base_path}{path}" if base_path else path
    return urlunsplit((base.scheme, base.netloc, target_path, "", ""))


# ------------------------------ Streamable HTTP Transport ------------------------------


@asynccontextmanager
async def get_db() -> AsyncGenerator[Session, Any]:
    """
    Asynchronous context manager for database sessions.

    Commits the transaction on successful completion to avoid implicit rollbacks
    for read-only operations. Rolls back explicitly on exception. Handles
    asyncio.CancelledError explicitly to prevent transaction leaks when MCP
    handlers are cancelled (client disconnect, timeout, etc.).

    Yields:
        A database session instance from SessionLocal.
        Ensures the session is closed after use.

    Raises:
        asyncio.CancelledError: Re-raised after rollback and close on task cancellation.
        Exception: Re-raises any exception after rolling back the transaction.

    Examples:
        >>> # Test database context manager
        >>> import asyncio
        >>> async def test_db():
        ...     async with get_db() as db:
        ...         return db is not None
        >>> result = asyncio.run(test_db())
        >>> result
        True
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except asyncio.CancelledError:
        # Handle cancellation explicitly to prevent transaction leaks.
        # When MCP handlers are cancelled (client disconnect, timeout, etc.),
        # we must rollback and close the session before re-raising.
        try:
            db.rollback()
        except Exception:
            pass  # nosec B110 - Best effort rollback on cancellation
        try:
            db.close()
        except Exception:
            pass  # nosec B110 - Best effort close on cancellation
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass  # nosec B110 - Best effort cleanup on connection failure
        raise
    finally:
        db.close()


def get_user_email_from_context() -> str:
    """Extract user email from the current user context.

    Returns:
        User email address or 'unknown' if not available
    """
    user = user_context_var.get()
    if isinstance(user, dict):
        # First try 'email', then 'sub' (JWT standard claim)
        return user.get("email") or user.get("sub") or "unknown"
    return str(user) if user else "unknown"


def _should_enforce_streamable_rbac(user_context: Optional[dict[str, Any]]) -> bool:
    """Return True when request originated from authenticated Streamable HTTP middleware.

    Direct unit tests may call MCP handlers without middleware context; those
    invocations should preserve historical behavior and avoid forced RBAC checks.

    Args:
        user_context: Request user context propagated by Streamable HTTP auth middleware.

    Returns:
        bool: ``True`` when permission checks should be enforced for this request.
    """
    return isinstance(user_context, dict) and user_context.get("is_authenticated", False) is True


def _build_resource_metadata_url(scope: Scope, server_id: str) -> str:
    """Construct the RFC 9728 OAuth Protected Resource Metadata URL from ASGI scope.

    Inspects ``x-forwarded-proto`` and ``host`` headers first (reverse-proxy
    scenario), then falls back to ``scope["scheme"]`` and ``scope["server"]``.
    Includes ``scope["root_path"]`` so that deployments behind a reverse proxy
    with a path prefix emit the correct public URL.

    Args:
        scope: ASGI connection scope.
        server_id: Virtual-server identifier.

    Returns:
        Fully-qualified URL string, or ``""`` if construction fails.
    """
    try:
        headers = Headers(scope=scope)
        forwarded_proto = headers.get("x-forwarded-proto")
        if forwarded_proto:
            proto = forwarded_proto.split(",")[0].strip().lower()
        else:
            proto = scope.get("scheme", "https")
        if proto not in ("http", "https"):
            proto = "https"

        host = headers.get("host")
        if not host:
            server_tuple = scope.get("server")
            if server_tuple:
                host_addr, port = server_tuple
                # Wrap IPv6 addresses in brackets per RFC 2732
                if ":" in str(host_addr):
                    host_addr = f"[{host_addr}]"
                default_port = 443 if proto == "https" else 80
                host = f"{host_addr}:{port}" if port != default_port else host_addr
            else:
                return ""

        root_path = scope.get("root_path", "").rstrip("/")
        return f"{proto}://{host}{root_path}/.well-known/oauth-protected-resource/servers/{server_id}/mcp"
    except Exception:
        return ""


async def _check_server_oauth_enforcement(server_id: str, user_context: Optional[dict[str, Any]]) -> None:
    """Reject unauthenticated callers when a server requires OAuth.

    Looks up the server's ``oauth_enabled`` flag and raises
    ``OAuthRequiredError`` when the flag is set but the caller is not
    authenticated.  This closes the gap where OAuth capability is
    *advertised* (via RFC 9728 ``experimental.oauth``) but never
    *enforced* on subsequent MCP requests.

    The result is cached in ``_oauth_checked_var`` for the lifetime of
    the request so that handler-level defense-in-depth calls do not
    repeat the DB query already performed by the middleware.

    .. note::
        SSE transport is not covered here because it already requires
        authentication unconditionally.

    Args:
        server_id: Virtual-server identifier extracted from the URL path.
        user_context: User context set by ``streamable_http_auth`` middleware.

    Raises:
        OAuthRequiredError: When the server requires OAuth and the caller has
            not provided valid authentication credentials.
        OAuthEnforcementUnavailableError: When the database or session is
            unavailable and the server's ``oauth_enabled`` flag cannot be
            verified (fail-closed).
    """
    if _oauth_checked_var.get(False):
        return  # Already checked during this request

    if not server_id or server_id == "default_server_id":
        return  # No server context — nothing to enforce

    is_authenticated = (user_context or {}).get("is_authenticated", False)
    if is_authenticated:
        _oauth_checked_var.set(True)
        return  # Already authenticated — no need to check

    # Lazy DB lookup to avoid import-time side-effects
    # Third-Party
    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

    # First-Party
    from mcpgateway.db import Server as DbServer  # pylint: disable=import-outside-toplevel

    try:
        async with get_db() as db:
            server = db.execute(select(DbServer).where(DbServer.id == server_id)).scalar_one_or_none()
            if server and server.oauth_enabled:
                logger.warning("OAuth required for server %s but caller is unauthenticated", server_id)
                raise OAuthRequiredError(
                    "This server requires OAuth authentication. Please provide a valid access token.",
                    server_id=server_id,
                )
            _oauth_checked_var.set(True)
    except SQLAlchemyError as exc:
        # DB lookup failure — fail-closed for security.
        logger.error("OAuth enforcement DB lookup failed for server %s: %s", server_id, exc)
        raise OAuthEnforcementUnavailableError(
            f"Unable to verify OAuth requirements for server {server_id}",
            server_id=server_id,
        ) from exc


async def _check_streamable_permission(
    *,
    user_context: dict[str, Any],
    permission: str,
    allow_admin_bypass: bool = True,
    check_any_team: bool = False,
) -> bool:
    """Evaluate RBAC permission for a Streamable HTTP request context.

    Args:
        user_context: Authenticated user context from Streamable HTTP middleware.
        permission: Permission name to evaluate (for example ``tools.execute``).
        allow_admin_bypass: Whether unrestricted admin tokens can bypass team checks.
        check_any_team: Whether any matching team grants permission.

    Returns:
        bool: ``True`` when the caller is authorized for ``permission``.
    """
    user_email = user_context.get("email")
    if not user_email:
        return False

    try:
        async with get_db() as db:
            permission_service = PermissionService(db)
            granted = await permission_service.check_permission(
                user_email=user_email,
                permission=permission,
                token_teams=user_context.get("teams"),
                allow_admin_bypass=allow_admin_bypass,
                check_any_team=check_any_team,
            )
            if not granted:
                logger.warning("Streamable HTTP RBAC denied: user=%s, permission=%s", user_email, permission)
            return granted
    except Exception as exc:
        logger.warning("Streamable HTTP RBAC check failed for %s / %s: %s", user_email, permission, exc)
        return False


def _check_scoped_permission(user_context: dict[str, Any], permission: str) -> bool:
    """Check if token scoped permissions allow this operation.

    Args:
        user_context: User context dict (may contain 'scoped_permissions' key).
        permission: Permission to check.

    Returns:
        True if allowed (no scope cap, wildcard, or permission present).
    """
    scoped = user_context.get("scoped_permissions")
    if not scoped:  # None or empty list = defer to RBAC
        return True
    if "*" in scoped:
        return True
    allowed = permission in scoped
    if not allowed:
        logger.warning("Streamable HTTP token scope denied: user=%s, required=%s", user_context.get("email"), permission)
    return allowed


def _check_any_team_for_server_scoped_rbac(user_context: dict[str, Any] | None, server_id: str | None) -> bool:
    """Return whether Streamable HTTP RBAC should check across team-scoped roles.

    Server-scoped MCP routes (``/servers/<id>/mcp``) should authorize team-bound
    callers against the specific virtual server context. Session tokens already do
    this via ``check_any_team=True`` because they have no single explicit team_id.
    Team-scoped API tokens need the same treatment on server-scoped routes; otherwise
    they are evaluated only in global scope and incorrectly denied.

    Args:
        user_context: Current authenticated MCP user context, if any.
        server_id: Effective virtual server identifier for the MCP request.

    Returns:
        ``True`` when RBAC should search across the caller's token teams.
    """
    if not user_context:
        return False
    if user_context.get("token_use") == "session":
        return True
    return bool(server_id) and bool(user_context.get("teams"))


def set_shared_session_registry(session_registry: Any) -> None:
    """Set the process-wide session registry used by Streamable HTTP helpers.

    Args:
        session_registry: Registry instance created by application bootstrap.
    """
    global _shared_session_registry  # pylint: disable=global-statement
    _shared_session_registry = session_registry


def _get_shared_session_registry() -> Optional[Any]:
    """Return the process-wide session registry reference.

    Returns:
        Optional[Any]: Session registry instance, or ``None`` when unavailable.
    """
    return _shared_session_registry


async def _claim_streamable_session_owner(session_id: str, owner_email: str) -> Optional[str]:
    """Claim or resolve the logical owner for a Streamable HTTP session.

    Args:
        session_id: Logical MCP session identifier to claim.
        owner_email: Caller email that should own the session.

    Returns:
        Optional[str]: Effective owner email after claim, or ``None`` if unavailable.
    """
    if not session_id or not owner_email:
        return None

    session_registry = _get_shared_session_registry()
    if session_registry is None:
        return None

    try:
        return await session_registry.claim_session_owner(session_id, owner_email)
    except Exception as exc:
        logger.warning("Failed to claim session owner for %s: %s", session_id, exc)
        return None


async def _validate_streamable_session_access(
    *,
    mcp_session_id: Optional[str],
    user_context: Optional[dict[str, Any]],
    rpc_method: Optional[str] = None,
) -> tuple[bool, int, str]:
    """Authorize access to a stateful Streamable HTTP session identifier.

    Args:
        mcp_session_id: Session identifier from request headers.
        user_context: Authenticated user context for the current request.
        rpc_method: JSON-RPC method name when available.

    Returns:
        Tuple ``(allowed, deny_status_code, deny_message)``.
    """
    if not settings.use_stateful_sessions:
        return True, 200, ""

    if not mcp_session_id or mcp_session_id == "not-provided":
        return True, 200, ""

    if not _should_enforce_streamable_rbac(user_context):
        return True, 200, ""

    if isinstance(user_context, dict) and user_context.get("_rust_session_validated") is True:
        return True, 200, ""

    # Initialize establishes a new session and is authorized separately.
    if (rpc_method or "").strip() == "initialize":
        return True, 200, ""

    requester_email = user_context.get("email") if isinstance(user_context, dict) else None
    requester_is_admin = bool(user_context.get("is_admin", False)) if isinstance(user_context, dict) else False

    session_registry = _get_shared_session_registry()
    if session_registry is None:
        return False, HTTP_403_FORBIDDEN, "Session ownership unavailable"

    try:
        session_owner = await session_registry.get_session_owner(mcp_session_id)
    except Exception as exc:
        logger.warning("Failed to get session owner for %s: %s", mcp_session_id, exc)
        return False, HTTP_403_FORBIDDEN, "Session ownership unavailable"

    if session_owner:
        if requester_is_admin:
            return True, 200, ""
        if requester_email and requester_email == session_owner:
            return True, 200, ""
        return False, HTTP_403_FORBIDDEN, "Session access denied"

    try:
        session_exists = await session_registry.session_exists(mcp_session_id)
    except Exception as exc:
        logger.warning("Failed to check session existence for %s: %s", mcp_session_id, exc)
        return False, HTTP_403_FORBIDDEN, "Session ownership unavailable"

    if session_exists is False:
        return False, HTTP_404_NOT_FOUND, "Session not found"
    return False, HTTP_403_FORBIDDEN, "Session owner metadata unavailable"


async def _proxy_list_tools_to_gateway(gateway: Any, request_headers: dict, user_context: dict, meta: Optional[Any] = None) -> List[types.Tool]:  # pylint: disable=unused-argument
    """Proxy tools/list request directly to remote MCP gateway using MCP SDK.

    Args:
        gateway: Gateway ORM instance
        request_headers: Request headers from client
        user_context: User context (not used - _meta comes from MCP SDK)
        meta: Request metadata (_meta) from the original request

    Returns:
        List of Tool objects from remote server
    """
    try:
        # Prepare headers with gateway auth
        headers = build_gateway_auth_headers(gateway)

        # Forward passthrough headers if configured
        if gateway.passthrough_headers and request_headers:
            for header_name in gateway.passthrough_headers:
                header_value = request_headers.get(header_name.lower()) or request_headers.get(header_name)
                if header_value:
                    headers[header_name] = header_value

        # Use MCP SDK to connect and list tools
        async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Prepare params with _meta if provided
                params = None
                if meta:
                    params = PaginatedRequestParams(_meta=meta)
                    logger.debug("Forwarding _meta to remote gateway: %s", meta)

                # List tools with _meta forwarded
                result = await session.list_tools(params=params)
                return result.tools

    except Exception as e:
        logger.exception("Error proxying tools/list to gateway %s: %s", gateway.id, e)
        return []


async def _proxy_list_resources_to_gateway(gateway: Any, request_headers: dict, user_context: dict, meta: Optional[Any] = None) -> List[types.Resource]:  # pylint: disable=unused-argument
    """Proxy resources/list request directly to remote MCP gateway using MCP SDK.

    Args:
        gateway: Gateway ORM instance
        request_headers: Request headers from client
        user_context: User context (not used - _meta comes from MCP SDK)
        meta: Request metadata (_meta) from the original request

    Returns:
        List of Resource objects from remote server
    """
    try:
        # Prepare headers with gateway auth
        headers = build_gateway_auth_headers(gateway)

        # Forward passthrough headers if configured
        if gateway.passthrough_headers and request_headers:
            for header_name in gateway.passthrough_headers:
                header_value = request_headers.get(header_name.lower()) or request_headers.get(header_name)
                if header_value:
                    headers[header_name] = header_value

        logger.info("Proxying resources/list to gateway %s at %s", gateway.id, gateway.url)
        if meta:
            logger.debug("Forwarding _meta to remote gateway: %s", meta)

        # Use MCP SDK to connect and list resources
        async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Prepare params with _meta if provided
                params = None
                if meta:
                    params = PaginatedRequestParams(_meta=meta)
                    logger.debug("Forwarding _meta to remote gateway: %s", meta)

                # List resources with _meta forwarded
                result = await session.list_resources(params=params)

                logger.info("Received %s resources from gateway %s", len(result.resources), gateway.id)
                return result.resources

    except Exception as e:
        logger.exception("Error proxying resources/list to gateway %s: %s", gateway.id, e)
        return []


async def _proxy_read_resource_to_gateway(gateway: Any, resource_uri: str, user_context: dict, meta: Optional[Any] = None) -> List[Any]:  # pylint: disable=unused-argument
    """Proxy resources/read request directly to remote MCP gateway using MCP SDK.

    Args:
        gateway: Gateway ORM instance
        resource_uri: URI of the resource to read
        user_context: User context (not used - auth comes from gateway config)
        meta: Request metadata (_meta) from the original request

    Returns:
        List of content objects (TextResourceContents or BlobResourceContents) from remote server
    """
    try:
        # Prepare headers with gateway auth
        headers = build_gateway_auth_headers(gateway)

        # Get request headers
        request_headers = request_headers_var.get()

        # Forward X-Context-Forge-Gateway-Id header
        gw_id = extract_gateway_id_from_headers(request_headers)
        if gw_id:
            headers[GATEWAY_ID_HEADER] = gw_id

        # Forward passthrough headers if configured
        if gateway.passthrough_headers and request_headers:
            for header_name in gateway.passthrough_headers:
                header_value = request_headers.get(header_name.lower()) or request_headers.get(header_name)
                if header_value:
                    headers[header_name] = header_value

        logger.info("Proxying resources/read for %s to gateway %s at %s", resource_uri, gateway.id, gateway.url)
        if meta:
            logger.debug("Forwarding _meta to remote gateway: %s", meta)

        # Use MCP SDK to connect and read resource
        async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Prepare request params with _meta if provided
                if meta:
                    # Create params and inject _meta
                    request_params = ReadResourceRequestParams(uri=resource_uri)
                    request_params_dict = request_params.model_dump()
                    request_params_dict["_meta"] = meta

                    # Send request with _meta
                    result = await session.send_request(
                        types.ClientRequest(ReadResourceRequest(params=ReadResourceRequestParams.model_validate(request_params_dict))),
                        types.ReadResourceResult,
                    )
                else:
                    # No _meta, use simple read_resource
                    result = await session.read_resource(uri=resource_uri)

                logger.info("Received %s content items from gateway %s for resource %s", len(result.contents), gateway.id, resource_uri)
                return result.contents

    except Exception as e:
        logger.exception("Error proxying resources/read to gateway %s for resource %s: %s", gateway.id, resource_uri, e)
        return []


@mcp_app.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict) -> Union[
    types.CallToolResult,
    List[Union[types.TextContent, types.ImageContent, types.AudioContent, types.ResourceLink, types.EmbeddedResource]],
    Tuple[List[Union[types.TextContent, types.ImageContent, types.AudioContent, types.ResourceLink, types.EmbeddedResource]], Dict[str, Any]],
]:
    """
    Handles tool invocation via the MCP Server.

    Note: validate_input=False disables the MCP SDK's built-in JSON Schema validation.
    This is necessary because the SDK uses jsonschema.validate() which internally calls
    check_schema() with the default validator. Schemas using older draft features
    (e.g., Draft 4 style exclusiveMinimum: true) fail this validation. The gateway
    handles schema validation separately in tool_service.py with multi-draft support.

    This function supports the MCP protocol's tool calling with structured content validation.
    In direct_proxy mode, returns the raw CallToolResult from the remote server.
    In normal mode, converts ToolResult to CallToolResult with content normalization.

    Args:
        name (str): The name of the tool to invoke.
        arguments (dict): A dictionary of arguments to pass to the tool.

    Returns:
        types.CallToolResult: MCP SDK CallToolResult with content and optional structuredContent.

    Raises:
        PermissionError: If the caller lacks ``tools.execute`` permission.
        Exception: Re-raised after logging to allow MCP SDK to convert to JSON-RPC error response.

    Examples:
        >>> # Test call_tool function signature
        >>> import inspect
        >>> sig = inspect.signature(call_tool)
        >>> list(sig.parameters.keys())
        ['name', 'arguments']
        >>> sig.parameters['name'].annotation
        <class 'str'>
        >>> sig.parameters['arguments'].annotation
        <class 'dict'>
    """
    server_id, request_headers, user_context = await _get_request_context_or_default()

    meta_data = None
    # Extract _meta from request context if available
    try:
        ctx = mcp_app.request_context
        if ctx and ctx.meta is not None:
            meta_data = ctx.meta.model_dump()
    except LookupError:
        # request_context might not be active in some edge cases (e.g. tests)
        logger.debug("No active request context found")

    # Extract authorization parameters from user context (same pattern as list_tools)
    user_email = user_context.get("email") if user_context else None
    token_teams = user_context.get("teams") if user_context else None
    is_admin = user_context.get("is_admin", False) if user_context else False

    # Admin bypass - only when token has NO team restrictions (token_teams is None)
    # If token has explicit team scope (even empty [] for public-only), respect it
    if is_admin and token_teams is None:
        user_email = None
        # token_teams stays None (unrestricted)
    elif token_teams is None:
        token_teams = []  # Non-admin without teams = public-only (secure default)

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    if _should_enforce_streamable_rbac(user_context):
        # Layer 1: Token scope cap
        if not _check_scoped_permission(user_context, "tools.execute"):
            raise PermissionError(_ACCESS_DENIED_MSG)
        # Layer 2: RBAC check
        # Session tokens have no explicit team_id; check across all team-scoped roles.
        # Mirrors the @require_permission decorator's check_any_team fallback (rbac.py:562-576).
        has_execute_permission = await _check_streamable_permission(
            user_context=user_context,
            permission="tools.execute",
            check_any_team=_check_any_team_for_server_scoped_rbac(user_context, server_id),
        )
        if not has_execute_permission:
            raise PermissionError(_ACCESS_DENIED_MSG)

    # Check if we're in direct_proxy mode by looking for X-Context-Forge-Gateway-Id header
    gateway_id_from_header = extract_gateway_id_from_headers(request_headers)

    # If X-Context-Forge-Gateway-Id header is present, use direct proxy mode
    if gateway_id_from_header:
        try:  # Check if this gateway is in direct_proxy mode
            async with get_db() as check_db:
                # Third-Party
                from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                gateway = check_db.execute(select(DbGateway).where(DbGateway.id == gateway_id_from_header)).scalar_one_or_none()
                if gateway and getattr(gateway, "gateway_mode", "cache") == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                    # SECURITY: Check gateway access before allowing direct proxy
                    if not await check_gateway_access(check_db, gateway, user_email, token_teams):
                        logger.warning("Access denied to gateway %s in direct_proxy mode for user %s", gateway_id_from_header, user_email)
                        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Tool not found: {name}")], isError=True)

                    logger.info("Using direct_proxy mode for tool '%s' via gateway %s", name, gateway_id_from_header)

                    # Use direct proxy method - returns raw CallToolResult from remote server
                    # Return it directly without any normalization
                    return await tool_service.invoke_tool_direct(
                        gateway_id=gateway_id_from_header,
                        name=name,
                        arguments=arguments,
                        request_headers=request_headers,
                        meta_data=meta_data,
                        user_email=user_email,
                        token_teams=token_teams,
                    )
        except Exception as e:
            logger.error("Direct proxy mode failed for gateway %s: %s", gateway_id_from_header, e)
            return types.CallToolResult(content=[types.TextContent(type="text", text="Direct proxy tool invocation failed")], isError=True)

    # Normal mode: use standard tool invocation with normalization
    # Use the already-recovered user_context (works for both ContextVar and stateful session paths)
    app_user_email = (user_context.get("email") or user_context.get("sub") or "unknown") if user_context else "unknown"

    # Multi-worker session affinity: check if we should forward to another worker
    # Check both x-mcp-session-id (internal/forwarded) and mcp-session-id (client protocol header)
    mcp_session_id = None
    if request_headers:
        request_headers_lower = {k.lower(): v for k, v in request_headers.items()}
        mcp_session_id = request_headers_lower.get("x-mcp-session-id") or request_headers_lower.get("mcp-session-id")
    if settings.mcpgateway_session_affinity_enabled and mcp_session_id:
        try:
            # First-Party
            from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache  # pylint: disable=import-outside-toplevel
            from mcpgateway.services.mcp_session_pool import get_mcp_session_pool  # pylint: disable=import-outside-toplevel
            from mcpgateway.services.mcp_session_pool import MCPSessionPool  # pylint: disable=import-outside-toplevel

            if not MCPSessionPool.is_valid_mcp_session_id(mcp_session_id):
                logger.debug("Invalid MCP session id for Streamable HTTP tool affinity, executing locally")
                raise RuntimeError("invalid mcp session id")

            pool = get_mcp_session_pool()

            # Register session mapping BEFORE checking forwarding (same pattern as SSE)
            # This ensures ownership is registered atomically so forward_request_to_owner() works
            try:
                cached = await tool_lookup_cache.get(name)
                if cached and cached.get("status") == "active":
                    gateway_info = cached.get("gateway")
                    if gateway_info:
                        url = gateway_info.get("url")
                        gateway_id = gateway_info.get("id", "")
                        transport_type = gateway_info.get("transport", "streamablehttp")
                        if url:
                            await pool.register_session_mapping(mcp_session_id, url, gateway_id, transport_type, user_email)
            except Exception as e:
                logger.error("Failed to pre-register session mapping for Streamable HTTP: %s", e)

            forwarded_response = await pool.forward_request_to_owner(
                mcp_session_id,
                {"method": "tools/call", "params": {"name": name, "arguments": arguments, "_meta": meta_data}, "headers": dict(request_headers) if request_headers else {}},
            )
            if forwarded_response is not None:
                # Request was handled by another worker - convert response to expected format
                if "error" in forwarded_response:
                    raise Exception(forwarded_response["error"].get("message", "Forwarded request failed"))  # pylint: disable=broad-exception-raised
                result_data = forwarded_response.get("result", {})

                def _rehydrate_content_items(items: Any) -> list[types.TextContent | types.ImageContent | types.AudioContent | types.ResourceLink | types.EmbeddedResource]:
                    """Convert forwarded tool result items back to MCP content types.

                    Args:
                        items: List of content item dicts from forwarded response.

                    Returns:
                        List of validated MCP content type instances.
                    """
                    if not isinstance(items, list):
                        return []
                    converted: list[types.TextContent | types.ImageContent | types.AudioContent | types.ResourceLink | types.EmbeddedResource] = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get("type")
                        try:
                            if item_type == "text":
                                converted.append(types.TextContent.model_validate(item))
                            elif item_type == "image":
                                converted.append(types.ImageContent.model_validate(item))
                            elif item_type == "audio":
                                converted.append(types.AudioContent.model_validate(item))
                            elif item_type == "resource_link":
                                converted.append(types.ResourceLink.model_validate(item))
                            elif item_type == "resource":
                                converted.append(types.EmbeddedResource.model_validate(item))
                            else:
                                converted.append(types.TextContent(type="text", text=item if isinstance(item, str) else orjson.dumps(item).decode()))
                        except Exception:
                            converted.append(types.TextContent(type="text", text=item if isinstance(item, str) else orjson.dumps(item).decode()))
                    return converted

                unstructured = _rehydrate_content_items(result_data.get("content", []))
                structured = result_data.get("structuredContent") or result_data.get("structured_content")
                if structured:
                    return (unstructured, structured)
                return unstructured
        except RuntimeError:
            # Pool not initialized - execute locally
            pass

    try:
        async with get_db() as db:
            # Use tool service for all tool invocations (handles direct_proxy internally)
            result = await tool_service.invoke_tool(
                db=db,
                name=name,
                arguments=arguments,
                request_headers=request_headers,
                app_user_email=app_user_email,
                user_email=user_email,
                token_teams=token_teams,
                server_id=server_id,
                meta_data=meta_data,
            )
            if not result or not result.content:
                logger.warning("No content returned by tool: %s", name)
                return []

            # Normalize unstructured content to MCP SDK types, preserving metadata (annotations, _meta, size)
            # Helper to convert gateway Annotations to dict for MCP SDK compatibility
            # (mcpgateway.common.models.Annotations != mcp.types.Annotations)
            def _convert_annotations(ann: Any) -> dict[str, Any] | None:
                """Convert gateway Annotations to dict for MCP SDK compatibility.

                Args:
                    ann: Gateway Annotations object, dict, or None.

                Returns:
                    Dict representation of annotations, or None.
                """
                if ann is None:
                    return None
                if isinstance(ann, dict):
                    return ann
                if hasattr(ann, "model_dump"):
                    return ann.model_dump(by_alias=True, mode="json")
                return None

            def _convert_meta(meta: Any) -> dict[str, Any] | None:
                """Convert gateway meta to dict for MCP SDK compatibility.

                Args:
                    meta: Gateway meta object, dict, or None.

                Returns:
                    Dict representation of meta, or None.
                """
                if meta is None:
                    return None
                if isinstance(meta, dict):
                    return meta
                if hasattr(meta, "model_dump"):
                    return meta.model_dump(by_alias=True, mode="json")
                return None

            unstructured: list[types.TextContent | types.ImageContent | types.AudioContent | types.ResourceLink | types.EmbeddedResource] = []
            for content in result.content:
                if content.type == "text":
                    unstructured.append(
                        types.TextContent(
                            type="text",
                            text=content.text,
                            annotations=_convert_annotations(getattr(content, "annotations", None)),
                            _meta=_convert_meta(getattr(content, "meta", None)),
                        )
                    )
                elif content.type == "image":
                    unstructured.append(
                        types.ImageContent(
                            type="image",
                            data=content.data,
                            mimeType=content.mime_type,
                            annotations=_convert_annotations(getattr(content, "annotations", None)),
                            _meta=_convert_meta(getattr(content, "meta", None)),
                        )
                    )
                elif content.type == "audio":
                    unstructured.append(
                        types.AudioContent(
                            type="audio",
                            data=content.data,
                            mimeType=content.mime_type,
                            annotations=_convert_annotations(getattr(content, "annotations", None)),
                            _meta=_convert_meta(getattr(content, "meta", None)),
                        )
                    )
                elif content.type == "resource_link":
                    unstructured.append(
                        types.ResourceLink(
                            type="resource_link",
                            uri=content.uri,
                            name=content.name,
                            description=getattr(content, "description", None),
                            mimeType=getattr(content, "mime_type", None),
                            size=getattr(content, "size", None),
                            _meta=_convert_meta(getattr(content, "meta", None)),
                        )
                    )
                elif content.type == "resource":
                    # EmbeddedResource - pass through the model dump as the MCP SDK type requires complex nested structure
                    unstructured.append(types.EmbeddedResource.model_validate(content.model_dump(by_alias=True, mode="json")))
                else:
                    # Unknown content type - convert to text representation
                    unstructured.append(types.TextContent(type="text", text=orjson.dumps(content.model_dump(by_alias=True, mode="json")).decode()))

            # If the tool produced structured content (ToolResult.structured_content / structuredContent),
            # return a combination (unstructured, structured) so the server can validate against outputSchema.
            # The ToolService may populate structured_content (snake_case) or the model may expose
            # an alias 'structuredContent' when dumped via model_dump(by_alias=True).
            structured = None
            try:
                # Prefer attribute if present
                structured = getattr(result, "structured_content", None)
            except Exception:
                structured = None

            # Fallback to by-alias dump (in case the result is a pydantic model with alias fields)
            if structured is None:
                try:
                    structured = result.model_dump(by_alias=True).get("structuredContent") if hasattr(result, "model_dump") else None
                except Exception:
                    structured = None

            if structured:
                return (unstructured, structured)

            return unstructured
    except Exception as e:
        logger.exception("Error calling tool '%s': %s", name, e)
        # Re-raise the exception so the MCP SDK can properly convert it to an error response
        # This ensures error details are propagated to the client instead of returning empty results
        raise


async def _get_request_context_or_default() -> Tuple[str, dict[str, Any], dict[str, Any]]:
    """Retrieves request context information for the current execution.

    This function resolves request context using the following precedence:

    1. Context variables (fast path). Used when the handler executes in the
       same async context as the middleware (for example, direct ASGI dispatch).
    2. ASGI scope. The middleware stores resolved context on
       ``scope[_MCPGATEWAY_CONTEXT_KEY]`` before handing off to the MCP SDK.
       Because the SDK passes the same ``scope`` dictionary through to
       ``mcp_app.request_context.request``, this survives task-group
       boundaries where ContextVars may be lost.
    3. Re-authentication fallback. Re-extracts identity from the request's
       Authorization header or cookies. This is the most expensive path and
       may produce a different context shape for anonymous callers (an empty
       dictionary instead of the middleware's canonical
       ``{"is_authenticated": False, ...}`` structure).

    Returns:
        Tuple[str, dict[str, Any], dict[str, Any]]: A tuple containing:

            - server_id: The resolved server identifier.
            - request_headers: The request headers as a dictionary.
            - user_context: The resolved user context dictionary.
    """
    # 1. Try context vars first (fast path)
    s_id = server_id_var.get()

    # Check if context vars are populated with real data (not defaults)
    if s_id != "default_server_id":
        return s_id, request_headers_var.get(), user_context_var.get()

    # 2. Try ASGI scope context injected by handle_streamable_http()
    ctx = None
    try:
        ctx = mcp_app.request_context
        request = ctx.request
        if request:
            gw_ctx = getattr(request, "scope", {}).get(_MCPGATEWAY_CONTEXT_KEY)
            if isinstance(gw_ctx, dict):
                return (
                    gw_ctx.get("server_id") or s_id,
                    gw_ctx.get("request_headers", {}),
                    gw_ctx.get("user_context", {}),
                )
    except LookupError:
        # Not in a request context — fall through to ContextVar defaults
        return s_id, request_headers_var.get(), user_context_var.get()
    except Exception as e:
        logger.debug("Failed to read %s from scope: %s", _MCPGATEWAY_CONTEXT_KEY, e)

    # 3. Re-authentication fallback (stateful session path)
    try:
        # Reuse ctx from the scope-reading block above (step 2) to avoid
        # a redundant mcp_app.request_context lookup.
        if ctx is None:
            ctx = mcp_app.request_context
        request = ctx.request
        if not request:
            logger.warning("No request object found in MCP context")
            return s_id, request_headers_var.get(), user_context_var.get()

        # Extract server_id from URL
        path = request.url.path
        match = _SERVER_ID_RE.search(path)
        if match:
            s_id = match.group("server_id")

        # Extract headers
        req_headers = dict(request.headers)

        # Extract and verify user context
        # Use require_auth_header_first to match streamable_http_auth token precedence:
        # Authorization header > request cookies > jwt_token parameter
        auth_header = req_headers.get("authorization")
        cookie_token = request.cookies.get("jwt_token")

        try:
            raw_payload = await require_auth_header_first(auth_header=auth_header, jwt_token=cookie_token, request=request)
            if isinstance(raw_payload, str):  # "anonymous"
                user_ctx = {}
            elif isinstance(raw_payload, dict):
                # Normalize raw JWT payload to canonical user context shape
                # (matches streamable_http_auth normalization at lines 2155-2259)
                user_ctx = _normalize_jwt_payload(raw_payload)
            else:
                user_ctx = {}
        except Exception as e:
            logger.warning("Failed to recover user context in stateful session: %s", e)
            user_ctx = {}

        return s_id, req_headers, user_ctx

    except LookupError:
        # Not in a request context
        return s_id, request_headers_var.get(), user_context_var.get()
    except Exception as e:
        logger.exception("Error recovering context in stateful session: %s", e)
        return s_id, request_headers_var.get(), user_context_var.get()


def _normalize_jwt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw JWT payload to the canonical user context shape.

    Converts raw JWT fields (sub, token_use, nested user.is_admin) into the
    canonical ``{email, teams, is_admin, is_authenticated, token_use}`` dict that MCP
    handlers expect.  This mirrors the normalization performed by
    ``streamable_http_auth`` so that the stateful-session fallback path in
    ``_get_request_context_or_default`` returns an identical shape.

    Args:
        payload: Raw JWT payload dict from ``require_auth_header_first``.

    Returns:
        Canonical user context dict with keys email, teams, is_admin, is_authenticated, token_use.
    """
    email = payload.get("sub") or payload.get("email")
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        user_info = payload.get("user", {})
        is_admin = user_info.get("is_admin", False) if isinstance(user_info, dict) else False

    token_use = payload.get("token_use")
    if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
        # Session token: resolve teams from DB/cache
        if is_admin:
            final_teams = None  # Admin bypass
        elif email:
            # First-Party
            from mcpgateway.auth import _resolve_teams_from_db_sync  # pylint: disable=import-outside-toplevel

            final_teams = _resolve_teams_from_db_sync(email, is_admin=False)
        else:
            final_teams = []  # No email — public-only
    else:
        # API token or legacy: use embedded teams from JWT
        # First-Party
        from mcpgateway.auth import normalize_token_teams  # pylint: disable=import-outside-toplevel

        final_teams = normalize_token_teams(payload)

    user_ctx: dict[str, Any] = {
        "email": email,
        "teams": final_teams,
        "is_admin": is_admin,
        "is_authenticated": True,
        "token_use": token_use,
    }
    # Extract scoped permissions from JWT for per-method enforcement
    scopes = payload.get("scopes") or {}
    scoped_perms = scopes.get("permissions") or [] if isinstance(scopes, dict) else []
    if scoped_perms:
        user_ctx["scoped_permissions"] = scoped_perms
    return user_ctx


@mcp_app.list_tools()
async def list_tools() -> List[types.Tool]:
    """
    Lists all tools available to the MCP Server.

    Supports two modes based on gateway's gateway_mode:
    - 'cache': Returns tools from database (default behavior)
    - 'direct_proxy': Proxies the request directly to the remote MCP server

    Returns:
        A list of Tool objects containing metadata such as name, description, and input schema.
        Logs and returns an empty list on failure.

    Raises:
        PermissionError: If the caller lacks ``tools.read`` permission.

    Examples:
        >>> # Test list_tools function signature
        >>> import inspect
        >>> sig = inspect.signature(list_tools)
        >>> list(sig.parameters.keys())
        []
        >>> sig.return_annotation
        typing.List[mcp.types.Tool]
    """
    server_id, request_headers, user_context = await _get_request_context_or_default()

    # Token scope cap: deny early if scoped permissions exclude tools.read
    if _should_enforce_streamable_rbac(user_context):
        if not _check_scoped_permission(user_context, "tools.read"):
            raise PermissionError(_ACCESS_DENIED_MSG)

    # Extract filtering parameters from user context
    user_email = user_context.get("email") if user_context else None
    # Use None as default to distinguish "no teams specified" from "empty teams array"
    token_teams = user_context.get("teams") if user_context else None
    is_admin = user_context.get("is_admin", False) if user_context else False

    # Admin bypass - only when token has NO team restrictions (token_teams is None)
    # If token has explicit team scope (even empty [] for public-only), respect it
    if is_admin and token_teams is None:
        user_email = None
        # token_teams stays None (unrestricted)
    elif token_teams is None:
        token_teams = []  # Non-admin without teams = public-only (secure default)

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    if server_id:
        try:
            async with get_db() as db:
                # Check for X-Context-Forge-Gateway-Id header first - if present, try direct proxy mode
                gateway_id = extract_gateway_id_from_headers(request_headers)

                # If X-Context-Forge-Gateway-Id is provided, check if that gateway is in direct_proxy mode
                if gateway_id:
                    # Third-Party
                    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                    # First-Party
                    from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                    gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
                    if gateway and getattr(gateway, "gateway_mode", "cache") == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                        # SECURITY: Check gateway access before allowing direct proxy
                        if not await check_gateway_access(db, gateway, user_email, token_teams):
                            logger.warning("Access denied to gateway %s in direct_proxy mode for user %s", gateway_id, user_email)
                            return []  # Return empty list for unauthorized access

                        # Direct proxy mode: forward request to remote MCP server
                        # Get _meta from request context if available
                        meta = None
                        try:
                            request_ctx = mcp_app.request_context
                            meta = request_ctx.meta
                            logger.info(
                                "[LIST TOOLS] Using direct_proxy mode for server %s, gateway %s (from %s header). Meta Attached: %s",
                                server_id,
                                gateway.id,
                                GATEWAY_ID_HEADER,
                                meta is not None,
                            )
                        except (LookupError, AttributeError) as e:
                            logger.debug("No request context available for _meta extraction: %s", e)

                        return await _proxy_list_tools_to_gateway(gateway, request_headers, user_context, meta)
                    if gateway:
                        logger.debug("Gateway %s found but not in direct_proxy mode (mode: %s), using cache mode", gateway_id, getattr(gateway, "gateway_mode", "cache"))
                    else:
                        logger.warning("Gateway %s specified in %s header not found", gateway_id, GATEWAY_ID_HEADER)

                # Check if server exists for cache mode
                # Third-Party
                from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.db import Server as DbServer  # pylint: disable=import-outside-toplevel

                server = db.execute(select(DbServer).where(DbServer.id == server_id)).scalar_one_or_none()
                if not server:
                    logger.warning("Server %s not found in database", server_id)
                    return []

                # Default cache mode: use database
                tools = await tool_service.list_server_tools(db, server_id, user_email=user_email, token_teams=token_teams, _request_headers=request_headers)
                return [types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema, outputSchema=tool.output_schema, annotations=tool.annotations) for tool in tools]
        except Exception as e:
            logger.error("Error listing tools:%s", e)
            return []
    else:
        try:
            async with get_db() as db:
                tools, _ = await tool_service.list_tools(db, include_inactive=False, limit=0, user_email=user_email, token_teams=token_teams, _request_headers=request_headers)
                return [types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema, outputSchema=tool.output_schema, annotations=tool.annotations) for tool in tools]
        except Exception as e:
            logger.exception("Error listing tools:%s", e)
            return []


@mcp_app.list_prompts()
async def list_prompts() -> List[types.Prompt]:
    """
    Lists all prompts available to the MCP Server.

    Returns:
        A list of Prompt objects containing metadata such as name, description, and arguments.
        Logs and returns an empty list on failure.

    Raises:
        PermissionError: If the user context indicates insufficient permissions (e.g., missing "prompts.read" scope).

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(list_prompts)
        >>> list(sig.parameters.keys())
        []
        >>> sig.return_annotation
        typing.List[mcp.types.Prompt]
    """
    server_id, _, user_context = await _get_request_context_or_default()

    # Token scope cap: deny early if scoped permissions exclude prompts.read
    if _should_enforce_streamable_rbac(user_context):
        if not _check_scoped_permission(user_context, "prompts.read"):
            raise PermissionError(_ACCESS_DENIED_MSG)

    # Extract filtering parameters from user context
    user_email = user_context.get("email") if user_context else None
    # Use None as default to distinguish "no teams specified" from "empty teams array"
    token_teams = user_context.get("teams") if user_context else None
    is_admin = user_context.get("is_admin", False) if user_context else False

    # Admin bypass - only when token has NO team restrictions (token_teams is None)
    # If token has explicit team scope (even empty [] for public-only), respect it
    if is_admin and token_teams is None:
        user_email = None
        # token_teams stays None (unrestricted)
    elif token_teams is None:
        token_teams = []  # Non-admin without teams = public-only (secure default)

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    if server_id:
        try:
            async with get_db() as db:
                prompts = await prompt_service.list_server_prompts(db, server_id, user_email=user_email, token_teams=token_teams)
                return [types.Prompt(name=prompt.name, description=prompt.description, arguments=prompt.arguments) for prompt in prompts]
        except Exception as e:
            logger.exception("Error listing Prompts:%s", e)
            return []
    else:
        try:
            async with get_db() as db:
                prompts, _ = await prompt_service.list_prompts(db, include_inactive=False, limit=0, user_email=user_email, token_teams=token_teams)
                return [types.Prompt(name=prompt.name, description=prompt.description, arguments=prompt.arguments) for prompt in prompts]
        except Exception as e:
            logger.exception("Error listing prompts:%s", e)
            return []


@mcp_app.get_prompt()
async def get_prompt(prompt_id: str, arguments: dict[str, str] | None = None) -> types.GetPromptResult:
    """
    Retrieves a prompt by ID, optionally substituting arguments.

    Args:
        prompt_id (str): The ID of the prompt to retrieve.
        arguments (Optional[dict[str, str]]): Optional dictionary of arguments to substitute into the prompt.

    Returns:
        GetPromptResult: Object containing the prompt messages and description.
        Returns an empty list on failure or if no prompt content is found.

    Raises:
        PermissionError: If the user context indicates insufficient permissions (e.g., missing "prompts.read" scope).

    Logs exceptions if any errors occur during retrieval.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(get_prompt)
        >>> list(sig.parameters.keys())
        ['prompt_id', 'arguments']
        >>> sig.return_annotation.__name__
        'GetPromptResult'
    """
    server_id, _, user_context = await _get_request_context_or_default()

    # Token scope cap: deny early if scoped permissions exclude prompts.read
    if _should_enforce_streamable_rbac(user_context):
        if not _check_scoped_permission(user_context, "prompts.read"):
            raise PermissionError(_ACCESS_DENIED_MSG)

    # Extract authorization parameters from user context (same pattern as list_prompts)
    user_email = user_context.get("email") if user_context else None
    token_teams = user_context.get("teams") if user_context else None
    is_admin = user_context.get("is_admin", False) if user_context else False

    # Admin bypass - only when token has NO team restrictions (token_teams is None)
    if is_admin and token_teams is None:
        user_email = None
        # token_teams stays None (unrestricted)
    elif token_teams is None:
        token_teams = []  # Non-admin without teams = public-only (secure default)

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    meta_data = None
    # Extract _meta from request context if available
    try:
        ctx = mcp_app.request_context
        if ctx and ctx.meta is not None:
            meta_data = ctx.meta.model_dump()
    except LookupError:
        # request_context might not be active in some edge cases (e.g. tests)
        logger.debug("No active request context found")

    try:
        async with get_db() as db:
            try:
                result = await prompt_service.get_prompt(
                    db=db,
                    prompt_id=prompt_id,
                    arguments=arguments,
                    user=user_email,
                    server_id=server_id,
                    token_teams=token_teams,
                    _meta_data=meta_data,
                )
            except Exception as e:
                logger.exception("Error getting prompt '%s': %s", prompt_id, e)
                return []
            if not result or not result.messages:
                logger.warning("No content returned by prompt: %s", prompt_id)
                return []
            message_dicts = [message.model_dump() for message in result.messages]
            return types.GetPromptResult(messages=message_dicts, description=result.description)
    except Exception as e:
        logger.exception("Error getting prompt '%s': %s", prompt_id, e)
        return []


@mcp_app.list_resources()
async def list_resources() -> List[types.Resource]:
    """
    Lists all resources available to the MCP Server.

    Returns:
        A list of Resource objects containing metadata such as uri, name, description, and mimeType.
        Logs and returns an empty list on failure.

    Raises:
        PermissionError: If the user context indicates insufficient permissions (e.g., missing "resources.read" scope).

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(list_resources)
        >>> list(sig.parameters.keys())
        []
        >>> sig.return_annotation
        typing.List[mcp.types.Resource]
    """
    server_id, request_headers, user_context = await _get_request_context_or_default()

    # Token scope cap: deny early if scoped permissions exclude resources.read
    if _should_enforce_streamable_rbac(user_context):
        if not _check_scoped_permission(user_context, "resources.read"):
            raise PermissionError(_ACCESS_DENIED_MSG)

    # Extract filtering parameters from user context
    user_email = user_context.get("email") if user_context else None
    # Use None as default to distinguish "no teams specified" from "empty teams array"
    token_teams = user_context.get("teams") if user_context else None
    is_admin = user_context.get("is_admin", False) if user_context else False

    # Admin bypass - only when token has NO team restrictions (token_teams is None)
    # If token has explicit team scope (even empty [] for public-only), respect it
    if is_admin and token_teams is None:
        user_email = None
        # token_teams stays None (unrestricted)
    elif token_teams is None:
        token_teams = []  # Non-admin without teams = public-only (secure default)

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    if server_id:
        try:
            async with get_db() as db:
                # Check for X-Context-Forge-Gateway-Id header first for direct proxy mode
                gateway_id = extract_gateway_id_from_headers(request_headers)

                # If X-Context-Forge-Gateway-Id is provided, check if that gateway is in direct_proxy mode
                if gateway_id:
                    # Third-Party
                    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                    # First-Party
                    from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                    gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
                    if gateway and gateway.gateway_mode == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                        # SECURITY: Check gateway access before allowing direct proxy
                        if not await check_gateway_access(db, gateway, user_email, token_teams):
                            logger.warning("Access denied to gateway %s in direct_proxy mode for user %s", gateway_id, user_email)
                            return []  # Return empty list for unauthorized access

                        # Direct proxy mode: forward request to remote MCP server
                        # Get _meta from request context if available
                        meta = None
                        try:
                            request_ctx = mcp_app.request_context
                            meta = request_ctx.meta
                            logger.info(
                                "[LIST RESOURCES] Using direct_proxy mode for server %s, gateway %s (from %s header). Meta Attached: %s",
                                server_id,
                                gateway.id,
                                GATEWAY_ID_HEADER,
                                meta is not None,
                            )
                        except (LookupError, AttributeError) as e:
                            logger.debug("No request context available for _meta extraction: %s", e)

                        return await _proxy_list_resources_to_gateway(gateway, request_headers, user_context, meta)
                    if gateway:
                        logger.debug("Gateway %s found but not in direct_proxy mode (mode: %s), using cache mode", gateway_id, gateway.gateway_mode)
                    else:
                        logger.warning("Gateway %s specified in %s header not found", gateway_id, GATEWAY_ID_HEADER)

                # Default cache mode: use database
                resources = await resource_service.list_server_resources(db, server_id, user_email=user_email, token_teams=token_teams)
                return [types.Resource(uri=resource.uri, name=resource.name, description=resource.description, mimeType=resource.mime_type) for resource in resources]
        except Exception as e:
            logger.exception("Error listing Resources:%s", e)
            return []
    else:
        try:
            async with get_db() as db:
                resources, _ = await resource_service.list_resources(db, include_inactive=False, limit=0, user_email=user_email, token_teams=token_teams)
                return [types.Resource(uri=resource.uri, name=resource.name, description=resource.description, mimeType=resource.mime_type) for resource in resources]
        except Exception as e:
            logger.exception("Error listing resources:%s", e)
            return []


@mcp_app.read_resource()
async def read_resource(resource_uri: str) -> Union[str, bytes]:
    """
    Reads the content of a resource specified by its URI.

    Args:
        resource_uri (str): The URI of the resource to read.

    Returns:
        Union[str, bytes]: The content of the resource as text or binary data.
        Returns empty string on failure or if no content is found.

    Raises:
        PermissionError: If the user does not have the required permissions to read resources.

    Logs exceptions if any errors occur during reading.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(read_resource)
        >>> list(sig.parameters.keys())
        ['resource_uri']
        >>> sig.return_annotation
        typing.Union[str, bytes]
    """
    server_id, request_headers, user_context = await _get_request_context_or_default()

    # Token scope cap: deny early if scoped permissions exclude resources.read
    if _should_enforce_streamable_rbac(user_context):
        if not _check_scoped_permission(user_context, "resources.read"):
            raise PermissionError(_ACCESS_DENIED_MSG)

    # Extract authorization parameters from user context (same pattern as list_resources)
    user_email = user_context.get("email") if user_context else None
    token_teams = user_context.get("teams") if user_context else None
    is_admin = user_context.get("is_admin", False) if user_context else False

    # Admin bypass - only when token has NO team restrictions (token_teams is None)
    if is_admin and token_teams is None:
        user_email = None
        # token_teams stays None (unrestricted)
    elif token_teams is None:
        token_teams = []  # Non-admin without teams = public-only (secure default)

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    meta_data = None
    # Extract _meta from request context if available
    try:
        ctx = mcp_app.request_context
        if ctx and ctx.meta is not None:
            meta_data = ctx.meta.model_dump()
    except LookupError:
        # request_context might not be active in some edge cases (e.g. tests)
        logger.debug("No active request context found")

    try:
        async with get_db() as db:
            # Check for X-Context-Forge-Gateway-Id header first for direct proxy mode
            gateway_id = extract_gateway_id_from_headers(request_headers)

            # If X-Context-Forge-Gateway-Id is provided, check if that gateway is in direct_proxy mode
            if gateway_id:
                # Third-Party
                from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
                if gateway and gateway.gateway_mode == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                    # SECURITY: Check gateway access before allowing direct proxy
                    if not await check_gateway_access(db, gateway, user_email, token_teams):
                        logger.warning("Access denied to gateway %s in direct_proxy mode for user %s", gateway_id, user_email)
                        return ""

                    # Direct proxy mode: forward request to remote MCP server
                    # Get _meta from request context if available
                    meta = None
                    try:
                        request_ctx = mcp_app.request_context
                        meta = request_ctx.meta
                        logger.info(
                            "Using direct_proxy mode for resources/read %s, server %s, gateway %s (from %s header), forwarding _meta: %s",
                            resource_uri,
                            server_id,
                            gateway.id,
                            GATEWAY_ID_HEADER,
                            meta,
                        )
                    except (LookupError, AttributeError) as e:
                        logger.debug("No request context available for _meta extraction: %s", e)

                    contents = await _proxy_read_resource_to_gateway(gateway, str(resource_uri), user_context, meta)
                    if contents:
                        # Return first content (text or blob)
                        first_content = contents[0]
                        if hasattr(first_content, "text"):
                            return first_content.text
                        if hasattr(first_content, "blob"):
                            return first_content.blob
                    return ""
                if gateway:
                    logger.debug("Gateway %s found but not in direct_proxy mode (mode: %s), using cache mode", gateway_id, gateway.gateway_mode)
                else:
                    logger.warning("Gateway %s specified in %s header not found", gateway_id, GATEWAY_ID_HEADER)

            # Default cache mode: use database
            try:
                result = await resource_service.read_resource(
                    db=db,
                    resource_uri=str(resource_uri),
                    user=user_email,
                    server_id=server_id,
                    token_teams=token_teams,
                    meta_data=meta_data,
                )
            except Exception as e:
                logger.exception("Error reading resource '%s': %s", resource_uri, e)
                return ""

            # Return blob content if available (binary resources)
            if result and result.blob:
                return result.blob

            # Return text content if available (text resources)
            if result and result.text:
                return result.text

            # No content found
            logger.warning("No content returned by resource: %s", resource_uri)
            return ""
    except Exception as e:
        logger.exception("Error reading resource '%s': %s", resource_uri, e)
        return ""


@mcp_app.list_resource_templates()
async def list_resource_templates() -> List[Dict[str, Any]]:
    """
    Lists all resource templates available to the MCP Server.

    Returns:
        List[types.ResourceTemplate]: A list of resource templates with their URIs and metadata.

    Raises:
        PermissionError: If the caller lacks ``resources.read`` permission.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(list_resource_templates)
        >>> list(sig.parameters.keys())
        []
        >>> sig.return_annotation.__origin__.__name__
        'list'
    """
    # Extract filtering parameters from user context (same pattern as list_resources)
    server_id, _, user_context = await _get_request_context_or_default()

    # Token scope cap: deny early if scoped permissions exclude resources.read
    if _should_enforce_streamable_rbac(user_context):
        if not _check_scoped_permission(user_context, "resources.read"):
            raise PermissionError(_ACCESS_DENIED_MSG)

    user_email = user_context.get("email") if user_context else None
    token_teams = user_context.get("teams") if user_context else None
    is_admin = user_context.get("is_admin", False) if user_context else False

    # Admin bypass - only when token has NO team restrictions (token_teams is None)
    # If token has explicit team scope (even empty [] for public-only), respect it
    if is_admin and token_teams is None:
        user_email = None
        # token_teams stays None (unrestricted)
    elif token_teams is None:
        token_teams = []  # Non-admin without teams = public-only (secure default)

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    try:
        async with get_db() as db:
            try:
                resource_templates = await resource_service.list_resource_templates(
                    db,
                    user_email=user_email,
                    token_teams=token_teams,
                    server_id=server_id,
                )
                return [template.model_dump(by_alias=True) for template in resource_templates]
            except Exception as e:
                logger.exception("Error listing resource templates: %s", e)
                return []
    except Exception as e:
        logger.exception("Error listing resource templates: %s", e)
        return []


@mcp_app.set_logging_level()
async def set_logging_level(level: types.LoggingLevel) -> types.EmptyResult:
    """
    Sets the logging level for the MCP Server.

    Args:
        level (types.LoggingLevel): The desired logging level (debug, info, notice, warning, error, critical, alert, emergency).

    Returns:
        types.EmptyResult: An empty result indicating success.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(set_logging_level)
        >>> list(sig.parameters.keys())
        ['level']

    Raises:
        PermissionError: If the user does not have permission to set the logging level.
    """
    server_id, _, user_context = await _get_request_context_or_default()

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    if _should_enforce_streamable_rbac(user_context):
        # Layer 1: Token scope cap
        if not _check_scoped_permission(user_context, "admin.system_config"):
            raise PermissionError(_ACCESS_DENIED_MSG)
        # Layer 2: RBAC check
        has_permission = await _check_streamable_permission(
            user_context=user_context,
            permission="admin.system_config",
            check_any_team=_check_any_team_for_server_scoped_rbac(user_context, server_id),
        )
        if not has_permission:
            raise PermissionError(_ACCESS_DENIED_MSG)

    try:
        # Convert MCP logging level to our LogLevel enum
        level_map = {
            "debug": LogLevel.DEBUG,
            "info": LogLevel.INFO,
            "notice": LogLevel.INFO,
            "warning": LogLevel.WARNING,
            "error": LogLevel.ERROR,
            "critical": LogLevel.CRITICAL,
            "alert": LogLevel.CRITICAL,
            "emergency": LogLevel.CRITICAL,
        }
        log_level = level_map.get(level.lower(), LogLevel.INFO)
        await logging_service.set_level(log_level)
        return types.EmptyResult()
    except PermissionError:
        raise
    except Exception as e:
        logger.exception("Error setting logging level: %s", e)
        return types.EmptyResult()


@mcp_app.completion()
async def complete(
    ref: Union[types.PromptReference, types.ResourceTemplateReference],
    argument: types.CompleteRequest,
    context: Optional[types.CompletionContext] = None,
) -> types.CompleteResult:
    """
    Provides argument completion suggestions for prompts or resources.

    Args:
        ref: A reference to a prompt or a resource template. Can be either
            `types.PromptReference` or `types.ResourceTemplateReference`.
        argument: The completion request specifying the input text and
            position for which completion suggestions should be generated.
        context: Optional contextual information for the completion request,
            such as user, environment, or invocation metadata.

    Returns:
        types.CompleteResult: A normalized completion result containing
        completion values, metadata (total, hasMore), and any additional
        MCP-compliant completion fields.

    Raises:
        PermissionError: If the caller lacks ``tools.read`` permission.
        Exception: If completion handling fails internally. The method
            logs the exception and returns an empty completion structure.
    """
    # Derive caller visibility scope from the current request context.
    server_id, _, user_context = await _get_request_context_or_default()

    # Token scope cap: deny early if scoped permissions exclude tools.read
    if _should_enforce_streamable_rbac(user_context):
        if not _check_scoped_permission(user_context, "tools.read"):
            raise PermissionError(_ACCESS_DENIED_MSG)

    # Enforce per-server OAuth requirement in permissive mode (defense-in-depth).
    # When mcp_require_auth=True, the middleware already guarantees authentication.
    # Note: OAuthEnforcementUnavailableError is intentionally uncaught here —
    # the middleware (streamable_http_auth) catches it and returns 503.  If the
    # middleware is somehow bypassed, an uncaught 500 is acceptable and will be
    # logged by the ASGI server.
    if not settings.mcp_require_auth:
        await _check_server_oauth_enforcement(server_id, user_context)

    try:
        user_email = user_context.get("email") if user_context else None
        token_teams = user_context.get("teams") if user_context else None
        is_admin = user_context.get("is_admin", False) if user_context else False

        # Admin bypass only for explicit unrestricted context; otherwise secure default.
        if is_admin and token_teams is None:
            user_email = None
        elif token_teams is None:
            token_teams = []  # Non-admin without explicit teams -> public-only

        async with get_db() as db:
            params = {
                "ref": ref.model_dump() if hasattr(ref, "model_dump") else ref,
                "argument": argument.model_dump() if hasattr(argument, "model_dump") else argument,
                "context": context.model_dump() if hasattr(context, "model_dump") else context,
            }

            result = await completion_service.handle_completion(
                db,
                params,
                user_email=user_email,
                token_teams=token_teams,
            )

            # ✅ Normalize the result for MCP
            if isinstance(result, dict):
                completion_data = result.get("completion", result)
                return types.Completion(**completion_data)

            if hasattr(result, "completion"):
                completion_obj = result.completion

                # If completion itself is a dict
                if isinstance(completion_obj, dict):
                    return types.Completion(**completion_obj)

                # If completion is another CompleteResult (nested)
                if hasattr(completion_obj, "completion"):
                    inner_completion = completion_obj.completion.model_dump() if hasattr(completion_obj.completion, "model_dump") else completion_obj.completion
                    return types.Completion(**inner_completion)

                # If completion is already a Completion model
                if isinstance(completion_obj, types.Completion):
                    return completion_obj

                # If it's another Pydantic model (e.g., mcpgateway.models.Completion)
                if hasattr(completion_obj, "model_dump"):
                    return types.Completion(**completion_obj.model_dump())

            # If result itself is already a types.Completion
            if isinstance(result, types.Completion):
                return result

            # Fallback: return empty completion
            return types.Completion(values=[], total=0, hasMore=False)

    except Exception as e:
        logger.exception("Error handling completion: %s", e)
        return types.Completion(values=[], total=0, hasMore=False)


class SessionManagerWrapper:
    """
    Wrapper class for managing the lifecycle of a StreamableHTTPSessionManager instance.
    Provides start, stop, and request handling methods.

    Examples:
        >>> # Test SessionManagerWrapper initialization
        >>> wrapper = SessionManagerWrapper()
        >>> wrapper
        <mcpgateway.transports.streamablehttp_transport.SessionManagerWrapper object at ...>
        >>> hasattr(wrapper, 'session_manager')
        True
        >>> hasattr(wrapper, 'stack')
        True
        >>> isinstance(wrapper.stack, AsyncExitStack)
        True
    """

    def __init__(self) -> None:
        """
        Initializes the session manager and the exit stack used for managing its lifecycle.

        Examples:
            >>> # Test initialization
            >>> wrapper = SessionManagerWrapper()
            >>> wrapper.session_manager is not None
            True
            >>> wrapper.stack is not None
            True
        """

        if settings.use_stateful_sessions:
            if settings.experimental_rust_mcp_runtime_enabled and settings.experimental_rust_mcp_session_auth_reuse_enabled and settings.experimental_rust_mcp_event_store_enabled:
                event_store = RustEventStore(
                    max_events_per_stream=settings.streamable_http_max_events_per_stream,
                    ttl=settings.streamable_http_event_ttl,
                )
                logger.debug("Using RustEventStore for stateful sessions")
            # Use Redis event store for single-worker stateful deployments
            elif settings.cache_type == "redis" and settings.redis_url:
                event_store = RedisEventStore(max_events_per_stream=settings.streamable_http_max_events_per_stream, ttl=settings.streamable_http_event_ttl)
                logger.debug("Using RedisEventStore for stateful sessions (single-worker)")
            else:
                # Fall back to in-memory for single-worker or when Redis not available
                event_store = InMemoryEventStore()
                logger.warning("Using InMemoryEventStore - only works with single worker!")
            stateless = False
        else:
            event_store = None
            stateless = True

        self.session_manager = StreamableHTTPSessionManager(
            app=mcp_app,
            event_store=event_store,
            json_response=settings.json_response_enabled,
            stateless=stateless,
        )
        self.stack = AsyncExitStack()

    async def initialize(self) -> None:
        """
        Starts the Streamable HTTP session manager context.

        Examples:
            >>> # Test initialize method exists
            >>> wrapper = SessionManagerWrapper()
            >>> hasattr(wrapper, 'initialize')
            True
            >>> callable(wrapper.initialize)
            True
        """
        logger.debug("Initializing Streamable HTTP service")
        await self.stack.enter_async_context(self.session_manager.run())

    async def shutdown(self) -> None:
        """
        Gracefully shuts down the Streamable HTTP session manager.

        Examples:
            >>> # Test shutdown method exists
            >>> wrapper = SessionManagerWrapper()
            >>> hasattr(wrapper, 'shutdown')
            True
            >>> callable(wrapper.shutdown)
            True
        """
        logger.debug("Stopping Streamable HTTP Session Manager...")
        await self.stack.aclose()

    async def handle_streamable_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Forwards an incoming ASGI request to the streamable HTTP session manager.

        Args:
            scope (Scope): ASGI scope object containing connection information.
            receive (Receive): ASGI receive callable.
            send (Send): ASGI send callable.

        Raises:
            Exception: Any exception raised during request handling is logged.

        Logs any exceptions that occur during request handling.

        Examples:
            >>> # Test handle_streamable_http method exists
            >>> wrapper = SessionManagerWrapper()
            >>> hasattr(wrapper, 'handle_streamable_http')
            True
            >>> callable(wrapper.handle_streamable_http)
            True

            >>> # Test method signature
            >>> import inspect
            >>> sig = inspect.signature(wrapper.handle_streamable_http)
            >>> list(sig.parameters.keys())
            ['scope', 'receive', 'send']
        """

        path = scope["modified_path"]
        # Uses precompiled regex for server ID extraction
        match = _SERVER_ID_RE.search(path)

        # Extract request headers from scope (ASGI provides bytes; normalize to lowercase for lookup).
        raw_headers = scope.get("headers") or []
        headers: dict[str, str] = {}
        for item in raw_headers:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                continue
            k, v = item
            if not isinstance(k, (bytes, bytearray)) or not isinstance(v, (bytes, bytearray)):
                continue
            # latin-1 is a byte-preserving decode; safe for arbitrary header bytes.
            headers[k.decode("latin-1").lower()] = v.decode("latin-1")

        # Log session info for debugging stateful sessions
        mcp_session_id = headers.get("mcp-session-id", "not-provided")
        method = scope.get("method", "UNKNOWN")
        query_string = scope.get("query_string", b"").decode("utf-8")
        logger.debug("[STATEFUL] Streamable HTTP %s %s | MCP-Session-Id: %s | Query: %s | Stateful: %s", method, path, mcp_session_id, query_string, settings.use_stateful_sessions)

        # Note: mcp-session-id from client is used for gateway-internal session affinity
        # routing (stored in request_headers_var), but is NOT renamed or forwarded to
        # upstream servers - it's a gateway-side concept, not an end-to-end semantic header

        # Multi-worker session affinity: check if we should forward to another worker
        # This must happen BEFORE the SDK's session manager handles the request
        # Only trust x-forwarded-internally from loopback to prevent external spoofing
        _client = scope.get("client")
        _client_host = _client[0] if _client else None
        _from_loopback = _client_host in ("127.0.0.1", "::1") if _client_host else False
        is_internally_forwarded = _from_loopback and headers.get("x-forwarded-internally") == "true"

        if settings.mcpgateway_session_affinity_enabled and mcp_session_id != "not-provided":
            try:
                # First-Party
                from mcpgateway.services.mcp_session_pool import MCPSessionPool  # pylint: disable=import-outside-toplevel

                if not MCPSessionPool.is_valid_mcp_session_id(mcp_session_id):
                    logger.debug("Invalid MCP session id on Streamable HTTP request, skipping affinity")
                    mcp_session_id = "not-provided"
            except Exception:
                mcp_session_id = "not-provided"

        # Log session manager ID for debugging
        logger.debug("[SESSION_MGR_DEBUG] Manager ID: %s", id(self.session_manager))

        # Enforce server access parity for server-scoped Streamable HTTP MCP routes.
        # This mirrors /servers/{id}/sse and /servers/{id}/message guards.
        user_context = user_context_var.get()
        if match and _should_enforce_streamable_rbac(user_context):
            _server_id = match.group("server_id")
            has_server_access = await _check_streamable_permission(
                user_context=user_context,
                permission="servers.use",
                check_any_team=_check_any_team_for_server_scoped_rbac(user_context, _server_id),
            )
            if not has_server_access:
                response = ORJSONResponse(
                    {"detail": _ACCESS_DENIED_MSG},
                    status_code=HTTP_403_FORBIDDEN,
                )
                await response(scope, receive, send)
                return

        if is_internally_forwarded:
            logger.debug("[HTTP_AFFINITY_FORWARDED] Received forwarded request | Method: %s | Session: %s", method, mcp_session_id)

            # Only route POST requests with JSON-RPC body to /rpc
            # DELETE and other methods should return success (session cleanup is local)
            if method != "POST":
                logger.debug("[HTTP_AFFINITY_FORWARDED] Non-POST method, returning 200 OK")
                await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","result":{}}'})
                return

            # For POST requests, bypass SDK session manager and use /rpc directly
            # This avoids SDK's session cleanup issues while maintaining stateful upstream connections
            try:
                # Read request body
                body_parts = []
                while True:
                    message = await receive()
                    if message["type"] == "http.request":
                        body_parts.append(message.get("body", b""))
                        if not message.get("more_body", False):
                            break
                    elif message["type"] == "http.disconnect":
                        return
                body = b"".join(body_parts)

                if not body:
                    logger.debug("[HTTP_AFFINITY_FORWARDED] Empty body, returning 202 Accepted")
                    await send({"type": "http.response.start", "status": 202, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
                    return

                json_body = orjson.loads(body)
                rpc_method = json_body.get("method", "")
                logger.debug("[HTTP_AFFINITY_FORWARDED] Routing to /rpc | Method: %s", rpc_method)

                session_allowed, deny_status, deny_detail = await _validate_streamable_session_access(
                    mcp_session_id=mcp_session_id,
                    user_context=user_context,
                    rpc_method=rpc_method,
                )
                if not session_allowed:
                    response = ORJSONResponse({"detail": deny_detail}, status_code=deny_status)
                    await response(scope, receive, send)
                    return

                # Notifications don't need /rpc routing - just acknowledge
                if rpc_method.startswith("notifications/"):
                    logger.debug("[HTTP_AFFINITY_FORWARDED] Notification, returning 202 Accepted")
                    await send({"type": "http.response.start", "status": 202, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
                    return

                # Inject server_id from URL path into params for /rpc routing
                if match:
                    server_id = match.group("server_id")
                    if not isinstance(json_body.get("params"), dict):
                        json_body["params"] = {}
                    json_body["params"]["server_id"] = server_id
                    # Re-serialize body with injected server_id
                    body = orjson.dumps(json_body)
                    logger.debug("[HTTP_AFFINITY_FORWARDED] Injected server_id %s into /rpc params", server_id)

                async with httpx.AsyncClient() as client:
                    rpc_headers = {
                        "content-type": "application/json",
                        "x-mcp-session-id": mcp_session_id,  # Pass session for upstream affinity
                        "x-forwarded-internally": "true",  # Prevent infinite forwarding loops
                    }
                    # Copy auth header if present
                    if "authorization" in headers:
                        rpc_headers["authorization"] = headers["authorization"]

                    response = await client.post(
                        f"http://127.0.0.1:{settings.port}/rpc",
                        content=body,
                        headers=rpc_headers,
                        timeout=30.0,
                    )

                    # Return response to client
                    response_headers = [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response.content)).encode()),
                    ]
                    if mcp_session_id != "not-provided":
                        response_headers.append((b"mcp-session-id", mcp_session_id.encode()))

                    await send(
                        {
                            "type": "http.response.start",
                            "status": response.status_code,
                            "headers": response_headers,
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": response.content,
                        }
                    )
                    logger.debug("[HTTP_AFFINITY_FORWARDED] Response sent | Status: %s", response.status_code)
                    return
            except Exception as e:
                logger.error("[HTTP_AFFINITY_FORWARDED] Error routing to /rpc: %s", e)
                # Fall through to SDK handling as fallback

        if settings.mcpgateway_session_affinity_enabled and settings.use_stateful_sessions and mcp_session_id != "not-provided" and not is_internally_forwarded:
            try:
                # First-Party - lazy import to avoid circular dependencies
                # First-Party
                from mcpgateway.services.mcp_session_pool import get_mcp_session_pool, WORKER_ID  # pylint: disable=import-outside-toplevel

                pool = get_mcp_session_pool()
                owner = await pool.get_streamable_http_session_owner(mcp_session_id)
                logger.debug("[HTTP_AFFINITY_CHECK] Worker %s | Session %s... | Owner from Redis: %s", WORKER_ID, mcp_session_id[:8], owner)

                if owner and owner != WORKER_ID:
                    # Session owned by another worker - forward the entire HTTP request
                    logger.info("[HTTP_AFFINITY] Worker %s | Session %s... | Owner: %s | Forwarding HTTP request", WORKER_ID, mcp_session_id[:8], owner)

                    # Read request body
                    body_parts = []
                    while True:
                        message = await receive()
                        if message["type"] == "http.request":
                            body_parts.append(message.get("body", b""))
                            if not message.get("more_body", False):
                                break
                        elif message["type"] == "http.disconnect":
                            return
                    body = b"".join(body_parts)

                    # Forward to owner worker
                    response = await pool.forward_streamable_http_to_owner(
                        owner_worker_id=owner,
                        mcp_session_id=mcp_session_id,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        query_string=query_string,
                    )

                    if response:
                        # Send forwarded response back to client
                        response_headers = [(k.encode(), v.encode()) for k, v in response["headers"].items() if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")]
                        response_headers.append((b"content-length", str(len(response["body"])).encode()))

                        await send(
                            {
                                "type": "http.response.start",
                                "status": response["status"],
                                "headers": response_headers,
                            }
                        )
                        await send(
                            {
                                "type": "http.response.body",
                                "body": response["body"],
                            }
                        )
                        logger.debug("[HTTP_AFFINITY] Worker %s | Session %s... | Forwarded response sent to client", WORKER_ID, mcp_session_id[:8])
                        return

                    # Forwarding failed - fall through to local handling
                    # This may result in "session not found" but it's better than no response
                    logger.debug("[HTTP_AFFINITY] Worker %s | Session %s... | Forwarding failed, falling back to local", WORKER_ID, mcp_session_id[:8])

                elif owner == WORKER_ID and method == "POST":
                    # We own this session - route POST requests to /rpc to avoid SDK session issues
                    # The SDK's _server_instances gets cleared between requests, so we can't rely on it
                    logger.debug("[HTTP_AFFINITY_LOCAL] Worker %s | Session %s... | Owner is us, routing to /rpc", WORKER_ID, mcp_session_id[:8])

                    # Read request body
                    body_parts = []
                    while True:
                        message = await receive()
                        if message["type"] == "http.request":
                            body_parts.append(message.get("body", b""))
                            if not message.get("more_body", False):
                                break
                        elif message["type"] == "http.disconnect":
                            return
                    body = b"".join(body_parts)

                    if not body:
                        logger.debug("[HTTP_AFFINITY_LOCAL] Empty body, returning 202 Accepted")
                        await send({"type": "http.response.start", "status": 202, "headers": []})
                        await send({"type": "http.response.body", "body": b""})
                        return

                    # Parse JSON-RPC and route to /rpc
                    try:
                        json_body = orjson.loads(body)
                        rpc_method = json_body.get("method", "")
                        logger.debug("[HTTP_AFFINITY_LOCAL] Routing to /rpc | Method: %s", rpc_method)

                        session_allowed, deny_status, deny_detail = await _validate_streamable_session_access(
                            mcp_session_id=mcp_session_id,
                            user_context=user_context,
                            rpc_method=rpc_method,
                        )
                        if not session_allowed:
                            response = ORJSONResponse({"detail": deny_detail}, status_code=deny_status)
                            await response(scope, receive, send)
                            return

                        # Notifications don't need /rpc routing
                        if rpc_method.startswith("notifications/"):
                            logger.debug("[HTTP_AFFINITY_LOCAL] Notification, returning 202 Accepted")
                            await send({"type": "http.response.start", "status": 202, "headers": []})
                            await send({"type": "http.response.body", "body": b""})
                            return

                        # Inject server_id from URL path into params for /rpc routing
                        if match:
                            server_id = match.group("server_id")
                            if not isinstance(json_body.get("params"), dict):
                                json_body["params"] = {}
                            json_body["params"]["server_id"] = server_id
                            # Re-serialize body with injected server_id
                            body = orjson.dumps(json_body)
                            logger.debug("[HTTP_AFFINITY_LOCAL] Injected server_id %s into /rpc params", server_id)

                        async with httpx.AsyncClient() as client:
                            rpc_headers = {
                                "content-type": "application/json",
                                "x-mcp-session-id": mcp_session_id,
                                "x-forwarded-internally": "true",
                            }
                            if "authorization" in headers:
                                rpc_headers["authorization"] = headers["authorization"]

                            response = await client.post(
                                f"http://127.0.0.1:{settings.port}/rpc",
                                content=body,
                                headers=rpc_headers,
                                timeout=30.0,
                            )

                            response_headers = [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(response.content)).encode()),
                                (b"mcp-session-id", mcp_session_id.encode()),
                            ]

                            await send(
                                {
                                    "type": "http.response.start",
                                    "status": response.status_code,
                                    "headers": response_headers,
                                }
                            )
                            await send(
                                {
                                    "type": "http.response.body",
                                    "body": response.content,
                                }
                            )
                            logger.debug("[HTTP_AFFINITY_LOCAL] Response sent | Status: %s", response.status_code)
                            return
                    except Exception as e:
                        logger.error("[HTTP_AFFINITY_LOCAL] Error routing to /rpc: %s", e)
                        # Fall through to SDK handling as fallback

            except RuntimeError:
                # Pool not initialized - proceed with local handling
                pass
            except Exception as e:
                logger.debug("Session affinity check failed, proceeding locally: %s", e)

        # Store headers in context for tool invocations
        request_headers_var.set(headers)

        if match:
            server_id = match.group("server_id")
            server_id_var.set(server_id)
        else:
            server_id_var.set(None)

        # For session affinity: wrap send to capture session ID from response headers
        # This allows us to register ownership for new sessions created by the SDK
        captured_session_id: Optional[str] = None

        async def send_with_capture(message: Dict[str, Any]) -> None:
            """Wrap ASGI send to capture session ID from response headers.

            Args:
                message: ASGI message dict.
            """
            nonlocal captured_session_id
            if message["type"] == "http.response.start" and settings.mcpgateway_session_affinity_enabled:
                # Look for mcp-session-id in response headers
                response_headers = message.get("headers", [])
                for header_name, header_value in response_headers:
                    if isinstance(header_name, bytes):
                        header_name = header_name.decode("latin-1")
                    if isinstance(header_value, bytes):
                        header_value = header_value.decode("latin-1")
                    if header_name.lower() == "mcp-session-id":
                        captured_session_id = header_value
                        break
            await send(message)

        # Propagate middleware-resolved context via ASGI scope so that MCP
        # handlers can retrieve it even when ContextVars are lost (the SDK's
        # task group was created at startup, so spawned handler tasks inherit
        # the startup context rather than the per-request context).
        scope[_MCPGATEWAY_CONTEXT_KEY] = {
            "server_id": server_id_var.get(),
            "request_headers": headers,
            "user_context": user_context,
        }

        try:
            await self.session_manager.handle_request(scope, receive, send_with_capture)
            logger.debug("[STATEFUL] Streamable HTTP request completed successfully | Session: %s", mcp_session_id)

            # Register ownership for the session we just handled
            # This captures both existing sessions (mcp_session_id from request)
            # and new sessions (captured_session_id from response)
            logger.debug(
                "[HTTP_AFFINITY_DEBUG] affinity_enabled=%s stateful=%s captured=%s mcp_session_id=%s",
                settings.mcpgateway_session_affinity_enabled,
                settings.use_stateful_sessions,
                captured_session_id,
                mcp_session_id,
            )
            if settings.mcpgateway_session_affinity_enabled and settings.use_stateful_sessions:
                session_to_register: Optional[str] = None

                # Only server-emitted session IDs (from successful initialize) can
                # establish new ownership state for affinity.
                if captured_session_id:
                    session_to_register = captured_session_id

                    requester_email = user_context.get("email") if isinstance(user_context, dict) else None
                    if requester_email:
                        effective_owner = await _claim_streamable_session_owner(captured_session_id, requester_email)
                        if effective_owner and effective_owner != requester_email and not bool(user_context.get("is_admin", False)):
                            logger.warning("Session owner mismatch for %s... (requester=%s, owner=%s)", captured_session_id[:8], requester_email, effective_owner)
                elif mcp_session_id != "not-provided":
                    # Existing client-provided IDs may only refresh affinity when they
                    # are already bound to the caller's principal.
                    session_allowed, _deny_status, _deny_detail = await _validate_streamable_session_access(
                        mcp_session_id=mcp_session_id,
                        user_context=user_context,
                        rpc_method=None,
                    )
                    if session_allowed:
                        session_to_register = mcp_session_id

                logger.debug("[HTTP_AFFINITY_DEBUG] session_to_register=%s", session_to_register)
                if session_to_register:
                    try:
                        # First-Party - lazy import to avoid circular dependencies
                        # First-Party
                        from mcpgateway.services.mcp_session_pool import get_mcp_session_pool, WORKER_ID  # pylint: disable=import-outside-toplevel

                        pool = get_mcp_session_pool()
                        await pool.register_pool_session_owner(session_to_register)
                        logger.debug("[HTTP_AFFINITY_SDK] Worker %s | Session %s... | Registered ownership after SDK handling", WORKER_ID, session_to_register[:8])
                    except Exception as e:
                        logger.debug("[HTTP_AFFINITY_DEBUG] Exception during registration: %s", e)
                        logger.warning("Failed to register session ownership: %s", e)

        except anyio.ClosedResourceError:
            # Expected when client closes one side of the stream (normal lifecycle)
            logger.debug("Streamable HTTP connection closed by client (ClosedResourceError)")
        except Exception as e:
            logger.error("[STATEFUL] Streamable HTTP request failed | Session: %s | Error: %s", mcp_session_id, e)
            logger.exception("Error handling streamable HTTP request: %s", e)
            raise


# ------------------------- Authentication for /mcp routes ------------------------------


def _set_proxy_user_context(proxy_user: str) -> None:
    """Set user context for a proxy-authenticated request (no team context, non-admin).

    Args:
        proxy_user: Email address of the proxy-authenticated user.
    """
    user_context_var.set(
        {
            "email": proxy_user,
            "teams": [],
            "is_authenticated": True,
            "is_admin": False,
            "permission_is_admin": False,
        }
    )


def get_streamable_http_auth_context() -> dict[str, Any]:
    """Return the current StreamableHTTP auth context for trusted internal forwarding.

    The Rust MCP proxy uses this to carry already-authenticated MCP request context
    across the Python -> Rust -> Python seam so the internal dispatcher does not
    need to repeat JWT verification and team normalization on the hot path.

    Returns:
        A shallow copy of the trusted auth context fields that may be forwarded
        across the internal MCP seam.
    """
    user_context = user_context_var.get()
    if not isinstance(user_context, dict):
        return {}

    forwarded: dict[str, Any] = {}
    for key in (
        "email",
        "teams",
        "is_authenticated",
        "is_admin",
        "token_use",
        "permission_is_admin",
        "scoped_permissions",
        "scoped_server_id",
    ):
        if key not in user_context:
            continue
        value = user_context[key]
        if isinstance(value, list):
            forwarded[key] = list(value)
        else:
            forwarded[key] = value
    return forwarded


class _StreamableHttpAuthHandler:
    """Per-request handler that authenticates MCP StreamableHTTP requests.

    Encapsulates the ASGI triple (scope, receive, send) so that helper methods
    can send error responses without threading these values through every call.
    """

    __slots__ = ("scope", "receive", "send")

    def __init__(self, scope: Any, receive: Any, send: Any) -> None:
        self.scope = scope
        self.receive = receive
        self.send = send

    async def _send_error(self, *, detail: str, status_code: int = HTTP_401_UNAUTHORIZED, headers: dict[str, str] | None = None) -> bool:
        """Send an error response and return False (auth rejected).

        Args:
            detail: Error message for the JSON response body.
            status_code: HTTP status code (default 401).
            headers: Optional response headers (e.g. WWW-Authenticate).

        Returns:
            Always ``False`` so callers can ``return await self._send_error(...)``.
        """
        response = ORJSONResponse({"detail": detail}, status_code=status_code, headers=headers or {})
        await response(self.scope, self.receive, self.send)
        return False

    async def authenticate(self) -> bool:
        """Perform authentication check in middleware context (ASGI scope).

        Authenticates only requests targeting paths ending in "/mcp" or "/mcp/".

        Behavior:
        - If the path does not end with "/mcp", authentication is skipped.
        - If mcp_require_auth=True (strict mode): requests without valid auth are rejected with 401.
        - If mcp_require_auth=False (permissive mode):
          - Requests without auth are allowed but get public-only access (token_teams=[]).
          - EXCEPTION: if the target server has oauth_enabled=True, unauthenticated
            requests are rejected with 401 regardless of the global setting.
          - Valid tokens get full scoped access based on their teams.
          - Malformed/invalid Bearer tokens are rejected with 401 (no silent downgrade).
        - If a Bearer token is present, it is verified using ``verify_credentials``.

        Returns:
            True if authentication passes or is skipped.
            False if authentication fails and a 401 response is sent.
        """
        path = self.scope.get("path", "")
        if (not path.endswith("/mcp") and not path.endswith("/mcp/")) or path.startswith("/.well-known/"):
            # No auth for non-MCP paths or RFC 9728 metadata endpoints
            return True

        # Reset per-request OAuth enforcement cache so keep-alive connections
        # re-evaluate on every request instead of inheriting a stale True.
        _oauth_checked_var.set(False)

        headers = Headers(scope=self.scope)

        # CORS preflight (OPTIONS + Origin + Access-Control-Request-Method) cannot carry auth headers
        method = self.scope.get("method", "")
        if method == "OPTIONS":
            origin = headers.get("origin")
            if origin and headers.get("access-control-request-method"):
                return True

        authorization = headers.get("authorization")
        proxy_trusted = is_proxy_auth_trust_active(settings)
        proxy_user = headers.get(settings.proxy_user_header) if proxy_trusted else None

        # Determine authentication strategy based on settings
        if proxy_trusted and proxy_user:
            _set_proxy_user_context(proxy_user)
            return True  # Trusted proxy supplied user

        # --- Standard JWT authentication flow (client auth enabled) ---
        token: str | None = None
        bearer_header_supplied = False
        if authorization:
            scheme, credentials = get_authorization_scheme_param(authorization)
            if scheme.lower() == "bearer":
                bearer_header_supplied = True
                if credentials:
                    token = credentials

        if token is None:
            return await self._auth_no_token(path=path, bearer_header_supplied=bearer_header_supplied)

        return await self._auth_jwt(token=token)

    async def _auth_no_token(self, *, path: str, bearer_header_supplied: bool) -> bool:
        """Handle unauthenticated MCP requests (no Bearer token present).

        Args:
            path: Request path (used for per-server OAuth enforcement).
            bearer_header_supplied: True when Authorization: Bearer was present but empty.

        Returns:
            True if the request is allowed with public-only access, False if rejected.
        """
        # If client supplied a Bearer header but with empty credentials, fail closed
        if bearer_header_supplied:
            return await self._send_error(detail="Invalid authentication credentials", headers={"WWW-Authenticate": "Bearer"})

        # Strict mode: require authentication
        if settings.mcp_require_auth:
            return await self._send_error(detail="Authentication required for MCP endpoints", headers={"WWW-Authenticate": "Bearer"})

        # Permissive mode: allow unauthenticated access with public-only scope
        # BUT first check if this specific server requires OAuth (per-server enforcement)
        match = _SERVER_ID_RE.search(path)
        if match:
            per_server_id = match.group("server_id")
            try:
                await _check_server_oauth_enforcement(per_server_id, {"is_authenticated": False})
            except OAuthRequiredError:
                resource_metadata = _build_resource_metadata_url(self.scope, per_server_id)
                www_auth = f'Bearer resource_metadata="{resource_metadata}"' if resource_metadata else "Bearer"
                return await self._send_error(detail="This server requires OAuth authentication", headers={"WWW-Authenticate": www_auth})
            except OAuthEnforcementUnavailableError:
                logger.exception("OAuth enforcement check failed for server %s", per_server_id)
                return await self._send_error(detail="Service unavailable — unable to verify server authentication requirements", status_code=503)

        # Set context indicating unauthenticated user with public-only access (teams=[])
        user_context_var.set(
            {
                "email": None,
                "teams": [],  # Empty list = public-only access
                "is_authenticated": False,
                "is_admin": False,
                "permission_is_admin": False,
            }
        )
        return True  # Allow request to proceed with public-only access

    async def _auth_jwt(self, *, token: str) -> bool:
        """Verify a JWT Bearer token and populate the user context.

        Args:
            token: Bearer token value extracted from the Authorization header.

        Returns:
            True if verification succeeds, False if rejected (401/403/503 sent).
        """
        try:
            user_payload = await verify_credentials(token)
            # Store enriched user context with normalized teams
            if not isinstance(user_payload, dict):
                return True

            # First-Party
            from mcpgateway.auth import _get_auth_context_batched_sync  # pylint: disable=import-outside-toplevel
            from mcpgateway.cache.auth_cache import CachedAuthContext, get_auth_cache  # pylint: disable=import-outside-toplevel

            jti = user_payload.get("jti")
            user_email = user_payload.get("sub") or user_payload.get("email")
            nested_user = user_payload.get("user", {})
            nested_is_admin = nested_user.get("is_admin", False) if isinstance(nested_user, dict) else False
            is_admin = user_payload.get("is_admin", False) or nested_is_admin
            token_use = user_payload.get("token_use")
            db_user_is_admin = False
            user_record = None
            auth_cache = get_auth_cache() if settings.auth_cache_enabled else None
            cached_ctx: CachedAuthContext | None = None
            batched_auth_ctx: dict[str, Any] | None = None
            cached_team_ids: list[str] | None = None
            platform_admin_email = getattr(settings, "platform_admin_email", "admin@example.com")

            if user_email and auth_cache is not None:
                try:
                    cached_ctx = await auth_cache.get_auth_context(user_email, jti)
                    if cached_ctx is not None:
                        _record_mcp_auth_cache_event("auth_context_hit")
                        if cached_ctx.is_token_revoked:
                            _record_mcp_auth_cache_event("auth_context_hit_revoked")
                            return await self._send_error(detail="Token has been revoked", headers={"WWW-Authenticate": "Bearer"})

                        cached_user = cached_ctx.user
                        if cached_user and not cached_user.get("is_active", True):
                            _record_mcp_auth_cache_event("auth_context_hit_inactive")
                            return await self._send_error(detail="Account disabled", headers={"WWW-Authenticate": "Bearer"})

                        if cached_user:
                            db_user_is_admin = bool(cached_user.get("is_admin", False))
                        elif settings.require_user_in_db and user_email != platform_admin_email:
                            return await self._send_error(detail="User not found in database", headers={"WWW-Authenticate": "Bearer"})

                        if token_use == "session" and not is_admin:  # nosec B105 - token_use is a JWT claim type, not a password
                            cached_team_ids = await auth_cache.get_user_teams(f"{user_email}:True")
                            if cached_team_ids is not None:
                                _record_mcp_auth_cache_event("teams_cache_hit")
                    else:
                        _record_mcp_auth_cache_event("auth_context_miss")
                except HTTPException:
                    raise
                except Exception as cache_error:
                    _record_mcp_auth_cache_event("auth_context_cache_error")
                    logger.debug("MCP auth cache lookup failed for %s: %s", user_email, cache_error)
                    cached_ctx = None

            if user_email and cached_ctx is None and settings.auth_cache_batch_queries:
                try:
                    batched_auth_ctx = await asyncio.to_thread(_get_auth_context_batched_sync, user_email, jti)
                    _record_mcp_auth_cache_event("auth_context_batch_hit")
                    if batched_auth_ctx.get("is_token_revoked", False):
                        _record_mcp_auth_cache_event("auth_context_batch_revoked")
                        return await self._send_error(detail="Token has been revoked", headers={"WWW-Authenticate": "Bearer"})

                    cached_user = batched_auth_ctx.get("user")
                    if cached_user and not cached_user.get("is_active", True):
                        _record_mcp_auth_cache_event("auth_context_batch_inactive")
                        return await self._send_error(detail="Account disabled", headers={"WWW-Authenticate": "Bearer"})

                    if cached_user:
                        db_user_is_admin = bool(cached_user.get("is_admin", False))
                    elif settings.require_user_in_db and user_email != platform_admin_email:
                        return await self._send_error(detail="User not found in database", headers={"WWW-Authenticate": "Bearer"})

                    if auth_cache is not None:
                        await auth_cache.set_auth_context(
                            user_email,
                            jti,
                            CachedAuthContext(
                                user=cached_user,
                                personal_team_id=batched_auth_ctx.get("personal_team_id"),
                                is_token_revoked=bool(batched_auth_ctx.get("is_token_revoked", False)),
                            ),
                        )
                        if token_use == "session" and not is_admin:  # nosec B105 - token_use is a JWT claim type, not a password
                            cached_team_ids = list(batched_auth_ctx.get("team_ids") or [])
                            await auth_cache.set_user_teams(f"{user_email}:True", cached_team_ids)
                            _record_mcp_auth_cache_event("teams_batch_hit")
                except HTTPException:
                    raise
                except Exception as batch_error:
                    _record_mcp_auth_cache_event("auth_context_batch_error")
                    logger.warning("Batched MCP auth lookup failed for user=%s; falling back to individual checks: %s", user_email, batch_error)
                    batched_auth_ctx = None

            if user_email and cached_ctx is None and batched_auth_ctx is None:
                _record_mcp_auth_cache_event("auth_context_fallback")
                # First-Party
                from mcpgateway.auth import _check_token_revoked_sync, _get_user_by_email_sync  # pylint: disable=import-outside-toplevel

                is_revoked = False
                if jti:
                    try:
                        is_revoked = await asyncio.to_thread(_check_token_revoked_sync, jti)
                    except Exception as exc:
                        logger.warning("MCP token revocation check failed for jti=%s; allowing request (fail-open): %s", jti, exc)
                        is_revoked = False
                    if is_revoked:
                        return await self._send_error(detail="Token has been revoked", headers={"WWW-Authenticate": "Bearer"})

                user_lookup_succeeded = True
                try:
                    user_record = await asyncio.to_thread(_get_user_by_email_sync, user_email)
                except Exception as exc:
                    user_lookup_succeeded = False
                    user_record = None
                    logger.warning("MCP user lookup failed for user=%s; allowing request (fail-open): %s", user_email, exc)

                if user_lookup_succeeded:
                    if user_record and not getattr(user_record, "is_active", True):
                        return await self._send_error(detail="Account disabled", headers={"WWW-Authenticate": "Bearer"})
                    if user_record:
                        db_user_is_admin = bool(getattr(user_record, "is_admin", False))
                    if user_record is None and settings.require_user_in_db and user_email != platform_admin_email:
                        return await self._send_error(detail="User not found in database", headers={"WWW-Authenticate": "Bearer"})

                    if auth_cache is not None:
                        try:
                            await auth_cache.set_auth_context(
                                user_email,
                                jti,
                                CachedAuthContext(
                                    user=(
                                        {
                                            "email": user_record.email,
                                            "password_hash": user_record.password_hash,
                                            "full_name": user_record.full_name,
                                            "is_admin": bool(user_record.is_admin),
                                            "is_active": bool(user_record.is_active),
                                            "auth_provider": user_record.auth_provider,
                                            "password_change_required": bool(user_record.password_change_required),
                                            "email_verified_at": user_record.email_verified_at,
                                            "created_at": user_record.created_at,
                                            "updated_at": user_record.updated_at,
                                        }
                                        if user_record is not None
                                        else None
                                    ),
                                    personal_team_id=None,
                                    is_token_revoked=is_revoked,
                                ),
                            )
                        except Exception as cache_set_error:
                            logger.debug("Failed to cache MCP auth context for %s: %s", user_email, cache_set_error)

            if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
                # Session token: resolve teams from DB/cache
                if is_admin:
                    final_teams = None  # Admin bypass
                elif user_email:
                    if cached_team_ids is not None:
                        final_teams = cached_team_ids
                    elif batched_auth_ctx is not None:
                        final_teams = list(batched_auth_ctx.get("team_ids") or [])
                    else:
                        _record_mcp_auth_cache_event("teams_db_resolve")
                        # Resolve teams synchronously with L1 cache (StreamableHTTP uses sync context)
                        # First-Party
                        from mcpgateway.auth import _resolve_teams_from_db_sync  # pylint: disable=import-outside-toplevel

                        final_teams = _resolve_teams_from_db_sync(user_email, is_admin=False)
                        if auth_cache is not None and final_teams is not None:
                            try:
                                await auth_cache.set_user_teams(f"{user_email}:True", final_teams)
                            except Exception as cache_set_error:
                                logger.debug("Failed to cache MCP teams list for %s: %s", user_email, cache_set_error)
                else:
                    final_teams = []  # No email — public-only
            else:
                # API token or legacy: use embedded teams from JWT
                # First-Party
                from mcpgateway.auth import normalize_token_teams  # pylint: disable=import-outside-toplevel

                final_teams = normalize_token_teams(user_payload)

            # ═══════════════════════════════════════════════════════════════════════════
            # SECURITY: Validate team membership for team-scoped tokens
            # Users removed from a team should lose MCP access immediately, not at token expiry
            # ═══════════════════════════════════════════════════════════════════════════
            # Only validate membership for team-scoped tokens (non-empty teams list)
            # Skip for: public-only tokens ([]), admin unrestricted tokens (None)
            if final_teams and len(final_teams) > 0 and user_email:
                # Import lazily to avoid circular imports
                # Third-Party
                from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.cache.auth_cache import get_auth_cache  # pylint: disable=import-outside-toplevel
                from mcpgateway.db import EmailTeamMember  # pylint: disable=import-outside-toplevel

                auth_cache = get_auth_cache()

                # Check cache first (60s TTL)
                cached_result = auth_cache.get_team_membership_valid_sync(user_email, final_teams)
                if cached_result is False:
                    _record_mcp_auth_cache_event("team_membership_cache_reject")
                    logger.warning("MCP auth rejected: User %s no longer member of teams (cached)", user_email)
                    return await self._send_error(detail="Token invalid: User is no longer a member of the associated team", status_code=HTTP_403_FORBIDDEN)

                if cached_result is None:
                    _record_mcp_auth_cache_event("team_membership_cache_miss")
                    # Cache miss - query database
                    with SessionLocal() as db:
                        memberships = (
                            db.execute(
                                select(EmailTeamMember.team_id).where(
                                    EmailTeamMember.team_id.in_(final_teams),
                                    EmailTeamMember.user_email == user_email,
                                    EmailTeamMember.is_active.is_(True),
                                )
                            )
                            .scalars()
                            .all()
                        )

                        valid_team_ids = set(memberships)
                        missing_teams = set(final_teams) - valid_team_ids

                        if missing_teams:
                            logger.warning("MCP auth rejected: User %s no longer member of teams: %s", user_email, missing_teams)
                            auth_cache.set_team_membership_valid_sync(user_email, final_teams, False)
                            return await self._send_error(detail="Token invalid: User is no longer a member of the associated team", status_code=HTTP_403_FORBIDDEN)

                        # Cache positive result
                        auth_cache.set_team_membership_valid_sync(user_email, final_teams, True)
                else:
                    _record_mcp_auth_cache_event("team_membership_cache_hit")

            auth_user_ctx: dict[str, Any] = {
                "email": user_email,
                "teams": final_teams,
                "is_authenticated": True,
                "is_admin": is_admin,
                "permission_is_admin": db_user_is_admin or is_admin,
                "token_use": token_use,  # propagated for downstream RBAC (check_any_team)
            }
            # Extract scoped permissions from JWT for per-method enforcement
            jwt_scopes = user_payload.get("scopes") or {}
            jwt_scoped_perms = jwt_scopes.get("permissions") or [] if isinstance(jwt_scopes, dict) else []
            if jwt_scoped_perms:
                auth_user_ctx["scoped_permissions"] = jwt_scoped_perms
            scoped_server_id = jwt_scopes.get("server_id") if isinstance(jwt_scopes, dict) else None
            if isinstance(scoped_server_id, str) and scoped_server_id:
                auth_user_ctx["scoped_server_id"] = scoped_server_id
            user_context_var.set(auth_user_ctx)
        except HTTPException:
            # JWT verification failed (expired, malformed, bad signature, etc.)
            return await self._send_error(detail="Invalid authentication credentials", headers={"WWW-Authenticate": "Bearer"})
        except SQLAlchemyError:
            # DB failure during team resolution or membership validation
            logger.exception("Database error during MCP authentication")
            return await self._send_error(detail="Service unavailable — unable to verify authentication", status_code=503)
        except Exception:
            # Unexpected error during authentication — fail closed with 401.
            logger.exception("Unexpected error during MCP JWT authentication")
            return await self._send_error(detail="Authentication failed", headers={"WWW-Authenticate": "Bearer"})

        return True


async def streamable_http_auth(scope: Any, receive: Any, send: Any) -> bool:
    """Perform authentication check in middleware context (ASGI scope).

    Delegates to :class:`_StreamableHttpAuthHandler` which encapsulates the
    ASGI triple so helper methods can send error responses directly.

    Args:
        scope: The ASGI scope dictionary, which includes request metadata.
        receive: ASGI receive callable used to receive events.
        send: ASGI send callable used to send events (e.g. a 401 response).

    Returns:
        bool: True if authentication passes or is skipped.
              False if authentication fails and a 401 response is sent.

    Examples:
        >>> # Test streamable_http_auth function exists
        >>> callable(streamable_http_auth)
        True

        >>> # Test function signature
        >>> import inspect
        >>> sig = inspect.signature(streamable_http_auth)
        >>> list(sig.parameters.keys())
        ['scope', 'receive', 'send']
    """
    return await _StreamableHttpAuthHandler(scope, receive, send).authenticate()
