# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_exchange_integration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Module Description.
Module documentation...
"""

# tests/unit/mcpgateway/services/test_token_exchange_integration.py
# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayService
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager, OAuthTokenExchangeError
from mcpgateway.services.tool_service import ToolInvocationError, ToolService


class TestTokenExchangeConfigValidation:
    def test_token_exchange_requires_target_audience(self):
        cfg = {"grant_type": "token-exchange", "client_id": "cf", "token_url": "https://as/token"}
        with pytest.raises(ValueError, match="target_audience is required"):
            GatewayService._validate_token_exchange_config(cfg)

    def test_token_exchange_valid_config_passes(self):
        cfg = {
            "grant_type": "token-exchange",
            "client_id": "cf",
            "token_url": "https://as/token",
            "target_audience": "https://downstream",
        }
        # returns the (defaulted) config unchanged-ish; no raise
        out = GatewayService._validate_token_exchange_config(cfg)
        assert out["subject_token_source"] == "inbound_user_jwt"
        assert out["requested_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
        # RFC 8693 §3: default subject_token_type is "jwt" (CF's own inbound JWT),
        # not "access_token" (which implies an AS-issued token).
        assert out["subject_token_type"] == "urn:ietf:params:oauth:token-type:jwt"

    def test_non_exchange_grant_is_untouched(self):
        cfg = {"grant_type": "client_credentials", "client_id": "cf"}
        assert GatewayService._validate_token_exchange_config(cfg) == cfg

    def test_invalid_subject_token_source_rejected(self):
        cfg = {
            "grant_type": "token-exchange",
            "token_url": "https://as/token",
            "target_audience": "https://downstream",
            "subject_token_source": "bogus",
        }
        with pytest.raises(ValueError, match="subject_token_source"):
            GatewayService._validate_token_exchange_config(cfg)

    def test_token_url_must_pass_url_validation(self):
        # SSRF guard: the subject token (user's CF JWT) is POSTed to token_url,
        # so a non-trusted / internal URL must be rejected.
        cfg = {
            "grant_type": "token-exchange",
            "token_url": "http://169.254.169.254/latest/meta-data/",
            "target_audience": "https://downstream",
        }
        with pytest.raises(ValueError):
            GatewayService._validate_token_exchange_config(cfg)

    def test_user_oauth_token_source_rejected_at_gateway_config(self):
        # Fix 2: "user_oauth_token" is a valid ToolService source but not supported on the
        # gateway config path. Must fail at config time (not silently use wrong token at runtime).
        cfg = {
            "grant_type": "token-exchange",
            "token_url": "https://as/token",
            "target_audience": "https://downstream",
            "subject_token_source": "user_oauth_token",
        }
        with pytest.raises(ValueError, match="subject_token_source"):
            GatewayService._validate_token_exchange_config(cfg)


@pytest.mark.asyncio
class TestGetAccessTokenTokenExchange:
    async def test_token_exchange_branch_calls_token_exchange(self):
        mgr = OAuthManager()
        mgr.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        cfg = {
            "grant_type": "token-exchange",
            "client_id": "cf",
            "client_secret": "shh",  # pragma: allowlist secret
            "token_url": "https://as/token",
            "target_audience": "https://downstream",
            "scopes": ["a", "b"],
        }
        tok = await mgr.get_access_token(cfg, subject_token="user-jwt")
        assert tok == "exch-tok"
        mgr.token_exchange.assert_awaited_once()
        kwargs = mgr.token_exchange.await_args.kwargs
        assert kwargs["subject_token"] == "user-jwt"
        assert kwargs["audience"] == "https://downstream"

    async def test_token_exchange_missing_subject_token_raises(self):
        mgr = OAuthManager()
        cfg = {"grant_type": "token-exchange", "client_id": "cf", "token_url": "https://as/token", "target_audience": "aud"}
        with pytest.raises(OAuthError, match="subject token"):
            await mgr.get_access_token(cfg, subject_token=None)

    async def test_other_grants_still_dispatch_with_new_param(self):
        # G6 back-compat: adding subject_token must not disturb existing grant dispatch.
        mgr = OAuthManager()
        mgr._client_credentials_flow = AsyncMock(return_value="cc-tok")
        mgr._password_flow = AsyncMock(return_value="pw-tok")
        assert await mgr.get_access_token({"grant_type": "client_credentials"}) == "cc-tok"
        assert await mgr.get_access_token({"grant_type": "password"}) == "pw-tok"
        # authorization_code still requires interactive consent
        with pytest.raises(OAuthError):
            await mgr.get_access_token({"grant_type": "authorization_code"})
        # unknown grant still raises ValueError
        with pytest.raises(ValueError):
            await mgr.get_access_token({"grant_type": "bogus"})

    async def test_token_exchange_routes_full_config_to_token_exchange(self):
        # get_access_token passes the complete stored config via oauth_config so the
        # token_endpoint_auth_method (e.g. private_key_jwt) is honored at exchange time
        # and token_url is runtime-validated inside token_exchange.
        mgr = OAuthManager()
        mgr.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        mgr._prepare_runtime_credentials = AsyncMock()

        cfg = {"grant_type": "token-exchange", "client_id": "cf", "token_url": "https://as/token", "target_audience": "aud"}
        await mgr.get_access_token(cfg, subject_token="user-jwt")

        mgr._prepare_runtime_credentials.assert_not_awaited()
        mgr.token_exchange.assert_awaited_once()
        kwargs = mgr.token_exchange.await_args.kwargs
        assert kwargs["oauth_config"] is cfg
        assert kwargs["subject_token"] == "user-jwt"
        assert kwargs["audience"] == "aud"

    async def test_token_exchange_forwards_mtls_params(self):
        # Fix 4: ca_certificate/client_cert/client_key passed to get_access_token must be
        # forwarded to token_exchange() so mTLS against corporate-CA IdPs works.
        mgr = OAuthManager()
        mgr.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        mgr._prepare_runtime_credentials = AsyncMock(
            return_value={"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "client_secret": "s", "target_audience": "aud"}
        )  # pragma: allowlist secret

        cfg = {"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "target_audience": "aud"}
        await mgr.get_access_token(cfg, subject_token="user-jwt", ca_certificate="PEM", client_cert="cert", client_key="key")

        kwargs = mgr.token_exchange.await_args.kwargs
        assert kwargs["ca_certificate"] == "PEM"
        assert kwargs["client_cert"] == "cert"
        assert kwargs["client_key"] == "key"

    async def test_get_access_token_hands_decryption_to_token_exchange(self):
        # Decryption and token_endpoint_auth dispatch now happen inside token_exchange
        # via oauth_config, so get_access_token must not pre-decrypt the secret or pass
        # client_id/client_secret arguments.
        mgr = OAuthManager()
        mgr.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        mgr._prepare_runtime_credentials = AsyncMock()

        cfg = {"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "target_audience": "aud"}
        await mgr.get_access_token(cfg, subject_token="user-jwt")

        kwargs = mgr.token_exchange.await_args.kwargs
        assert kwargs["oauth_config"] is cfg
        assert "client_secret_is_plaintext" not in kwargs
        assert "client_id" not in kwargs
        assert "client_secret" not in kwargs
        assert "token_url" not in kwargs

    async def test_token_exchange_skips_inline_decrypt_when_plaintext(self):
        # When client_secret_is_plaintext=True, the inline decrypt block must not run,
        # so a plaintext secret that false-positives is_encrypted() is sent unchanged.
        # Standard
        from unittest.mock import patch

        mgr = OAuthManager()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"access_token": "exch", "token_type": "Bearer", "expires_in": 60})
        mgr._post_token_request = AsyncMock(return_value=resp)

        # A plaintext secret that looks like an encrypted v2 bundle (false positive).
        tricky_secret = "v2:looks-encrypted-but-isnt"  # pragma: allowlist secret

        with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_enc:
            await mgr.token_exchange(
                token_url="https://as/token",
                subject_token="user-jwt",
                client_id="cf",
                client_secret=tricky_secret,
                audience="aud",
                client_secret_is_plaintext=True,
            )
            # decrypt path never touched
            mock_enc.assert_not_called()

        # secret reached the AS unchanged
        sent = mgr._post_token_request.await_args.args[1]
        assert sent["client_secret"] == tricky_secret


# First-Party
from mcpgateway.utils.token_exchange_audit import audit_token_exchange


class TestTokenExchangeAudit:
    def test_audit_never_logs_raw_token(self, caplog):
        # Standard
        import logging

        with caplog.at_level(logging.INFO):
            audit_token_exchange(
                user_email="u@e",
                gateway_id="gw1",
                target_audience="https://downstream",
                success=True,
                expires_in=3600,
                upstream="https://upstream",
                error=None,
                latency_ms=42,
            )
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "u@e" in joined
        assert "https://downstream" in joined
        assert "token-exchange" in joined.lower()
        # raw token material must never appear
        assert "access_token" not in joined or "exch-tok" not in joined

    def test_audit_failure_records_error(self, caplog):
        # Standard
        import logging

        with caplog.at_level(logging.WARNING):
            audit_token_exchange(
                user_email="u@e",
                gateway_id="gw1",
                target_audience="aud",
                success=False,
                expires_in=None,
                upstream="https://upstream",
                error="403 Forbidden",
                latency_ms=12,
            )
        assert any("403 Forbidden" in r.getMessage() for r in caplog.records)

    def test_audit_structured_extra_has_no_token_keys(self, caplog):
        # G11: inspect the structured payload, not just the rendered line. No subject
        # or exchanged token material may be present; required forensic fields must be.
        # Standard
        import logging

        with caplog.at_level(logging.INFO):
            audit_token_exchange(
                user_email="u@e",
                gateway_id="gw1",
                target_audience="aud",
                success=True,
                expires_in=1800,
                upstream="https://upstream",
                error=None,
                latency_ms=42,
            )
        rec = next(r for r in caplog.records if hasattr(r, "token_exchange"))
        event = rec.token_exchange
        # forensic fields present
        assert event["user_email"] == "u@e"
        assert event["target_audience"] == "aud"
        assert event["exchanged_token_expires_in"] == 1800
        assert event["latency_ms"] == 42
        # no token-bearing keys leaked into the event
        forbidden = {"access_token", "subject_token", "client_secret"}
        assert forbidden.isdisjoint(event.keys())
        assert not any("token" in str(v).lower() and "exchange" not in str(v).lower() for v in event.values() if isinstance(v, str) and len(v) > 40)

    def test_audit_carries_correlation_and_request_id(self, caplog):
        # L3: forensic correlation to the originating request.
        # Standard
        import logging

        with caplog.at_level(logging.INFO):
            audit_token_exchange(
                user_email="u@e",
                gateway_id="gw1",
                target_audience="aud",
                success=True,
                expires_in=1800,
                upstream="https://upstream",
                error=None,
                latency_ms=42,
                correlation_id="corr-123",
                request_id="req-456",
            )
        event = next(r.token_exchange for r in caplog.records if hasattr(r, "token_exchange"))
        assert event["correlation_id"] == "corr-123"
        assert event["request_id"] == "req-456"

    @pytest.mark.parametrize("purpose", ["invocation", "discovery"])
    def test_audit_emits_purpose(self, caplog, purpose):
        # Standard
        import logging

        kwargs = {} if purpose == "invocation" else {"purpose": purpose}
        with caplog.at_level(logging.INFO):
            audit_token_exchange(user_email=None, gateway_id="gw1", target_audience=None, success=True, expires_in=60, upstream="https://upstream", error=None, latency_ms=1, **kwargs)
        rec = next(r for r in caplog.records if hasattr(r, "token_exchange"))
        assert rec.token_exchange["purpose"] == purpose
        assert f"purpose={purpose}" in rec.getMessage()


# First-Party
from mcpgateway.utils.subject_token import extract_inbound_bearer


class TestSubjectTokenExtraction:
    def test_extracts_bearer_case_insensitive(self):
        assert extract_inbound_bearer({"Authorization": "Bearer abc.def"}) == "abc.def"
        assert extract_inbound_bearer({"authorization": "bearer xyz"}) == "xyz"

    def test_returns_none_when_absent(self):
        assert extract_inbound_bearer({}) is None
        assert extract_inbound_bearer(None) is None

    def test_ignores_non_bearer_scheme(self):
        assert extract_inbound_bearer({"authorization": "Basic abc"}) is None


class TestLooksLikeJwt:
    def test_three_segment_token_is_jwt(self):
        # First-Party
        from mcpgateway.utils.subject_token import looks_like_jwt

        assert looks_like_jwt("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.sig") is True  # pragma: allowlist secret

    def test_opaque_token_is_not_jwt(self):
        # First-Party
        from mcpgateway.utils.subject_token import looks_like_jwt

        assert looks_like_jwt("opaque-token") is False
        assert looks_like_jwt(None) is False
        assert looks_like_jwt("a.b") is False

    def test_jwt_edge_cases(self):
        # G12: empty segment and 4-segment strings are not compact-serialization JWTs.
        # First-Party
        from mcpgateway.utils.subject_token import looks_like_jwt

        assert looks_like_jwt("a..b") is False  # empty middle segment
        assert looks_like_jwt("a.b.c.d") is False  # too many segments
        assert looks_like_jwt("") is False
        assert looks_like_jwt("...") is False


# A minimal but structurally-valid JWT (header.payload.signature) for subject-token checks.
_FAKE_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1QGUifQ.sig"  # pragma: allowlist secret

_TE_CFG = {"grant_type": "token-exchange", "target_audience": "aud", "token_url": "https://as/token", "subject_token_source": "inbound_user_jwt"}


@pytest.mark.asyncio
@pytest.mark.parametrize("service_class,error_class", [(ToolService, ToolInvocationError), (GatewayService, GatewayConnectionError)])
async def test_same_user_denied_credential_stays_denied(service_class, error_class):
    """Keep denied credentials isolated from another credential's warm cache."""
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from tests.helpers.auth import make_test_jwt

    email = "credential-isolation@example.test"
    session = make_test_jwt(email, extra_payload={"token_use": "session", "jti": "session-credential"})
    api = make_test_jwt(email, extra_payload={"jti": "api-credential"})
    service = service_class()
    service._token_exchange_cache = TokenExchangeCache(redis_url=None)

    async def exchange(**kwargs):
        if kwargs["subject_token"] != session:
            raise OAuthError("subject credential denied")
        return {"access_token": "synthetic-upstream-bearer", "expires_in": 3600}

    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock(side_effect=exchange)
    args = (dict(_TE_CFG), "credential-gateway", "credential-gateway", email)
    with pytest.raises(error_class):
        await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {api}"})
    service._token_exchange_cache = TokenExchangeCache(redis_url=None)
    allowed = await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {session}"})
    before = service.oauth_manager.token_exchange.await_count
    with pytest.raises(error_class):
        await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {api}"})
    assert service.oauth_manager.token_exchange.await_count == before + 1
    assert await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {session}"}) == allowed
    assert service.oauth_manager.token_exchange.await_count == before + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("service_class,error_class", [(ToolService, ToolInvocationError), (GatewayService, GatewayConnectionError)])
