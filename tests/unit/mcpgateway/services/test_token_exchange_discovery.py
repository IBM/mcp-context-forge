# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_exchange_discovery.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Discovery credential for token-exchange gateways: config validation, the effective
client-credentials config, and secret storage.
"""

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayRead
from mcpgateway.services.encryption_service import decrypt_oauth_config_for_runtime, get_encryption_service, protect_oauth_config_for_storage
from mcpgateway.services.gateway_service import build_discovery_oauth_config, GatewayService

MALFORMED_KEY = "dummy-private-key-material"  # pragma: allowlist secret
DISCOVERY_SECRET = "discovery-secret-value"  # pragma: allowlist secret


def _rsa_pem() -> str:
    """Return an unencrypted RSA private key PEM.

    Returns:
        str: PEM-encoded RSA private key.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def _te_config(**overrides) -> dict:
    """Build a token-exchange oauth_config.

    Args:
        **overrides: Fields to override on the base config.

    Returns:
        dict: oauth_config dict.
    """
    config = {
        "grant_type": "token-exchange",
        "client_id": "cf",
        "client_secret": "parent-secret",  # pragma: allowlist secret
        "token_url": "https://as.example.com/token",
        "token_endpoint_auth_method": "client_secret_basic",
        "target_audience": "https://downstream",
        "scopes": ["openid", "mcp.call"],
    }
    config.update(overrides)
    return config


class TestDiscoveryConfigValidation:
    def test_minimal_discovery_accepted(self):
        out = GatewayService._validate_token_exchange_config(_te_config(discovery={"grant_type": "client_credentials", "scopes": ["mcp.discover"]}))
        assert out["discovery"] == {"grant_type": "client_credentials", "scopes": ["mcp.discover"]}

    def test_absent_discovery_accepted(self):
        out = GatewayService._validate_token_exchange_config(_te_config())
        assert "discovery" not in out

    def test_discovery_must_be_dict(self):
        with pytest.raises(ValueError, match="discovery must be an object"):
            GatewayService._validate_token_exchange_config(_te_config(discovery=["client_credentials"]))

    @pytest.mark.parametrize("grant_type", [None, "authorization_code", "token-exchange", "password"])
    def test_unsupported_discovery_grant_rejected(self, grant_type):
        with pytest.raises(ValueError, match="discovery.grant_type"):
            GatewayService._validate_token_exchange_config(_te_config(discovery={"grant_type": grant_type}))

    def test_discovery_token_url_ssrf_rejected(self):
        with pytest.raises(ValueError):
            GatewayService._validate_token_exchange_config(_te_config(discovery={"grant_type": "client_credentials", "token_url": "http://169.254.169.254/latest/meta-data/"}))

    def test_discovery_token_url_same_error_as_parent(self):
        bad_url = "http://169.254.169.254/latest/meta-data/"
        with pytest.raises(ValueError) as parent_exc:
            GatewayService._validate_token_exchange_config(_te_config(token_url=bad_url))
        with pytest.raises(ValueError) as discovery_exc:
            GatewayService._validate_token_exchange_config(_te_config(discovery={"grant_type": "client_credentials", "token_url": bad_url}))
        assert str(discovery_exc.value) == str(parent_exc.value)

    def test_unknown_discovery_auth_method_rejected(self):
        with pytest.raises(ValueError, match="discovery.token_endpoint_auth_method"):
            GatewayService._validate_token_exchange_config(_te_config(discovery={"grant_type": "client_credentials", "token_endpoint_auth_method": "client_secret_digest"}))

    @pytest.mark.parametrize("method", ["none", "client_secret_basic", "client_secret_post", "private_key_jwt"])
    def test_supported_discovery_auth_methods_accepted(self, method):
        GatewayService._validate_token_exchange_config(_te_config(discovery={"grant_type": "client_credentials", "token_endpoint_auth_method": method}))

    def test_discovery_private_key_jwt_malformed_inherited_key_rejected(self):
        cfg = _te_config(private_key=MALFORMED_KEY, discovery={"grant_type": "client_credentials", "token_endpoint_auth_method": "private_key_jwt"})
        with pytest.raises(ValueError, match="not a valid PEM-encoded private key"):
            GatewayService._validate_private_key_jwt_config(cfg)

    def test_discovery_private_key_jwt_missing_key_rejected(self):
        cfg = _te_config(discovery={"grant_type": "client_credentials", "token_endpoint_auth_method": "private_key_jwt"})
        with pytest.raises(ValueError, match="private_key is required"):
            GatewayService._validate_private_key_jwt_config(cfg)

    def test_discovery_private_key_jwt_valid_inherited_key_accepted(self):
        cfg = _te_config(private_key=_rsa_pem(), discovery={"grant_type": "client_credentials", "token_endpoint_auth_method": "private_key_jwt"})
        GatewayService._validate_private_key_jwt_config(cfg)

    def test_discovery_private_key_jwt_masked_key_resolves_stored_key(self):
        stored = get_encryption_service(settings.auth_encryption_secret).encrypt_secret(_rsa_pem())
        discovery = {"grant_type": "client_credentials", "token_endpoint_auth_method": "private_key_jwt"}
        cfg = _te_config(private_key=settings.masked_auth_value, discovery=discovery)
        GatewayService._validate_private_key_jwt_config(cfg, existing_oauth_config=_te_config(private_key=stored, discovery=discovery))


