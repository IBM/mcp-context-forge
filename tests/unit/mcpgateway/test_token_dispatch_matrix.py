# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_token_dispatch_matrix.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Cross-mode token dispatch deny-test matrix (issue #5896).

Executable form of the six mode-x-token combinations pinned in
docs/docs/architecture/auth-token-dispatch.md:

- The trust-mode rows for non-eligible tokens exercise the default funnel.
  That IS the documented behavior for these rows.
- The gateway-signed branch-(a) rows are green since #5900 landed the
  trust branch in get_current_user.
- The external-IdP branch-(b) row is green since #5903 landed the
  external IdP trust root.

Real-entry-point conversion (#6753 / F4): the external rows previously
called ``_maybe_verify_external()`` directly with a mocked
``verify_external_idp_token``. They now drive the real entry points
(``get_current_user()`` for the ingress rows, ``verify_credentials_cached()``
for the default-mode provisioning row) with externally-signed RS256 tokens
minted from Task 9's local OIDC issuer key. ONLY the OIDC discovery/JWKS
network fetch is mocked: the dispatch (``_maybe_verify_external`` /
``verify_credentials_cached``), provider resolution, RSA
signature/audience/expiry verification, and claim mapping all run for real.
"""

# Standard
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailUser, SSOProvider
from mcpgateway.services import sso_service
from mcpgateway.utils import verify_credentials as vc
from tests.live_gateway.helpers.local_oidc_issuer import generate_signing_key, mint_token

# The externally-signed fixtures' issuer/audience. The issuer is an https
# origin so the JWKS-URI SSRF defense in verify_oauth_access_token accepts
# the (mocked) discovery document.
EXT_ISSUER = "https://idp.example.test"
EXT_AUDIENCE = "api://my-app"
EXT_JWKS_URI = f"{EXT_ISSUER}/.well-known/jwks.json"
EXT_PROVIDER_ID = "local-oidc-test"
UNTRUSTED_ISSUER = "https://untrusted-idp.example.test"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture(scope="module")
def ext_signing_key():
    """RSA keypair shared by this module's externally-signed fixtures.

    Generated once per module via Task 9's local OIDC issuer harness; tokens
    are minted per test with distinct subjects/jtis.
    """
    return generate_signing_key()


def _make_user(email: str) -> EmailUser:
    """Active, non-admin local user for the default funnel."""
    return EmailUser(
        email=email,
        password_hash="hash",
        full_name="Matrix User",
        is_admin=False,
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _seed_trust_root_provider(db) -> str:
    """Insert the SSO provider row that makes EXT_ISSUER a configured trust root.

    This is the row ``resolve_trusted_provider_by_issuer`` matches against:
    enabled, opted into API auth, with a pinned audience. Only the NOT-NULL
    columns plus the trust-root fields matter on the dispatch path.
    """
    provider = SSOProvider(
        id=EXT_PROVIDER_ID,
        name=EXT_PROVIDER_ID,
        display_name="Local OIDC Test Issuer",
        provider_type="oidc",
        is_enabled=True,
        client_id="dispatch-matrix-tests",
        client_secret_encrypted="unused-on-this-path",  # pragma: allowlist secret
        authorization_url=f"{EXT_ISSUER}/authorize",
        token_url=f"{EXT_ISSUER}/token",
        userinfo_url=f"{EXT_ISSUER}/userinfo",
        issuer=EXT_ISSUER,
        trusted_for_api_auth=True,
        api_audience=EXT_AUDIENCE,
    )
    db.add(provider)
    db.commit()
    # Return the id (not the ORM object): the seeding session may close
    # before the caller reads attributes, which would detach the instance.
    return provider.id


def _install_external_jwks(monkeypatch, signing_key) -> None:
    """Mock ONLY the OIDC discovery/JWKS network fetch for EXT_ISSUER.

    Signature, audience, expiry, and issuer checks in
    ``verify_oauth_access_token`` still run for real against the module RSA
    key, as do the dispatch, provider resolution, and claim mapping.
    """

    async def _fake_discover(issuer: str):
        if issuer.rstrip("/") == EXT_ISSUER:
            return {"issuer": EXT_ISSUER, "jwks_uri": EXT_JWKS_URI}
        return None

    class _StaticJWKClient:
        """Stand-in for the PyJWKClient cache entry: serves the test key."""

        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key=signing_key.public_key())

    monkeypatch.setattr(vc, "_discover_oidc_metadata", _fake_discover)
    monkeypatch.setitem(vc._oauth_jwks_client_cache, EXT_JWKS_URI, _StaticJWKClient())


def _mint_external_token(signing_key, subject: str, *, issuer: str = EXT_ISSUER, **claims) -> str:
    """Mint an RS256 token from the local issuer key with the registered audience."""
    payload = {
        "iss": issuer,
        "sub": subject,
        "aud": EXT_AUDIENCE,
        "exp": _exp(),
        "iat": datetime.now(timezone.utc).timestamp(),
        "jti": f"ext-jti-{subject}-{issuer.split('//')[1]}",
    }
    payload.update(claims)
    return mint_token(payload, signing_key)


async def _reset_external_caches() -> None:
    """Cold-start the provider map and external-identity caches for a test."""
    sso_service.invalidate_trusted_provider_cache()
    await vc.invalidate_external_identity_cache()


def _repoint_funnel_sessions(monkeypatch):
    """Re-point the funnel's internal sessions at a schema-complete test DB.

    The trust branch validates role claims against the server-side roles
    table through ``fresh_db_session``, and the external-IdP dispatch opens
    its own session through ``mcpgateway.db.SessionLocal`` when the request
    does not carry one. The default in-memory engine gives each connection
    a fresh empty database, so the trust-path tests re-point all three
    session factories at one shared engine (the same way the B.4/B.5 trust
    tests do).

    Returns the session factory so tests can seed rows and hand the
    dispatch a request-scoped session (``request.state.db``).
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session_test = sessionmaker(bind=engine)
    monkeypatch.setattr("mcpgateway.auth.SessionLocal", session_test)
    monkeypatch.setattr("mcpgateway.db.SessionLocal", session_test)

    @contextlib.contextmanager
    def _fresh_db_session():
        session = session_test()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _fresh_db_session)
    return session_test


