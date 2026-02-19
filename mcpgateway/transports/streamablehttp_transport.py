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
from uuid import uuid4

# Third-Party
import anyio
from fastapi.security.utils import get_authorization_scheme_param
import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import EventCallback, EventId, EventMessage, EventStore, StreamId
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    CompleteRequest,
    CompleteRequestParams,
    GetPromptRequest,
    GetPromptRequestParams,
    JSONRPCMessage,
    PaginatedRequestParams,
    ReadResourceRequest,
    ReadResourceRequestParams,
)
import orjson
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from starlette.types import Receive, Scope, Send

# First-Party
from mcpgateway.common.models import LogLevel
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.services.completion_service import CompletionService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.transports.redis_event_store import RedisEventStore
from mcpgateway.utils.gateway_access import build_gateway_auth_headers, check_gateway_access, extract_gateway_id_from_headers, GATEWAY_ID_HEADER
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.verify_credentials import require_auth_override, verify_credentials

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Precompiled regex for server ID extraction from path
_SERVER_ID_RE: Pattern[str] = re.compile(r"/servers/(?P<server_id>[a-fA-F0-9\-]+)/mcp")

# Initialize ToolService, PromptService, ResourceService, CompletionService and MCP Server
tool_service: ToolService = ToolService()
prompt_service: PromptService = PromptService()
resource_service: ResourceService = ResourceService()
completion_service: CompletionService = CompletionService()

mcp_app: Server[Any] = Server("mcp-streamable-http")

server_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("server_id", default="default_server_id")
request_headers_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("request_headers", default={})
user_context_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("user_context", default={})

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
            logger.warning(f"Event ID {last_event_id} not found in store")
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

async def update_headers_with_passthrough_headers(gateway: Any, request_headers: dict) -> dict:
    """
    Build headers for forwarding to remote gateway, including auth headers and passthrough headers.

    Args:
        gateway: Gateway ORM instance containing auth config and passthrough header list
        request_headers: Original request headers from the client

    Returns:
        Dictionary of headers to include in the proxied request to the remote gateway    
    """

    headers = build_gateway_auth_headers(gateway)

    # Forward passthrough headers if configured
    if gateway.passthrough_headers and request_headers:
        for header_name in gateway.passthrough_headers:
            header_value = request_headers.get(header_name.lower()) or request_headers.get(header_name)
            if header_value:
                headers[header_name] = header_value

    return headers



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
        headers = await update_headers_with_passthrough_headers(gateway=gateway, request_headers=request_headers)

        # Use MCP SDK to connect and list tools
        async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Prepare params with _meta if provided
                params = None
                if meta:
                    params = PaginatedRequestParams(_meta=meta)
                    logger.debug(f"Forwarding _meta to remote gateway: {meta}")

                # List tools with _meta forwarded
                result = await session.list_tools(params=params)
                return result.tools

    except Exception as e:
        logger.exception(f"Error proxying tools/list to gateway {gateway.id}: {e}")
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
        headers = await update_headers_with_passthrough_headers(gateway=gateway, request_headers=request_headers)

        logger.info(f"Proxying resources/list to gateway {gateway.id} at {gateway.url}")
        if meta:
            logger.debug(f"Forwarding _meta to remote gateway: {meta}")

        # Use MCP SDK to connect and list resources
        async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Prepare params with _meta if provided
                params = None
                if meta:
                    params = PaginatedRequestParams(_meta=meta)
                    logger.debug(f"Forwarding _meta to remote gateway: {meta}")

                # List resources with _meta forwarded
                result = await session.list_resources(params=params)

                logger.info(f"Received {len(result.resources)} resources from gateway {gateway.id}")
                return result.resources

    except Exception as e:
        logger.exception(f"Error proxying resources/list to gateway {gateway.id}: {e}")
        return []


async def _proxy_list_prompts_to_gateway(gateway: Any, request_headers: dict, user_context: dict, meta: Optional[Any] = None) -> List[types.Prompt]:  # pylint: disable=unused-argument
    """Proxy prompts/list request directly to remote MCP gateway using MCP SDK.

    Args:
        gateway: Gateway ORM instance
        request_headers: Request headers from client
        user_context: User context (not used - _meta comes from MCP SDK)
        meta: Request metadata (_meta) from the original request

    Returns:
        List of Prompt objects from remote server
    """
    try:
        headers = await update_headers_with_passthrough_headers(gateway=gateway, request_headers=request_headers)

        logger.info(f"Proxying prompts/list to gateway {gateway.id} at {gateway.url}")
        if meta:
            logger.debug(f"Forwarding _meta to remote gateway: {meta}")

        async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                params = None
                if meta:
                    params = PaginatedRequestParams(_meta=meta)

                result = await session.list_prompts(params=params)
                logger.info(f"Received {len(result.prompts)} prompts from gateway {gateway.id}")
                return result.prompts

    except Exception as e:
        logger.exception(f"Error proxying prompts/list to gateway {gateway.id}: {e}")
        return []