@pytest.mark.parametrize("headers", [None, {"authorization": "Bearer malformed"}, {"authorization": "Bearer opaque-token"}])
async def test_warm_cache_rejects_unusable_subject_before_cache_access(service_class, error_class, headers):
    """Reject missing and non-JWT credentials before checking a warm cache."""
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache

    service = service_class()
    cache = TokenExchangeCache(redis_url=None)
    service._token_exchange_cache = cache
    cache.get = AsyncMock(wraps=cache.get)
    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock()
    with pytest.raises(error_class):
        await service._resolve_token_exchange_header(dict(_TE_CFG), "gw", "gw", "u@e", headers)
    cache.get.assert_not_awaited()
    service.oauth_manager.token_exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_gateway_opaque_bearer_does_not_fall_back_to_valid_cookie():
    """Keep the authenticated bearer authoritative when a different cookie is present."""
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache

    service = GatewayService()
    cache = TokenExchangeCache(redis_url=None)
    service._token_exchange_cache = cache
    cache.get = AsyncMock(wraps=cache.get)
    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock()
    headers = {"authorization": "Bearer opaque-token", "cookie": f"jwt_token={_FAKE_JWT}"}
    with pytest.raises(GatewayConnectionError):
        await service._resolve_token_exchange_header(dict(_TE_CFG), "gw", "gw", "u@e", headers)
    cache.get.assert_not_awaited()
    service.oauth_manager.token_exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_negative_cache_and_warm_tokens_are_subject_specific():
    """A failed exchange for one JWT must not block another JWT for the same user."""
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from tests.helpers.auth import make_test_jwt

    service = ToolService()
    service._token_exchange_cache = TokenExchangeCache(redis_url=None)
    a = make_test_jwt("same@example.test", extra_payload={"jti": "subject-a"})
    b = make_test_jwt("same@example.test", extra_payload={"jti": "subject-b"})

    async def exchange(**kwargs):
        if kwargs["subject_token"] == b:
            raise OAuthError("denied")
        return {"access_token": "upstream-a", "expires_in": 3600}

    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock(side_effect=exchange)
    args = (dict(_TE_CFG), "gw", "gw", "same@example.test")
    with pytest.raises(ToolInvocationError):
        await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {b}"})
    assert await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {a}"}) == {"Authorization": "Bearer upstream-a"}
    with pytest.raises(ToolInvocationError, match="unavailable"):
        await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {b}"})
    assert await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {a}"}) == {"Authorization": "Bearer upstream-a"}
    assert service.oauth_manager.token_exchange.await_count == 2


