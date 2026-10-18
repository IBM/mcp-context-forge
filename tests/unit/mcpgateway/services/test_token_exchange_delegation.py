# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_exchange_delegation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

RFC 8693 delegation for token-exchange gateways: config validation, the actor
token resolver, the exchange request, cache separation by mode, and audit.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayCreate, GatewayUpdate
from mcpgateway.services import gateway_service_token_cache
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.gateway_service_token_cache import GatewayServiceTokenCache
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager
from mcpgateway.services.token_exchange_actor import build_actor_oauth_config, invalidate_actor_token, resolve_actor_token
from mcpgateway.services.token_exchange_cache import TokenExchangeCache

MALFORMED_KEY = "dummy-private-key-material"  # pragma: allowlist secret
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"  # nosec B105 - RFC 8693 URI
JWT_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:jwt"  # nosec B105 - RFC 8693 URI


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


class TestDelegationConfigValidation:
    def test_absent_source_defaults_to_none(self):
        out = GatewayService._validate_token_exchange_config(_te_config())
        assert out["actor_token_source"] == "none"
        assert "actor_token_type" not in out

    def test_none_source_drops_actor_token_type(self):
        out = GatewayService._validate_token_exchange_config(_te_config(actor_token_source="none", actor_token_type=ACCESS_TOKEN_TYPE))
        assert "actor_token_type" not in out

    @pytest.mark.parametrize(("source", "expected"), [("client_credentials", ACCESS_TOKEN_TYPE), ("client_assertion", JWT_TOKEN_TYPE)])
    def test_actor_token_type_defaults_by_source(self, source, expected):
        out = GatewayService._validate_token_exchange_config(_te_config(actor_token_source=source))
        assert out["actor_token_type"] == expected

    def test_explicit_actor_token_type_kept(self):
        out = GatewayService._validate_token_exchange_config(_te_config(actor_token_source="client_credentials", actor_token_type=JWT_TOKEN_TYPE))
        assert out["actor_token_type"] == JWT_TOKEN_TYPE

    @pytest.mark.parametrize("source", ["password", "client_secret", "CLIENT_CREDENTIALS", 1])
    def test_unknown_source_rejected(self, source):
        with pytest.raises(ValueError, match="actor_token_source"):
            GatewayService._validate_token_exchange_config(_te_config(actor_token_source=source))

    @pytest.mark.parametrize("token_type", ["access_token", "urn:example:token", 42])
    def test_non_rfc8693_actor_token_type_rejected(self, token_type):
        with pytest.raises(ValueError, match="actor_token_type"):
            GatewayService._validate_token_exchange_config(_te_config(actor_token_source="client_credentials", actor_token_type=token_type))

    def test_client_assertion_without_private_key_rejected(self):
        cfg = GatewayService._validate_token_exchange_config(_te_config(actor_token_source="client_assertion"))
        with pytest.raises(ValueError, match="private_key is required when actor_token_source is client_assertion"):
            GatewayService._validate_private_key_jwt_config(cfg)

    def test_client_assertion_with_malformed_key_rejected(self):
        cfg = GatewayService._validate_token_exchange_config(_te_config(actor_token_source="client_assertion", private_key=MALFORMED_KEY))
        with pytest.raises(ValueError, match="not a valid PEM-encoded private key"):
            GatewayService._validate_private_key_jwt_config(cfg)

    def test_client_assertion_with_valid_key_accepted(self):
        cfg = GatewayService._validate_token_exchange_config(_te_config(actor_token_source="client_assertion", private_key=_rsa_pem()))
        GatewayService._validate_private_key_jwt_config(cfg)

    def test_client_assertion_masked_key_resolves_stored_key(self):
        stored = get_encryption_service(settings.auth_encryption_secret).encrypt_secret(_rsa_pem())
        cfg = _te_config(actor_token_source="client_assertion", private_key=settings.masked_auth_value)
        GatewayService._validate_private_key_jwt_config(cfg, existing_oauth_config=_te_config(private_key=stored))

    def test_client_assertion_masked_key_without_stored_key_rejected(self):
        cfg = _te_config(actor_token_source="client_assertion", private_key=settings.masked_auth_value)
        with pytest.raises(ValueError, match="no stored key exists"):
            GatewayService._validate_private_key_jwt_config(cfg, existing_oauth_config=_te_config())

    def test_client_credentials_does_not_require_private_key(self):
        cfg = GatewayService._validate_token_exchange_config(_te_config(actor_token_source="client_credentials"))
        GatewayService._validate_private_key_jwt_config(cfg)


