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
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager, OAuthTokenExchangeError
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

    async def test_invalidate_deletes_exact_key_without_scan(self, service_cache, monkeypatch):
        """Actor eviction deletes the one deterministic key and never scans the keyspace."""
        cfg = _te_config(actor_token_source="client_credentials")
        await resolve_actor_token(_cc_manager(return_value={"access_token": "actor-tok", "expires_in": 600}), cfg, gateway_id="gw")
        scan = AsyncMock()
        monkeypatch.setattr(service_cache, "invalidate", scan)

        await invalidate_actor_token("gw", cfg, OAuthTokenExchangeError("x", status_code=401))

        scan.assert_not_awaited()
        assert service_cache._mem == {}

    async def test_invalidate_keeps_token_for_non_actor_failure(self, service_cache):
        cfg = _te_config(actor_token_source="client_credentials")
        await resolve_actor_token(_cc_manager(return_value={"access_token": "actor-tok", "expires_in": 600}), cfg, gateway_id="gw")

        await invalidate_actor_token("gw", cfg, OAuthTokenExchangeError("denied", status_code=400, error_code="invalid_grant"))
        await invalidate_actor_token("gw", cfg, OAuthTokenExchangeError("actor down", stage="actor", status_code=401))

        assert len(service_cache._mem) == 1

    async def test_actor_failures_carry_actor_stage(self, service_cache):
        manager = _cc_manager(side_effect=RuntimeError("as down"))
        with pytest.raises(OAuthTokenExchangeError) as excinfo:
            await resolve_actor_token(manager, _te_config(actor_token_source="client_credentials"), gateway_id="gw")
        assert excinfo.value.stage == "actor"

    async def test_service_cache_delete_removes_redis_key(self):
        cache = GatewayServiceTokenCache()
        cache._redis = AsyncMock()
        cache._redis_live = lambda: True
        await cache.set("actor", "gw", "fp", "a", expires_in=600)

        await cache.delete("actor", "gw", "fp")

        cache._redis.delete.assert_awaited_once_with(GatewayServiceTokenCache._key("actor", "gw", "fp"))
        cache._redis.scan_iter.assert_not_called()

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


# ---------- Actor credential override ----------

ACTOR_SECRET = "actor-secret-value"  # pragma: allowlist secret
_ACTOR = {"client_id": "contextforge", "client_secret": ACTOR_SECRET}


def _actor_config(**overrides) -> dict:
    """Build a delegation config whose exchange client is ``mcp1`` and whose actor is ``contextforge``.

    Args:
        **overrides: Fields to override on the base config.

    Returns:
        dict: oauth_config dict.
    """
    base = {"client_id": "mcp1", "token_endpoint_auth_method": "client_secret_post", "actor_token_source": "client_credentials", "actor": dict(_ACTOR)}
    base.update(overrides)
    return _te_config(**base)


class _FakeTokenEndpoint:
    """Record token endpoint requests and answer by grant type."""

    EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"

    def __init__(self, fail_actor: bool = False):
        self.requests: list = []
        self.fail_actor = fail_actor
        self._issued = 0

    async def __call__(self, url, data, ca_certificate=None, client_cert=None, client_key=None, headers=None):
        # Third-Party
        import httpx

        self.requests.append({"url": url, "data": dict(data), "headers": dict(headers or {})})
        request = httpx.Request("POST", url)
        if data["grant_type"] == "client_credentials":
            if self.fail_actor:
                return httpx.Response(401, json={"error": "invalid_client"}, request=request)
            self._issued += 1
            return httpx.Response(200, json={"access_token": f"actor-tok-{data['client_id']}-{self._issued}", "token_type": "Bearer", "expires_in": 600}, request=request)
        return httpx.Response(200, json={"access_token": f"exchanged-for-{data['client_id']}", "token_type": "Bearer", "expires_in": 600}, request=request)

    def by_grant(self, grant_type: str) -> list:
        return [r for r in self.requests if r["data"]["grant_type"] == grant_type]


def _wired_manager(endpoint: _FakeTokenEndpoint) -> OAuthManager:
    manager = OAuthManager(max_retries=1)
    manager._post_token_request = endpoint  # type: ignore[method-assign]
    return manager


async def _exchange(manager: OAuthManager, oauth_config: dict, gateway_id: str = "gw") -> dict:
    """Run the resolver and the exchange the way every call site does.

    Args:
        manager: OAuth manager under test.
        oauth_config: Stored gateway oauth_config.
        gateway_id: Gateway id for the actor token cache.

    Returns:
        dict: Exchange response.
    """
    actor_token, actor_token_type = await resolve_actor_token(manager, oauth_config, gateway_id=gateway_id)
    return await manager.token_exchange(
        oauth_config=oauth_config, subject_token="user-subject", audience=oauth_config["target_audience"], actor_token=actor_token, actor_token_type=actor_token_type
    )


