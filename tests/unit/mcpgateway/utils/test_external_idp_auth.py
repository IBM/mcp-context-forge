# -*- coding: utf-8 -*-
"""Tests for external OIDC bearer token API auth (issue #3567)."""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.config import Settings


def test_sso_api_token_auth_disabled_by_default():
    s = Settings()
    assert s.sso_api_token_auth_enabled is False


def test_ssoprovider_has_api_auth_columns():
    # First-Party
    from mcpgateway.db import SSOProvider

    cols = SSOProvider.__table__.columns.keys()
    assert "trusted_for_api_auth" in cols
    assert "api_audience" in cols


def test_sso_provider_schema_exposes_api_auth_fields():
    # First-Party
    from mcpgateway.routers.sso import SSOProviderCreateRequest, SSOProviderUpdateRequest

    assert "trusted_for_api_auth" in SSOProviderCreateRequest.model_fields
    assert "api_audience" in SSOProviderCreateRequest.model_fields
    assert "trusted_for_api_auth" in SSOProviderUpdateRequest.model_fields
    assert "api_audience" in SSOProviderUpdateRequest.model_fields


def test_api_trust_requires_audience_on_create():
    # Third-Party
    import pytest

    # First-Party
    from mcpgateway.routers.sso import SSOProviderCreateRequest

    with pytest.raises(ValueError, match="api_audience is required"):
        SSOProviderCreateRequest(
            id="kc",
            name="kc",
            display_name="KC",
            provider_type="oidc",
            client_id="c",
            client_secret="s",
            authorization_url="https://idp/authorize",
            token_url="https://idp/token",
            userinfo_url="https://idp/userinfo",
            trusted_for_api_auth=True,
            api_audience=None,
        )


def test_api_trust_requires_audience_on_update():
    # Third-Party
    import pytest

    # First-Party
    from mcpgateway.routers.sso import SSOProviderUpdateRequest

    with pytest.raises(ValueError, match="api_audience is required"):
        SSOProviderUpdateRequest(trusted_for_api_auth=True, api_audience=None)


def test_api_trust_with_audience_succeeds():
    # First-Party
    from mcpgateway.routers.sso import SSOProviderCreateRequest

    req = SSOProviderCreateRequest(
        id="kc",
        name="kc",
        display_name="KC",
        provider_type="oidc",
        client_id="c",
        client_secret="s",
        authorization_url="https://idp/authorize",
        token_url="https://idp/token",
        userinfo_url="https://idp/userinfo",
        trusted_for_api_auth=True,
        api_audience="api://my-api",
    )
    assert req.api_audience == "api://my-api"


def _fake_provider(issuer, enabled=True, trusted=True):
    p = MagicMock()
    p.issuer = issuer
    p.is_enabled = enabled
    p.trusted_for_api_auth = trusted
    return p


