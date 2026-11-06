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
"""

# Standard
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
from mcpgateway.db import Base, EmailUser


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


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


def _fake_provider(issuer: str) -> MagicMock:
    """SSO provider opted into API auth with a pinned audience."""
    provider = MagicMock()
    provider.issuer = issuer
    provider.is_enabled = True
    provider.trusted_for_api_auth = True
    provider.api_audience = "api://my-app"
    return provider


def _repoint_funnel_sessions(monkeypatch) -> None:
    """Re-point the funnel's internal sessions at a schema-complete test DB.

    The trust branch validates role claims against the server-side roles
    table through ``fresh_db_session``. The default in-memory engine gives
    each connection a fresh empty database, so the trust-path tests re-point
    the funnel sessions the same way the B.4/B.5 trust tests do.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session_test = sessionmaker(bind=engine)
    monkeypatch.setattr("mcpgateway.auth.SessionLocal", session_test)

    @contextlib.contextmanager
    def _fresh_db_session():
        session = session_test()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _fresh_db_session)


class TestTokenDispatchMatrix:
    """Six mode-x-token combinations of the token dispatch rule (#5896)."""

    @pytest.mark.asyncio
    async def test_external_idp_token_default_mode_provisioning(self, monkeypatch):
        """Default mode + external IdP token -> current provisioning behavior.

        A token from a trusted issuer verifies through
        verify_external_idp_token and enters the default provisioning
        funnel. This is the current code path and the expected result for
        this combination.
        """
        # Third-Party
        import jwt as pyjwt

        # First-Party
        from mcpgateway.utils import verify_credentials as vc

        token = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "agent"}, "k", algorithm="HS256")
        provider = _fake_provider("https://kc/realms/m")
        monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda iss, db: provider)

        async def fake_verify(tok, authorization_servers, *, expected_audience=None):
            return {"iss": "https://kc/realms/m", "sub": "agent"}

        monkeypatch.setattr(vc, "verify_oauth_access_token", fake_verify)
        claims, returned_provider = await vc.verify_external_idp_token(token, MagicMock())

        assert claims["sub"] == "agent"
        assert returned_provider is provider

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
    async def test_external_idp_token_trust_mode_trust_semantics(self, monkeypatch):
        """Trust mode + external IdP token (trusted issuer) -> trust-semantics.

        The issuer is a configured trust root, so the token is
        trust-eligible via the issuer branch: the identity is built from
        token claims alone and the provisioning path
        (build_external_identity) is not invoked. Green since #5903 landed
        the external IdP trust root.
        """
        # Third-Party
        import jwt as pyjwt

        # First-Party
        from mcpgateway.utils import verify_credentials as vc

        token = pyjwt.encode({"iss": "https://kc/realms/m", "sub": "agent", "exp": _exp()}, "k", algorithm="HS256")
        provider = _fake_provider("https://kc/realms/m")

        monkeypatch.setattr(vc.settings, "sso_api_token_auth_enabled", True)
        monkeypatch.setattr(vc.settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(vc, "_has_trusted_providers", lambda db: True)

        async def fake_verify_external(tok, db):
            return {"iss": "https://kc/realms/m", "sub": "agent", "exp": _exp()}, provider

        monkeypatch.setattr(vc, "verify_external_idp_token", fake_verify_external)
        mock_build = AsyncMock(return_value={"sub": "agent", "token": token})
        monkeypatch.setattr(vc, "build_external_identity", mock_build)

        await vc.invalidate_external_identity_cache()
        request = SimpleNamespace(state=SimpleNamespace(db=MagicMock()))
        await vc._maybe_verify_external(token, request)

        # Trust-semantics: claims-derived identity, no local provisioning.
        mock_build.assert_not_called()


def _external_payload() -> dict:
    """Claims-derived identity payload as build_trusted_external_identity returns it.

    Carries the original token claims (sub/email/groups/jti) plus the derived
    trust markers, exactly the shape ``_maybe_verify_external`` yields on the
    trust-root branch.
    """
    return {
        "iss": "https://idp.example.test",
        "sub": "ext-subject-0001",
        "email": "ext.user@example.com",
        "user_id": "ext-subject-0001",
        "groups": ["external-group-1"],
        "teams": [],
        "roles": [],
        "is_admin": False,
        "jti": "ext-jti-ingress-1",
        "exp": _exp(),
        "token_use": "trusted",
        "source": "external_idp",
        "auth_provider": "local-oidc-test",
    }


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
    """

    @pytest.mark.asyncio
    async def test_unauthenticated_invoke_401(self):
        """No bearer credentials -> 401 (existing behavior, pinned)."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=None, request=None)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_db_mode_external_token_stays_on_internal_funnel(self, monkeypatch):
        """Trust mode OFF + external-issuer token -> 401 via the internal funnel.

        The external dispatch must never run: with jwt_trust_mode="db" the
        internal verifier alone decides, and it rejects externally-signed
        tokens.
        """
        # Third-Party
        import jwt as pyjwt

        # First-Party
        from mcpgateway.utils import verify_credentials as vc

        token = pyjwt.encode({"iss": "https://idp.example.test", "sub": "ext", "exp": _exp()}, "k", algorithm="HS256")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret

        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        external_dispatch = AsyncMock(side_effect=AssertionError("external path entered in db mode"))
        monkeypatch.setattr(vc, "_maybe_verify_external", external_dispatch)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials"))):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, request=None)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        external_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_mode_external_token_authenticates_via_external_path(self, monkeypatch):
        """Trust mode ON + trust-root token -> claims-derived principal.

        The internal verifier would reject this RS256-style external token
        (mocked to 401); the request still authenticates because the ingress
        dispatch consults the external verifier FIRST and its payload flows
        into the token_use="trusted" branch.
        """
        # Third-Party
        import jwt as pyjwt

        # First-Party
        from mcpgateway.utils import verify_credentials as vc

        token = pyjwt.encode({"iss": "https://idp.example.test", "sub": "ext-subject-0001", "exp": _exp()}, "k", algorithm="HS256")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret

        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _repoint_funnel_sessions(monkeypatch)

        external_dispatch = AsyncMock(return_value=_external_payload())
        monkeypatch.setattr(vc, "_maybe_verify_external", external_dispatch)
        internal_verifier = AsyncMock(side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials"))

        request = SimpleNamespace(state=SimpleNamespace())
        with patch("mcpgateway.auth.verify_jwt_token_cached", internal_verifier):
            with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "ext.user@example.com"
        assert request.state.token_use == "trusted"
        external_dispatch.assert_awaited_once()
        internal_verifier.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_mode_trust_root_invalid_token_fails_closed(self, monkeypatch):
        """Trust mode ON + trust-root token that fails verification -> 401.

        Fail-closed: a definitive external-verification failure (bad
        signature, wrong audience, expired, missing revocation claim) must
        NOT fall through to the internal funnel for that token.
        """
        # Third-Party
        import jwt as pyjwt

        # First-Party
        from mcpgateway.utils import verify_credentials as vc

        token = pyjwt.encode({"iss": "https://idp.example.test", "sub": "ext", "exp": _exp()}, "k", algorithm="HS256")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret

        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        external_dispatch = AsyncMock(side_effect=vc.ExternalIssuerVerificationError("trust-root token failed verification"))
        monkeypatch.setattr(vc, "_maybe_verify_external", external_dispatch)
        internal_verifier = AsyncMock(return_value={"sub": "internal@example.com", "exp": _exp(), "jti": "internal-jti"})

        with patch("mcpgateway.auth.verify_jwt_token_cached", internal_verifier):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, request=SimpleNamespace(state=SimpleNamespace()))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        external_dispatch.assert_awaited_once()
        internal_verifier.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_mode_non_trust_root_token_falls_through_to_internal(self, monkeypatch):
        """Trust mode ON + issuer NOT a trust root -> internal funnel as today.

        The external dispatch returns None (not external-issuer material) and
        the internal verifier decides; a gateway-signed JWT still
        authenticates with trust mode ON (no regression).
        """
        # Third-Party
        import jwt as pyjwt

        # First-Party
        from mcpgateway.utils import verify_credentials as vc

        token = pyjwt.encode({"iss": "mcpgateway", "sub": "api@example.com", "exp": _exp()}, "k", algorithm="HS256")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret

        jwt_payload = {
            "sub": "api@example.com",
            "token_use": "api",
            "teams": ["api-team-1"],
            "exp": _exp(),
            "user": {"auth_provider": "api_token"},
        }

        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        external_dispatch = AsyncMock(return_value=None)
        monkeypatch.setattr(vc, "_maybe_verify_external", external_dispatch)
        internal_verifier = AsyncMock(return_value=jwt_payload)

        with patch("mcpgateway.auth.verify_jwt_token_cached", internal_verifier):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=_make_user("api@example.com")):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "api@example.com"
        assert request.state.token_use == "api"
        internal_verifier.assert_awaited_once()
