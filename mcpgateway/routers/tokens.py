# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/tokens.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token Management API Routes.
Provides API token management endpoints:
- Token creation and listing
- Token revocation and management
- Token usage statistics
"""

# Standard
import logging

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, status

# First-Party
from mcpgateway.auth import get_current_user, get_jwt_service, require_admin
from mcpgateway.db import User
from mcpgateway.schemas import ErrorResponse, TokenCreate, TokenListResponse, TokenResponse
from mcpgateway.services.jwt_service import JWTService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tokens", tags=["Token Management"])


@router.post(
    "/",
    response_model=TokenResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Token name already exists"},
    },
)
@router.post("", include_in_schema=False)  # Support both /tokens and /tokens/
async def create_token(request: Request, token_data: TokenCreate, current_user: User = Depends(get_current_user), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Create a new API token.

    Creates a new JWT token for programmatic API access.
    The raw token is only returned once - store it securely.
    """
    request.client.host if request.client else None

    try:
        token_info = await jwt_service.create_token(
            user=current_user,
            name=token_data.name,
            expires_in_days=token_data.expires_in_days,
            scopes=token_data.scopes,
            description=token_data.description,
        )

        logger.info(f"API token created by user {current_user.username}: {token_data.name}")

        # Return token response with raw JWT
        return TokenResponse(
            token=token_info["token"],  # Raw JWT (only returned once)
            id=token_info["token_id"],
            name=token_info["name"],
            description=token_info.get("description"),
            jti=token_info["jti"],
            created_at=token_info["created_at"],
            expires_at=token_info.get("expires_at"),
            last_used=None,
            is_active=True,
            scopes=token_data.scopes,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create token for user {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create token")


@router.get("/", response_model=TokenListResponse, responses={200: {"description": "List of user's API tokens"}})
@router.get("", include_in_schema=False)  # Support both /tokens and /tokens/
async def list_tokens(current_user: User = Depends(get_current_user), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    List current user's API tokens.

    Returns all API tokens for the authenticated user.
    Raw token values are never returned in listings.
    """
    try:
        tokens = await jwt_service.list_user_tokens(current_user.id)

        return TokenListResponse(
            tokens=[
                TokenResponse(
                    token=None,  # Never return raw token in listings
                    id=token["id"],
                    name=token["name"],
                    description=token.get("description"),
                    jti=token["jti"],
                    created_at=token["created_at"],
                    expires_at=token.get("expires_at"),
                    last_used=token.get("last_used"),
                    is_active=token["is_active"],
                    scopes=token.get("scopes"),
                )
                for token in tokens
            ]
        )

    except Exception as e:
        logger.error(f"Failed to list tokens for user {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve tokens")


@router.get(
    "/{token_id}",
    response_model=TokenResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Token not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to access this token"},
    },
)
async def get_token(token_id: str, current_user: User = Depends(get_current_user), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Get details of a specific API token.

    Returns token metadata (without the raw token value).
    """
    try:
        tokens = await jwt_service.list_user_tokens(current_user.id)
        token = next((t for t in tokens if t["id"] == token_id), None)

        if not token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

        return TokenResponse(
            token=None,  # Never return raw token
            id=token["id"],
            name=token["name"],
            description=token.get("description"),
            jti=token["jti"],
            created_at=token["created_at"],
            expires_at=token.get("expires_at"),
            last_used=token.get("last_used"),
            is_active=token["is_active"],
            scopes=token.get("scopes"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get token {token_id} for user {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve token")


@router.delete(
    "/{token_id}",
    responses={
        200: {"description": "Token revoked successfully"},
        404: {"model": ErrorResponse, "description": "Token not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to revoke this token"},
    },
)
async def revoke_token(token_id: str, current_user: User = Depends(get_current_user), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Revoke a specific API token.

    Immediately revokes the specified token, making it invalid for future use.
    """
    try:
        # First, get the token to verify ownership and get JTI
        tokens = await jwt_service.list_user_tokens(current_user.id)
        token = next((t for t in tokens if t["id"] == token_id), None)

        if not token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

        if not token["is_active"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token is already revoked")

        # Revoke the token using its JTI
        await jwt_service.revoke_token(token["jti"], current_user.id)

        logger.info(f"API token revoked by user {current_user.username}: {token['name']}")

        return {"message": f"Token '{token['name']}' revoked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke token {token_id} for user {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to revoke token")


@router.delete("/", responses={200: {"description": "All tokens revoked successfully"}})
async def revoke_all_tokens(current_user: User = Depends(get_current_user), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Revoke all API tokens for the current user.

    Immediately revokes all active tokens for the authenticated user.
    This is useful for security purposes if tokens may have been compromised.
    """
    try:
        count = await jwt_service.revoke_user_tokens(current_user.id, current_user.id)

        logger.info(f"All API tokens revoked by user {current_user.username} ({count} tokens)")

        return {"message": "All tokens revoked successfully", "revoked_count": count}

    except Exception as e:
        logger.error(f"Failed to revoke all tokens for user {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to revoke tokens")


# Admin endpoints for token management


@router.get(
    "/admin/user/{user_id}",
    response_model=TokenListResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def admin_list_user_tokens(user_id: str, current_user: User = Depends(require_admin), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    List API tokens for a specific user (admin only).

    Allows administrators to view all tokens for any user.
    """
    try:
        tokens = await jwt_service.list_user_tokens(user_id)

        return TokenListResponse(
            tokens=[
                TokenResponse(
                    token=None,  # Never return raw token
                    id=token["id"],
                    name=token["name"],
                    description=token.get("description"),
                    jti=token["jti"],
                    created_at=token["created_at"],
                    expires_at=token.get("expires_at"),
                    last_used=token.get("last_used"),
                    is_active=token["is_active"],
                    scopes=token.get("scopes"),
                )
                for token in tokens
            ]
        )

    except Exception as e:
        logger.error(f"Failed to list tokens for user {user_id} by admin {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve tokens")


@router.delete(
    "/admin/user/{user_id}",
    responses={
        200: {"description": "All user tokens revoked successfully"},
        404: {"model": ErrorResponse, "description": "User not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def admin_revoke_user_tokens(user_id: str, current_user: User = Depends(require_admin), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Revoke all API tokens for a specific user (admin only).

    Allows administrators to revoke all tokens for any user.
    Useful for security incidents or user deactivation.
    """
    try:
        count = await jwt_service.revoke_user_tokens(user_id, current_user.id)

        logger.warning(f"All API tokens revoked for user {user_id} by admin {current_user.username} ({count} tokens)")

        return {"message": f"All tokens revoked for user {user_id}", "revoked_count": count}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke user tokens for {user_id} by admin {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to revoke tokens")


@router.delete(
    "/admin/jti/{jti}",
    responses={
        200: {"description": "Token revoked successfully"},
        404: {"model": ErrorResponse, "description": "Token not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def admin_revoke_token_by_jti(jti: str, current_user: User = Depends(require_admin), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Revoke a specific token by JTI (admin only).

    Allows administrators to revoke any token by its JWT ID.
    Useful for emergency token revocation.
    """
    try:
        await jwt_service.revoke_token(jti, current_user.id)

        logger.warning(f"Token with JTI {jti} revoked by admin {current_user.username}")

        return {"message": f"Token with JTI {jti} revoked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke token {jti} by admin {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to revoke token")


# Token statistics and monitoring


@router.get("/stats/summary", responses={200: {"description": "Token statistics summary"}})
async def get_token_stats(current_user: User = Depends(get_current_user), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Get token statistics for the current user.

    Returns summary statistics about the user's API tokens.
    """
    try:
        tokens = await jwt_service.list_user_tokens(current_user.id)

        active_count = sum(1 for token in tokens if token["is_active"])
        revoked_count = sum(1 for token in tokens if not token["is_active"])
        expired_count = 0  # Would need to check expiration dates

        # Calculate usage statistics
        used_recently = 0
        never_used = 0

        for token in tokens:
            if token.get("last_used"):
                # Token has been used - could add time-based analysis here
                used_recently += 1
            else:
                never_used += 1

        return {
            "total_tokens": len(tokens),
            "active_tokens": active_count,
            "revoked_tokens": revoked_count,
            "expired_tokens": expired_count,
            "tokens_used_recently": used_recently,
            "tokens_never_used": never_used,
        }

    except Exception as e:
        logger.error(f"Failed to get token stats for user {current_user.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve token statistics")