def _mock_db(providers):
    """db where the .filter().all() map-load returns `providers` and the
    .filter().first() PK lookup returns the first provider (id match)."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = providers
    db.query.return_value.filter.return_value.first.return_value = providers[0] if providers else None
    return db


def _scan_count(db):
    """How many times the expensive .filter().all() table scan ran."""
    return db.query.return_value.filter.return_value.all.call_count


def test_resolve_trusted_provider_matches_issuer():
    # First-Party
    from mcpgateway.services import sso_service

    sso_service.invalidate_trusted_provider_cache()
    prov = _fake_provider("https://kc.example.com/realms/m")
    prov.id = "kc"
    db = _mock_db([prov])
    # trailing slash on the token's iss must still match
    result = sso_service.resolve_trusted_provider_by_issuer("https://kc.example.com/realms/m/", db)
    assert result is prov


def test_resolve_trusted_provider_unknown_issuer_returns_none():
    # First-Party
    from mcpgateway.services import sso_service

    sso_service.invalidate_trusted_provider_cache()
    db = _mock_db([])
    assert sso_service.resolve_trusted_provider_by_issuer("https://evil.example.com", db) is None


def test_resolver_with_no_providers_does_not_rescan():
    """Empty trusted-provider map must still be cached (no per-request rescan when none configured)."""
    # First-Party
    from mcpgateway.services import sso_service

    sso_service.invalidate_trusted_provider_cache()
    db = _mock_db([])
    assert sso_service.resolve_trusted_provider_by_issuer("https://kc.example.com/realms/m", db) is None
    db.reset_mock()
    assert sso_service.resolve_trusted_provider_by_issuer("https://kc.example.com/realms/m", db) is None
    assert _scan_count(db) == 0


def test_resolver_caches_scan_and_skips_unknown_issuer_db_hit():
    """P1: the expensive table scan runs once within TTL; an UNKNOWN issuer
    served from the cached map costs ZERO DB queries (DoS-amplification fix)."""
    # First-Party
    from mcpgateway.services import sso_service

    sso_service.invalidate_trusted_provider_cache()
    prov = _fake_provider("https://kc.example.com/realms/m")
    prov.id = "kc"
    db = _mock_db([prov])
    sso_service.resolve_trusted_provider_by_issuer("https://kc.example.com/realms/m", db)
    db.reset_mock()
    # repeat known-issuer lookup -> no re-scan (cache hit), only the cheap PK fetch
    sso_service.resolve_trusted_provider_by_issuer("https://kc.example.com/realms/m", db)
    assert _scan_count(db) == 0
    # unknown issuer within TTL -> not in cached map -> returns None with NO db query at all
    db.reset_mock()
    assert sso_service.resolve_trusted_provider_by_issuer("https://evil.example.com", db) is None
    assert db.query.call_count == 0


def test_resolver_cache_invalidation_forces_rescan():
    """P1: invalidation forces a fresh table scan (e.g. after provider edit)."""
    # First-Party
    from mcpgateway.services import sso_service

    sso_service.invalidate_trusted_provider_cache()
    prov = _fake_provider("https://kc.example.com/realms/m")
    prov.id = "kc"
    db = _mock_db([prov])
    sso_service.resolve_trusted_provider_by_issuer("https://kc.example.com/realms/m", db)
    db.reset_mock()
    db.query.return_value.filter.return_value.all.return_value = [prov]
    db.query.return_value.filter.return_value.first.return_value = prov
    sso_service.invalidate_trusted_provider_cache()
    sso_service.resolve_trusted_provider_by_issuer("https://kc.example.com/realms/m", db)
    assert _scan_count(db) == 1  # re-scanned after invalidation


@pytest.mark.asyncio
async def test_verify_external_idp_token_unknown_issuer(monkeypatch):
    # Third-Party
    import jwt as pyjwt

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    # token with an issuer that resolves to no provider
    token = pyjwt.encode({"iss": "https://evil.example.com", "sub": "x"}, "k", algorithm="HS256")
    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: None)
    db = MagicMock()
    result = await vc.verify_external_idp_token(token, db)
    assert result == (None, None)


@pytest.mark.asyncio
async def test_verify_external_idp_token_valid(monkeypatch):
    # Third-Party
    import jwt as pyjwt

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    token = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "agent"}, "k", algorithm="HS256")
    prov = _fake_provider("https://kc/realms/m")
    prov.api_audience = "api://my-app"
    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: prov)

    async def fake_verify(tok, authorization_servers, *, expected_audience=None):
        assert authorization_servers == ["https://kc/realms/m"]
        assert expected_audience == "api://my-app"
        return {"iss": "https://kc/realms/m", "sub": "agent"}

    monkeypatch.setattr(vc, "verify_oauth_access_token", fake_verify)
    db = MagicMock()
    claims, returned_prov = await vc.verify_external_idp_token(token, db)
    assert claims["sub"] == "agent"
    assert returned_prov is prov


@pytest.mark.asyncio
async def test_verify_external_idp_token_no_issuer_claim(monkeypatch):
    # Third-Party
    import jwt as pyjwt

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    token = pyjwt.encode({"sub": "x"}, "k", algorithm="HS256")
    db = MagicMock()
    assert await vc.verify_external_idp_token(token, db) == (None, None)


@pytest.mark.asyncio
async def test_verify_external_idp_token_non_string_issuer(monkeypatch):
    # Standard
    # iss as a list is valid JWT JSON but must not crash the resolver.
    # PyJWT's encode() rejects non-string "iss" claims, so build the token
    # manually (header.payload.signature with arbitrary base64url segments)
    # to simulate an attacker-controlled unverified token.
    import base64
    import json

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps({"iss": ["https://evil.example.com"], "sub": "x"}).encode())
    token = f"{header}.{payload}.fakesig"

    db = MagicMock()
    assert await vc.verify_external_idp_token(token, db) == (None, None)


@pytest.mark.asyncio
async def test_verify_external_idp_token_provider_missing_issuer(monkeypatch):
    # Third-Party
    import jwt as pyjwt

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    token = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "x"}, "k", algorithm="HS256")
    prov = _fake_provider("https://kc/realms/m")
    prov.issuer = None
    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: prov)
    db = MagicMock()
    assert await vc.verify_external_idp_token(token, db) == (None, None)


@pytest.mark.asyncio
async def test_verify_external_idp_token_verification_fails(monkeypatch):
    # Third-Party
    import jwt as pyjwt

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    token = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "x"}, "k", algorithm="HS256")
    prov = _fake_provider("https://kc/realms/m")
    prov.api_audience = "api://my-app"
    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: prov)

    async def fake_verify(tok, authorization_servers, *, expected_audience=None):
        return None

    monkeypatch.setattr(vc, "verify_oauth_access_token", fake_verify)
    db = MagicMock()
    assert await vc.verify_external_idp_token(token, db) == (None, None)


@pytest.mark.asyncio
async def test_build_external_identity_uses_session_token_use_and_db_admin(monkeypatch):
    """C1 + C2: token_use must be 'session'; is_admin from DB user, not claim."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "keycloak"
    claims = {"iss": "https://kc/realms/m", "sub": "agent", "email": "agent@corp.com"}

    svc = MagicMock()
    # Claim maps to admin-looking groups...
    svc._normalize_user_info.return_value = {"email": "agent@corp.com", "is_admin": True}

    async def fake_auth(user_info):
        return "an-internal-jwt-token-string"  # C3: returns a TOKEN, not an email

    svc.authenticate_or_create_user = fake_auth
    # ...but the DB user is NOT admin -> payload.is_admin must be False (C2)
    db_user = MagicMock()
    db_user.is_admin = False

    async def fake_get_user(email):
        return db_user

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)

    captured = {}

    async def fake_resolve(payload, email, user_info, **kw):
        captured["args"] = (payload, email, user_info)
        return ["team-a"]  # non-admin DB teams

    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", fake_resolve)

    db = MagicMock()
    payload = await vc.build_external_identity(prov, claims, "rawtoken", db)
    assert payload["sub"] == "agent@corp.com"
    assert payload["email"] == "agent@corp.com"
    assert payload["token_use"] == "session"  # C1
    assert payload["source"] == "external_idp"  # audit only
    assert payload["is_admin"] is False  # C2: DB authority, not claim
    assert payload["teams"] == ["team-a"]
    assert payload["auth_provider"] == "keycloak"
    # C2: resolve_session_teams called with the DB user object, signature (payload, email, user_info)
    assert captured["args"][1] == "agent@corp.com"
    assert captured["args"][2] is db_user