@pytest.mark.asyncio
async def test_same_type_jwts_with_different_jti_exchange_independently():
    """Include the complete JWT identity when claims share a principal."""
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from tests.helpers.auth import make_test_jwt

    service = ToolService()
    service._token_exchange_cache = TokenExchangeCache(redis_url=None)
    first = make_test_jwt("same@example.test", extra_payload={"jti": "jwt-one"})
    second = make_test_jwt("same@example.test", extra_payload={"jti": "jwt-two"})
    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock(side_effect=[{"access_token": "one", "expires_in": 3600}, {"access_token": "two", "expires_in": 3600}])
    args = (dict(_TE_CFG), "gw", "gw", "same@example.test")
    assert await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {first}"}) == {"Authorization": "Bearer one"}
    assert await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {second}"}) == {"Authorization": "Bearer two"}
    assert service.oauth_manager.token_exchange.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_distinct_subjects_receive_only_their_exchange():
    """Distinct JWTs use separate single-flight locks and cache entries."""
    import asyncio
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from tests.helpers.auth import make_test_jwt

    service = ToolService()
    service._token_exchange_cache = TokenExchangeCache(redis_url=None)
    first = make_test_jwt("same@example.test", extra_payload={"jti": "concurrent-one"})
    second = make_test_jwt("same@example.test", extra_payload={"jti": "concurrent-two"})

    async def exchange(**kwargs):
        await asyncio.sleep(0)
        return {"access_token": "for-one" if kwargs["subject_token"] == first else "for-two", "expires_in": 3600}

    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock(side_effect=exchange)
    args = (dict(_TE_CFG), "gw", "gw", "same@example.test")
    results = await asyncio.gather(
        service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {first}"}),
        service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {second}"}),
    )
    assert results == [{"Authorization": "Bearer for-one"}, {"Authorization": "Bearer for-two"}]
    assert service.oauth_manager.token_exchange.await_count == 2


@pytest.mark.asyncio
async def test_401_invalidates_only_the_exact_subject_and_retries_once():
    """Evict only the JWT that received 401 and perform one refresh."""
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from tests.helpers.auth import make_test_jwt

    service = ToolService()
    service._token_exchange_cache = TokenExchangeCache(redis_url=None)
    first = make_test_jwt("same@example.test", extra_payload={"jti": "refresh-one"})
    second = make_test_jwt("same@example.test", extra_payload={"jti": "refresh-two"})
    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock(
        side_effect=[
            {"access_token": "one-old", "expires_in": 3600},
            {"access_token": "two", "expires_in": 3600},
            {"access_token": "one-new", "expires_in": 3600},
        ]
    )
    args = (dict(_TE_CFG), "gw", "gw", "same@example.test")
    old = await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {first}"})
    await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {second}"})
    sends = []

    async def send(headers):
        sends.append(headers)
        response = MagicMock()
        response.status_code = 401 if len(sends) == 1 else 200
        return response

    response = await service._send_with_token_exchange_retry(send, old, dict(_TE_CFG), "gw", "gw", "same@example.test", {"authorization": f"Bearer {first}"})
    assert response.status_code == 200
    assert [headers["Authorization"] for headers in sends] == ["Bearer one-old", "Bearer one-new"]
    assert await service._resolve_token_exchange_header(*args, {"authorization": f"Bearer {second}"}) == {"Authorization": "Bearer two"}
    assert service.oauth_manager.token_exchange.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service_class,error_class,module_name",
    [
        (ToolService, ToolInvocationError, "mcpgateway.services.tool_service"),
        (GatewayService, GatewayConnectionError, "mcpgateway.services.gateway_service"),
    ],
)
@pytest.mark.parametrize("fail", [False, True])
async def test_audit_and_logs_keep_correlation_without_raw_tokens(service_class, error_class, module_name, fail, caplog):
    """Carry real correlation IDs into audit and logs without exposing credentials."""
    import importlib
    import logging
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from tests.helpers.auth import make_test_jwt

    subject = make_test_jwt("audit@example.test", extra_payload={"jti": "audit-subject"})
    exchanged = "synthetic-exchanged-secret"
    correlation_id = "correlation-real-711"
    service = service_class()
    service._token_exchange_cache = TokenExchangeCache(redis_url=None)
    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock(side_effect=OAuthError("synthetic failure") if fail else None)
    if not fail:
        service.oauth_manager.token_exchange.return_value = {"access_token": exchanged, "expires_in": 3600}
    sec_logger = MagicMock()
    module = importlib.import_module(module_name)
    with patch.object(module, "audit_token_exchange") as audit, patch.object(module, "get_structured_logger", return_value=sec_logger), caplog.at_level(logging.INFO):
        call = service._resolve_token_exchange_header(dict(_TE_CFG), "audit-gateway", "audit-gateway", "audit@example.test", {"authorization": f"Bearer {subject}", "x-correlation-id": correlation_id})
        if fail:
            with pytest.raises(error_class):
                await call
        else:
            assert await call == {"Authorization": f"Bearer {exchanged}"}
    assert audit.call_args.kwargs["correlation_id"] == correlation_id
    structured_logs = repr(sec_logger.log.call_args_list)
    assert correlation_id in structured_logs
    captured = " ".join(record.getMessage() for record in caplog.records) + structured_logs + repr(audit.call_args_list)
    assert correlation_id in captured
    assert subject not in captured
    assert exchanged not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_tool_call_exchange_audits_invocation_purpose(fail, caplog):
    """The per-user exchange on the tool-call path emits ``purpose="invocation"``."""
    import logging
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from tests.helpers.auth import make_test_jwt

    subject = make_test_jwt("purpose@example.test", extra_payload={"jti": "purpose-subject"})
    service = ToolService()
    service._token_exchange_cache = TokenExchangeCache(redis_url=None)
    service.oauth_manager = MagicMock()
    service.oauth_manager.token_exchange = AsyncMock(side_effect=OAuthError("synthetic failure") if fail else None, return_value={"access_token": "exch", "expires_in": 3600})
    with caplog.at_level(logging.INFO, logger="mcpgateway.audit.token_exchange"):
        call = service._resolve_token_exchange_header(dict(_TE_CFG), "gw", "gw", "purpose@example.test", {"authorization": f"Bearer {subject}"})
        if fail:
            with pytest.raises(ToolInvocationError):
                await call
        else:
            await call
    events = [r.token_exchange for r in caplog.records if hasattr(r, "token_exchange")]
    assert len(events) == 1
    assert events[0]["purpose"] == "invocation"
    assert events[0]["success"] is (not fail)


def _mock_te_cache(get_return=None, failed=False):
    """A MagicMock TokenExchangeCache with all async methods + single-flight lock stubbed."""
    # Standard
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    c = MagicMock()
    c.get = AsyncMock(return_value=get_return)
    c.set = AsyncMock()
    c.invalidate = AsyncMock()
    c.is_failed = AsyncMock(return_value=failed)
    c.set_failure = AsyncMock()
    c.lock = MagicMock(return_value=asyncio.Lock())
    return c