class TestActorOverrideSchema:
    _BASE = {"name": "gw", "url": "https://upstream.example.com/mcp", "auth_type": "oauth"}

    @pytest.mark.parametrize("schema", [GatewayCreate, GatewayUpdate])
    def test_actor_object_accepted(self, schema):
        model = schema(**self._BASE, oauth_config=_actor_config())
        assert model.oauth_config["actor"]["client_id"] == "contextforge"

    @pytest.mark.parametrize("schema", [GatewayCreate, GatewayUpdate])
    @pytest.mark.parametrize(
        ("actor", "message"),
        [
            ("contextforge", "oauth_config.actor must be an object"),
            ({"client_secret": "s"}, "oauth_config.actor.client_id is required"),
            ({"client_id": "  "}, "oauth_config.actor.client_id is required"),
            ({"client_id": "cf", "token_endpoint_auth_method": "tls_client_auth"}, "oauth_config.actor.token_endpoint_auth_method is not supported"),
            ({"client_id": "cf", "token_url": 42}, "oauth_config.actor.token_url must be a string URL"),
        ],
    )
    def test_invalid_actor_rejected(self, schema, actor, message):
        with pytest.raises(ValidationError, match=message):
            schema(**self._BASE, oauth_config=_actor_config(actor=actor))

    @pytest.mark.parametrize("schema", [GatewayCreate, GatewayUpdate])
    @pytest.mark.parametrize("source", ["none", "client_assertion", None])
    def test_actor_rejected_without_client_credentials_source(self, schema, source):
        with pytest.raises(ValidationError, match="oauth_config.actor is only supported with actor_token_source client_credentials"):
            schema(**self._BASE, oauth_config=_actor_config(actor_token_source=source))

    @pytest.mark.parametrize("schema", [GatewayCreate, GatewayUpdate])
    @pytest.mark.parametrize("grant_type", ["client_credentials", "authorization_code"])
    def test_actor_rejected_on_other_grants(self, schema, grant_type):
        oauth_config = {"grant_type": grant_type, "client_id": "c", "token_url": "https://as.example.com/token", "actor": dict(_ACTOR)}
        with pytest.raises(ValidationError, match="oauth_config.actor"):
            schema(**self._BASE, oauth_config=oauth_config)


class TestActorOverrideServiceValidation:
    def test_valid_actor_accepted(self):
        out = GatewayService._validate_token_exchange_config(_actor_config(actor={**_ACTOR, "token_url": "https://actor-as.example.com/token"}))
        assert out["actor"]["client_id"] == "contextforge"
        assert out["actor_token_type"] == ACCESS_TOKEN_TYPE

    def test_absent_source_with_actor_rejected(self):
        cfg = _actor_config()
        cfg.pop("actor_token_source")
        with pytest.raises(ValueError, match="actor is only supported with actor_token_source client_credentials"):
            GatewayService._validate_token_exchange_config(cfg)

    @pytest.mark.parametrize("source", ["none", "client_assertion"])
    def test_other_sources_with_actor_rejected(self, source):
        with pytest.raises(ValueError, match="actor is only supported"):
            GatewayService._validate_token_exchange_config(_actor_config(actor_token_source=source, private_key=_rsa_pem()))

    @pytest.mark.parametrize(("actor", "message"), [("cf", "actor must be an object"), ({"client_secret": "s"}, "actor.client_id is required")])
    def test_malformed_actor_rejected(self, actor, message):
        with pytest.raises(ValueError, match=message):
            GatewayService._validate_token_exchange_config(_actor_config(actor=actor))

    def test_blocked_actor_token_url_rejected_with_warning(self, caplog, monkeypatch):
        # Standard
        import logging

        # First-Party
        from mcpgateway.common.validators import SecurityValidator

        def _reject(url, _name):
            if "internal" in url:
                raise ValueError("OAuth token URL resolves to a blocked network")
            return url

        monkeypatch.setattr(SecurityValidator, "validate_url", staticmethod(_reject))
        with caplog.at_level(logging.WARNING, logger="mcpgateway.services.gateway_service"):
            with pytest.raises(ValueError, match="blocked network"):
                GatewayService._validate_token_exchange_config(_actor_config(actor={**_ACTOR, "token_url": "https://internal.example/token"}))
        assert any("Rejected token-exchange actor.token_url" in r.getMessage() for r in caplog.records)