class TestBuildDiscoveryOauthConfig:
    def test_none_without_discovery(self):
        assert build_discovery_oauth_config(_te_config()) is None
        assert build_discovery_oauth_config(None) is None
        assert build_discovery_oauth_config(_te_config(discovery="not-a-dict")) is None

    def test_inherits_parent_client_auth(self):
        out = build_discovery_oauth_config(_te_config(private_key="pk", private_key_jwt_kid="kid", token_endpoint_auth_signing_alg="ES256", discovery={"grant_type": "client_credentials"}))
        assert out == {
            "grant_type": "client_credentials",
            "token_url": "https://as.example.com/token",
            "client_id": "cf",
            "client_secret": "parent-secret",  # pragma: allowlist secret
            "token_endpoint_auth_method": "client_secret_basic",
            "private_key": "pk",
            "private_key_jwt_kid": "kid",
            "token_endpoint_auth_signing_alg": "ES256",
            "scopes": ["openid", "mcp.call"],
        }

    def test_overrides_win(self):
        out = build_discovery_oauth_config(
            _te_config(
                discovery={
                    "grant_type": "client_credentials",
                    "token_url": "https://as.example.com/discovery-token",
                    "client_id": "svc",
                    "client_secret": DISCOVERY_SECRET,
                    "token_endpoint_auth_method": "client_secret_post",
                    "scopes": ["mcp.discover"],
                }
            )
        )
        assert out["token_url"] == "https://as.example.com/discovery-token"
        assert out["client_id"] == "svc"
        assert out["client_secret"] == DISCOVERY_SECRET
        assert out["token_endpoint_auth_method"] == "client_secret_post"
        assert out["scopes"] == ["mcp.discover"]

    def test_blank_overrides_inherit(self):
        out = build_discovery_oauth_config(_te_config(discovery={"grant_type": "client_credentials", "client_id": "", "client_secret": None, "scopes": []}))
        assert out["client_id"] == "cf"
        assert out["client_secret"] == "parent-secret"  # pragma: allowlist secret
        assert out["scopes"] == ["openid", "mcp.call"]

    def test_scopes_omitted_when_neither_set(self):
        out = build_discovery_oauth_config(_te_config(scopes=None, discovery={"grant_type": "client_credentials"}))
        assert "scopes" not in out

    def test_excludes_token_exchange_keys(self):
        cfg = _te_config(discovery={"grant_type": "client_credentials"})
        cfg = GatewayService._validate_token_exchange_config(cfg)
        out = build_discovery_oauth_config(cfg)
        for key in ("target_audience", "subject_token_source", "subject_token_type", "requested_token_type", "discovery"):
            assert key not in out
        assert out["grant_type"] == "client_credentials"

    def test_does_not_mutate_input(self):
        cfg = _te_config(discovery={"grant_type": "client_credentials", "scopes": ["mcp.discover"]})
        snapshot = {**cfg, "discovery": dict(cfg["discovery"])}
        out = build_discovery_oauth_config(cfg)
        out["scopes"].append("extra")
        assert cfg == snapshot


