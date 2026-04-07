# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/validation_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Validation middleware for ContextForge input validation and output sanitization.

This middleware provides comprehensive input validation and output sanitization
for ContextForge requests. It validates request parameters, JSON payloads, and
resource paths to prevent security vulnerabilities like path traversal, XSS,
and injection attacks.

Examples:
    >>> from mcpgateway.middleware.validation_middleware import ValidationMiddleware  # doctest: +SKIP
    >>> app.add_middleware(ValidationMiddleware)  # doctest: +SKIP
"""

# Standard
import asyncio
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
from mcpgateway.services.validation_sidecar_client import (
    ValidationSidecarClient,
    ValidationSidecarProtocolError,
    ValidationSidecarTimeoutError,
    ValidationSidecarTransportError,
    ValidationSidecarValidationError,
)

logger = logging.getLogger(__name__)

_MAX_JSON_VALIDATION_DEPTH = 1024


def _get_bool_setting(name: str, default: bool = False) -> bool:
    """Return a boolean setting value without letting MagicMock placeholders leak through.

    Args:
        name: Settings attribute name to read.
        default: Fallback boolean to use when the value is unset or mocked.

    Returns:
        A concrete boolean value for the requested setting.
    """
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return value
    return default


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
        self.enabled = _get_bool_setting("experimental_validate_io")
        self.strict = settings.validation_strict
        self.sanitize = settings.sanitize_output
        self.allowed_roots = [Path(root).resolve() for root in settings.allowed_roots]
        self.dangerous_pattern_strings = list(settings.dangerous_patterns)
        self.dangerous_patterns = [re.compile(pattern) for pattern in settings.dangerous_patterns]
        self.validation_middleware_enabled = _get_bool_setting("validation_middleware_enabled")
        self.experimental_rust_validation_sidecar_enabled = _get_bool_setting("experimental_rust_validation_sidecar_enabled")
        self._validation_sidecar_client = None
        if self.validation_middleware_enabled and self.enabled and self.experimental_rust_validation_sidecar_enabled:
            uds_path = getattr(settings, "experimental_rust_validation_sidecar_uds", None)
            if isinstance(uds_path, str) and uds_path:
                self._validation_sidecar_client = ValidationSidecarClient(
                    uds_path=uds_path,
                    timeout_seconds=float(getattr(settings, "experimental_rust_validation_sidecar_timeout_seconds", 30.0)),
                    pool_size=int(getattr(settings, "experimental_rust_validation_sidecar_pool_size", 8)),
                )

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
            if warn_only and e.status_code == 422:
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
                    if self._should_use_sidecar_validation():
                        await self._validate_json_body_with_sidecar(body)
                    else:
                        data = orjson.loads(body)
                        await self._validate_json_data_async(data)
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

    def _should_use_sidecar_validation(self) -> bool:
        """Return whether the validation sidecar should handle JSON bodies.

        Returns:
            `True` when the middleware gates and sidecar flag are all enabled.
        """
        return self.enabled and self.validation_middleware_enabled and self.experimental_rust_validation_sidecar_enabled

    def _is_warn_only_mode(self) -> bool:
        """Return whether validation failures should be logged instead of raised.

        Returns:
            `True` when the environment is development or staging and strict mode is off.
        """
        return settings.environment in ("development", "staging") and not self.strict

    def _validate_json_data(self, data: Any):
        """Synchronously validate parsed JSON data using the active backend.

        Args:
            data: Parsed JSON payload to validate.

        Returns:
            `None` when validation succeeds.

        Raises:
            RuntimeError: If called from an active async event loop.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._validate_json_data_async(data))
        raise RuntimeError("Use await _validate_json_data_async() from async contexts")

    async def _validate_json_data_async(self, data: Any):
        """Recursively validate JSON data structure.

        Args:
            data (Any): JSON data to validate

        Raises:
            HTTPException: If validation fails in strict mode
        """
        result = self._validate_json_data_with_python(data)
        if result is not None:
            key, error_type = result
            self._raise_validation_failure(key, error_type)

    async def _validate_json_body_with_sidecar(self, body: bytes) -> None:
        """Validate raw JSON body bytes using the Rust validation sidecar.

        Args:
            body: Raw request body bytes to validate.

        Raises:
            HTTPException: If the sidecar is unavailable or rejects the body.
        """
        if self._validation_sidecar_client is None:
            raise HTTPException(status_code=503, detail="Validation sidecar is not configured")

        try:
            await self._validation_sidecar_client.validate_json_body(
                body,
                max_param_length=settings.max_param_length,
                dangerous_patterns=self.dangerous_pattern_strings,
            )
        except ValidationSidecarValidationError as exc:
            self._raise_validation_failure(exc.key or "payload", exc.error_type or "validation")
        except ValidationSidecarProtocolError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValidationSidecarTimeoutError, ValidationSidecarTransportError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def _validate_json_data_with_python(self, data: Any, depth: int = 0) -> tuple[str, str] | None:
        """Validate JSON data with the Python implementation.

        Args:
            data: Parsed JSON payload to validate.
            depth: Current container depth in the recursive traversal.

        Returns:
            A `(key, error_type)` tuple when validation fails, otherwise `None`.

        Raises:
            HTTPException: If the payload exceeds the supported nesting depth.
        """
        if depth > _MAX_JSON_VALIDATION_DEPTH:
            raise HTTPException(status_code=422, detail="JSON payload exceeds maximum supported nesting depth")

        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    if len(value) > settings.max_param_length:
                        return key, "max_length"
                    for pattern in self.dangerous_patterns:
                        if pattern.search(value):
                            return key, "dangerous_pattern"
                elif isinstance(value, (dict, list)):
                    result = self._validate_json_data_with_python(value, depth + 1)
                    if result is not None:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    if len(item) > settings.max_param_length:
                        return "list_item", "max_length"
                    for pattern in self.dangerous_patterns:
                        if pattern.search(item):
                            return "list_item", "dangerous_pattern"
                else:
                    result = self._validate_json_data_with_python(item, depth + 1)
                    if result is not None:
                        return result
        return None

    def _raise_validation_failure(self, key: str, error_type: str):
        """Raise or log validation failures while preserving middleware mode semantics.

        Args:
            key: Logical field name associated with the validation failure.
            error_type: Failure type returned by the active validator backend.

        Raises:
            HTTPException: If the failure should be surfaced to the caller.
        """
        if error_type == "max_length":
            if self._is_warn_only_mode():
                logger.warning("Parameter %s exceeds maximum length", key)
                return
            raise HTTPException(status_code=422, detail=f"Parameter {key} exceeds maximum length")

        if error_type == "dangerous_pattern":
            if self._is_warn_only_mode():
                logger.warning("Parameter %s contains dangerous characters", key)
                return
            raise HTTPException(status_code=422, detail=f"Parameter {key} contains dangerous characters")

        raise HTTPException(status_code=422, detail=f"Parameter {key} failed validation")

    def validate_resource_path(self, path: str) -> str:
        """Validate and normalize resource paths to prevent traversal attacks.

        Args:
            path (str): Resource path to validate

        Returns:
            str: Normalized path if valid

        Raises:
            HTTPException: If path is invalid or contains traversal patterns
        """
        # Skip validation for URI schemes (http://, plugin://, etc.)
        #
        # Note: This must run before the '//' traversal check, otherwise every URI
        # would be rejected due to the '://' sequence.
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", path):
            return path

        # Check explicit path traversal detection
        if ".." in path or "//" in path:
            raise HTTPException(status_code=400, detail="invalid_path: Path traversal detected")

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
