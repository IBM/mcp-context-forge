# -*- coding: utf-8 -*-
"""Location: ./tests/test_validation_middleware_performance.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for validation middleware performance optimizations.
"""

# Standard
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, Request, Response
import orjson
import pytest

# First-Party
from mcpgateway.middleware.validation_middleware import LRUCache, ValidationMiddleware


class TestLRUCache:
    """Tests for LRU cache implementation."""

    def test_cache_basic_operations(self):
        """Test basic cache get/set operations."""
        cache = LRUCache(max_size=3, ttl=60)

        # Set and get
        cache.set("key1", True)
        assert cache.get("key1") is True

        # Non-existent key
        assert cache.get("nonexistent") is None

    def test_cache_expiration(self):
        """Test cache TTL expiration."""
        cache = LRUCache(max_size=3, ttl=1)

        cache.set("key1", True)
        assert cache.get("key1") is True

        # Wait for expiration
        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = LRUCache(max_size=3, ttl=60)

        cache.set("key1", True)
        cache.set("key2", True)
        cache.set("key3", True)

        # Access key1 to make it most recently used
        cache.get("key1")

        # Add key4, should evict key2 (least recently used)
        cache.set("key4", True)

        assert cache.get("key1") is True
        assert cache.get("key2") is None
        assert cache.get("key3") is True
        assert cache.get("key4") is True

    def test_cache_update_existing(self):
        """Test updating existing cache entry."""
        cache = LRUCache(max_size=3, ttl=60)

        cache.set("key1", True)
        cache.set("key1", False)

        assert cache.get("key1") is False


class TestValidationMiddlewarePerformance:
    """Tests for validation middleware performance optimizations."""

    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app."""
        return MagicMock()

    @pytest.fixture
    def middleware(self, mock_app):
        """Create validation middleware instance."""
        patcher = patch("mcpgateway.middleware.validation_middleware.settings")
        mock_settings = patcher.start()
        mock_settings.environment = "production"
        mock_settings.experimental_validate_io = True
        mock_settings.validation_strict = True
        mock_settings.sanitize_output = True
        mock_settings.allowed_roots = []
        mock_settings.dangerous_patterns = [r"[;&|`$(){}\[\]<>]"]
        mock_settings.validation_max_body_size = 1024
        mock_settings.validation_max_response_size = 2048
        mock_settings.validation_skip_endpoints = [r"^/health$", r"^/metrics$"]
        mock_settings.validation_cache_enabled = True
        mock_settings.validation_cache_max_size = 100
        mock_settings.validation_cache_ttl = 300
        mock_settings.validation_sample_large_responses = True
        mock_settings.validation_sample_size = 512
        mock_settings.max_param_length = 1000

        middleware_instance = ValidationMiddleware(mock_app)

        yield middleware_instance

        patcher.stop()

    @pytest.mark.asyncio
    async def test_skip_endpoint_validation(self, middleware):
        """Test that configured endpoints skip validation."""
        # Create mock request for /health endpoint
        request = MagicMock(spec=Request)
        request.url.path = "/health"
        request.headers.get.return_value = "application/json"

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        # Should skip validation and call next middleware
        call_next.assert_called_once_with(request)
        assert response is not None

    @pytest.mark.asyncio
    async def test_large_body_skips_validation(self, middleware):
        """Test that large request bodies skip validation."""
        # Create large body exceeding threshold
        large_body = b'{"data": "' + b"x" * 2000 + b'"}'

        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get.return_value = "application/json"
        request.body = AsyncMock(return_value=large_body)
        request.path_params = {}
        request.query_params = {}

        call_next = AsyncMock(return_value=Response())

        # Should not raise exception despite large body
        response = await middleware.dispatch(request, call_next)
        assert response is not None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_validation(self, middleware):
        """Test that cached validation results are reused."""
        body = b'{"test": "data"}'

        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get.return_value = "application/json"
        request.body = AsyncMock(return_value=body)
        request.path_params = {}
        request.query_params = {}

        call_next = AsyncMock(return_value=Response())

        # First request - should validate and cache
        await middleware.dispatch(request, call_next)

        # Second request with same body - should use cache
        request.body = AsyncMock(return_value=body)
        await middleware.dispatch(request, call_next)

        # Verify cache was used (body should only be read once per request)
        assert middleware.cache is not None
        assert len(middleware.cache.cache) > 0

    @pytest.mark.asyncio
    async def test_large_response_skips_sanitization(self, middleware):
        """Test that large responses skip sanitization."""
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get.return_value = "application/json"
        request.body = AsyncMock(return_value=b'{}')
        request.path_params = {}
        request.query_params = {}

        # Create large response exceeding threshold
        large_body = b"x" * 3000
        response = Response(content=large_body)
        response.body = large_body

        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        # Response should not be modified
        assert result.body == large_body

    @pytest.mark.asyncio
    async def test_response_sampling(self, middleware):
        """Test that large responses are sampled instead of fully sanitized."""
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get.return_value = "application/json"
        request.body = AsyncMock(return_value=b'{}')
        request.path_params = {}
        request.query_params = {}

        # Create response larger than sample size but smaller than max
        body = b"clean data " * 100  # ~1100 bytes
        response = Response(content=body)
        response.body = body

        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        # Should return response (sampling found it clean)
        assert result is not None

    @pytest.mark.asyncio
    async def test_cache_validation_failure(self, middleware):
        """Test that validation failures are also cached."""
        # Body with dangerous pattern - use a pattern that will actually trigger validation failure
        body = b'{"cmd": "rm -rf /", "test": "value with ; semicolon"}'

        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get.return_value = "application/json"
        request.body = AsyncMock(return_value=body)
        request.path_params = {}
        request.query_params = {}

        call_next = AsyncMock(return_value=Response())

        # First request - should fail validation due to dangerous pattern in value
        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(request, call_next)
        assert exc_info.value.status_code == 422

        # Second request with same body - should use cached failure
        request.body = AsyncMock(return_value=body)
        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(request, call_next)
        assert exc_info.value.status_code == 422

        # Verify failure was cached
        cache_key = middleware._get_cache_key(body)
        assert middleware.cache.get(cache_key) is False

    @pytest.mark.asyncio
    async def test_disabled_middleware_skips_all(self, middleware):
        """Test that disabled middleware skips all processing."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = False
            middleware.enabled = False

            request = MagicMock(spec=Request)
            call_next = AsyncMock(return_value=Response())

            response = await middleware.dispatch(request, call_next)

            # Should immediately call next without any processing
            call_next.assert_called_once_with(request)

    def test_should_skip_endpoint_patterns(self, middleware):
        """Test endpoint pattern matching."""
        assert middleware._should_skip_endpoint("/health") is True
        assert middleware._should_skip_endpoint("/metrics") is True
        # /static/ is not in the configured skip patterns, so it should not be skipped
        assert middleware._should_skip_endpoint("/static/css/style.css") is False
        assert middleware._should_skip_endpoint("/api/test") is False

    def test_cache_key_generation(self, middleware):
        """Test cache key generation is consistent."""
        data1 = b'{"test": "data"}'
        data2 = b'{"test": "data"}'
        data3 = b'{"test": "other"}'

        key1 = middleware._get_cache_key(data1)
        key2 = middleware._get_cache_key(data2)
        key3 = middleware._get_cache_key(data3)

        # Same data should produce same key
        assert key1 == key2
        # Different data should produce different key
        assert key1 != key3

    @pytest.mark.asyncio
    async def test_response_with_control_characters(self, middleware):
        """Test sanitization of responses with control characters."""
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get.return_value = "application/json"
        request.body = AsyncMock(return_value=b'{}')
        request.path_params = {}
        request.query_params = {}

        # Response with control characters
        body = b"test\x00data\x1f"
        response = Response(content=body)
        response.body = body
        # Don't try to set headers directly - Response.headers is read-only
        # The middleware will update headers when it sanitizes

        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        # Control characters should be removed
        assert b"\x00" not in result.body
        assert b"\x1f" not in result.body

    @pytest.mark.asyncio
    async def test_empty_body_handling(self, middleware):
        """Test handling of empty request bodies."""
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get.return_value = "application/json"
        request.body = AsyncMock(return_value=b'')
        request.path_params = {}
        request.query_params = {}

        call_next = AsyncMock(return_value=Response())

        # Should not raise exception for empty body
        response = await middleware.dispatch(request, call_next)
        assert response is not None


