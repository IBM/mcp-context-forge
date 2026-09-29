# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_team_invitation_security.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Security tests for decorated invitee invitation routes.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.middleware import rbac
from mcpgateway.routers import teams
from mcpgateway.services.team_invitation_service import InvitationEmailMismatchError, TeamInvitationService


@pytest.fixture
def mock_db():
    """Return a mocked database session."""
    return MagicMock(spec=Session)


def _decorated_decline_handler():
    """Bind the production RBAC decorator regardless of router import order."""
    handler = getattr(teams.decline_team_invitation, "__wrapped__", teams.decline_team_invitation)
    return rbac.require_permission("teams.join")(handler)


def _client(current_user, mock_db):
    """Expose the decorated production handler through an isolated ASGI app."""
    app = FastAPI()
    app.dependency_overrides[teams.get_current_user_with_permissions] = lambda: current_user
    app.dependency_overrides[teams.get_db] = lambda: mock_db
    app.post("/v1/teams/invitations/{token}/decline")(_decorated_decline_handler())
    return TestClient(app, raise_server_exceptions=False)


def test_decline_invitation_requires_authentication(mock_db):
    """Reject an unauthenticated HTTP request before service access."""
    with patch("mcpgateway.routers.teams.TeamInvitationService") as MockService:
        response = _client(None, mock_db).post("/v1/teams/invitations/invitation-token/decline")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "User authentication required"}
    MockService.assert_not_called()


def test_decline_invitation_requires_teams_join_scope(mock_db):
    """Reject an HTTP request scoped without teams.join before service access."""
    current_user = {"email": "invitee@example.com", "token_scopes": ["teams.read"]}

    with patch("mcpgateway.routers.teams.TeamInvitationService") as MockService:
        response = _client(current_user, mock_db).post("/v1/teams/invitations/invitation-token/decline")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Access denied"}
    MockService.assert_not_called()


def test_decline_invitation_rejects_wrong_owner(mock_db):
    """Map a wrong-owner decline to 403 through the HTTP route."""
    current_user = {"email": "wrong@example.com", "token_scopes": ["teams.join"]}

    with patch("mcpgateway.routers.teams.TeamInvitationService") as MockService:
        service = AsyncMock(spec=TeamInvitationService)
        service.decline_invitation = AsyncMock(side_effect=InvitationEmailMismatchError("wrong user"))
        MockService.return_value = service

        response = _client(current_user, mock_db).post("/v1/teams/invitations/invitation-token/decline")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Access denied"}
    service.decline_invitation.assert_awaited_once_with("invitation-token", "wrong@example.com")


def test_decline_invitation_stays_available_when_creation_disabled(mock_db):
    """Allow HTTP decline while creation feature flag is disabled."""
    current_user = {"email": "invitee@example.com", "token_scopes": ["teams.join"]}

    with patch.object(teams.settings, "allow_team_invitations", False), patch("mcpgateway.routers.teams.TeamInvitationService") as MockService:
        service = AsyncMock(spec=TeamInvitationService)
        service.decline_invitation = AsyncMock(return_value=True)
        MockService.return_value = service

        response = _client(current_user, mock_db).post("/v1/teams/invitations/invitation-token/decline")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"success": True, "message": "Team invitation declined successfully"}
    service.decline_invitation.assert_awaited_once_with("invitation-token", "invitee@example.com")