@pytest.mark.asyncio
class TestDiscoverySecretStorage:
    async def test_discovery_client_secret_encrypted_and_decrypted(self):
        encryption = get_encryption_service(settings.auth_encryption_secret)
        stored = await protect_oauth_config_for_storage(_te_config(discovery={"grant_type": "client_credentials", "client_secret": DISCOVERY_SECRET}))
        assert stored["discovery"]["client_secret"] != DISCOVERY_SECRET
        assert encryption.is_encrypted(stored["discovery"]["client_secret"])

        runtime = await decrypt_oauth_config_for_runtime(stored)
        assert runtime["discovery"]["client_secret"] == DISCOVERY_SECRET
        assert build_discovery_oauth_config(runtime)["client_secret"] == DISCOVERY_SECRET

    async def test_masked_discovery_secret_keeps_stored_ciphertext(self):
        stored = await protect_oauth_config_for_storage(_te_config(discovery={"grant_type": "client_credentials", "client_secret": DISCOVERY_SECRET}))
        updated = await protect_oauth_config_for_storage(
            _te_config(discovery={"grant_type": "client_credentials", "client_secret": settings.masked_auth_value}),
            existing_oauth_config=stored,
        )
        assert updated["discovery"]["client_secret"] == stored["discovery"]["client_secret"]

    async def test_gateway_read_masks_discovery_secret(self):
        gw = GatewayRead(name="te-gw", url="http://example.com", oauth_config=_te_config(discovery={"grant_type": "client_credentials", "client_secret": DISCOVERY_SECRET}))
        masked = gw.masked()
        assert masked.oauth_config["discovery"]["client_secret"] == settings.masked_auth_value
        assert masked.oauth_config["discovery"]["grant_type"] == "client_credentials"
        assert DISCOVERY_SECRET not in masked.model_dump_json()


def _discovery_service(token_response=None, side_effect=None) -> GatewayService:
    """Build a GatewayService whose client-credentials call is mocked.

    Args:
        token_response: Token endpoint response to return.
        side_effect: Exception to raise instead.

    Returns:
        GatewayService: Service under test.
    """
    # Standard
    from unittest.mock import AsyncMock

    # First-Party
    from mcpgateway.services.gateway_service_token_cache import GatewayServiceTokenCache

    service = GatewayService()
    service._service_token_cache = GatewayServiceTokenCache()
    service.oauth_manager.get_client_credentials_token_response = AsyncMock(return_value=token_response or {"access_token": "svc-tok", "expires_in": 3600}, side_effect=side_effect)
    service.oauth_manager.token_exchange = AsyncMock()
    service.oauth_manager.get_access_token = AsyncMock()
    return service


_WITH_DISCOVERY = _te_config(discovery={"grant_type": "client_credentials", "scopes": ["mcp.discover"]})