class TestDelegationKeysSchemaScope:
    _BASE = {"name": "gw", "url": "https://upstream.example.com/mcp", "auth_type": "oauth"}

    @pytest.mark.parametrize("schema", [GatewayCreate, GatewayUpdate])
    @pytest.mark.parametrize(("key", "value"), [("actor_token_source", "client_credentials"), ("actor_token_type", ACCESS_TOKEN_TYPE)])
    @pytest.mark.parametrize("grant_type", ["client_credentials", "authorization_code"])
    def test_delegation_keys_rejected_on_other_grants(self, schema, key, value, grant_type):
        oauth_config = {"grant_type": grant_type, "client_id": "c", "token_url": "https://as.example.com/token", key: value}
        with pytest.raises(ValidationError, match=f"{key} is only supported for the token-exchange grant type"):
            schema(**self._BASE, oauth_config=oauth_config)

    @pytest.mark.parametrize("schema", [GatewayCreate, GatewayUpdate])
    def test_unknown_source_rejected_with_named_field(self, schema):
        with pytest.raises(ValidationError, match="actor_token_source must be one of"):
            schema(**self._BASE, oauth_config=_te_config(actor_token_source="password"))

    @pytest.mark.parametrize("schema", [GatewayCreate, GatewayUpdate])
    def test_non_rfc8693_actor_token_type_rejected(self, schema):
        with pytest.raises(ValidationError, match="actor_token_type must be an RFC 8693 token type URI"):
            schema(**self._BASE, oauth_config=_te_config(actor_token_source="client_credentials", actor_token_type="access_token"))

    @pytest.mark.parametrize("schema", [GatewayCreate, GatewayUpdate])
    def test_delegation_keys_accepted_on_token_exchange(self, schema):
        oauth_config = _te_config(actor_token_source="client_credentials", actor_token_type=ACCESS_TOKEN_TYPE)
        model = schema(**self._BASE, oauth_config=oauth_config)
        assert model.oauth_config["actor_token_source"] == "client_credentials"


# ---------- Actor token resolver (D2) ----------


@pytest.fixture
def service_cache(monkeypatch):
    cache = GatewayServiceTokenCache()
    monkeypatch.setattr(gateway_service_token_cache, "_shared_cache", cache)
    return cache


def _cc_manager(**kwargs):
    manager = MagicMock()
    manager.get_client_credentials_token_response = AsyncMock(**kwargs)
    return manager


