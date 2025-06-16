# -*- coding: utf-8 -*-
"""Streamable HTTP Transport Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

This module implements Streamable Http transport for MCP

Key components include:
- SessionManagerWrapper: Manages the lifecycle of streamable HTTP sessions
- JWTAuthMiddlewareStreamableHttp: Middleware for JWT authentication
- Configuration options for:
        1. stateful/stateless operation
        2. JSON response mode or SSE streams
- InMemoryEventStore: A simple in-memory event storage system for maintaining session state

"""

import logging
from collections import deque
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import List, Union
from uuid import uuid4

import mcp.types as types
from fastapi.security.utils import get_authorization_scheme_param
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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED
from starlette.types import ASGIApp, Receive, Scope, Send

from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.verify_credentials import verify_credentials

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize ToolService and MCP Server
tool_service = ToolService()
mcp_app = Server("mcp-streamable-http-stateless")

## ------------------------------ Event store ------------------------------


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
        """Stores an event with a generated event ID."""
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
        """Replays events that occurred after the specified event ID."""
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


## ------------------------------ Streamable HTTP Transport ------------------------------


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
            result = await tool_service.invoke_tool(db, name, arguments)
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
    try:
        async with get_db() as db:
            tools = await tool_service.list_tools(db)
            return [types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema) for tool in tools]
    except Exception as e:
        logger.exception("Error listing tools")
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

    async def start(self) -> None:
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
        Logs any exceptions that occur during request handling.
        """
        try:
            await self.session_manager.handle_request(scope, receive, send)
        except Exception as e:
            logger.exception("Error handling streamable HTTP request")
            raise


## ------------------------- FastAPI Middleware for Authentication ------------------------------


class JWTAuthMiddlewareStreamableHttp(BaseHTTPMiddleware):
    """
    Middleware for handling JWT authentication in an ASGI application.
    This middleware checks for JWT tokens in the authorization header or cookies
    and verifies the credentials before allowing access to protected routes.
    """

    def __init__(self, app: ASGIApp):
        """
        Initialize the middleware with the given ASGI application.

        Args:
            app (ASGIApp): The ASGI application to wrap.
        """
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        """
        Dispatch the request to the appropriate handler after performing JWT authentication.

        Args:
            request (Request): The incoming request.
            call_next: The next middleware or route handler in the chain.

        Returns:
            JSONResponse: A response indicating authentication failure if the token is invalid or missing.
            Response: The response from the next middleware or route handler if authentication is successful.
        """
        # Only apply auth to /mcp path
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        headers = Headers(scope=request.scope)
        authorization = headers.get("authorization")
        cookie_header = headers.get("cookie", "")

        token = None
        if authorization:
            scheme, credentials = get_authorization_scheme_param(authorization)
            if scheme.lower() == "bearer" and credentials:
                token = credentials

        if not token:
            for cookie in cookie_header.split(";"):
                if cookie.strip().startswith("jwt_token="):
                    token = cookie.strip().split("=", 1)[1]
                    break

        try:
            if settings.auth_required and not token:
                return JSONResponse(
                    {"detail": "Not authenticated"},
                    status_code=HTTP_401_UNAUTHORIZED,
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if token:
                await verify_credentials(token)

            return await call_next(request)

        except Exception as e:
            return JSONResponse(
                {"detail": "Authentication failed"},
                status_code=HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )
