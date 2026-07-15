# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_team_member_seeding.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for seeding members into a team at creation time.

These run against a real session rather than mocks: the point of the feature is
that the team, its memberships and its invitations are written as one atomic
unit, and only a real transaction can show that.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, EmailTeamInvitation, EmailTeamMember, EmailTeamMemberHistory, EmailUser, utc_now
from mcpgateway.schemas import MAX_TEAM_MEMBER_SEEDS, TeamMemberSeed
from mcpgateway.services.team_management_service import TeamManagementService, TeamMemberLimitExceededError, TeamMemberSeedError

CREATOR = "creator@example.com"

# The test engine is session-scoped, so each test starts from a clean slate itself.
TABLES_TO_CLEAR = (EmailTeamMemberHistory, EmailTeamInvitation, EmailTeamMember, EmailTeam, EmailUser)


def make_user(db, email, *, is_active=True, verified=True):
    """Persist an EmailUser for the tests to route against.

    Args:
        db: Database session.
        email: Email address of the user.
        is_active: Whether the account is active.
        verified: Whether the email address is verified.

    Returns:
        EmailUser: The persisted user.
    """
    user = EmailUser(
        email=email,
        password_hash="x",  # pragma: allowlist secret
        is_admin=False,
        is_active=is_active,
        email_verified_at=utc_now() if verified else None,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def service(test_db):
    """Team management service bound to a freshly emptied test session.

    Args:
        test_db: Database session fixture.

    Returns:
        TeamManagementService: Service under test, with the creator already registered.
    """
    for model in TABLES_TO_CLEAR:
        test_db.query(model).delete()
    test_db.commit()

    make_user(test_db, CREATOR)
    return TeamManagementService(test_db)


def team_exists(db, name):
    """Report whether a team with this name survived the call.

    Args:
        db: Database session.
        name: Team name to look for.

    Returns:
        bool: True if the team is present.
    """
    return db.query(EmailTeam).filter(EmailTeam.name == name).first() is not None


class TestMemberSeedRouting:
    """The server decides member vs. invitation; the caller does not."""

    @pytest.mark.asyncio
    async def test_active_user_is_added_unknown_email_is_invited(self, service, test_db):
        """An active user becomes a member; an unknown address gets an invitation."""
        make_user(test_db, "alice@example.com")

        result = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[
                TeamMemberSeed(email="alice@example.com", role="member"),
                TeamMemberSeed(email="external@partner.com", role="member"),
            ],
        )

        assert [m.email for m in result.members_added] == ["alice@example.com"]
        assert [i.email for i in result.invitations_sent] == ["external@partner.com"]
        assert result.invitations_sent[0].invitation_id

        # Creator is the owner, alice is a member, the outsider is not a member at all
        members = {m.user_email: m.role for m in test_db.query(EmailTeamMember).filter(EmailTeamMember.team_id == result.team.id, EmailTeamMember.is_active.is_(True)).all()}
        assert members == {CREATOR: "owner", "alice@example.com": "member"}

        invitation = test_db.query(EmailTeamInvitation).filter(EmailTeamInvitation.team_id == result.team.id).one()
        assert invitation.email == "external@partner.com"
        assert invitation.invited_by == CREATOR
        assert invitation.token

    @pytest.mark.asyncio
    async def test_deactivated_user_is_invited_not_added(self, service, test_db):
        """A known but deactivated account is invited rather than silently re-added."""
        make_user(test_db, "gone@example.com", is_active=False)

        result = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[TeamMemberSeed(email="gone@example.com", role="member")],
        )

        assert result.members_added == []
        assert [i.email for i in result.invitations_sent] == ["gone@example.com"]

    @pytest.mark.asyncio
    async def test_seeded_role_is_honoured(self, service, test_db):
        """Owner seeds land as owners, for members and invitees alike."""
        make_user(test_db, "lead@example.com")

        result = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[
                TeamMemberSeed(email="lead@example.com", role="owner"),
                TeamMemberSeed(email="external@partner.com", role="owner"),
            ],
        )

        assert result.members_added[0].role == "owner"
        assert result.invitations_sent[0].role == "owner"

        membership = test_db.query(EmailTeamMember).filter(EmailTeamMember.team_id == result.team.id, EmailTeamMember.user_email == "lead@example.com").one()
        assert membership.role == "owner"

    @pytest.mark.asyncio
    async def test_creator_row_is_skipped(self, service, test_db):
        """Listing yourself is a no-op: team creation already makes you the owner."""
        result = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[
                TeamMemberSeed(email=CREATOR.upper(), role="member"),
                TeamMemberSeed(email="external@partner.com", role="member"),
            ],
        )

        assert result.members_added == []
        assert [i.email for i in result.invitations_sent] == ["external@partner.com"]

        membership = test_db.query(EmailTeamMember).filter(EmailTeamMember.team_id == result.team.id, EmailTeamMember.user_email == CREATOR).one()
        assert membership.role == "owner"


