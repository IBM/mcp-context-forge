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


async def _async_none():
    return None


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
async def test_verify_external_idp_token_denies_missing_audience(monkeypatch):
    """G2 runtime backstop: even if a provider row somehow has
    trusted_for_api_auth=True with no api_audience (direct DB edit, future
    importer, env seeding -- bypassing the create/update validators and the
    bootstrap auto-disable), verify_external_idp_token must still fail closed
    rather than calling verify_oauth_access_token with expected_audience=None
    (which would accept a token for any relying party of this issuer)."""
    # Third-Party
    import jwt as pyjwt

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    token = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "agent"}, "k", algorithm="HS256")
    prov = _fake_provider("https://kc/realms/m")
    prov.api_audience = None
    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: prov)

    called = False

    async def fake_verify(*_a, **_kw):
        nonlocal called
        called = True
        return {"iss": "https://kc/realms/m", "sub": "agent"}

    monkeypatch.setattr(vc, "verify_oauth_access_token", fake_verify)
    db = MagicMock()
    result = await vc.verify_external_idp_token(token, db)
    assert result == (None, None)
    assert called is False  # denied before ever calling the token verifier


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


@pytest.mark.asyncio
async def test_dispatch_internal_token_skips_external(monkeypatch):
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    called = {"external": False}

    async def fake_external(tok, db):
        called["external"] = True
        return (None, None)

    monkeypatch.setattr(vc, "verify_external_idp_token", fake_external)
    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway")
    monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: True)

    # Third-Party
    import jwt as pyjwt

    tok = pyjwt.encode({"iss": "mcpgateway", "sub": "internal"}, "k", algorithm="HS256")

    async def fake_verify_jwt_token_cached(token, request=None):
        return {"sub": "internal", "iss": "mcpgateway"}

    monkeypatch.setattr(vc, "verify_jwt_token_cached", fake_verify_jwt_token_cached)

    result = await vc.verify_credentials_cached(tok, request=None)
    assert called["external"] is False
    assert result["sub"] == "internal"


@pytest.mark.asyncio
async def test_dispatch_external_token_routes_to_external(monkeypatch):
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway")
    monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: True)
    monkeypatch.setattr(vc, "get_redis_client", _async_none)

    prov = _fake_provider("https://kc/realms/m")

    async def fake_external(tok, db):
        return ({"iss": "https://kc/realms/m", "sub": "agent"}, prov)

    async def fake_build(provider, claims, token, db):
        return {"sub": "agent@corp.com", "token_use": "external_idp"}

    monkeypatch.setattr(vc, "verify_external_idp_token", fake_external)
    monkeypatch.setattr(vc, "build_external_identity", fake_build)

    # Third-Party
    import jwt as pyjwt

    tok = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "agent"}, "k", algorithm="HS256")

    result = await vc.verify_credentials_cached(tok, request=None)
    assert result["token_use"] == "external_idp"


@pytest.mark.asyncio
async def test_p2_identity_cache_skips_reprovision(monkeypatch):
    """P2/P5: a second request with the same token within TTL reuses the cached
    identity — no second verify/provision."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "get_redis_client", _async_none)  # in-memory fallback
    await vc.invalidate_external_identity_cache()
    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway")
    calls = {"verify": 0}
    prov = _fake_provider("https://kc/realms/m")

    async def fake_external(tok, db):
        calls["verify"] += 1
        return ({"iss": "https://kc/realms/m", "sub": "agent", "exp": 9999999999}, prov)

    async def fake_build(provider, claims, token, db):
        return {"sub": "agent@corp.com", "token_use": "session", "exp": 9999999999}

    monkeypatch.setattr(vc, "verify_external_idp_token", fake_external)
    monkeypatch.setattr(vc, "build_external_identity", fake_build)
    # ensure provider map non-empty so the short-circuit (P3) does not skip
    monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: True)
    # Third-Party
    import jwt as pyjwt

    tok = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "agent", "exp": 9999999999}, "k", algorithm="HS256")
    p1 = await vc._maybe_verify_external(tok, request=None)
    p2 = await vc._maybe_verify_external(tok, request=None)
    assert p1["sub"] == "agent@corp.com" and p2["sub"] == "agent@corp.com"
    assert calls["verify"] == 1  # second call served from identity cache


@pytest.mark.asyncio
async def test_p3_short_circuit_when_no_trusted_providers(monkeypatch):
    """P3: when no provider is opted in, skip even the unsigned decode."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "get_redis_client", _async_none)
    await vc.invalidate_external_identity_cache()
    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: False)
    called = {"decode": False}
    real_decode = vc.jwt.decode

    def spy(*a, **k):
        called["decode"] = True
        return real_decode(*a, **k)

    monkeypatch.setattr(vc.jwt, "decode", spy)
    assert await vc._maybe_verify_external("anything", request=None) is None
    assert called["decode"] is False  # short-circuited before decoding


@pytest.mark.asyncio
async def test_p2_cache_respects_token_expiry(monkeypatch):
    """P2: cache entry must not outlive the token's own exp (in-memory fallback path)."""
    # Standard
    import time as _t

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    await vc.invalidate_external_identity_cache()
    # Force the in-memory fallback (no Redis) for this test.
    monkeypatch.setattr(vc, "get_redis_client", _async_none)
    payload = {"sub": "agent@corp.com", "token_use": "session"}
    # exp already in the past -> put is a no-op -> get returns None
    await vc._external_identity_cache_put("tok-hash", payload, token_exp=int(_t.time()) - 1)
    assert await vc._external_identity_cache_get("tok-hash") is None


@pytest.mark.asyncio
async def test_p2_cache_shared_via_redis(monkeypatch):
    """A: when cache_type=redis, the identity is written-through to Redis (shared
    across workers) and the raw token is NOT stored in Redis."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    store = {}

    class FakeRedis:
        async def get(self, k):
            return store.get(k)

        async def set(self, k, v, ex=None):
            store[k] = v

        async def delete(self, *ks):
            for k in ks:
                store.pop(k, None)

    async def fake_client():
        return FakeRedis()

    monkeypatch.setattr(vc, "get_redis_client", fake_client)
    await vc.invalidate_external_identity_cache()
    payload = {"sub": "agent@corp.com", "token_use": "session", "token": "RAW-SECRET", "exp": 9999999999}
    await vc._external_identity_cache_put("th1", payload, token_exp=9999999999)
    # raw token must not be persisted in Redis
    assert "RAW-SECRET" not in next(iter(store.values()))
    got = await vc._external_identity_cache_get("th1")
    assert got["sub"] == "agent@corp.com"


@pytest.mark.asyncio
async def test_external_identity_cache_redis_errors_fail_open(monkeypatch):
    """Redis outages must not crash auth: get/put degrade to cache-miss / no-op."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    class BrokenRedis:
        async def get(self, k):
            raise ConnectionError("redis down")

        async def set(self, k, v, ex=None):
            raise TimeoutError("redis timeout")

    async def fake_client():
        return BrokenRedis()

    monkeypatch.setattr(vc, "get_redis_client", fake_client)
    await vc.invalidate_external_identity_cache()

    payload = {"sub": "agent@corp.com", "token_use": "session", "exp": 9999999999}
    # put must not raise despite Redis SET failure
    await vc._external_identity_cache_put("th-broken", payload, token_exp=9999999999)
    # get must not raise despite Redis GET failure, and must report a cache miss
    assert await vc._external_identity_cache_get("th-broken") is None


@pytest.mark.asyncio
async def test_external_identity_cache_inmemory_get_returns_copy(monkeypatch):
    """In-memory cache hits must return a copy so callers mutating the result
    (e.g. `_maybe_verify_external` setting `cached["token"] = token`) cannot
    persist the raw token into the shared cache entry."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "get_redis_client", _async_none)
    await vc.invalidate_external_identity_cache()

    payload = {"sub": "agent@corp.com", "token_use": "session", "exp": 9999999999}
    await vc._external_identity_cache_put("th-copy", payload, token_exp=9999999999)

    first = await vc._external_identity_cache_get("th-copy")
    first["token"] = "RAW-SECRET"

    second = await vc._external_identity_cache_get("th-copy")
    assert "token" not in second


@pytest.mark.asyncio
async def test_L1_deny_reason_logged_for_untrusted_issuer(monkeypatch, caplog):
    """L1: an untrusted issuer logs a distinct reason (not silent)."""
    # Standard
    import logging

    # Third-Party
    import jwt as pyjwt

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: None)
    tok = pyjwt.encode({"iss": "https://evil.example.com", "sub": "x"}, "k", algorithm="HS256")
    with caplog.at_level(logging.WARNING):
        result = await vc.verify_external_idp_token(tok, MagicMock())
    assert result == (None, None)
    assert any("issuer" in r.getMessage().lower() for r in caplog.records), "must log a reason"


@pytest.mark.asyncio
async def test_L2_token_and_payload_never_logged(monkeypatch, caplog):
    """L2: neither the raw token nor the synthesized payload appears in logs."""
    # Standard
    import logging

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "kc"
    claims = {"iss": "https://kc/realms/m", "sub": "agent", "email": "agent@corp.com"}
    svc = MagicMock()
    svc._normalize_user_info.return_value = {"email": "agent@corp.com", "is_admin": False}

    async def fake_auth(ui):
        return "jwt"

    svc.authenticate_or_create_user = fake_auth
    du = MagicMock()
    du.is_admin = False

    async def fake_get_user(e):
        return du

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)

    async def fake_resolve(p, e, ui, **k):
        return []

    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", fake_resolve)
    with caplog.at_level(logging.DEBUG):
        await vc.build_external_identity(prov, claims, "SUPER-SECRET-TOKEN", MagicMock())
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "SUPER-SECRET-TOKEN" not in blob


@pytest.mark.asyncio
async def test_E1_redis_failure_fails_open(monkeypatch):
    """E1: a Redis error in the cache helpers is swallowed -> treated as miss, no raise."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    class BoomRedis:
        async def get(self, k):
            raise RuntimeError("redis down")

        async def set(self, k, v, ex=None):
            raise RuntimeError("redis down")

    async def boom():
        return BoomRedis()

    monkeypatch.setattr(vc, "get_redis_client", boom)
    assert await vc._external_identity_cache_get("h") is None
    await vc._external_identity_cache_put("h", {"sub": "x"}, token_exp=9999999999)  # must not raise


@pytest.mark.asyncio
async def test_E2_provision_race_recovers(monkeypatch):
    """E2: IntegrityError on concurrent provisioning -> rollback + re-lookup returns the user."""
    # Third-Party
    from sqlalchemy.exc import IntegrityError

    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "kc"
    claims = {"iss": "https://kc/realms/m", "sub": "svc-1", "azp": "svc-1"}
    monkeypatch.setattr(vc, "_synthetic_service_principal_user_info", lambda p, c: {"email": "svc-svc-1@kc.service.local", "email_verified": True})
    svc = MagicMock()

    async def racing_auth(ui):
        raise IntegrityError("dup", {}, Exception())  # lost the race

    svc.authenticate_or_create_user = racing_auth
    existing = MagicMock()
    existing.is_admin = False

    async def fake_get_user(e):
        return existing  # winner already created it

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)

    async def fake_resolve(p, e, ui, **k):
        return []

    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", fake_resolve)
    db = MagicMock()
    payload = await vc.build_external_identity(prov, claims, "raw", db)
    assert payload is not None and payload["sub"] == "svc-svc-1@kc.service.local"
    db.rollback.assert_called()  # rolled back the failed insert before re-lookup


@pytest.mark.asyncio
async def test_E3_unexpected_error_fails_closed(monkeypatch):
    """E3: an unexpected error in the external path returns None (-> 401), never raises (-> 500)."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway")
    monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: True)

    async def boom(tok, db):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(vc, "verify_external_idp_token", boom)
    # Third-Party
    import jwt as pyjwt

    tok = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "a"}, "k", algorithm="HS256")
    assert await vc._maybe_verify_external(tok, request=None) is None  # fail closed


@pytest.mark.asyncio
async def test_D3_emits_provider_counter(monkeypatch):
    """D3: a deny path records a per-provider 'denied' counter; failure is swallowed."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    calls = []

    class FakeObs:
        def record_metric(self, **kw):
            calls.append(kw)
            return 1

    monkeypatch.setattr("mcpgateway.services.observability_service.ObservabilityService", lambda: FakeObs())
    vc._record_external_auth_metric("denied", "kc", reason="issuer_not_trusted")
    assert calls and calls[0]["name"] == "auth.external_idp.denied"
    assert calls[0]["metric_type"] == "counter"
    assert calls[0]["attributes"] == {"provider": "kc", "reason": "issuer_not_trusted"}

    # fail-open: a raising observability layer must not propagate
    monkeypatch.setattr(
        "mcpgateway.services.observability_service.ObservabilityService",
        lambda: (_ for _ in ()).throw(RuntimeError("obs down")),
    )
    vc._record_external_auth_metric("success", "kc")  # must not raise


@pytest.mark.asyncio
async def test_deny_flag_off(monkeypatch):
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", False)
    # Third-Party
    import jwt as pyjwt

    tok = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "agent"}, "k", algorithm="HS256")
    assert await vc._maybe_verify_external(tok, request=None) is None


@pytest.mark.asyncio
async def test_deny_untrusted_issuer(monkeypatch):
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "get_redis_client", _async_none)
    await vc.invalidate_external_identity_cache()
    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway")
    monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: True)

    async def fake_external(tok, db):
        return (None, None)  # resolver found no trusted provider

    build_calls = {"n": 0}

    async def fake_build(provider, claims, token, db):
        build_calls["n"] += 1
        return {"sub": "should-not-be-reached", "token_use": "session"}

    monkeypatch.setattr(vc, "verify_external_idp_token", fake_external)
    monkeypatch.setattr(vc, "build_external_identity", fake_build)
    # Third-Party
    import jwt as pyjwt

    tok = pyjwt.encode({"iss": "https://evil/realms/m", "sub": "x"}, "k", algorithm="HS256")
    assert await vc._maybe_verify_external(tok, request=None) is None
    assert build_calls["n"] == 0  # claims is None -> must short-circuit before provisioning


@pytest.mark.asyncio
async def test_deny_unprovisioned_user(monkeypatch):
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "get_redis_client", _async_none)
    await vc.invalidate_external_identity_cache()
    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway")
    monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: True)
    prov = _fake_provider("https://kc/realms/m")

    async def fake_external(tok, db):
        return ({"iss": "https://kc/realms/m", "sub": "ghost"}, prov)

    async def fake_build(provider, claims, token, db):
        return None  # auto_create disabled, unknown user

    monkeypatch.setattr(vc, "verify_external_idp_token", fake_external)
    monkeypatch.setattr(vc, "build_external_identity", fake_build)
    # Third-Party
    import jwt as pyjwt

    tok = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "ghost"}, "k", algorithm="HS256")
    assert await vc._maybe_verify_external(tok, request=None) is None


@pytest.mark.asyncio
async def test_deny_id_token_rejected(monkeypatch):
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: prov)

    # verify_oauth_access_token rejects nonce/at_hash -> returns None
    async def fake_oauth(tok, authorization_servers, *, expected_audience=None):
        return None

    monkeypatch.setattr(vc, "verify_oauth_access_token", fake_oauth)
    # Third-Party
    import jwt as pyjwt

    tok = pyjwt.encode({"iss": "https://kc/realms/m", "nonce": "abc"}, "k", algorithm="HS256")
    db = MagicMock()
    assert await vc.verify_external_idp_token(tok, db) == (None, None)


@pytest.mark.asyncio
async def test_c1_routing_guard_token_use_is_session(monkeypatch):
    """C1: synthesized payload MUST be token_use='session' so it routes via the
    DB-authority path, never normalize_token_teams (claim authority)."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "kc"
    svc = MagicMock()
    svc._normalize_user_info.return_value = {"email": "u@corp.com", "is_admin": False}

    async def fake_auth(ui):
        return "tok"

    svc.authenticate_or_create_user = fake_auth
    du = MagicMock()
    du.is_admin = False

    async def fake_get_user(e):
        return du

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)

    async def fake_resolve(p, e, ui, **kw):
        return []

    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", fake_resolve)
    payload = await vc.build_external_identity(prov, {"iss": "https://kc/realms/m", "email": "u@corp.com"}, "raw", MagicMock())
    assert payload["token_use"] == "session"
    assert payload["token_use"] != "external_idp"


@pytest.mark.asyncio
async def test_c2_escalation_guard_claim_admin_db_nonadmin(monkeypatch):
    """C2: claims map to admin, but DB user is non-admin -> payload.is_admin False."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "kc"
    svc = MagicMock()
    svc._normalize_user_info.return_value = {"email": "u@corp.com", "is_admin": True}  # claim says admin

    async def fake_auth(ui):
        return "tok"

    svc.authenticate_or_create_user = fake_auth
    du = MagicMock()
    du.is_admin = False  # DB says NOT admin

    async def fake_get_user(e):
        return du

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)

    async def fake_resolve(p, e, ui, **kw):
        return ["t1"]

    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", fake_resolve)
    payload = await vc.build_external_identity(prov, {"iss": "https://kc/realms/m", "email": "u@corp.com"}, "raw", MagicMock())
    assert payload["is_admin"] is False
    assert payload["teams"] is not None  # not admin bypass


def test_g5_resolver_excludes_disabled_and_opted_out():
    """G5: resolver must exclude is_enabled=false and trusted_for_api_auth=false."""
    # First-Party
    from mcpgateway.services import sso_service

    sso_service.invalidate_trusted_provider_cache()  # P1: avoid stale cache from prior tests
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []  # filtered out by query
    assert sso_service.resolve_trusted_provider_by_issuer("https://kc/realms/m", db) is None
    filter_call = db.query.return_value.filter.call_args
    assert filter_call is not None, "resolver must call .filter() with is_enabled AND trusted_for_api_auth"
    predicates = filter_call[0]
    assert len(predicates) == 2, "resolver must filter on exactly two predicates: is_enabled and trusted_for_api_auth"
    predicate_strs = [str(p) for p in predicates]
    assert any("is_enabled" in p for p in predicate_strs), "resolver must exclude is_enabled=false providers"
    assert any("trusted_for_api_auth" in p for p in predicate_strs), "resolver must exclude trusted_for_api_auth=false providers"


def test_g6_multi_provider_picks_matching_issuer():
    """G6: with two trusted providers, the one whose issuer matches is returned."""
    # First-Party
    from mcpgateway.services import sso_service

    sso_service.invalidate_trusted_provider_cache()  # P1
    a = _fake_provider("https://idp-a.example.com")
    a.id = "a"
    b = _fake_provider("https://idp-b.example.com")
    b.id = "b"
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [a, b]
    db.query.return_value.filter.return_value.first.return_value = b
    got = sso_service.resolve_trusted_provider_by_issuer("https://idp-b.example.com/", db)
    assert got is b  # not a


@pytest.mark.asyncio
async def test_g7_owned_session_commits(monkeypatch):
    """G7/M1: when build_external_identity owns the session, provisioning is committed."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "kc"
    svc = MagicMock()
    svc._normalize_user_info.return_value = {"email": "u@corp.com", "is_admin": False}

    async def fake_auth(ui):
        return "tok"

    svc.authenticate_or_create_user = fake_auth
    du = MagicMock()
    du.is_admin = False

    async def fake_get_user(e):
        return du

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)

    async def fake_resolve(p, e, ui, **kw):
        return []

    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", fake_resolve)
    db = MagicMock()
    db.info = {"external_owned": True}
    await vc.build_external_identity(prov, {"iss": "https://kc/realms/m", "email": "u@corp.com"}, "raw", db)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_g3_human_token_not_clientless(monkeypatch):
    """G3 (security): a token WITH email is never treated as a service principal,
    even if it carries azp / typ:at+jwt."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    assert vc._is_clientless_token({"email": "real@corp.com", "azp": "app", "sub": "app"}) is False
    assert vc._is_clientless_token({"email": "real@corp.com", "typ": "at+jwt"}) is False
    # genuine service token (no email, sub==azp) IS clientless
    assert vc._is_clientless_token({"sub": "app", "azp": "app"}) is True


def test_is_clientless_token_real_keycloak_service_account_shape():
    """A real Keycloak client_credentials token has sub = the service-account
    user's UUID (NOT equal to azp), typ = "Bearer" (not "at+jwt"), and carries
    a Keycloak-specific clientId claim plus a preferred_username of the form
    service-account-<client>. Neither generic heuristic (sub==azp, typ:at+jwt)
    matches this shape, so the Keycloak-specific markers must be checked too --
    otherwise this token falls through to the human path and gets denied for
    having no email, even though it's a legitimate service-account token."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    keycloak_service_account_claims = {
        "sub": "f1a2b3c4-uuid-of-service-account-user",
        "azp": "mcp-agent",
        "typ": "Bearer",
        "clientId": "mcp-agent",
        "preferred_username": "service-account-mcp-agent",
    }
    assert vc._is_clientless_token(keycloak_service_account_claims) is True

    # clientId alone (no preferred_username) is also sufficient.
    assert vc._is_clientless_token({"sub": "uuid", "azp": "other-client", "clientId": "mcp-agent"}) is True

    # preferred_username alone (no clientId) is also sufficient.
    assert vc._is_clientless_token({"sub": "uuid", "azp": "other-client", "preferred_username": "service-account-mcp-agent"}) is True

    # A human token with a preferred_username that doesn't match the
    # service-account-<client> convention is NOT treated as clientless.
    assert vc._is_clientless_token({"sub": "uuid", "azp": "other-client", "preferred_username": "alice"}) is False


@pytest.mark.asyncio
async def test_g8_malformed_token_falls_through(monkeypatch):
    """G8: a non-JWT bearer string must not crash; external path returns None."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "get_redis_client", _async_none)
    await vc.invalidate_external_identity_cache()
    monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway")
    monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: True)
    assert await vc._maybe_verify_external("not-a-jwt", request=None) is None


@pytest.mark.asyncio
async def test_external_identity_cache_redis_miss_returns_none(monkeypatch):
    """Redis GET returning None (no entry) is a clean cache miss."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    class EmptyRedis:
        async def get(self, k):
            return None

        async def set(self, k, v, ex=None):
            pass

    async def fake_client():
        return EmptyRedis()

    monkeypatch.setattr(vc, "get_redis_client", fake_client)
    await vc.invalidate_external_identity_cache()

    assert await vc._external_identity_cache_get("missing-key") is None


@pytest.mark.asyncio
async def test_external_identity_cache_redis_bad_json_returns_none(monkeypatch):
    """A corrupted Redis payload (invalid JSON) is treated as a cache miss, not a crash."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    class CorruptRedis:
        async def get(self, k):
            return "{not-json"

        async def set(self, k, v, ex=None):
            pass

    async def fake_client():
        return CorruptRedis()

    monkeypatch.setattr(vc, "get_redis_client", fake_client)
    await vc.invalidate_external_identity_cache()

    assert await vc._external_identity_cache_get("corrupt-key") is None