async def _proxy_get_prompt_to_gateway(
    gateway: Any, request_headers: dict, user_context: dict, name: str, arguments: dict[str, str] | None = None, meta: Optional[Any] = None
) -> Optional[types.GetPromptResult]:  # pylint: disable=unused-argument
    """Proxy prompts/get request directly to remote MCP gateway using MCP SDK.

    Uses session.send_request() when _meta is present (ClientSession.get_prompt()
    has no params argument), matching the pattern in _proxy_read_resource_to_gateway.

    Args:
        gateway: Gateway ORM instance
        request_headers: Request headers from client
        user_context: User context (not used - auth comes from gateway config)
        name: Prompt name to retrieve
        arguments: Optional argument substitutions
        meta: Request metadata (_meta) from the original request

    Returns:
        GetPromptResult from remote server, or None on failure
    """
    try:
        headers = await update_headers_with_passthrough_headers(gateway=gateway, request_headers=request_headers)

        logger.info(f"Proxying prompts/get '{name}' to gateway {gateway.id} at {gateway.url}")
        if meta:
            logger.debug(f"Forwarding _meta to remote gateway: {meta}")

        async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                if meta:
                    # ClientSession.get_prompt() has no params arg, use send_request to forward _meta
                    params_dict = GetPromptRequestParams(name=name, arguments=arguments).model_dump()
                    params_dict["_meta"] = meta
                    result = await session.send_request(
                        types.ClientRequest(GetPromptRequest(params=GetPromptRequestParams.model_validate(params_dict))),
                        types.GetPromptResult,
                    )
                else:
                    result = await session.get_prompt(name, arguments=arguments)

                logger.info(f"Received prompt '{name}' from gateway {gateway.id}")
                return result

    except Exception as e:
        logger.exception(f"Error proxying prompts/get '{name}' to gateway {gateway.id}: {e}")
        return None


async def _proxy_complete_to_gateway(  # pylint: disable=unused-argument
    gateway: Any,
    request_headers: dict,
    user_context: dict,
    ref: Any,
    argument: Any,
    context: Optional[Any] = None,
    meta: Optional[Any] = None,
) -> Optional[types.CompleteResult]:
    """Proxy completion/complete request directly to remote MCP gateway using MCP SDK.

    Uses session.send_request() when _meta is present (ClientSession.complete()
    has no params argument), matching the pattern in _proxy_read_resource_to_gateway.

    Args:
        gateway: Gateway ORM instance
        request_headers: Request headers from client
        user_context: User context (not used - auth comes from gateway config)
        ref: PromptReference or ResourceTemplateReference
        argument: CompletionArgument specifying name and partial value
        context: Optional CompletionContext with previously resolved arguments
        meta: Request metadata (_meta) from the original request

    Returns:
        CompleteResult from remote server, or None on failure
    """
    try:
        headers = await update_headers_with_passthrough_headers(gateway=gateway, request_headers=request_headers)

        logger.info(f"Proxying completion/complete to gateway {gateway.id} at {gateway.url}")
        if meta:
            logger.debug(f"Forwarding _meta to remote gateway: {meta}")

        async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                if meta:
                    # ClientSession.complete() has no params arg, use send_request to forward _meta
                    params_dict = CompleteRequestParams(ref=ref, argument=argument, context=context).model_dump()
                    params_dict["_meta"] = meta
                    result = await session.send_request(
                        types.ClientRequest(CompleteRequest(params=CompleteRequestParams.model_validate(params_dict))),
                        types.CompleteResult,
                    )
                else:
                    ref_dict = ref.model_dump() if hasattr(ref, "model_dump") else ref
                    arg_dict = argument.model_dump() if hasattr(argument, "model_dump") else argument
                    context_args = context.arguments if context and hasattr(context, "arguments") else None
                    result = await session.complete(
                        ref=ref_dict,
                        argument=arg_dict,
                        context_arguments=context_args,
                    )

                logger.info(f"Received completion result from gateway {gateway.id}")
                return result

    except Exception as e:
        logger.exception(f"Error proxying completion/complete to gateway {gateway.id}: {e}")
        return None


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
        # Get request headers
        request_headers = request_headers_var.get()

        headers = await update_headers_with_passthrough_headers(gateway=gateway, request_headers=request_headers)

        # Forward X-Context-Forge-Gateway-Id header
        gw_id = extract_gateway_id_from_headers(request_headers)
        if gw_id:
            headers[GATEWAY_ID_HEADER] = gw_id

        logger.info(f"Proxying resources/read for {resource_uri} to gateway {gateway.id} at {gateway.url}")
        if meta:
            logger.debug(f"Forwarding _meta to remote gateway: {meta}")

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

                logger.info(f"Received {len(result.contents)} content items from gateway {gateway.id} for resource {resource_uri}")
                return result.contents

    except Exception as e:
        logger.exception(f"Error proxying resources/read to gateway {gateway.id} for resource {resource_uri}: {e}")
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
        Exception: Re-raised after logging to allow MCP SDK to convert to JSON-RPC error response.

    Raises:
        Exception: Re-raises exceptions encountered during tool invocation after logging.

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
                        logger.warning(f"Access denied to gateway {gateway_id_from_header} in direct_proxy mode for user {user_email}")
                        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Tool not found: {name}")], isError=True)

                    logger.info(f"Using direct_proxy mode for tool '{name}' via gateway {gateway_id_from_header}")

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
            logger.error(f"Direct proxy mode failed for gateway {gateway_id_from_header}: {e}")
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
                logger.error(f"Failed to pre-register session mapping for Streamable HTTP: {e}")

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
                                converted.append(types.TextContent(type="text", text=str(item)))
                        except Exception:
                            converted.append(types.TextContent(type="text", text=str(item)))
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
                logger.warning(f"No content returned by tool: {name}")
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
                    unstructured.append(types.TextContent(type="text", text=str(content.model_dump(by_alias=True, mode="json"))))

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
        logger.exception(f"Error calling tool '{name}': {e}")
        # Re-raise the exception so the MCP SDK can properly convert it to an error response
        # This ensures error details are propagated to the client instead of returning empty results
        raise