class TestResolveActorToken:
    async def test_none_returns_no_actor(self, service_cache):
        manager = _cc_manager(return_value={"access_token": "actor-tok"})
        for cfg in (_te_config(), _te_config(actor_token_source="none")):
            assert await resolve_actor_token(manager, cfg, gateway_id="gw") == (None, None)
        manager.get_client_credentials_token_response.assert_not_awaited()

    async def test_client_credentials_returns_token_and_default_type(self, service_cache):
        manager = _cc_manager(return_value={"access_token": "actor-tok", "expires_in": 600})

        token, token_type = await resolve_actor_token(manager, _te_config(actor_token_source="client_credentials"), gateway_id="gw", ca_certificate="ca-pem")

        assert (token, token_type) == ("actor-tok", ACCESS_TOKEN_TYPE)
        call = manager.get_client_credentials_token_response.await_args
        assert call.kwargs["ca_certificate"] == "ca-pem"
        assert call.args[0] == {
            "token_url": "https://as.example.com/token",
            "client_id": "cf",
            "client_secret": "parent-secret",  # pragma: allowlist secret
            "token_endpoint_auth_method": "client_secret_basic",
            "grant_type": "client_credentials",
        }

    async def test_client_credentials_cached_per_gateway(self, service_cache):
        manager = _cc_manager(return_value={"access_token": "actor-tok", "expires_in": 600})
        cfg = _te_config(actor_token_source="client_credentials")

        first = await resolve_actor_token(manager, cfg, gateway_id="gw-1")
        second = await resolve_actor_token(manager, cfg, gateway_id="gw-1")
        await resolve_actor_token(manager, cfg, gateway_id="gw-2")

        assert first == second
        assert manager.get_client_credentials_token_response.await_count == 2

    async def test_client_credentials_without_gateway_id_is_uncached(self, service_cache):
        manager = _cc_manager(return_value={"access_token": "actor-tok", "expires_in": 600})
        cfg = _te_config(actor_token_source="client_credentials")

        await resolve_actor_token(manager, cfg, gateway_id=None)
        await resolve_actor_token(manager, cfg, gateway_id=None)

        assert manager.get_client_credentials_token_response.await_count == 2
        assert service_cache._mem == {}

    async def test_concurrent_requests_single_flight(self, service_cache):
        # Standard
        import asyncio

        started = asyncio.Event()

        async def slow_response(*_args, **_kwargs):
            started.set()
            await asyncio.sleep(0.01)
            return {"access_token": "actor-tok", "expires_in": 600}

        manager = _cc_manager(side_effect=slow_response)
        cfg = _te_config(actor_token_source="client_credentials")

        results = await asyncio.gather(*(resolve_actor_token(manager, cfg, gateway_id="gw") for _ in range(3)))

        assert {r[0] for r in results} == {"actor-tok"}
        manager.get_client_credentials_token_response.assert_awaited_once()

    @pytest.mark.parametrize("expires_in", ["soon", None])
    async def test_unusable_expires_in_uses_fallback_ttl(self, service_cache, expires_in):
        manager = _cc_manager(return_value={"access_token": "actor-tok", "expires_in": expires_in})
        cfg = _te_config(actor_token_source="client_credentials")

        await resolve_actor_token(manager, cfg, gateway_id="gw")
        await resolve_actor_token(manager, cfg, gateway_id="gw")

        manager.get_client_credentials_token_response.assert_awaited_once()

    def test_non_dict_config_is_impersonation(self):
        # First-Party
        from mcpgateway.services.token_exchange_actor import actor_token_source, exchange_mode

        assert actor_token_source("not-a-dict") == "none"
        assert exchange_mode(None) == "impersonation"

    async def test_explicit_actor_token_type_returned(self, service_cache):
        manager = _cc_manager(return_value={"access_token": "actor-tok"})
        _, token_type = await resolve_actor_token(manager, _te_config(actor_token_source="client_credentials", actor_token_type=JWT_TOKEN_TYPE), gateway_id="gw")
        assert token_type == JWT_TOKEN_TYPE

    @pytest.mark.parametrize("kwargs", [{"side_effect": RuntimeError("as down actor-secret-detail")}, {"return_value": {"access_token": ""}}, {"return_value": {}}])
    async def test_client_credentials_failure_raises_oauth_error(self, service_cache, kwargs):
        manager = _cc_manager(**kwargs)
        with pytest.raises(OAuthError) as exc_info:
            await resolve_actor_token(manager, _te_config(actor_token_source="client_credentials"), gateway_id="gw")
        assert "actor-secret-detail" not in str(exc_info.value)
        assert service_cache._mem == {}

    async def test_client_assertion_signs_fresh_jwt(self, service_cache):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        public_pem = private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        cfg = _te_config(actor_token_source="client_assertion", private_key=get_encryption_service(settings.auth_encryption_secret).encrypt_secret(pem))
        manager = OAuthManager(max_retries=1)

        first, token_type = await resolve_actor_token(manager, cfg, gateway_id="gw")
        second, _ = await resolve_actor_token(manager, cfg, gateway_id="gw")

        assert token_type == JWT_TOKEN_TYPE
        claims = [jwt.decode(t, public_pem, algorithms=["RS256"], audience=cfg["token_url"]) for t in (first, second)]
        assert claims[0]["iss"] == claims[0]["sub"] == "cf"
        assert claims[0]["jti"] != claims[1]["jti"]
        assert service_cache._mem == {}

    async def test_client_assertion_without_key_raises_oauth_error(self, service_cache):
        with pytest.raises(OAuthError, match="no private_key"):
            await resolve_actor_token(OAuthManager(max_retries=1), _te_config(actor_token_source="client_assertion"), gateway_id="gw")

    async def test_client_assertion_unexpected_failure_wrapped(self, service_cache):
        manager = MagicMock()
        manager._prepare_runtime_credentials = AsyncMock(side_effect=RuntimeError("decrypt failed"))
        with pytest.raises(OAuthError, match="Actor token signing failed"):
            await resolve_actor_token(manager, _te_config(actor_token_source="client_assertion"), gateway_id="gw")

    async def test_unsupported_source_raises(self, service_cache):
        with pytest.raises(OAuthError, match="Unsupported actor_token_source"):
            await resolve_actor_token(MagicMock(), _te_config(actor_token_source="password"), gateway_id="gw")

    async def test_invalidate_drops_only_actor_entries(self, service_cache):
        await service_cache.set("discovery", "gw", "fp", "discovery-tok", expires_in=600)
        manager = _cc_manager(return_value={"access_token": "actor-tok", "expires_in": 600})
        cfg = _te_config(actor_token_source="client_credentials")
        await resolve_actor_token(manager, cfg, gateway_id="gw")

        await invalidate_actor_token("gw", cfg)

        assert await service_cache.get("discovery", "gw", "fp") == "discovery-tok"
        await resolve_actor_token(manager, cfg, gateway_id="gw")
        assert manager.get_client_credentials_token_response.await_count == 2

    async def test_invalidate_noop_for_other_sources(self, service_cache):
        await service_cache.set("actor", "gw", "fp", "actor-tok", expires_in=600)
        await invalidate_actor_token("gw", _te_config(actor_token_source="client_assertion"))
        await invalidate_actor_token(None, _te_config(actor_token_source="client_credentials"))
        assert await service_cache.get("actor", "gw", "fp") == "actor-tok"

    def test_actor_config_excludes_scopes_discovery_and_exchange_keys(self):
        cfg = build_actor_oauth_config(_te_config(actor_token_source="client_credentials", discovery={"grant_type": "client_credentials", "client_id": "svc"}))
        assert cfg["client_id"] == "cf"
        for key in ("scopes", "discovery", "target_audience", "actor_token_source"):
            assert key not in cfg