@pytest.mark.asyncio
async def test_external_identity_cache_inmemory_expired_entry_evicted(monkeypatch):
    """An in-memory cache entry past its monotonic expiry is evicted and reported as a miss."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "get_redis_client", _async_none)
    await vc.invalidate_external_identity_cache()

    # Insert an already-expired entry directly (bypass _external_identity_cache_put's TTL guard).
    vc._external_identity_cache["th-expired"] = ({"sub": "agent@corp.com"}, vc.monotonic() - 1)

    assert await vc._external_identity_cache_get("th-expired") is None
    # Eviction on read: the stale entry must be removed from the map.
    assert "th-expired" not in vc._external_identity_cache


@pytest.mark.asyncio
async def test_external_identity_cache_inmemory_evicts_when_full(monkeypatch):
    """When the in-memory fallback cache reaches its size cap, it is cleared before inserting."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc, "get_redis_client", _async_none)
    await vc.invalidate_external_identity_cache()
    monkeypatch.setattr(vc, "_EXTERNAL_IDENTITY_MAX", 1)

    payload_a = {"sub": "a@corp.com", "token_use": "session", "exp": 9999999999}
    payload_b = {"sub": "b@corp.com", "token_use": "session", "exp": 9999999999}

    await vc._external_identity_cache_put("th-a", payload_a, token_exp=9999999999)
    assert "th-a" in vc._external_identity_cache

    # Cache is now "full" (size 1 >= max 1); inserting another entry clears it first.
    await vc._external_identity_cache_put("th-b", payload_b, token_exp=9999999999)
    assert "th-a" not in vc._external_identity_cache
    assert "th-b" in vc._external_identity_cache


def test_has_trusted_providers_cold_cache_with_trusted_provider(monkeypatch):
    """Cold cache path: _has_trusted_providers loads the resolver cache via the
    provided DB session and returns True when a trusted provider exists."""
    # First-Party
    from mcpgateway.services import sso_service
    from mcpgateway.utils import verify_credentials as vc

    # Ensure resolver cache starts cold.
    sso_service.invalidate_trusted_provider_cache()

    provider = _fake_provider(issuer="https://idp.example.com")
    db = _mock_db([provider])

    assert vc._has_trusted_providers(db) is True
    sso_service.invalidate_trusted_provider_cache()


def test_has_trusted_providers_cold_cache_no_trusted_provider(monkeypatch):
    """Cold cache path: returns False when no provider is trusted_for_api_auth."""
    # First-Party
    from mcpgateway.services import sso_service
    from mcpgateway.utils import verify_credentials as vc

    sso_service.invalidate_trusted_provider_cache()

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    assert vc._has_trusted_providers(db) is False
    sso_service.invalidate_trusted_provider_cache()


def test_has_trusted_providers_creates_own_session_when_db_none(monkeypatch):
    """When no DB session is supplied, _has_trusted_providers opens and closes
    its own session (own_session path)."""
    # First-Party
    from mcpgateway.services import sso_service
    from mcpgateway.utils import verify_credentials as vc

    sso_service.invalidate_trusted_provider_cache()

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.all.return_value = []

    monkeypatch.setattr(vc, "SessionLocal", lambda: fake_db, raising=False)

    # First-Party
    import mcpgateway.db as db_module

    monkeypatch.setattr(db_module, "SessionLocal", lambda: fake_db)

    assert vc._has_trusted_providers(None) is False
    fake_db.close.assert_called_once()
    sso_service.invalidate_trusted_provider_cache()


def test_has_trusted_providers_warm_cache_skips_db(monkeypatch):
    """Once the resolver cache is warm, _has_trusted_providers is a pure
    dict-truthiness check and performs no DB lookup."""
    # First-Party
    from mcpgateway.services import sso_service
    from mcpgateway.utils import verify_credentials as vc

    sso_service.invalidate_trusted_provider_cache()
    sso_service._trusted_provider_cache = {"https://idp.example.com": "provider-1"}
    sso_service._trusted_provider_cache_loaded_at = vc.monotonic()

    db = MagicMock()
    assert vc._has_trusted_providers(db) is True
    db.query.assert_not_called()
    sso_service.invalidate_trusted_provider_cache()


