# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_trust_token_minting.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Trust-token minting (#5904): the gateway-signed ``token_use="trusted"`` mint
path and the operational ``POST /admin/tokens/trust`` endpoint.

The minted token must satisfy the B.1 dispatch rule's eligibility check for
gateway-signed tokens (``token_use=="trusted"``, mapped user_id claim present,
configured revocation claim present). All claims derive from server-side
authority; ``sub`` always equals the verified principal's user_id (no act-as).
Trust tokens are ephemeral: no ``email_api_tokens`` row is written.
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import uuid

# Third-Party
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import jwt
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailApiToken, EmailTeam, EmailTeamMember, EmailUser, Role, UserRole
from mcpgateway.routers.tokens import create_trust_token, TrustTokenMintRequest
from mcpgateway.services.token_catalog_service import TokenCatalogService
from mcpgateway.utils.trusted_claims import VirtualPrincipal

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

CALLER_ID = "trust-subject-0042"
CALLER_EMAIL = "trust.mint@example.com"
TARGET_EMAIL = "mint.target@example.com"
ADMIN_EMAIL = "mint.admin@example.com"


@pytest.fixture(autouse=True)
def setup_rbac_mocks():
    """Bypass the RBAC decorator layer; the endpoint's own gates are under test."""
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
def service(db):
    """Token catalog service bound to the test database."""
    return TokenCatalogService(db)


def _add_user(db, email: str, *, is_admin: bool = False) -> EmailUser:
    """Insert an EmailUser row and return it (with the generated id)."""
    now = datetime.now(timezone.utc)
    user = EmailUser(
        email=email,
        password_hash="hash",  # pragma: allowlist secret
        full_name="Mint Target",
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


def _add_team_with_member(db, team_id: str, user_email: str) -> EmailTeam:
    """Insert a non-personal team plus an active membership for the user."""
    team = EmailTeam(id=team_id, name=f"Team {team_id}", slug=f"team-{team_id}", created_by=user_email, is_personal=False, visibility="private")
    db.add(team)
    db.add(EmailTeamMember(id=str(uuid.uuid4()), team_id=team_id, user_email=user_email, role="member", is_active=True, joined_at=datetime.now(timezone.utc)))
    db.commit()
    return team


def _assign_role(db, email: str, role_name: str) -> Role:
    """Create a global role and assign it to the user."""
    role = Role(name=role_name, description="test role", scope="global", permissions=["tools.read"], created_by=email, is_active=True)
    db.add(role)
    db.commit()
    db.refresh(role)
    db.add(UserRole(user_email=email, role_id=role.id, scope="global", granted_by=email, is_active=True))
    db.commit()
    return role


def _decode(raw_token: str) -> dict:
    """Verify and decode a gateway-signed JWT with the configured key."""
    secret = settings.jwt_secret_key
    if hasattr(secret, "get_secret_value"):
        secret = secret.get_secret_value()
    return jwt.decode(raw_token, secret, algorithms=[settings.jwt_algorithm], audience=settings.jwt_audience, issuer=settings.jwt_issuer)


def _principal(**overrides) -> VirtualPrincipal:
    """Verified trust principal as produced by extract_trusted_principal."""
    values = {
        "user_id": CALLER_ID,
        "email": CALLER_EMAIL,
        "full_name": "Trust Mint",
        "teams": ["team-a"],
        "roles": ["developer"],
        "is_admin": False,
    }
    values.update(overrides)
    return VirtualPrincipal(**values)


class TestMintTrustToken:
    """The mint_trust_token service method stamps server-authority claims."""

    @pytest.mark.asyncio
    async def test_stamps_trusted_marker_and_mapped_claims(self, monkeypatch, service):
        """Minted token: token_use "trusted", mapped claims, jti present."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        principal = _principal(is_admin=True)

        raw_token = await service.mint_trust_token(principal, settings)

        payload = _decode(raw_token)
        assert payload["token_use"] == "trusted"
        assert payload[settings.jwt_claim_user_id] == CALLER_ID
        assert payload[settings.jwt_claim_teams] == ["team-a"]
        assert payload[settings.jwt_claim_roles] == ["developer"]
        assert payload[settings.jwt_claim_admin] is True
        assert payload[settings.jwt_claim_email] == CALLER_EMAIL
        assert payload["jti"]  # Configured revocation claim present.

    @pytest.mark.asyncio
    async def test_minted_token_passes_dispatch_eligibility(self, monkeypatch, service, db):
        """The minted token authenticates through the B.1 trust dispatch branch."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        import contextlib  # pylint: disable=import-outside-toplevel

        session_test = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr("mcpgateway.auth.SessionLocal", session_test)

        @contextlib.contextmanager
        def _fresh_db_session():
            session = session_test()
            try:
                yield session
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _fresh_db_session)

        raw_token = await service.mint_trust_token(_principal(), settings)

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw_token)  # pragma: allowlist secret
        request = SimpleNamespace(state=SimpleNamespace())
        with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.user_id == CALLER_ID
        assert user.token_use == "trusted"
        assert request.state.token_use == "trusted"

    @pytest.mark.asyncio
    async def test_sub_equals_inbound_user_id_no_act_as(self, monkeypatch, service):
        """Minted sub equals the verified principal's user_id; identity cannot drift."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        principal = _principal(user_id="verified-user-1", email="someone.else@example.com")

        raw_token = await service.mint_trust_token(principal, settings)

        payload = _decode(raw_token)
        assert payload["sub"] == "verified-user-1"
        assert payload[settings.jwt_claim_user_id] == "verified-user-1"

    @pytest.mark.asyncio
    async def test_no_catalog_row_inserted(self, monkeypatch, service, db):
        """Trust tokens are ephemeral: minting writes no email_api_tokens row."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")

        await service.mint_trust_token(_principal(), settings)

        assert db.query(EmailApiToken).count() == 0


