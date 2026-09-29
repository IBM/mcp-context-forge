# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/users.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Authenticated user-scoped API routes.
"""

# Standard
from typing import Any, List

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import get_user_email
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import TeamInvitationResponse
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.team_invitation_service import TeamInvitationService

logger = LoggingService().get_logger(__name__)
users_router = APIRouter()


@users_router.get("/me/invitations", response_model=List[TeamInvitationResponse])
@require_permission("teams.join")
async def list_my_team_invitations(current_user: dict[str, Any] = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> List[TeamInvitationResponse]:
    """List active, unexpired team invitations addressed to the caller.

    Args:
        current_user: Authenticated user context
        db: Database session

    Returns:
        List[TeamInvitationResponse]: Pending invitations for the caller

    Raises:
        HTTPException: If invitations cannot be loaded
    """
    user_email = get_user_email(current_user)
    try:
        invitations = await TeamInvitationService(db).get_user_invitations(user_email)
        return [
            TeamInvitationResponse(
                id=invitation.id,
                team_id=invitation.team_id,
                team_name=invitation.team.name if invitation.team else "Unknown Team",
                email=invitation.email,
                role=invitation.role,
                invited_by=invitation.invited_by,
                invited_at=invitation.invited_at,
                expires_at=invitation.expires_at,
                token=invitation.token,
                is_active=invitation.is_active,
                is_expired=invitation.is_expired(),
            )
            for invitation in invitations
        ]
    except Exception as error:
        logger.error("Failed to list invitations for user %s: %s", SecurityValidator.sanitize_log_message(user_email), error)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list invitations") from error