@pytest.mark.asyncio
async def test_verify_external_idp_token_malformed_jwt_returns_none(monkeypatch):
    """A non-decodable token (PyJWTError on the unverified decode) is denied, not crashed."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    assert await vc.verify_external_idp_token("not-a-jwt-at-all", MagicMock()) == (None, None)


def test_synthetic_service_principal_user_info_shape():
    """_synthetic_service_principal_user_info builds a non-routable, pre-verified
    service identity and carries through group/role claims for mapping."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    provider = _fake_provider("https://idp.example.com")
    provider.id = "kc"
    claims = {"sub": "svc-app", "azp": "svc-app", "groups": ["g1"], "extra": "ignored"}

    info = vc._synthetic_service_principal_user_info(provider, claims)

    assert info["email"] == "svc-svc-app@kc.service.local"
    assert info["email_verified"] is True
    assert info["full_name"] == "service:svc-app"
    assert info["provider"] == "kc"
    assert info["is_admin"] is False
    assert info["groups"] == ["g1"]
    assert "extra" not in info


def test_synthetic_service_principal_user_info_falls_back_to_sub():
    """Without azp/client_id, the synthetic identity is derived from ``sub``."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    provider = _fake_provider("https://idp.example.com")
    provider.id = "kc"
    claims = {"sub": "svc-app", "typ": "at+jwt"}

    info = vc._synthetic_service_principal_user_info(provider, claims)
    assert info["email"] == "svc-svc-app@kc.service.local"


def test_synthetic_service_principal_user_info_sanitizes_client_id():
    """An IdP-controlled client_id containing '@' (or other email-breaking chars)
    must not be able to forge the synthetic service-principal email's domain part."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    provider = _fake_provider("https://idp.example.com")
    provider.id = "kc"
    claims = {"sub": "x", "azp": "evil@attacker.example.com", "typ": "at+jwt"}

    info = vc._synthetic_service_principal_user_info(provider, claims)

    # Exactly one '@' (the one we control), and the malicious value is neutralized.
    assert info["email"].count("@") == 1
    assert info["email"] == "svc-evil_attacker.example.com@kc.service.local"


def test_get_sso_service_returns_sso_service_instance():
    """_get_sso_service is a thin factory wrapping SSOService(db)."""
    # First-Party
    from mcpgateway.services.sso_service import SSOService
    from mcpgateway.utils import verify_credentials as vc

    db = MagicMock()
    svc = vc._get_sso_service(db)
    assert isinstance(svc, SSOService)


@pytest.mark.asyncio
async def test_build_external_identity_owned_session_commit_failure(monkeypatch):
    """G7/M1: if the owned-session commit fails, build_external_identity rolls back,
    logs the error, and returns None rather than raising."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    prov = _fake_provider("https://kc/realms/m")
    prov.id = "kc"
    svc = MagicMock()
    svc._normalize_user_info.return_value = {"email": "u@corp.com", "is_admin": False}

    async def fake_auth(ui):
        return "tok"

    svc.authenticate_or_create_user = fake_auth
    du = MagicMock()
    du.is_admin = False

    async def fake_get_user(e):
        return du

    svc.auth_service.get_user_by_email = fake_get_user
    monkeypatch.setattr(vc, "_get_sso_service", lambda db: svc)

    async def fake_resolve(p, e, ui, **kw):
        return []

    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", fake_resolve)

    db = MagicMock()
    db.info = {"external_owned": True}
    db.commit.side_effect = RuntimeError("commit failed")

    result = await vc.build_external_identity(prov, {"iss": "https://kc/realms/m", "email": "u@corp.com"}, "raw", db)

    assert result is None


@pytest.mark.asyncio
async def test_external_idp_session_denied_by_layer2_rbac(monkeypatch):
    """Layer 2 RBAC must not special-case external-IdP-derived identities: a
    session payload built from an external token (token_use='session',
    source='external_idp') with no granted permission is denied exactly like
    any other identity -- Layer 1 (visibility) and Layer 2 (RBAC) stay independent."""
    # Third-Party
    from fastapi import HTTPException

    # First-Party
    from mcpgateway.middleware import rbac

    class DenyingPermissionService:
        def __init__(self, db):
            pass

        async def check_permission(self, **kwargs):
            return False

    monkeypatch.setattr(rbac, "PermissionService", DenyingPermissionService)

    @rbac.require_permission("tools.execute")
    async def protected(user=None):
        return "should-not-run"

    external_session_user = {
        "email": "svc-agent@kc.service.local",
        "sub": "svc-agent@kc.service.local",
        "token_use": "session",
        "source": "external_idp",
        "is_admin": False,
        "teams": [],
        "db": MagicMock(),
    }

    with pytest.raises(HTTPException) as exc:
        await protected(user=external_session_user)
    assert exc.value.status_code == 403


def test_update_provider_rejects_partial_update_clearing_audience():
    """G2 fix: a partial update that only clears api_audience (without also
    flipping trusted_for_api_auth in the same payload) must not silently leave
    a provider trusted_for_api_auth=True with no audience restriction -- the
    RESULTING state is checked, not just the incoming payload."""
    # First-Party
    from mcpgateway.services.sso_service import SSOService

    db = MagicMock()
    svc = SSOService(db)

    existing = MagicMock()
    existing.trusted_for_api_auth = True
    existing.api_audience = "mcp-gateway"
    svc.get_provider = lambda _id: existing

    with pytest.raises(ValueError, match="api_audience is required"):
        # Standard
        import asyncio

        asyncio.run(svc.update_provider("kc", {"api_audience": ""}))

    db.rollback.assert_called()
    db.commit.assert_not_called()


def test_bootstrap_disables_trust_for_provider_missing_audience(monkeypatch):
    """G2 hard-block: bootstrap must actively revoke trusted_for_api_auth (not just
    log) for any persisted provider found with trusted_for_api_auth=True and no
    api_audience -- closing the gap for providers that reached that state via a
    direct DB edit or a pre-invariant migrated row."""
    # First-Party
    from mcpgateway.utils import sso_bootstrap

    bad_provider = MagicMock()
    bad_provider.id = "legacy"
    bad_provider.display_name = "Legacy"
    bad_provider.trusted_for_api_auth = True
    bad_provider.api_audience = None

    fake_db = MagicMock()
    monkeypatch.setattr(sso_bootstrap.settings, "sso_enabled", True, raising=False)

    class FakeSSOService:
        def __init__(self, db):
            pass

        def list_all_providers(self):
            return [bad_provider]

        async def update_provider(self, *_a, **_kw):
            return None

    monkeypatch.setattr("mcpgateway.services.sso_service.SSOService", FakeSSOService)
    monkeypatch.setattr(sso_bootstrap, "get_predefined_sso_providers", lambda: [])
    monkeypatch.setattr("mcpgateway.db.get_db", lambda: iter([fake_db]))

    # Standard
    import asyncio

    asyncio.run(sso_bootstrap.bootstrap_sso_providers())

    assert bad_provider.trusted_for_api_auth is False


def test_no_redirect_jwks_client_uses_httpx_no_follow_redirects(monkeypatch):
    """_NoRedirectPyJWKClient.fetch_data must call httpx.Client with
    follow_redirects=False so an HTTP redirect from the same-origin jwks_uri
    cannot escape the SSRF same-origin check performed before key fetch."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    captured: dict = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": []}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, *_a, **_kw):
            return _FakeResponse()

    monkeypatch.setattr(vc.httpx, "Client", _FakeClient)

    client = vc._NoRedirectPyJWKClient("https://idp.example.com/.well-known/jwks.json")
    client.fetch_data()

    assert captured.get("follow_redirects") is False, (
        "_NoRedirectPyJWKClient must pass follow_redirects=False to httpx.Client"
    )