@pytest.mark.asyncio
class TestToolPathTokenExchange:
    async def test_resolve_header_exchanges_and_forwards_exchanged_token(self):
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 1800})
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        header = await svc._resolve_token_exchange_header(
            oauth_config=dict(_TE_CFG),
            gateway_id="gw1",
            gateway_name="gw",
            app_user_email="u@e",
            request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
        )
        assert header == {"Authorization": "Bearer exch-tok"}
        # exchanged token used, NOT the user jwt
        assert _FAKE_JWT not in header["Authorization"]
        svc.oauth_manager.token_exchange.assert_awaited_once()
        assert svc.oauth_manager.token_exchange.await_args.kwargs["subject_token"] == _FAKE_JWT
        # B1: cached with the REAL expires_in from the response, not a hardcoded default.
        assert svc._token_exchange_cache.set.await_args.kwargs.get("expires_in", svc._token_exchange_cache.set.await_args.args[-1]) == 1800

    async def test_resolve_header_forwards_ca_and_mtls_to_token_exchange(self):
        # Regression: the token-exchange call to the AS must carry the gateway's
        # configured CA certificate / mTLS client cert+key, same as the
        # client_credentials grant does -- otherwise an AS behind a private CA or
        # requiring mTLS is unreachable for token-exchange gateways.
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 1800})
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        await svc._resolve_token_exchange_header(
            oauth_config=dict(_TE_CFG),
            gateway_id="gw1",
            gateway_name="gw",
            app_user_email="u@e",
            request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            ca_certificate="ca-pem",
            client_cert="cert-pem",
            client_key="key-pem",
        )
        kwargs = svc.oauth_manager.token_exchange.await_args.kwargs
        assert kwargs["ca_certificate"] == "ca-pem"
        assert kwargs["client_cert"] == "cert-pem"
        assert kwargs["client_key"] == "key-pem"

    async def test_cache_hit_skips_exchange(self):
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock()
        svc._token_exchange_cache = _mock_te_cache(get_return="cached-tok")

        header = await svc._resolve_token_exchange_header(
            oauth_config=dict(_TE_CFG),
            gateway_id="gw1",
            gateway_name="gw",
            app_user_email="u@e",
            request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
        )
        assert header == {"Authorization": "Bearer cached-tok"}
        svc.oauth_manager.token_exchange.assert_not_awaited()

    async def test_negative_cache_fast_fails(self):
        # P4: a recently-failed key short-circuits before any subject resolution / AS call.
        # First-Party
        from mcpgateway.services.tool_service import ToolInvocationError, ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock()
        svc._token_exchange_cache = _mock_te_cache(get_return=None, failed=True)
        with pytest.raises(ToolInvocationError, match="unavailable"):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG),
                gateway_id="gw1",
                gateway_name="gw",
                app_user_email="u@e",
                request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            )
        svc.oauth_manager.token_exchange.assert_not_awaited()

    async def test_single_flight_collapses_concurrent_misses(self):
        # P1: 10 concurrent cache-miss callers must trigger exactly ONE exchange.
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.services.token_exchange_cache import TokenExchangeCache
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc._token_exchange_cache = TokenExchangeCache(redis_url=None)  # real memory cache + real lock
        svc.oauth_manager = MagicMock()
        calls = {"n": 0}

        async def _exchange(**_kw):
            calls["n"] += 1
            await asyncio.sleep(0.01)  # widen the race window
            return {"access_token": "exch-tok", "expires_in": 3600}

        svc.oauth_manager.token_exchange = AsyncMock(side_effect=_exchange)
        headers = {"authorization": f"Bearer {_FAKE_JWT}"}
        results = await asyncio.gather(*[svc._resolve_token_exchange_header(dict(_TE_CFG), "gw1", "gw", "u@e", headers) for _ in range(10)])
        assert all(r == {"Authorization": "Bearer exch-tok"} for r in results)
        assert calls["n"] == 1  # single-flight collapsed 10 misses into 1 exchange

    async def test_missing_subject_token_denies(self):
        # First-Party
        from mcpgateway.services.tool_service import ToolInvocationError, ToolService

        svc = ToolService()
        svc._token_exchange_cache = _mock_te_cache(get_return=None)
        with pytest.raises(ToolInvocationError, match="authentication required"):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG),
                gateway_id="gw1",
                gateway_name="gw",
                app_user_email="u@e",
                request_headers={},  # no bearer
            )

    @pytest.mark.parametrize("empty_email", [None, ""])
    async def test_empty_app_user_email_denies_before_cache_lookup(self, empty_email):
        # Regression: an empty/None app_user_email must never collapse into a shared
        # cache key ("") -- that would let unrelated callers share one delegated
        # token (cross-user leakage of an RFC 8693 exchanged token). The guard must
        # fire before any cache interaction, not just before the AS call.
        # First-Party
        from mcpgateway.services.tool_service import ToolInvocationError, ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock()
        svc._token_exchange_cache = _mock_te_cache(get_return=None)
        with pytest.raises(ToolInvocationError, match="authenticated user identity"):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG),
                gateway_id="gw1",
                gateway_name="gw",
                app_user_email=empty_email,
                request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            )
        svc._token_exchange_cache.get.assert_not_awaited()
        svc._token_exchange_cache.is_failed.assert_not_awaited()
        svc.oauth_manager.token_exchange.assert_not_awaited()

    async def test_invalidate_on_unauthorized_noop_without_user_email(self):
        # Companion fix: with nothing ever cached under an empty user key,
        # invalidation for an anonymous caller must be a no-op, not a call
        # into the cache with a "" key.
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc._token_exchange_cache = _mock_te_cache()
        await svc._invalidate_token_exchange_on_unauthorized(401, dict(_TE_CFG), "gw1", None, {"authorization": f"Bearer {_FAKE_JWT}"})
        svc._token_exchange_cache.invalidate.assert_not_awaited()

    async def test_non_jwt_subject_token_denies(self):
        # H2: an opaque/non-JWT inbound bearer must not be shipped to the AS.
        # First-Party
        from mcpgateway.services.tool_service import ToolInvocationError, ToolService

        svc = ToolService()
        svc._token_exchange_cache = _mock_te_cache(get_return=None)
        with pytest.raises(ToolInvocationError, match="authentication required"):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG),
                gateway_id="gw1",
                gateway_name="gw",
                app_user_email="u@e",
                request_headers={"authorization": "Bearer opaque-not-a-jwt"},
            )

    async def test_exchange_failure_message_is_generic_and_not_cached(self):
        # H1: AS error detail must not leak to the caller; positive cache must stay empty,
        # negative cache must be set (P4).
        # First-Party
        from mcpgateway.services.tool_service import ToolInvocationError, ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(side_effect=Exception("AS said: subject_token=eyJ... is invalid"))
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        with pytest.raises(ToolInvocationError) as ei:
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG),
                gateway_id="gw1",
                gateway_name="gw",
                app_user_email="u@e",
                request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            )
        # generic message; no token / AS body echoed
        assert "eyJ" not in str(ei.value)
        assert "subject_token" not in str(ei.value)
        svc._token_exchange_cache.set.assert_not_awaited()
        svc._token_exchange_cache.set_failure.assert_awaited_once()

    async def test_exchange_failure_log_omits_exc_info(self, monkeypatch):
        # CWE-532: exc_info=True renders str(exc) unredacted as the traceback's final
        # line regardless of how sanitized the log *message* is, re-leaking AS response
        # content into the log record. The warning log for a failed exchange must not
        # request a traceback.
        # First-Party
        import mcpgateway.services.tool_service as tsmod
        from mcpgateway.services.tool_service import ToolInvocationError, ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(side_effect=Exception("AS said: refresh_token=super-secret is invalid"))
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        mock_warning = MagicMock()
        monkeypatch.setattr(tsmod.logger, "warning", mock_warning)

        with pytest.raises(ToolInvocationError):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG),
                gateway_id="gw1",
                gateway_name="gw",
                app_user_email="u@e",
                request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            )

        assert mock_warning.called
        _, kwargs = mock_warning.call_args
        assert not kwargs.get("exc_info")


# First-Party
from mcpgateway.services.tool_service import ToolService


class TestPassthroughHardening:
    def test_authorization_excluded_from_passthrough_for_token_exchange(self):
        # B3: the exchanged Authorization must win; inbound user JWT must not pass through.
        allowed = ["authorization", "x-trace-id"]
        result = ToolService._sanitize_passthrough_for_token_exchange(allowed, grant_type="token-exchange")
        assert "authorization" not in [h.lower() for h in result]
        assert "x-trace-id" in result

    def test_passthrough_untouched_for_other_grants(self):
        allowed = ["authorization", "x-trace-id"]
        result = ToolService._sanitize_passthrough_for_token_exchange(allowed, grant_type="client_credentials")
        assert result == allowed


