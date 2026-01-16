# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/sso.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Single Sign-On (SSO) authentication routes for OAuth2/OIDC providers.
Handles SSO login flows, provider configuration, and callback handling.
"""

# Standard
from typing import Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.sso_service import SSOService


class SSOProviderCreateRequest(BaseModel):
    """Request to create SSO provider."""

    id: str
    name: str
    display_name: str
    provider_type: str  # oauth2, oidc
    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    userinfo_url: str
    issuer: Optional[str] = None
    scope: str = "openid profile email"
    trusted_domains: List[str] = []
    auto_create_users: bool = True
    team_mapping: Dict = {}
    provider_metadata: Dict = {}  # Role mappings, groups_claim config, etc.


class SSOProviderUpdateRequest(BaseModel):
    """Request to update SSO provider."""

    name: Optional[str] = None
    display_name: Optional[str] = None
    provider_type: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    authorization_url: Optional[str] = None
    token_url: Optional[str] = None
    userinfo_url: Optional[str] = None
    issuer: Optional[str] = None
    scope: Optional[str] = None
    trusted_domains: Optional[List[str]] = None
    auto_create_users: Optional[bool] = None
    team_mapping: Optional[Dict] = None
    provider_metadata: Optional[Dict] = None  # Role mappings, groups_claim config, etc.
    is_enabled: Optional[bool] = None


# Create router
sso_router = APIRouter(prefix="/auth/sso", tags=["SSO Authentication"])


class SSOProviderResponse(BaseModel):
    """SSO provider information for client."""

    id: str
    name: str
    display_name: str
    authorization_url: Optional[str] = None  # Only provided when initiating login


class SSOLoginResponse(BaseModel):
    """SSO login initiation response."""

    authorization_url: str
    state: str


class SSOCallbackResponse(BaseModel):
    """SSO authentication callback response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Dict


@sso_router.get("/providers", response_model=List[SSOProviderResponse])
async def list_sso_providers(
    db: Session = Depends(get_db),
) -> List[SSOProviderResponse]:
    """List available SSO providers for login.

    Args:
        db: Database session

    Returns:
        List of enabled SSO providers with basic information.

    Raises:
        HTTPException: If SSO authentication is disabled

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(list_sso_providers)
        True
    """
    if not settings.sso_enabled:
        raise HTTPException(status_code=404, detail="SSO authentication is disabled")

    sso_service = SSOService(db)
    providers = sso_service.list_enabled_providers()

    return [SSOProviderResponse(id=provider.id, name=provider.name, display_name=provider.display_name) for provider in providers]


@sso_router.get("/login/{provider_id}", response_model=SSOLoginResponse)
async def initiate_sso_login(
    provider_id: str,
    redirect_uri: str = Query(..., description="Callback URI after authentication"),
    scopes: Optional[str] = Query(None, description="Space-separated OAuth scopes"),
    db: Session = Depends(get_db),
) -> SSOLoginResponse:
    """Initiate SSO authentication flow.

    Args:
        provider_id: SSO provider identifier (e.g., 'github', 'google')
        redirect_uri: Callback URI after successful authentication
        scopes: Optional custom OAuth scopes (space-separated)
        db: Database session

    Returns:
        Authorization URL and state parameter for redirect.

    Raises:
        HTTPException: If SSO is disabled or provider not found

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(initiate_sso_login)
        True
    """
    if not settings.sso_enabled:
        raise HTTPException(status_code=404, detail="SSO authentication is disabled")

    sso_service = SSOService(db)
    scope_list = scopes.split() if scopes else None

    auth_url = sso_service.get_authorization_url(provider_id, redirect_uri, scope_list)
    if not auth_url:
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider_id}' not found or disabled")

    # Extract state from URL for client reference
    # Standard
    import urllib.parse

    parsed = urllib.parse.urlparse(auth_url)
    params = urllib.parse.parse_qs(parsed.query)
    state = params.get("state", [""])[0]

    return SSOLoginResponse(authorization_url=auth_url, state=state)