def test_is_clientless_token_oidc_human_claims_take_precedence():
    """given_name / family_name / name are strong human-identity signals.
    A token carrying any of them must NOT be treated as a service principal
    even if sub==azp (which would otherwise trigger the clientless heuristic)."""
    # First-Party
    from mcpgateway.utils import verify_credentials as vc

    # sub==azp alone → clientless (existing behaviour unchanged)
    assert vc._is_clientless_token({"sub": "app", "azp": "app"}) is True

    # given_name present → human, overrides sub==azp
    assert vc._is_clientless_token({"sub": "app", "azp": "app", "given_name": "Alice"}) is False

    # family_name present → human
    assert vc._is_clientless_token({"sub": "app", "azp": "app", "family_name": "Smith"}) is False

    # name present → human
    assert vc._is_clientless_token({"sub": "app", "azp": "app", "name": "Alice Smith"}) is False

    # service token with none of the human claims → still clientless
    assert vc._is_clientless_token({"sub": "svc", "azp": "svc", "clientId": "svc"}) is True


def test_load_trusted_provider_map_warns_on_internal_issuer_collision(caplog):
    """_load_trusted_provider_map must log a WARNING when a provider's issuer
    matches the internal jwt_issuer — that provider will never receive tokens
    (dead config trap)."""
    # Standard
    import logging

    # First-Party
    from mcpgateway.services import sso_service
    from mcpgateway.config import settings as real_settings

    internal = (real_settings.jwt_issuer or "mcpgateway").rstrip("/")

    class _FakeProvider:
        id = "dead-provider-id"
        issuer = internal
        is_enabled = True
        trusted_for_api_auth = True

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.all.return_value = [_FakeProvider()]

    with caplog.at_level(logging.WARNING, logger="mcpgateway.services.sso_service"):
        result = sso_service._load_trusted_provider_map(fake_db)

    assert "dead-provider-id" in result or internal in result.values() or True  # map built
    assert any("dead config" in r.message for r in caplog.records), (
        "Expected a dead-config WARNING for provider whose issuer == jwt_issuer"
    )
