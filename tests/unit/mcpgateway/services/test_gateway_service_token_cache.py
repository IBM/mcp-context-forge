# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_token_cache.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Per-gateway service-token cache: serve window, fingerprint keys, isolation from the
per-user token-exchange cache, invalidation, and Redis fallback.
"""

# Standard
import time
from unittest.mock import AsyncMock, patch

# Third-Party
import fakeredis.aioredis as fakeredis_aio
import pytest

# First-Party
from mcpgateway.services.gateway_service_token_cache import GatewayServiceTokenCache, service_token_fingerprint
from mcpgateway.services.token_exchange_cache import TokenExchangeCache

_CONFIG = {"grant_type": "client_credentials", "token_url": "https://as/token", "client_id": "svc", "client_secret": "v2:ciphertext", "scopes": ["mcp.discover"]}  # pragma: allowlist secret
_FP = service_token_fingerprint(_CONFIG)


@pytest.mark.asyncio
class TestGatewayServiceTokenCache:
    async def test_miss_then_hit(self):
        c = GatewayServiceTokenCache()
        assert await c.get("discovery", "gw1", _FP) is None
        await c.set("discovery", "gw1", _FP, "svc-tok", expires_in=3600)
        assert await c.get("discovery", "gw1", _FP) == "svc-tok"

    async def test_serve_window_expires_before_hard_ttl(self):
        c = GatewayServiceTokenCache(skew_seconds=300)
        now = time.time()
        with patch("mcpgateway.services.token_exchange_cache.time.time", return_value=now):
            await c.set("discovery", "gw1", _FP, "svc-tok", expires_in=3600)
        with patch("mcpgateway.services.token_exchange_cache.time.time", return_value=now + 3299):
            assert await c.get("discovery", "gw1", _FP) == "svc-tok"
        with patch("mcpgateway.services.token_exchange_cache.time.time", return_value=now + 3301):
            assert await c.get("discovery", "gw1", _FP) is None

    async def test_fingerprint_changes_with_config(self):
        rotated = service_token_fingerprint({**_CONFIG, "client_secret": "v2:rotated"})  # pragma: allowlist secret
        assert rotated != _FP
        for change in ({"client_id": "other"}, {"token_url": "https://as/other"}, {"scopes": ["other"]}, {"token_endpoint_auth_method": "client_secret_post"}, {"private_key": "v2:pk"}):
            assert service_token_fingerprint({**_CONFIG, **change}) != _FP
        assert service_token_fingerprint({**_CONFIG, "scopes": ["mcp.discover"]}) == _FP

    async def test_fingerprint_miss_after_config_change(self):
        c = GatewayServiceTokenCache()
        await c.set("discovery", "gw1", _FP, "svc-tok", expires_in=3600)
        rotated = service_token_fingerprint({**_CONFIG, "client_secret": "v2:rotated"})  # pragma: allowlist secret
        assert await c.get("discovery", "gw1", rotated) is None

    async def test_purposes_and_gateways_isolated(self):
        c = GatewayServiceTokenCache()
        await c.set("discovery", "gw1", _FP, "svc-tok", expires_in=3600)
        assert await c.get("actor", "gw1", _FP) is None
        assert await c.get("discovery", "gw2", _FP) is None

    async def test_invalid_key_components_rejected(self):
        c = GatewayServiceTokenCache()
        with pytest.raises(ValueError):
            await c.get("", "gw1", _FP)
        with pytest.raises(ValueError):
            await c.get("disc:overy", "gw1", _FP)
        with pytest.raises(ValueError):
            await c.get("discovery", "", _FP)

    async def test_no_key_overlap_with_token_exchange_cache(self):
        service_key = GatewayServiceTokenCache._key("discovery", "gw1", _FP)
        user_key = TokenExchangeCache._key("gw1", "discovery", _FP, subject_token="a.b.c")
        assert service_key.split(":", 1)[0] != user_key.split(":", 1)[0]

    async def test_shared_redis_has_no_cross_lookup(self):
        redis = fakeredis_aio.FakeRedis(decode_responses=True)
        service_cache = GatewayServiceTokenCache()
        service_cache._redis = redis
        user_cache = TokenExchangeCache()
        user_cache._redis = redis
        await service_cache.set("discovery", "gw1", _FP, "svc-tok", expires_in=3600)
        await user_cache.set("gw1", "u@e", "aud", "user-tok", expires_in=3600, subject_token="a.b.c")
        assert await user_cache.get("gw1", "u@e", "aud", subject_token="a.b.c") == "user-tok"
        assert await service_cache.get("discovery", "gw1", _FP) == "svc-tok"
        await service_cache.invalidate("gw1")
        assert await service_cache.get("discovery", "gw1", _FP) is None
        assert await user_cache.get("gw1", "u@e", "aud", subject_token="a.b.c") == "user-tok"

    async def test_invalidate_memory_removes_all_entries_of_one_gateway(self):
        c = GatewayServiceTokenCache()
        other_fp = service_token_fingerprint({**_CONFIG, "client_id": "other"})
        await c.set("discovery", "gw1", _FP, "a", expires_in=3600)
        await c.set("discovery", "gw1", other_fp, "b", expires_in=3600)
        await c.set("actor", "gw1", _FP, "c", expires_in=3600)
        await c.set("discovery", "gw2", _FP, "d", expires_in=3600)
        await c.invalidate("gw1")
        assert await c.get("discovery", "gw1", _FP) is None
        assert await c.get("discovery", "gw1", other_fp) is None
        assert await c.get("actor", "gw1", _FP) is None
        assert await c.get("discovery", "gw2", _FP) == "d"

    async def test_invalidate_redis(self):
        c = GatewayServiceTokenCache()
        c._redis = fakeredis_aio.FakeRedis(decode_responses=True)
        await c.set("discovery", "gw1", _FP, "a", expires_in=3600)
        await c.set("discovery", "gw2", _FP, "b", expires_in=3600)
        await c.invalidate("gw1")
        assert await c.get("discovery", "gw1", _FP) is None
        assert await c.get("discovery", "gw2", _FP) == "b"

    async def test_invalidate_empty_gateway_id_is_noop(self):
        c = GatewayServiceTokenCache()
        await c.set("discovery", "gw1", _FP, "a", expires_in=3600)
        await c.invalidate("")
        assert await c.get("discovery", "gw1", _FP) == "a"

    async def test_redis_down_falls_back_to_memory(self):
        c = GatewayServiceTokenCache(redis_breaker_threshold=1)
        broken = AsyncMock()
        broken.set = AsyncMock(side_effect=ConnectionError("down"))
        broken.get = AsyncMock(side_effect=ConnectionError("down"))
        c._redis = broken
        await c.set("discovery", "gw1", _FP, "svc-tok", expires_in=3600)
        assert await c.get("discovery", "gw1", _FP) == "svc-tok"
        assert c._redis_live() is False

    async def test_lock_is_per_key(self):
        c = GatewayServiceTokenCache()
        assert c.lock("discovery", "gw1", _FP) is c.lock("discovery", "gw1", _FP)
        assert c.lock("discovery", "gw1", _FP) is not c.lock("discovery", "gw2", _FP)
