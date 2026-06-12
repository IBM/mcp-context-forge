# tests/unit/mcpgateway/services/test_token_exchange_integration.py
# Standard
from unittest.mock import AsyncMock

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
