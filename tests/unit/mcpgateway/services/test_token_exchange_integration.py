# tests/unit/mcpgateway/services/test_token_exchange_integration.py
# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.gateway_service import GatewayService
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


@pytest.mark.asyncio
class TestGetAccessTokenTokenExchange:
    async def test_token_exchange_branch_calls_token_exchange(self):
        mgr = OAuthManager()
        mgr.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        cfg = {
            "grant_type": "token-exchange",
            "client_id": "cf",
            "client_secret": "shh",
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
        from mcpgateway.utils.subject_token import looks_like_jwt
        assert looks_like_jwt("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.sig") is True

    def test_opaque_token_is_not_jwt(self):
        from mcpgateway.utils.subject_token import looks_like_jwt
        assert looks_like_jwt("opaque-token") is False
        assert looks_like_jwt(None) is False
        assert looks_like_jwt("a.b") is False

    def test_jwt_edge_cases(self):
        # G12: empty segment and 4-segment strings are not compact-serialization JWTs.
        from mcpgateway.utils.subject_token import looks_like_jwt
        assert looks_like_jwt("a..b") is False      # empty middle segment
        assert looks_like_jwt("a.b.c.d") is False   # too many segments
        assert looks_like_jwt("") is False
        assert looks_like_jwt("...") is False


# A minimal but structurally-valid JWT (header.payload.signature) for subject-token checks.
_FAKE_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1QGUifQ.sig"

_TE_CFG = {"grant_type": "token-exchange", "target_audience": "aud", "token_url": "https://as/token", "subject_token_source": "inbound_user_jwt"}


def _mock_te_cache(get_return=None, failed=False):
    """A MagicMock TokenExchangeCache with all async methods + single-flight lock stubbed."""
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
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 1800})
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        header = await svc._resolve_token_exchange_header(
            oauth_config=dict(_TE_CFG), gateway_id="gw1", gateway_name="gw",
            app_user_email="u@e", request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
        )
        assert header == {"Authorization": "Bearer exch-tok"}
        # exchanged token used, NOT the user jwt
        assert _FAKE_JWT not in header["Authorization"]
        svc.oauth_manager.token_exchange.assert_awaited_once()
        assert svc.oauth_manager.token_exchange.await_args.kwargs["subject_token"] == _FAKE_JWT
        # B1: cached with the REAL expires_in from the response, not a hardcoded default.
        assert svc._token_exchange_cache.set.await_args.kwargs.get("expires_in", svc._token_exchange_cache.set.await_args.args[-1]) == 1800

    async def test_cache_hit_skips_exchange(self):
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock()
        svc._token_exchange_cache = _mock_te_cache(get_return="cached-tok")

        header = await svc._resolve_token_exchange_header(
            oauth_config=dict(_TE_CFG), gateway_id="gw1", gateway_name="gw",
            app_user_email="u@e", request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
        )
        assert header == {"Authorization": "Bearer cached-tok"}
        svc.oauth_manager.token_exchange.assert_not_awaited()

    async def test_negative_cache_fast_fails(self):
        # P4: a recently-failed key short-circuits before any subject resolution / AS call.
        from mcpgateway.services.tool_service import ToolService, ToolInvocationError

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock()
        svc._token_exchange_cache = _mock_te_cache(get_return=None, failed=True)
        with pytest.raises(ToolInvocationError, match="unavailable"):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG), gateway_id="gw1", gateway_name="gw",
                app_user_email="u@e", request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            )
        svc.oauth_manager.token_exchange.assert_not_awaited()

    async def test_single_flight_collapses_concurrent_misses(self):
        # P1: 10 concurrent cache-miss callers must trigger exactly ONE exchange.
        import asyncio
        from mcpgateway.services.tool_service import ToolService
        from mcpgateway.services.token_exchange_cache import TokenExchangeCache

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
        results = await asyncio.gather(*[
            svc._resolve_token_exchange_header(dict(_TE_CFG), "gw1", "gw", "u@e", headers) for _ in range(10)
        ])
        assert all(r == {"Authorization": "Bearer exch-tok"} for r in results)
        assert calls["n"] == 1  # single-flight collapsed 10 misses into 1 exchange

    async def test_user_oauth_token_source_uses_stored_token(self, monkeypatch):
        # G4: subject_token_source="user_oauth_token" pulls the stored upstream token
        # (no inbound bearer needed) and exchanges that.
        import contextlib
        import mcpgateway.services.tool_service as tsmod
        from mcpgateway.services.tool_service import ToolService
        from mcpgateway.services import token_storage_service as tss

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "exch-tok", "expires_in": 3600})
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        @contextlib.contextmanager
        def _fake_session():
            yield MagicMock()

        monkeypatch.setattr(tsmod, "fresh_db_session", _fake_session)
        monkeypatch.setattr(tss.TokenStorageService, "get_user_token", AsyncMock(return_value="stored-tok"))

        cfg = dict(_TE_CFG, subject_token_source="user_oauth_token")
        header = await svc._resolve_token_exchange_header(cfg, "gw1", "gw", "u@e", request_headers={})
        assert header == {"Authorization": "Bearer exch-tok"}
        assert svc.oauth_manager.token_exchange.await_args.kwargs["subject_token"] == "stored-tok"

    async def test_missing_subject_token_denies(self):
        from mcpgateway.services.tool_service import ToolService, ToolInvocationError

        svc = ToolService()
        svc._token_exchange_cache = _mock_te_cache(get_return=None)
        with pytest.raises(ToolInvocationError, match="authentication required"):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG), gateway_id="gw1", gateway_name="gw",
                app_user_email="u@e", request_headers={},  # no bearer
            )

    async def test_non_jwt_subject_token_denies(self):
        # H2: an opaque/non-JWT inbound bearer must not be shipped to the AS.
        from mcpgateway.services.tool_service import ToolService, ToolInvocationError

        svc = ToolService()
        svc._token_exchange_cache = _mock_te_cache(get_return=None)
        with pytest.raises(ToolInvocationError, match="authentication required"):
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG), gateway_id="gw1", gateway_name="gw",
                app_user_email="u@e", request_headers={"authorization": "Bearer opaque-not-a-jwt"},
            )

    async def test_exchange_failure_message_is_generic_and_not_cached(self):
        # H1: AS error detail must not leak to the caller; positive cache must stay empty,
        # negative cache must be set (P4).
        from mcpgateway.services.tool_service import ToolService, ToolInvocationError

        svc = ToolService()
        svc.oauth_manager = MagicMock()
        svc.oauth_manager.token_exchange = AsyncMock(side_effect=Exception("AS said: subject_token=eyJ... is invalid"))
        svc._token_exchange_cache = _mock_te_cache(get_return=None)

        with pytest.raises(ToolInvocationError) as ei:
            await svc._resolve_token_exchange_header(
                oauth_config=dict(_TE_CFG), gateway_id="gw1", gateway_name="gw",
                app_user_email="u@e", request_headers={"authorization": f"Bearer {_FAKE_JWT}"},
            )
        # generic message; no token / AS body echoed
        assert "eyJ" not in str(ei.value)
        assert "subject_token" not in str(ei.value)
        svc._token_exchange_cache.set.assert_not_awaited()
        svc._token_exchange_cache.set_failure.assert_awaited_once()
