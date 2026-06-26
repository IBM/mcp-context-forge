# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_external_idp_auth_integration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for external IdP bearer auth (issue #3567) -- no crypto mocks.

Tasks 5-8 mock ``verify_oauth_access_token``/JWKS and ``resolve_session_teams``, so the two
security-critical mechanisms (real JWKS signature validation, real DB-authority team
resolution) are never exercised through our wiring. These tests remove those mocks so
findings G1/G2/G4/G6 (and invariants C1/C2) are proven against real code.
"""

# Standard
import time
from unittest.mock import MagicMock, patch
import uuid

# Third-Party
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
import jwt as pyjwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser


@pytest.fixture
def rsa_keypair():
    """Generate an RSA keypair used to sign test JWTs."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


# ---------------------------------------------------------------------------
# G1 / G6: real signature, audience, and issuer validation through
# verify_external_idp_token -> verify_oauth_access_token (no jwt.decode mocking).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g1_real_signature_valid_and_tampered(monkeypatch, rsa_keypair):
    """G1: a real RS256-signed token verifies; a token re-signed with a different key fails."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    issuer = "https://kc.example.com/realms/m"
    aud = "mcp-gateway"
    now = int(time.time())
    claims = {"iss": issuer, "sub": "agent", "aud": aud, "exp": now + 300, "iat": now}
    token = pyjwt.encode(claims, rsa_keypair, algorithm="RS256")

    prov = MagicMock()
    prov.issuer = issuer
    prov.api_audience = aud
    prov.is_enabled = True
    prov.trusted_for_api_auth = True
    prov.id = "kc"
    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: prov)

    # Patch ONLY discovery + JWKS key resolution; the signature/aud/exp/iss checks run for real.
    async def fake_discovery(iss):
        return {"jwks_uri": f"{issuer}/protocol/openid-connect/certs", "issuer": issuer}

    monkeypatch.setattr(vc, "_discover_oidc_metadata", fake_discovery)

    class FakeKey:
        key = rsa_keypair.public_key()

    class FakeJWKClient:
        def __init__(self, uri):
            pass

        def get_signing_key_from_jwt(self, tok):
            return FakeKey()

    monkeypatch.setattr(vc, "_NoRedirectPyJWKClient", FakeJWKClient)
    vc._oauth_jwks_client_cache.clear()

    db = MagicMock()
    good_claims, got_prov = await vc.verify_external_idp_token(token, db)
    assert good_claims is not None
    assert good_claims["sub"] == "agent"
    assert got_prov is prov

    # Tampered token (re-signed with a DIFFERENT key) must fail real signature verify.
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad_token = pyjwt.encode(claims, other, algorithm="RS256")

    class FakeJWKClientWrongKey:
        """Simulates JWKS lookup still returning the ORIGINAL provider key.

        The signing key resolution is independent of the token's actual
        signature -- the JWKS endpoint serves the provider's published keys
        regardless of what signed the inbound token. ``jwt.decode`` is what
        must reject the mismatch.
        """

        def __init__(self, uri):
            pass

        def get_signing_key_from_jwt(self, tok):
            return FakeKey()

    monkeypatch.setattr(vc, "_NoRedirectPyJWKClient", FakeJWKClientWrongKey)
    vc._oauth_jwks_client_cache.clear()

    bad_claims, _ = await vc.verify_external_idp_token(bad_token, db)
    assert bad_claims is None


@pytest.mark.asyncio
async def test_g6_wrong_audience_rejected(monkeypatch, rsa_keypair):
    """G6/H2: a real, validly-signed token whose aud != provider.api_audience is rejected."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    issuer = "https://kc.example.com/realms/m"
    now = int(time.time())
    token = pyjwt.encode(
        {"iss": issuer, "sub": "a", "aud": "some-other-app", "exp": now + 300, "iat": now},
        rsa_keypair,
        algorithm="RS256",
    )
    prov = MagicMock()
    prov.issuer = issuer
    prov.api_audience = "mcp-gateway"
    prov.is_enabled = True
    prov.trusted_for_api_auth = True
    prov.id = "kc"
    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: prov)

    async def fake_discovery(iss):
        return {"jwks_uri": f"{issuer}/certs", "issuer": issuer}

    monkeypatch.setattr(vc, "_discover_oidc_metadata", fake_discovery)

    class FakeKey:
        key = rsa_keypair.public_key()

    class FakeJWKClient:
        def __init__(self, uri):
            pass

        def get_signing_key_from_jwt(self, tok):
            return FakeKey()

    monkeypatch.setattr(vc, "_NoRedirectPyJWKClient", FakeJWKClient)
    vc._oauth_jwks_client_cache.clear()

    claims, prov_out = await vc.verify_external_idp_token(token, MagicMock())
    assert claims is None  # wrong aud -> rejected
    assert prov_out is None


# ---------------------------------------------------------------------------
# Shared in-memory DB fixture for G2 / G4: real resolve_session_teams against
# a real SQLite-backed mcpgateway.db.SessionLocal.
# ---------------------------------------------------------------------------


