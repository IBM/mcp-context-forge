# -*- coding: utf-8 -*-
"""Middleware to cleanup request-scoped DB session at end of request.

This middleware relies on `mcpgateway.db.get_request_session` creating the
session lazily and `mcpgateway.db.close_request_session` to close it.
"""

from typing import Callable
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from mcpgateway.db import close_request_session

logger = logging.getLogger(__name__)


class SessionMiddleware(BaseHTTPMiddleware):
    """Ensure the request-scoped DB session is closed after each request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Dispatch request and ensure DB session cleanup after response.

        This method forwards the request to the next handler and always
        attempts to close the request-scoped DB session afterward.
        """
        try:
            response = await call_next(request)
            return response
        finally:
            try:
                close_request_session()
            except Exception as e:
                logger.debug(f"Failed to close request-scoped DB session: {e}")
