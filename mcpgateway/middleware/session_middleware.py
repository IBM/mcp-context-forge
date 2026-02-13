# -*- coding: utf-8 -*-
"""Middleware to cleanup request-scoped DB session at end of request.

This middleware relies on `mcpgateway.db.get_request_session` creating the
session lazily and `mcpgateway.db.close_request_session` to close it.
"""

# Standard
import logging
from typing import Callable, Awaitable

# ASGI middleware (callable) avoids BaseHTTPMiddleware's context.copy() behavior
# which can break ContextVar propagation. Implementing as pure ASGI ensures
# request-scoped ContextVar sessions are visible to downstream handlers and
# closed in the same context.

# First-Party
from mcpgateway.db import close_request_session

logger = logging.getLogger(__name__)


class SessionMiddleware:
    """Pure ASGI middleware that ensures request-scoped DB session cleanup.

    Using a pure ASGI middleware avoids context copying performed by
    `BaseHTTPMiddleware` and guarantees `ContextVar`-backed request sessions
    are closed from the same context they were created in.
    """

    def __init__(self, app: Callable):
        """Initialize middleware with the downstream ASGI application.

        Args:
            app: The downstream ASGI application callable.
        """
        self.app = app

    async def __call__(
        self,
        scope: dict,
        receive: Callable[..., Awaitable[dict]],
        send: Callable[..., Awaitable[None]],
    ):
        """ASGI callable entrypoint.

        Awaits the downstream application and ensures the request-scoped DB
        session is closed afterward from the same context.

        Args:
            scope: ASGI scope dict.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                close_request_session()
            except Exception as e:
                logger.debug("Failed to close request-scoped DB session: %s", e)
