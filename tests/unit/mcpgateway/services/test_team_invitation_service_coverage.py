# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.services.team_invitation_service — missing branches."""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeam, EmailTeamInvitation, EmailTeamMember, EmailUser
from mcpgateway.services.team_invitation_service import TeamInvitationService


@pytest.fixture
def db():
    return MagicMock(spec=Session)


@pytest.fixture
def svc(db):
    return TeamInvitationService(db)


def _mock_team(**overrides):
    t = MagicMock(spec=EmailTeam)
    t.id = overrides.get("id", "team1")
    t.name = "Team"
    t.is_personal = overrides.get("is_personal", False)
    t.is_active = True
    t.max_members = overrides.get("max_members", 100)
    return t


def _mock_invitation(**overrides):
    inv = MagicMock(spec=EmailTeamInvitation)
    inv.id = overrides.get("id", "inv1")
    inv.team_id = overrides.get("team_id", "team1")
    inv.email = overrides.get("email", "user@t.com")
    inv.role = overrides.get("role", "member")
    inv.invited_by = overrides.get("invited_by", "owner@t.com")
    inv.invited_at = datetime.now(timezone.utc)
    inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    inv.token = overrides.get("token", "tok-123")
    inv.is_active = overrides.get("is_active", True)
    inv.is_expired = MagicMock(return_value=overrides.get("is_expired", False))
    inv.is_valid = MagicMock(return_value=overrides.get("is_valid", True))
    return inv


# ===========================================================================
# create_invitation — deactivate old + create new path (lines 196-213)
# ===========================================================================


class TestCreateInvitationCoverage:
    @pytest.mark.asyncio
    async def test_deactivate_expired_existing_and_create_new(self, svc, db):
        """When an expired existing invitation exists, it's deactivated and a new one is created."""
        team = _mock_team()
        inviter = MagicMock(spec=EmailUser)
        inviter.email = "owner@t.com"
        inviter_membership = MagicMock(spec=EmailTeamMember)
        inviter_membership.role = "owner"
        inviter_membership.is_active = True

        # Existing invitation that IS expired
        existing_inv = _mock_invitation(is_expired=True, is_active=True)

        call_count = [0]

        def _query_side_effect(model):
            q = MagicMock()
            f = MagicMock()

            def _filter(*args, **kwargs):
                return f

            q.filter = _filter

            def _first():
                nonlocal call_count
                call_count[0] += 1
                # 1=team, 2=inviter user, 3=inviter membership,
                # 4=existing active member, 5=existing invitation, 6=member count(not used for first)
                if call_count[0] == 1:
                    return team
                elif call_count[0] == 2:
                    return inviter
                elif call_count[0] == 3:
                    return inviter_membership
                elif call_count[0] == 4:
                    return None  # not already a member
                elif call_count[0] == 5:
                    return existing_inv
                return None

            def _count():
                return 1  # member count or invitation count

            f.first = _first
            f.count = _count
            return q

        db.query = _query_side_effect

        result = await svc.create_invitation("team1", "user@t.com", "member", "owner@t.com")

        assert result is not None
        assert existing_inv.is_active is False  # old invitation deactivated
        db.add.assert_called_once()  # new invitation added
        db.commit.assert_called_once()


# ===========================================================================
# accept_invitation — create membership through cache (lines 309-334)
# ===========================================================================


class TestAcceptInvitationCoverage:
    @pytest.mark.asyncio
    async def test_successful_acceptance_creates_membership(self, svc, db):
        """Full acceptance flow: validates, creates membership, deactivates invitation."""
        invitation = _mock_invitation()
        team = _mock_team(max_members=None)

        call_count = [0]

        def _query_side_effect(model):
            nonlocal call_count
            q = MagicMock()
            f = MagicMock()
            q.filter = MagicMock(return_value=f)

            def _first():
                call_count[0] += 1
                # 1=user lookup, 2=team lookup, 3=existing member check, 4=member count
                if call_count[0] == 1:
                    return MagicMock(spec=EmailUser)  # user exists
                elif call_count[0] == 2:
                    return team
                elif call_count[0] == 3:
                    return None  # not already a member
                return None

            f.first = _first
            f.count = MagicMock(return_value=1)
            return q

        db.query = _query_side_effect

        with patch.object(svc, "get_invitation_by_token", AsyncMock(return_value=invitation)), \
             patch("asyncio.create_task", MagicMock(side_effect=RuntimeError("no loop"))):

            result = await svc.accept_invitation("tok-123", "user@t.com")

        assert result is True
        assert invitation.is_active is False
        db.add.assert_called_once()  # membership created
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_acceptance_cache_invalidation_failure(self, svc, db):
        """Cache failure during acceptance does not raise."""
        invitation = _mock_invitation()
        team = _mock_team(max_members=None)

        call_count = [0]

        def _query_side_effect(model):
            nonlocal call_count
            q = MagicMock()
            f = MagicMock()
            q.filter = MagicMock(return_value=f)

            def _first():
                call_count[0] += 1
                if call_count[0] == 1:
                    return MagicMock(spec=EmailUser)
                elif call_count[0] == 2:
                    return team
                elif call_count[0] == 3:
                    return None
                return None

            f.first = _first
            f.count = MagicMock(return_value=0)
            return q

        db.query = _query_side_effect

        with patch.object(svc, "get_invitation_by_token", AsyncMock(return_value=invitation)), \
             patch("asyncio.create_task", MagicMock(side_effect=RuntimeError("no loop"))):

            result = await svc.accept_invitation("tok-123", "user@t.com")

        assert result is True