@pytest.mark.asyncio
class TestUnauthorizedInvalidation:
    async def test_upstream_401_invalidates_cache(self):
        # Standard
        from unittest.mock import AsyncMock, MagicMock

        svc = ToolService()
        svc._token_exchange_cache = MagicMock()
        svc._token_exchange_cache.invalidate = AsyncMock()

        await svc._invalidate_token_exchange_on_unauthorized(
            status_code=401,
            oauth_config={"grant_type": "token-exchange", "target_audience": "aud"},
            gateway_id="gw1",
            app_user_email="u@e",
            request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
        )
        svc._token_exchange_cache.invalidate.assert_awaited_once_with("gw1", "u@e", "aud", subject_token=_FAKE_JWT, variant="")

    async def test_non_401_does_not_invalidate(self):
        # Standard
        from unittest.mock import AsyncMock, MagicMock

        svc = ToolService()
        svc._token_exchange_cache = MagicMock()
        svc._token_exchange_cache.invalidate = AsyncMock()

        await svc._invalidate_token_exchange_on_unauthorized(
            status_code=200,
            oauth_config={"grant_type": "token-exchange", "target_audience": "aud"},
            gateway_id="gw1",
            app_user_email="u@e",
            request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
        )
        svc._token_exchange_cache.invalidate.assert_not_awaited()


class TestPassthroughMergeOutcome:
    def test_exchanged_token_wins_over_inbound_when_authorization_passthrough(self):
        # B3 outcome (not just the helper): feed the sanitized list through the real merge and
        # prove the exchanged Authorization survives, never the inbound user JWT.
        # First-Party
        from mcpgateway.services.tool_service import compute_passthrough_headers_cached, ToolService

        inbound = {"authorization": f"Bearer {_FAKE_JWT}", "x-trace-id": "t1"}
        base = {"Authorization": "Bearer exch-tok"}  # set by the resolver
        allowed = ToolService._sanitize_passthrough_for_token_exchange(["authorization", "x-trace-id"], "token-exchange")
        merged = compute_passthrough_headers_cached(inbound, base, allowed, gateway_auth_type="oauth", gateway_passthrough_headers=None)
        auth = next(v for k, v in merged.items() if k.lower() == "authorization")
        assert auth == "Bearer exch-tok"
        assert _FAKE_JWT not in auth

    def test_x_upstream_authorization_cannot_override_exchanged_token(self):
        # The X-Upstream-Authorization rename runs before the allow-list check, so
        # _sanitize_passthrough_for_token_exchange() (which only strips "authorization"
        # from the allow-list) never reaches it. Without is_token_exchange=True, a
        # caller-supplied X-Upstream-Authorization would silently replace the
        # resolver's exchanged Authorization header.
        # First-Party
        from mcpgateway.services.tool_service import compute_passthrough_headers_cached

        inbound = {"x-upstream-authorization": "Bearer attacker"}
        base = {"Authorization": "Bearer exchanged"}  # set by _resolve_token_exchange_header
        merged = compute_passthrough_headers_cached(inbound, base, [], gateway_auth_type="oauth", gateway_passthrough_headers=None, is_token_exchange=True)
        assert merged["Authorization"] == "Bearer exchanged"


@pytest.mark.asyncio
class TestUnauthorizedRetryOnce:
    async def test_401_triggers_single_reexchange_then_succeeds(self):
        # B2 end-to-end: first send 401 -> invalidate + re-resolve -> second send 200. Exactly one retry.
        # Standard
        from unittest.mock import AsyncMock, MagicMock

        # First-Party
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc._token_exchange_cache = MagicMock()
        svc._token_exchange_cache.invalidate = AsyncMock()
        svc._resolve_token_exchange_header = AsyncMock(return_value={"Authorization": "Bearer fresh-tok"})

        sends = []

        async def _send(headers):
            sends.append(headers)
            resp = MagicMock()
            resp.status_code = 401 if len(sends) == 1 else 200
            return resp

        cfg = {"grant_type": "token-exchange", "target_audience": "aud"}
        resp = await svc._send_with_token_exchange_retry(
            _send,
            {"Authorization": "Bearer stale-tok"},
            cfg,
            "gw1",
            "gw",
            "u@e",
            {"authorization": f"Bearer {_FAKE_JWT}"},
        )
        assert resp.status_code == 200
        assert len(sends) == 2  # exactly one retry, no loop
        assert sends[1] == {"Authorization": "Bearer fresh-tok"}
        svc._token_exchange_cache.invalidate.assert_awaited_once()

    async def test_401_retry_preserves_original_headers_besides_authorization(self):
        # Regression: the retry must merge the fresh Authorization into the original
        # headers, not replace them wholesale -- otherwise Content-Type, header_mapping
        # output, identity-propagation headers, and session-affinity headers are lost
        # on the retried call.
        # Standard
        from unittest.mock import AsyncMock, MagicMock

        # First-Party
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc._token_exchange_cache = MagicMock()
        svc._token_exchange_cache.invalidate = AsyncMock()
        svc._resolve_token_exchange_header = AsyncMock(return_value={"Authorization": "Bearer fresh-tok"})

        sends = []

        async def _send(headers):
            sends.append(headers)
            resp = MagicMock()
            resp.status_code = 401 if len(sends) == 1 else 200
            return resp

        cfg = {"grant_type": "token-exchange", "target_audience": "aud"}
        original_headers = {"Authorization": "Bearer stale-tok", "Content-Type": "application/json", "X-Mcp-Session-Id": "sess-1"}
        resp = await svc._send_with_token_exchange_retry(
            _send,
            original_headers,
            cfg,
            "gw1",
            "gw",
            "u@e",
            {"authorization": f"Bearer {_FAKE_JWT}"},
        )
        assert resp.status_code == 200
        assert sends[1]["Authorization"] == "Bearer fresh-tok"
        assert sends[1]["Content-Type"] == "application/json"
        assert sends[1]["X-Mcp-Session-Id"] == "sess-1"

    async def test_persistent_401_retries_only_once(self):
        # Standard
        from unittest.mock import AsyncMock, MagicMock

        # First-Party
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc._token_exchange_cache = MagicMock()
        svc._token_exchange_cache.invalidate = AsyncMock()
        svc._resolve_token_exchange_header = AsyncMock(return_value={"Authorization": "Bearer fresh-tok"})

        count = {"n": 0}

        async def _send(headers):
            count["n"] += 1
            resp = MagicMock()
            resp.status_code = 401
            return resp

        cfg = {"grant_type": "token-exchange", "target_audience": "aud"}
        resp = await svc._send_with_token_exchange_retry(_send, {"Authorization": "Bearer x"}, cfg, "gw1", "gw", "u@e", {})
        assert resp.status_code == 401
        assert count["n"] == 2  # initial + one retry, never more


class TestGatewayServiceSanitizeMirror:
    """GatewayService._sanitize_passthrough_for_token_exchange mirrors ToolService (B3)."""

    def test_sanitize_drops_authorization_for_token_exchange(self):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayService

        result = GatewayService._sanitize_passthrough_for_token_exchange(["authorization", "x-trace-id"], grant_type="token-exchange")
        assert "authorization" not in [h.lower() for h in result]
        assert "x-trace-id" in result

    def test_sanitize_noop_for_other_grants(self):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayService

        allowed = ["authorization", "x-trace-id"]
        assert GatewayService._sanitize_passthrough_for_token_exchange(allowed, grant_type="client_credentials") == allowed

    def test_sanitize_noop_for_empty_passthrough(self):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayService

        assert GatewayService._sanitize_passthrough_for_token_exchange([], grant_type="token-exchange") == []