class TestMixedCaseEmailNormalisation:
    """Seed emails with uppercase characters are handled as their lowercase canonical form."""

    @pytest.mark.asyncio
    async def test_uppercase_active_user_is_matched_and_added(self, service, test_db):
        """An active user whose address is supplied in mixed-case is added as a member.

        Regression: before the fix, str(seed.email).strip() preserved case, so the
        EmailUser.email.in_([...]) query returned nothing for 'ALICE@example.com'
        (the canonical record is 'alice@example.com'), and the seed fell through to
        the invitation path — storing 'ALICE@example.com' in the invitation.  That
        invitation could never be accepted because accept_invitation() compares
        invitation.email against the lowercase authenticated identity.
        """
        make_user(test_db, "alice@example.com")

        result = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[TeamMemberSeed(email="ALICE@example.com", role="member")],
        )

        # Must be a membership, not an invitation
        assert [m.email for m in result.members_added] == ["alice@example.com"]
        assert result.invitations_sent == []

        # Canonical lowercase address stored in the membership row
        member = test_db.query(EmailTeamMember).filter(EmailTeamMember.team_id == result.team.id, EmailTeamMember.user_email == "alice@example.com").one()
        assert member.role == "member"

    @pytest.mark.asyncio
    async def test_uppercase_unknown_email_invitation_is_stored_lowercase(self, service, test_db):
        """An unknown address supplied in mixed-case is invited using its canonical lowercase form."""
        result = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[TeamMemberSeed(email="External@Partner.com", role="member")],
        )

        assert result.members_added == []
        assert [i.email for i in result.invitations_sent] == ["external@partner.com"]

        invitation = test_db.query(EmailTeamInvitation).filter(EmailTeamInvitation.team_id == result.team.id).one()
        assert invitation.email == "external@partner.com"

    @pytest.mark.asyncio
    async def test_mixed_case_duplicate_is_rejected(self, service, test_db):
        """alice@example.com and ALICE@example.com are the same address and must be de-duped."""
        make_user(test_db, "alice@example.com")

        with pytest.raises(TeamMemberSeedError) as exc_info:
            await service.create_team_with_members(
                name="Engineering",
                description=None,
                created_by=CREATOR,
                visibility="private",
                members=[
                    TeamMemberSeed(email="alice@example.com", role="member"),
                    TeamMemberSeed(email="ALICE@example.com", role="owner"),
                ],
            )

        assert exc_info.value.index == 1
        assert "already listed at members[0]" in str(exc_info.value)
        assert not team_exists(test_db, "Engineering")


class TestMemberSeedAtomicity:
    """A bad row leaves nothing behind — no team, no members, no invitations."""

    @pytest.mark.asyncio
    async def test_duplicate_emails_are_rejected(self, service, test_db):
        """The same address twice is a caller error, and creates nothing."""
        make_user(test_db, "alice@example.com")

        with pytest.raises(TeamMemberSeedError) as exc_info:
            await service.create_team_with_members(
                name="Engineering",
                description=None,
                created_by=CREATOR,
                visibility="private",
                members=[
                    TeamMemberSeed(email="alice@example.com", role="member"),
                    TeamMemberSeed(email="ALICE@example.com", role="owner"),
                ],
            )

        assert exc_info.value.index == 1
        assert "already listed at members[0]" in str(exc_info.value)
        assert not team_exists(test_db, "Engineering")

    @pytest.mark.asyncio
    async def test_more_seeds_than_allowed_in_one_call(self, service):
        """A request larger than the hard ceiling is refused outright."""
        members = [TeamMemberSeed(email=f"user{i}@example.com") for i in range(MAX_TEAM_MEMBER_SEEDS + 1)]

        with pytest.raises(TeamMemberLimitExceededError, match="more than"):
            await service.create_team_with_members(name="Huge", description=None, created_by=CREATOR, visibility="private", max_members=0, members=members)