class TestBuildActorOAuthConfig:
    def test_no_actor_keeps_parent_client(self):
        parent = _te_config(actor_token_source="client_credentials")
        assert build_actor_oauth_config(parent) == {
            "token_url": "https://as.example.com/token",
            "client_id": "cf",
            "client_secret": "parent-secret",  # pragma: allowlist secret
            "token_endpoint_auth_method": "client_secret_basic",
            "grant_type": "client_credentials",
        }

    def test_actor_client_id_and_secret_override(self):
        cfg = build_actor_oauth_config(_actor_config())
        assert (cfg["client_id"], cfg["client_secret"]) == ("contextforge", ACTOR_SECRET)
        assert cfg["token_url"] == "https://as.example.com/token"

    def test_actor_token_url_overrides_only_actor_config(self):
        parent = _actor_config(actor={**_ACTOR, "token_url": "https://actor-as.example.com/token"})
        assert build_actor_oauth_config(parent)["token_url"] == "https://actor-as.example.com/token"
        assert parent["token_url"] == "https://as.example.com/token"

    def test_actor_config_carries_no_exchange_keys(self):
        cfg = build_actor_oauth_config(_actor_config(discovery={"grant_type": "client_credentials", "client_id": "svc"}))
        for key in ("scopes", "subject_token", "audience", "target_audience", "actor", "discovery", "actor_token_source"):
            assert key not in cfg

    def test_method_override_drops_parent_key_material(self):
        parent = _actor_config(token_endpoint_auth_method="private_key_jwt", private_key="pk", private_key_jwt_kid="kid", token_endpoint_auth_signing_alg="RS256")  # pragma: allowlist secret
        cfg = build_actor_oauth_config({**parent, "actor": {**_ACTOR, "token_endpoint_auth_method": "client_secret_basic"}})
        assert cfg["token_endpoint_auth_method"] == "client_secret_basic"
        for key in ("private_key", "private_key_jwt_kid", "token_endpoint_auth_signing_alg"):
            assert key not in cfg

    @pytest.mark.parametrize("actor_method", [None, "private_key_jwt"])
    def test_same_or_private_key_jwt_method_keeps_key_material(self, actor_method):
        parent = _actor_config(token_endpoint_auth_method="private_key_jwt", private_key="pk")  # pragma: allowlist secret
        actor = {"client_id": "contextforge"} if actor_method is None else {"client_id": "contextforge", "token_endpoint_auth_method": actor_method}
        assert build_actor_oauth_config({**parent, "actor": actor})["private_key"] == "pk"

    def test_parent_config_not_mutated(self):
        parent = _actor_config()
        snapshot = {**parent, "actor": dict(parent["actor"])}
        build_actor_oauth_config(parent)
        assert parent == snapshot


