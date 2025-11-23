# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/token_scoping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token Scoping Middleware.
This middleware enforces token scoping restrictions at the API level,
including server_id restrictions, IP restrictions, permission checks,
and time-based restrictions.
"""

# Standard
from datetime import datetime, timezone
import ipaddress
import re
from typing import List, Optional

# Third-Party
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

# First-Party
from mcpgateway.db import get_db
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.utils.verify_credentials import verify_jwt_token

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class TokenScopingMiddleware:
    """Middleware to enforce token scoping restrictions.

    Examples:
        >>> middleware = TokenScopingMiddleware()
        >>> isinstance(middleware, TokenScopingMiddleware)
        True
    """

    def __init__(self):
        """Initialize token scoping middleware.

        Examples:
            >>> middleware = TokenScopingMiddleware()
            >>> hasattr(middleware, '_extract_token_scopes')
            True
        """

    async def _extract_token_scopes(self, request: Request) -> Optional[dict]:
        """Extract token scopes from JWT in request.

        Args:
            request: FastAPI request object

        Returns:
            Dict containing token scopes or None if no valid token
        """
        # Get authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ", 1)[1]

        try:
            # Use the centralized verify_jwt_token function for consistent JWT validation
            payload = await verify_jwt_token(token)
            return payload
        except HTTPException:
            # Token validation failed (expired, invalid, etc.)
            return None
        except Exception:
            # Any other error in token validation
            return None

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request.

        Args:
            request: FastAPI request object

        Returns:
            str: Client IP address
        """
        # Check for X-Forwarded-For header (proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        # Check for X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        return request.client.host if request.client else "unknown"

    def _check_ip_restrictions(self, client_ip: str, ip_restrictions: list) -> bool:
        """Check if client IP is allowed by restrictions.

        Args:
            client_ip: Client's IP address
            ip_restrictions: List of allowed IP addresses/CIDR ranges

        Returns:
            bool: True if IP is allowed, False otherwise

        Examples:
            Allow specific IP:
            >>> m = TokenScopingMiddleware()
            >>> m._check_ip_restrictions('192.168.1.10', ['192.168.1.10'])
            True

            Allow CIDR range:
            >>> m._check_ip_restrictions('10.0.0.5', ['10.0.0.0/24'])
            True

            Deny when not in list:
            >>> m._check_ip_restrictions('10.0.1.5', ['10.0.0.0/24'])
            False

            Empty restrictions allow all:
            >>> m._check_ip_restrictions('203.0.113.1', [])
            True
        """
        if not ip_restrictions:
            return True  # No restrictions

        try:
            client_ip_obj = ipaddress.ip_address(client_ip)

            for restriction in ip_restrictions:
                try:
                    # Check if it's a CIDR range
                    if "/" in restriction:
                        network = ipaddress.ip_network(restriction, strict=False)
                        if client_ip_obj in network:
                            return True
                    else:
                        # Single IP address
                        if client_ip_obj == ipaddress.ip_address(restriction):
                            return True
                except (ValueError, ipaddress.AddressValueError):
                    continue

        except (ValueError, ipaddress.AddressValueError):
            return False

        return False

    def _check_time_restrictions(self, time_restrictions: dict) -> bool:
        """Check if current time is allowed by restrictions.

        Args:
            time_restrictions: Dict containing time-based restrictions

        Returns:
            bool: True if current time is allowed, False otherwise

        Examples:
            No restrictions allow access:
            >>> m = TokenScopingMiddleware()
            >>> m._check_time_restrictions({})
            True

            Weekdays only: result depends on current weekday (always bool):
            >>> isinstance(m._check_time_restrictions({'weekdays_only': True}), bool)
            True

            Business hours only: result depends on current hour (always bool):
            >>> isinstance(m._check_time_restrictions({'business_hours_only': True}), bool)
            True
        """
        if not time_restrictions:
            return True  # No restrictions

        now = datetime.now(tz=timezone.utc)

        # Check business hours restriction
        if time_restrictions.get("business_hours_only"):
            # Assume business hours are 9 AM to 5 PM UTC
            # This could be made configurable
            if not 9 <= now.hour < 17:
                return False

        # Check day of week restrictions
        weekdays_only = time_restrictions.get("weekdays_only")
        if weekdays_only and now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        return True



    def _check_permission_restrictions(self, request_path: str, request_method: str, permissions: list, permission_service: PermissionService) -> bool:
        """Check if request is allowed by permission restrictions.

        Args:
            request_path: The request path/URL
            request_method: HTTP method (GET, POST, etc.)
            permissions: List of allowed permissions
            permission_service: PermissionService instance

        Returns:
            bool: True if request is allowed, False otherwise
        """
        if not permissions or "*" in permissions:
            return True  # No restrictions or full access

        required_permission = permission_service.get_required_permission(request_method, request_path)

        if not required_permission:
            return True

        return required_permission in permissions

    async def _get_user_permissions(self, payload: dict, permission_service: PermissionService) -> List[str]:
        """
        Retrieve all permissions for the user in the token.

        Args:
            payload: Decoded JWT payload containing user info
            permission_service: PermissionService instance

        Returns:
            List[str]: List of permission strings the user has
        """
        user_email = payload.get("sub")
        
        if not user_email:
            return []
        
        # Get all permissions for the user
        permissions = await permission_service.get_user_permissions(user_email)
        
        return permissions

    async def __call__(self, request: Request, call_next):
        """Middleware function to check token scoping including team-level validation.

        Args:
            request: FastAPI request object
            call_next: Next middleware/handler in chain

        Returns:
            Response from next handler or HTTPException

        Raises:
            HTTPException: If token scoping restrictions are violated
        """
        try:
            # Skip scoping for certain paths (truly public endpoints only)
            skip_paths = [
                "/health",
                "/metrics",
                "/openapi.json",
                "/docs",
                "/redoc",
                "/auth/email/login",
                "/auth/email/register",
                "/.well-known/",
            ]

            # Check exact root path separately
            if request.url.path == "/":
                return await call_next(request)

            if any(request.url.path.startswith(path) for path in skip_paths):
                return await call_next(request)

            # Extract full token payload (not just scopes)
            payload = await self._extract_token_scopes(request)

            # If no payload, continue (regular auth will handle this)
            if not payload:
                return await call_next(request)

            # Initialize DB and Service
            db = next(get_db())
            permission_service = PermissionService(db)

            try:
                # PERMISSION RETRIEVAL: Get user permissions and cache them
                user_permissions = await self._get_user_permissions(payload, permission_service)
                
                # Validate user has some permissions (replaces team membership check)
                if not user_permissions:
                    logger.warning("Token rejected: User has no permissions")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is invalid: User has no permissions")
                
                # Cache permissions in request state for use by require_permission
                request.state.user_permissions = user_permissions
                request.state.user_email = payload.get("sub")

                # TEAM VALIDATION: Check resource team ownership
                token_teams = payload.get("teams", [])
                if not await permission_service.check_resource_access(request.url.path, token_teams):
                    logger.warning(f"Access denied: Resource does not belong to token's teams {token_teams}")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: You do not have permission to access this resource using the current token")

                # Extract scopes from payload
                scopes = payload.get("scopes", {})

                # Check IP restrictions
                ip_restrictions = scopes.get("ip_restrictions", [])
                if ip_restrictions:
                    client_ip = self._get_client_ip(request)
                    if not self._check_ip_restrictions(client_ip, ip_restrictions):
                        logger.warning(f"Request from IP {client_ip} not allowed by token restrictions")
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Request from IP {client_ip} not allowed by token restrictions")

                # Check time restrictions
                time_restrictions = scopes.get("time_restrictions", {})
                if not self._check_time_restrictions(time_restrictions):
                    logger.warning("Request not allowed at this time by token restrictions")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Request not allowed at this time by token restrictions")

                # Check permission restrictions
                permissions = scopes.get("permissions", [])
                if not self._check_permission_restrictions(request.url.path, request.method, permissions, permission_service):
                    logger.warning("Insufficient permissions for this operation")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this operation")

                # All scoping checks passed, continue
                return await call_next(request)
            
            finally:
                db.close()

        except HTTPException as exc:
            # Return clean JSON response instead of traceback
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )


# Create middleware instance
token_scoping_middleware = TokenScopingMiddleware()
