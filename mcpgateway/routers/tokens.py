# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/tokens.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

JWT Token Catalog API endpoints.
Provides comprehensive API token management with scoping, revocation, and analytics.
"""

# Standard
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import TokenCreateRequest, TokenCreateResponse, TokenListResponse, TokenResponse, TokenRevokeRequest, TokenUpdateRequest, TokenUsageStatsResponse
from mcpgateway.services.token_catalog_service import TokenCatalogService, TokenScope

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.post("", response_model=TokenCreateResponse, status_code=status.HTTP_201_CREATED)
@require_permission("tokens.create")
async def create_token(
    request: TokenCreateRequest,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> TokenCreateResponse:
    """Create a new API token for the current user.

    Args:
        request: Token creation request with name, description, scoping, etc.
        current_user: Authenticated user from JWT
        db: Database session

    Returns:
        TokenCreateResponse: Created token details with raw token

    Raises:
        HTTPException: If token name already exists or validation fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(create_token)
        True
    """
    service = TokenCatalogService(db)

    # if not request.team_id:
    #     raise HTTPException(
    #         status_code=status.HTTP_400_BAD_REQUEST, detail="team_id is required. Please select a specific team before creating a token. You cannot create tokens while viewing 'All Teams'."
    #     )

    # Convert request to TokenScope if provided
    scope = None
    if request.scope:
        scope = TokenScope(
            server_id=request.scope.server_id,
            permissions=request.scope.permissions,
            ip_restrictions=request.scope.ip_restrictions,
            time_restrictions=request.scope.time_restrictions,
            usage_limits=request.scope.usage_limits,
        )

    try:
        token_record, raw_token = await service.create_token(
            user_email=current_user["email"],
            name=request.name,
            description=request.description,
            scope=scope,
            expires_in_days=request.expires_in_days,
            tags=request.tags,
            team_id=request.team_id,
        )

        # Create TokenResponse for the token info
        token_response = TokenResponse(
            id=token_record.id,
            name=token_record.name,
            description=token_record.description,
            user_email=token_record.user_email,
            team_id=token_record.team_id,
            server_id=token_record.server_id,
            resource_scopes=token_record.resource_scopes or [],
            ip_restrictions=token_record.ip_restrictions or [],
            time_restrictions=token_record.time_restrictions or {},
            usage_limits=token_record.usage_limits or {},
            created_at=token_record.created_at,
            expires_at=token_record.expires_at,
            last_used=token_record.last_used,
            is_active=token_record.is_active,
            tags=token_record.tags or [],
        )

        return TokenCreateResponse(
            token=token_response,
            access_token=raw_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=TokenListResponse)
@require_permission("tokens.read")
async def list_tokens(
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_permissions),
) -> TokenListResponse:
    """List API tokens for the current user.

    Args:
        include_inactive: Include inactive/expired tokens
        limit: Maximum number of tokens to return (default 50)
        offset: Number of tokens to skip for pagination
        current_user: Authenticated user from JWT
        db: Database session

    Returns:
        TokenListResponse: List of user's API tokens

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(list_tokens)
        True
    """
    service = TokenCatalogService(db)
    tokens = await service.list_user_tokens(
        user_email=current_user["email"],
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )

    token_responses = []
    for token in tokens:
        # Check if token is revoked
        revocation_info = await service.get_token_revocation(token.jti)

        token_responses.append(
            TokenResponse(
                id=token.id,
                name=token.name,
                description=token.description,
                user_email=token.user_email,
                team_id=token.team_id,
                created_at=token.created_at,
                expires_at=token.expires_at,
                last_used=token.last_used,
                is_active=token.is_active,
                is_revoked=revocation_info is not None,
                revoked_at=revocation_info.revoked_at if revocation_info else None,
                revoked_by=revocation_info.revoked_by if revocation_info else None,
                revocation_reason=revocation_info.reason if revocation_info else None,
                tags=token.tags,
                server_id=token.server_id,
                resource_scopes=token.resource_scopes,
                ip_restrictions=token.ip_restrictions,
                time_restrictions=token.time_restrictions,
                usage_limits=token.usage_limits,
            )
        )

    return TokenListResponse(tokens=token_responses, total=len(token_responses), limit=limit, offset=offset)


@router.get("/{token_id}", response_model=TokenResponse)
async def get_token(
    token_id: str,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Get details of a specific token.

    Args:
        token_id: Token ID to retrieve
        current_user: Authenticated user from JWT
        db: Database session

    Returns:
        TokenResponse: Token details

    Raises:
        HTTPException: If token not found or not owned by user

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(get_token)
        True
    """
    service = TokenCatalogService(db)
    token = await service.get_token(token_id, current_user["email"])

    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    return TokenResponse(
        id=token.id,
        name=token.name,
        description=token.description,
        user_email=token.user_email,
        team_id=token.team_id,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used=token.last_used,
        is_active=token.is_active,
        tags=token.tags,
        server_id=token.server_id,
        resource_scopes=token.resource_scopes,
        ip_restrictions=token.ip_restrictions,
        time_restrictions=token.time_restrictions,
        usage_limits=token.usage_limits,
    )


