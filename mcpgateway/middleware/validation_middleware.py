# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/validation_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Validation middleware for MCP Gateway input validation and output sanitization.

This middleware provides comprehensive input validation and output sanitization
for MCP Gateway requests. It validates request parameters, JSON payloads, and
resource paths to prevent security vulnerabilities like path traversal, XSS,
and injection attacks.

Examples:
    >>> from mcpgateway.middleware.validation_middleware import ValidationMiddleware  # doctest: +SKIP
    >>> app.add_middleware(ValidationMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
from pathlib import Path
import re
from typing import Any

# Third-Party
from fastapi import HTTPException, Request, Response
import orjson
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


def is_path_traversal(uri: str) -> bool:
    """Check if URI contains path traversal patterns.

    Args:
        uri (str): URI to check

    Returns:
        bool: True if path traversal detected
    """
    return ".." in uri or uri.startswith("/") or "\\" in uri


class ValidationMiddleware(BaseHTTPMiddleware):
    """Middleware for validating inputs and sanitizing outputs.

    This middleware validates request parameters, JSON data, and resource paths
    to prevent security vulnerabilities. It can operate in strict or lenient mode
    and optionally sanitizes response content.
    """

    def __init__(self, app):
        """Initialize validation middleware with configuration settings.

        Args:
            app: FastAPI application instance
        """
        super().__init__(app)
        self.enabled = settings.experimental_validate_io
        self.strict = settings.validation_strict
        self.sanitize = settings.sanitize_output
        self.allowed_roots = [Path(root).resolve() for root in settings.allowed_roots]
        self.dangerous_patterns = [re.compile(pattern) for pattern in settings.dangerous_patterns]

    async def dispatch(self, request: Request, call_next):
        """Process request with validation and response sanitization.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response, potentially sanitized

        Raises:
            HTTPException: If validation fails in strict mode
        """
        # Phase 0: Feature disabled - skip entirely
        if not self.enabled:
            response = await call_next(request)
            return response

        # Phase 1: Log-only mode in dev/staging
        warn_only = settings.environment in ("development", "staging") and not self.strict

        # Validate input
        try:
            await self._validate_request(request)
        except HTTPException as e:
            if warn_only:
                logger.warning("[VALIDATION] Input validation failed (log-only mode): %s", e.detail)
            else:
                logger.error("[VALIDATION] Input validation failed: %s", e.detail)
                raise

        response = await call_next(request)

        # Sanitize output
        if self.sanitize:
            response = await self._sanitize_response(response)

        return response

    async def _validate_request(self, request: Request):
        """Validate incoming request parameters.

        Args:
            request (Request): Incoming HTTP request to validate

        Raises:
            HTTPException: If validation fails in strict mode
        """
        # Validate path parameters
        if hasattr(request, "path_params"):
            for key, value in request.path_params.items():
                self._validate_parameter(key, str(value))

        # Validate query parameters
        for key, value in request.query_params.items():
            self._validate_parameter(key, value)

        # Validate JSON body for resource/tool requests
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.body()
                if body:
                    data = orjson.loads(body)
                    self._validate_json_data(data)
            except orjson.JSONDecodeError:
                pass  # Let other middleware handle JSON errors

    def _validate_parameter(self, key: str, value: str):
        """Validate individual parameter for length and dangerous patterns.

        Args:
            key (str): Parameter name
            value (str): Parameter value

        Raises:
            HTTPException: If validation fails in strict mode
        """
        if len(value) > settings.max_param_length:
            if settings.environment in ("development", "staging"):
                logger.warning(f"Parameter {key} exceeds maximum length")
                return
            raise HTTPException(status_code=422, detail=f"Parameter {key} exceeds maximum length")

        for pattern in self.dangerous_patterns:
            if pattern.search(value):
                if settings.environment in ("development", "staging"):
                    logger.warning(f"Parameter {key} contains dangerous characters")
                    return
                raise HTTPException(status_code=422, detail=f"Parameter {key} contains dangerous characters")

    def _validate_json_data(self, data: Any):
        """Recursively validate JSON data structure.

        Args:
            data (Any): JSON data to validate

        Raises:
            HTTPException: If validation fails in strict mode
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    self._validate_parameter(key, value)
                elif isinstance(value, (dict, list)):
                    self._validate_json_data(value)
        elif isinstance(data, list):
            for item in data:
                self._validate_json_data(item)

    def validate_resource_path(self, path: str) -> str:
        """Validate and normalize resource paths to prevent traversal attacks.

        Args:
            path (str): Resource path to validate

        Returns:
            str: Normalized path if valid

        Raises:
            HTTPException: If path is invalid or contains traversal patterns
        """
        # Check explicit path traversal detection
        if ".." in path or "//" in path:
            raise HTTPException(status_code=400, detail="invalid_path: Path traversal detected")

        # Skip validation for URI schemes (http://, plugin://, etc.)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", path):
            return path

        try:
            resolved_path = Path(path).resolve()

            # Check path depth
            if len(resolved_path.parts) > settings.max_path_depth:
                raise HTTPException(status_code=400, detail="invalid_path: Path too deep")

            # Check against allowed roots
            if self.allowed_roots:
                allowed = any(str(resolved_path).startswith(str(root)) for root in self.allowed_roots)
                if not allowed:
                    raise HTTPException(status_code=400, detail="invalid_path: Path outside allowed roots")

            return str(resolved_path)
        except (OSError, ValueError):
            raise HTTPException(status_code=400, detail="invalid_path: Invalid path")

    async def _sanitize_response(self, response: Response) -> Response:
        """Sanitize response content by removing control characters.

        Args:
            response: HTTP response to sanitize

        Returns:
            Response: Sanitized response
        """
        if not hasattr(response, "body"):
            return response

        try:
            body = response.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")

            # Remove control characters except newlines and tabs
            sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", body)

            response.body = sanitized.encode("utf-8")
            response.headers["content-length"] = str(len(response.body))

        except Exception as e:
            logger.warning("Failed to sanitize response: %s", e)

        return response
