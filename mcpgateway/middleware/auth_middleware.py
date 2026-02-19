# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/auth_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Authentication Middleware for early user context extraction.

This middleware extracts user information from JWT tokens early in the request
lifecycle and stores it in request.state.user for use by other middleware
(like ObservabilityMiddleware) and route handlers.

Examples:
    >>> from mcpgateway.middleware.auth_middleware import AuthContextMiddleware  # doctest: +SKIP
    >>> app.add_middleware(AuthContextMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
from typing import Callable

# Third-Party
from fastapi.security import HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.middleware.path_filter import should_skip_auth_context
from mcpgateway.services.security_logger import get_security_logger
from mcpgateway.services.siem_export_service import get_siem_export_service

logger = logging.getLogger(__name__)
security_logger = get_security_logger()


def _should_log_auth_success() -> bool:
    """Check if successful authentication should be captured.

    Returns:
        True when DB security logging requires it or SIEM auth source is enabled.
    """
    db_logging_enabled = settings.security_logging_enabled and settings.security_logging_level == "all"
    siem_service = get_siem_export_service()
    siem_logging_enabled = (settings.siem_export_enabled or siem_service.enabled or bool(siem_service.destinations)) and siem_service.is_source_enabled("auth")
    return db_logging_enabled or siem_logging_enabled


def _should_log_auth_failure() -> bool:
    """Check if failed authentication should be captured.

    Returns:
        True when DB security logging requires it or SIEM auth source is enabled.
    """
    db_logging_enabled = settings.security_logging_enabled and settings.security_logging_level in ("all", "failures_only")
    siem_service = get_siem_export_service()
    siem_logging_enabled = (settings.siem_export_enabled or siem_service.enabled or bool(siem_service.destinations)) and siem_service.is_source_enabled("auth")
    return db_logging_enabled or siem_logging_enabled


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Middleware for extracting user authentication context early in request lifecycle.

    This middleware attempts to authenticate requests using JWT tokens from cookies
    or Authorization headers, and stores the user information in request.state.user
    for downstream middleware and handlers to use.

    Unlike route-level authentication dependencies, this runs for ALL requests,
    allowing middleware like ObservabilityMiddleware to access user context.

    Note:
        Authentication failures are silent - requests continue as unauthenticated.
        Route-level dependencies should still enforce authentication requirements.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and populate user context if authenticated.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response
        """
        # Skip for health checks and static files
        if should_skip_auth_context(request.url.path):
            return await call_next(request)

        # Try to extract token from multiple sources
        token = None

        # 1. Try manual cookie reading
        if request.cookies:
            token = request.cookies.get("jwt_token") or request.cookies.get("access_token")

        # 2. Try Authorization header
        if not token:
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "")

        # If no token found, continue without user context
        if not token:
            return await call_next(request)

        # Check logging settings once upfront to avoid DB session when not needed
        log_success = _should_log_auth_success()
        log_failure = _should_log_auth_failure()
        siem_runtime_enabled = settings.siem_export_enabled or get_siem_export_service().enabled
        persist_to_db = settings.security_logging_enabled or not siem_runtime_enabled

        # Try to authenticate and populate user context
        # Note: get_current_user manages its own DB sessions internally
        # We only create a DB session here when security logging is enabled
        try:
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            user = await get_current_user(credentials, request=request)

            # Note: EmailUser uses 'email' as primary key, not 'id'
            # User is already detached (created with fresh session that was closed)
            user_email = user.email
            user_id = user_email  # For EmailUser, email IS the ID

            # Store user in request state for downstream use
            request.state.user = user
            logger.info(f"✓ Authenticated user: {user_email if user_email else user_id}")

            # Log successful authentication (only if logging level is "all")
            # DB session created only when needed
            if log_success:
                if persist_to_db:
                    db = SessionLocal()
                    try:
                        security_logger.log_authentication_attempt(
                            user_id=user_id,
                            user_email=user_email,
                            auth_method="bearer_token",
                            success=True,
                            client_ip=request.client.host if request.client else "unknown",
                            user_agent=request.headers.get("user-agent"),
                            db=db,
                            persist=True,
                        )
                        db.commit()
                    except Exception as log_error:
                        logger.debug(f"Failed to log successful auth: {log_error}")
                    finally:
                        try:
                            db.close()
                        except Exception as close_error:
                            logger.debug(f"Failed to close database session: {close_error}")
                else:
                    security_logger.log_authentication_attempt(
                        user_id=user_id,
                        user_email=user_email,
                        auth_method="bearer_token",
                        success=True,
                        client_ip=request.client.host if request.client else "unknown",
                        user_agent=request.headers.get("user-agent"),
                        persist=False,
                    )

        except Exception as e:
            # Silently fail - let route handlers enforce auth if needed
            logger.info(f"✗ Auth context extraction failed (continuing as anonymous): {e}")

            # Log failed authentication attempt (based on logging level)
            # DB session created only when needed
            if log_failure:
                if persist_to_db:
                    db = SessionLocal()
                    try:
                        security_logger.log_authentication_attempt(
                            user_id="unknown",
                            user_email=None,
                            auth_method="bearer_token",
                            success=False,
                            client_ip=request.client.host if request.client else "unknown",
                            user_agent=request.headers.get("user-agent"),
                            failure_reason=str(e),
                            db=db,
                            persist=True,
                        )
                        db.commit()
                    except Exception as log_error:
                        logger.debug(f"Failed to log auth failure: {log_error}")
                    finally:
                        try:
                            db.close()
                        except Exception as close_error:
                            logger.debug(f"Failed to close database session: {close_error}")
                else:
                    security_logger.log_authentication_attempt(
                        user_id="unknown",
                        user_email=None,
                        auth_method="bearer_token",
                        success=False,
                        client_ip=request.client.host if request.client else "unknown",
                        user_agent=request.headers.get("user-agent"),
                        failure_reason=str(e),
                        persist=False,
                    )

        # Continue with request
        return await call_next(request)
