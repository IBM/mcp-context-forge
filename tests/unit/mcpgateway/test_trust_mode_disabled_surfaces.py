# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_mode_disabled_surfaces.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Disabled-with-clear-error surfaces (#5906): every "Disabled" row of the B.2
feature-by-mode matrix (docs/docs/architecture/auth-feature-mode-matrix.md)
gets an executable test here. With JWT trust mode ON, the documented HTTP
status and message come back — never a 500, never an IntegrityError.

Rows are of two kinds:

- Mode-level rows (password authentication, SSO browser login, session
  refresh, user management): the surface is off for every caller while
  ``jwt_trust_mode="jwt-trust"``.
- Local-record rows (invitations, team membership writes, API-token
  catalog): a trust-only principal — one with no ``email_users`` row — hits
  the surface and gets the documented error. DB-backed principals keep the
  default behavior.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock
import uuid

# Third-Party
from fastapi import HTTPException
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.admin as admin_module
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser
from mcpgateway.routers import email_auth as email_auth_router
from mcpgateway.routers.auth import refresh_session
from mcpgateway.routers.sso import handle_sso_callback
from mcpgateway.routers.teams import add_team_member, invite_team_member
from mcpgateway.schemas import (
    AdminCreateUserRequest,
    AdminUserUpdateRequest,
    EmailLoginRequest,
    ForgotPasswordRequest,
    PublicRegistrationRequest,
    ResetPasswordRequest,
    TeamInviteRequest,
    TeamMemberAddRequest,
)
from mcpgateway.services.team_invitation_service import TeamInvitationService
from mcpgateway.services.team_management_service import LocalUserRecordRequiredError, TeamManagementService, UserNotFoundError
from mcpgateway.services.token_catalog_service import TokenCatalogService

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

TRUST_ONLY_EMAIL = "trust.only@example.com"  # never has an EmailUser row
OWNER_EMAIL = "owner@example.com"
INVITEE_EMAIL = "invitee@example.com"

PASSWORD_DISABLED_MSG = "Password authentication disabled in trust mode"
USER_MANAGEMENT_DISABLED_MSG = "User management disabled in trust mode"
SSO_DISABLED_MSG = "SSO browser login disabled in trust mode"
SESSION_REFRESH_DISABLED_MSG = "Session refresh disabled in trust mode"
INVITATIONS_MSG = "Invitations require local user records"
MEMBERSHIP_WRITES_MSG = "Team membership writes require local user records"
TOKEN_MINTING_MSG = "Token minting is disabled for trust-only principals. Create a local user account first."


@pytest.fixture(autouse=True)
def setup_rbac_mocks():
    """Bypass the RBAC decorator layer; the trust-mode gates are under test."""
    originals = patch_rbac_decorators()
    yield
    restore_rbac_decorators(originals)


@pytest.fixture
def db():
    """In-memory SQLite session with the full schema and no rows."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def trust_mode(monkeypatch):
    """Switch the deployment to JWT trust mode."""
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")


def _add_user(db, email: str, *, is_admin: bool = False) -> EmailUser:
    """Insert an EmailUser row and return it."""
    now = datetime.now(timezone.utc)
    user = EmailUser(
        email=email,
        password_hash="hash",  # pragma: allowlist secret
        full_name="Surface Owner",
        is_admin=is_admin,
        is_active=True,
        email_verified_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _add_team(db, team_id: str, created_by: str) -> EmailTeam:
    """Insert a non-personal, active team."""
    team = EmailTeam(id=team_id, name=f"Team {team_id}", slug=f"team-{team_id}", created_by=created_by, is_personal=False, visibility="private")
    db.add(team)
    db.commit()
    return team


def _add_membership(db, team_id: str, user_email: str, role: str = "owner") -> EmailTeamMember:
    """Insert an active team membership."""
    member = EmailTeamMember(id=str(uuid.uuid4()), team_id=team_id, user_email=user_email, role=role, is_active=True, joined_at=datetime.now(timezone.utc))
    db.add(member)
    db.commit()
    return member


def _admin_ctx(email: str = OWNER_EMAIL) -> dict:
    """User context dict for permission-decorated endpoints."""
    return {"email": email, "is_admin": True, "permissions": ["admin.user_management", "teams.manage_members"], "auth_method": "jwt"}


class TestPasswordAuthenticationDisabled:
    """Matrix row: Password login/register/reset -> 401 in trust mode."""

    @pytest.mark.asyncio
    async def test_login_rejected(self, trust_mode, db):
        """POST /auth/email/login -> 401 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await email_auth_router.login(EmailLoginRequest(email=TRUST_ONLY_EMAIL, password="password123"), MagicMock(), db)  # pragma: allowlist secret
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == PASSWORD_DISABLED_MSG

    @pytest.mark.asyncio
    async def test_register_rejected(self, trust_mode, db):
        """POST /auth/email/register -> 401 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await email_auth_router.register(PublicRegistrationRequest(email=TRUST_ONLY_EMAIL, password="password123"), MagicMock(), db)  # pragma: allowlist secret
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == PASSWORD_DISABLED_MSG

    @pytest.mark.asyncio
    async def test_forgot_password_rejected(self, trust_mode, db):
        """POST /auth/email/forgot-password -> 401 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await email_auth_router.forgot_password(ForgotPasswordRequest(email=TRUST_ONLY_EMAIL), MagicMock(), db)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == PASSWORD_DISABLED_MSG

    @pytest.mark.asyncio
    async def test_validate_reset_token_rejected(self, trust_mode, db):
        """GET /auth/email/reset-password/{token} -> 401 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await email_auth_router.validate_password_reset_token("reset-token", MagicMock(), db)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == PASSWORD_DISABLED_MSG

    @pytest.mark.asyncio
    async def test_complete_reset_rejected(self, trust_mode, db):
        """POST /auth/email/reset-password/{token} -> 401 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await email_auth_router.complete_password_reset("reset-token", ResetPasswordRequest(new_password="password123", confirm_password="password123"), MagicMock(), db)  # pragma: allowlist secret
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == PASSWORD_DISABLED_MSG