class _SeedUsers:
    """Helper exposing post-seed mutations (e.g. deactivation) against the test DB."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def deactivate(self, email: str) -> None:
        with self._session_factory() as db:
            user = db.query(EmailUser).filter(EmailUser.email == email).one()
            user.is_active = False
            db.add(user)
            db.commit()


@pytest.fixture
def seeded_db(monkeypatch):
    """Bind mcpgateway.db.SessionLocal (and mcpgateway.auth.SessionLocal) to an
    in-memory SQLite DB seeded per the AGENTS.md session-token resolution matrix:

    - admin@corp.com: is_admin=True, no team memberships.
    - member@corp.com: is_admin=False, member of "team-x".
    - lonely@corp.com: is_admin=False, no team memberships (provisioned, teamless).

    Returns the bound session factory plus a _SeedUsers helper for post-seed mutations.
    """
    # First-Party
    import mcpgateway.auth as auth_mod
    import mcpgateway.db as db_mod

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    monkeypatch.setattr(auth_mod, "SessionLocal", TestSessionLocal, raising=False)

    # Disable the auth cache so DB mutations (e.g. deactivation) take effect immediately
    # without waiting on TTLs, and so resolve_session_teams hits the real DB.
    # First-Party
    from mcpgateway.cache.auth_cache import auth_cache

    monkeypatch.setattr(auth_cache, "_enabled", False, raising=False)

    with TestSessionLocal() as db:
        admin = EmailUser(email="admin@corp.com", password_hash="x", full_name="Admin", is_admin=True, is_active=True)
        member = EmailUser(email="member@corp.com", password_hash="x", full_name="Member", is_admin=False, is_active=True)
        lonely = EmailUser(email="lonely@corp.com", password_hash="x", full_name="Lonely", is_admin=False, is_active=True)
        db.add_all([admin, member, lonely])
        db.flush()

        team_x_id = str(uuid.uuid4())
        team_x = EmailTeam(id=team_x_id, name="Team X", slug="team-x", created_by="admin@corp.com", is_personal=False)
        db.add(team_x)
        db.flush()

        membership = EmailTeamMember(id=str(uuid.uuid4()), team_id=team_x_id, user_email="member@corp.com", role="member", is_active=True)
        db.add(membership)
        db.commit()

    return TestSessionLocal, _SeedUsers(TestSessionLocal), team_x_id


# ---------------------------------------------------------------------------
# G2 / C1 / C2: build_external_identity with REAL resolve_session_teams.
# ---------------------------------------------------------------------------


async def _build_identity(vc, prov, email, db):
    """Drive build_external_identity with provisioning pre-satisfied (user already
    seeded), so only normalization + the REAL resolve_session_teams/DB lookups run.
    """
    claims = {"iss": prov.issuer, "sub": email, "email": email, "email_verified": True}
    with patch.object(vc, "_get_sso_service") as gss:
        svc = gss.return_value
        svc._normalize_user_info.return_value = {"email": email, "email_verified": True}

        async def ok(_user_info):
            return "tok"

        svc.authenticate_or_create_user = ok

        # First-Party
        from mcpgateway.services.sso_service import SSOService

        svc.auth_service = SSOService(db).auth_service
        return await vc.build_external_identity(prov, claims, "raw", db)


@pytest.mark.asyncio
async def test_g2_real_team_resolution(seeded_db):
    """G2/C1/C2: build_external_identity resolves teams via the REAL resolve_session_teams,
    asserting the AGENTS.md session-token matrix outcomes against a real in-memory DB.
    """
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    TestSessionLocal, _seed_users, team_x_id = seeded_db

    prov = MagicMock()
    prov.id = "kc"
    prov.issuer = "https://kc/realms/m"

    with TestSessionLocal() as db:
        # Admin -> teams None (DB-authority bypass), is_admin True
        p_admin = await _build_identity(vc, prov, "admin@corp.com", db)
        assert p_admin is not None
        assert p_admin["is_admin"] is True
        assert p_admin["teams"] is None
        assert p_admin["token_use"] == "session"

        # Member -> teams == DB membership, is_admin False
        p_member = await _build_identity(vc, prov, "member@corp.com", db)
        assert p_member is not None
        assert p_member["is_admin"] is False
        assert team_x_id in (p_member["teams"] or [])

        # Teamless provisioned user -> [] (public-only), NOT bypass
        p_lonely = await _build_identity(vc, prov, "lonely@corp.com", db)
        assert p_lonely is not None
        assert p_lonely["teams"] == []
        assert p_lonely["is_admin"] is False


# ---------------------------------------------------------------------------
# G4: end-to-end through require_auth + active-user enforcement.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g4_require_auth_external_then_deactivated(seeded_db, monkeypatch):
    """G4: an external-IdP-derived session payload authenticates via require_auth while the
    user is active; after the user is deactivated in the DB, the next call 401s via
    _enforce_revocation_and_active_user (real DB lookup, no mocked active-user check).
    """
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    _TestSessionLocal, seed_users, team_x_id = seeded_db

    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc.settings, "auth_required", True)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True)

    async def fake_maybe(token, request):
        return {
            "sub": "member@corp.com",
            "email": "member@corp.com",
            "token_use": "session",
            "source": "external_idp",
            "is_admin": False,
            "teams": [team_x_id],
            "token": token,
        }

    monkeypatch.setattr(vc, "_maybe_verify_external", fake_maybe)

    req = Request(scope={"type": "http", "headers": []})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="ext-token")  # pragma: allowlist secret
    result = await vc.require_auth(request=req, credentials=creds, jwt_token=None)
    assert result["sub"] == "member@corp.com"

    # Deactivate the user in the real DB, then assert the next call 401s via the
    # real _enforce_revocation_and_active_user -> _get_user_by_email_sync path.
    seed_users.deactivate("member@corp.com")

    with pytest.raises(vc.HTTPException) as exc:
        await vc.require_auth(
            request=Request(scope={"type": "http", "headers": []}),
            credentials=creds,
            jwt_token=None,
        )
    assert exc.value.status_code == 401