async def _get_request_context_or_default() -> Tuple[str, dict[str, Any], dict[str, Any]]:
    """Retrieve request context information for the current execution.

    This function attempts to obtain the `server_id`, request headers, and
    user context from ContextVars (fast path). If the ContextVars contain
    default values—indicating a stateful session where context propagation
    may not have occurred—it falls back to extracting the information from
    `mcp_app.request_context`.

    The fallback logic:
    - Extracts `server_id` from the request URL path.
    - Copies request headers from the underlying request object.
    - Attempts to recover user context using the authorization header or
      JWT token stored in cookies.

    If recovery fails at any point, default ContextVar values are returned.

    Returns:
        Tuple[str, dict[str, Any], dict[str, Any]]: A tuple containing:
            - server_id: The resolved server identifier.
            - request_headers: A dictionary of request headers.
            - user_context: A dictionary representing the authenticated user
              context (empty if anonymous or recovery fails).
    """
    # 1. Try context vars first (fast path)
    s_id = server_id_var.get()

    # Check if context vars are populated with real data (not defaults)
    if s_id != "default_server_id":
        return s_id, request_headers_var.get(), user_context_var.get()

    # 2. Fallback to mcp_app.request_context (stateful session path)
    try:
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
        auth_header = req_headers.get("authorization")
        # In stateful session, cookie might be more reliable
        cookie_token = request.cookies.get("jwt_token")

        try:
            raw_payload = await require_auth_override(auth_header=auth_header, jwt_token=cookie_token, request=request)
            if isinstance(raw_payload, str):  # "anonymous"
                user_ctx = {}
            elif isinstance(raw_payload, dict):
                # Normalize raw JWT payload to canonical user context shape
                # (matches streamable_http_auth normalization at lines 2155-2259)
                user_ctx = _normalize_jwt_payload(raw_payload)
            else:
                user_ctx = {}
        except Exception as e:
            logger.warning(f"Failed to recover user context in stateful session: {e}")
            user_ctx = {}

        return s_id, req_headers, user_ctx

    except LookupError:
        # Not in a request context
        return s_id, request_headers_var.get(), user_context_var.get()
    except Exception as e:
        logger.error(f"Error recovering context in stateful session: {e}", exc_info=True)
        return s_id, request_headers_var.get(), user_context_var.get()


def _normalize_jwt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw JWT payload to the canonical user context shape.

    Converts raw JWT fields (sub, token_use, nested user.is_admin) into the
    canonical ``{email, teams, is_admin, is_authenticated}`` dict that MCP
    handlers expect.  This mirrors the normalization performed by
    ``streamable_http_auth`` so that the stateful-session fallback path in
    ``_get_request_context_or_default`` returns an identical shape.

    Args:
        payload: Raw JWT payload dict from ``require_auth_override``.

    Returns:
        Canonical user context dict with keys email, teams, is_admin, is_authenticated.
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

    return {
        "email": email,
        "teams": final_teams,
        "is_admin": is_admin,
        "is_authenticated": True,
    }


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
                            logger.warning(f"Access denied to gateway {gateway_id} in direct_proxy mode for user {user_email}")
                            return []  # Return empty list for unauthorized access

                        # Direct proxy mode: forward request to remote MCP server
                        # Get _meta from request context if available
                        meta = None
                        try:
                            request_ctx = mcp_app.request_context
                            meta = request_ctx.meta
                            logger.info(f"[LIST TOOLS] Using direct_proxy mode for server {server_id}, gateway {gateway.id} (from {GATEWAY_ID_HEADER} header). Meta Attached: {meta is not None}")
                        except (LookupError, AttributeError) as e:
                            logger.debug(f"No request context available for _meta extraction: {e}")

                        return await _proxy_list_tools_to_gateway(gateway, request_headers, user_context, meta)
                    if gateway:
                        logger.debug(f"Gateway {gateway_id} found but not in direct_proxy mode (mode: {getattr(gateway, 'gateway_mode', 'cache')}), using cache mode")
                    else:
                        logger.warning(f"Gateway {gateway_id} specified in {GATEWAY_ID_HEADER} header not found")

                # Check if server exists for cache mode
                # Third-Party
                from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.db import Server as DbServer  # pylint: disable=import-outside-toplevel

                server = db.execute(select(DbServer).where(DbServer.id == server_id)).scalar_one_or_none()
                if not server:
                    logger.warning(f"Server {server_id} not found in database")
                    return []

                # Default cache mode: use database
                tools = await tool_service.list_server_tools(db, server_id, user_email=user_email, token_teams=token_teams, _request_headers=request_headers)
                return [types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema, outputSchema=tool.output_schema, annotations=tool.annotations) for tool in tools]
        except Exception as e:
            logger.error(f"Error listing tools:{e}")
            return []
    else:
        try:
            async with get_db() as db:
                tools, _ = await tool_service.list_tools(db, include_inactive=False, limit=0, user_email=user_email, token_teams=token_teams, _request_headers=request_headers)
                return [types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema, outputSchema=tool.output_schema, annotations=tool.annotations) for tool in tools]
        except Exception as e:
            logger.exception(f"Error listing tools:{e}")
            return []