@sso_router.get("/callback/{provider_id}")
async def handle_sso_callback(
    provider_id: str,
    code: str = Query(..., description="Authorization code from SSO provider"),
    state: str = Query(..., description="CSRF state parameter"),
    request: Request = None,
    response: Response = None,
    db: Session = Depends(get_db),
):
    """Handle SSO authentication callback.

    Args:
        provider_id: SSO provider identifier
        code: Authorization code from provider
        state: CSRF state parameter for validation
        request: FastAPI request object
        response: FastAPI response object
        db: Database session

    Returns:
        JWT access token and user information.

    Raises:
        HTTPException: If SSO is disabled or authentication fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(handle_sso_callback)
        True
    """
    if not settings.sso_enabled:
        raise HTTPException(status_code=404, detail="SSO authentication is disabled")

    # Get root path for URL construction
    root_path = request.scope.get("root_path", "") if request else ""

    sso_service = SSOService(db)

    # Handle OAuth callback
    user_info = await sso_service.handle_oauth_callback(provider_id, code, state)
    if not user_info:
        # Redirect back to login with error
        # Third-Party
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=f"{root_path}/admin/login?error=sso_failed", status_code=302)

    # Authenticate or create user
    access_token = await sso_service.authenticate_or_create_user(user_info)
    if not access_token:
        # Redirect back to login with error
        # Third-Party
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=f"{root_path}/admin/login?error=user_creation_failed", status_code=302)

    # Create redirect response
    # Third-Party
    from fastapi.responses import RedirectResponse

    redirect_response = RedirectResponse(url=f"{root_path}/admin", status_code=302)

    # Set secure HTTP-only cookie using the same method as email auth
    # First-Party
    from mcpgateway.utils.security_cookies import set_auth_cookie

    set_auth_cookie(redirect_response, access_token, remember_me=False)

    return redirect_response


