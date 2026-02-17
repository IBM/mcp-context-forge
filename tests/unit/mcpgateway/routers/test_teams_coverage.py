# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.routers.teams — error branches, edge cases."""

# Standard
import importlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# Third-Party
import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session


# Patch RBAC decorators before importing teams module
def _noop_decorator(permission: str, resource_type=None):
    def decorator(func):
        return func

    return decorator


with patch("mcpgateway.middleware.rbac.require_permission", _noop_decorator):
    with patch("mcpgateway.middleware.rbac.require_admin_permission", lambda: (lambda f: f)):
        from mcpgateway.db import EmailTeam, EmailTeamInvitation, EmailTeamMember, EmailUser
        from mcpgateway.routers import teams
        from mcpgateway.services.team_invitation_service import TeamInvitationService
        from mcpgateway.services.team_management_service import TeamManagementService

        importlib.reload(teams)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    return MagicMock(spec=Session)


@pytest.fixture
def user_ctx(db):
    return {
        "email": "user@test.com",
        "full_name": "User",
        "is_admin": False,
        "db": db,
        "permissions": ["admin.*", "a2a.*", "tools.*", "servers.*", "resources.*", "prompts.*", "gateways.*", "teams.*", "tags.*", "tokens.*"],
    }


@pytest.fixture
def admin_ctx(db):
    return {
        "email": "admin@test.com",
        "full_name": "Admin",
        "is_admin": True,
        "db": db,
        "permissions": ["admin.*", "a2a.*", "tools.*", "servers.*", "resources.*", "prompts.*", "gateways.*", "teams.*", "tags.*", "tokens.*"],
    }


@pytest.fixture
def mock_team():
    t = MagicMock(spec=EmailTeam)
    t.id = str(uuid4())
    t.name = "Team"
    t.slug = "team"
    t.description = "desc"
    t.created_by = "user@test.com"
    t.is_personal = False
    t.visibility = "private"
    t.max_members = 100
    t.created_at = datetime.now(timezone.utc)
    t.updated_at = datetime.now(timezone.utc)
    t.is_active = True
    t.get_member_count = MagicMock(return_value=1)
    return t


@pytest.fixture
def mock_member():
    m = MagicMock(spec=EmailTeamMember)
    m.id = str(uuid4())
    m.team_id = str(uuid4())
    m.user_email = "member@test.com"
    m.role = "member"
    m.joined_at = datetime.now(timezone.utc)
    m.invited_by = "owner@test.com"
    m.is_active = True
    return m


@pytest.fixture
def mock_invitation():
    inv = MagicMock(spec=EmailTeamInvitation)
    inv.id = str(uuid4())
    inv.team_id = str(uuid4())
    inv.email = "invited@test.com"
    inv.role = "member"
    inv.invited_by = "owner@test.com"
    inv.invited_at = datetime.now(timezone.utc)
    inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    inv.token = "tok-123"
    inv.is_active = True
    inv.is_expired = MagicMock(return_value=False)
    return inv


def _svc(**methods):
    """Build a patched TeamManagementService context manager."""
    svc = AsyncMock(spec=TeamManagementService)
    for k, v in methods.items():
        setattr(svc, k, v)
    return patch("mcpgateway.routers.teams.TeamManagementService", return_value=svc)


def _inv_svc(**methods):
    """Build a patched TeamInvitationService context manager."""
    svc = AsyncMock(spec=TeamInvitationService)
    for k, v in methods.items():
        setattr(svc, k, v)
    return patch("mcpgateway.routers.teams.TeamInvitationService", return_value=svc)


# ===========================================================================
# discover_public_teams — error branch
# ===========================================================================


