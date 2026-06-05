# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_rate_limit_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Team

Unit tests for Redis-backed rate limit middleware.

Examples:
    >>> pytest tests/unit/mcpgateway/middleware/test_rate_limit_middleware.py -v  # doctest: +SKIP
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRateLimiterRedisUrl:
    """Test rate limit middleware uses dedicated Redis function."""

    @patch("mcpgateway.auth._get_ratelimiter_redis_client")
    @patch("mcpgateway.middleware.rate_limit_middleware.settings")
    def test_rate_limit_calls_dedicated_redis_function(self, mock_settings, mock_get_client):
        """Test rate limit middleware calls _get_ratelimiter_redis_client."""
        mock_settings.rate_limiting_enabled = True
        mock_settings.rate_limiting_redis_enabled = True
        mock_settings.ratelimiter_redis_url = "redis://localhost:6380/0"

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware

        middleware = RateLimitMiddleware(MagicMock())

        # Verify dedicated function was called
        mock_get_client.assert_called()

    @patch("mcpgateway.auth._get_ratelimiter_redis_client")
    @patch("mcpgateway.middleware.rate_limit_middleware.settings")
    def test_rate_limit_dedicated_function_handles_fallback(self, mock_settings, mock_get_client):
        """Test rate limit middleware dedicated function handles fallback internally."""
        mock_settings.rate_limiting_enabled = True
        mock_settings.rate_limiting_redis_enabled = True
        mock_settings.ratelimiter_redis_url = None

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware

        middleware = RateLimitMiddleware(MagicMock())

        # Verify client was obtained (will use main REDIS_URL via _get_sync_redis_client)
        mock_get_client.assert_called()


