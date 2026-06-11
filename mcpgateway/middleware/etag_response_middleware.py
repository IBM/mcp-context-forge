# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/etag_response_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

ETag Response Middleware for RFC 6585 Phase 2 conditional requests.

This middleware automatically adds ETag headers to GET responses for resources
that support versioning. It enables standard HTTP conditional request workflows
where clients can retrieve ETags and use them for subsequent modifications.

The middleware operates on successful GET responses (200 OK) and adds an ETag
header based on the resource's version field in the JSON response body.

Examples:
    >>> from mcpgateway.middleware.etag_response_middleware import ETagResponseMiddleware  # doctest: +SKIP
    >>> app.add_middleware(ETagResponseMiddleware)  # doctest: +SKIP
"""

# Standard
import json
import logging
import re

# Third-Party
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.etag import generate_etag

logger = logging.getLogger(__name__)


class ETagResponseMiddleware(BaseHTTPMiddleware):
    """Middleware to add ETag headers to GET responses for versioned resources.

    Automatically adds ETag headers to successful GET responses for resources
    with version fields, enabling standard HTTP conditional request workflows.

    Only processes:
    - GET requests (safe, idempotent)
    - 200 OK responses (successful)
    - JSON responses (application/json)
    - Responses with 'id' and 'version' fields
    """

    # Resource path patterns that support versioning
    # Pattern: /resource_type/{id}
    VERSIONED_RESOURCE_PATTERNS = [
        re.compile(r"^/servers/([a-zA-Z0-9_-]+)$"),
        re.compile(r"^/gateways/([a-zA-Z0-9_-]+)$"),
        re.compile(r"^/tools/([a-zA-Z0-9_-]+)$"),
        re.compile(r"^/resources/([a-zA-Z0-9_-]+)$"),
        re.compile(r"^/prompts/([a-zA-Z0-9_-]+)$"),
        re.compile(r"^/a2a/([a-zA-Z0-9_-]+)$"),
    ]

    def __init__(self, app):
        """Initialize ETag response middleware."""
        super().__init__(app)
        self.enabled = settings.conditional_requests_enabled
        logger.info(f"ETagResponseMiddleware initialized: enabled={self.enabled}")

    async def dispatch(self, request: Request, call_next):
        """Process response and add ETag header if applicable.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response with ETag header (if applicable)
        """
        # Call the next handler
        response = await call_next(request)

        # Skip if middleware disabled
        if not self.enabled:
            return response

        # Only process GET requests
        if request.method != "GET":
            return response

        # Only process successful responses
        if response.status_code != 200:
            return response

        # Only process versioned resource endpoints
        if not self._is_versioned_resource(request.url.path):
            return response

        # Add ETag header if response contains version info
        await self._add_etag_header(response)

        return response

    def _is_versioned_resource(self, path: str) -> bool:
        """Check if path is a versioned resource endpoint.

        Args:
            path: Request URL path

        Returns:
            True if path matches versioned resource pattern
        """
        for pattern in self.VERSIONED_RESOURCE_PATTERNS:
            if pattern.match(path):
                return True
        return False

    async def _add_etag_header(self, response: Response) -> None:
        """Add ETag header to response if it contains version info.

        Parses the response body JSON to extract 'id' and 'version' fields,
        generates an ETag, and adds it to the response headers.

        Args:
            response: HTTP response to modify
        """
        # Check if response is JSON
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return

        try:
            # Get response body - handle both Response with body and StreamingResponse with body_iterator
            body_content = None

            # Try to get body directly (Response object)
            if hasattr(response, "body"):
                body_content = response.body
            # Otherwise consume body_iterator (StreamingResponse)
            elif hasattr(response, "body_iterator"):
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                body_content = body

                # Restore body iterator
                async def new_body_iterator():
                    yield body

                response.body_iterator = new_body_iterator()

            if not body_content:
                return

            # Parse JSON
            data = json.loads(body_content)

            # Extract id and version
            resource_id = data.get("id")
            version = data.get("version")

            if resource_id and version is not None:
                # Generate ETag
                etag = generate_etag(resource_id, version)

                # Add ETag header
                response.headers["ETag"] = etag

                logger.debug(f"Added ETag header: {etag} for resource {resource_id}")

        except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as e:
            # Failed to parse or extract version - skip ETag
            logger.debug(f"Could not add ETag header: {e}")
