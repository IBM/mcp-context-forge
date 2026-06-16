# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/conditional_request_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

RFC 6585 Phase 2: Conditional Request Middleware (428 Precondition Required).

This middleware enforces conditional request validation using ETags to prevent
lost updates in concurrent modification scenarios. When enabled, PUT/PATCH/DELETE
operations require an If-Match header containing a valid ETag.

Features:
- 428 Precondition Required for missing If-Match headers
- 412 Precondition Failed for stale ETags (version mismatch)
- Configurable method and path exemptions
- Resource version validation against database
- SecurityLogger integration for audit trails

Compliance:
- RFC 6585 Section 3 (428 Precondition Required)
- RFC 7232 Section 3.1 (If-Match conditional header)
- RFC 7232 Section 2.3 (ETag field)

Examples:
    >>> from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware  # doctest: +SKIP
    >>> app.add_middleware(ConditionalRequestMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
import re
from typing import Optional, Tuple

# Third-Party
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.services.security_logger import SecurityEventType, SecurityLogger, SecuritySeverity
from mcpgateway.utils.etag import matches_any_etag, parse_if_match_header

logger = logging.getLogger(__name__)


class ConditionalRequestMiddleware(BaseHTTPMiddleware):
    """RFC 6585 Phase 2 conditional request validation middleware.

    Enforces If-Match header validation for PUT/PATCH/DELETE operations
    to prevent lost updates through optimistic locking with version-based ETags.

    Configuration via environment variables:
    - CONDITIONAL_REQUESTS_ENABLED: Enable/disable middleware
    - CONDITIONAL_REQUESTS_REQUIRED_METHODS: Methods requiring validation
    - CONDITIONAL_REQUESTS_EXEMPT_PATHS: Paths exempt from validation
    - CONDITIONAL_REQUESTS_REQUIRE_ETAG: Require ETag-based validation
    """

    # Resource path patterns for ETag validation
    # Pattern: /resources/{id}, /servers/{id}, /tools/{id}, etc.
    RESOURCE_PATTERNS = {
        "servers": re.compile(r"^/servers/([a-zA-Z0-9_-]+)$"),
        "gateways": re.compile(r"^/gateways/([a-zA-Z0-9_-]+)$"),
        "tools": re.compile(r"^/tools/([a-zA-Z0-9_-]+)$"),
        "resources": re.compile(r"^/resources/([a-zA-Z0-9_-]+)$"),
        "prompts": re.compile(r"^/prompts/([a-zA-Z0-9_-]+)$"),
        "a2a": re.compile(r"^/a2a/([a-zA-Z0-9_-]+)$"),
    }

    def __init__(self, app):
        """Initialize conditional request middleware."""
        super().__init__(app)
        self.enabled = settings.conditional_requests_enabled
        self.required_methods = set(settings.conditional_requests_required_methods)
        self.exempt_paths = settings.conditional_requests_exempt_paths
        self.require_etag = settings.conditional_requests_require_etag
        self.security_logger = SecurityLogger()

        logger.info(f"ConditionalRequestMiddleware initialized: " f"enabled={self.enabled}, " f"required_methods={self.required_methods}, " f"exempt_paths={len(self.exempt_paths)} paths")

    async def dispatch(self, request: Request, call_next):
        """Process request with conditional validation.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response (428, 412, or proxied response)
        """
        # Skip if middleware disabled
        if not self.enabled:
            return await call_next(request)

        # Check if this request requires conditional validation
        if not self._should_validate_conditional(request):
            return await call_next(request)

        # Extract If-Match header
        if_match_header = request.headers.get("If-Match")

        # Return 428 if If-Match is missing
        if not if_match_header:
            return self._create_428_response(request)

        # Extract resource info from path
        resource_info = self._extract_resource_info(request.url.path)
        if not resource_info:
            # Path matched required method but not a known resource pattern
            # Allow request to proceed (endpoint will handle invalid paths)
            return await call_next(request)

        resource_type, resource_id = resource_info

        # Get current resource version from database
        current_version = self._get_current_version(resource_type, resource_id)
        if current_version is None:
            # Resource doesn't exist - let endpoint return 404
            return await call_next(request)

        # Parse and validate If-Match header
        etags = parse_if_match_header(if_match_header)
        if not etags:
            # Malformed If-Match header
            return self._create_428_response(request, invalid_format=True)

        # Check if any provided ETag matches current version
        if not matches_any_etag(etags, resource_id, current_version):
            # ETag is stale - return 412 Precondition Failed
            return self._create_412_response(request, resource_id, current_version)

        # ETag is valid - proceed with request
        response = await call_next(request)
        return response

    def _should_validate_conditional(self, request: Request) -> bool:
        """Check if request requires conditional validation.

        Args:
            request: Incoming HTTP request

        Returns:
            True if validation required, False otherwise
        """
        # Check if method requires validation
        if request.method not in self.required_methods:
            return False

        # Check if path is exempt
        path = request.url.path
        for exempt_path in self.exempt_paths:
            if path.startswith(exempt_path):
                return False

        return True

    def _extract_resource_info(self, path: str) -> Optional[Tuple[str, str]]:
        """Extract resource type and ID from request path.

        Args:
            path: Request URL path

        Returns:
            Tuple of (resource_type, resource_id) or None if not matched
        """
        for resource_type, pattern in self.RESOURCE_PATTERNS.items():
            match = pattern.match(path)
            if match:
                resource_id = match.group(1)
                return (resource_type, resource_id)
        return None

    def _get_current_version(self, resource_type: str, resource_id: str) -> Optional[int]:
        """Get current version for a resource from database.

        Args:
            resource_type: Type of resource (servers, tools, etc.)
            resource_id: Resource identifier

        Returns:
            Current version number or None if not found
        """
        # Map resource type to DB model
        model_mapping = {
            "servers": "Server",
            "gateways": "Gateway",
            "tools": "Tool",
            "resources": "Resource",
            "prompts": "Prompt",
            "a2a": "A2AAgent",
        }

        model_name = model_mapping.get(resource_type)
        if not model_name:
            return None

        try:
            # Import models dynamically to avoid circular imports
            # First-Party
            from mcpgateway import db

            model_class = getattr(db, model_name)

            # Query database for current version
            with SessionLocal() as session:
                resource = session.query(model_class).filter(model_class.id == resource_id).first()
                if resource and hasattr(resource, "version"):
                    return resource.version
                return None
        except Exception as e:
            logger.error(f"Failed to fetch version for {resource_type}/{resource_id}: {e}")
            return None

    def _create_428_response(self, request: Request, invalid_format: bool = False) -> JSONResponse:
        """Create 428 Precondition Required response.

        Args:
            request: Incoming HTTP request
            invalid_format: Whether If-Match header had invalid format

        Returns:
            JSONResponse with 428 status
        """
        # Log security event
        self._log_security_event(
            request=request,
            event_type=SecurityEventType.AUTHORIZATION_FAILURE,
            description="Conditional request missing or invalid If-Match header",
        )

        if invalid_format:
            message = "The If-Match header format is invalid. " 'Expected format: If-Match: W/"resource_id-version"'
        else:
            message = (
                "This request requires an If-Match header to prevent concurrent modifications. "
                "Please retrieve the current resource with a GET request to obtain the ETag, "
                "then retry with If-Match: <etag> header."
            )

        return JSONResponse(
            status_code=428,
            content={
                "error": "Precondition Required",
                "message": message,
                "required_headers": ["If-Match"],
                "resource": request.url.path,
                "documentation": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/If-Match",
                "rfc": "https://datatracker.ietf.org/doc/html/rfc6585#section-3",
            },
            headers={
                "Content-Type": "application/json",
            },
        )

    def _create_412_response(self, request: Request, resource_id: str, current_version: int) -> JSONResponse:
        """Create 412 Precondition Failed response for stale ETag.

        Args:
            request: Incoming HTTP request
            resource_id: Resource identifier
            current_version: Current version from database

        Returns:
            JSONResponse with 412 status
        """
        # Log security event
        self._log_security_event(
            request=request,
            event_type=SecurityEventType.AUTHORIZATION_FAILURE,
            description=f"Conditional request with stale ETag for {request.url.path}",
        )

        # Generate current ETag for client
        # First-Party
        from mcpgateway.utils.etag import generate_etag

        current_etag = generate_etag(resource_id, current_version)

        return JSONResponse(
            status_code=412,
            content={
                "error": "Precondition Failed",
                "message": ("The resource has been modified by another client. " "Your ETag is stale. Please retrieve the current resource " "and retry your modification."),
                "current_etag": current_etag,
                "resource": request.url.path,
                "documentation": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/412",
            },
            headers={
                "Content-Type": "application/json",
                "ETag": current_etag,
            },
        )

    def _log_security_event(
        self,
        request: Request,
        event_type: SecurityEventType,
        description: str,
    ) -> None:
        """Log security event for conditional request violation.

        Args:
            request: Incoming HTTP request
            event_type: Type of security event
            description: Event description
        """
        try:
            user_id = getattr(request.state, "user_id", None)
            user_email = getattr(request.state, "user_email", None)
            team_id = getattr(request.state, "team_id", None)
            client_ip = self._get_client_ip(request)

            self.security_logger._create_security_event(  # pylint: disable=protected-access
                event_type=event_type,
                severity=SecuritySeverity.MEDIUM,
                category="conditional_request",
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip,
                description=description,
                threat_score=0.3,
                context={
                    "team_id": team_id,
                    "endpoint": request.url.path,
                    "method": request.method,
                    "if_match_header": request.headers.get("If-Match"),
                },
            )
        except Exception as e:
            logger.error(f"Failed to log security event: {e}")

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request.

        Trusts X-Forwarded-For when trust_proxy_auth is enabled.

        Args:
            request: Incoming HTTP request

        Returns:
            Client IP address
        """
        if settings.trust_proxy_auth:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()

            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip

        client = request.scope.get("client")
        if client:
            return client[0]

        return "unknown"