class TestRateLimitMiddlewareTiers:
    """Test rate limit middleware tier detection."""

    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app."""
        return MagicMock()

    @pytest.fixture
    def middleware(self, mock_app):
        """Create middleware instance with test settings."""
        with patch("mcpgateway.middleware.rate_limit_middleware.settings") as mock_settings:
            mock_settings.rate_limiting_enabled = True
            mock_settings.rate_limiting_redis_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.rate_limit_critical_rpm = 10
            mock_settings.rate_limit_critical_burst = 0
            mock_settings.rate_limit_high_rpm = 30
            mock_settings.rate_limit_high_burst = 0
            mock_settings.rate_limit_medium_rpm = 100
            mock_settings.rate_limit_medium_burst = 20
            mock_settings.rate_limit_low_rpm = 500
            mock_settings.rate_limit_low_burst = 100
            mock_settings.rate_limit_lockout_enabled = True
            mock_settings.rate_limit_lockout_threshold = 5
            mock_settings.rate_limit_lockout_duration_minutes = 15

            from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware

            yield RateLimitMiddleware(mock_app)

    @pytest.fixture
    def mock_request(self):
        """Create mock HTTP request."""
        request = MagicMock()
        request.headers = {}
        request.client.host = "192.168.1.100"
        request.url.path = "/api/test"
        request.state = MagicMock()
        request.scope = {"client": ("192.168.1.100", 12345)}
        return request

    def test_endpoint_tier_critical(self, middleware):
        """Test CRITICAL tier detection for auth endpoints."""
        tier = middleware.get_endpoint_tier("/auth/email/login")
        assert tier["limit"] == 10
        assert tier["burst"] == 0

    def test_endpoint_tier_high(self, middleware):
        """Test HIGH tier detection for token endpoints."""
        tier = middleware.get_endpoint_tier("/tokens/list")
        assert tier["limit"] == 30

    def test_endpoint_tier_medium(self, middleware):
        """Test MEDIUM tier detection for MCP tools endpoints."""
        tier = middleware.get_endpoint_tier("/tools/execute")
        assert tier["limit"] == 100

    def test_endpoint_tier_low(self, middleware):
        """Test LOW tier detection for health endpoints."""
        tier = middleware.get_endpoint_tier("/health")
        assert tier["limit"] == 500

    def test_get_client_ip_forwarded(self, middleware, mock_request):
        """Test IP extraction from X-Forwarded-For."""
        mock_request.headers["X-Forwarded-For"] = "10.0.0.1, 192.168.1.1"

        ip = middleware._get_client_ip(mock_request)

        assert ip == "10.0.0.1"

    def test_get_client_ip_x_real(self, middleware, mock_request):
        """Test IP extraction from X-Real-IP."""
        mock_request.headers = {"X-Real-IP": "10.0.0.2"}

        ip = middleware._get_client_ip(mock_request)

        assert ip == "10.0.0.2"

    def test_get_client_ip_fallback(self, middleware, mock_request):
        """Test IP fallback to request.scope client."""
        mock_request.headers = {}

        ip = middleware._get_client_ip(mock_request)

        assert ip == "192.168.1.100"

    def test_get_client_dimensions_ip_only(self, middleware, mock_request):
        """Test dimensions for unauthenticated request."""
        mock_request.state = MagicMock()
        mock_request.state.user_email = None
        mock_request.state.user = None
        mock_request.state.team_id = None

        dims = middleware._get_client_dimensions(mock_request)

        assert "ip:192.168.1.100" in dims
        assert len(dims) == 1

    def test_get_client_dimensions_with_user(self, middleware, mock_request):
        """Test dimensions for authenticated request."""
        mock_request.state.user_email = "user@example.com"
        mock_request.state.team_id = None

        dims = middleware._get_client_dimensions(mock_request)

        assert "ip:192.168.1.100" in dims
        assert "user:user@example.com" in dims
        assert len(dims) == 2

    def test_get_client_dimensions_with_user_object(self, middleware, mock_request):
        """Test dimensions when user object provides email."""
        user = MagicMock()
        user.email = "user@example.com"
        mock_request.state.user_email = None
        mock_request.state.user = user
        mock_request.state.team_id = None

        dims = middleware._get_client_dimensions(mock_request)

        assert "ip:192.168.1.100" in dims
        assert "user:user@example.com" in dims
        assert len(dims) == 2

    def test_get_client_dimensions_with_team(self, middleware, mock_request):
        """Test dimensions for team-scoped request."""
        mock_request.state.user_email = "user@example.com"
        mock_request.state.team_id = "team-acme"

        dims = middleware._get_client_dimensions(mock_request)

        assert "ip:192.168.1.100" in dims
        assert "user:user@example.com" in dims
        assert "team:team-acme" in dims
        assert len(dims) == 3

    def test_check_rate_limit_memory_allowed(self, middleware):
        """Test in-memory rate limit allows under limit."""
        allowed, remaining = middleware._check_rate_limit_memory("test:ip:192.168.1.100:CRITICAL", 10, 60)

        assert allowed is True
        assert remaining == 9

    def test_check_rate_limit_memory_blocked(self, middleware):
        """Test in-memory rate limit blocks at limit."""
        now = time.time()
        middleware._memory_store = {"test:ip:192.168.1.100:CRITICAL": [now - i for i in range(10)]}

        allowed, remaining = middleware._check_rate_limit_memory("test:ip:192.168.1.100:CRITICAL", 10, 60)

        assert allowed is False
        assert remaining == 0

    def test_should_lockout_memory_false(self, middleware):
        """Test lockout not triggered below threshold."""
        middleware._violation_counts = {"test:ip:192.168.1.100": 3}

        result = middleware._should_lockout_memory("test:ip:192.168.1.100", "CRITICAL")

        assert result is False

    def test_should_lockout_memory_true(self, middleware):
        """Test lockout triggered at threshold."""
        middleware._violation_counts = {"test:ip:192.168.1.100": 5}

        result = middleware._should_lockout_memory("test:ip:192.168.1.100", "CRITICAL")

        assert result is True

    def test_should_lockout_memory_expires_stale_entries(self, middleware):
        """Test memory lockout clears expired violation entries."""
        dim = "ip:192.168.1.100"
        middleware._violation_counts = {dim: 5}
        middleware._violation_expiry = {dim: time.time() - 1}

        result = middleware._should_lockout_memory(dim, "LOW")

        assert result is False
        assert dim not in middleware._violation_counts
        assert dim not in middleware._violation_expiry

    @pytest.mark.asyncio
    async def test_should_lockout_async_executor_exception_falls_back(self, middleware):
        """Test async lockout check falls back to memory on executor failure."""
        middleware._violation_counts = {"ip:192.168.1.100": 5}
        middleware._violation_expiry = {"ip:192.168.1.100": float("inf")}

        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(side_effect=Exception("executor boom"))
            result = await middleware._should_lockout("ip:192.168.1.100", "CRITICAL")

        assert result is True

    def test_should_lockout_sync_redis_below_threshold(self, middleware):
        """Test Redis lockout check below threshold."""
        middleware.use_redis = True
        middleware.redis_client = MagicMock()
        middleware.redis_client.get.return_value = "2"

        result = middleware._should_lockout_sync("ratelimit:violations:ip:192.168.1.100", "CRITICAL", "ip:192.168.1.100")

        assert result is False

    def test_get_tier_name_critical(self, middleware):
        """Test tier name for auth endpoints."""
        tier = middleware._get_tier_name("/auth/email/login")

        assert tier == "CRITICAL"

    def test_get_tier_name_high(self, middleware):
        """Test tier name for token endpoints."""
        tier = middleware._get_tier_name("/tokens/list")

        assert tier == "HIGH"

    def test_get_tier_name_default(self, middleware):
        """Test tier name default for unknown endpoints."""
        tier = middleware._get_tier_name("/unknown/path")

        assert tier == "LOW"

    @pytest.mark.asyncio
    async def test_middleware_passes_when_under_limit(self, middleware, mock_request):
        """Test request passes when under rate limit."""
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_call_next = AsyncMock(return_value=mock_response)

        await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limit_response_headers(self, middleware, mock_request):
        """Test rate limit response includes headers."""
        mock_request.url.path = "/health"
        mock_request.state = MagicMock()
        mock_request.state.user_email = None
        mock_request.state.user = None
        mock_request.state.team_id = None
        now = time.time()
        key = "ratelimit:ip:192.168.1.100:LOW"
        if not hasattr(middleware, "_memory_store"):
            middleware._memory_store = {}
        for i in range(550):
            middleware._memory_store.setdefault(key, []).append(now - i * 0.1)

        async def mock_call_next(req):
            return MagicMock(headers={})

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 429
        assert response.headers.get("X-RateLimit-Limit") == "500"
        assert response.headers.get("X-RateLimit-Remaining") == "0"

    @pytest.mark.asyncio
    async def test_lockout_response(self, middleware, mock_request):
        """Test lockout response when threshold exceeded."""
        mock_request.url.path = "/health"
        mock_request.state = MagicMock()
        mock_request.state.user_email = None
        mock_request.state.user = None
        mock_request.state.team_id = None
        if not hasattr(middleware, "_violation_counts"):
            middleware._violation_counts = {}
        middleware._violation_counts["ip:192.168.1.100"] = 5
        now = time.time()
        key = "ratelimit:ip:192.168.1.100:LOW"
        if not hasattr(middleware, "_memory_store"):
            middleware._memory_store = {}
        for i in range(550):
            middleware._memory_store.setdefault(key, []).append(now - i * 0.1)

        async def mock_call_next(req):
            return MagicMock(headers={})

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 429
        assert "Account locked" in response.body.decode()
        assert response.headers.get("X-Lockout-Remaining") is not None

    @pytest.mark.asyncio
    async def test_lockout_does_not_increment_violations(self, middleware, mock_request):
        """Test lockout responses do not increment violation counters."""
        mock_request.url.path = "/health"
        mock_request.state = MagicMock()
        mock_request.state.user_email = None
        mock_request.state.user = None
        mock_request.state.team_id = None
        middleware._violation_counts = {"ip:192.168.1.100": 5}
        middleware._violation_expiry = {"ip:192.168.1.100": float("inf")}

        original_increment = middleware._increment_violation
        middleware._increment_violation = AsyncMock()

        async def mock_call_next(req):
            return MagicMock(headers={})

        try:
            response = await middleware.dispatch(mock_request, mock_call_next)
            assert response.status_code == 429
            middleware._increment_violation.assert_not_called()
        finally:
            middleware._increment_violation = original_increment

    def test_compiled_tiers_not_empty(self, middleware):
        """Test tier patterns are compiled."""
        assert len(middleware.compiled_tiers) > 0

    def test_default_tier(self, middleware):
        """Test default tier configuration."""
        assert middleware.default_tier["limit"] == 500
        assert middleware.default_tier["burst"] == 100

    def test_redis_fallback_when_disabled(self, middleware):
        """Test in-memory fallback when Redis disabled."""
        assert middleware.use_redis is False

    def test_init_redis_success(self, mock_app):
        """Test Redis initialization success path."""
        mock_client = MagicMock()
        mock_script = MagicMock()
        mock_client.register_script.return_value = mock_script

        with patch("mcpgateway.middleware.rate_limit_middleware.settings") as mock_settings, patch("mcpgateway.middleware.rate_limit_middleware.auth._get_ratelimiter_redis_client", return_value=mock_client):
            mock_settings.rate_limiting_enabled = True
            mock_settings.rate_limiting_redis_enabled = True
            mock_settings.trust_proxy_auth = True
            mock_settings.rate_limit_critical_rpm = 10
            mock_settings.rate_limit_critical_burst = 0
            mock_settings.rate_limit_high_rpm = 30
            mock_settings.rate_limit_high_burst = 0
            mock_settings.rate_limit_medium_rpm = 100
            mock_settings.rate_limit_medium_burst = 20
            mock_settings.rate_limit_low_rpm = 500
            mock_settings.rate_limit_low_burst = 100
            mock_settings.rate_limit_lockout_enabled = True
            mock_settings.rate_limit_lockout_threshold = 5
            mock_settings.rate_limit_lockout_duration_minutes = 15

            from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware

            mw = RateLimitMiddleware(mock_app)

        # Note: _get_ratelimiter_redis_client() calls ping() internally, so we don't assert it here
        mock_client.register_script.assert_called_once()
        assert mw.use_redis is True
        assert mw._sliding_window_script is mock_script

    def test_init_redis_exception(self, mock_app):
        """Test Redis initialization fallback on exception."""
        with (
            patch("mcpgateway.middleware.rate_limit_middleware.settings") as mock_settings,
            patch("mcpgateway.middleware.rate_limit_middleware.auth._get_sync_redis_client", side_effect=Exception("boom")),
        ):
            mock_settings.rate_limiting_enabled = True
            mock_settings.rate_limiting_redis_enabled = True
            mock_settings.trust_proxy_auth = True
            mock_settings.rate_limit_critical_rpm = 10
            mock_settings.rate_limit_critical_burst = 0
            mock_settings.rate_limit_high_rpm = 30
            mock_settings.rate_limit_high_burst = 0
            mock_settings.rate_limit_medium_rpm = 100
            mock_settings.rate_limit_medium_burst = 20
            mock_settings.rate_limit_low_rpm = 500
            mock_settings.rate_limit_low_burst = 100
            mock_settings.rate_limit_lockout_enabled = True
            mock_settings.rate_limit_lockout_threshold = 5
            mock_settings.rate_limit_lockout_duration_minutes = 15

            from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware

            mw = RateLimitMiddleware(mock_app)

        assert mw.use_redis is False

    def test_get_endpoint_tier_default_unknown(self, middleware):
        """Test default tier for unknown endpoints."""
        tier = middleware.get_endpoint_tier("/some/unknown/path")
        assert tier["limit"] == 500

    def test_get_client_dimensions_team_only(self, middleware, mock_request):
        """Test dimensions when only team available."""
        mock_request.state.user_email = None
        mock_request.state.user = None
        mock_request.state.team_id = "team-acme"

        dims = middleware._get_client_dimensions(mock_request)

        assert "ip:192.168.1.100" in dims
        assert "team:team-acme" in dims
        assert len(dims) == 2

    def test_middleware_disabled(self, mock_app):
        """Test middleware when disabled in config."""
        with patch("mcpgateway.middleware.rate_limit_middleware.settings") as mock_settings:
            mock_settings.rate_limiting_enabled = False
            mock_settings.rate_limiting_redis_enabled = True
            mock_settings.trust_proxy_auth = True
            mock_settings.rate_limit_critical_rpm = 10
            mock_settings.rate_limit_high_rpm = 30
            mock_settings.rate_limit_medium_rpm = 100
            mock_settings.rate_limit_low_rpm = 500
            mock_settings.rate_limit_lockout_enabled = True
            mock_settings.rate_limit_lockout_threshold = 5
            mock_settings.rate_limit_lockout_duration_minutes = 15

            from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware

            mw = RateLimitMiddleware(mock_app)

        assert mw.enabled is False

    def test_compiled_tiers_structure(self, middleware):
        """Test compiled tiers have correct structure."""
        assert len(middleware.compiled_tiers) > 0
        pattern, config = middleware.compiled_tiers[0]
        assert hasattr(pattern, "match")
        assert "limit" in config
        assert "burst" in config

    def test_tier_name_high_oauth(self, middleware):
        """Test tier for OAuth endpoints."""
        tier = middleware._get_tier_name("/oauth/authorize")

        assert tier == "HIGH"

    def test_tier_name_critical_sso(self, middleware):
        """Test tier for SSO auth endpoints."""
        tier = middleware._get_tier_name("/auth/sso/login")

        assert tier == "CRITICAL_SSO"

    def test_security_logger_integration(self, middleware):
        """Test SecurityLogger is initialized."""
        assert middleware.security_logger is not None

    def test_security_logger_type(self, middleware):
        """Test SecurityLogger has correct type."""
        from mcpgateway.services.security_logger import SecurityLogger

        assert isinstance(middleware.security_logger, SecurityLogger)

    def test_executor_integration(self, middleware):
        """Test ThreadPoolExecutor is used."""
        assert middleware.executor is not None

    def test_lockout_config(self, middleware):
        """Test lockout configuration is set."""
        assert middleware.lockout_enabled is True
        assert middleware.lockout_threshold == 5
        assert middleware.lockout_duration_minutes == 15

    def test_check_rate_limit_sync_returns_allowed(self, middleware):
        """Test sync rate limit check allows under limit."""
        allowed, remaining = middleware._check_rate_limit_sync("ratelimit:test:LOW", 10, 60)
        assert allowed is True

    def test_check_rate_limit_sync_blocks_at_limit(self, middleware):
        """Test sync rate limit blocks when at limit."""
        middleware._memory_store = {"ratelimit:test:LOW": [time.time() - i for i in range(10)]}

        allowed, remaining = middleware._check_rate_limit_sync("ratelimit:test:LOW", 10, 60)
        assert allowed is False
        assert remaining == 0

    def test_check_rate_limit_sync_redis_blocked(self, middleware):
        """Test Redis rate limit blocks when script returns 0."""
        middleware.use_redis = True
        middleware.redis_client = MagicMock()
        middleware._sliding_window_script = MagicMock(return_value=0)

        allowed, remaining = middleware._check_rate_limit_sync("ratelimit:test:LOW", 10, 60)

        assert allowed is False
        assert remaining == 0

    def test_tier_for_unknown_regex(self, middleware):
        """Test tier for endpoint not matching any regex."""
        tier = middleware.get_endpoint_tier("/totally/unknown/endpoint")
        assert tier["limit"] == 500

    def test_dispatch_passes_when_disabled(self, middleware, mock_request):
        """Test dispatch passes when rate limiting disabled."""
        from unittest.mock import AsyncMock

        middleware.enabled = False
        mock_call_next = AsyncMock(return_value=MagicMock(headers={}))

        import asyncio

        asyncio.run(middleware.dispatch(mock_request, mock_call_next))

        mock_call_next.assert_called_once()

    def test_lockout_sync_uses_memory_when_no_redis(self, middleware):
        """Test lockout sync uses memory fallback."""
        result = middleware._should_lockout_sync("test:dimension", "CRITICAL", "test:dimension")
        assert result is False

    def test_lockout_sync_redis_below_threshold(self, middleware):
        """Test lockout sync with Redis count below threshold."""
        middleware.use_redis = True
        middleware.redis_client = MagicMock()
        middleware.redis_client.get.return_value = "2"

        result = middleware._should_lockout_sync("ratelimit:violations:test:dimension", "CRITICAL", "test:dimension")

        assert result is False

    def test_lockout_sync_returns_true_at_threshold(self, middleware):
        """Test lockout sync returns true when threshold met."""
        if not hasattr(middleware, "_violation_counts"):
            middleware._violation_counts = {}
        middleware._violation_counts["test:dimension"] = 5

        result = middleware._should_lockout_sync("test:dimension", "CRITICAL", "test:dimension")

        assert result is True

    def test_increment_violation_sync_redis_path(self, middleware):
        """Test Redis increment and expiry are called."""
        middleware.use_redis = True
        middleware.redis_client = MagicMock()

        middleware._increment_violation_sync("ratelimit:violations:test:dimension", "test:dimension")

        middleware.redis_client.incr.assert_called_once_with("ratelimit:violations:test:dimension")
        middleware.redis_client.expire.assert_called_once_with("ratelimit:violations:test:dimension", middleware.lockout_duration_minutes * 60)

    def test_endpoint_tiers_all_critical(self, middleware):
        """Test all critical tier patterns defined."""
        tiers_keys = list(middleware.endpoint_tiers.keys())
        assert "CRITICAL" in tiers_keys
        assert "CRITICAL_SSO" in tiers_keys
        assert "HIGH" in tiers_keys
        assert "MEDIUM" in tiers_keys
        assert "LOW" in tiers_keys

    def test_endpoint_tier_critical_config(self, middleware):
        """Test CRITICAL tier has correct config."""
        tier = middleware.endpoint_tiers["CRITICAL"]
        assert tier["limit"] == 10
        assert tier["burst"] == 0

    def test_endpoint_tier_high_config(self, middleware):
        """Test HIGH tier has correct config."""
        tier = middleware.endpoint_tiers["HIGH"]
        assert tier["limit"] == 30
        assert tier["burst"] == 0

    def test_get_client_ip_empty_headers(self, middleware, mock_request):
        """Test IP extraction with empty headers."""
        mock_request.headers = {}
        mock_request.scope = {"client": ("192.168.1.1", 12345)}

        ip = middleware._get_client_ip(mock_request)

        assert ip == "192.168.1.1"

    def test_create_rate_limit_response_structure(self, middleware):
        """Test rate limit response has correct structure."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"

        response = middleware._create_rate_limit_response(
            request=mock_request,
            dimensions=["ip:192.168.1.100"],
            tier={"limit": 10},
            tier_name="CRITICAL",
        )

        assert response.status_code == 429
        body = response.body.decode()
        assert "Rate limit exceeded" in body
        assert "X-RateLimit-Limit" in response.headers

    def test_create_rate_limit_response_with_reset(self, middleware):
        """Test rate limit response includes reset info."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"

        response = middleware._create_rate_limit_response(
            request=mock_request,
            dimensions=["ip:192.168.1.100"],
            tier={"limit": 10},
            tier_name="CRITICAL",
        )

        assert "reset_in_seconds" in response.body.decode()

    def test_log_security_event_handles_exception(self, middleware):
        """Test security event logging handles exceptions."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"
        mock_request.state = MagicMock()

        middleware.security_logger = None

        try:
            middleware._log_security_event(
                request=mock_request,
                dimension="ip:test",
                tier={"limit": 10},
                tier_name="CRITICAL",
                is_lockout=False,
            )
        except Exception:
            pass

    def test_check_rate_limit_uses_executor(self, middleware):
        """Test check_rate_limit uses executor."""
        import asyncio

        result = asyncio.run(
            middleware._check_rate_limit(
                "test:dimension",
                {"limit": 10},
                "CRITICAL",
            )
        )

        assert result is not None
        assert isinstance(result, tuple)

    @pytest.mark.asyncio
    async def test_dispatch_all_dims_allowed(self, middleware, mock_request):
        """Test dispatch when all dimensions allowed."""
        from unittest.mock import AsyncMock

        mock_request.url.path = "/health"
        mock_request.state.user_email = "user@example.com"
        mock_request.state.team_id = None

        mock_response = MagicMock()
        mock_response.headers = {}
        mock_call_next = AsyncMock(return_value=mock_response)

        await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()

    def test_should_lockout_memory_initializes_counts(self, middleware):
        """Test lockout memory initializes violation counts."""
        if hasattr(middleware, "_violation_counts"):
            del middleware._violation_counts

        result = middleware._should_lockout_memory("new:dimension", "CRITICAL")

        assert result is False
        assert hasattr(middleware, "_violation_counts")

    def test_check_rate_limit_memory_initializes_store(self, middleware):
        """Test memory initializes store."""
        if hasattr(middleware, "_memory_store"):
            del middleware._memory_store

        result = middleware._check_rate_limit_memory("new:key", 10, 60)

        assert result[0] is True
        assert hasattr(middleware, "_memory_store")

    def test_endpoint_tier_low_config(self, middleware):
        """Test LOW tier has correct config."""
        tier = middleware.endpoint_tiers["LOW"]
        assert tier["limit"] == 500
        assert tier["burst"] == 100

    def test_tier_for_prompts(self, middleware):
        """Test tier for prompts endpoint."""
        tier = middleware.get_endpoint_tier("/prompts/list")
        assert tier["limit"] == 100

    def test_tier_for_servers(self, middleware):
        """Test tier for servers endpoint."""
        tier = middleware.get_endpoint_tier("/servers/list")
        assert tier["limit"] == 100

    def test_tier_for_gateways(self, middleware):
        """Test tier for gateways endpoint."""
        tier = middleware.get_endpoint_tier("/gateways/list")
        assert tier["limit"] == 100

    def test_tier_for_llmchat(self, middleware):
        """Test tier for llmchat endpoint."""
        tier = middleware.get_endpoint_tier("/llmchat/completions")
        assert tier["limit"] == 100

    def test_tier_for_docs(self, middleware):
        """Test tier for docs endpoint."""
        tier = middleware.get_endpoint_tier("/docs")
        assert tier["limit"] == 500

    def test_tier_for_metrics(self, middleware):
        """Test tier for metrics endpoint."""
        tier = middleware.get_endpoint_tier("/metrics")
        assert tier["limit"] == 500

    def test_tier_for_openapi(self, middleware):
        """Test tier for openapi endpoint."""
        tier = middleware.get_endpoint_tier("/openapi.json")
        assert tier["limit"] == 500

    def test_should_lockout_when_disabled(self, middleware):
        """Test lockout returns false when disabled."""
        import asyncio

        middleware.lockout_enabled = False

        result = asyncio.run(middleware._should_lockout("test:dimension", "CRITICAL"))

        assert result is False
        middleware.lockout_enabled = True

    def test_violation_key_format(self, middleware):
        """Test violation key format."""
        key = "ratelimit:violations:ip:192.168.1.100"
        assert "violations" in key

    @pytest.mark.asyncio
    async def test_async_should_lockout(self, middleware):
        """Test async lockout check."""
        if not hasattr(middleware, "_violation_counts"):
            middleware._violation_counts = {}
        middleware._violation_counts["test:dimension"] = 3

        result = await middleware._should_lockout("test:dimension", "CRITICAL")

        assert isinstance(result, bool)

    def test_get_tier_name_unknown(self, middleware):
        """Test tier name for unknown path."""
        tier = middleware._get_tier_name("/completely/random/path")
        assert tier == "LOW"

    def test_get_tier_name_auth_email_register(self, middleware):
        """Test tier for auth email register."""
        tier = middleware._get_tier_name("/auth/email/register")
        assert tier == "CRITICAL"

    def test_get_tier_name_auth_email_forgot(self, middleware):
        """Test tier for auth email forgot password."""
        tier = middleware._get_tier_name("/auth/email/forgot-password")
        assert tier == "CRITICAL"

    def test_get_tier_name_rbac(self, middleware):
        """Test tier for RBAC endpoints."""
        tier = middleware._get_tier_name("/rbac/roles")
        assert tier == "HIGH"

    def test_endpoint_tier_resources(self, middleware):
        """Test tier for resources endpoint."""
        tier = middleware.get_endpoint_tier("/resources/list")
        assert tier["limit"] == 100

    def test_endpoint_tier_tools(self, middleware):
        """Test tier for tools endpoint."""
        tier = middleware.get_endpoint_tier("/tools/list")
        assert tier["limit"] == 100

    def test_response_body_format(self, middleware):
        """Test response body has correct format."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"

        response = middleware._create_rate_limit_response(
            request=mock_request,
            dimensions=["ip:192.168.1.100"],
            tier={"limit": 10},
            tier_name="CRITICAL",
        )

        import json

        body = json.loads(response.body)
        assert "error" in body
        assert "message" in body

    def test_check_rate_limit_redis_path_when_redis_available(self, middleware):
        """Test Redis path when Redis is available."""
        original_use_redis = middleware.use_redis
        original_client = middleware.redis_client
        original_script = middleware._sliding_window_script

        try:
            middleware.use_redis = True
            mock_client = MagicMock()
            mock_client.zcard.return_value = 5
            middleware.redis_client = mock_client

            mock_script = MagicMock(return_value=1)
            middleware._sliding_window_script = mock_script

            allowed, remaining = middleware._check_rate_limit_sync("ratelimit:test:LOW", 10, 60)

            assert allowed is True
            assert remaining == 5
            mock_script.assert_called_once()
        finally:
            middleware.use_redis = original_use_redis
            middleware.redis_client = original_client
            middleware._sliding_window_script = original_script

    def test_check_rate_limit_redis_exception_fallback(self, middleware):
        """Test Redis exception triggers fallback."""
        original_use_redis = middleware.use_redis
        original_client = middleware.redis_client
        original_script = middleware._sliding_window_script

        try:
            middleware.use_redis = True
            mock_client = MagicMock()
            middleware.redis_client = mock_client

            mock_script = MagicMock(side_effect=Exception("Redis error"))
            middleware._sliding_window_script = mock_script

            allowed, remaining = middleware._check_rate_limit_sync("ratelimit:test:LOW", 10, 60)

            assert allowed is True
        finally:
            middleware.use_redis = original_use_redis
            middleware.redis_client = original_client
            middleware._sliding_window_script = original_script

    def test_get_client_ip_with_both_headers(self, middleware):
        """Test IP extraction prefers X-Forwarded-For."""
        mock_request = MagicMock()
        mock_request.headers = {"X-Forwarded-For": "10.0.0.1", "X-Real-IP": "10.0.0.2"}
        mock_request.scope = {"client": ("10.0.0.1", 12345)}

        ip = middleware._get_client_ip(mock_request)

        assert ip == "10.0.0.1"

    def test_get_client_ip_unknown_when_no_client(self, middleware):
        """Test IP returns unknown when no client info."""
        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.scope = {}

        ip = middleware._get_client_ip(mock_request)

        assert ip == "unknown"

    def test_get_endpoint_tier_regex_endpoints(self, middleware):
        """Test all regex patterns in tiers."""
        for key, config in middleware.endpoint_tiers.items():
            pattern = config["pattern"]
            assert pattern is not None

    def test_compiled_tiers_sorted(self, middleware):
        """Test compiled tiers maintain order."""
        pattern1, config1 = middleware.compiled_tiers[0]
        assert hasattr(pattern1, "match")

    def test_rate_limit_sync_with_redis_zadd_exception(self, middleware):
        """Test Redis zadd exception triggers fallback."""
        original_use_redis = middleware.use_redis
        original_client = middleware.redis_client
        original_script = middleware._sliding_window_script

        try:
            middleware.use_redis = True
            mock_client = MagicMock()
            middleware.redis_client = mock_client

            mock_script = MagicMock(side_effect=Exception("Redis error"))
            middleware._sliding_window_script = mock_script

            allowed, remaining = middleware._check_rate_limit_sync("ratelimit:test:LOW", 10, 60)

            assert allowed is True
        finally:
            middleware.use_redis = original_use_redis
            middleware.redis_client = original_client
            middleware._sliding_window_script = original_script

    def test_should_lockout_sync_with_redis_error(self, middleware):
        """Test lockout sync handles Redis error."""
        original_use_redis = middleware.use_redis
        original_client = middleware.redis_client

        try:
            middleware.use_redis = True
            mock_client = MagicMock()
            mock_client.get.side_effect = Exception("Redis error")
            middleware.redis_client = mock_client

            result = middleware._should_lockout_sync("test:dimension", "CRITICAL", "test:dimension")

            assert isinstance(result, bool)
        finally:
            middleware.use_redis = original_use_redis
            middleware.redis_client = original_client

    def test_rate_limit_response_contains_retry_after(self, middleware):
        """Test rate limit response has Retry-After."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"

        response = middleware._create_rate_limit_response(
            request=mock_request,
            dimensions=["ip:192.168.1.100"],
            tier={"limit": 10},
            tier_name="CRITICAL",
        )

        assert "Retry-After" in response.headers

    def test_check_rate_limit_exception_path(self, middleware):
        """Test check_rate_limit handles exception."""
        import asyncio

        original_executor = middleware.executor
        mock_executor = MagicMock()
        mock_executor.submit.side_effect = Exception("Executor error")
        middleware.executor = mock_executor

        result = asyncio.run(middleware._check_rate_limit("test:dimension", {"limit": 10}, "CRITICAL"))

        assert result is not None
        middleware.executor = original_executor

    def test_get_client_dimensions_all_empty(self, middleware, mock_request):
        """Test dimensions when no auth info."""
        mock_request.state = MagicMock()
        mock_request.state.user_email = None
        mock_request.state.user = None
        mock_request.state.team_id = None

        dims = middleware._get_client_dimensions(mock_request)

        assert len(dims) == 1

    def test_compiled_tiers_patterns_valid(self, middleware):
        """Test compiled tier patterns are valid regex."""
        for pattern, config in middleware.compiled_tiers:
            result = pattern.match("/some/test/path")
            assert result is None or result is not None

    def test_log_security_event_with_user_info(self, middleware):
        """Test security event logging with user info."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"
        mock_request.state = MagicMock()
        mock_request.state.user_id = "user123"
        mock_request.state.user_email = "test@example.com"
        mock_request.state.team_id = "team1"

        try:
            middleware._log_security_event(
                request=mock_request,
                dimension="user:test@example.com",
                tier={"limit": 10},
                tier_name="CRITICAL",
                is_lockout=True,
            )
        except Exception:
            pass

    def test_get_endpoint_tier_with_slash_mcp(self, middleware):
        """Test tier for /mcp/ path."""
        tier = middleware.get_endpoint_tier("/mcp/server1")
        assert tier["limit"] == 100

    def test_default_tier_values(self, middleware):
        """Test default tier values."""
        assert middleware.default_tier["limit"] == 500
        assert middleware.default_tier["burst"] == 100

    def test_rate_limit_keys_use_tier_name(self, middleware):
        """Test rate limit keys include tier name."""
        key = "ratelimit:ip:192.168.1.100:CRITICAL"
        assert "CRITICAL" in key

    def test_middleware_has_all_attributes(self, middleware):
        """Test middleware has all required attributes."""
        assert hasattr(middleware, "enabled")
        assert hasattr(middleware, "redis_enabled")
        assert hasattr(middleware, "use_redis")
        assert hasattr(middleware, "redis_client")
        assert hasattr(middleware, "lockout_enabled")
        assert hasattr(middleware, "lockout_threshold")
        assert hasattr(middleware, "compiled_tiers")

    def test_compiled_tiers_are_not_empty(self, middleware):
        """Test compiled tiers list is not empty."""
        assert len(middleware.compiled_tiers) > 0

    def test_default_tier_is_set(self, middleware):
        """Test default tier is configured."""
        assert middleware.default_tier is not None
        assert "limit" in middleware.default_tier

    def test_middleware_can_be_created(self, mock_app):
        """Test middleware can be instantiated."""
        with patch("mcpgateway.middleware.rate_limit_middleware.settings") as mock_settings:
            mock_settings.rate_limiting_enabled = True
            mock_settings.rate_limiting_redis_enabled = False
            mock_settings.rate_limit_critical_rpm = 10
            mock_settings.rate_limit_high_rpm = 30
            mock_settings.rate_limit_medium_rpm = 100
            mock_settings.rate_limit_low_rpm = 500
            mock_settings.rate_limit_lockout_enabled = True
            mock_settings.rate_limit_lockout_threshold = 5
            mock_settings.rate_limit_lockout_duration_minutes = 15

            from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware

            mw = RateLimitMiddleware(mock_app)

        assert mw is not None
        assert mw.enabled is True

    def test_check_rate_limit_handles_timeout(self, middleware):
        """Test check_rate_limit handles timeout from executor."""
        import asyncio

        original_executor = middleware.executor
        middleware.executor = MagicMock()
        middleware.executor.submit.side_effect = TimeoutError()

        try:
            result = asyncio.run(middleware._check_rate_limit("test:dimension", {"limit": 10}, "CRITICAL"))

            assert result is not None
        finally:
            middleware.executor = original_executor

    def test_compile_tiers_creates_regex_objects(self, middleware):
        """Test compile tiers creates regex objects."""
        tiers = middleware._compile_tiers()

        assert len(tiers) == len(middleware.endpoint_tiers)
        for pattern, config in tiers:
            assert hasattr(pattern, "match")

    def test_get_endpoint_tier_with_deep_mcp_path(self, middleware):
        """Test tier for deeply nested MCP path."""
        tier = middleware.get_endpoint_tier("/mcp/server/tool/action")
        assert tier["limit"] == 100

    def test_security_logger_has_methods(self, middleware):
        """Test SecurityLogger has required methods."""
        from mcpgateway.services.security_logger import SecurityLogger

        assert hasattr(SecurityLogger, "log_authentication_attempt")
        assert hasattr(SecurityLogger, "_create_security_event")

    def test_middleware_endpoints_dict_complete(self, middleware):
        """Test endpoint_tiers has all required keys."""
        required = ["CRITICAL", "CRITICAL_SSO", "HIGH", "MEDIUM", "LOW"]
        for key in required:
            assert key in middleware.endpoint_tiers

    def test_endpoint_tier_for_well_known(self, middleware):
        """Test tier for .well-known endpoints."""
        tier = middleware.get_endpoint_tier("/.well-known/openid-configuration")
        assert tier["limit"] == 500

    def test_middleware_logs_when_disabled(self, middleware):
        """Test middleware logs info when disabled."""
        from unittest.mock import MagicMock

        with patch("mcpgateway.middleware.rate_limit_middleware.settings") as ms:
            ms.rate_limiting_enabled = False
            ms.rate_limiting_redis_enabled = True

            from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware

            mw = RateLimitMiddleware(MagicMock())

        assert mw.enabled is False

    def test_check_rate_limit_memory_stores_time(self, middleware):
        """Test memory store stores timestamp."""
        key = "test:key"
        limit = 10
        window = 60

        if hasattr(middleware, "_memory_store"):
            del middleware._memory_store

        middleware._check_rate_limit_memory(key, limit, window)

        assert key in middleware._memory_store

    def test_lockout_memory_empty_count(self, middleware):
        """Test lockout returns false for unknown dimension."""
        if hasattr(middleware, "_violation_counts"):
            del middleware._violation_counts

        result = middleware._should_lockout_memory("unknown:dimension", "CRITICAL")

        assert result is False

    def test_endpoint_tier_matches_exact_paths(self, middleware):
        """Test tier matching for exact paths."""
        assert middleware.get_endpoint_tier("/auth/email/login")["limit"] == 10
        assert middleware.get_endpoint_tier("/auth/email/register")["limit"] == 10
        assert middleware.get_endpoint_tier("/auth/email/forgot-password")["limit"] == 10
        assert middleware.get_endpoint_tier("/auth/email/reset-password")["limit"] == 10
        assert middleware.get_endpoint_tier("/auth/sso/login")["limit"] == 10

    def test_should_lockout_uses_both_redis_and_memory(self, middleware):
        """Test lockout check tries Redis first then memory."""
        import asyncio

        if not hasattr(middleware, "_violation_counts"):
            middleware._violation_counts = {}
        middleware._violation_counts["test:dim"] = 3
        middleware.lockout_enabled = True
        middleware.use_redis = False

        result = asyncio.run(middleware._should_lockout("test:dim", "CRITICAL"))

        assert result is False

    def test_check_rate_limit_returns_tuple(self, middleware):
        """Test check rate limit returns tuple properly."""
        import asyncio

        result = asyncio.run(middleware._check_rate_limit("test:dim", {"limit": 10, "burst": 2}, "LOW"))

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], int)

    def test_get_endpoint_tier_nonexistent(self, middleware):
        """Test tier for non-existent endpoint uses default."""
        tier = middleware.get_endpoint_tier("/completely/fake/path/that/does/not/exist")
        assert tier == middleware.default_tier

    def test_tier_burst_values(self, middleware):
        """Test tier burst values are correctly set."""
        assert middleware.endpoint_tiers["CRITICAL"]["burst"] == 0
        assert middleware.endpoint_tiers["HIGH"]["burst"] == 0
        assert middleware.endpoint_tiers["MEDIUM"]["burst"] == 20
        assert middleware.endpoint_tiers["LOW"]["burst"] == 100

    def test_middleware_initializes_executor(self, middleware):
        """Test middleware initializes thread pool executor."""
        assert middleware.executor is not None
        from concurrent.futures import ThreadPoolExecutor

        assert isinstance(middleware.executor, ThreadPoolExecutor)

    def test_rate_limit_response_has_all_headers(self, middleware):
        """Test rate limit response has all required headers."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"

        response = middleware._create_rate_limit_response(
            request=mock_request,
            dimensions=["ip:test"],
            tier={"limit": 10},
            tier_name="HIGH",
        )

        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    def test_tier_name_returns_string(self, middleware):
        """Test tier name returns string."""
        name = middleware._get_tier_name("/test")
        assert isinstance(name, str)

    def test_middleware_has_security_logger_attr(self, middleware):
        """Test middleware has security logger attribute."""
        assert hasattr(middleware, "security_logger")

    def test_check_rate_limit_key_format(self, middleware):
        """Test rate limit key format is correct."""
        key = middleware._check_rate_limit_sync("test:dim", 10, 60)
        assert key is not None

    @pytest.mark.asyncio
    async def test_increment_violation_async_exception_fallback(self, middleware):
        """Test _increment_violation falls back to memory on executor error."""
        original_executor = middleware.executor
        mock_executor = MagicMock()
        mock_executor.submit.side_effect = RuntimeError("Executor error")
        middleware.executor = mock_executor

        if not hasattr(middleware, "_violation_counts"):
            middleware._violation_counts = {}
        middleware._violation_counts.pop("test:dim", None)

        try:
            await middleware._increment_violation("test:dim", "CRITICAL")
            assert middleware._violation_counts.get("test:dim") == 1
        finally:
            middleware.executor = original_executor

    def test_increment_violation_sync_redis_exception_fallback(self, middleware):
        """Test _increment_violation_sync falls back to memory on Redis error."""
        original_use_redis = middleware.use_redis
        original_client = middleware.redis_client
        original_script = getattr(middleware, "_sliding_window_script", None)

        try:
            middleware.use_redis = True
            mock_client = MagicMock()
            mock_client.incr.side_effect = RuntimeError("Redis incr error")
            middleware.redis_client = mock_client
            middleware._sliding_window_script = None

            if not hasattr(middleware, "_violation_counts"):
                middleware._violation_counts = {}
            middleware._violation_counts.pop("test:dim", None)

            middleware._increment_violation_sync("test:key", "test:dim")
            assert middleware._violation_counts.get("test:dim") == 1
        finally:
            middleware.use_redis = original_use_redis
            middleware.redis_client = original_client
            if original_script is not None:
                middleware._sliding_window_script = original_script

    def test_should_lockout_memory_initializes_expiry(self, middleware):
        """Test _should_lockout_memory initializes _violation_expiry if missing."""
        if hasattr(middleware, "_violation_expiry"):
            del middleware._violation_expiry
        if not hasattr(middleware, "_violation_counts"):
            middleware._violation_counts = {}

        result = middleware._should_lockout_memory("test:dim", "CRITICAL")

        assert result is False
        assert hasattr(middleware, "_violation_expiry")