class TestSsoBrowserLoginDisabled:
    """Matrix row: SSO browser login -> 401 in trust mode."""

    @pytest.mark.asyncio
    async def test_callback_rejected(self, trust_mode, monkeypatch, db):
        """GET /auth/sso/callback/{provider} -> 401 with the documented message."""
        monkeypatch.setattr(settings, "sso_enabled", True)
        with pytest.raises(HTTPException) as exc_info:
            await handle_sso_callback(provider_id="entra", code="auth-code", state="state", request=MagicMock(), response=MagicMock(), db=db)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == SSO_DISABLED_MSG


class TestSessionRefreshDisabled:
    """Matrix row: Session-token refresh -> 401 in trust mode."""

    @pytest.mark.asyncio
    async def test_refresh_rejected(self, trust_mode):
        """POST /auth/refresh -> 401 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await refresh_session(MagicMock(), MagicMock())
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == SESSION_REFRESH_DISABLED_MSG


class TestUserManagementDisabled:
    """Matrix row: Admin UI user CRUD + admin API CRUD -> 403 in trust mode."""

    @pytest.mark.asyncio
    async def test_api_create_user_rejected(self, trust_mode, db):
        """POST /auth/email/admin/users -> 403 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await email_auth_router.create_user(AdminCreateUserRequest(email=INVITEE_EMAIL, password="password123"), current_user_ctx=_admin_ctx(), db=db)  # pragma: allowlist secret
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == USER_MANAGEMENT_DISABLED_MSG

    @pytest.mark.asyncio
    async def test_api_update_user_rejected(self, trust_mode, db):
        """PATCH /auth/email/admin/users/{email} -> 403 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await email_auth_router.update_user(INVITEE_EMAIL, AdminUserUpdateRequest(full_name="New Name"), current_user_ctx=_admin_ctx(), db=db)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == USER_MANAGEMENT_DISABLED_MSG

    @pytest.mark.asyncio
    async def test_api_delete_user_rejected(self, trust_mode, db):
        """DELETE /auth/email/admin/users/{email} -> 403 with the documented message."""
        with pytest.raises(HTTPException) as exc_info:
            await email_auth_router.delete_user(INVITEE_EMAIL, current_user_ctx=_admin_ctx(), db=db)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == USER_MANAGEMENT_DISABLED_MSG

    @pytest.mark.asyncio
    async def test_admin_ui_create_user_rejected(self, trust_mode, db):
        """Admin UI POST /admin/users -> 403 HTML with the documented message."""
        response = await admin_module.admin_create_user(request=MagicMock(), db=db, user=_admin_ctx())
        assert response.status_code == 403
        assert USER_MANAGEMENT_DISABLED_MSG in response.body.decode()

    @pytest.mark.asyncio
    async def test_admin_ui_update_user_rejected(self, trust_mode, db):
        """Admin UI POST /admin/users/{email}/update -> 403 HTML with the message."""
        response = await admin_module.admin_update_user(user_email=INVITEE_EMAIL, request=MagicMock(), db=db, _user=_admin_ctx())
        assert response.status_code == 403
        assert USER_MANAGEMENT_DISABLED_MSG in response.body.decode()

    @pytest.mark.asyncio
    async def test_admin_ui_delete_user_rejected(self, trust_mode, db):
        """Admin UI DELETE /admin/users/{email} -> 403 HTML with the message."""
        response = await admin_module.admin_delete_user(user_email=INVITEE_EMAIL, _request=MagicMock(), db=db, user=_admin_ctx())
        assert response.status_code == 403
        assert USER_MANAGEMENT_DISABLED_MSG in response.body.decode()


class TestInvitationsRequireLocalUserRecords:
    """Matrix row: Invitations -> 403 for trust-only principals in trust mode."""

    @pytest.mark.asyncio
    async def test_service_rejects_trust_only_inviter(self, trust_mode, db):
        """create_invitation with no local inviter record -> documented error."""
        _add_team(db, "team-inv", created_by=OWNER_EMAIL)
        service = TeamInvitationService(db)
        with pytest.raises(LocalUserRecordRequiredError) as exc_info:
            await service.create_invitation(team_id="team-inv", email=INVITEE_EMAIL, role="member", invited_by=TRUST_ONLY_EMAIL)
        assert str(exc_info.value) == INVITATIONS_MSG

    @pytest.mark.asyncio
    async def test_endpoint_rejects_trust_only_inviter(self, trust_mode, monkeypatch, db):
        """POST /teams/{id}/invitations -> 403 with the documented message."""
        monkeypatch.setattr(settings, "allow_team_invitations", True)
        _add_team(db, "team-inv", created_by=OWNER_EMAIL)
        with pytest.raises(HTTPException) as exc_info:
            await invite_team_member("team-inv", TeamInviteRequest(email=INVITEE_EMAIL, role="member"), current_user={"email": TRUST_ONLY_EMAIL, "auth_method": "jwt"}, db=db)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == INVITATIONS_MSG

    @pytest.mark.asyncio
    async def test_default_mode_inviter_behavior_unchanged(self, monkeypatch, db):
        """Default mode: a missing inviter still returns None (legacy behavior)."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        _add_team(db, "team-inv", created_by=OWNER_EMAIL)
        service = TeamInvitationService(db)
        result = await service.create_invitation(team_id="team-inv", email=INVITEE_EMAIL, role="member", invited_by=TRUST_ONLY_EMAIL)
        assert result is None