class TestSeedErrorsIdentifyTheRow:
    """A failing row is reported by the position the caller sent it in."""

    @pytest.mark.asyncio
    async def test_failing_row_is_named_by_request_index(self, service, test_db):
        """The reported index is the caller's row, not the position after filtering."""
        make_user(test_db, "alice@example.com")

        # The creator's row is dropped during normalization, so the failing invitation
        # is the 2nd surviving seed but the 3rd row the caller actually typed.
        with patch.object(settings, "allow_team_invitations", False):
            with pytest.raises(TeamMemberSeedError) as exc_info:
                await service.create_team_with_members(
                    name="Engineering",
                    description=None,
                    created_by=CREATOR,
                    visibility="private",
                    members=[
                        TeamMemberSeed(email=CREATOR, role="member"),
                        TeamMemberSeed(email="alice@example.com", role="member"),
                        TeamMemberSeed(email="external@partner.com", role="member"),
                    ],
                )

        error = exc_info.value
        assert error.index == 2
        assert error.email == "external@partner.com"
        assert str(error).startswith("members[2] (external@partner.com):")
        assert "invitations are currently disabled" in error.reason

    @pytest.mark.asyncio
    async def test_member_at_team_limit_is_named(self, service, test_db):
        """A user who cannot join another team is identified, not reported anonymously."""
        make_user(test_db, "alice@example.com")
        make_user(test_db, "bob@example.com")

        # Bob is already in as many teams as he is allowed
        with patch.object(settings, "max_teams_per_user", 0):
            with pytest.raises(TeamMemberSeedError) as exc_info:
                await service.create_team_with_members(
                    name="Engineering",
                    description=None,
                    created_by=CREATOR,
                    visibility="private",
                    skip_limits=True,  # the creator bypasses the limit; the seeded member must not
                    members=[TeamMemberSeed(email="bob@example.com", role="member")],
                )

        assert exc_info.value.email == "bob@example.com"
        assert "maximum team limit" in exc_info.value.reason
        assert not team_exists(test_db, "Engineering")


class TestInvitationTransactionOwnership:
    """create_invitation(commit=False) must not unwind a transaction it does not own."""

    @pytest.mark.asyncio
    async def test_failure_leaves_the_callers_transaction_intact(self, service, test_db):
        """A failing invitation leaves the caller's pending rows for the caller to deal with."""
        # First-Party
        from mcpgateway.services.team_invitation_service import TeamInvitationService

        team = await service.create_team(name="Engineering", description=None, created_by=CREATOR, visibility="private")

        # An uncommitted row belonging to the caller's transaction
        test_db.add(EmailUser(email="pending@example.com", password_hash="x", is_admin=False, is_active=True))  # pragma: allowlist secret
        test_db.flush()

        with pytest.raises(ValueError):
            await TeamInvitationService(test_db).create_invitation(team_id=team.id, email="x@example.com", role="bogus-role", invited_by=CREATOR, commit=False)

        # Still there: the callee did not roll the caller's work back
        assert test_db.query(EmailUser).filter(EmailUser.email == "pending@example.com").first() is not None

    @pytest.mark.asyncio
    async def test_failure_still_rolls_back_when_it_owns_the_transaction(self, service, test_db):
        """The default path is unchanged: create_invitation rolls its own work back."""
        # First-Party
        from mcpgateway.services.team_invitation_service import TeamInvitationService

        team = await service.create_team(name="Engineering", description=None, created_by=CREATOR, visibility="private")

        test_db.add(EmailUser(email="pending@example.com", password_hash="x", is_admin=False, is_active=True))  # pragma: allowlist secret
        test_db.flush()

        with pytest.raises(ValueError):
            await TeamInvitationService(test_db).create_invitation(team_id=team.id, email="x@example.com", role="bogus-role", invited_by=CREATOR)

        assert test_db.query(EmailUser).filter(EmailUser.email == "pending@example.com").first() is None


