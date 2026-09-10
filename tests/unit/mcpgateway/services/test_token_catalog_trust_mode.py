# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_catalog_trust_mode.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Mint-path decisions for the API-token catalog in JWT trust mode (#5904).

The B.2 feature-mode matrix (docs/docs/architecture/auth-feature-mode-matrix.md)
pins the API-token catalog row: DB-backed principals mint normally; trust-only
principals (no email_users row) get an explicit documented error, never a
500/IntegrityError. Claims in minted tokens derive from server-side authority
only, and minted ``sub`` always equals the target row's canonical user_id.
"""

# Standard
from datetime import datetime, timezone
import uuid

# Third-Party
import jwt
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser
from mcpgateway.services.token_catalog_service import TokenCatalogService

CALLER_EMAIL = "caller@example.com"
TARGET_EMAIL = "target@example.com"
GHOST_EMAIL = "ghost@example.com"

TRUST_ONLY_MESSAGE = "Token minting is disabled for trust-only principals. Create a local user account first."


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
        full_name="Test User",
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
    now = datetime.now(timezone.utc)
    db.add(EmailTeamMember(id=str(uuid.uuid4()), team_id=team_id, user_email=user_email, role="member", is_active=True, joined_at=now))
    db.commit()
    return team


def _decode(raw_token: str) -> dict:
    """Verify and decode a gateway-signed JWT with the configured key."""
    secret = settings.jwt_secret_key
    if hasattr(secret, "get_secret_value"):
        secret = secret.get_secret_value()
    return jwt.decode(raw_token, secret, algorithms=[settings.jwt_algorithm], audience=settings.jwt_audience, issuer=settings.jwt_issuer)


class TestTrustOnlyPrincipalMinting:
    """Test A: a trust-only principal (no email_users row) cannot mint."""

    @pytest.mark.asyncio
    async def test_create_token_trust_only_principal_gets_documented_error(self, monkeypatch, service):
        """Trust mode ON + no EmailUser row -> documented error, never 500/IntegrityError."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")

        with pytest.raises(ValueError, match="Token minting is disabled for trust-only principals") as exc_info:
            await service.create_token(user_email=GHOST_EMAIL, name="ghost-token", caller_email=GHOST_EMAIL)

        assert str(exc_info.value) == TRUST_ONLY_MESSAGE

    @pytest.mark.asyncio
    async def test_create_token_unknown_user_default_mode_keeps_legacy_error(self, monkeypatch, service):
        """Default mode is unchanged: unknown user -> the legacy not-found error."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")

        with pytest.raises(ValueError, match="User not found"):
            await service.create_token(user_email=GHOST_EMAIL, name="ghost-token")


class TestDbBackedPrincipalMinting:
    """Test B: a DB-backed principal mints API tokens with server-derived claims."""

    @pytest.mark.asyncio
    async def test_create_token_mints_api_token_with_db_derived_claims(self, monkeypatch, service, db):
        """Minted JWT: token_use "api", is_admin from the DB row, sub == user.id."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        user = _add_user(db, CALLER_EMAIL, is_admin=True)

        _, raw_token = await service.create_token(
            user_email=CALLER_EMAIL,
            name="self-token",
            expires_in_days=30,
            is_admin=False,  # Caller flag must not override the DB row.
            caller_email=CALLER_EMAIL,
        )

        payload = _decode(raw_token)
        assert payload["token_use"] == "api"
        assert payload["sub"] == str(user.id)
        assert payload["user"]["is_admin"] is True  # From the DB row, not the caller flag.


class TestNoActAs:
    """Test C: a mint request naming a different sub than the caller is rejected."""

    @pytest.mark.asyncio
    async def test_create_token_for_other_user_rejected_in_trust_mode(self, monkeypatch, service, db):
        """Trust mode ON: non-admin caller minting for another user -> clear error."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        _add_user(db, CALLER_EMAIL)
        target = _add_user(db, TARGET_EMAIL)

        with pytest.raises(ValueError, match="requires platform admin"):
            await service.create_token(
                user_email=TARGET_EMAIL,
                name="act-as-token",
                caller_email=CALLER_EMAIL,
                is_admin=False,
                caller_permissions=["tokens.create"],
            )

        # The target row's canonical id must never reach a token minted this way.
        assert target.id  # Control: the target has a distinct canonical user_id.

    @pytest.mark.asyncio
    async def test_default_mode_service_delegation_behavior_unchanged(self, monkeypatch, service, db):
        """Default mode: the service-layer delegation path is not gated by the trust guard."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        _add_user(db, CALLER_EMAIL)
        _add_user(db, TARGET_EMAIL)

        _, raw_token = await service.create_token(
            user_email=TARGET_EMAIL,
            name="delegated-token",
            expires_in_days=30,
            caller_email=CALLER_EMAIL,
            is_admin=False,
            caller_permissions=["tokens.create"],
        )

        assert _decode(raw_token)["token_use"] == "api"


class TestCallerSuppliedClaimsIgnored:
    """Test D: caller-supplied teams/is_admin values never enter minted claims."""

    @pytest.mark.asyncio
    async def test_create_token_claims_derive_from_server_authority_only(self, monkeypatch, service, db):
        """Minted claims come from the DB row and team_id param, not caller values."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        user = _add_user(db, CALLER_EMAIL, is_admin=False)
        _add_team_with_member(db, "team-a", CALLER_EMAIL)

        _, raw_token = await service.create_token(
            user_email=CALLER_EMAIL,
            name="scoped-token",
            expires_in_days=30,
            team_id="team-a",
            is_admin=True,  # Caller-supplied admin flag: must not leak into claims.
            caller_permissions=["*"],
            caller_token_teams=["team-evil"],  # Caller narrowing: must not leak.
            caller_token_teams_provided=True,
            caller_email=CALLER_EMAIL,
        )

        payload = _decode(raw_token)
        assert payload["user"]["is_admin"] is False  # DB row wins over the caller flag.
        assert payload["teams"] == ["team-a"]  # team_id param wins over caller teams.
        assert payload["sub"] == str(user.id)