class TestTeamMembershipWritesRequireLocalUserRecords:
    """Matrix row: Team membership writes -> 403 for trust-only targets."""

    @pytest.mark.asyncio
    async def test_service_rejects_trust_only_target(self, trust_mode, db):
        """add_member_to_team for a user with no local record -> documented error."""
        _add_team(db, "team-mem", created_by=OWNER_EMAIL)
        service = TeamManagementService(db)
        with pytest.raises(LocalUserRecordRequiredError) as exc_info:
            await service.add_member_to_team("team-mem", TRUST_ONLY_EMAIL, "member", invited_by=OWNER_EMAIL)
        assert str(exc_info.value) == MEMBERSHIP_WRITES_MSG

    @pytest.mark.asyncio
    async def test_endpoint_rejects_trust_only_target(self, trust_mode, db):
        """POST /teams/{id}/members -> 403 with the documented message."""
        _add_user(db, OWNER_EMAIL)
        _add_team(db, "team-mem", created_by=OWNER_EMAIL)
        _add_membership(db, "team-mem", OWNER_EMAIL, role="owner")
        with pytest.raises(HTTPException) as exc_info:
            await add_team_member("team-mem", TeamMemberAddRequest(email=TRUST_ONLY_EMAIL, role="member"), current_user=_admin_ctx(), db=db)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == MEMBERSHIP_WRITES_MSG

    @pytest.mark.asyncio
    async def test_default_mode_still_raises_user_not_found(self, monkeypatch, db):
        """Default mode: unknown target -> UserNotFoundError (legacy behavior)."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        _add_team(db, "team-mem", created_by=OWNER_EMAIL)
        service = TeamManagementService(db)
        with pytest.raises(UserNotFoundError):
            await service.add_member_to_team("team-mem", TRUST_ONLY_EMAIL, "member", invited_by=OWNER_EMAIL)


class TestTokenCatalogTrustOnlyPrincipal:
    """Matrix row: API-token catalog -> explicit error for trust-only principals."""

    @pytest.mark.asyncio
    async def test_create_token_rejects_trust_only_principal(self, trust_mode, db):
        """create_token with no local user record -> documented explicit error."""
        service = TokenCatalogService(db)
        with pytest.raises(ValueError) as exc_info:
            await service.create_token(user_email=TRUST_ONLY_EMAIL, name="ghost-token", caller_email=TRUST_ONLY_EMAIL)
        assert str(exc_info.value) == TOKEN_MINTING_MSG