class TestSeedRollback:
    """A row that cannot be applied takes the whole team with it."""

    @pytest.mark.asyncio
    async def test_seeds_over_capacity_are_rejected(self, service, test_db):
        """Creator plus seeds must fit the member limit, checked before any write."""
        make_user(test_db, "alice@example.com")

        with pytest.raises(TeamMemberLimitExceededError):
            await service.create_team_with_members(
                name="Engineering",
                description=None,
                created_by=CREATOR,
                visibility="private",
                max_members=2,
                members=[
                    TeamMemberSeed(email="alice@example.com", role="member"),
                    TeamMemberSeed(email="external@partner.com", role="member"),
                ],
            )

        assert not team_exists(test_db, "Engineering")

    @pytest.mark.asyncio
    async def test_creator_plus_seeds_exactly_at_the_limit_is_allowed(self, service, test_db):
        """The boundary is inclusive: creator + seeds may equal max_members exactly."""
        make_user(test_db, "alice@example.com")

        # max_members=2 leaves room for the creator (owner) plus exactly one seed.
        result = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            max_members=2,
            members=[TeamMemberSeed(email="alice@example.com", role="member")],
        )

        assert [m.email for m in result.members_added] == ["alice@example.com"]
        members = test_db.query(EmailTeamMember).filter(EmailTeamMember.team_id == result.team.id, EmailTeamMember.is_active.is_(True)).count()
        assert members == 2

    @pytest.mark.asyncio
    async def test_failed_invitation_rolls_back_the_whole_team(self, service, test_db):
        """An invitation that cannot be sent takes the team and the members with it."""
        make_user(test_db, "alice@example.com")

        with patch.object(settings, "allow_team_invitations", False):
            with pytest.raises(TeamMemberSeedError, match="invitations are currently disabled"):
                await service.create_team_with_members(
                    name="Engineering",
                    description=None,
                    created_by=CREATOR,
                    visibility="private",
                    members=[
                        TeamMemberSeed(email="alice@example.com", role="member"),
                        TeamMemberSeed(email="external@partner.com", role="member"),
                    ],
                )

        # The membership for alice was written before the failing row, and must be gone too
        assert not team_exists(test_db, "Engineering")
        assert test_db.query(EmailTeamMember).filter(EmailTeamMember.user_email == "alice@example.com").first() is None
        assert test_db.query(EmailTeamInvitation).count() == 0


class TestSeedingAReactivatedTeam:
    """Creating a team whose slug matches a deleted one revives that row — seeds must survive it."""

    @pytest.mark.asyncio
    async def test_deleting_a_team_deactivates_its_pending_invitations(self, service, test_db):
        """An invitation must not outlive the team it points at."""
        result = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[TeamMemberSeed(email="external@partner.com", role="member")],
        )

        await service.delete_team(result.team.id, deleted_by=CREATOR)

        invitation = test_db.query(EmailTeamInvitation).filter(EmailTeamInvitation.team_id == result.team.id).one()
        assert invitation.is_active is False

    @pytest.mark.asyncio
    async def test_recreating_a_deleted_team_with_the_same_people(self, service, test_db):
        """The same name and the same members, after a delete, must not collide with the old rows."""
        make_user(test_db, "alice@example.com")

        first = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[
                TeamMemberSeed(email="alice@example.com", role="member"),
                TeamMemberSeed(email="external@partner.com", role="member"),
            ],
        )
        await service.delete_team(first.team.id, deleted_by=CREATOR)

        # Same team, same people. Alice's membership and the partner's invitation both
        # have stale rows from the previous incarnation.
        second = await service.create_team_with_members(
            name="Engineering",
            description=None,
            created_by=CREATOR,
            visibility="private",
            members=[
                TeamMemberSeed(email="alice@example.com", role="owner"),
                TeamMemberSeed(email="external@partner.com", role="member"),
            ],
        )

        assert second.team.id == first.team.id  # the slug collision reactivated the original row
        assert [m.email for m in second.members_added] == ["alice@example.com"]
        assert [i.email for i in second.invitations_sent] == ["external@partner.com"]

        # Alice comes back with her new role, not the one she had before
        members = {m.user_email: m.role for m in test_db.query(EmailTeamMember).filter(EmailTeamMember.team_id == second.team.id, EmailTeamMember.is_active.is_(True)).all()}
        assert members == {CREATOR: "owner", "alice@example.com": "owner"}

        # Exactly one live invitation: the new one, not the resurrected old one
        active = test_db.query(EmailTeamInvitation).filter(EmailTeamInvitation.team_id == second.team.id, EmailTeamInvitation.is_active.is_(True)).all()
        assert [i.id for i in active] == [second.invitations_sent[0].invitation_id]