@pytest.mark.asyncio
async def test_build_external_identity_unknown_user_returns_none(monkeypatch):
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "keycloak"
    svc = MagicMock()
    svc._normalize_user_info.return_value = {"email": "ghost@corp.com", "is_admin": False}

    async def fake_auth(user_info):
        return None  # provisioning rejected (auto_create off / unverified / untrusted domain)

    svc.authenticate_or_create_user = fake_auth
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)
    db = MagicMock()
    payload = await vc.build_external_identity(prov, {"sub": "ghost"}, "raw", db)
    assert payload is None


@pytest.mark.asyncio
async def test_build_external_identity_empty_email_returns_none(monkeypatch):
    """If user_info has no usable email after normalization, fail closed."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "keycloak"
    svc = MagicMock()
    svc._normalize_user_info.return_value = {"email": "   ", "is_admin": False}

    async def fake_auth(user_info):
        return "token-string"

    svc.authenticate_or_create_user = fake_auth
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)
    db = MagicMock()
    payload = await vc.build_external_identity(prov, {"iss": "https://kc/realms/m"}, "raw", db)
    assert payload is None


@pytest.mark.asyncio
async def test_build_external_identity_missing_db_user_returns_none(monkeypatch):
    """Provisioning succeeded but the user can't be found afterward -- fail closed."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "keycloak"
    svc = MagicMock()
    svc._normalize_user_info.return_value = {"email": "agent@corp.com", "is_admin": False}

    async def fake_auth(user_info):
        return "token-string"

    svc.authenticate_or_create_user = fake_auth

    async def fake_get_user(email):
        return None

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)
    db = MagicMock()
    payload = await vc.build_external_identity(prov, {"iss": "https://kc/realms/m"}, "raw", db)
    assert payload is None


@pytest.mark.asyncio
async def test_service_principal_synthetic_identity(monkeypatch):
    """H1: a clientless token (no email) provisions a synthetic service-principal."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "keycloak"
    # client_credentials token: sub == azp, no email/email_verified
    claims = {"iss": "https://kc/realms/m", "sub": "svc-client-123", "azp": "svc-client-123"}

    seen = {}

    def fake_synth(provider, claims_in):
        seen["called"] = True
        return {
            "email": "svc-svc-client-123@keycloak.service.local",
            "email_verified": True,
            "full_name": "service:svc-client-123",
            "provider": provider.id,
            "is_admin": False,
        }

    monkeypatch.setattr(vc, "_synthetic_service_principal_user_info", fake_synth)

    svc = MagicMock()

    async def fake_auth(user_info):
        # human-path gate is satisfied by the synthetic verified email
        assert user_info["email"].endswith(".service.local")
        return "token"

    svc.authenticate_or_create_user = fake_auth
    du = MagicMock()
    du.is_admin = False

    async def fake_get_user(email):
        return du

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)

    async def fake_resolve(payload, email, user_info, **kw):
        return []

    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", fake_resolve)

    db = MagicMock()
    payload = await vc.build_external_identity(prov, claims, "raw", db)
    assert seen.get("called") is True
    assert payload["sub"] == "svc-svc-client-123@keycloak.service.local"
    assert payload["token_use"] == "session"
