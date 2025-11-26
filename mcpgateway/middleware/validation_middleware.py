# -*- coding: utf-8 -*-
"""Validation middleware for MCP Gateway input validation and output sanitization."""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from mcpgateway.config import settings

logger = logging.getLogger(__name__)

def is_path_traversal(uri: str) -> bool:
    return ".." in uri or uri.startswith("/") or "\\" in uri


class ValidationMiddleware(BaseHTTPMiddleware):
    """Middleware for validating inputs and sanitizing outputs."""

    def __init__(self, app):
        super().__init__(app)
        self.enabled = settings.experimental_validate_io
        self.strict = settings.validation_strict
        self.sanitize = settings.sanitize_output
        self.allowed_roots = [Path(root).resolve() for root in settings.allowed_roots]
        self.dangerous_patterns = [re.compile(pattern) for pattern in settings.dangerous_patterns]

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # Validate input
        try:
            await self._validate_request(request)
        except HTTPException as e:
            if self.strict:
                raise
            logger.warning("Validation failed but continuing in non-strict mode: %s", e.detail)

        response = await call_next(request)

        # Sanitize output
        if self.sanitize:
            response = await self._sanitize_response(response)

        return response

    async def _validate_request(self, request: Request):
        """Validate incoming request parameters."""
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
                    data = json.loads(body)
                    self._validate_json_data(data)
            except json.JSONDecodeError:
                pass  # Let other middleware handle JSON errors

    def _validate_parameter(self, key: str, value: str):
        """Validate individual parameter."""
        if len(value) > settings.max_param_length:
            raise HTTPException(status_code=422, detail=f"Parameter {key} exceeds maximum length")

        for pattern in self.dangerous_patterns:
            if pattern.search(value):
                raise HTTPException(status_code=422, detail=f"Parameter {key} contains dangerous characters")

    def _validate_json_data(self, data: Any):
        """Recursively validate JSON data."""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    self._validate_parameter(key, value)
                elif isinstance(value, (dict, list)):
                    self._validate_json_data(value)
        elif isinstance(data, list):
            for item in data:
                self._validate_json_data(item)

    def _validate_resource_path(self, path: str) -> str:
        """Validate and normalize resource paths."""

        # Check explicit path traversal detection
        if ".." in path or path.startswith(("/", "\\")) or "//" in path:
            raise HTTPException(status_code=400, detail="invalid_path: Path traversal detected")
    
        try:
            resolved_path = Path(path).resolve()
            
            # Check path depth
            if len(resolved_path.parts) > settings.max_path_depth:
                raise HTTPException(status_code=400, detail="invalid_path: Path too deep")

            # Check against allowed roots
            if self.allowed_roots:
                allowed = any(
                    str(resolved_path).startswith(str(root))
                    for root in self.allowed_roots
                )
                if not allowed:
                    raise HTTPException(status_code=400, detail="invalid_path: Path outside allowed roots")

            return str(resolved_path)
        except (OSError, ValueError):
            raise HTTPException(status_code=400, detail="invalid_path: Invalid path")

    async def _sanitize_response(self, response: Response) -> Response:
        """Sanitize response content."""
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