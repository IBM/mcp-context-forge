# tests/unit/mcpgateway/services/test_token_exchange_integration.py
# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayService
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager


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

    async def test_token_exchange_routes_through_prepare_runtime_credentials(self):
        # Fix 3: get_access_token TE branch must call _prepare_runtime_credentials so
        # token_url gets validate_core_url applied at runtime (not only at config-save time).
        mgr = OAuthManager()
        mgr.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        prepared = {"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "client_secret": "s", "target_audience": "aud"}  # pragma: allowlist secret
        mgr._prepare_runtime_credentials = AsyncMock(return_value=prepared)

        cfg = {"grant_type": "token-exchange", "client_id": "cf", "token_url": "https://as/token", "target_audience": "aud"}
        await mgr.get_access_token(cfg, subject_token="user-jwt")

        mgr._prepare_runtime_credentials.assert_awaited_once_with(cfg, "token-exchange")
        # token_exchange was called with the runtime-decrypted/validated values
        mgr.token_exchange.assert_awaited_once()
        assert mgr.token_exchange.await_args.kwargs["token_url"] == "https://as/token"

    async def test_token_exchange_forwards_mtls_params(self):
        # Fix 4: ca_certificate/client_cert/client_key passed to get_access_token must be
        # forwarded to token_exchange() so mTLS against corporate-CA IdPs works.
        mgr = OAuthManager()
        mgr.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        mgr._prepare_runtime_credentials = AsyncMock(return_value={"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "client_secret": "s", "target_audience": "aud"})  # pragma: allowlist secret

        cfg = {"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "target_audience": "aud"}
        await mgr.get_access_token(cfg, subject_token="user-jwt", ca_certificate="PEM", client_cert="cert", client_key="key")

        kwargs = mgr.token_exchange.await_args.kwargs
        assert kwargs["ca_certificate"] == "PEM"
        assert kwargs["client_cert"] == "cert"
        assert kwargs["client_key"] == "key"

    async def test_get_access_token_marks_client_secret_plaintext(self):
        # _prepare_runtime_credentials already decrypts client_secret, so get_access_token
        # must tell token_exchange() to skip the inline decrypt (client_secret_is_plaintext=True).
        mgr = OAuthManager()
        mgr.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        mgr._prepare_runtime_credentials = AsyncMock(return_value={"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "client_secret": "decrypted-secret", "target_audience": "aud"})  # pragma: allowlist secret

        cfg = {"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "target_audience": "aud"}
        await mgr.get_access_token(cfg, subject_token="user-jwt")

        assert mgr.token_exchange.await_args.kwargs["client_secret_is_plaintext"] is True

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
        await svc._invalidate_token_exchange_on_unauthorized(401, dict(_TE_CFG), "gw1", None)
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
        )
        svc._token_exchange_cache.invalidate.assert_awaited_once_with("gw1", "u@e", "aud")

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

        async def _get(_url, params=None, headers=None):
            responses.append(headers)
            status = 401 if len(responses) == 1 else 200
            return _make_response(status)

        svc._http_client.get = AsyncMock(side_effect=_get)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            result = await svc.invoke_tool(test_db, "test_tool", {}, request_headers={"authorization": "Bearer inbound"}, app_user_email="u@e")

        assert result.content[0].text == '{\n  "result": "ok"\n}'
        assert len(responses) == 2  # exactly one retry
        # Second attempt carried the freshly re-exchanged Authorization header.
        assert responses[1].get("Authorization") == "Bearer fresh-tok"
        svc._token_exchange_cache.invalidate.assert_awaited_once()
        svc._resolve_token_exchange_header.assert_awaited_once()
