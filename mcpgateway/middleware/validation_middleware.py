# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/validation_middleware.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Validation middleware for ContextForge input validation and output sanitization.

This middleware provides comprehensive input validation and output sanitization
for ContextForge requests. It validates request parameters, JSON payloads, and
resource paths to prevent security vulnerabilities like path traversal, XSS,
and injection attacks.

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): JSON request bodies
read during validation are replayed downstream via a fresh receive callable
(mirroring what BaseHTTPMiddleware's _CachedRequest did), and responses stream
unbuffered. A ``dispatch`` shim is retained for tests.

Output sanitization was removed with the ASGI conversion: under
BaseHTTPMiddleware ``call_next`` always returned ``_StreamingResponse`` (which
carries no ``body`` attribute), so ``_sanitize_response`` could never run in
production. ``settings.sanitize_output`` is retained for environment
compatibility but has no effect.


Examples:
    >>> from mcpgateway.middleware.validation_middleware import ValidationMiddleware  # doctest: +SKIP
    >>> app.add_middleware(ValidationMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
from pathlib import Path
import re
from typing import Any, List
import warnings

# Third-Party
from fastapi import HTTPException, Request
import orjson
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# First-Party
from mcpgateway.config import settings
from mcpgateway.deprecations import VALIDATION_MIDDLEWARE_DEPRECATION_MESSAGE
from mcpgateway.utils.paths import is_path_within

logger = logging.getLogger(__name__)
_VALIDATION_MIDDLEWARE_DEPRECATION_LOGGED = False


def is_path_traversal(uri: str) -> bool:
    """Check if URI contains path traversal patterns.

    Args:
        uri (str): URI to check

    Returns:
        bool: True if path traversal detected
    """
    return ".." in uri or uri.startswith("/") or "\\" in uri


class ValidationMiddleware:
    """Middleware for validating inputs.

    This middleware validates request parameters, JSON data, and resource paths
    to prevent security vulnerabilities. It can operate in strict or lenient mode.
    """

    def __init__(self, app: ASGIApp):
        """Initialize validation middleware with configuration settings.

        Args:
            app: ASGI application instance
        """
        global _VALIDATION_MIDDLEWARE_DEPRECATION_LOGGED  # pylint: disable=global-statement
        self.app = app
        warnings.warn(VALIDATION_MIDDLEWARE_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
        if not _VALIDATION_MIDDLEWARE_DEPRECATION_LOGGED:
            logger.warning(VALIDATION_MIDDLEWARE_DEPRECATION_MESSAGE)
            _VALIDATION_MIDDLEWARE_DEPRECATION_LOGGED = True
        self.enabled = settings.experimental_validate_io
        self.strict = settings.validation_strict
        self.allowed_roots = [Path(root).resolve() for root in settings.allowed_roots]
        self.dangerous_patterns = [re.compile(pattern) for pattern in settings.dangerous_patterns]

    async def _run_validation(self, request: Request) -> None:
        """Validate the request, honoring log-only mode in dev/staging.

        Args:
            request: Incoming HTTP request

        Raises:
            HTTPException: If validation fails outside log-only mode
        """
        # Log-only mode in dev/staging
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry point with request-body replay for JSON validation.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        Raises:
            HTTPException: If validation fails outside log-only mode
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Feature disabled - skip entirely
        if not self.enabled:
            await self.app(scope, receive, send)
            return

        # Record any request-stream messages consumed during validation so the
        # body can be replayed downstream exactly as BaseHTTPMiddleware's
        # _CachedRequest replayed dispatch-read bodies.
        consumed: List[Message] = []

        async def recording_receive() -> Message:
            """Forward receive messages while recording them for replay."""
            message = await receive()
            consumed.append(message)
            return message

        request = Request(scope, recording_receive)
        await self._run_validation(request)

        if not consumed:
            await self.app(scope, receive, send)
            return

        replay_queue = list(consumed)

        async def replay_receive() -> Message:
            """Replay recorded request messages, then defer to the real receive."""
            if replay_queue:
                return replay_queue.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)

    async def dispatch(self, request: Request, call_next):
        """BaseHTTPMiddleware-compatible entry point retained for tests.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response from the downstream handler

        Raises:
            HTTPException: If validation fails in strict mode
        """
        # Phase 0: Feature disabled - skip entirely
        if not self.enabled:
            response = await call_next(request)
            return response

        await self._run_validation(request)

        return await call_next(request)

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

        # UAIDs have their own validation rules and should not be subject to
        # generic dangerous pattern matching (UAIDs contain semicolons as field separators)
        if value.startswith("uaid:"):
            try:
                # First-Party
                from mcpgateway.utils.uaid import validate_uaid  # pylint: disable=import-outside-toplevel
            except ImportError:
                # Fallback if UAID utilities not available - allow UAIDs through
                logger.debug("UAID validator not available, skipping UAID validation")
                return

            is_valid, error_msg = validate_uaid(value)
            if is_valid:
                return  # Valid UAID, skip dangerous pattern check
            # Invalid UAID: log warning and raise in strict mode, otherwise fall through to dangerous pattern check
            logger.warning(f"Invalid UAID format for {key}: {error_msg}")
            if settings.environment not in ("development", "staging") and self.strict:
                raise HTTPException(status_code=422, detail=f"Invalid UAID format: {error_msg}")
            # Non-strict mode: fall through to dangerous pattern check below

        # Special handling for identifier fields (_id suffix or 'id')
        if key.endswith("_id") or key == "id":
            # UUID validation: standard UUID format (8-4-4-4-12 hex digits with hyphens)
            if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", value, re.IGNORECASE):
                return  # Valid UUID, skip dangerous pattern check

        # Apply dangerous pattern validation to non-identifier fields or non-UAID/UUID identifiers
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
        # Skip validation for URI schemes (http://, plugin://, etc.)
        #
        # Note: This must run before the '//' traversal check, otherwise every URI
        # would be rejected due to the '://' sequence.
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", path):
            return path

        # Check explicit path traversal detection
        if ".." in path or "//" in path:
            raise HTTPException(status_code=400, detail="invalid_path: Path traversal detected")

        try:  # noqa: PLW0717 - keep validation checks in the path-resolution block.
            resolved_path = Path(path).resolve()

            # Check path depth
            if len(resolved_path.parts) > settings.max_path_depth:
                raise HTTPException(status_code=400, detail="invalid_path: Path too deep")

            # Check against allowed roots
            if self.allowed_roots:
                # Component-aware confinement: a plain string prefix would let a sibling
                # directory such as /srv/data_secret pass a /srv/data root.
                allowed = any(is_path_within(resolved_path, root) for root in self.allowed_roots)
                if not allowed:
                    raise HTTPException(status_code=400, detail="invalid_path: Path outside allowed roots")

            return str(resolved_path)
        except (OSError, ValueError):
            raise HTTPException(status_code=400, detail="invalid_path: Invalid path")
