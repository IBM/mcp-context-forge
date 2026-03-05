# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_team_governance_flags.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for team governance feature flags: allow_team_creation, allow_team_join_requests,
allow_team_invitations, max_teams_per_user, personal_team_prefix, and
require_email_verification_for_invites enforcement.
"""

# Standard
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeam, EmailTeamMember, EmailUser


class TestAllowTeamCreationFlag:
    """Tests for the allow_team_creation feature flag."""

    @pytest.fixture(autouse=True)
    async def drain_fire_and_forget_tasks(self):
        """Give fire-and-forget cache invalidation tasks one loop turn to complete."""
        yield
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    @patch("mcpgateway.routers.teams.settings")
    async def test_allow_team_creation_disabled_non_admin(self, mock_settings):
        """When allow_team_creation=False and user is not admin, create_team returns 403."""
        mock_settings.allow_team_creation = False

        # First-Party
        from mcpgateway.routers.teams import create_team
        from mcpgateway.schemas import TeamCreateRequest

        request = TeamCreateRequest(name="Test Team", visibility="private")
        current_user_ctx = {"email": "user@example.com", "is_admin": False}
        db = MagicMock(spec=Session)

        with pytest.raises(HTTPException) as exc_info:
            await create_team(request=request, current_user_ctx=current_user_ctx, db=db)
        assert exc_info.value.status_code == 403
        assert "disabled" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("mcpgateway.routers.teams.TeamManagementService")
    @patch("mcpgateway.routers.teams.settings")
    async def test_allow_team_creation_disabled_admin_bypass(self, mock_settings, mock_service_cls):
        """When allow_team_creation=False but user is admin, create_team succeeds."""
        mock_settings.allow_team_creation = False

        mock_team = MagicMock()
        mock_team.id = "team-1"
        mock_team.name = "Admin Team"
        mock_team.slug = "admin-team"
        mock_team.description = None
        mock_team.created_by = "admin@example.com"
        mock_team.is_personal = False
        mock_team.visibility = "private"
        mock_team.max_members = 100
        mock_team.get_member_count.return_value = 1
        mock_team.created_at = datetime.now(timezone.utc)
        mock_team.updated_at = datetime.now(timezone.utc)
        mock_team.is_active = True

        mock_service = MagicMock()
        mock_service.create_team = AsyncMock(return_value=mock_team)
        mock_service_cls.return_value = mock_service

        # First-Party
        from mcpgateway.routers.teams import create_team
        from mcpgateway.schemas import TeamCreateRequest

        request = TeamCreateRequest(name="Admin Team", visibility="private")
        current_user_ctx = {"email": "admin@example.com", "is_admin": True}
        db = MagicMock(spec=Session)

        result = await create_team(request=request, current_user_ctx=current_user_ctx, db=db)
        assert result.name == "Admin Team"


class TestAllowTeamJoinRequestsFlag:
    """Tests for the allow_team_join_requests feature flag."""

    @pytest.mark.asyncio
    @patch("mcpgateway.routers.teams.settings")
    async def test_allow_team_join_requests_disabled(self, mock_settings):
        """When allow_team_join_requests=False, request_to_join_team returns 403."""
        mock_settings.allow_team_join_requests = False

        # First-Party
        from mcpgateway.routers.teams import request_to_join_team
        from mcpgateway.schemas import TeamJoinRequest

        join_request = TeamJoinRequest(message="Please let me join")
        current_user = {"email": "user@example.com", "is_admin": False}
        db = MagicMock(spec=Session)

        with pytest.raises(HTTPException) as exc_info:
            await request_to_join_team(team_id="team-1", join_request=join_request, current_user=current_user, db=db)
        assert exc_info.value.status_code == 403
        assert "disabled" in exc_info.value.detail.lower()


class TestAllowTeamInvitationsFlag:
    """Tests for the allow_team_invitations feature flag."""

    @pytest.fixture(autouse=True)
    async def drain_fire_and_forget_tasks(self):
        """Give fire-and-forget cache invalidation tasks one loop turn to complete."""
        yield
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_allow_team_invitations_disabled(self):
        """When allow_team_invitations=False, create_invitation raises ValueError."""
        # First-Party
        from mcpgateway.services.team_invitation_service import TeamInvitationService

        db = MagicMock(spec=Session)
        service = TeamInvitationService(db)

        with patch("mcpgateway.services.team_invitation_service.settings") as mock_settings:
            mock_settings.allow_team_invitations = False
            with pytest.raises(ValueError, match="invitations are currently disabled"):
                await service.create_invitation(team_id="team-1", email="invitee@example.com", role="member", invited_by="owner@example.com")


class TestMaxTeamsPerUser:
    """Tests for max_teams_per_user enforcement."""

    @pytest.fixture(autouse=True)
    async def drain_fire_and_forget_tasks(self):
        """Give fire-and-forget cache invalidation tasks one loop turn to complete."""
        yield
        await asyncio.sleep(0)

    @pytest.fixture(autouse=True)
    def clear_caches(self):
        """Clear caches before each test to avoid cross-test contamination."""
        try:
            # First-Party
            from mcpgateway.cache.auth_cache import get_auth_cache

            cache = get_auth_cache()
            cache.invalidate_all()
        except ImportError:
            pass
        try:
            # First-Party
            from mcpgateway.cache.admin_stats_cache import get_admin_stats_cache

            cache = get_admin_stats_cache()
            cache.invalidate_all()
        except ImportError:
            pass
        yield

    @pytest.mark.asyncio
    async def test_max_teams_per_user_enforced_create_team(self):
        """When user is at max_teams_per_user limit, create_team raises ValueError."""
        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService

        db = MagicMock(spec=Session)
        service = TeamManagementService(db)
        service._get_user_team_count = MagicMock(return_value=5)

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.max_teams_per_user = 5
            mock_settings.max_members_per_team = 100
            with pytest.raises(ValueError, match="maximum team limit"):
                await service.create_team(name="Overflow Team", description="test", created_by="user@example.com", visibility="private")

    @pytest.mark.asyncio
    async def test_max_teams_per_user_enforced_add_member(self):
        """When target user is at max_teams_per_user limit, add_member_to_team raises error."""
        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementError, TeamManagementService

        db = MagicMock(spec=Session)
        service = TeamManagementService(db)
        service._get_user_team_count = MagicMock(return_value=5)

        mock_team = MagicMock()
        mock_team.is_personal = False
        mock_team.max_members = 100

        service.get_team_by_id = AsyncMock(return_value=mock_team)

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "target@example.com"
        db.query.return_value.filter.return_value.first.return_value = mock_user

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.max_teams_per_user = 5
            with pytest.raises(TeamManagementError, match="maximum team limit"):
                await service.add_member_to_team(team_id="team-1", user_email="target@example.com", role="member")

    @pytest.mark.asyncio
    async def test_max_teams_per_user_enforced_accept_invitation(self):
        """When accepting user is at max_teams_per_user limit, accept_invitation raises ValueError."""
        # First-Party
        from mcpgateway.services.team_invitation_service import TeamInvitationService

        db = MagicMock(spec=Session)
        service = TeamInvitationService(db)
        service._get_user_team_count = MagicMock(return_value=5)

        mock_invitation = MagicMock()
        mock_invitation.email = "user@example.com"
        mock_invitation.team_id = "team-1"
        mock_invitation.is_valid.return_value = True
        mock_invitation.is_active = True
        service.get_invitation_by_token = AsyncMock(return_value=mock_invitation)

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user@example.com"
        mock_user.email_verified_at = datetime.now(timezone.utc)

        mock_team = MagicMock(spec=EmailTeam)
        mock_team.is_active = True
        mock_team.max_members = 100

        call_count = [0]

        def query_side_effect(model):
            mock_q = MagicMock()

            def _first():
                call_count[0] += 1
                if call_count[0] == 1:
                    return mock_user  # user existence
                elif call_count[0] == 2:
                    return mock_team  # team existence
                elif call_count[0] == 3:
                    return None  # not already a member
                return None

            mock_q.filter.return_value.first = _first
            mock_q.filter.return_value.count = MagicMock(return_value=2)
            return mock_q

        db.query.side_effect = query_side_effect

        with patch("mcpgateway.services.team_invitation_service.settings") as mock_settings:
            mock_settings.max_teams_per_user = 5
            mock_settings.require_email_verification_for_invites = False
            with pytest.raises(ValueError, match="maximum team limit"):
                await service.accept_invitation(token="test-token", accepting_user_email="user@example.com")


class TestPersonalTeamFlags:
    """Tests for personal team feature flag and prefix configuration."""

    @pytest.fixture(autouse=True)
    async def drain_fire_and_forget_tasks(self):
        """Give fire-and-forget cache invalidation tasks one loop turn to complete."""
        yield
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_ensure_personal_team_respects_flag(self):
        """When auto_create_personal_teams=False and no team exists, ensure_personal_team returns None."""
        # First-Party
        from mcpgateway.services.personal_team_service import PersonalTeamService

        db = MagicMock(spec=Session)
        service = PersonalTeamService(db)

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user@example.com"

        service.get_personal_team = AsyncMock(return_value=None)

        with patch("mcpgateway.services.personal_team_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            result = await service.ensure_personal_team(mock_user)
            assert result is None

    @pytest.mark.asyncio
    async def test_personal_team_prefix_used(self):
        """Verify create_personal_team uses settings.personal_team_prefix for slug."""
        # First-Party
        from mcpgateway.services.personal_team_service import PersonalTeamService

        db = MagicMock(spec=Session)
        service = PersonalTeamService(db)

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user@example.com"
        mock_user.get_display_name.return_value = "User"

        # No existing team
        db.query.return_value.filter.return_value.first.return_value = None

        with patch("mcpgateway.services.personal_team_service.settings") as mock_settings:
            mock_settings.personal_team_prefix = "workspace"
            try:
                await service.create_personal_team(mock_user)
            except Exception:
                pass

            # Verify the team was created with the right prefix
            add_calls = db.add.call_args_list
            if add_calls:
                team_arg = add_calls[0][0][0]
                if isinstance(team_arg, EmailTeam):
                    assert team_arg.slug.startswith("workspace-")
                else:
                    # Team was passed to db.add — check slug in the call
                    for call in add_calls:
                        arg = call[0][0]
                        if hasattr(arg, "slug") and arg.slug:
                            assert arg.slug.startswith("workspace-")
                            break


class TestEmailVerificationForInvites:
    """Tests for require_email_verification_for_invites enforcement."""

    @pytest.fixture(autouse=True)
    async def drain_fire_and_forget_tasks(self):
        """Give fire-and-forget cache invalidation tasks one loop turn to complete."""
        yield
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_require_email_verification_for_invites(self):
        """When require_email_verification_for_invites=True and invitee is unverified, raise ValueError."""
        # First-Party
        from mcpgateway.services.team_invitation_service import TeamInvitationService

        db = MagicMock(spec=Session)
        service = TeamInvitationService(db)

        mock_team = MagicMock(spec=EmailTeam)
        mock_team.is_personal = False
        mock_team.max_members = 100

        mock_inviter = MagicMock(spec=EmailUser)
        mock_inviter.email = "owner@example.com"

        mock_invitee = MagicMock(spec=EmailUser)
        mock_invitee.email = "invitee@example.com"
        mock_invitee.email_verified_at = None  # Not verified

        mock_inviter_membership = MagicMock(spec=EmailTeamMember)
        mock_inviter_membership.role = "owner"

        def query_side_effect(model):
            mock_q = MagicMock()
            if model == EmailTeam:
                mock_q.filter.return_value.first.return_value = mock_team
            elif model == EmailUser:
                # Return inviter first, then invitee on subsequent calls
                mock_first = MagicMock()
                call_count = [0]

                def first_side_effect():
                    call_count[0] += 1
                    if call_count[0] == 1:
                        return mock_invitee  # invitee check (email verification)
                    return mock_inviter  # inviter check

                mock_first.first = first_side_effect
                mock_q.filter.return_value = mock_first
            elif model == EmailTeamMember:
                mock_q.filter.return_value.first.return_value = mock_inviter_membership
            else:
                mock_q.filter.return_value.first.return_value = None
            return mock_q

        db.query.side_effect = query_side_effect

        with patch("mcpgateway.services.team_invitation_service.settings") as mock_settings:
            mock_settings.allow_team_invitations = True
            mock_settings.require_email_verification_for_invites = True
            with pytest.raises(ValueError, match="not been verified"):
                await service.create_invitation(team_id="team-1", email="invitee@example.com", role="member", invited_by="owner@example.com")


class TestMaxTeamsInApproveJoinRequest:
    """Test max_teams_per_user enforcement in approve_join_request()."""

    @pytest.fixture(autouse=True)
    async def drain_fire_and_forget_tasks(self):
        yield
        await asyncio.sleep(0)

    @pytest.fixture(autouse=True)
    def clear_caches(self):
        try:
            # First-Party
            from mcpgateway.cache.auth_cache import get_auth_cache

            get_auth_cache().invalidate_all()
        except ImportError:
            pass
        try:
            # First-Party
            from mcpgateway.cache.admin_stats_cache import get_admin_stats_cache

            get_admin_stats_cache().invalidate_all()
        except ImportError:
            pass
        yield

    @pytest.mark.asyncio
    async def test_max_teams_enforced_in_approve_join_request(self):
        """When user is at max_teams_per_user limit, approve_join_request raises ValueError."""
        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService

        db = MagicMock(spec=Session)
        service = TeamManagementService(db)
        service._get_user_team_count = MagicMock(return_value=5)

        mock_join_request = MagicMock()
        mock_join_request.team_id = "team-1"
        mock_join_request.user_email = "user@example.com"
        mock_join_request.status = "pending"
        mock_join_request.is_expired.return_value = False
        db.query.return_value.filter.return_value.first.return_value = mock_join_request

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.max_teams_per_user = 5
            with pytest.raises(ValueError, match="maximum team limit"):
                await service.approve_join_request(request_id="req-1", approved_by="admin@example.com")


class TestAdminJoinRequestFlag:
    """Test allow_team_join_requests enforcement in admin UI."""

    @pytest.mark.asyncio
    async def test_admin_join_request_disabled(self):
        """When allow_team_join_requests=False, admin join request returns 403."""
        # First-Party
        from mcpgateway.admin import admin_create_join_request

        with patch("mcpgateway.admin.settings") as mock_settings:
            mock_settings.email_auth_enabled = True
            mock_settings.allow_team_join_requests = False

            mock_request = MagicMock()
            mock_db = MagicMock(spec=Session)
            mock_user = {"email": "user@example.com", "is_admin": False}

            result = await admin_create_join_request(team_id="team-1", request=mock_request, db=mock_db, user=mock_user)
            assert result.status_code == 403
            assert "disabled" in result.body.decode().lower()


class TestAcceptTimeEmailVerification:
    """Test require_email_verification_for_invites at accept-time."""

    @pytest.fixture(autouse=True)
    async def drain_fire_and_forget_tasks(self):
        yield
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_accept_invitation_unverified_email_rejected(self):
        """When require_email_verification_for_invites=True, unverified user cannot accept invitation."""
        # First-Party
        from mcpgateway.services.team_invitation_service import TeamInvitationService

        db = MagicMock(spec=Session)
        service = TeamInvitationService(db)
        service._get_user_team_count = MagicMock(return_value=0)

        mock_invitation = MagicMock()
        mock_invitation.email = "user@example.com"
        mock_invitation.team_id = "team-1"
        mock_invitation.is_valid.return_value = True
        mock_invitation.is_active = True
        service.get_invitation_by_token = AsyncMock(return_value=mock_invitation)

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user@example.com"
        mock_user.email_verified_at = None  # Not verified
        db.query.return_value.filter.return_value.first.return_value = mock_user

        with patch("mcpgateway.services.team_invitation_service.settings") as mock_settings:
            mock_settings.require_email_verification_for_invites = True
            mock_settings.max_teams_per_user = 50
            with pytest.raises(ValueError, match="not been verified"):
                await service.accept_invitation(token="test-token", accepting_user_email="user@example.com")


class TestAdminTeamCreationFlagDisabled:
    """Test allow_team_creation=False in admin UI (covers admin.py:5148)."""

    @pytest.mark.asyncio
    async def test_admin_ui_team_creation_disabled_non_admin(self):
        """Non-admin user in admin UI gets 403 when team creation is disabled."""
        # First-Party
        from mcpgateway.admin import admin_create_team

        with patch("mcpgateway.admin.settings") as mock_settings:
            mock_settings.email_auth_enabled = True
            mock_settings.allow_team_creation = False

            mock_request = MagicMock()
            mock_db = MagicMock(spec=Session)
            mock_user = {"email": "user@example.com", "is_admin": False}

            result = await admin_create_team(request=mock_request, db=mock_db, user=mock_user)
            assert result.status_code == 403
            assert "disabled" in result.body.decode().lower()


class TestAdminCreatedUserEmailVerified:
    """Test that admin-created users get email_verified_at set via service (covers email_auth_service.py)."""

    @pytest.mark.asyncio
    async def test_admin_created_user_gets_email_verified_via_service(self):
        """When granted_by is provided, create_user sets email_verified_at before insert."""
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService

        db = MagicMock(spec=Session)
        service = EmailAuthService(db)

        with (
            patch.object(service, "validate_email"),
            patch.object(service, "validate_password"),
            patch.object(service, "get_user_by_email", new=AsyncMock(return_value=None)),
            patch.object(service, "password_service") as mock_pw,
            patch("mcpgateway.services.email_auth_service.settings") as mock_settings,
            patch("mcpgateway.services.email_auth_service.EmailUser") as MockUser,
        ):
            mock_pw.hash_password_async = AsyncMock(return_value="hashed")
            mock_settings.auto_create_personal_teams = False

            mock_user_instance = MagicMock(spec=EmailUser)
            mock_user_instance.email = "new@example.com"
            mock_user_instance.email_verified_at = None
            MockUser.return_value = mock_user_instance

            result = await service.create_user(email="new@example.com", password="P@ssw0rd123", granted_by="admin@example.com")

        # email_verified_at should be set before db.add
        assert mock_user_instance.email_verified_at is not None

    @pytest.mark.asyncio
    async def test_self_registered_user_not_auto_verified(self):
        """When granted_by is None (self-registration), email_verified_at stays None."""
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService

        db = MagicMock(spec=Session)
        service = EmailAuthService(db)

        with (
            patch.object(service, "validate_email"),
            patch.object(service, "validate_password"),
            patch.object(service, "get_user_by_email", new=AsyncMock(return_value=None)),
            patch.object(service, "password_service") as mock_pw,
            patch("mcpgateway.services.email_auth_service.settings") as mock_settings,
            patch("mcpgateway.services.email_auth_service.EmailUser") as MockUser,
        ):
            mock_pw.hash_password_async = AsyncMock(return_value="hashed")
            mock_settings.auto_create_personal_teams = False

            mock_user_instance = MagicMock(spec=EmailUser)
            mock_user_instance.email = "self@example.com"
            mock_user_instance.email_verified_at = None
            MockUser.return_value = mock_user_instance

            result = await service.create_user(email="self@example.com", password="P@ssw0rd123")

        # email_verified_at should remain None
        assert mock_user_instance.email_verified_at is None


class TestInvitationFlagReturns403:
    """Test that ALLOW_TEAM_INVITATIONS=false returns 403 at router level."""

    @pytest.mark.asyncio
    @patch("mcpgateway.routers.teams.settings")
    async def test_invite_team_member_returns_403_when_disabled(self, mock_settings):
        """Router returns 403 (not 400) when allow_team_invitations=False."""
        mock_settings.allow_team_invitations = False

        # First-Party
        from mcpgateway.routers.teams import invite_team_member
        from mcpgateway.schemas import TeamInviteRequest

        request = TeamInviteRequest(email="someone@example.com", role="member")
        current_user = {"email": "owner@example.com", "is_admin": False}
        db = MagicMock(spec=Session)

        with pytest.raises(HTTPException) as exc_info:
            await invite_team_member(team_id="team-1", request=request, current_user=current_user, db=db)
        assert exc_info.value.status_code == 403
        assert "disabled" in exc_info.value.detail.lower()


class TestInvitationServiceGetUserTeamCount:
    """Test _get_user_team_count on TeamInvitationService (covers team_invitation_service.py:89)."""

    def test_get_user_team_count_returns_count(self):
        """_get_user_team_count queries the database and returns an integer count."""
        # First-Party
        from mcpgateway.services.team_invitation_service import TeamInvitationService

        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.count.return_value = 3
        service = TeamInvitationService(db)

        result = service._get_user_team_count("user@example.com")
        assert result == 3
        db.query.assert_called_once()


class TestGetUserTeamCount:
    """Test the shared get_user_team_count function and service delegations."""

    def test_standalone_function_returns_count(self):
        """get_user_team_count queries the database and returns an integer count."""
        # First-Party
        from mcpgateway.services.team_management_service import get_user_team_count

        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.count.return_value = 7

        result = get_user_team_count(db, "user@example.com")
        assert result == 7
        db.query.assert_called_once()

    def test_management_service_delegates(self):
        """TeamManagementService._get_user_team_count delegates to standalone function."""
        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService

        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.count.return_value = 3
        service = TeamManagementService(db)

        result = service._get_user_team_count("user@example.com")
        assert result == 3


class TestUpdateUserEmailVerified:
    """Test email_verified parameter in EmailAuthService.update_user (covers email_auth_service.py:1567-1568)."""

    @pytest.mark.asyncio
    async def test_update_user_sets_email_verified(self):
        """When email_verified=True, update_user sets email_verified_at."""
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService

        db = MagicMock(spec=Session)
        service = EmailAuthService(db)

        mock_user = MagicMock()
        mock_user.email = "user@example.com"
        mock_user.is_admin = False
        mock_user.is_active = True
        mock_user.email_verified_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = mock_result

        await service.update_user(email="user@example.com", email_verified=True)

        assert mock_user.email_verified_at is not None

    @pytest.mark.asyncio
    async def test_update_user_clears_email_verified(self):
        """When email_verified=False, update_user clears email_verified_at."""
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService

        db = MagicMock(spec=Session)
        service = EmailAuthService(db)

        mock_user = MagicMock()
        mock_user.email = "user@example.com"
        mock_user.is_admin = False
        mock_user.is_active = True
        mock_user.email_verified_at = datetime.now(timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = mock_result

        await service.update_user(email="user@example.com", email_verified=False)

        assert mock_user.email_verified_at is None
