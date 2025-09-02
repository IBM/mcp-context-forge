"""Experimental API access control middleware for MCP Gateway.

Controls access to experimental endpoints based on user roles with
audit logging and graceful error handling.
"""

# Standard
import re
from typing import Callable, Set

# Third-Party
from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service
logging_service = LoggingService()
logger = logging_service.get_logger("experimental_access_middleware")

# Compiled regex for experimental paths
EXPERIMENTAL_PATH_PATTERN = re.compile(r"^/experimental/")

# Default roles with experimental access
DEFAULT_EXPERIMENTAL_ROLES: Set[str] = {"admin", "developer", "platform_admin"}


def has_experimental_access(user: str, user_roles: Set[str] = None) -> bool:
    """Check if user has access to experimental features.

    Args:
        user: Username
        user_roles: Set of user roles (defaults to admin check)

    Returns:
        bool: True if user has experimental access
    """
    # For now, simple admin check - can be extended with proper RBAC
    if user_roles:
        return bool(user_roles.intersection(DEFAULT_EXPERIMENTAL_ROLES))

    # Fallback: treat 'admin' user as having access
    return user == "admin"


class ExperimentalAccessMiddleware(BaseHTTPMiddleware):
    """Middleware to control access to experimental API endpoints.

    Provides role-based access control for experimental features with
    audit logging and configurable access rules.
    """

    def __init__(self, app, enabled: bool = True, allowed_roles: Set[str] = None):
        """Initialize experimental access middleware.

        Args:
            app: FastAPI application
            enabled: Whether experimental access control is enabled
            allowed_roles: Set of roles allowed experimental access
        """
        super().__init__(app)
        self.enabled = enabled
        self.allowed_roles = allowed_roles or DEFAULT_EXPERIMENTAL_ROLES

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and check experimental access if needed.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware in chain

        Returns:
            Response: HTTP response from middleware chain

        Raises:
            HTTPException: For authentication or authorization failures
        """
        # Skip if middleware disabled or not experimental path
        if not self.enabled or not EXPERIMENTAL_PATH_PATTERN.match(request.url.path):
            return await call_next(request)

        try:
            # Extract user from request (simplified - would use proper auth)
            user = self._extract_user_from_request(request)

            if not user:
                logger.warning(f"Unauthenticated access attempt to experimental API: {request.url.path}")
                raise HTTPException(status_code=401, detail="Authentication required for experimental APIs")

            # Check experimental access
            if not has_experimental_access(user):
                logger.warning(f"Unauthorized experimental API access attempt by user '{user}': " f"{request.method} {request.url.path}")
                raise HTTPException(status_code=403, detail="Experimental API access requires elevated privileges")

            # Log successful access
            logger.info(f"Experimental API access granted to user '{user}': " f"{request.method} {request.url.path}")

            response = await call_next(request)

            # Add experimental headers
            response.headers["X-API-Experimental"] = "true"
            response.headers["X-API-Stability"] = "unstable"
            response.headers["Warning"] = '299 - "This is an experimental API and may change without notice"'

            return response

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in experimental access middleware: {str(e)}")
            # Fail secure - deny access on errors
            raise HTTPException(status_code=500, detail="Internal error processing experimental API request")

    def _extract_user_from_request(self, request: Request) -> str:
        """Extract user from request headers/auth.

        This is a simplified implementation - in production would integrate
        with the full authentication system.

        Args:
            request: HTTP request

        Returns:
            str: Username or None if not authenticated
        """
        # Check for basic auth header (simplified)
        auth_header = request.headers.get("authorization", "")

        if auth_header.startswith("Bearer "):
            # In real implementation, would decode JWT token
            # For now, assume admin user for any bearer token
            return "admin"

        if auth_header.startswith("Basic "):
            # In real implementation, would decode basic auth
            # For now, assume admin user for any basic auth
            return "admin"

        return None
