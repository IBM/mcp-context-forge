# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_users.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for authenticated user-scoped routes.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import FastAPI, HTTPException, status
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, EmailTeamInvitation
from mcpgateway.routers import users
from mcpgateway.services.team_invitation_service import TeamInvitationService


@pytest.fixture
def mock_db():
    """Return a mocked database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def invitation():
    """Return a pending invitation with its team eagerly available."""
    team = MagicMock(spec=EmailTeam)
    team.name = "Platform Engineering"

    pending = MagicMock(spec=EmailTeamInvitation)
    pending.id = "invitation-1"
    pending.team_id = "team-1"
    pending.team = team
    pending.email = "invitee@example.com"
    pending.role = "member"
    pending.invited_by = "owner@example.com"
    pending.invited_at = datetime.now(timezone.utc)
    pending.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    pending.token = "invitation-token"
    pending.is_active = True
    pending.is_expired = MagicMock(return_value=False)
    return pending


def _handler():
    """Return route handler without RBAC decorator for behavior unit tests."""
    return getattr(users.list_my_team_invitations, "__wrapped__", users.list_my_team_invitations)


@pytest.mark.asyncio
async def test_list_my_invitations_uses_authenticated_email(mock_db, invitation):
    """Caller identity selects invitations and response contains display fields."""
    with patch("mcpgateway.routers.users.TeamInvitationService") as MockService:
        service = AsyncMock(spec=TeamInvitationService)
        service.get_user_invitations = AsyncMock(return_value=[invitation])
        MockService.return_value = service

        result = await _handler()(current_user={"email": "invitee@example.com"}, db=mock_db)

    service.get_user_invitations.assert_awaited_once_with("invitee@example.com")
    assert len(result) == 1
    assert result[0].team_name == "Platform Engineering"
    assert result[0].invited_by == "owner@example.com"
    assert result[0].token == "invitation-token"
    assert result[0].is_expired is False


@pytest.mark.asyncio
async def test_list_my_invitations_stays_available_when_creation_disabled(mock_db):
    """Disabling new invitations does not hide pending invitations."""
    with patch.object(settings, "allow_team_invitations", False), patch("mcpgateway.routers.users.TeamInvitationService") as MockService:
        service = AsyncMock(spec=TeamInvitationService)
        service.get_user_invitations = AsyncMock(return_value=[])
        MockService.return_value = service

        result = await _handler()(current_user={"email": "invitee@example.com"}, db=mock_db)

    assert result == []
    service.get_user_invitations.assert_awaited_once_with("invitee@example.com")


@pytest.mark.asyncio
async def test_list_my_invitations_database_failure_returns_500(mock_db):
    """Database failures are not reported as an empty inbox."""
    with patch("mcpgateway.routers.users.TeamInvitationService") as MockService:
        service = AsyncMock(spec=TeamInvitationService)
        service.get_user_invitations = AsyncMock(side_effect=RuntimeError("database unavailable"))
        MockService.return_value = service

        with pytest.raises(HTTPException) as exc_info:
            await _handler()(current_user={"email": "invitee@example.com"}, db=mock_db)

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to list invitations"


@pytest.mark.asyncio
async def test_list_my_invitations_requires_authentication(mock_db):
    """RBAC wrapper rejects missing authenticated identity."""
    with pytest.raises(HTTPException) as exc_info:
        await users.list_my_team_invitations(current_user=None, db=mock_db)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_list_my_invitations_requires_teams_join_scope(mock_db):
    """Scoped API tokens without teams.join are rejected."""
    current_user = {"email": "invitee@example.com", "token_scopes": ["teams.read"]}

    with pytest.raises(HTTPException) as exc_info:
        await users.list_my_team_invitations(current_user=current_user, db=mock_db)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_users_router_openapi_contract():
    """OpenAPI publishes caller inbox response under canonical versioned path."""
    app = FastAPI()
    app.include_router(users.users_router, prefix="/v1/users")

    operation = app.openapi()["paths"]["/v1/users/me/invitations"]["get"]

    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["type"] == "array"
    assert response_schema["items"]["$ref"] == "#/components/schemas/TeamInvitationResponse"