class TestSeededMembershipCrossServiceEffects:
    """Seeding a member must reach the same RBAC and cache side effects as add_member_to_team()."""

    @pytest.mark.asyncio
    async def test_seeded_members_get_an_rbac_role_invitees_do_not(self, service, test_db):
        """Each added member is granted the matching RBAC role; invited addresses are not."""
        make_user(test_db, "alice@example.com")
        make_user(test_db, "lead@example.com")

        with patch.object(service, "_assign_team_rbac_role", new_callable=AsyncMock) as assign_role:
            result = await service.create_team_with_members(
                name="Engineering",
                description=None,
                created_by=CREATOR,
                visibility="private",
                members=[
                    TeamMemberSeed(email="alice@example.com", role="member"),
                    TeamMemberSeed(email="lead@example.com", role="owner"),
                    TeamMemberSeed(email="external@partner.com", role="member"),
                ],
            )

        team_id = str(result.team.id)
        granted = {(call.args[0], call.args[1], call.args[2]) for call in assign_role.call_args_list}
        # Both known users are granted their seeded role against the new team.
        assert ("alice@example.com", team_id, "member") in granted
        assert ("lead@example.com", team_id, "owner") in granted
        # The invited outsider never became a member, so no role is assigned for them.
        assert not any(call.args[0] == "external@partner.com" for call in assign_role.call_args_list)

    @pytest.mark.asyncio
    async def test_auth_caches_are_invalidated_for_each_seeded_member(self, service, test_db):
        """Adding a member must invalidate that member's auth caches, or a stale cache hides the new team."""
        make_user(test_db, "alice@example.com")

        with patch.object(service, "_invalidate_membership_caches", new=MagicMock()) as invalidate:
            result = await service.create_team_with_members(
                name="Engineering",
                description=None,
                created_by=CREATOR,
                visibility="private",
                members=[
                    TeamMemberSeed(email="alice@example.com", role="member"),
                    TeamMemberSeed(email="external@partner.com", role="member"),
                ],
            )

        team_id = str(result.team.id)
        invalidated = {call.args[0] for call in invalidate.call_args_list}
        # The added member's caches are cleared; the invited outsider has no membership to clear.
        assert "alice@example.com" in invalidated
        assert "external@partner.com" not in invalidated
        assert all(call.args[1] == team_id for call in invalidate.call_args_list)


class TestCreateTeamUnchanged:
    """Existing callers that do not seed members are unaffected."""

    @pytest.mark.asyncio
    async def test_create_team_still_returns_the_team(self, service, test_db):
        """create_team keeps its old signature and return type."""
        team = await service.create_team(name="Engineering", description="Software", created_by=CREATOR, visibility="private")

        assert isinstance(team, EmailTeam)
        assert team.name == "Engineering"

        members = test_db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team.id).all()
        assert [(m.user_email, m.role) for m in members] == [(CREATOR, "owner")]

    @pytest.mark.asyncio
    async def test_no_members_seeds_nothing(self, service):
        """An omitted members list produces empty result arrays, not None."""
        result = await service.create_team_with_members(name="Engineering", description=None, created_by=CREATOR, visibility="private")

        assert result.members_added == []
        assert result.invitations_sent == []