@pytest.mark.asyncio
class TestGatewayServiceTokenExchangeResolver:
    """GatewayService._resolve_token_exchange_header, used by manual gateway refresh.

    Mirrors ToolService's resolver tests: an explicitly authenticated manual refresh
    must perform a real RFC 8693 exchange of the caller's inbound JWT, never forward
    it raw, and never populate tools without a valid exchanged token.
    """

    async def test_resolve_header_exchanges_and_forwards_exchanged_token(self):
        svc = GatewayService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 1800})
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        header = await svc._resolve_token_exchange_header(
            oauth_config=dict(_TE_CFG),
            gateway_id="gw1",
            gateway_name="gw",
            app_user_email="u@e",
            request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
        )
        assert header == {"Authorization": "Bearer exch-tok"}
        assert _FAKE_JWT not in header["Authorization"]
        assert svc.oauth_manager.token_exchange.await_args.kwargs["subject_token"] == _FAKE_JWT

    async def test_resolve_header_forwards_ca_and_mtls(self):
        svc = GatewayService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 1800})
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        await svc._resolve_token_exchange_header(
            oauth_config=dict(_TE_CFG),
            gateway_id="gw1",
            gateway_name="gw",
            app_user_email="u@e",
            request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            ca_certificate="ca-pem",
            client_cert="cert-pem",
            client_key="key-pem",
        )
        kwargs = svc.oauth_manager.token_exchange.await_args.kwargs
        assert kwargs["ca_certificate"] == "ca-pem"
        assert kwargs["client_cert"] == "cert-pem"
        assert kwargs["client_key"] == "key-pem"

    async def test_cache_hit_skips_exchange(self):
        svc = GatewayService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock()
        svc._token_exchange_cache = _mock_te_cache(get_return="cached-tok")

        header = await svc._resolve_token_exchange_header(
            oauth_config=dict(_TE_CFG),
            gateway_id="gw1",
            gateway_name="gw",
            app_user_email="u@e",
            request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
        )
        assert header == {"Authorization": "Bearer cached-tok"}
        svc.oauth_manager.token_exchange.assert_not_awaited()

    async def test_missing_subject_token_denies(self):
        svc = GatewayService()
        svc._token_exchange_cache = _mock_te_cache(get_return=None)
        with pytest.raises(GatewayConnectionError, match="authentication required"):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG),
                gateway_id="gw1",
                gateway_name="gw",
                app_user_email="u@e",
                request_headers={},
            )

    async def test_exchange_failure_message_is_generic_and_not_cached(self):
        svc = GatewayService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(side_effect=Exception("AS said: subject_token=eyJ... is invalid"))
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        with pytest.raises(GatewayConnectionError) as ei:
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG),
                gateway_id="gw1",
                gateway_name="gw",
                app_user_email="u@e",
                request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            )
        assert "eyJ" not in str(ei.value)
        svc._token_exchange_cache.set.assert_not_awaited()
        svc._token_exchange_cache.set_failure.assert_awaited_once()


@pytest.mark.asyncio
class TestRestIntegrationB2Wiring:
    """B2 end-to-end via the REST-integration call site in invoke_tool.

    Proves the REST upstream HTTP send (self._http_client.request/get) is routed
    through _send_with_token_exchange_retry for a gateway with
    grant_type == "token-exchange": a 401 invalidates the cached exchanged token,
    re-resolves it, and retries exactly once with the fresh Authorization header.
    """

    async def test_rest_tool_401_triggers_single_reexchange_then_succeeds(self):
        # Standard
        from unittest.mock import AsyncMock, MagicMock, Mock, patch

        # First-Party
        from mcpgateway.cache.global_config_cache import global_config_cache
        from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache
        from mcpgateway.db import Gateway as DbGateway
        from mcpgateway.db import Tool as DbTool
        from mcpgateway.services.tool_service import ToolService

        # Reset caches so the DB lookup path runs (no stale entries from other tests).
        tool_lookup_cache.invalidate_all_local()
        global_config_cache.invalidate()

        svc = ToolService()
        svc._http_client = AsyncMock()
        svc.get_plugin_manager = AsyncMock()

        # Cached exchanged token -> invalidate -> fresh token after re-exchange.
        svc._token_exchange_cache = MagicMock()
        svc._token_exchange_cache.invalidate = AsyncMock()
        svc._resolve_token_exchange_header = AsyncMock(return_value={"Authorization": "Bearer fresh-tok"})

        # Gateway configured for token-exchange.
        mock_gateway = MagicMock(spec=DbGateway)
        mock_gateway.id = "gw1"
        mock_gateway.name = "test_gateway"
        mock_gateway.slug = "test-gateway"
        mock_gateway.url = "http://example.com/gateway"
        mock_gateway.auth_type = "oauth"
        mock_gateway.auth_value = {}
        mock_gateway.oauth_config = {"grant_type": "token-exchange", "target_audience": "aud"}
        mock_gateway.passthrough_headers = []
        mock_gateway.auth_query_params = None
        mock_gateway.ca_certificate = None
        mock_gateway.ca_certificate_sig = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_gateway.enabled = True
        mock_gateway.reachable = True

        # REST tool hanging off the token-exchange gateway.
        mock_tool = MagicMock(spec=DbTool)
        mock_tool.id = "1"
        mock_tool.original_name = "test_tool"
        mock_tool.name = "test-gateway-test-tool"
        mock_tool.custom_name = "test_tool"
        mock_tool.custom_name_slug = "test-tool"
        mock_tool.gateway_slug = "test-gateway"
        mock_tool.display_name = None
        mock_tool.url = "http://example.com/tools/test"
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.headers = {}
        mock_tool.input_schema = {"type": "object", "properties": {}}
        mock_tool.output_schema = None
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_type = None
        mock_tool.auth_value = None
        mock_tool.gateway_id = mock_gateway.id
        mock_tool.gateway = mock_gateway
        mock_tool.annotations = {}
        mock_tool.tags = []
        mock_tool.team = None
        mock_tool.team_id = None
        mock_tool.visibility = "public"
        mock_tool.owner_email = "admin@admin.org"
        mock_tool.enabled = True
        mock_tool.deprecated = False
        mock_tool.reachable = True
        mock_tool.query_mapping = None
        mock_tool.header_mapping = None
        mock_tool.timeout_ms = None

        test_db = MagicMock()
        mock_scalar_tool = Mock()
        mock_scalar_tool.scalar_one_or_none.return_value = mock_tool
        mock_scalar_tool.scalars.return_value = mock_scalar_tool
        mock_scalar_tool.all.return_value = [mock_tool]
        test_db.execute = Mock(return_value=mock_scalar_tool)

        mock_global_config = MagicMock()
        mock_global_config.passthrough_headers = []
        mock_query_result = Mock()
        mock_query_result.first.return_value = mock_global_config
        test_db.query = Mock(return_value=mock_query_result)

        # First call -> 401, second call -> 200.
        responses = []

        def _make_response(status_code):
            resp = AsyncMock()
            resp.status_code = status_code
            resp.raise_for_status = Mock()
            resp.json = Mock(return_value={"result": "ok"})
            return resp

        async def _get(_url, params=None, headers=None, **_kwargs):
            responses.append(headers)
            status = 401 if len(responses) == 1 else 200
            return _make_response(status)

        pinned_client = MagicMock()
        pinned_client.get = AsyncMock(side_effect=_get)
        pinned_client.request = AsyncMock()
        pinned_client.aclose = AsyncMock()

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with (
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch(
                "mcpgateway.services.tool_service.SecurityValidator.validate_url_for_connection_pinning",
                AsyncMock(
                    return_value={
                        "validated_url": mock_tool.url,
                        "hostname": "example.com",
                        "original_authority": "example.com",
                        "resolved_ip": "93.184.216.34",
                    }
                ),
            ),
            patch("mcpgateway.services.tool_service._build_pinned_rest_http_client", return_value=pinned_client),
        ):
            result = await svc.invoke_tool(test_db, "test_tool", {}, request_headers={"authorization": f"Bearer {_FAKE_JWT}"}, app_user_email="u@e")

        assert result.content[0].text == '{\n  "result": "ok"\n}'
        assert len(responses) == 2  # exactly one retry
        # Second attempt carried the freshly re-exchanged Authorization header.
        assert responses[1].get("Authorization") == "Bearer fresh-tok"
        pinned_client.aclose.assert_awaited_once()
        svc._token_exchange_cache.invalidate.assert_awaited_once()
        svc._resolve_token_exchange_header.assert_awaited_once()


@pytest.mark.asyncio
class TestGatewayRefreshTokenExchangeSubjectSources:
    """Issue #5382: manual-refresh resolver accepts the jwt_token cookie as subject source."""

    def _svc(self):
        """GatewayService with a stubbed exchange and cache-miss token cache."""
        # First-Party
        from mcpgateway.services.gateway_service import GatewayService

        svc = GatewayService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 300})
        svc._token_exchange_cache = _mock_te_cache(get_return=None)
        return svc

    async def test_resolve_header_accepts_cookie_jwt(self):
        """Cookie-only request headers (Admin UI session) must resolve a subject token."""
        svc = self._svc()
        header = await svc._resolve_token_exchange_header(
            dict(_TE_CFG),
            "gw-1",
            "gw-name",
            "admin@example.com",
            {"cookie": f"jwt_token={_FAKE_JWT}"},
        )
        assert header == {"Authorization": "Bearer exch-tok"}
        assert svc.oauth_manager.token_exchange.await_args.kwargs["subject_token"] == _FAKE_JWT

    async def test_resolve_header_rejects_opaque_cookie(self):
        """A non-JWT jwt_token cookie must fail closed, never reach the AS."""
        svc = self._svc()
        with pytest.raises(GatewayConnectionError):
            await svc._resolve_token_exchange_header(
                dict(_TE_CFG),
                "gw-1",
                "gw-name",
                "admin@example.com",
                {"cookie": "jwt_token=opaque-not-a-jwt"},
            )
        svc.oauth_manager.token_exchange.assert_not_awaited()

    async def test_resolve_header_audits_correlation_id(self):
        """x-correlation-id / x-request-id from inbound headers must reach the audit event."""
        svc = self._svc()
        with patch("mcpgateway.services.gateway_service.audit_token_exchange") as mock_audit:
            await svc._resolve_token_exchange_header(
                dict(_TE_CFG),
                "gw-1",
                "gw-name",
                "admin@example.com",
                {"cookie": f"jwt_token={_FAKE_JWT}", "x-correlation-id": "corr-42", "x-request-id": "req-7"},
            )
        assert mock_audit.call_args.kwargs["correlation_id"] == "corr-42"
        assert mock_audit.call_args.kwargs["request_id"] == "req-7"


