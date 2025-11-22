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
    ...     EventEntry, InMemoryEventStore, SessionManagerWrapper
    ... )
    >>>
    >>> # Verify classes are available
    >>> EventEntry.__name__
    'EventEntry'
    >>> InMemoryEventStore.__name__
    'InMemoryEventStore'
    >>> SessionManagerWrapper.__name__
    'SessionManagerWrapper'
"""

# Standard
from collections import deque
from contextlib import asynccontextmanager, AsyncExitStack
import contextvars
from dataclasses import dataclass
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from uuid import uuid4

# Third-Party
import anyio
from fastapi.security.utils import get_authorization_scheme_param
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import EventCallback, EventId, EventMessage, EventStore, StreamId
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import JSONRPCMessage
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED
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
from mcpgateway.utils.verify_credentials import verify_credentials

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

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
        >>> entry = EventEntry(event_id="test-123", stream_id="stream-456", message=message)
        >>> entry.event_id
        'test-123'
        >>> entry.stream_id
        'stream-456'
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


class InMemoryEventStore(EventStore):
    """
    Simple in-memory implementation of the EventStore interface for resumability.
    This is primarily intended for examples and testing, not for production use
    where a persistent storage solution would be more appropriate.

    This implementation keeps only the last N events per stream for memory efficiency.

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
        # for maintaining last N events per stream
        self.streams: dict[StreamId, deque[EventEntry]] = {}
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

            >>> # Test deque overflow
            >>> store2 = InMemoryEventStore(max_events_per_stream=2)
            >>> msg1 = JSONRPCMessage(jsonrpc="2.0", method="m1", id=1)
            >>> msg2 = JSONRPCMessage(jsonrpc="2.0", method="m2", id=2)
            >>> msg3 = JSONRPCMessage(jsonrpc="2.0", method="m3", id=3)
            >>> id1 = asyncio.run(store2.store_event("stream-2", msg1))
            >>> id2 = asyncio.run(store2.store_event("stream-2", msg2))
            >>> # Now deque is full, adding third will remove first
            >>> id3 = asyncio.run(store2.store_event("stream-2", msg3))
            >>> len(store2.streams["stream-2"])
            2
            >>> id1 in store2.event_index  # First event removed
            False
            >>> id2 in store2.event_index and id3 in store2.event_index
            True
        """
        event_id = str(uuid4())
        event_entry = EventEntry(event_id=event_id, stream_id=stream_id, message=message)

        # Get or create deque for this stream
        if stream_id not in self.streams:
            self.streams[stream_id] = deque(maxlen=self.max_events_per_stream)

        # If deque is full, the oldest event will be automatically removed
        # We need to remove it from the event_index as well
        if len(self.streams[stream_id]) == self.max_events_per_stream:
            oldest_event = self.streams[stream_id][0]
            self.event_index.pop(oldest_event.event_id, None)

        # Add new event
        self.streams[stream_id].append(event_entry)
        self.event_index[event_id] = event_entry

        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> Union[StreamId, None]:
        """
        Replays events that occurred after the specified event ID.

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
        if last_event_id not in self.event_index:
            logger.warning(f"Event ID {last_event_id} not found in store")
            return None

        # Get the stream and find events after the last one
        last_event = self.event_index[last_event_id]
        stream_id = last_event.stream_id
        stream_events = self.streams.get(last_event.stream_id, deque())

        # Events in deque are already in chronological order
        found_last = False
        for event in stream_events:
            if found_last:
                await send_callback(EventMessage(event.message, event.event_id))
            elif event.event_id == last_event_id:
                found_last = True

        return stream_id


# ------------------------------ Streamable HTTP Transport ------------------------------