class TestTokenDispatchMatrix:
    """Six mode-x-token combinations of the token dispatch rule (#5896)."""

    @pytest.mark.asyncio
    async def test_external_idp_token_default_mode_provisioning(self, monkeypatch, ext_signing_key):
        """Default mode + external IdP token -> current provisioning behavior.

        A token from a trusted issuer verifies through
        verify_external_idp_token and enters the default provisioning
        funnel. This is the current code path and the expected result for
        this combination.

        Real-entry-point shape (#6753): drives ``verify_credentials_cached``
        — the default-mode entry point for external bearers — with an
        externally-signed RS256 token. Only the JWKS network fetch is
        mocked; the dispatch, RSA signature/audience/expiry verification,
        and the provisioning funnel (build_external_identity) run for real.
        """
        session_test = _repoint_funnel_sessions(monkeypatch)
        provider_id = _seed_trust_root_provider(session_test())
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        monkeypatch.setattr(settings, "sso_api_token_auth_enabled", True)
        _install_external_jwks(monkeypatch, ext_signing_key)
        await _reset_external_caches()

        token = _mint_external_token(ext_signing_key, "agent", email="agent@example.com", email_verified=True)
        request = SimpleNamespace(state=SimpleNamespace(db=session_test()))
        payload = await vc.verify_credentials_cached(token, request)

        # The external dispatch served the request: the verified payload is
        # stashed on the request for downstream consumers.
        assert request.state._jwt_verified_payload == (token, payload)  # pylint: disable=protected-access
        # Session semantics from the provisioning funnel, not trust claims.
        assert payload["token_use"] == "session"
        assert payload["email"] == "agent@example.com"
        assert payload["auth_provider"] == provider_id
        # Provisioning side-effect: a local user record now exists.
        db = session_test()
        assert db.query(EmailUser).filter(EmailUser.email == "agent@example.com").first() is not None

    @pytest.mark.asyncio
    async def test_session_token_trust_mode_default_funnel(self, monkeypatch):
        """Trust mode + default session token -> default-semantics.

        A session token carries no trust marker and its issuer is not a
        trust root, so it is not trust-eligible: teams are resolved
        server-side and an embedded teams claim is narrowed against the
        DB. Trust mode does not exist yet (#5898/#5900), so this exercises
        the current path, which is the documented behavior for this row.
        """
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="session_jwt_token")  # pragma: allowlist secret

        # JWT claims one team; the DB reports a disjoint team. Default
        # semantics intersect: the claim alone can never widen access.
        jwt_payload = {
            "sub": "test@example.com",
            "token_use": "session",
            "teams": ["team-from-claim"],
            "exp": _exp(),
            "jti": "session_jti_matrix",
        }

        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "test@example.com", "full_name": "Matrix User", "is_admin": False, "is_active": True},
            personal_team_id="team_123",
        )

        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)):
                with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["team-from-db"]) as mock_resolve_db:
                    user = await get_current_user(credentials=credentials, request=request)

                    assert user.email == "test@example.com"
                    # Server-side resolution ran; the embedded claim was not honored.
                    mock_resolve_db.assert_called_once()
                    assert request.state.token_use == "session"
                    assert request.state.token_teams == []

    @pytest.mark.asyncio
    async def test_api_token_trust_mode_default_funnel(self, monkeypatch):
        """Trust mode + default API token -> default-semantics.

        An API token carries token_use="api", not the trust marker, so it
        is not trust-eligible: the embedded teams claim is honored and no
        DB team resolution runs. Trust mode does not exist yet
        (#5898/#5900), so this exercises the current path, which is the
        documented behavior for this row.
        """
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="api_jwt_token")  # pragma: allowlist secret

        jwt_payload = {
            "sub": "api@example.com",
            "token_use": "api",
            "teams": ["api-team-1"],
            "exp": _exp(),
            "user": {"auth_provider": "api_token"},
        }

        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=_make_user("api@example.com")):
                with patch("mcpgateway.auth._resolve_teams_from_db") as mock_resolve_db:
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials, request=request)

                        assert user.email == "api@example.com"
                        # Embedded teams honored; no server-side resolution.
                        mock_resolve_db.assert_not_called()
                        assert request.state.token_use == "api"
                        assert request.state.token_teams == ["api-team-1"]

    @pytest.mark.asyncio
    async def test_gateway_trust_token_trust_mode_trust_semantics(self, monkeypatch):
        """Trust mode + gateway-signed trust token -> trust-semantics.

        A token_use="trusted" token with the mapped claim set (sub, teams,
        roles) and a jti authenticates from claims alone: no local user
        record is read on the request path.
        """
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret

        jwt_payload = {
            "sub": "trust.user@example.com",
            "token_use": "trusted",
            "teams": ["trust-team-1"],
            "roles": ["team_admin"],
            "jti": "trusted_jti_matrix",
            "exp": _exp(),
        }

        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _repoint_funnel_sessions(monkeypatch)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                # No EmailUser row exists for this principal.
                with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials, request=request)

                        # Trust-semantics: identity and teams come from the claims.
                        assert user.email == "trust.user@example.com"
                        assert request.state.token_use == "trusted"
                        assert request.state.token_teams == ["trust-team-1"]

    @pytest.mark.asyncio
    async def test_gateway_trust_token_default_mode_401(self, monkeypatch):
        """Default mode + gateway-signed trust token -> HTTP 401.

        Trust mode is OFF, so a token_use="trusted" token must be rejected
        with 401. It must never enter the default funnel, whose UUID
        heuristic and embedded-teams handling would re-attribute identity.
        """
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret

        jwt_payload = {
            "sub": "existing@example.com",
            "token_use": "trusted",
            "teams": ["trust-team-1"],
            "roles": ["team_admin"],
            "jti": "trusted_jti_matrix_off",
            "exp": _exp(),
        }

        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                with patch("mcpgateway.auth._get_user_by_email_sync", return_value=_make_user("existing@example.com")):
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        with pytest.raises(HTTPException) as exc_info:
                            await get_current_user(credentials=credentials)

                        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_external_idp_token_trust_mode_trust_semantics(self, monkeypatch, ext_signing_key):
        """Trust mode + external IdP token (trusted issuer) -> trust-semantics.

        The issuer is a configured trust root, so the token is
        trust-eligible via the issuer branch: the identity is built from
        token claims alone and the provisioning path
        (build_external_identity) is not invoked. Green since #5903 landed
        the external IdP trust root.

        Real-entry-point shape (#6753): drives ``get_current_user()`` with
        an externally-signed RS256 token whose issuer is a seeded trust
        root. Only the JWKS network fetch is mocked; the ingress dispatch,
        signature verification, and claims-derived identity build run for
        real.
        """
        session_test = _repoint_funnel_sessions(monkeypatch)
        _seed_trust_root_provider(session_test())
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "sso_api_token_auth_enabled", True)
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _install_external_jwks(monkeypatch, ext_signing_key)
        await _reset_external_caches()

        token = _mint_external_token(ext_signing_key, "ext-subject-0001", email="ext.user@example.com")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret
        request = SimpleNamespace(state=SimpleNamespace(db=session_test()))

        mock_build = AsyncMock(side_effect=AssertionError("provisioning path entered for a trust-root token"))
        monkeypatch.setattr(vc, "build_external_identity", mock_build)
        internal_verifier = AsyncMock(side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials"))

        with patch("mcpgateway.auth.verify_jwt_token_cached", internal_verifier):
            user = await get_current_user(credentials=credentials, request=request)

        # Trust-semantics: claims-derived identity, no local provisioning,
        # and the internal verifier was never consulted.
        assert user.email == "ext.user@example.com"
        assert request.state.token_use == "trusted"
        mock_build.assert_not_called()
        internal_verifier.assert_not_called()


class TestIngressExternalDispatch:
    """get_current_user() trust-mode ingress dispatch (#5903 / Task 9).

    Dispatch contract pinned here (mirrors docs/5896 and AGENTS.md):

    - Trust mode ON + issuer is a configured trust root + verification
      succeeds -> external principal (token_use="trusted" branch).
    - Trust mode ON + issuer is a configured trust root + definitive
      verification failure -> 401 fail-closed; the internal verifier is
      NEVER consulted for that token.
    - Trust mode ON + issuer NOT a trust root -> fall through to the
      internal funnel exactly as before.
    - Trust mode OFF (db) -> external path is never entered.
    - No credentials -> 401 (pre-existing behavior, pinned).

    Real-entry-point shape (#6753 / F4): every external row uses an
    externally-signed RS256 token minted from the local issuer key and runs
    the real dispatch (``_try_external_verification`` ->
    ``_maybe_verify_external`` -> ``verify_external_idp_token``). Only the
    OIDC discovery/JWKS network fetch is mocked. Where a test must prove
    the dispatch was (or was not) consulted, a wraps-spy records the call
    while delegating to the real function.
    """

    @pytest.mark.asyncio
    async def test_unauthenticated_invoke_401(self):
        """No bearer credentials -> 401 (existing behavior, pinned)."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=None, request=None)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_db_mode_external_token_stays_on_internal_funnel(self, monkeypatch, ext_signing_key):
        """Trust mode OFF + external-issuer token -> 401 via the internal funnel.

        The external dispatch must never run: with jwt_trust_mode="db" the
        internal verifier alone decides, and it rejects the externally-signed
        RS256 token (real signature check against the gateway HMAC secret).
        The wraps-spy proves the real dispatch is never consulted.
        """
        token = _mint_external_token(ext_signing_key, "ext")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret

        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        external_spy = AsyncMock(wraps=vc._maybe_verify_external)
        monkeypatch.setattr(vc, "_maybe_verify_external", external_spy)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, request=None)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        external_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_mode_external_token_authenticates_via_external_path(self, monkeypatch, ext_signing_key):
        """Trust mode ON + trust-root token -> claims-derived principal.

        The internal verifier would reject this externally-signed RS256
        token (patched to 401 to prove it is never consulted); the request
        still authenticates because the real ingress dispatch consults the
        external verifier FIRST — only the JWKS network fetch is mocked —
        and its payload flows into the token_use="trusted" branch.
        """
        session_test = _repoint_funnel_sessions(monkeypatch)
        _seed_trust_root_provider(session_test())
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "sso_api_token_auth_enabled", True)
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _install_external_jwks(monkeypatch, ext_signing_key)
        await _reset_external_caches()

        token = _mint_external_token(ext_signing_key, "ext-subject-0001", email="ext.user@example.com", groups=["external-group-1"])
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret
        request = SimpleNamespace(state=SimpleNamespace(db=session_test()))

        external_spy = AsyncMock(wraps=vc._maybe_verify_external)
        monkeypatch.setattr(vc, "_maybe_verify_external", external_spy)
        internal_verifier = AsyncMock(side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials"))

        with patch("mcpgateway.auth.verify_jwt_token_cached", internal_verifier):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "ext.user@example.com"
        assert request.state.token_use == "trusted"
        external_spy.assert_awaited_once()
        internal_verifier.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_mode_trust_root_invalid_token_fails_closed(self, monkeypatch, ext_signing_key):
        """Trust mode ON + trust-root token that fails verification -> 401.

        Fail-closed: a definitive external-verification failure (here a bad
        signature — the token is signed with a key the JWKS endpoint does
        not serve) must NOT fall through to the internal funnel for that
        token. The patched internal verifier WOULD authenticate this
        request, so the 401 proves it was never consulted.
        """
        session_test = _repoint_funnel_sessions(monkeypatch)
        _seed_trust_root_provider(session_test())
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "sso_api_token_auth_enabled", True)
        _install_external_jwks(monkeypatch, ext_signing_key)
        await _reset_external_caches()

        wrong_key = generate_signing_key()  # not the key the JWKS stub serves
        token = _mint_external_token(wrong_key, "ext")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret
        request = SimpleNamespace(state=SimpleNamespace(db=session_test()))

        external_spy = AsyncMock(wraps=vc._maybe_verify_external)
        monkeypatch.setattr(vc, "_maybe_verify_external", external_spy)
        internal_verifier = AsyncMock(return_value={"sub": "internal@example.com", "exp": _exp(), "jti": "internal-jti"})

        with patch("mcpgateway.auth.verify_jwt_token_cached", internal_verifier):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, request=request)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        external_spy.assert_awaited_once()
        internal_verifier.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_mode_non_trust_root_token_falls_through_to_internal(self, monkeypatch, ext_signing_key):
        """Trust mode ON + issuer NOT a trust root -> internal funnel as today.

        The real external dispatch decodes the token, finds the issuer is
        not a configured trust root (a DIFFERENT issuer is seeded as the
        trust root, so the provider-resolution query really runs), and
        returns None; the internal verifier then decides. A gateway-signed
        JWT still authenticates with trust mode ON (no regression).
        """
        session_test = _repoint_funnel_sessions(monkeypatch)
        _seed_trust_root_provider(session_test())
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "sso_api_token_auth_enabled", True)
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        await _reset_external_caches()

        token = _mint_external_token(ext_signing_key, "api@example.com", issuer=UNTRUSTED_ISSUER)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret

        jwt_payload = {
            "sub": "api@example.com",
            "token_use": "api",
            "teams": ["api-team-1"],
            "exp": _exp(),
            "user": {"auth_provider": "api_token"},
        }

        request = SimpleNamespace(state=SimpleNamespace(db=session_test()))
        external_spy = AsyncMock(wraps=vc._maybe_verify_external)
        monkeypatch.setattr(vc, "_maybe_verify_external", external_spy)
        # The internal funnel's own JWT verification is outside this row's
        # scope (the row pins the fall-through DECISION), so the internal
        # verifier is stubbed exactly as in the default-funnel rows above.
        internal_verifier = AsyncMock(return_value=jwt_payload)

        with patch("mcpgateway.auth.verify_jwt_token_cached", internal_verifier):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=_make_user("api@example.com")):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "api@example.com"
        assert request.state.token_use == "api"
        external_spy.assert_awaited_once()
        internal_verifier.assert_awaited_once()
