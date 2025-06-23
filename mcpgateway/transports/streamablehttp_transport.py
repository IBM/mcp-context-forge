# -*- coding: utf-8 -*-
"""Streamable HTTP Transport Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

This module implements Streamable Http transport for MCP

Key components include:
- SessionManagerWrapper: Manages the lifecycle of streamable HTTP sessions
- Configuration options for:
        1. stateful/stateless operation
        2. JSON response mode or SSE streams
- InMemoryEventStore: A simple in-memory event storage system for maintaining session state

"""

import contextvars
import logging
import re
from collections import deque
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import List, Union
from uuid import uuid4

from fastapi.security.utils import get_authorization_scheme_param
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import (
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamId,
)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import JSONRPCMessage
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED
from starlette.types import Receive, Scope, Send

from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.verify_credentials import verify_credentials

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize ToolService and MCP Server
tool_service = ToolService()
mcp_app = Server("mcp-streamable-http-stateless")

server_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("server_id", default=None)

# ------------------------------ Event store ------------------------------


@dataclass
class EventEntry:
    """
    Represents an event entry in the event store.
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
    """

    def __init__(self, max_events_per_stream: int = 100):
        """Initialize the event store.

        Args:
            max_events_per_stream: Maximum number of events to keep per stream
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
    ) -> StreamId | None:
        """
        Replays events that occurred after the specified event ID.

        Args:
            last_event_id (EventId): The ID of the last received event. Replay starts after this event.
            send_callback (EventCallback): Async callback to send each replayed event.

        Returns:
            StreamId | None: The stream ID if the event is found and replayed, otherwise None.
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
async def get_db():
    """
    Asynchronous context manager for database sessions.

    Yields:
        A database session instance from SessionLocal.
        Ensures the session is closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@mcp_app.call_tool()
async def call_tool(name: str, arguments: dict) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
    """
    Handles tool invocation via the MCP Server.

    Args:
        name (str): The name of the tool to invoke.
        arguments (dict): A dictionary of arguments to pass to the tool.

    Returns:
        List of content (TextContent, ImageContent, or EmbeddedResource) from the tool response.
        Logs and returns an empty list on failure.
    """
    try:
        async with get_db() as db:
            result = await tool_service.invoke_tool(db=db, name=name, arguments=arguments)
            if not result or not result.content:
                logger.warning(f"No content returned by tool: {name}")
                return []

            return [types.TextContent(type=result.content[0].type, text=result.content[0].text)]
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
    """
    server_id = server_id_var.get()

    if server_id:
        try:
            async with get_db() as db:
                tools = await tool_service.list_server_tools(db, server_id)
                return [types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema) for tool in tools]
        except Exception as e:
            logger.exception(f"Error listing tools:{e}")
            return []
    else:
        try:
            async with get_db() as db:
                tools = await tool_service.list_tools(db)
                return [types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema) for tool in tools]
        except Exception as e:
            logger.exception(f"Error listing tools:{e}")
            return []


class SessionManagerWrapper:
    """
    Wrapper class for managing the lifecycle of a StreamableHTTPSessionManager instance.
    Provides start, stop, and request handling methods.
    """

    def __init__(self) -> None:
        """
        Initializes the session manager and the exit stack used for managing its lifecycle.
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
        """
        logger.info("Initializing Streamable HTTP service")
        await self.stack.enter_async_context(self.session_manager.run())

    async def shutdown(self) -> None:
        """
        Gracefully shuts down the Streamable HTTP session manager.
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
        """

        path = scope["modified_path"]
        match = re.search(r"/servers/(?P<server_id>\d+)/mcp", path)

        if match:
            server_id = match.group("server_id")
            server_id_var.set(server_id)

        try:
            await self.session_manager.handle_request(scope, receive, send)
        except Exception as e:
            logger.exception(f"Error handling streamable HTTP request: {e}")
            raise


# ------------------------- Authentication for /mcp routes ------------------------------


async def streamable_http_auth(scope, receive, send):
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
    """

    path = scope.get("path", "")
    if not path.endswith("/mcp") and not path.endswith("/mcp/"):
        # No auth needed for other paths in this middleware usage
        return True

    headers = Headers(scope=scope)
    authorization = headers.get("authorization")

    token = None
    if authorization:
        scheme, credentials = get_authorization_scheme_param(authorization)
        if scheme.lower() == "bearer" and credentials:
            token = credentials
    try:
        await verify_credentials(token)
    except Exception:
        response = JSONResponse(
            {"detail": "Authentication failed"},
            status_code=HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)
        return False

    return True