@pytest.mark.asyncio
class TestResolveDiscoveryHeader:
    async def test_none_without_discovery(self):
        service = _discovery_service()
        assert await service._resolve_discovery_header(_te_config(), gateway_id="gw1", gateway_name="gw") is None
        service.oauth_manager.get_client_credentials_token_response.assert_not_awaited()

    async def test_success_uses_effective_config(self):
        service = _discovery_service()
        header = await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id="gw1", gateway_name="gw", ca_certificate="ca", client_cert="cert", client_key="key")
        assert header == {"Authorization": "Bearer svc-tok"}
        call = service.oauth_manager.get_client_credentials_token_response.call_args
        assert call.args[0] == build_discovery_oauth_config(_WITH_DISCOVERY)
        assert call.kwargs == {"ca_certificate": "ca", "client_cert": "cert", "client_key": "key"}
        service.oauth_manager.token_exchange.assert_not_awaited()

    async def test_cache_hit_sends_no_request(self):
        service = _discovery_service()
        await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id="gw1", gateway_name="gw")
        assert await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id="gw1", gateway_name="gw") == {"Authorization": "Bearer svc-tok"}
        assert service.oauth_manager.get_client_credentials_token_response.await_count == 1

    async def test_concurrent_requests_single_flight(self):
        # Standard
        import asyncio

        service = _discovery_service()

        async def slow(*_a, **_k):
            await asyncio.sleep(0.01)
            return {"access_token": "svc-tok", "expires_in": 3600}

        service.oauth_manager.get_client_credentials_token_response.side_effect = slow
        results = await asyncio.gather(*(service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id="gw1", gateway_name="gw") for _ in range(5)))
        assert all(r == {"Authorization": "Bearer svc-tok"} for r in results)
        assert service.oauth_manager.get_client_credentials_token_response.await_count == 1

    async def test_registration_without_gateway_id_is_uncached(self):
        service = _discovery_service()
        await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id=None, gateway_name="gw")
        await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id=None, gateway_name="gw")
        assert service.oauth_manager.get_client_credentials_token_response.await_count == 2

    async def test_config_change_requests_new_token(self):
        service = _discovery_service()
        await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id="gw1", gateway_name="gw")
        changed = _te_config(discovery={"grant_type": "client_credentials", "scopes": ["mcp.discover", "extra"]})
        await service._resolve_discovery_header(changed, gateway_id="gw1", gateway_name="gw")
        assert service.oauth_manager.get_client_credentials_token_response.await_count == 2

    async def test_non_numeric_expires_in_uses_fallback_ttl(self):
        service = _discovery_service(token_response={"access_token": "svc-tok", "expires_in": "soon"})
        assert await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id="gw1", gateway_name="gw") == {"Authorization": "Bearer svc-tok"}
        assert await service._service_token_cache.get("discovery", "gw1", next(iter(service._service_token_cache._mem)).rsplit(":", 1)[-1]) == "svc-tok"

    async def test_missing_expires_in_uses_fallback_ttl(self):
        service = _discovery_service(token_response={"access_token": "svc-tok"})
        await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id="gw1", gateway_name="gw")
        assert await service._resolve_discovery_header(dict(_WITH_DISCOVERY), gateway_id="gw1", gateway_name="gw") == {"Authorization": "Bearer svc-tok"}
        assert service.oauth_manager.get_client_credentials_token_response.await_count == 1

    async def test_failure_raises_connection_error_and_audits(self, caplog):
        # Standard
        import logging

        # First-Party
        from mcpgateway.services.gateway_service import GatewayConnectionError

        service = _discovery_service(side_effect=RuntimeError(f"401 from AS, secret={DISCOVERY_SECRET}"))
        cfg = _te_config(discovery={"grant_type": "client_credentials", "client_secret": DISCOVERY_SECRET})
        with caplog.at_level(logging.INFO, logger="mcpgateway.audit.token_exchange"):
            with pytest.raises(GatewayConnectionError, match="Discovery credential token request failed") as exc:
                await service._resolve_discovery_header(cfg, gateway_id="gw1", gateway_name="gw")
        assert DISCOVERY_SECRET not in str(exc.value)
        events = [r.token_exchange for r in caplog.records if hasattr(r, "token_exchange")]
        assert len(events) == 1
        assert events[0]["purpose"] == "discovery"
        assert events[0]["success"] is False
        assert events[0]["user_email"] is None
        assert events[0]["gateway_id"] == "gw1"
        # Nothing cached after a failure.
        assert service._service_token_cache._mem == {}

    async def test_success_audit_has_purpose_correlation_and_no_secrets(self, caplog):
        # Standard
        import logging
        from unittest.mock import patch

        service = _discovery_service(token_response={"access_token": "svc-raw-token-value", "expires_in": 600})
        cfg = _te_config(discovery={"grant_type": "client_credentials", "client_secret": DISCOVERY_SECRET})
        with caplog.at_level(logging.INFO, logger="mcpgateway.audit.token_exchange"), patch("mcpgateway.services.gateway_service.get_correlation_id", return_value="corr-disc-1"):
            await service._resolve_discovery_header(cfg, gateway_id="gw1", gateway_name="gw")
            await service._resolve_discovery_header(cfg, gateway_id="gw1", gateway_name="gw")  # cache hit: no event
        records = [r for r in caplog.records if hasattr(r, "token_exchange")]
        assert len(records) == 1
        event = records[0].token_exchange
        assert event["purpose"] == "discovery"
        assert event["success"] is True
        assert event["correlation_id"] == "corr-disc-1"
        assert event["exchanged_token_expires_in"] == 600
        rendered = repr(event) + records[0].getMessage()
        for secret in ("svc-raw-token-value", DISCOVERY_SECRET, "parent-secret"):
            assert secret not in rendered