# ---------- RFC 8693 delegation on the tool and gateway exchange paths ----------

_DELEGATION_CFG = {**_TE_CFG, "client_id": "cf", "actor_token_source": "client_credentials", "actor_token_type": "urn:ietf:params:oauth:token-type:access_token"}


@pytest.fixture
def shared_service_cache(monkeypatch):
    """Give each test a fresh process-wide service-token cache."""
    # First-Party
    from mcpgateway.services import gateway_service_token_cache

    cache = gateway_service_token_cache.GatewayServiceTokenCache()
    monkeypatch.setattr(gateway_service_token_cache, "_shared_cache", cache)
    return cache


def _delegation_tool_service(*, actor_side_effect=None, exchange_side_effect=None):
    """Build a ToolService with a real per-user cache and a mocked OAuth manager.

    Args:
        actor_side_effect: Optional exception for the actor client-credentials request.
        exchange_side_effect: Optional exception for the exchange request.

    Returns:
        ToolService: Service under test.
    """
    # First-Party
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache

    svc = ToolService()
    svc._token_exchange_cache = TokenExchangeCache(redis_url=None)
    svc.oauth_manager = MagicMock()
    svc.oauth_manager.get_client_credentials_token_response = AsyncMock(return_value={"access_token": "actor-tok", "expires_in": 600}, side_effect=actor_side_effect)
    svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "delegated-tok", "expires_in": 600}, side_effect=exchange_side_effect)
    return svc


def _subject(email="d@example.test", jti="d-subject"):
    # First-Party
    from tests.helpers.auth import make_test_jwt

    return make_test_jwt(email, extra_payload={"jti": jti})


@pytest.mark.asyncio
class TestToolPathDelegation:
    async def test_exchange_carries_actor_token(self, shared_service_cache):
        svc = _delegation_tool_service()
        subject = _subject()

        header = await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", {"authorization": f"Bearer {subject}"})

        assert header == {"Authorization": "Bearer delegated-tok"}
        kwargs = svc.oauth_manager.token_exchange.await_args.kwargs
        assert kwargs["subject_token"] == subject
        assert kwargs["actor_token"] == "actor-tok"
        assert kwargs["actor_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
        actor_config = svc.oauth_manager.get_client_credentials_token_response.await_args.args[0]
        assert actor_config["grant_type"] == "client_credentials"
        assert "subject_token" not in actor_config and "actor_token_source" not in actor_config

    async def test_impersonation_sends_no_actor_token(self, shared_service_cache):
        svc = _delegation_tool_service()

        await svc._resolve_token_exchange_header(dict(_TE_CFG), "gw", "gw", "d@example.test", {"authorization": f"Bearer {_subject()}"})

        kwargs = svc.oauth_manager.token_exchange.await_args.kwargs
        assert kwargs["actor_token"] is None and kwargs["actor_token_type"] is None
        svc.oauth_manager.get_client_credentials_token_response.assert_not_awaited()

    async def test_one_actor_request_serves_two_users(self, shared_service_cache):
        svc = _delegation_tool_service()

        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "a@example.test", {"authorization": f"Bearer {_subject('a@example.test', 'a')}"})
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "b@example.test", {"authorization": f"Bearer {_subject('b@example.test', 'b')}"})

        assert svc.oauth_manager.token_exchange.await_count == 2
        svc.oauth_manager.get_client_credentials_token_response.assert_awaited_once()

    async def test_actor_failure_fails_closed_and_sets_negative_cache(self, shared_service_cache, caplog):
        # Standard
        import logging

        svc = _delegation_tool_service(actor_side_effect=OAuthError("actor as down"))
        headers = {"authorization": f"Bearer {_subject()}"}

        with caplog.at_level(logging.INFO, logger="mcpgateway.audit.token_exchange"):
            with pytest.raises(ToolInvocationError, match="Token exchange failed"):
                await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        svc.oauth_manager.token_exchange.assert_not_awaited()

        with pytest.raises(ToolInvocationError, match="Token exchange unavailable"):
            await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        svc.oauth_manager.get_client_credentials_token_response.assert_awaited_once()
        svc.oauth_manager.token_exchange.assert_not_awaited()
        events = [r.token_exchange for r in caplog.records if hasattr(r, "token_exchange")]
        assert [(e["mode"], e["success"]) for e in events] == [("delegation", False)]

    @pytest.mark.parametrize(
        "error",
        [
            OAuthError("network down"),
            OAuthTokenExchangeError("denied", status_code=400, error_code="invalid_grant"),
            OAuthTokenExchangeError("policy", status_code=403, error_code="access_denied"),
            OAuthTokenExchangeError("timeout"),
        ],
    )
    async def test_non_actor_failure_keeps_cached_actor_token(self, shared_service_cache, error):
        """A failure that does not blame the actor keeps the shared actor token for other users."""
        svc = _delegation_tool_service(exchange_side_effect=error)
        headers = {"authorization": f"Bearer {_subject()}"}

        with pytest.raises(ToolInvocationError):
            await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        assert len(shared_service_cache._mem) == 1

        svc._token_exchange_cache._neg.clear()
        svc.oauth_manager.token_exchange.side_effect = None
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        assert svc.oauth_manager.get_client_credentials_token_response.await_count == 1

    @pytest.mark.parametrize(
        "error",
        [
            OAuthTokenExchangeError("unauthorized", status_code=401),
            OAuthTokenExchangeError("bad client", status_code=400, error_code="invalid_client"),
            OAuthTokenExchangeError("bad actor", status_code=400, error_code="invalid_request", error_description="actor_token is expired"),
        ],
    )
    async def test_rejected_exchange_discards_cached_actor_token(self, shared_service_cache, error):
        svc = _delegation_tool_service(exchange_side_effect=error)
        headers = {"authorization": f"Bearer {_subject()}"}

        with pytest.raises(ToolInvocationError):
            await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        assert shared_service_cache._mem == {}

        # After the negative-cache TTL, the next exchange requests a new actor token.
        svc._token_exchange_cache._neg.clear()
        svc.oauth_manager.token_exchange.side_effect = None
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        assert svc.oauth_manager.get_client_credentials_token_response.await_count == 2

    async def test_enabling_delegation_with_warm_impersonation_cache_reexchanges(self, shared_service_cache):
        svc = _delegation_tool_service()
        subject = _subject()
        headers = {"authorization": f"Bearer {subject}"}
        await svc._token_exchange_cache.set("gw", "d@example.test", "aud", "impersonation-tok", expires_in=3600, subject_token=subject)

        assert await svc._resolve_token_exchange_header(dict(_TE_CFG), "gw", "gw", "d@example.test", headers) == {"Authorization": "Bearer impersonation-tok"}
        svc.oauth_manager.token_exchange.assert_not_awaited()

        header = await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)

        assert header == {"Authorization": "Bearer delegated-tok"}
        assert svc.oauth_manager.token_exchange.await_args.kwargs["actor_token"] == "actor-tok"

    async def test_disabling_delegation_does_not_serve_delegated_token(self, shared_service_cache):
        svc = _delegation_tool_service()
        headers = {"authorization": f"Bearer {_subject()}"}
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        svc.oauth_manager.token_exchange.return_value = {"access_token": "impersonation-tok", "expires_in": 600}

        header = await svc._resolve_token_exchange_header(dict(_TE_CFG), "gw", "gw", "d@example.test", headers)

        assert header == {"Authorization": "Bearer impersonation-tok"}

    @pytest.mark.parametrize(
        "change",
        [
            {"actor": {"client_id": "other-actor"}},
            {"actor": {"token_url": "https://other-as.example.test/token"}},
            {"actor_token_type": "urn:ietf:params:oauth:token-type:jwt"},
            {"client_id": "other-exchange-client"},
        ],
    )
    async def test_actor_config_change_misses_exchanged_token_cache(self, shared_service_cache, change):
        """A changed exchange or actor client never serves a token issued with the old act claim."""
        svc = _delegation_tool_service()
        headers = {"authorization": f"Bearer {_subject()}"}
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        svc.oauth_manager.token_exchange.return_value = {"access_token": "new-actor-delegated-tok", "expires_in": 600}

        header = await svc._resolve_token_exchange_header({**_DELEGATION_CFG, **change}, "gw", "gw", "d@example.test", headers)

        assert header == {"Authorization": "Bearer new-actor-delegated-tok"}
        assert svc.oauth_manager.token_exchange.await_count == 2

    async def test_unchanged_actor_config_hits_exchanged_token_cache(self, shared_service_cache):
        svc = _delegation_tool_service()
        headers = {"authorization": f"Bearer {_subject()}"}
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)

        assert svc.oauth_manager.token_exchange.await_count == 1

    async def test_upstream_401_invalidates_delegation_entry(self, shared_service_cache):
        svc = _delegation_tool_service()
        headers = {"authorization": f"Bearer {_subject()}"}
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)

        await svc._invalidate_token_exchange_on_unauthorized(401, dict(_DELEGATION_CFG), "gw", "d@example.test", headers)
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)

        assert svc.oauth_manager.token_exchange.await_count == 2

    async def test_success_audit_mode_and_no_token_values(self, shared_service_cache, caplog):
        # Standard
        import logging

        svc = _delegation_tool_service()
        subject = _subject()
        with (
            caplog.at_level(logging.INFO),
            patch("mcpgateway.utils.token_exchange_audit._db_logger") as db_logger,
            patch("mcpgateway.services.tool_service.get_structured_logger") as get_sec_logger,
        ):
            await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", {"authorization": f"Bearer {subject}", "x-correlation-id": "corr-d"})

        event = next(r.token_exchange for r in caplog.records if hasattr(r, "token_exchange"))
        assert event["mode"] == "delegation"
        assert event["correlation_id"] == "corr-d"
        captured = repr(event) + repr(db_logger.log.call_args_list) + repr(get_sec_logger.return_value.log.call_args_list) + " ".join(r.getMessage() for r in caplog.records)
        assert get_sec_logger.return_value.log.call_args.kwargs["custom_fields"]["mode"] == "delegation"
        for secret in (subject, "actor-tok", "delegated-tok"):
            assert secret not in captured


