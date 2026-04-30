# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/token_usage_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token Usage Logging Middleware.

This middleware logs API token usage for analytics and security monitoring.
It records each request made with an API token, including endpoint, method,
response time, and status code.

Note: Implemented as raw ASGI middleware (not BaseHTTPMiddleware) to avoid
response body buffering issues with streaming responses.

Examples:
    >>> from mcpgateway.middleware.token_usage_middleware import TokenUsageMiddleware  # doctest: +SKIP
    >>> app.add_middleware(TokenUsageMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
import time
from typing import Optional

# Third-Party
import jwt as _jwt
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

# First-Party
from mcpgateway.db import fresh_db_session
from mcpgateway.middleware.path_filter import should_skip_auth_context
from mcpgateway.services.token_catalog_service import TokenCatalogService
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

logger = logging.getLogger(__name__)


class TokenUsageMiddleware:
    """Raw ASGI middleware for logging API token usage.

    This middleware tracks when API tokens are used, recording details like:
    - Endpoint accessed
    - HTTP method
    - Response status code
    - Response time
    - Client IP and user agent

    This data is used for security auditing, usage analytics, and detecting
    anomalous token usage patterns.

    Note:
        Only logs usage for requests authenticated with API tokens (identified
        by request.state.auth_method == "api_token").

        Implemented as raw ASGI middleware to avoid BaseHTTPMiddleware issues:
        - BaseHTTPMiddleware buffers entire response bodies (problematic for streaming)
        - Raw ASGI middleware streams responses efficiently
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize middleware.

        Args:
            app: ASGI application to wrap
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request.

        Args:
            scope: ASGI scope dict
            receive: Receive callable
            send: Send callable
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip health checks and static files
        path = scope.get("path", "")
        if should_skip_auth_context(path):
            await self.app(scope, receive, send)
            return

        # Record start time
        start_time = time.time()

        # Capture response status
        status_code = 200  # Default

        async def send_wrapper(message: dict) -> None:
            """Wrap send to capture response status.

            Args:
                message: ASGI message dict containing response data
            """
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        # Process request
        await self.app(scope, receive, send_wrapper)

        # Calculate response time
        response_time_ms = round((time.time() - start_time) * 1000)

        # Log API token usage — covers both successful requests and auth-rejected attempts.
        # Every request that uses (or tries to use) an API token is recorded,
        # including blocked calls with revoked/expired tokens, so that usage stats are accurate.
        state = scope.get("state", {})
        auth_method = state.get("auth_method") if state else None

        jti: Optional[str] = None
        user_email: Optional[str] = None
        blocked: bool = False
        block_reason: Optional[str] = None

        if auth_method == "api_token":
            # --- Successfully authenticated API token request ---
            jti = state.get("jti") if state else None
            user = state.get("user") if state else None
            user_email = getattr(user, "email", None) if user else None
            if not user_email:
                user_email = state.get("user_email") if state else None

            # If we don't have JTI or email, try to decode the token from the header
            if not jti or not user_email:
                try:
                    headers = Headers(scope=scope)
                    auth_header = headers.get("authorization")
                    if not auth_header or not auth_header.startswith("Bearer "):
                        return
                    token = auth_header.replace("Bearer ", "")
                    request = Request(scope, receive)
                    try:
                        payload = await verify_jwt_token_cached(token, request)
                        jti = jti or payload.get("jti")
                        user_email = user_email or payload.get("sub") or payload.get("email")
                    except Exception as decode_error:
                        logger.debug(f"Failed to decode token for usage logging: {decode_error}")
                        return
                except Exception as e:
                    logger.debug(f"Error extracting token information: {e}")
                    return

            if not jti or not user_email:
                logger.debug("Missing JTI or user_email for token usage logging")
                return

            # Bug 3a fix: reflect the actual outcome — 4xx responses mark the attempt
            # as blocked (e.g. RBAC denied, rate-limited, or server-scoping violation).
            # 5xx errors are backend failures, not security denials, so exclude them.
            blocked = 400 <= status_code < 500
            if blocked:
                block_reason = f"http_{status_code}"

        elif status_code in (401, 403):
            # --- Auth-rejected request: check if the Bearer token was an API token ---
            # When a revoked or expired API token is used, auth middleware rejects the
            # request before setting auth_method="api_token", so the path above is
            # never reached.  We detect the attempt here by decoding the JWT payload
            # without re-verifying it (the token identity is valid even if rejected).
            try:
                headers = Headers(scope=scope)
                auth_header = headers.get("authorization")
                if not auth_header or not auth_header.startswith("Bearer "):
                    return
                raw_token = auth_header[7:]  # strip "Bearer "

                # Decode without signature/expiry check — for identification only, not auth.
                unverified = _jwt.decode(raw_token, options={"verify_signature": False})
                user_info = unverified.get("user", {})
                if user_info.get("auth_provider") != "api_token":
                    return  # Not an API token — nothing to log

                jti = unverified.get("jti")
                user_email = unverified.get("sub") or unverified.get("email")
                if not jti or not user_email:
                    return

                # Verify JTI belongs to a real API token before logging.
                # Without this check, an attacker can craft a JWT with fake
                # jti/sub and auth_provider=api_token to pollute usage logs.
                # Verify JTI belongs to a real API token and use the DB-stored
                # owner email instead of the unverified JWT claim.  Without this,
                # an attacker who knows a valid JTI could forge a JWT with an
                # arbitrary sub/email to poison another user's usage stats.
                try:
                    # Third-Party
                    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                    # First-Party
                    from mcpgateway.db import EmailApiToken  # pylint: disable=import-outside-toplevel

                    with fresh_db_session() as verify_db:
                        token_row = verify_db.execute(select(EmailApiToken.id, EmailApiToken.user_email).where(EmailApiToken.jti == jti)).first()
                        if token_row is None:
                            return  # JTI not in DB — forged token, skip logging
                        # Use the DB-stored owner, not the unverified JWT claim
                        user_email = token_row.user_email
                except Exception:
                    return  # DB error — skip logging rather than log unverified data

                blocked = True
                block_reason = "revoked_or_expired" if status_code == 401 else f"http_{status_code}"
            except Exception as e:
                logger.debug(f"Failed to extract API token identity from rejected request: {e}")
                return
        else:
            return  # Not an API token request — nothing to log

        # Shared logging path for both authenticated and blocked API token requests
        try:
            with fresh_db_session() as db:
                token_service = TokenCatalogService(db)
                client = scope.get("client")
                ip_address = client[0] if client else None
                headers = Headers(scope=scope)
                user_agent = headers.get("user-agent")

                await token_service.log_token_usage(
                    jti=jti,
                    user_email=user_email,
                    endpoint=path,
                    method=scope.get("method", "GET"),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status_code=status_code,
                    response_time_ms=response_time_ms,
                    blocked=blocked,
                    block_reason=block_reason,
                )
        except Exception as e:
            logger.debug(f"Failed to log token usage: {e}")