@pytest.mark.asyncio
class TestInitializeGatewayDiscovery:
    @staticmethod
    def _connect_result():
        # Standard
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.name = "listed_tool"
        return ({"tools": {}}, [tool], [], [], [])

    async def test_registration_with_discovery_connects_with_discovery_token(self):
        # Standard
        from unittest.mock import AsyncMock

        service = _discovery_service()
        service.connect_to_streamablehttp_server = AsyncMock(return_value=self._connect_result())
        _caps, tools, _r, _p, _e = await service._initialize_gateway("http://upstream.test/mcp", None, "streamablehttp", "oauth", dict(_WITH_DISCOVERY))
        assert [t.name for t in tools] == ["listed_tool"]
        assert service.connect_to_streamablehttp_server.call_args.args[1] == {"Authorization": "Bearer svc-tok"}
        service.oauth_manager.token_exchange.assert_not_awaited()
        service.oauth_manager.get_access_token.assert_not_awaited()

    async def test_gateway_id_enables_cache(self):
        # Standard
        from unittest.mock import AsyncMock

        service = _discovery_service()
        service.connect_to_streamablehttp_server = AsyncMock(return_value=self._connect_result())
        for _ in range(2):
            await service._initialize_gateway("http://upstream.test/mcp", None, "streamablehttp", "oauth", dict(_WITH_DISCOVERY), gateway_id="gw1")
        assert service.oauth_manager.get_client_credentials_token_response.await_count == 1

    async def test_registration_without_discovery_returns_empty(self):
        # Standard
        from unittest.mock import AsyncMock

        service = _discovery_service()
        service.connect_to_streamablehttp_server = AsyncMock()
        assert await service._initialize_gateway("http://upstream.test/mcp", None, "streamablehttp", "oauth", _te_config()) == ({}, [], [], [], [])
        service.connect_to_streamablehttp_server.assert_not_awaited()
        service.oauth_manager.get_client_credentials_token_response.assert_not_awaited()

    async def test_discovery_failure_at_registration_raises(self):
        # Standard
        from unittest.mock import AsyncMock

        # First-Party
        from mcpgateway.services.gateway_service import GatewayConnectionError

        service = _discovery_service(side_effect=RuntimeError("as down"))
        service.connect_to_streamablehttp_server = AsyncMock()
        with pytest.raises(GatewayConnectionError):
            await service._initialize_gateway("http://upstream.test/mcp", None, "streamablehttp", "oauth", dict(_WITH_DISCOVERY))
        service.connect_to_streamablehttp_server.assert_not_awaited()

    async def test_pre_auth_headers_win_over_discovery(self):
        # Standard
        from unittest.mock import AsyncMock

        service = _discovery_service()
        service.connect_to_streamablehttp_server = AsyncMock(return_value=self._connect_result())
        await service._initialize_gateway("http://upstream.test/mcp", None, "streamablehttp", "oauth", dict(_WITH_DISCOVERY), pre_auth_headers={"Authorization": "Bearer user-exchanged"})
        assert service.connect_to_streamablehttp_server.call_args.args[1] == {"Authorization": "Bearer user-exchanged"}
        service.oauth_manager.get_client_credentials_token_response.assert_not_awaited()

    async def test_predicate_false_with_discovery(self):
        # Standard
        from unittest.mock import MagicMock

        assert GatewayService._initialize_skips_discovery(dict(_WITH_DISCOVERY)) is False
        assert GatewayService._discovery_result_is_unusable(MagicMock(oauth_config=dict(_WITH_DISCOVERY)), [], [], []) is False