class TestServiceTokenCacheInvalidatePurpose:
    async def test_purpose_scoped_and_full_invalidate(self):
        cache = GatewayServiceTokenCache()
        await cache.set("actor", "gw", "fp", "a", expires_in=600)
        await cache.set("discovery", "gw", "fp", "d", expires_in=600)
        await cache.set("actor", "other", "fp", "o", expires_in=600)

        await cache.invalidate("gw", purpose="actor")
        assert await cache.get("actor", "gw", "fp") is None
        assert await cache.get("discovery", "gw", "fp") == "d"
        assert await cache.get("actor", "other", "fp") == "o"

        await cache.invalidate("gw")
        assert await cache.get("discovery", "gw", "fp") is None
        assert await cache.get("actor", "other", "fp") == "o"

    def test_shared_cache_is_a_singleton(self, monkeypatch):
        monkeypatch.setattr(gateway_service_token_cache, "_shared_cache", None)
        first = gateway_service_token_cache.get_service_token_cache()
        assert gateway_service_token_cache.get_service_token_cache() is first


# ---------- Mode-scoped exchanged-token cache keys (D3) ----------


class TestTokenExchangeCacheVariant:
    _ARGS = ("gw", "u@example.test", "aud")

    def test_empty_variant_matches_current_key(self):
        # Standard
        import hashlib

        expected = "token_exchange:v2:" + ":".join(hashlib.sha256(p.encode("utf-8")).hexdigest() for p in (*self._ARGS, "subject.jwt"))
        assert TokenExchangeCache._key(*self._ARGS, subject_token="subject.jwt") == expected
        assert TokenExchangeCache._key(*self._ARGS, subject_token="subject.jwt", variant="") == expected

    def test_variant_produces_distinct_keys(self):
        base = TokenExchangeCache._key(*self._ARGS, subject_token="subject.jwt")
        cc = TokenExchangeCache._key(*self._ARGS, subject_token="subject.jwt", variant="actor:client_credentials")
        ca = TokenExchangeCache._key(*self._ARGS, subject_token="subject.jwt", variant="actor:client_assertion")
        assert len({base, cc, ca}) == 3

    async def test_variant_entries_are_isolated(self):
        cache = TokenExchangeCache()
        await cache.set(*self._ARGS, "impersonation-tok", expires_in=3600, subject_token="subject.jwt")
        await cache.set_failure(*self._ARGS, subject_token="subject.jwt")

        assert await cache.get(*self._ARGS, subject_token="subject.jwt", variant="actor:client_credentials") is None
        assert await cache.is_failed(*self._ARGS, subject_token="subject.jwt", variant="actor:client_credentials") is False
        assert await cache.get(*self._ARGS, subject_token="subject.jwt") == "impersonation-tok"


# ---------- Audit mode (D5) ----------


class TestAuditMode:
    @pytest.mark.parametrize("mode", ["delegation", "impersonation"])
    def test_mode_in_event_and_db_record(self, caplog, monkeypatch, mode):
        # Standard
        import logging

        # First-Party
        from mcpgateway.utils import token_exchange_audit

        db_logger = MagicMock()
        monkeypatch.setattr(token_exchange_audit, "_db_logger", db_logger)
        kwargs = {} if mode == "impersonation" else {"mode": mode}
        with caplog.at_level(logging.INFO, logger="mcpgateway.audit.token_exchange"):
            token_exchange_audit.audit_token_exchange(
                user_email="u@example.test", gateway_id="gw", target_audience="aud", success=True, expires_in=60, upstream="gw", error=None, latency_ms=1, correlation_id="corr-1", **kwargs
            )

        record = next(r for r in caplog.records if hasattr(r, "token_exchange"))
        assert record.token_exchange["mode"] == mode
        assert record.token_exchange["correlation_id"] == "corr-1"
        assert f"mode={mode}" in record.getMessage()
        custom_fields = db_logger.log.call_args.kwargs["custom_fields"]
        assert custom_fields["mode"] == mode
        assert not {"subject_token", "actor_token", "access_token"} & set(custom_fields)