@pytest.mark.asyncio
class TestGatewayPathDelegation:
    """Manual refresh with a user subject token runs the same delegation rules."""

    @staticmethod
    def _service(*, actor_side_effect=None):
        # First-Party
        from mcpgateway.services.token_exchange_cache import TokenExchangeCache

        svc = GatewayService()
        svc._token_exchange_cache = TokenExchangeCache(redis_url=None)
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.get_client_credentials_token_response = AsyncMock(return_value={"access_token": "actor-tok", "expires_in": 600}, side_effect=actor_side_effect)
        svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "delegated-tok", "expires_in": 600})
        return svc

    async def test_manual_refresh_exchange_carries_actor_token(self, shared_service_cache, caplog):
        # Standard
        import logging

        svc = self._service()
        subject = _subject()

        with caplog.at_level(logging.INFO, logger="mcpgateway.audit.token_exchange"):
            header = await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", {"authorization": f"Bearer {subject}"})

        assert header == {"Authorization": "Bearer delegated-tok"}
        kwargs = svc.oauth_manager.token_exchange.await_args.kwargs
        assert kwargs["subject_token"] == subject
        assert kwargs["actor_token"] == "actor-tok"
        events = [r.token_exchange for r in caplog.records if hasattr(r, "token_exchange")]
        assert events[0]["mode"] == "delegation"

    async def test_manual_refresh_actor_failure_fails_closed(self, shared_service_cache):
        svc = self._service(actor_side_effect=OAuthError("actor as down"))
        headers = {"authorization": f"Bearer {_subject()}"}

        with pytest.raises(GatewayConnectionError, match="Token exchange failed"):
            await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)
        with pytest.raises(GatewayConnectionError, match="Token exchange unavailable"):
            await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", headers)

        svc.oauth_manager.token_exchange.assert_not_awaited()
        svc.oauth_manager.get_client_credentials_token_response.assert_awaited_once()

    async def test_manual_refresh_mode_change_misses_warm_cache(self, shared_service_cache):
        svc = self._service()
        subject = _subject()
        await svc._token_exchange_cache.set("gw", "d@example.test", "aud", "impersonation-tok", expires_in=3600, subject_token=subject)

        header = await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", {"authorization": f"Bearer {subject}"})

        assert header == {"Authorization": "Bearer delegated-tok"}

    async def test_gateway_invalidate_clears_actor_token(self, shared_service_cache):
        svc = self._service()
        assert svc._service_token_cache is shared_service_cache
        await svc._resolve_token_exchange_header(dict(_DELEGATION_CFG), "gw", "gw", "d@example.test", {"authorization": f"Bearer {_subject()}"})
        assert len(shared_service_cache._mem) == 1

        await svc._service_token_cache.invalidate("gw")

        assert shared_service_cache._mem == {}


# ---------- Actor client override on the tool and gateway exchange paths ----------

_ACTOR_OVERRIDE = {"client_id": "contextforge", "client_secret": "actor-secret"}  # pragma: allowlist secret


def _actor_cfg(client_id: str = "mcp1") -> dict:
    """Return a delegation config that authenticates the exchange as ``client_id`` and the actor as ``contextforge``.

    Args:
        client_id: Exchange client id.

    Returns:
        dict: oauth_config dict.
    """
    return {**_DELEGATION_CFG, "client_id": client_id, "actor": dict(_ACTOR_OVERRIDE)}


def _actor_aware_tool_service() -> ToolService:
    """Build a ToolService whose mocked actor token names the requesting client.

    Returns:
        ToolService: Service under test.
    """
    svc = _delegation_tool_service()

    async def issue(actor_config, **_kwargs):
        return {"access_token": f"actor-tok-{actor_config['client_id']}", "expires_in": 600}

    svc.oauth_manager.get_client_credentials_token_response = AsyncMock(side_effect=issue)
    return svc


@pytest.mark.asyncio
class TestActorOverrideExchangePaths:
    async def test_tool_call_sends_actor_client_token(self, shared_service_cache):
        svc = _actor_aware_tool_service()

        await svc._resolve_token_exchange_header(_actor_cfg(), "gw", "gw", "d@example.test", {"authorization": f"Bearer {_subject()}"})

        actor_config = svc.oauth_manager.get_client_credentials_token_response.await_args.args[0]
        assert actor_config["client_id"] == "contextforge"
        exchange = svc.oauth_manager.token_exchange.await_args.kwargs
        assert exchange["oauth_config"]["client_id"] == "mcp1"
        assert exchange["actor_token"] == "actor-tok-contextforge"

    async def test_manual_refresh_sends_actor_client_token(self, shared_service_cache):
        svc = TestGatewayPathDelegation._service()

        async def issue(actor_config, **_kwargs):
            return {"access_token": f"actor-tok-{actor_config['client_id']}", "expires_in": 600}

        svc.oauth_manager.get_client_credentials_token_response = AsyncMock(side_effect=issue)

        await svc._resolve_token_exchange_header(_actor_cfg(), "gw", "gw", "d@example.test", {"authorization": f"Bearer {_subject()}"})

        exchange = svc.oauth_manager.token_exchange.await_args.kwargs
        assert exchange["oauth_config"]["client_id"] == "mcp1"
        assert exchange["actor_token"] == "actor-tok-contextforge"

    async def test_two_gateways_share_one_actor(self, shared_service_cache):
        svc = _actor_aware_tool_service()
        headers = {"authorization": f"Bearer {_subject()}"}

        await svc._resolve_token_exchange_header(_actor_cfg("mcp1"), "gw-a", "gw-a", "d@example.test", headers)
        await svc._resolve_token_exchange_header(_actor_cfg("mcp2"), "gw-b", "gw-b", "d@example.test", headers)

        exchanges = [call.kwargs for call in svc.oauth_manager.token_exchange.await_args_list]
        assert [e["oauth_config"]["client_id"] for e in exchanges] == ["mcp1", "mcp2"]
        assert {e["actor_token"] for e in exchanges} == {"actor-tok-contextforge"}
        actor_clients = [call.args[0]["client_id"] for call in svc.oauth_manager.get_client_credentials_token_response.await_args_list]
        assert actor_clients == ["contextforge", "contextforge"]
