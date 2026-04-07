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
import importlib
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

_RUST_VALIDATION_MODULE = None
_MAX_JSON_VALIDATION_DEPTH = 1024


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
        self.allowed_root_strings = [str(root) for root in self.allowed_roots]
        self.dangerous_pattern_strings = list(settings.dangerous_patterns)
        self.dangerous_patterns = [re.compile(pattern) for pattern in settings.dangerous_patterns]
        self._rust_validator = None
        self._rust_validate_http_request = None
        self._rust_sanitize_response_body = None
        self._rust_validate_resource_path = None

        if getattr(settings, "experimental_rust_validation_middleware_enabled", False) is True:
            self._rust_validator = self._build_rust_validator()
            if self._rust_validator is not None:
                self._rust_validate_http_request = self._rust_validator.validate_http_request
                self._rust_sanitize_response_body = self._rust_validator.sanitize_response_body
                self._rust_validate_resource_path = self._rust_validator.validate_resource_path

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
        parameters_to_validate = []
        if hasattr(request, "path_params"):
            for key, value in request.path_params.items():
                parameters_to_validate.append((key, str(value)))

        # Validate query parameters
        for key, value in request.query_params.items():
            parameters_to_validate.append((key, value))

        content_type = request.headers.get("content-type", "")
        body = b""
        if content_type.startswith("application/json"):
            body = await request.body()

        if self._rust_validate_http_request is not None:
            try:
                result = self._validate_request_with_rust(parameters_to_validate, content_type, body)
                if result is not None:
                    key, error_type = result
                    self._raise_validation_failure(key, error_type)
                return
            except orjson.JSONDecodeError:
                pass
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Rust validation extension unavailable or failed; falling back to Python validation: %s", exc)

        if parameters_to_validate:
            result = self._validate_parameters_with_python(parameters_to_validate)
            if result is not None:
                key, error_type = result
                self._raise_validation_failure(key, error_type)

        if content_type.startswith("application/json"):
            try:
                if body:
                    data = orjson.loads(body)
                    result = self._validate_json_data_with_python(data)
                    if result is not None:
                        key, error_type = result
                        self._raise_validation_failure(key, error_type)
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

    def _validate_parameters(self, parameters: list[tuple[str, str]]):
        """Validate request parameters using the active backend."""
        if getattr(settings, "experimental_rust_validation_middleware_enabled", False) is True:
            result = self._validate_parameters_with_rust(parameters)
            if result is not None:
                key, error_type = result
                self._raise_validation_failure(key, error_type)
            return

        result = self._validate_parameters_with_python(parameters)
        if result is not None:
            key, error_type = result
            self._raise_validation_failure(key, error_type)

    def _validate_parameters_with_python(self, parameters: list[tuple[str, str]]) -> tuple[str, str] | None:
        """Validate request parameters with the Python implementation."""
        for key, value in parameters:
            if len(value) > settings.max_param_length:
                return key, "max_length"

            for pattern in self.dangerous_patterns:
                if pattern.search(value):
                    return key, "dangerous_pattern"

        return None

    def _validate_json_data(self, data: Any):
        """Recursively validate JSON data structure.

        Args:
            data (Any): JSON data to validate

        Raises:
            HTTPException: If validation fails in strict mode
        """
        if getattr(settings, "experimental_rust_validation_middleware_enabled", False) is True:
            result = self._validate_json_data_with_rust(data)
            if result is not None:
                key, error_type = result
                self._raise_validation_failure(key, error_type)
            return

        result = self._validate_json_data_with_python(data)
        if result is not None:
            key, error_type = result
            self._raise_validation_failure(key, error_type)

    def _load_rust_validation_module(self):
        """Load the experimental Rust validation extension on demand."""
        global _RUST_VALIDATION_MODULE

        if _RUST_VALIDATION_MODULE is None:
            _RUST_VALIDATION_MODULE = importlib.import_module("validation_middleware_rust")
        return _RUST_VALIDATION_MODULE

    def _build_rust_validator(self):
        """Build the compiled Rust validator once per middleware instance."""
        try:
            return self._load_rust_validation_module().Validator(
                settings.max_param_length,
                self.dangerous_pattern_strings,
                self.allowed_root_strings,
                settings.max_path_depth,
            )
        except Exception as exc:
            logger.warning("Rust validation extension unavailable or failed; falling back to Python validation: %s", exc)
            return None

    def _validate_parameters_with_rust(self, parameters: list[tuple[str, str]]) -> tuple[str, str] | None:
        """Validate request parameters with the Rust extension, falling back to Python on failures."""
        try:
            if self._rust_validator is None:
                self._rust_validator = self._build_rust_validator()
                if self._rust_validator is None:
                    return self._validate_parameters_with_python(parameters)

            return self._rust_validator.validate_parameters(parameters)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Rust validation extension unavailable or failed; falling back to Python validation: %s", exc)
            return self._validate_parameters_with_python(parameters)

    def _validate_request_with_rust(
        self,
        parameters: list[tuple[str, str]],
        content_type: str,
        body: bytes,
    ) -> tuple[str, str] | None:
        """Validate the middleware request path via the Rust engine."""
        try:
            if self._rust_validate_http_request is None:
                raise RuntimeError("rust validator unavailable")

            return self._rust_validate_http_request(parameters, content_type, body if body else None)
        except ValueError as exc:
            if "maximum supported nesting depth" in str(exc):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if "Request body contains invalid JSON:" in str(exc):
                raise orjson.JSONDecodeError("invalid json", b"", 0) from exc
            raise
        except Exception:
            raise

    def _validate_json_data_with_rust(self, data: Any) -> tuple[str, str] | None:
        """Validate JSON data with the Rust extension, falling back to Python on extension failures."""
        try:
            if self._rust_validator is None:
                self._rust_validator = self._build_rust_validator()
                if self._rust_validator is None:
                    return self._validate_json_data_with_python(data)

            return self._rust_validator.validate_json_data(data)
        except ValueError as exc:
            if "maximum supported nesting depth" in str(exc):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            logger.warning("Rust validation extension unavailable or failed; falling back to Python validation: %s", exc)
            return self._validate_json_data_with_python(data)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Rust validation extension unavailable or failed; falling back to Python validation: %s", exc)
            return self._validate_json_data_with_python(data)

    def _validate_json_body_with_rust(self, body: bytes):
        """Validate raw JSON bytes with the Rust extension, falling back to Python on extension failures."""
        try:
            if self._rust_validator is None:
                self._rust_validator = self._build_rust_validator()
                if self._rust_validator is None:
                    data = orjson.loads(body)
                    self._validate_json_data(data)
                    return

            result = self._rust_validator.validate_json_bytes(body)
            if result is not None:
                key, error_type = result
                self._raise_validation_failure(key, error_type)
        except ValueError as exc:
            if "maximum supported nesting depth" in str(exc):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            logger.warning("Rust validation extension unavailable or failed; falling back to Python validation: %s", exc)
            data = orjson.loads(body)
            result = self._validate_json_data_with_python(data)
            if result is not None:
                key, error_type = result
                self._raise_validation_failure(key, error_type)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Rust validation extension unavailable or failed; falling back to Python validation: %s", exc)
            data = orjson.loads(body)
            result = self._validate_json_data_with_python(data)
            if result is not None:
                key, error_type = result
                self._raise_validation_failure(key, error_type)

    def _validate_json_data_with_python(self, data: Any, depth: int = 0) -> tuple[str, str] | None:
        """Validate JSON data with the Python implementation."""
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
        """Raise or log validation failures while preserving middleware mode semantics."""
        if error_type == "max_length":
            if settings.environment in ("development", "staging"):
                logger.warning("Parameter %s exceeds maximum length", key)
                return
            raise HTTPException(status_code=422, detail=f"Parameter {key} exceeds maximum length")

        if error_type == "dangerous_pattern":
            if settings.environment in ("development", "staging"):
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
        if getattr(settings, "experimental_rust_validation_middleware_enabled", False) is True:
            try:
                if self._rust_validate_resource_path is None:
                    self._rust_validator = self._build_rust_validator()
                    if self._rust_validator is None:
                        return self._validate_resource_path_with_python(path)
                    self._rust_validate_http_request = self._rust_validator.validate_http_request
                    self._rust_sanitize_response_body = self._rust_validator.sanitize_response_body
                    self._rust_validate_resource_path = self._rust_validator.validate_resource_path

                return self._rust_validate_resource_path(path)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                logger.warning("Rust validation extension unavailable or failed; falling back to Python validation: %s", exc)
                return self._validate_resource_path_with_python(path)

        return self._validate_resource_path_with_python(path)

    def _validate_resource_path_with_python(self, path: str) -> str:
        """Validate and normalize resource paths with the Python implementation."""
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", path):
            return path

        if ".." in path or "//" in path:
            raise HTTPException(status_code=400, detail="invalid_path: Path traversal detected")

        try:
            resolved_path = Path(path).resolve()

            if len(resolved_path.parts) > settings.max_path_depth:
                raise HTTPException(status_code=400, detail="invalid_path: Path too deep")

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
            if getattr(settings, "experimental_rust_validation_middleware_enabled", False) is True:
                if self._rust_sanitize_response_body is None:
                    self._rust_validator = self._build_rust_validator()
                    if self._rust_validator is not None:
                        self._rust_validate_http_request = self._rust_validator.validate_http_request
                        self._rust_sanitize_response_body = self._rust_validator.sanitize_response_body
                        self._rust_validate_resource_path = self._rust_validator.validate_resource_path

                if self._rust_sanitize_response_body is not None:
                    if isinstance(body, str):
                        body = body.encode("utf-8", errors="replace")
                    response.body = self._rust_sanitize_response_body(body)
                else:
                    response.body = self._sanitize_response_body_with_python(body)
            else:
                response.body = self._sanitize_response_body_with_python(body)

            response.headers["content-length"] = str(len(response.body))

        except Exception as e:
            logger.warning("Failed to sanitize response: %s", e)

        return response

    def _sanitize_response_body_with_python(self, body: bytes | str) -> bytes:
        """Sanitize response payload with the Python implementation."""
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")

        sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", body)
        return sanitized.encode("utf-8")