class TestDiscoverPublicTeamsErrors:
    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(discover_public_teams=AsyncMock(side_effect=Exception("db"))):
            with pytest.raises(HTTPException) as exc:
                await teams.discover_public_teams(0, 50, current_user_ctx=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# update_team — missing branches
# ===========================================================================


class TestUpdateTeamErrors:
    @pytest.mark.asyncio
    async def test_team_not_found_after_update(self, user_ctx, db, mock_team):
        with _svc(
            get_user_role_in_team=AsyncMock(return_value="owner"),
            update_team=AsyncMock(return_value=True),
            get_team_by_id=AsyncMock(return_value=None),
        ):
            from mcpgateway.schemas import TeamUpdateRequest

            req = TeamUpdateRequest(name="X", description="Y")
            with pytest.raises(HTTPException) as exc:
                await teams.update_team(mock_team.id, req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND
            assert "not found after update" in exc.value.detail

    @pytest.mark.asyncio
    async def test_value_error(self, user_ctx, db):
        with _svc(
            get_user_role_in_team=AsyncMock(return_value="owner"),
            update_team=AsyncMock(side_effect=ValueError("bad name")),
        ):
            from mcpgateway.schemas import TeamUpdateRequest

            req = TeamUpdateRequest(name="X")
            with pytest.raises(HTTPException) as exc:
                await teams.update_team("tid", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "bad name" in exc.value.detail

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, user_ctx, db):
        with _svc(
            get_user_role_in_team=AsyncMock(side_effect=RuntimeError("crash")),
        ):
            from mcpgateway.schemas import TeamUpdateRequest

            req = TeamUpdateRequest(name="X")
            with pytest.raises(HTTPException) as exc:
                await teams.update_team("tid", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# delete_team — exception branch
# ===========================================================================


class TestDeleteTeamErrors:
    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_user_role_in_team=AsyncMock(side_effect=Exception("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.delete_team("tid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# list_team_members — cursor pagination, include_pagination, exception
# ===========================================================================


class TestListTeamMembersEdge:
    @pytest.mark.asyncio
    async def test_cursor_pagination(self, user_ctx, db, mock_member):
        mock_user = MagicMock(spec=EmailUser)
        members = [(mock_user, mock_member)]
        with _svc(
            get_user_role_in_team=AsyncMock(return_value="member"),
            get_team_members=AsyncMock(return_value=(members, "next-cursor")),
        ):
            result = await teams.list_team_members("tid", cursor="abc", limit=10, include_pagination=False, current_user=user_ctx, db=db)
            assert isinstance(result, list)
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_include_pagination(self, user_ctx, db, mock_member):
        mock_user = MagicMock(spec=EmailUser)
        members = [(mock_user, mock_member)]
        with _svc(
            get_user_role_in_team=AsyncMock(return_value="member"),
            get_team_members=AsyncMock(return_value=(members, "nc")),
        ):
            result = await teams.list_team_members("tid", cursor="abc", limit=10, include_pagination=True, current_user=user_ctx, db=db)
            assert hasattr(result, "members")
            assert result.next_cursor == "nc"

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_user_role_in_team=AsyncMock(side_effect=Exception("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.list_team_members("tid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# update_team_member — all missing branches
# ===========================================================================


class TestUpdateTeamMemberErrors:
    @pytest.mark.asyncio
    async def test_not_owner(self, user_ctx, db):
        with _svc(get_user_role_in_team=AsyncMock(return_value="member")):
            from mcpgateway.schemas import TeamMemberUpdateRequest

            req = TeamMemberUpdateRequest(role="owner")
            with pytest.raises(HTTPException) as exc:
                await teams.update_team_member("tid", "u@t.com", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_update_failed(self, user_ctx, db):
        with _svc(
            get_user_role_in_team=AsyncMock(return_value="owner"),
            update_member_role=AsyncMock(return_value=False),
        ):
            from mcpgateway.schemas import TeamMemberUpdateRequest

            req = TeamMemberUpdateRequest(role="owner")
            with pytest.raises(HTTPException) as exc:
                await teams.update_team_member("tid", "u@t.com", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_member_not_found_after_update(self, user_ctx, db):
        with _svc(
            get_user_role_in_team=AsyncMock(return_value="owner"),
            update_member_role=AsyncMock(return_value=True),
            get_member=AsyncMock(return_value=None),
        ):
            from mcpgateway.schemas import TeamMemberUpdateRequest

            req = TeamMemberUpdateRequest(role="owner")
            with pytest.raises(HTTPException) as exc:
                await teams.update_team_member("tid", "u@t.com", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND
            assert "after update" in exc.value.detail

    @pytest.mark.asyncio
    async def test_value_error(self, user_ctx, db):
        with _svc(
            get_user_role_in_team=AsyncMock(return_value="owner"),
            update_member_role=AsyncMock(side_effect=ValueError("bad role")),
        ):
            from mcpgateway.schemas import TeamMemberUpdateRequest

            req = TeamMemberUpdateRequest(role="member")
            with pytest.raises(HTTPException) as exc:
                await teams.update_team_member("tid", "u@t.com", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_user_role_in_team=AsyncMock(side_effect=RuntimeError("crash"))):
            from mcpgateway.schemas import TeamMemberUpdateRequest

            req = TeamMemberUpdateRequest(role="member")
            with pytest.raises(HTTPException) as exc:
                await teams.update_team_member("tid", "u@t.com", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# remove_team_member — missing branches
# ===========================================================================


class TestRemoveTeamMemberErrors:
    @pytest.mark.asyncio
    async def test_member_not_found(self, user_ctx, db):
        with _svc(
            get_user_role_in_team=AsyncMock(return_value="owner"),
            remove_member_from_team=AsyncMock(return_value=False),
        ):
            with pytest.raises(HTTPException) as exc:
                await teams.remove_team_member("tid", "other@t.com", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_user_role_in_team=AsyncMock(side_effect=RuntimeError("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.remove_team_member("tid", "other@t.com", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# invite_team_member — missing branches
# ===========================================================================


class TestInviteTeamMemberErrors:
    @pytest.mark.asyncio
    async def test_invitation_creation_failed(self, user_ctx, db):
        with (
            _svc(get_user_role_in_team=AsyncMock(return_value="owner")),
            _inv_svc(
                create_invitation=AsyncMock(return_value=None),
            ),
        ):
            from mcpgateway.schemas import TeamInviteRequest

            req = TeamInviteRequest(email="x@t.com", role="member")
            with pytest.raises(HTTPException) as exc:
                await teams.invite_team_member("tid", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.asyncio
    async def test_value_error(self, user_ctx, db):
        with (
            _svc(get_user_role_in_team=AsyncMock(return_value="owner")),
            _inv_svc(
                create_invitation=AsyncMock(side_effect=ValueError("dup")),
            ),
        ):
            from mcpgateway.schemas import TeamInviteRequest

            req = TeamInviteRequest(email="x@t.com", role="member")
            with pytest.raises(HTTPException) as exc:
                await teams.invite_team_member("tid", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_user_role_in_team=AsyncMock(side_effect=RuntimeError("crash"))):
            from mcpgateway.schemas import TeamInviteRequest

            req = TeamInviteRequest(email="x@t.com", role="member")
            with pytest.raises(HTTPException) as exc:
                await teams.invite_team_member("tid", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# list_team_invitations — missing branches
# ===========================================================================


class TestListTeamInvitationsErrors:
    @pytest.mark.asyncio
    async def test_not_owner(self, user_ctx, db):
        with _svc(get_user_role_in_team=AsyncMock(return_value="member")):
            with pytest.raises(HTTPException) as exc:
                await teams.list_team_invitations("tid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_user_role_in_team=AsyncMock(side_effect=RuntimeError("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.list_team_invitations("tid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# accept_team_invitation — missing branches
# ===========================================================================


class TestAcceptTeamInvitationErrors:
    @pytest.mark.asyncio
    async def test_value_error(self, user_ctx, db):
        with _inv_svc(accept_invitation=AsyncMock(side_effect=ValueError("expired"))):
            with pytest.raises(HTTPException) as exc:
                await teams.accept_team_invitation("tok", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _inv_svc(accept_invitation=AsyncMock(side_effect=RuntimeError("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.accept_team_invitation("tok", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# cancel_team_invitation — missing branches
# ===========================================================================


class TestCancelTeamInvitationErrors:
    @pytest.mark.asyncio
    async def test_invitation_not_found(self, user_ctx, db):
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_filter)
        mock_filter.first = MagicMock(return_value=None)
        db.query = MagicMock(return_value=mock_query)

        with pytest.raises(HTTPException) as exc:
            await teams.cancel_team_invitation("inv-id", current_user=user_ctx, db=db)
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_not_owner_not_inviter(self, user_ctx, db, mock_invitation):
        mock_invitation.invited_by = "someone_else@test.com"
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_filter)
        mock_filter.first = MagicMock(return_value=mock_invitation)
        db.query = MagicMock(return_value=mock_query)

        with _svc(get_user_role_in_team=AsyncMock(return_value="member")):
            with pytest.raises(HTTPException) as exc:
                await teams.cancel_team_invitation(mock_invitation.id, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_revoke_failed(self, user_ctx, db, mock_invitation):
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_filter)
        mock_filter.first = MagicMock(return_value=mock_invitation)
        db.query = MagicMock(return_value=mock_query)

        with (
            _svc(get_user_role_in_team=AsyncMock(return_value="owner")),
            _inv_svc(
                revoke_invitation=AsyncMock(return_value=False),
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await teams.cancel_team_invitation(mock_invitation.id, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        db.query = MagicMock(side_effect=RuntimeError("crash"))

        with pytest.raises(HTTPException) as exc:
            await teams.cancel_team_invitation("inv-id", current_user=user_ctx, db=db)
        assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# request_to_join_team — missing branches
# ===========================================================================


class TestRequestToJoinTeamErrors:
    @pytest.mark.asyncio
    async def test_team_not_found(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(return_value=None)):
            from mcpgateway.schemas import TeamJoinRequest

            req = TeamJoinRequest(message="hi")
            with pytest.raises(HTTPException) as exc:
                await teams.request_to_join_team("tid", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(side_effect=RuntimeError("crash"))):
            from mcpgateway.schemas import TeamJoinRequest

            req = TeamJoinRequest(message="hi")
            with pytest.raises(HTTPException) as exc:
                await teams.request_to_join_team("tid", req, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# leave_team — missing branches
# ===========================================================================


class TestLeaveTeamErrors:
    @pytest.mark.asyncio
    async def test_team_not_found(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await teams.leave_team("tid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_not_a_member(self, user_ctx, db, mock_team):
        with _svc(
            get_team_by_id=AsyncMock(return_value=mock_team),
            get_user_role_in_team=AsyncMock(return_value=None),
        ):
            with pytest.raises(HTTPException) as exc:
                await teams.leave_team(mock_team.id, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "not a member" in exc.value.detail

    @pytest.mark.asyncio
    async def test_remove_failed_last_owner(self, user_ctx, db, mock_team):
        with _svc(
            get_team_by_id=AsyncMock(return_value=mock_team),
            get_user_role_in_team=AsyncMock(return_value="owner"),
            remove_member_from_team=AsyncMock(return_value=False),
        ):
            with pytest.raises(HTTPException) as exc:
                await teams.leave_team(mock_team.id, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "last owner" in exc.value.detail

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(side_effect=RuntimeError("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.leave_team("tid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# list_team_join_requests — missing branches
# ===========================================================================


class TestListTeamJoinRequestsErrors:
    @pytest.mark.asyncio
    async def test_team_not_found(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await teams.list_team_join_requests("tid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_not_owner(self, user_ctx, db, mock_team):
        with _svc(
            get_team_by_id=AsyncMock(return_value=mock_team),
            get_user_role_in_team=AsyncMock(return_value="member"),
        ):
            with pytest.raises(HTTPException) as exc:
                await teams.list_team_join_requests(mock_team.id, current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(side_effect=RuntimeError("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.list_team_join_requests("tid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# approve_join_request — missing branches
# ===========================================================================


class TestApproveJoinRequestErrors:
    @pytest.mark.asyncio
    async def test_team_not_found(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await teams.approve_join_request("tid", "rid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_not_owner(self, user_ctx, db, mock_team):
        with _svc(
            get_team_by_id=AsyncMock(return_value=mock_team),
            get_user_role_in_team=AsyncMock(return_value="member"),
        ):
            with pytest.raises(HTTPException) as exc:
                await teams.approve_join_request(mock_team.id, "rid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_member_none(self, user_ctx, db, mock_team):
        with _svc(
            get_team_by_id=AsyncMock(return_value=mock_team),
            get_user_role_in_team=AsyncMock(return_value="owner"),
            approve_join_request=AsyncMock(return_value=None),
        ):
            with pytest.raises(HTTPException) as exc:
                await teams.approve_join_request(mock_team.id, "rid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(side_effect=RuntimeError("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.approve_join_request("tid", "rid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ===========================================================================
# reject_join_request — missing branches
# ===========================================================================


class TestRejectJoinRequestErrors:
    @pytest.mark.asyncio
    async def test_team_not_found(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await teams.reject_join_request("tid", "rid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_request_not_found(self, user_ctx, db, mock_team):
        with _svc(
            get_team_by_id=AsyncMock(return_value=mock_team),
            get_user_role_in_team=AsyncMock(return_value="owner"),
            reject_join_request=AsyncMock(return_value=False),
        ):
            with pytest.raises(HTTPException) as exc:
                await teams.reject_join_request(mock_team.id, "rid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_exception(self, user_ctx, db):
        with _svc(get_team_by_id=AsyncMock(side_effect=RuntimeError("crash"))):
            with pytest.raises(HTTPException) as exc:
                await teams.reject_join_request("tid", "rid", current_user=user_ctx, db=db)
            assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