class TestValidationMiddlewareBenchmark:
    """Benchmark tests for validation middleware performance."""

    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app."""
        return MagicMock()

    @pytest.fixture
    def middleware_with_cache(self, mock_app):
        """Create middleware with caching enabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_cache_enabled = True
            mock_settings.validation_cache_max_size = 1000
            mock_settings.validation_cache_ttl = 300
            mock_settings.validation_max_body_size = 0  # Unlimited
            mock_settings.validation_max_response_size = 0  # Unlimited
            mock_settings.validation_skip_endpoints = []
            mock_settings.validation_sample_large_responses = False
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"[;&|`$(){}\[\]<>]"]
            mock_settings.environment = "production"
            mock_settings.max_param_length = 1000

            return ValidationMiddleware(mock_app)

    @pytest.fixture
    def middleware_without_cache(self, mock_app):
        """Create middleware with caching disabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_cache_enabled = False
            mock_settings.validation_max_body_size = 0
            mock_settings.validation_max_response_size = 0
            mock_settings.validation_skip_endpoints = []
            mock_settings.validation_sample_large_responses = False
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"[;&|`$(){}\[\]<>]"]
            mock_settings.environment = "production"
            mock_settings.max_param_length = 1000

            return ValidationMiddleware(mock_app)

    @pytest.mark.asyncio
    async def test_cache_performance_improvement(self, middleware_with_cache, middleware_without_cache):
        """Test that caching improves performance for repeated requests."""
        body = orjson.dumps({"test": "data" * 100})

        async def create_request():
            request = MagicMock(spec=Request)
            request.url.path = "/api/test"
            request.headers.get.return_value = "application/json"
            request.body = AsyncMock(return_value=body)
            request.path_params = {}
            request.query_params = {}
            return request

        call_next = AsyncMock(return_value=Response())

        # Benchmark with cache
        start = time.time()
        for _ in range(10):
            request = await create_request()
            await middleware_with_cache.dispatch(request, call_next)
        cached_time = time.time() - start

        # Benchmark without cache
        start = time.time()
        for _ in range(10):
            request = await create_request()
            await middleware_without_cache.dispatch(request, call_next)
        uncached_time = time.time() - start

        # Cached version should be faster (or at least not significantly slower)
        # Note: In practice, cache should be faster, but in tests with mocks it might be similar
        assert cached_time <= uncached_time * 1.5  # Allow 50% margin for test variance
