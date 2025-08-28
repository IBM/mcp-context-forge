# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/admin_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Admin Authentication Bridge.
Provides authentication compatibility between legacy admin auth and multi-user mode.
"""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBearer

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.verify_credentials import require_auth

logger = logging.getLogger(__name__)

# Security schemes
basic_security = HTTPBasic(auto_error=False)
bearer_security = HTTPBearer(auto_error=False)


async def require_admin_auth(
    request: Request,
    basic_credentials: Optional[HTTPBasic] = Depends(basic_security),
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_security),
) -> str:
    """
    Admin authentication that works in both legacy and multi-user modes.

    In legacy mode: Uses basic auth with BASIC_AUTH_USER/BASIC_AUTH_PASSWORD
    In multi-user mode: Uses JWT Bearer tokens, but falls back to basic auth for admin user

    Args:
        request: FastAPI request object
        basic_credentials: HTTP Basic credentials if provided
        bearer_credentials: HTTP Bearer credentials if provided

    Returns:
        str: Username of authenticated admin user

    Raises:
        HTTPException: If authentication fails
    """
    try:
        # If multi-user mode is disabled, use legacy auth
        if not settings.multi_user_enabled or settings.legacy_auth_mode:
            return await require_auth(request)

        # Multi-user mode: Try both Bearer and Basic auth

        # 1. Try Bearer token first (preferred in multi-user mode)
        if bearer_credentials:
            try:
                # First-Party
                from mcpgateway.db import SessionLocal
                from mcpgateway.services.jwt_service import JWTService

                # Create a minimal request-like object for JWT verification
                with SessionLocal() as db:
                    jwt_service = JWTService(db)
                    payload = await jwt_service.verify_token(bearer_credentials.credentials, request)
                    user_data = payload.get("user")

                    if user_data and user_data.get("is_admin"):
                        return user_data["username"]
                    else:
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")

            except HTTPException:
                # JWT failed, try basic auth fallback
                pass

        # 2. Fallback to basic auth for admin user
        if basic_credentials:
            if basic_credentials.username == settings.basic_auth_user and basic_credentials.password == settings.basic_auth_password:

                # In multi-user mode, verify this admin user exists
                try:
                    # First-Party
                    from mcpgateway.db import SessionLocal
                    from mcpgateway.services.user_service import UserService

                    with SessionLocal() as db:
                        user_service = UserService(db)
                        admin_user = await user_service.get_user_by_username(settings.basic_auth_user)

                        if admin_user and admin_user.is_admin:
                            return admin_user.username
                        else:
                            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin user not found or not admin")

                except Exception as e:
                    logger.error(f"Error verifying admin user in multi-user mode: {e}")
                    # Fall back to basic auth verification
                    return settings.basic_auth_user
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                    headers={"WWW-Authenticate": "Basic"},
                )

        # No valid credentials provided
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin authentication error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Authentication system error")


# Backward compatibility alias
require_admin = require_admin_auth