class TestTrustMintEndpoint:
    """POST /admin/tokens/trust: admin-only mint with server-derived claims."""

    def _admin_user(self):
        return {
            "email": ADMIN_EMAIL,
            "is_admin": True,
            "token_teams": None,
            "permissions": ["*"],
            "auth_method": "jwt",
        }

    @pytest.mark.asyncio
    async def test_admin_mints_for_db_backed_user(self, monkeypatch, service, db):
        """Admin mints for a DB-backed user: trusted token with server-derived claims."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        target = _add_user(db, TARGET_EMAIL, is_admin=False)
        _add_team_with_member(db, "team-b", TARGET_EMAIL)
        _assign_role(db, TARGET_EMAIL, "developer")

        body = TrustTokenMintRequest.model_validate(
            {
                "user_email": TARGET_EMAIL,
                # Caller-supplied claim fields: accepted but ignored.
                "teams": ["team-evil"],
                "roles": ["platform_admin"],
                "is_admin": True,
            }
        )
        response = await create_trust_token(body=body, current_user=self._admin_user(), db=db)

        payload = _decode(response.access_token)
        assert response.user_id == str(target.id)
        assert payload["token_use"] == "trusted"
        assert payload["sub"] == str(target.id)
        assert payload[settings.jwt_claim_admin] is False  # DB row wins over body.
        assert payload[settings.jwt_claim_teams] == ["team-b"]  # DB membership wins.
        assert payload[settings.jwt_claim_roles] == ["developer"]  # DB roles win.

    @pytest.mark.asyncio
    async def test_non_admin_rejected(self, monkeypatch, service, db):
        """A non-admin caller gets 403."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        _add_user(db, TARGET_EMAIL)
        non_admin = {"email": CALLER_EMAIL, "is_admin": False, "permissions": ["tokens.create"], "auth_method": "jwt"}

        with pytest.raises(HTTPException) as exc_info:
            await create_trust_token(body=TrustTokenMintRequest(user_email=TARGET_EMAIL), current_user=non_admin, db=db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_trust_only_target_rejected(self, monkeypatch, service, db):
        """A target with no email_users row gets 403 with the documented message."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")

        with pytest.raises(HTTPException) as exc_info:
            await create_trust_token(body=TrustTokenMintRequest(user_email="ghost@example.com"), current_user=self._admin_user(), db=db)

        assert exc_info.value.status_code == 403
        assert "Token minting is disabled for trust-only principals" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_act_as_subject_rejected(self, monkeypatch, service, db):
        """A body naming a sub other than the target's canonical user_id is rejected."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        target = _add_user(db, TARGET_EMAIL)

        body = TrustTokenMintRequest.model_validate({"user_email": TARGET_EMAIL, "sub": "someone-else"})
        with pytest.raises(HTTPException) as exc_info:
            await create_trust_token(body=body, current_user=self._admin_user(), db=db)

        assert exc_info.value.status_code == 403
        assert target.id != "someone-else"  # Control: the named sub differs.