@asynccontextmanager
async def get_db() -> AsyncGenerator[Session, Any]:
    """
    Asynchronous context manager for database sessions.

    Yields:
        A database session instance from SessionLocal.
        Ensures the session is closed after use.

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


@mcp_app.call_tool()
async def call_tool(name: str, arguments: dict) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
    """
    Handles tool invocation via the MCP Server.

    This function supports the MCP protocol's tool calling with structured content validation.
    It can return either unstructured content only, or both unstructured and structured content
    when the tool defines an outputSchema.

    Args:
        name (str): The name of the tool to invoke.
        arguments (dict): A dictionary of arguments to pass to the tool.

    Returns:
        Union[List[ContentBlock], Tuple[List[ContentBlock], Dict[str, Any]]]:
            - If structured content is not present: Returns a list of content blocks
              (TextContent, ImageContent, or EmbeddedResource)
            - If structured content is present: Returns a tuple of (unstructured_content, structured_content)
              where structured_content is a dictionary that will be validated against the tool's outputSchema

        The MCP SDK's call_tool decorator automatically handles both return types:
        - List return → CallToolResult with content only
        - Tuple return → CallToolResult with both content and structuredContent fields

        Logs and returns an empty list on failure.

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
        >>> sig.return_annotation
        typing.List[typing.Union[mcp.types.TextContent, mcp.types.ImageContent, mcp.types.EmbeddedResource]]
    """
    request_headers = request_headers_var.get()
    app_user_email = get_user_email_from_context()
    try:
        async with get_db() as db:
            result = await tool_service.invoke_tool(db=db, name=name, arguments=arguments, request_headers=request_headers, app_user_email=app_user_email)
            if not result or not result.content:
                logger.warning(f"No content returned by tool: {name}")
                return []

            # Normalize unstructured content to MCP SDK types
            unstructured = [types.TextContent(type=content.type, text=content.text) for content in result.content]

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
        return []


@mcp_app.list_tools()
async def list_tools() -> List[types.Tool]:
    """
    Lists all tools available to the MCP Server.

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
    server_id = server_id_var.get()
    request_headers = request_headers_var.get()

    if server_id:
        try:
            async with get_db() as db:
                tools = await tool_service.list_server_tools(db, server_id, _request_headers=request_headers)
                return [types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema, outputSchema=tool.output_schema, annotations=tool.annotations) for tool in tools]
        except Exception as e:
            logger.exception(f"Error listing tools:{e}")
            return []
    else:
        try:
            async with get_db() as db:
                tools, _ = await tool_service.list_tools(db, False, None, None, request_headers)
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

    server_id = server_id_var.get()

    if server_id:
        try:
            async with get_db() as db:
                prompts = await prompt_service.list_server_prompts(db, server_id)
                return [types.Prompt(name=prompt.name, description=prompt.description, arguments=prompt.arguments) for prompt in prompts]
        except Exception as e:
            logger.exception(f"Error listing Prompts:{e}")
            return []
    else:
        try:
            async with get_db() as db:
                prompts, _ = await prompt_service.list_prompts(db, False, None, None)
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
        Returns an empty list on failure or if no prompt content is found.

    Logs exceptions if any errors occur during retrieval.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(get_prompt)
        >>> list(sig.parameters.keys())
        ['prompt_id', 'arguments']
        >>> sig.return_annotation.__name__
        'GetPromptResult'
    """
    try:
        async with get_db() as db:
            try:
                result = await prompt_service.get_prompt(db=db, prompt_id=prompt_id, arguments=arguments)
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

    server_id = server_id_var.get()

    if server_id:
        try:
            async with get_db() as db:
                resources = await resource_service.list_server_resources(db, server_id)
                return [types.Resource(uri=resource.uri, name=resource.name, description=resource.description, mimeType=resource.mime_type) for resource in resources]
        except Exception as e:
            logger.exception(f"Error listing Resources:{e}")
            return []
    else:
        try:
            async with get_db() as db:
                resources, _ = await resource_service.list_resources(db, False)
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
    try:
        async with get_db() as db:
            try:
                result = await resource_service.read_resource(db=db, resource_uri=str(resource_uri))
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
    try:
        async with get_db() as db:
            try:
                resource_templates = await resource_service.list_resource_templates(db)
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
    try:
        async with get_db() as db:
            params = {
                "ref": ref.model_dump() if hasattr(ref, "model_dump") else ref,
                "argument": argument.model_dump() if hasattr(argument, "model_dump") else argument,
                "context": context.model_dump() if hasattr(context, "model_dump") else context,
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
            event_store = InMemoryEventStore()
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
        logger.info("Initializing Streamable HTTP service")
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
        logger.info("Stopping Streamable HTTP Session Manager...")
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
        match = re.search(r"/servers/(?P<server_id>[a-fA-F0-9\-]+)/mcp", path)

        # Extract request headers from scope
        headers = dict(Headers(scope=scope))
        # Store headers in context for tool invocations
        request_headers_var.set(headers)

        if match:
            server_id = match.group("server_id")
            server_id_var.set(server_id)
        else:
            server_id_var.set(None)

        try:
            await self.session_manager.handle_request(scope, receive, send)
        except anyio.ClosedResourceError:
            # Expected when client closes one side of the stream (normal lifecycle)
            logger.debug("Streamable HTTP connection closed by client (ClosedResourceError)")
        except Exception as e:
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
    - If there is no Authorization header, the request is allowed.
    - If a Bearer token is present, it is verified using `verify_credentials`.
    - If verification fails, a 401 Unauthorized JSON response is sent.

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
    authorization = headers.get("authorization")
    proxy_user = headers.get(settings.proxy_user_header) if settings.trust_proxy_auth else None

    # Determine authentication strategy based on settings
    if not settings.mcp_client_auth_enabled and settings.trust_proxy_auth:
        # Client auth disabled → allow proxy header
        if proxy_user:
            # Set user context for proxy-authenticated sessions
            user_context_var.set({"email": proxy_user})
            return True  # Trusted proxy supplied user

    # --- Standard JWT authentication flow (client auth enabled) ---
    token: str | None = None
    if authorization:
        scheme, credentials = get_authorization_scheme_param(authorization)
        if scheme.lower() == "bearer" and credentials:
            token = credentials

    try:
        if token is None:
            raise Exception()
        user_payload = await verify_credentials(token)
        # Store user context for later use in tool invocations
        if isinstance(user_payload, dict):
            user_context_var.set(user_payload)
        elif proxy_user:
            # If using proxy auth, store the proxy user
            user_context_var.set({"email": proxy_user})
    except Exception:
        # If JWT auth fails but we have a trusted proxy user, use that
        if settings.trust_proxy_auth and proxy_user:
            user_context_var.set({"email": proxy_user})
            return True  # Fall back to proxy authentication

        response = JSONResponse(
            {"detail": "Authentication failed"},
            status_code=HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)
        return False

    return True