@router.put("/{token_id}", response_model=TokenResponse)
async def update_token(
    token_id: str,
    request: TokenUpdateRequest,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Update an existing token.

    Args:
        token_id: Token ID to update
        request: Token update request
        current_user: Authenticated user from JWT
        db: Database session

    Returns:
        TokenResponse: Updated token details

    Raises:
        HTTPException: If token not found or validation fails
    """
    service = TokenCatalogService(db)

    # Convert request to TokenScope if provided
    scope = None
    if request.scope:
        scope = TokenScope(
            server_id=request.scope.server_id,
            permissions=request.scope.permissions,
            ip_restrictions=request.scope.ip_restrictions,
            time_restrictions=request.scope.time_restrictions,
            usage_limits=request.scope.usage_limits,
        )

    try:
        token = await service.update_token(
            token_id=token_id,
            user_email=current_user["email"],
            name=request.name,
            description=request.description,
            scope=scope,
            tags=request.tags,
        )

        if not token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

        return TokenResponse(
            id=token.id,
            name=token.name,
            description=token.description,
            user_email=token.user_email,
            team_id=token.team_id,
            created_at=token.created_at,
            expires_at=token.expires_at,
            last_used=token.last_used,
            is_active=token.is_active,
            tags=token.tags,
            server_id=token.server_id,
            resource_scopes=token.resource_scopes,
            ip_restrictions=token.ip_restrictions,
            time_restrictions=token.time_restrictions,
            usage_limits=token.usage_limits,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: str,
    request: Optional[TokenRevokeRequest] = None,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> None:
    """Revoke (delete) a token.

    Args:
        token_id: Token ID to revoke
        request: Optional revocation request with reason
        current_user: Authenticated user from JWT
        db: Database session

    Raises:
        HTTPException: If token not found
    """
    service = TokenCatalogService(db)

    reason = request.reason if request else "Revoked by user"
    success = await service.revoke_token(token_id=token_id, revoked_by=current_user["email"], reason=reason)

    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")


@router.get("/{token_id}/usage", response_model=TokenUsageStatsResponse)
async def get_token_usage_stats(
    token_id: str,
    days: int = 30,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> TokenUsageStatsResponse:
    """Get usage statistics for a specific token.

    Args:
        token_id: Token ID to get stats for
        days: Number of days to analyze (default 30)
        current_user: Authenticated user from JWT
        db: Database session

    Returns:
        TokenUsageStatsResponse: Token usage statistics

    Raises:
        HTTPException: If token not found or not owned by user
    """
    service = TokenCatalogService(db)

    # Verify token ownership
    token = await service.get_token(token_id, current_user["email"])
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    stats = await service.get_token_usage_stats(user_email=current_user["email"], token_id=token_id, days=days)

    return TokenUsageStatsResponse(**stats)


# Admin endpoints for token oversight
@router.get("/admin/all", response_model=TokenListResponse, tags=["admin"])
async def list_all_tokens(
    user_email: Optional[str] = None,
    include_inactive: bool = False,
    limit: int = 100,
    offset: int = 0,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> TokenListResponse:
    """Admin endpoint to list all tokens or tokens for a specific user.

    Args:
        user_email: Filter tokens by user email (admin only)
        include_inactive: Include inactive/expired tokens
        limit: Maximum number of tokens to return
        offset: Number of tokens to skip
        current_user: Authenticated admin user
        db: Database session

    Returns:
        TokenListResponse: List of tokens

    Raises:
        HTTPException: If user is not admin
    """
    if not current_user["is_admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    service = TokenCatalogService(db)

    if user_email:
        # Get tokens for specific user
        tokens = await service.list_user_tokens(
            user_email=user_email,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
    else:
        # This would need a new method in service for all tokens
        # For now, return empty list - can implement later if needed
        tokens = []

    token_responses = []
    for token in tokens:
        # Check if token is revoked
        revocation_info = await service.get_token_revocation(token.jti)

        token_responses.append(
            TokenResponse(
                id=token.id,
                name=token.name,
                description=token.description,
                user_email=token.user_email,
                team_id=token.team_id,
                created_at=token.created_at,
                expires_at=token.expires_at,
                last_used=token.last_used,
                is_active=token.is_active,
                is_revoked=revocation_info is not None,
                revoked_at=revocation_info.revoked_at if revocation_info else None,
                revoked_by=revocation_info.revoked_by if revocation_info else None,
                revocation_reason=revocation_info.reason if revocation_info else None,
                tags=token.tags,
                server_id=token.server_id,
                resource_scopes=token.resource_scopes,
                ip_restrictions=token.ip_restrictions,
                time_restrictions=token.time_restrictions,
                usage_limits=token.usage_limits,
            )
        )

    return TokenListResponse(tokens=token_responses, total=len(token_responses), limit=limit, offset=offset)


@router.delete("/admin/{token_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["admin"])
async def admin_revoke_token(
    token_id: str,
    request: Optional[TokenRevokeRequest] = None,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> None:
    """Admin endpoint to revoke any token.

    Args:
        token_id: Token ID to revoke
        request: Optional revocation request with reason
        current_user: Authenticated admin user
        db: Database session

    Raises:
        HTTPException: If user is not admin or token not found
    """
    if not current_user["is_admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    service = TokenCatalogService(db)
    admin_email = current_user["email"]
    reason = request.reason if request else f"Revoked by admin {admin_email}"

    success = await service.revoke_token(token_id=token_id, revoked_by=current_user["email"], reason=reason)

    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")


# Team-based token endpoints
@router.post("/teams/{team_id}", response_model=TokenCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_team_token(
    team_id: str,
    request: TokenCreateRequest,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> TokenCreateResponse:
    """Create a new API token for a team (only team owners can do this).

    Args:
        team_id: Team ID to create token for
        request: Token creation request with name, description, scoping, etc.
        current_user: Authenticated user (must be team owner)
        db: Database session

    Returns:
        TokenCreateResponse: Created token details with raw token

    Raises:
        HTTPException: If user is not team owner or validation fails
    """
    service = TokenCatalogService(db)

    # Convert request to TokenScope if provided
    scope = None
    if request.scope:
        scope = TokenScope(
            server_id=request.scope.server_id,
            permissions=request.scope.permissions,
            ip_restrictions=request.scope.ip_restrictions,
            time_restrictions=request.scope.time_restrictions,
            usage_limits=request.scope.usage_limits,
        )

    try:
        token_record, raw_token = await service.create_token(
            user_email=current_user["email"],
            name=request.name,
            description=request.description,
            scope=scope,
            expires_in_days=request.expires_in_days,
            tags=request.tags,
            team_id=team_id,  # This will validate team ownership
        )

        # Create TokenResponse for the token info
        token_response = TokenResponse(
            id=token_record.id,
            name=token_record.name,
            description=token_record.description,
            user_email=token_record.user_email,
            team_id=token_record.team_id,
            server_id=token_record.server_id,
            resource_scopes=token_record.resource_scopes or [],
            ip_restrictions=token_record.ip_restrictions or [],
            time_restrictions=token_record.time_restrictions or {},
            usage_limits=token_record.usage_limits or {},
            created_at=token_record.created_at,
            expires_at=token_record.expires_at,
            last_used=token_record.last_used,
            is_active=token_record.is_active,
            tags=token_record.tags or [],
        )

        return TokenCreateResponse(
            token=token_response,
            access_token=raw_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/teams/{team_id}", response_model=TokenListResponse)
async def list_team_tokens(
    team_id: str,
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
    current_user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> TokenListResponse:
    """List API tokens for a team (only team owners can do this).

    Args:
        team_id: Team ID to list tokens for
        include_inactive: Include inactive/expired tokens
        limit: Maximum number of tokens to return (default 50)
        offset: Number of tokens to skip for pagination
        current_user: Authenticated user (must be team owner)
        db: Database session

    Returns:
        TokenListResponse: List of teams API tokens

    Raises:
        HTTPException: If user is not team owner
    """
    service = TokenCatalogService(db)

    try:
        tokens = await service.list_team_tokens(
            team_id=team_id,
            user_email=current_user["email"],  # This will validate team ownership
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )

        token_responses = []
        for token in tokens:
            # Check if token is revoked
            revocation_info = await service.get_token_revocation(token.jti)

            token_responses.append(
                TokenResponse(
                    id=token.id,
                    name=token.name,
                    description=token.description,
                    user_email=token.user_email,
                    team_id=token.team_id,
                    created_at=token.created_at,
                    expires_at=token.expires_at,
                    last_used=token.last_used,
                    is_active=token.is_active,
                    is_revoked=revocation_info is not None,
                    revoked_at=revocation_info.revoked_at if revocation_info else None,
                    revoked_by=revocation_info.revoked_by if revocation_info else None,
                    revocation_reason=revocation_info.reason if revocation_info else None,
                    tags=token.tags,
                    server_id=token.server_id,
                    resource_scopes=token.resource_scopes,
                    ip_restrictions=token.ip_restrictions,
                    time_restrictions=token.time_restrictions,
                    usage_limits=token.usage_limits,
                )
            )

        return TokenListResponse(tokens=token_responses, total=len(token_responses), limit=limit, offset=offset)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
