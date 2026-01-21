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
from collections import OrderedDict
from hashlib import sha256
import logging
from pathlib import Path
import re
import time
from typing import Any, Optional

# Third-Party
from fastapi import HTTPException, Request, Response
import orjson
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class LRUCache:
    """Simple LRU cache for validation results."""

    def __init__(self, max_size: int, ttl: int):
        """Initialize LRU cache.

        Args:
            max_size: Maximum number of items to cache
            ttl: Time-to-live in seconds
        """
        self.cache: OrderedDict[str, tuple[bool, float]] = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl

    def get(self, key: str) -> Optional[bool]:
        """Get cached validation result.

        Args:
            key: Cache key

        Returns:
            Cached validation result or None if not found/expired
        """
        if key not in self.cache:
            return None

        result, timestamp = self.cache[key]
        if time.time() - timestamp > self.ttl:
            del self.cache[key]
            return None

        # Move to end (most recently used)
        self.cache.move_to_end(key)
        return result

    def set(self, key: str, value: bool) -> None:
        """Set validation result in cache.

        Args:
            key: Cache key
            value: Validation result
        """
        if key in self.cache:
            # Update existing entry with new value and timestamp
            self.cache[key] = (value, time.time())
            self.cache.move_to_end(key)
        else:
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
            self.cache[key] = (value, time.time())


def is_path_traversal(uri: str) -> bool:
    """Check if URI contains path traversal patterns.

    Args:
        uri (str): URI to check

    Returns:
        bool: True if path traversal detected
    """
    # Don't treat leading slash as traversal — only detect explicit '..'
    # path segments or backslash sequences. This checks for '..' as
    # a path segment (../ or /.. ) and backslashes which are suspicious
    # on POSIX systems when present in URIs/paths.
    if "\\" in uri:
        return True
    # Match .. as a path segment: beginning or after a slash, and followed
    # by a slash or end-of-string.
    if re.search(r'(^|/)\.{2}(?:/|$)', uri):
        return True
    return False


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
        # Enable middleware when either the experimental flag or the
        # explicit validation middleware flag is set (backwards compatible).
        self.enabled = bool(settings.experimental_validate_io or settings.validation_middleware_enabled)
        self.strict = settings.validation_strict
        self.sanitize = settings.sanitize_output
        self.allowed_roots = [Path(root).resolve() for root in settings.allowed_roots]
        self.dangerous_patterns = [re.compile(pattern) for pattern in settings.dangerous_patterns]
        
        # Performance optimization settings
        self.max_body_size = settings.validation_max_body_size
        self.max_response_size = settings.validation_max_response_size
        # Compile skip-endpoint regexes defensively so an invalid pattern
        # in the environment doesn't crash the app startup.
        self.skip_endpoint_patterns: list[re.Pattern] = []
        for pattern in settings.validation_skip_endpoints:
            try:
                self.skip_endpoint_patterns.append(re.compile(pattern))
            except re.error:
                logger.warning("[VALIDATION] Invalid skip endpoint regex skipped: %s", pattern)
        self.sample_large_responses = settings.validation_sample_large_responses
        self.sample_size = settings.validation_sample_size
        
        # Initialize cache if enabled
        self.cache: Optional[LRUCache] = None
        if settings.validation_cache_enabled:
            self.cache = LRUCache(
                max_size=settings.validation_cache_max_size,
                ttl=settings.validation_cache_ttl
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

        # Phase 1: Check if endpoint should skip validation
        if self._should_skip_endpoint(request.url.path):
            logger.info("[VALIDATION] Skipping validation for endpoint: %s", request.url.path)
            response = await call_next(request)
            return response

        # Phase 2: Log-only mode in dev/staging
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
            logger.info(f"self.sanitize :{self.sanitize}")
            response = await self._sanitize_response(response)

        return response

    def _should_skip_endpoint(self, path: str) -> bool:
        """Check if endpoint should skip validation.

        Args:
            path: Request path

        Returns:
            True if endpoint should skip validation
        """
        for pattern in self.skip_endpoint_patterns:
            if pattern.match(path):
                return True
        return False

    def _get_cache_key(self, data: bytes) -> str:
        """Generate cache key for validation data.

        Args:
            data: Data to generate key for

        Returns:
            Cache key (SHA256 hash)
        """
        return sha256(data).hexdigest()

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
                if not body:
                    return

                # Check body size threshold
                body_size = len(body)
                if self.max_body_size > 0 and body_size > self.max_body_size:
                    logger.info(
                        "[VALIDATION] Skipping validation for large request body: %d bytes (threshold: %d)",
                        body_size,
                        self.max_body_size
                    )
                    return
                # Check cache for identical payloads
                if self.cache:
                    cache_key = self._get_cache_key(body)
                    cached_result = self.cache.get(cache_key)
                    if cached_result is not None:
                        logger.info("[VALIDATION] Cache hit for request body")
                        if not cached_result:
                            raise HTTPException(status_code=422, detail="Validation failed (cached)")
                        return

                # Perform validation
                try:
                    data = orjson.loads(body)
                    self._validate_json_data(data)
                    
                    # Cache successful validation
                    if self.cache:
                        self.cache.set(cache_key, True)
                        
                except HTTPException:
                    # Cache validation failure
                    if self.cache:
                        self.cache.set(cache_key, False)
                    raise
                    
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
        logger.info("response: %s", response)
        logger.info("response type: %s", type(response))
        if not hasattr(response, "body"):
            logger.info("I am here not body")
            return response

        try:
            body = response.body
            logger.info("[VALIDATION] Sanitizing response: %d bytes", len(body))    
            if not body:
                return response

            body_size = len(body)
            logger.info("[VALIDATION] Sanitizing response: %d bytes", body_size)    
            
            # Check response size threshold
            if self.max_response_size > 0 and body_size > self.max_response_size:
                logger.info(
                    "[VALIDATION] Skipping sanitization for large response: %d bytes (threshold: %d)",
                    body_size,
                    self.max_response_size
                )
                return response

            # For large responses, sample instead of full sanitization
            if self.sample_large_responses and body_size > self.sample_size:
                logger.info(
                    "[VALIDATION] Sampling response for sanitization: %d bytes (sample: %d)",
                    body_size,
                    self.sample_size
                )
                # Sample from beginning, middle, and end
                sample_chunk = self.sample_size // 3
                if isinstance(body, bytes):
                    samples = [
                        body[:sample_chunk],
                        body[body_size // 2 - sample_chunk // 2:body_size // 2 + sample_chunk // 2],
                        body[-sample_chunk:]
                    ]
                    sample_body = b"".join(samples).decode("utf-8", errors="replace")
                else:
                    samples = [
                        body[:sample_chunk],
                        body[body_size // 2 - sample_chunk // 2:body_size // 2 + sample_chunk // 2],
                        body[-sample_chunk:]
                    ]
                    sample_body = "".join(samples)
                
                # Check sample for control characters
                if not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", sample_body):
                    logger.info("[VALIDATION] Sample clean, skipping full sanitization")
                    return response

            # Full sanitization for small responses or when sample has issues
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")

            # Remove control characters except newlines and tabs
            sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", body)

            response.body = sanitized.encode("utf-8")
            response.headers["content-length"] = str(len(response.body))

        except Exception as e:
            logger.warning("Failed to sanitize response: %s", e)

        return response