# ===========================================================================
# decline_invitation — exception handler (lines 373-376)
# ===========================================================================


class TestDeclineInvitationCoverage:
    @pytest.mark.asyncio
    async def test_exception_returns_false(self, svc, db):
        with patch.object(svc, "get_invitation_by_token", AsyncMock(side_effect=RuntimeError("crash"))):
            result = await svc.decline_invitation("tok")
        assert result is False
        db.rollback.assert_called_once()


# ===========================================================================
# revoke_invitation — exception handler (lines 415-418)
# ===========================================================================


class TestRevokeInvitationCoverage:
    @pytest.mark.asyncio
    async def test_exception_returns_false(self, svc, db):
        db.query = MagicMock(side_effect=RuntimeError("crash"))

        result = await svc.revoke_invitation("inv1", "owner@t.com")
        assert result is False
        db.rollback.assert_called_once()


# ===========================================================================
# get_user_invitations — active_only=False branch (line 462->465)
# ===========================================================================


class TestGetUserInvitationsCoverage:
    @pytest.mark.asyncio
    async def test_active_only_false(self, svc, db):
        """When active_only=False, no is_active filter is applied."""
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order = MagicMock()
        mock_order.all = MagicMock(return_value=[])
        mock_filter.order_by = MagicMock(return_value=mock_order)
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        result = await svc.get_user_invitations("u@t.com", active_only=False)
        assert result == []
        # Verify that filter was called only once (no is_active filter added)
        mock_query.filter.assert_called_once()


# ===========================================================================
# create_invitation — no max_members + no existing invitation + explicit expiry
# ===========================================================================


class TestCreateInvitationBranches:
    @pytest.mark.asyncio
    async def test_no_max_members_no_existing_explicit_expiry(self, svc, db):
        """max_members=None skips limit check; no existing inv; explicit expiry_days."""
        team = _mock_team(max_members=None)
        inviter = MagicMock(spec=EmailUser)
        inviter.email = "owner@t.com"
        inviter_membership = MagicMock(spec=EmailTeamMember)
        inviter_membership.role = "owner"
        inviter_membership.is_active = True

        call_count = [0]

        def _query_side_effect(model):
            q = MagicMock()
            f = MagicMock()
            q.filter = MagicMock(return_value=f)

            def _first():
                call_count[0] += 1
                if call_count[0] == 1:
                    return team
                elif call_count[0] == 2:
                    return inviter
                elif call_count[0] == 3:
                    return inviter_membership
                elif call_count[0] == 4:
                    return None  # not already a member
                elif call_count[0] == 5:
                    return None  # no existing invitation
                return None

            f.first = _first
            f.count = MagicMock(return_value=0)
            return q

        db.query = _query_side_effect

        result = await svc.create_invitation("team1", "new@t.com", "member", "owner@t.com", expiry_days=14)
        assert result is not None
        db.add.assert_called_once()
        db.commit.assert_called_once()


# ===========================================================================
# accept_invitation — with max_members check + successful cache invalidation
# ===========================================================================


class TestAcceptInvitationMoreBranches:
    @pytest.mark.asyncio
    async def test_accept_with_max_members_not_reached(self, svc, db):
        """accept_invitation with max_members set but not reached."""
        invitation = _mock_invitation()
        team = _mock_team(max_members=10)

        call_count = [0]

        def _query_side_effect(model):
            q = MagicMock()
            f = MagicMock()
            q.filter = MagicMock(return_value=f)

            def _first():
                call_count[0] += 1
                if call_count[0] == 1:
                    return MagicMock(spec=EmailUser)  # user exists
                elif call_count[0] == 2:
                    return team
                elif call_count[0] == 3:
                    return None  # not already a member
                return None

            f.first = _first
            f.count = MagicMock(return_value=2)  # under limit
            return q

        db.query = _query_side_effect

        mock_auth_cache = MagicMock()
        mock_auth_cache.invalidate_team = AsyncMock()
        mock_auth_cache.invalidate_user_role = AsyncMock()
        mock_auth_cache.invalidate_user_teams = AsyncMock()
        mock_auth_cache.invalidate_team_membership = AsyncMock()

        with patch.object(svc, "get_invitation_by_token", AsyncMock(return_value=invitation)), \
             patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache):
            result = await svc.accept_invitation("tok-123", "user@t.com")

        assert result is True
        assert invitation.is_active is False