# Admin endpoints for SSO provider management
@sso_router.post("/admin/providers", response_model=Dict)
@require_permission("admin.sso_providers:create")
async def create_sso_provider(
    provider_data: SSOProviderCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict:
    """Create new SSO provider configuration (Admin only).

    Args:
        provider_data: SSO provider configuration
        db: Database session
        user: Current authenticated user

    Returns:
        Created provider information.

    Raises:
        HTTPException: If provider already exists or creation fails
    """
    sso_service = SSOService(db)

    # Check if provider already exists
    existing = sso_service.get_provider(provider_data.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"SSO provider '{provider_data.id}' already exists")

    provider = sso_service.create_provider(provider_data.dict())

    return {
        "id": provider.id,
        "name": provider.name,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "is_enabled": provider.is_enabled,
        "created_at": provider.created_at,
    }


@sso_router.get("/admin/providers", response_model=List[Dict])
@require_permission("admin.sso_providers:read")
async def list_all_sso_providers(
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> List[Dict]:
    """List all SSO providers including disabled ones (Admin only).

    Args:
        db: Database session
        user: Current authenticated user

    Returns:
        List of all SSO providers with configuration details.
    """
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import SSOProvider

    stmt = select(SSOProvider)
    result = db.execute(stmt)
    providers = result.scalars().all()

    return [
        {
            "id": provider.id,
            "name": provider.name,
            "display_name": provider.display_name,
            "provider_type": provider.provider_type,
            "is_enabled": provider.is_enabled,
            "trusted_domains": provider.trusted_domains,
            "auto_create_users": provider.auto_create_users,
            "created_at": provider.created_at,
            "updated_at": provider.updated_at,
        }
        for provider in providers
    ]


@sso_router.get("/admin/providers/{provider_id}", response_model=Dict)
@require_permission("admin.sso_providers:read")
async def get_sso_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict:
    """Get SSO provider details (Admin only).

    Args:
        provider_id: Provider identifier
        db: Database session
        user: Current authenticated user

    Returns:
        Provider configuration details.

    Raises:
        HTTPException: If provider not found
    """
    sso_service = SSOService(db)
    provider = sso_service.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider_id}' not found")

    return {
        "id": provider.id,
        "name": provider.name,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "client_id": provider.client_id,
        "authorization_url": provider.authorization_url,
        "token_url": provider.token_url,
        "userinfo_url": provider.userinfo_url,
        "issuer": provider.issuer,
        "scope": provider.scope,
        "trusted_domains": provider.trusted_domains,
        "auto_create_users": provider.auto_create_users,
        "team_mapping": provider.team_mapping,
        "is_enabled": provider.is_enabled,
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


@sso_router.put("/admin/providers/{provider_id}", response_model=Dict)
@require_permission("admin.sso_providers:update")
async def update_sso_provider(
    provider_id: str,
    provider_data: SSOProviderUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict:
    """Update SSO provider configuration (Admin only).

    Args:
        provider_id: Provider identifier
        provider_data: Updated provider configuration
        db: Database session
        user: Current authenticated user

    Returns:
        Updated provider information.

    Raises:
        HTTPException: If provider not found or update fails
    """
    sso_service = SSOService(db)

    # Filter out None values
    update_data = {k: v for k, v in provider_data.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    provider = sso_service.update_provider(provider_id, update_data)
    if not provider:
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider_id}' not found")

    return {
        "id": provider.id,
        "name": provider.name,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "is_enabled": provider.is_enabled,
        "updated_at": provider.updated_at,
    }


@sso_router.delete("/admin/providers/{provider_id}")
@require_permission("admin.sso_providers:delete")
async def delete_sso_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict:
    """Delete SSO provider configuration (Admin only).

    Args:
        provider_id: Provider identifier
        db: Database session
        user: Current authenticated user

    Returns:
        Deletion confirmation.

    Raises:
        HTTPException: If provider not found
    """
    sso_service = SSOService(db)

    if not sso_service.delete_provider(provider_id):
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider_id}' not found")

    return {"message": f"SSO provider '{provider_id}' deleted successfully"}


# ---------------------------------------------------------------------------
# SSO User Approval Management Endpoints
# ---------------------------------------------------------------------------


class PendingUserApprovalResponse(BaseModel):
    """Response model for pending user approval."""

    id: str
    email: str
    full_name: str
    auth_provider: str
    requested_at: str
    expires_at: str
    status: str
    sso_metadata: Optional[Dict] = None


class ApprovalActionRequest(BaseModel):
    """Request model for approval actions."""

    action: str  # "approve" or "reject"
    reason: Optional[str] = None  # Required for rejection
    notes: Optional[str] = None


@sso_router.get("/pending-approvals", response_model=List[PendingUserApprovalResponse])
@require_permission("admin.user_management")
async def list_pending_approvals(
    include_expired: bool = Query(False, description="Include expired approval requests"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> List[PendingUserApprovalResponse]:
    """List pending SSO user approval requests (Admin only).

    Args:
        include_expired: Whether to include expired requests
        db: Database session
        user: Current authenticated admin user

    Returns:
        List of pending approval requests
    """
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import PendingUserApproval

    query = select(PendingUserApproval)

    if not include_expired:
        # First-Party
        from mcpgateway.db import utc_now

        query = query.where(PendingUserApproval.expires_at > utc_now())

    # Filter by status
    query = query.where(PendingUserApproval.status == "pending")
    query = query.order_by(PendingUserApproval.requested_at.desc())

    result = db.execute(query)
    pending_approvals = result.scalars().all()

    return [
        PendingUserApprovalResponse(
            id=approval.id,
            email=approval.email,
            full_name=approval.full_name,
            auth_provider=approval.auth_provider,
            requested_at=approval.requested_at.isoformat(),
            expires_at=approval.expires_at.isoformat(),
            status=approval.status,
            sso_metadata=approval.sso_metadata,
        )
        for approval in pending_approvals
    ]


@sso_router.post("/pending-approvals/{approval_id}/action")
@require_permission("admin.user_management")
async def handle_approval_request(
    approval_id: str,
    request: ApprovalActionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict:
    """Approve or reject a pending SSO user registration (Admin only).

    Args:
        approval_id: ID of the approval request
        request: Approval action (approve/reject) with optional reason/notes
        db: Database session
        user: Current authenticated admin user

    Returns:
        Action confirmation message

    Raises:
        HTTPException: If approval not found or invalid action
    """
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import PendingUserApproval

    # Get pending approval
    approval = db.execute(select(PendingUserApproval).where(PendingUserApproval.id == approval_id)).scalar_one_or_none()

    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if approval.status != "pending":
        raise HTTPException(status_code=400, detail=f"Approval request is already {approval.status}")

    if approval.is_expired():
        approval.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Approval request has expired")

    admin_email = user["email"]

    if request.action == "approve":
        approval.approve(admin_email, request.notes)
        db.commit()
        return {"message": f"User {approval.email} approved successfully"}

    elif request.action == "reject":
        if not request.reason:
            raise HTTPException(status_code=400, detail="Rejection reason is required")
        approval.reject(admin_email, request.reason, request.notes)
        db.commit()
        return {"message": f"User {approval.email} rejected"}

    else:
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'approve' or 'reject'")