@pytest.mark.asyncio
class TestActorOverrideResolver:
    async def test_actor_request_as_actor_client_and_exchange_as_parent(self, service_cache):
        endpoint = _FakeTokenEndpoint()

        response = await _exchange(_wired_manager(endpoint), _actor_config())

        [actor_request] = endpoint.by_grant("client_credentials")
        [exchange_request] = endpoint.by_grant(_FakeTokenEndpoint.EXCHANGE_GRANT)
        assert actor_request["data"]["client_id"] == "contextforge"
        assert actor_request["data"]["client_secret"] == ACTOR_SECRET
        for key in ("subject_token", "audience", "scope"):
            assert key not in actor_request["data"]
        assert exchange_request["data"]["client_id"] == "mcp1"
        assert exchange_request["data"]["client_secret"] == "parent-secret"  # pragma: allowlist secret
        assert exchange_request["data"]["actor_token"] == "actor-tok-contextforge-1"
        assert response["access_token"] == "exchanged-for-mcp1"

    async def test_actor_token_url_override_routes_only_actor_request(self, service_cache):
        endpoint = _FakeTokenEndpoint()

        await _exchange(_wired_manager(endpoint), _actor_config(actor={**_ACTOR, "token_url": "https://actor-as.example.com/token"}))

        assert endpoint.by_grant("client_credentials")[0]["url"] == "https://actor-as.example.com/token"
        assert endpoint.by_grant(_FakeTokenEndpoint.EXCHANGE_GRANT)[0]["url"] == "https://as.example.com/token"

    async def test_no_actor_authenticates_actor_request_as_parent(self, service_cache):
        endpoint = _FakeTokenEndpoint()
        cfg = _actor_config()
        cfg.pop("actor")

        await _exchange(_wired_manager(endpoint), cfg)

        assert endpoint.by_grant("client_credentials")[0]["data"]["client_id"] == "mcp1"

    async def test_actor_change_misses_cached_actor_token(self, service_cache):
        endpoint = _FakeTokenEndpoint()
        manager = _wired_manager(endpoint)

        await _exchange(manager, _actor_config(actor={"client_id": "cf-old", "client_secret": ACTOR_SECRET}))
        await _exchange(manager, _actor_config(actor={"client_id": "cf-old", "client_secret": ACTOR_SECRET}))
        await _exchange(manager, _actor_config(actor={"client_id": "cf-new", "client_secret": ACTOR_SECRET}))

        assert [r["data"]["client_id"] for r in endpoint.by_grant("client_credentials")] == ["cf-old", "cf-new"]
        assert endpoint.by_grant(_FakeTokenEndpoint.EXCHANGE_GRANT)[-1]["data"]["actor_token"] == "actor-tok-cf-new-2"

    async def test_failed_actor_request_sends_no_exchange(self, service_cache):
        endpoint = _FakeTokenEndpoint(fail_actor=True)

        with pytest.raises(OAuthError, match="Actor token request failed"):
            await _exchange(_wired_manager(endpoint), _actor_config())

        assert endpoint.by_grant(_FakeTokenEndpoint.EXCHANGE_GRANT) == []
        assert service_cache._mem == {}

    async def test_failed_actor_request_logs_no_secret_or_token(self, service_cache, caplog):
        # Standard
        import logging

        endpoint = _FakeTokenEndpoint()
        manager = _wired_manager(endpoint)
        await _exchange(manager, _actor_config(actor={"client_id": "cf-old", "client_secret": ACTOR_SECRET}))
        endpoint.fail_actor = True

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(OAuthError) as exc_info:
                await _exchange(manager, _actor_config(actor={"client_id": "cf-new", "client_secret": ACTOR_SECRET}))

        captured = " ".join(r.getMessage() for r in caplog.records) + repr([r.__dict__ for r in caplog.records]) + str(exc_info.value)
        for secret in (ACTOR_SECRET, "actor-tok-cf-old-1"):
            assert secret not in captured


@pytest.mark.asyncio
class TestActorSecretStorage:
    async def test_actor_secret_encrypted_and_decrypted_for_actor_request(self, service_cache):
        # First-Party
        from mcpgateway.services.encryption_service import protect_oauth_config_for_storage

        encryption = get_encryption_service(settings.auth_encryption_secret)
        stored = await protect_oauth_config_for_storage(_actor_config())
        assert stored["actor"]["client_secret"] != ACTOR_SECRET
        assert encryption.is_encrypted(stored["actor"]["client_secret"])

        endpoint = _FakeTokenEndpoint()
        await _exchange(_wired_manager(endpoint), stored)
        assert endpoint.by_grant("client_credentials")[0]["data"]["client_secret"] == ACTOR_SECRET

    async def test_prepare_for_storage_encrypts_actor_secret(self):
        svc = GatewayService()
        svc._enforce_token_exchange_admin_only = AsyncMock()
        svc._auto_discover_oauth_endpoints = AsyncMock(side_effect=lambda cfg: cfg)

        stored = await svc.prepare_oauth_config_for_storage(MagicMock(), _actor_config(), "admin@example.com")

        assert stored["actor"]["client_id"] == "contextforge"
        assert get_encryption_service(settings.auth_encryption_secret).is_encrypted(stored["actor"]["client_secret"])

    async def test_masked_actor_secret_keeps_stored_ciphertext(self, service_cache):
        # First-Party
        from mcpgateway.services.encryption_service import protect_oauth_config_for_storage

        stored = await protect_oauth_config_for_storage(_actor_config())
        updated = await protect_oauth_config_for_storage(_actor_config(actor={"client_id": "contextforge", "client_secret": settings.masked_auth_value}), existing_oauth_config=stored)
        assert updated["actor"]["client_secret"] == stored["actor"]["client_secret"]

        endpoint = _FakeTokenEndpoint()
        await _exchange(_wired_manager(endpoint), updated)
        assert endpoint.by_grant("client_credentials")[0]["data"]["client_secret"] == ACTOR_SECRET

    async def test_gateway_read_masks_actor_secret(self):
        # First-Party
        from mcpgateway.schemas import GatewayRead

        masked = GatewayRead(name="te-gw", url="http://example.com", oauth_config=_actor_config()).masked()
        assert masked.oauth_config["actor"]["client_secret"] == settings.masked_auth_value
        assert masked.oauth_config["actor"]["client_id"] == "contextforge"
        assert ACTOR_SECRET not in masked.model_dump_json()