@mcp_app.list_prompts()
async def list_prompts() -> List[types.Prompt]:
    """
    Lists all prompts available to the MCP Server.

    Returns:
        A list of Prompt objects containing metadata such as name, description, and arguments.
        Logs and returns an empty list on failure.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(list_prompts)
        >>> list(sig.parameters.keys())
        []
        >>> sig.return_annotation
        typing.List[mcp.types.Prompt]
    """
    server_id, request_headers, user_context = await _get_request_context_or_default()

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

    if server_id:
        try:
            async with get_db() as db:
                gateway_id = extract_gateway_id_from_headers(request_headers)

                if gateway_id:
                    # Third-Party
                    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                    # First-Party
                    from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                    gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
                    if gateway and getattr(gateway, "gateway_mode", "cache") == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                        if not await check_gateway_access(db, gateway, user_email, token_teams):
                            logger.warning(f"Access denied to gateway {gateway_id} in direct_proxy mode for user {user_email}")
                            return []

                        meta = None
                        try:
                            request_ctx = mcp_app.request_context
                            meta = request_ctx.meta
                            logger.info(f"[LIST PROMPTS] Using direct_proxy mode for server {server_id}, gateway {gateway.id}. Meta Attached: {meta is not None}")
                        except (LookupError, AttributeError) as e:
                            logger.debug(f"No request context available for _meta extraction: {e}")

                        return await _proxy_list_prompts_to_gateway(gateway, request_headers, user_context, meta)

                    if gateway:
                        logger.debug(f"Gateway {gateway_id} found but not in direct_proxy mode (mode: {getattr(gateway, 'gateway_mode', 'cache')}), using cache mode")
                    else:
                        logger.warning(f"Gateway {gateway_id} specified in {GATEWAY_ID_HEADER} header not found")

                prompts = await prompt_service.list_server_prompts(db, server_id, user_email=user_email, token_teams=token_teams)
                return [types.Prompt(name=prompt.name, description=prompt.description, arguments=prompt.arguments) for prompt in prompts]
        except Exception as e:
            logger.exception(f"Error listing Prompts:{e}")
            return []
    else:
        try:
            async with get_db() as db:
                prompts, _ = await prompt_service.list_prompts(db, include_inactive=False, limit=0, user_email=user_email, token_teams=token_teams)
                return [types.Prompt(name=prompt.name, description=prompt.description, arguments=prompt.arguments) for prompt in prompts]
        except Exception as e:
            logger.exception(f"Error listing prompts:{e}")
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

    Logs exceptions if any errors occur during retrieval.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(get_prompt)
        >>> list(sig.parameters.keys())
        ['prompt_id', 'arguments']
        >>> sig.return_annotation.__name__
        'GetPromptResult'
    """
    server_id, request_headers, user_context = await _get_request_context_or_default()

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
            # Check for direct_proxy mode (uses the same DB session as cache path)
            if server_id:
                gateway_id = extract_gateway_id_from_headers(request_headers)

                if gateway_id:
                    # Third-Party
                    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                    # First-Party
                    from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                    gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
                    if gateway and getattr(gateway, "gateway_mode", "cache") == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                        if not await check_gateway_access(db, gateway, user_email, token_teams):
                            logger.warning(f"Access denied to gateway {gateway_id} in direct_proxy mode for user {user_email}")
                            return types.GetPromptResult(messages=[], description=None)

                        logger.info(f"[GET PROMPT] Using direct_proxy mode for server {server_id}, gateway {gateway.id}")
                        result = await _proxy_get_prompt_to_gateway(gateway, request_headers, user_context, name=prompt_id, arguments=arguments, meta=meta_data)
                        if not result or not result.messages:
                            logger.warning(f"No content returned by upstream prompt: {prompt_id}")
                            return types.GetPromptResult(messages=[], description=None)
                        message_dicts = [message.model_dump() for message in result.messages]
                        return types.GetPromptResult(messages=message_dicts, description=result.description)

                    if gateway:
                        logger.debug(f"Gateway {gateway_id} found but not in direct_proxy mode (mode: {getattr(gateway, 'gateway_mode', 'cache')}), using cache mode")
                    else:
                        logger.warning(f"Gateway {gateway_id} specified in {GATEWAY_ID_HEADER} header not found")

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
                logger.exception(f"Error getting prompt '{prompt_id}': {e}")
                return []
            if not result or not result.messages:
                logger.warning(f"No content returned by prompt: {prompt_id}")
                return []
            message_dicts = [message.model_dump() for message in result.messages]
            return types.GetPromptResult(messages=message_dicts, description=result.description)
    except Exception as e:
        logger.exception(f"Error getting prompt '{prompt_id}': {e}")
        return []


@mcp_app.list_resources()
async def list_resources() -> List[types.Resource]:
    """
    Lists all resources available to the MCP Server.

    Returns:
        A list of Resource objects containing metadata such as uri, name, description, and mimeType.
        Logs and returns an empty list on failure.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(list_resources)
        >>> list(sig.parameters.keys())
        []
        >>> sig.return_annotation
        typing.List[mcp.types.Resource]
    """
    server_id, request_headers, user_context = await _get_request_context_or_default()

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
                            logger.warning(f"Access denied to gateway {gateway_id} in direct_proxy mode for user {user_email}")
                            return []  # Return empty list for unauthorized access

                        # Direct proxy mode: forward request to remote MCP server
                        # Get _meta from request context if available
                        meta = None
                        try:
                            request_ctx = mcp_app.request_context
                            meta = request_ctx.meta
                            logger.info(f"[LIST RESOURCES] Using direct_proxy mode for server {server_id}, gateway {gateway.id} (from {GATEWAY_ID_HEADER} header). Meta Attached: {meta is not None}")
                        except (LookupError, AttributeError) as e:
                            logger.debug(f"No request context available for _meta extraction: {e}")

                        return await _proxy_list_resources_to_gateway(gateway, request_headers, user_context, meta)
                    if gateway:
                        logger.debug(f"Gateway {gateway_id} found but not in direct_proxy mode (mode: {gateway.gateway_mode}), using cache mode")
                    else:
                        logger.warning(f"Gateway {gateway_id} specified in {GATEWAY_ID_HEADER} header not found")

                # Default cache mode: use database
                resources = await resource_service.list_server_resources(db, server_id, user_email=user_email, token_teams=token_teams)
                return [types.Resource(uri=resource.uri, name=resource.name, description=resource.description, mimeType=resource.mime_type) for resource in resources]
        except Exception as e:
            logger.exception(f"Error listing Resources:{e}")
            return []
    else:
        try:
            async with get_db() as db:
                resources, _ = await resource_service.list_resources(db, include_inactive=False, limit=0, user_email=user_email, token_teams=token_teams)
                return [types.Resource(uri=resource.uri, name=resource.name, description=resource.description, mimeType=resource.mime_type) for resource in resources]
        except Exception as e:
            logger.exception(f"Error listing resources:{e}")
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
                        logger.warning(f"Access denied to gateway {gateway_id} in direct_proxy mode for user {user_email}")
                        return ""

                    # Direct proxy mode: forward request to remote MCP server
                    # Get _meta from request context if available
                    meta = None
                    try:
                        request_ctx = mcp_app.request_context
                        meta = request_ctx.meta
                        logger.info(f"Using direct_proxy mode for resources/read {resource_uri}, server {server_id}, gateway {gateway.id} (from {GATEWAY_ID_HEADER} header), forwarding _meta: {meta}")
                    except (LookupError, AttributeError) as e:
                        logger.debug(f"No request context available for _meta extraction: {e}")

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
                    logger.debug(f"Gateway {gateway_id} found but not in direct_proxy mode (mode: {gateway.gateway_mode}), using cache mode")
                else:
                    logger.warning(f"Gateway {gateway_id} specified in {GATEWAY_ID_HEADER} header not found")

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
                logger.exception(f"Error reading resource '{resource_uri}': {e}")
                return ""

            # Return blob content if available (binary resources)
            if result and result.blob:
                return result.blob

            # Return text content if available (text resources)
            if result and result.text:
                return result.text

            # No content found
            logger.warning(f"No content returned by resource: {resource_uri}")
            return ""
    except Exception as e:
        logger.exception(f"Error reading resource '{resource_uri}': {e}")
        return ""


@mcp_app.list_resource_templates()
async def list_resource_templates() -> List[Dict[str, Any]]:
    """
    Lists all resource templates available to the MCP Server.

    Returns:
        List[types.ResourceTemplate]: A list of resource templates with their URIs and metadata.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(list_resource_templates)
        >>> list(sig.parameters.keys())
        []
        >>> sig.return_annotation.__origin__.__name__
        'list'
    """
    # Extract filtering parameters from user context (same pattern as list_resources)
    _, _, user_context = await _get_request_context_or_default()
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

    try:
        async with get_db() as db:
            try:
                resource_templates = await resource_service.list_resource_templates(
                    db,
                    user_email=user_email,
                    token_teams=token_teams,
                )
                return [template.model_dump(by_alias=True) for template in resource_templates]
            except Exception as e:
                logger.exception(f"Error listing resource templates: {e}")
                return []
    except Exception as e:
        logger.exception(f"Error listing resource templates: {e}")
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
    """
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
    except Exception as e:
        logger.exception(f"Error setting logging level: {e}")
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
        Exception: If completion handling fails internally. The method
            logs the exception and returns an empty completion structure.
    """
    meta_data = None
    try:
        ctx = mcp_app.request_context
        if ctx and ctx.meta is not None:
            meta_data = ctx.meta.model_dump()
    except LookupError:
        logger.debug("No active request context found for _meta extraction in completion/complete")

    server_id, request_headers, user_context = await _get_request_context_or_default()

    try:
        async with get_db() as db:
            # Check for direct_proxy mode (uses the same DB session as cache path)
            if server_id:
                gateway_id = extract_gateway_id_from_headers(request_headers)

                if gateway_id:
                    # Third-Party
                    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                    # First-Party
                    from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                    gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
                    if gateway and getattr(gateway, "gateway_mode", "cache") == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                        user_email = user_context.get("email") if user_context else None
                        token_teams = user_context.get("teams") if user_context else None

                        if not await check_gateway_access(db, gateway, user_email, token_teams):
                            logger.warning(f"Access denied to gateway {gateway_id} in direct_proxy mode for user {user_email}")
                            return types.Completion(values=[], total=0, hasMore=False)

                        logger.info(f"[COMPLETE] Using direct_proxy mode for server {server_id}, gateway {gateway.id}")
                        result = await _proxy_complete_to_gateway(
                            gateway,
                            request_headers,
                            user_context,
                            ref=ref,
                            argument=argument,
                            context=context,
                            meta=meta_data,
                        )
                        if result is None:
                            return types.Completion(values=[], total=0, hasMore=False)
                        if isinstance(result, dict):
                            return types.Completion(**result.get("completion", result))
                        if hasattr(result, "completion"):
                            comp = result.completion
                            return comp if isinstance(comp, types.Completion) else types.Completion(**comp.model_dump())
                        return result

                    if gateway:
                        logger.debug(f"Gateway {gateway_id} not in direct_proxy mode, using cache")
                    else:
                        logger.warning(f"Gateway {gateway_id} not found")

            params = {
                "ref": ref.model_dump() if hasattr(ref, "model_dump") else ref,
                "argument": argument.model_dump() if hasattr(argument, "model_dump") else argument,
                "context": context.model_dump() if hasattr(context, "model_dump") else context,
                "_meta": meta_data,
            }

            result = await completion_service.handle_completion(db, params)

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
        logger.exception(f"Error handling completion: {e}")
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
            # Use Redis event store for single-worker stateful deployments
            if settings.cache_type == "redis" and settings.redis_url:
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
        logger.debug(f"[STATEFUL] Streamable HTTP {method} {path} | MCP-Session-Id: {mcp_session_id} | Query: {query_string} | Stateful: {settings.use_stateful_sessions}")

        # Note: mcp-session-id from client is used for gateway-internal session affinity
        # routing (stored in request_headers_var), but is NOT renamed or forwarded to
        # upstream servers - it's a gateway-side concept, not an end-to-end semantic header

        # Multi-worker session affinity: check if we should forward to another worker
        # This must happen BEFORE the SDK's session manager handles the request
        is_internally_forwarded = headers.get("x-forwarded-internally") == "true"

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
        logger.debug(f"[SESSION_MGR_DEBUG] Manager ID: {id(self.session_manager)}")

        if is_internally_forwarded:
            logger.debug(f"[HTTP_AFFINITY_FORWARDED] Received forwarded request | Method: {method} | Session: {mcp_session_id}")

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
                logger.debug(f"[HTTP_AFFINITY_FORWARDED] Routing to /rpc | Method: {rpc_method}")

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
                    logger.debug(f"[HTTP_AFFINITY_FORWARDED] Injected server_id {server_id} into /rpc params")

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
                    logger.debug(f"[HTTP_AFFINITY_FORWARDED] Response sent | Status: {response.status_code}")
                    return
            except Exception as e:
                logger.error(f"[HTTP_AFFINITY_FORWARDED] Error routing to /rpc: {e}")
                # Fall through to SDK handling as fallback

        if settings.mcpgateway_session_affinity_enabled and settings.use_stateful_sessions and mcp_session_id != "not-provided" and not is_internally_forwarded:
            try:
                # First-Party - lazy import to avoid circular dependencies
                # First-Party
                from mcpgateway.services.mcp_session_pool import get_mcp_session_pool, WORKER_ID  # pylint: disable=import-outside-toplevel

                pool = get_mcp_session_pool()
                owner = await pool.get_streamable_http_session_owner(mcp_session_id)
                logger.debug(f"[HTTP_AFFINITY_CHECK] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Owner from Redis: {owner}")

                if owner and owner != WORKER_ID:
                    # Session owned by another worker - forward the entire HTTP request
                    logger.info(f"[HTTP_AFFINITY] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Owner: {owner} | Forwarding HTTP request")

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
                        logger.debug(f"[HTTP_AFFINITY] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Forwarded response sent to client")
                        return

                    # Forwarding failed - fall through to local handling
                    # This may result in "session not found" but it's better than no response
                    logger.debug(f"[HTTP_AFFINITY] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Forwarding failed, falling back to local")

                elif owner == WORKER_ID and method == "POST":
                    # We own this session - route POST requests to /rpc to avoid SDK session issues
                    # The SDK's _server_instances gets cleared between requests, so we can't rely on it
                    logger.debug(f"[HTTP_AFFINITY_LOCAL] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Owner is us, routing to /rpc")

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
                        logger.debug(f"[HTTP_AFFINITY_LOCAL] Routing to /rpc | Method: {rpc_method}")

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
                            logger.debug(f"[HTTP_AFFINITY_LOCAL] Injected server_id {server_id} into /rpc params")

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
                            logger.debug(f"[HTTP_AFFINITY_LOCAL] Response sent | Status: {response.status_code}")
                            return
                    except Exception as e:
                        logger.error(f"[HTTP_AFFINITY_LOCAL] Error routing to /rpc: {e}")
                        # Fall through to SDK handling as fallback

            except RuntimeError:
                # Pool not initialized - proceed with local handling
                pass
            except Exception as e:
                logger.debug(f"Session affinity check failed, proceeding locally: {e}")

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

        try:
            await self.session_manager.handle_request(scope, receive, send_with_capture)
            logger.debug(f"[STATEFUL] Streamable HTTP request completed successfully | Session: {mcp_session_id}")

            # Register ownership for the session we just handled
            # This captures both existing sessions (mcp_session_id from request)
            # and new sessions (captured_session_id from response)
            logger.debug(
                f"[HTTP_AFFINITY_DEBUG] affinity_enabled={settings.mcpgateway_session_affinity_enabled} stateful={settings.use_stateful_sessions} captured={captured_session_id} mcp_session_id={mcp_session_id}"
            )
            if settings.mcpgateway_session_affinity_enabled and settings.use_stateful_sessions:
                session_to_register = captured_session_id or (mcp_session_id if mcp_session_id != "not-provided" else None)
                logger.debug(f"[HTTP_AFFINITY_DEBUG] session_to_register={session_to_register}")
                if session_to_register:
                    try:
                        # First-Party - lazy import to avoid circular dependencies
                        # First-Party
                        from mcpgateway.services.mcp_session_pool import get_mcp_session_pool, WORKER_ID  # pylint: disable=import-outside-toplevel

                        pool = get_mcp_session_pool()
                        await pool.register_pool_session_owner(session_to_register)
                        logger.debug(f"[HTTP_AFFINITY_SDK] Worker {WORKER_ID} | Session {session_to_register[:8]}... | Registered ownership after SDK handling")
                    except Exception as e:
                        logger.debug(f"[HTTP_AFFINITY_DEBUG] Exception during registration: {e}")
                        logger.warning(f"Failed to register session ownership: {e}")

        except anyio.ClosedResourceError:
            # Expected when client closes one side of the stream (normal lifecycle)
            logger.debug("Streamable HTTP connection closed by client (ClosedResourceError)")
        except Exception as e:
            logger.error(f"[STATEFUL] Streamable HTTP request failed | Session: {mcp_session_id} | Error: {e}")
            logger.exception(f"Error handling streamable HTTP request: {e}")
            raise


# ------------------------- Authentication for /mcp routes ------------------------------


async def streamable_http_auth(scope: Any, receive: Any, send: Any) -> bool:
    """
    Perform authentication check in middleware context (ASGI scope).

    This function is intended to be used in middleware wrapping ASGI apps.
    It authenticates only requests targeting paths ending in "/mcp" or "/mcp/".

    Behavior:
    - If the path does not end with "/mcp", authentication is skipped.
    - If mcp_require_auth=True (strict mode):
      - Requests without valid auth are rejected with 401.
    - If mcp_require_auth=False (default, permissive mode):
      - Requests without auth are allowed but get public-only access (token_teams=[]).
      - Valid tokens get full scoped access based on their teams.
    - If a Bearer token is present, it is verified using `verify_credentials`.
    - If verification fails and mcp_require_auth=True, a 401 Unauthorized JSON response is sent.

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
    path = scope.get("path", "")
    if not path.endswith("/mcp") and not path.endswith("/mcp/"):
        # No auth needed for other paths in this middleware usage
        return True

    headers = Headers(scope=scope)

    # CORS preflight (OPTIONS + Origin + Access-Control-Request-Method) cannot carry auth headers
    method = scope.get("method", "")
    if method == "OPTIONS":
        origin = headers.get("origin")
        if origin and headers.get("access-control-request-method"):
            return True

    authorization = headers.get("authorization")
    proxy_user = headers.get(settings.proxy_user_header) if settings.trust_proxy_auth else None

    # Determine authentication strategy based on settings
    if not settings.mcp_client_auth_enabled and settings.trust_proxy_auth:
        # Client auth disabled → allow proxy header
        if proxy_user:
            # Set enriched user context for proxy-authenticated sessions
            user_context_var.set(
                {
                    "email": proxy_user,
                    "teams": [],  # Proxy auth has no team context
                    "is_authenticated": True,
                    "is_admin": False,
                }
            )
            return True  # Trusted proxy supplied user

    # --- Standard JWT authentication flow (client auth enabled) ---
    token: str | None = None
    if authorization:
        scheme, credentials = get_authorization_scheme_param(authorization)
        if scheme.lower() == "bearer" and credentials:
            token = credentials

    try:
        if token is None:
            raise Exception("No token provided")
        user_payload = await verify_credentials(token)
        # Store enriched user context with normalized teams
        if isinstance(user_payload, dict):
            # Resolve teams based on token_use claim
            token_use = user_payload.get("token_use")
            if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
                # Session token: resolve teams from DB/cache
                user_email_for_teams = user_payload.get("sub") or user_payload.get("email")
                is_admin_flag = user_payload.get("is_admin", False) or user_payload.get("user", {}).get("is_admin", False)
                if is_admin_flag:
                    final_teams = None  # Admin bypass
                elif user_email_for_teams:
                    # Resolve teams synchronously with L1 cache (StreamableHTTP uses sync context)
                    # First-Party
                    from mcpgateway.auth import _resolve_teams_from_db_sync  # pylint: disable=import-outside-toplevel

                    final_teams = _resolve_teams_from_db_sync(user_email_for_teams, is_admin=False)
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
            user_email = user_payload.get("sub") or user_payload.get("email")
            is_admin = user_payload.get("is_admin", False) or user_payload.get("user", {}).get("is_admin", False)

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
                    logger.warning(f"MCP auth rejected: User {user_email} no longer member of teams (cached)")
                    response = ORJSONResponse(
                        {"detail": "Token invalid: User is no longer a member of the associated team"},
                        status_code=HTTP_403_FORBIDDEN,
                    )
                    await response(scope, receive, send)
                    return False

                if cached_result is None:
                    # Cache miss - query database
                    db = SessionLocal()
                    try:
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
                            logger.warning(f"MCP auth rejected: User {user_email} no longer member of teams: {missing_teams}")
                            auth_cache.set_team_membership_valid_sync(user_email, final_teams, False)
                            response = ORJSONResponse(
                                {"detail": "Token invalid: User is no longer a member of the associated team"},
                                status_code=HTTP_403_FORBIDDEN,
                            )
                            await response(scope, receive, send)
                            return False

                        # Cache positive result
                        auth_cache.set_team_membership_valid_sync(user_email, final_teams, True)
                    finally:
                        # Rollback any implicit transaction before closing to prevent
                        # idle-in-transaction state if the connection is returned to pool
                        try:
                            db.rollback()
                        except Exception:
                            pass  # nosec B110 - Best effort rollback
                        db.close()

            user_context_var.set(
                {
                    "email": user_email,
                    "teams": final_teams,
                    "is_authenticated": True,
                    "is_admin": is_admin,
                }
            )
        elif proxy_user:
            # If using proxy auth, store the proxy user
            user_context_var.set(
                {
                    "email": proxy_user,
                    "teams": [],
                    "is_authenticated": True,
                    "is_admin": False,
                }
            )
    except Exception:
        # If JWT auth fails but we have a trusted proxy user, use that
        if settings.trust_proxy_auth and proxy_user:
            user_context_var.set(
                {
                    "email": proxy_user,
                    "teams": [],
                    "is_authenticated": True,
                    "is_admin": False,
                }
            )
            return True  # Fall back to proxy authentication

        # Check mcp_require_auth setting to determine behavior
        if settings.mcp_require_auth:
            # Strict mode: require authentication, return 401 for unauthenticated requests
            response = ORJSONResponse(
                {"detail": "Authentication required for MCP endpoints"},
                status_code=HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return False

        # Permissive mode (default): allow unauthenticated access with public-only scope
        # Set context indicating unauthenticated user with public-only access (teams=[])
        user_context_var.set(
            {
                "email": None,
                "teams": [],  # Empty list = public-only access
                "is_authenticated": False,
                "is_admin": False,
            }
        )
        return True  # Allow request to proceed with public-only access

    return True
