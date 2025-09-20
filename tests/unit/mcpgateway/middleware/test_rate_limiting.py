# -*- coding: utf-8 -*-
"""Unit test for RateLimiterMiddleware.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhavan Kidambi

Unit testing for the rate_limiter module
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request, Response
from fastapi.responses import JSONResponse

# Import the module to test
from mcpgateway.middleware.rate_limiter_middleware import RateLimiterMiddleware

@pytest.fixture
def mock_settings():
    with patch('mcpgateway.main.settings.rate_limit_storage_type',"memory"), \
         patch('mcpgateway.main.settings.experimental_protection_suite', True), \
         patch('mcpgateway.main.settings.rate_limit_admin_bypass_header', 'X-Admin-Bypass'), \
         patch('mcpgateway.main.settings.rate_limit_admin_bypass_secret','admin-secret'):
         yield


@pytest.fixture
def mock_redis_settings():
    with patch('mcpgateway.main.settings.experimental_protection_suite', True), \
         patch('mcpgateway.main.settings.redis_url', "redis://localhost:6379/0"), \
         patch('mcpgateway.main.settings.rate_limiting_stratergy', 'fixed-window'), \
         patch('mcpgateway.main.settings.rate_limit_storage_type',"redis"):
         yield

@pytest.fixture
def mock_disabled_settings():
    with patch('mcpgateway.main.settings.experimental_protection_suite', False), \
         patch('mcpgateway.main.settings.rate_limiting_enabled', False):
        yield


@pytest.fixture
def mock_limit():
    """Create a mock Limit object"""
    limit = MagicMock()
    limit.amount = 100
    limit.get_expiry.return_value = 60  # 60 seconds
    return limit

@pytest.fixture
def mock_async_memory_storage():
    """Mock the AsyncMemoryStorage class"""
    with patch('mcpgateway.middleware.rate_limiter_middleware.AsyncMemoryStorage') as mock:
        storage_instance = AsyncMock()
        mock.return_value = storage_instance
        yield storage_instance

@pytest.fixture
def mock_async_redis_storage():
    """Mock the AsyncRedisStorage class"""
    with patch('mcpgateway.middleware.rate_limiter_middleware.AsyncRedisStorage') as mock:
        storage_instance = AsyncMock()
        mock.return_value = storage_instance
        yield storage_instance

@pytest.fixture
def mock_async_moving_window_limiter():
    """Mock the AsyncMovingWindowRateLimiter class"""
    with patch('mcpgateway.middleware.rate_limiter_middleware.AsyncMovingWindowRateLimiter') as mock:
        limiter_instance = AsyncMock()
        limiter_instance.hit = AsyncMock(return_value=True)  # Default to allowing requests
        limiter_instance.get_window_stats = AsyncMock(return_value=(1, 99))  # (current, remaining)
        mock.return_value = limiter_instance
        yield limiter_instance

@pytest.fixture
def mock_async_fixed_window_limiter():
    """Mock the AsyncFixedWindowRateLimiter class"""
    with patch('mcpgateway.middleware.rate_limiter_middleware.AsyncFixedWindowRateLimiter') as mock:
        limiter_instance = AsyncMock()
        limiter_instance.hit = AsyncMock(return_value=True)  # Default to allowing requests
        limiter_instance.get_window_stats = AsyncMock(return_value=(1, 99))  # (current, remaining)
        mock.return_value = limiter_instance
        yield limiter_instance

@pytest.fixture
def mock_parse_many(mock_limit):
    """Mock the parse_many function"""
    with patch('mcpgateway.middleware.rate_limiter_middleware.parse') as mock:
        mock.return_value = mock_limit
        yield mock
# Mock requests

@pytest.fixture
def mock_request():
    """Create a mock Request object"""
    request = MagicMock(spec=Request)
    request.url = MagicMock()
    request.url.path = "/tools/endpoint"
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {}
    return request

@pytest.fixture
def mock_admin_request():
    """Create a mock Request object for admin endpoints"""
    request = MagicMock(spec=Request)
    request.url = MagicMock()
    request.url.path = "/admin/endpoint"
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"authorization": "Bearer token123"}
    return request

@pytest.fixture
def mock_auth_request():
    """Create a mock Request object with authorization"""
    request = MagicMock(spec=Request)
    request.url = MagicMock()
    request.url.path = "/tools/endpoint"
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"Authorization": "Bearer token123"}
    return request

@pytest.fixture
def mock_response():
    """Create a mock Response object"""
    response = MagicMock(spec=Response)
    response.headers = {}
    return response


class TestRateLimiterMiddleware:
    """Tests for the RateLimiterMiddleware class"""

    @pytest.mark.asyncio
    async def test_init_with_memory_storage(self, mock_settings, mock_async_memory_storage, 
                                           mock_async_moving_window_limiter):
        """Test initialization with memory storage"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        assert middleware.storage == mock_async_memory_storage
        assert middleware.limiter == mock_async_moving_window_limiter
        assert len(middleware.limits) == 4  # default, anonymous, admin, tool

    @pytest.mark.asyncio
    async def test_init_with_redis_storage(self, mock_redis_settings, mock_async_redis_storage, 
                                          mock_async_fixed_window_limiter):
        """Test initialization with Redis storage"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        assert middleware.storage == mock_async_redis_storage
        assert middleware.limiter == mock_async_fixed_window_limiter
        assert len(middleware.limits) == 4  # default, anonymous, admin, tool
    
    @pytest.mark.asyncio
    async def test_init_with_disabled_settings(self, mock_disabled_settings):
        """Test initialization with disabled settings"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        assert middleware.limiter is None

    @pytest.mark.asyncio
    async def test_get_limit_for_request_admin(self, mock_settings, mock_admin_request, 
                                              mock_async_memory_storage, 
                                              mock_async_moving_window_limiter):
        """Test _get_limit_for_request for admin paths"""
        app = MagicMock()
        metric_service = MagicMock() 
        middleware = RateLimiterMiddleware(app,metric_service)
        limit_key,limit = middleware._get_limit_for_request(mock_admin_request)
        
        assert limit_key == "admin"
        assert limit == middleware.limits["admin"]

    
    @pytest.mark.asyncio
    async def test_get_limit_for_request_anonymous(self, mock_settings, mock_request, 
                                                 mock_async_memory_storage, 
                                                 mock_async_moving_window_limiter):
        """Test _get_limit_for_request for anonymous requests"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        limit_key,limits = middleware._get_limit_for_request(mock_request)

        assert limit_key == "anonymous"
        assert limits == middleware.limits["anonymous"]
    
    @pytest.mark.asyncio
    async def test_get_limit_for_request_authenticated(self, mock_settings, mock_auth_request, 
                                                     mock_async_memory_storage, 
                                                     mock_async_moving_window_limiter):
        """Test _get_limit_for_request for authenticated requests"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        limit_key,limits  = middleware._get_limit_for_request(mock_auth_request)
        
        assert limit_key == "tools"
        assert limits == middleware.limits["tool"]


    @pytest.mark.asyncio
    async def test_get_client_identifier_no_auth(self, mock_settings, mock_request, 
                                               mock_async_memory_storage, 
                                               mock_async_moving_window_limiter):
        """Test _get_client_identifier without authorization"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        identifier = middleware._get_client_identifier(mock_request)
        
        assert identifier == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_get_client_identifier_with_auth(self, mock_settings, mock_auth_request, 
                                                 mock_async_memory_storage, 
                                                 mock_async_moving_window_limiter):
        """Test _get_client_identifier with authorization"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        identifier = middleware._get_client_identifier(mock_auth_request)
        assert identifier.startswith("127.0.0.1:")
        assert len(identifier) > len("127.0.0.1:")

    @pytest.mark.asyncio
    async def test_get_reset_time_fixed_window(self, mock_redis_settings, mock_limit, 
                                             mock_async_redis_storage, 
                                             mock_async_fixed_window_limiter):
        """Test _get_reset_time with fixed window strategy"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        reset_time = await middleware._get_reset_time("test_identifier", mock_limit)
        
        # Reset time should be in the future
        assert reset_time > int(time.time())

    @pytest.mark.asyncio
    async def test_get_reset_time_moving_window(self, mock_settings, mock_limit, 
                                              mock_async_memory_storage, 
                                              mock_async_moving_window_limiter):
        """Test _get_reset_time with moving window strategy"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Mock the get_window_stats to return some hits
        middleware.limiter.get_window_stats.return_value = (5, 95)  # (current, remaining)
        
        reset_time = await middleware._get_reset_time("test_identifier", mock_limit)
        
        # Reset time should be in the future
        assert reset_time > int(time.time())

    @pytest.mark.asyncio
    async def test_dispatch_rate_limiting_disabled(self, mock_disabled_settings):
        """Test dispatch when rate limiting is disabled"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        request = MagicMock()
        call_next = AsyncMock(return_value=MagicMock())
        
        response = await middleware.dispatch(request, call_next)
        
        # Should just pass through to call_next
        call_next.assert_called_once_with(request)
        assert response == call_next.return_value

    @pytest.mark.asyncio
    async def test_dispatch_allowed_request(self, mock_settings, mock_request, mock_limit,
                                          mock_async_memory_storage, 
                                          mock_async_moving_window_limiter):
        """Test dispatch with an allowed request"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Mock the limiter to allow the request
        middleware.limiter.hit.return_value = True
        
        call_next = AsyncMock(return_value=MagicMock())
        call_next.return_value.headers = {}
        
        response = await middleware.dispatch(mock_request, call_next)
        
        # Should pass through to call_next
        call_next.assert_called_once_with(mock_request)
        assert response == call_next.return_value
        
        # Should have rate limit headers
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    @pytest.mark.asyncio
    async def test_dispatch_rate_limited_request(self, mock_settings, mock_request, mock_limit,
                                               mock_async_memory_storage, 
                                               mock_async_moving_window_limiter):
        """Test dispatch with a rate-limited request"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Mock the limiter to deny the request
        middleware.limiter.hit.return_value = False
        
        call_next = AsyncMock()
        
        response = await middleware.dispatch(mock_request, call_next)
        
        # Should not pass through to call_next
        call_next.assert_not_called()
        
        # Should return a 429 response
        assert isinstance(response, JSONResponse)
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.body.decode()
        
        # Should have rate limit headers
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
    
    @pytest.mark.asyncio
    async def test_dispatch_with_error_in_get_window_stats(self, mock_settings, mock_request, mock_limit,
                                                        mock_async_memory_storage, 
                                                        mock_async_moving_window_limiter):
        """Test dispatch when get_window_stats raises an exception"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Mock the limiter to allow the request but raise an exception in get_window_stats
        middleware.limiter.hit.return_value = True
        middleware.limiter.get_window_stats.side_effect = Exception("Test exception")
        
        call_next = AsyncMock(return_value=MagicMock())
        call_next.return_value.headers = {}
        
        # Should not raise an exception
        response = await middleware.dispatch(mock_request, call_next)
        
        # Should pass through to call_next
        call_next.assert_called_once_with(mock_request)
        assert response == call_next.return_value
    
    @pytest.mark.asyncio
    async def test_get_reset_time_with_none_limiter(self, mock_disabled_settings):
        """Test _get_reset_time when limiter is None"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Should not raise an exception
        reset_time = await middleware._get_reset_time("test_identifier", MagicMock())
        
        # Should return current time
        assert reset_time <= int(time.time()) + 1

    @pytest.mark.asyncio
    async def test_no_warning_when_below_threshold(self, mock_settings, mock_request, mock_limit,
                                                 mock_async_memory_storage,
                                                 mock_async_moving_window_limiter, mock_parse_many):
        """Test that no warning headers are added when well below the rate limit"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Configure the limiter to return usage stats that don't trigger a warning
        # For a limit of 100, with 75% threshold, we need to show 50 remaining (50 used)
        mock_limit.amount = 100
        middleware.limiter.get_window_stats.return_value = (50, 50)  # (current, remaining)
        middleware.limiter.hit.return_value = True  # Allow the request
        
        call_next = AsyncMock(return_value=MagicMock())
        call_next.return_value.headers = {}
        
        response = await middleware.dispatch(mock_request, call_next)
        
        # Should pass through to call_next
        call_next.assert_called_once_with(mock_request)
        assert response == call_next.return_value
        
        # Should have rate limit headers
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
        
        # Should NOT have warning header
        assert "X-RateLimit-Warning" not in response.headers
        
    @pytest.mark.asyncio
    async def test_warning_threshold(self, mock_settings, mock_request, mock_limit,
                                          mock_async_memory_storage,
                                          mock_async_moving_window_limiter, mock_parse_many):
        """Test with a custom warning threshold"""
        app = MagicMock()
        
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
            
        # Configure the limiter to return usage stats that trigger a warning at 50%
        # For a limit of 100, with 75% threshold, we need to show 24 remaining (76 used)
        mock_limit.amount = 100
        middleware.limiter.get_window_stats.return_value = (76, 24)  # (current, remaining)
        middleware.limiter.hit.return_value = True  # Allow the request
            
        call_next = AsyncMock(return_value=MagicMock())
        call_next.return_value.headers = {}
            
        response = await middleware.dispatch(mock_request, call_next)
            
        # Should have warning header
        assert "X-RateLimit-Warning" in response.headers
        assert "75%" in response.headers["X-RateLimit-Warning"]
        assert "24 requests remaining" in response.headers["X-RateLimit-Warning"]

    @pytest.mark.asyncio
    async def test_ip_whitelist(self, mock_settings, mock_request, mock_limit,
                              mock_async_memory_storage,
                              mock_async_moving_window_limiter):
        """Test that whitelisted IPs bypass rate limiting"""
        app = MagicMock()
        
        # Set up a whitelist with the test IP
        with patch('mcpgateway.main.settings.rate_limit_whitelist_ips', "127.0.0.1"):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with the whitelisted IP
            mock_request.client.host = "127.0.0.1"
            
            call_next = AsyncMock(return_value=MagicMock())
            
            response = await middleware.dispatch(mock_request, call_next)
            
            # Should pass through to call_next without checking rate limits
            call_next.assert_called_once_with(mock_request)
            assert response == call_next.return_value
            
            # The limiter.hit method should not be called
            middleware.limiter.hit.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_whitelisted_ip(self, mock_settings, mock_request, mock_limit,
                                    mock_async_memory_storage,
                                    mock_async_moving_window_limiter):
        """Test that non-whitelisted IPs are subject to rate limiting"""
        app = MagicMock()
        
        # Set up a whitelist with a different IP
        with patch('mcpgateway.main.settings.rate_limit_whitelist_ips', "192.168.1.1"):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with a non-whitelisted IP
            mock_request.client.host = "127.0.0.1"
            
            # Configure the limiter to allow the request
            middleware.limiter.hit.return_value = True
            
            call_next = AsyncMock(return_value=MagicMock())
            call_next.return_value.headers = {}
            
            response = await middleware.dispatch(mock_request, call_next)
            
            # Should pass through to call_next after checking rate limits
            call_next.assert_called_once_with(mock_request)
            assert response == call_next.return_value
            
            # The limiter.hit method should be called
            assert middleware.limiter.hit.called

    @pytest.mark.asyncio
    async def test_empty_whitelist(self, mock_settings, mock_request, mock_limit,
                                 mock_async_memory_storage,
                                 mock_async_moving_window_limiter):
        """Test that an empty whitelist subjects all IPs to rate limiting"""
        app = MagicMock()
        
        # Set up an empty whitelist
        with patch('mcpgateway.main.settings.rate_limit_whitelist_ips', ""):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with any IP
            mock_request.client.host = "127.0.0.1"
            
            # Configure the limiter to allow the request
            middleware.limiter.hit.return_value = True
            
            call_next = AsyncMock(return_value=MagicMock())
            call_next.return_value.headers = {}
            
            response = await middleware.dispatch(mock_request, call_next)
            
            # Should pass through to call_next after checking rate limits
            call_next.assert_called_once_with(mock_request)
            assert response == call_next.return_value
            
            # The limiter.hit method should be called
            assert middleware.limiter.hit.called

    @pytest.mark.asyncio
    async def test_none_client_ip(self, mock_settings, mock_limit,
                                mock_async_memory_storage,
                                mock_async_moving_window_limiter):
        """Test handling of requests with no client IP"""
        app = MagicMock()
        
        # Set up a whitelist
        with patch('mcpgateway.main.settings.rate_limit_whitelist_ips', "127.0.0.1"):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Create a request with no client
            request = MagicMock(spec=Request)
            request.url = MagicMock()
            request.url.path = "/api/endpoint"
            request.client = None
            request.headers = {}
            
            # Configure the limiter to allow the request
            middleware.limiter.hit.return_value = True
            
            call_next = AsyncMock(return_value=MagicMock())
            call_next.return_value.headers = {}
            
            response = await middleware.dispatch(request, call_next)
            
            # Should pass through to call_next after checking rate limits
            call_next.assert_called_once_with(request)
            assert response == call_next.return_value
            
            # The limiter.hit method should be called (not whitelisted)
            assert middleware.limiter.hit.called

    @pytest.mark.asyncio
    async def test_user_agent_whitelist(self, mock_settings, mock_request, mock_limit,
                                      mock_async_memory_storage,
                                      mock_async_moving_window_limiter):
        """Test that whitelisted user agents bypass rate limiting"""
        app = MagicMock()
        
        # Set up a whitelist with the test user agent
        with patch('mcpgateway.main.settings.rate_limit_whitelist_user_agents', "TestAgent"):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with the whitelisted user agent (with different case)
            mock_request.headers = {"User-Agent": "Mozilla/5.0 TestAgent Chrome/91.0"}
            
            call_next = AsyncMock(return_value=MagicMock())
            
            response = await middleware.dispatch(mock_request, call_next)
            
            # Should pass through to call_next without checking rate limits
            call_next.assert_called_once_with(mock_request)
            assert response == call_next.return_value
            
            # The limiter.hit method should not be called
            middleware.limiter.hit.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_whitelisted_user_agent(self, mock_settings, mock_request, mock_limit,
                                           mock_async_memory_storage,
                                           mock_async_moving_window_limiter):
        """Test that non-whitelisted user agents are subject to rate limiting"""
        app = MagicMock()
        
        # Set up a whitelist with a different user agent
        with patch('mcpgateway.main.settings.rate_limit_whitelist_user_agents', "OtherAgent"):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with a non-whitelisted user agent
            mock_request.headers = {"user-agent": "Mozilla/5.0 Chrome/91.0"}
            
            # Configure the limiter to allow the request
            middleware.limiter.hit.return_value = True
            
            call_next = AsyncMock(return_value=MagicMock())
            call_next.return_value.headers = {}
            
            response = await middleware.dispatch(mock_request, call_next)
            
            # Should pass through to call_next after checking rate limits
            call_next.assert_called_once_with(mock_request)
            assert response == call_next.return_value
            
            # The limiter.hit method should be called
            assert middleware.limiter.hit.called

    @pytest.mark.asyncio
    async def test_api_key_whitelist(self, mock_settings, mock_request, mock_limit,
                                   mock_async_memory_storage,
                                   mock_async_moving_window_limiter):
        """Test that whitelisted API keys bypass rate limiting"""
        app = MagicMock()
        
        # Set up a whitelist with the test API key
        with patch('mcpgateway.main.settings.rate_limit_whitelist_api_keys', "test-api-key"):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with the whitelisted API key (with different case)
            mock_request.headers = {"Authorization": "Bearer test-api-key"}
            
            call_next = AsyncMock(return_value=MagicMock())
            
            response = await middleware.dispatch(mock_request, call_next)
            
            # Should pass through to call_next without checking rate limits
            call_next.assert_called_once_with(mock_request)
            assert response == call_next.return_value
            
            # The limiter.hit method should not be called
            middleware.limiter.hit.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_whitelisted_api_key(self, mock_settings, mock_request, mock_limit,
                                        mock_async_memory_storage,
                                        mock_async_moving_window_limiter):
        """Test that non-whitelisted API keys are subject to rate limiting"""
        app = MagicMock()
        
        # Set up a whitelist with a different API key
        with patch('mcpgateway.main.settings.rate_limit_whitelist_api_keys', "other-api-key"):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with a non-whitelisted API key
            mock_request.headers = {"authorization": "Bearer test-api-key"}
            
            # Configure the limiter to allow the request
            middleware.limiter.hit.return_value = True
            
            call_next = AsyncMock(return_value=MagicMock())
            call_next.return_value.headers = {}
            
            response = await middleware.dispatch(mock_request, call_next)
            
            # Should pass through to call_next after checking rate limits
            call_next.assert_called_once_with(mock_request)
            assert response == call_next.return_value
            
            # The limiter.hit method should be called
            assert middleware.limiter.hit.called

    @pytest.mark.asyncio
    async def test_multiple_whitelist_entries(self, mock_settings, mock_request, mock_limit,
                                           mock_async_memory_storage,
                                           mock_async_moving_window_limiter):
        """Test that comma-separated whitelist entries work correctly"""
        app = MagicMock()
        
        # Set up whitelists with multiple entries
        with patch('mcpgateway.main.settings.rate_limit_whitelist_ips', "192.168.1.1,127.0.0.1,10.0.0.1"), \
             patch('mcpgateway.main.settings.rate_limit_whitelist_user_agents', "Agent1,TestAgent,Agent3"), \
             patch('mcpgateway.main.settings.rate_limit_whitelist_api_keys', "key1,test-key,key3"):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Test IP whitelist
            mock_request.client.host = "127.0.0.1"
            mock_request.headers = {}
            
            call_next = AsyncMock(return_value=MagicMock())
            response = await middleware.dispatch(mock_request, call_next)
            call_next.assert_called_once_with(mock_request)
            middleware.limiter.hit.assert_not_called()
            
            # Reset mocks
            call_next.reset_mock()
            middleware.limiter.hit.reset_mock()
            
            # Test user agent whitelist
            mock_request.client.host = "1.2.3.4"  # Non-whitelisted IP
            mock_request.headers = {"user-agent": "Mozilla TestAgent Chrome"}
            
            response = await middleware.dispatch(mock_request, call_next)
            call_next.assert_called_once_with(mock_request)
            middleware.limiter.hit.assert_not_called()
            
            # Reset mocks
            call_next.reset_mock()
            middleware.limiter.hit.reset_mock()
            
            # Test API key whitelist
            mock_request.client.host = "1.2.3.4"  # Non-whitelisted IP
            mock_request.headers = {"user-agent": "Mozilla Chrome", "authorization": "Bearer test-key"}
            
            response = await middleware.dispatch(mock_request, call_next)
            call_next.assert_called_once_with(mock_request)
            middleware.limiter.hit.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_bypass_header(self, mock_settings, mock_limit,
                                     mock_async_memory_storage,
                                     mock_async_moving_window_limiter):
        """Test that admin endpoints with the bypass header and correct secret bypass rate limiting"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Create a request for an admin endpoint with the bypass header
        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/admin/endpoint"
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"X-Admin-Bypass": "admin-secret"}
        
        call_next = AsyncMock(return_value=MagicMock())
        
        response = await middleware.dispatch(request, call_next)
        
        # Should pass through to call_next without checking rate limits
        call_next.assert_called_once_with(request)
        assert response == call_next.return_value
        
        # The limiter.hit method should not be called
        middleware.limiter.hit.assert_not_called()
        
    @pytest.mark.asyncio
    async def test_admin_bypass_header_case_insensitive(self, mock_settings, mock_limit,
                                                     mock_async_memory_storage,
                                                     mock_async_moving_window_limiter):
        """Test that admin endpoints with the bypass header (different case) bypass rate limiting"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Create a request for an admin endpoint with the bypass header (different case)
        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/admin/endpoint"
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"x-admin-bypass": "admin-secret"}  # lowercase header
        
        call_next = AsyncMock(return_value=MagicMock())
        
        response = await middleware.dispatch(request, call_next)
        
        # Should pass through to call_next without checking rate limits
        call_next.assert_called_once_with(request)
        assert response == call_next.return_value
        
        # The limiter.hit method should not be called
        middleware.limiter.hit.assert_not_called()
        
    @pytest.mark.asyncio
    async def test_admin_bypass_wrong_secret(self, mock_settings, mock_limit,
                                          mock_async_memory_storage,
                                          mock_async_moving_window_limiter):
        """Test that admin endpoints with the bypass header but wrong secret are rate limited"""
        app = MagicMock()
        with patch('mcpgateway.main.settings.rate_limit_admin_bypass_header', 'X-Admin-Bypass'), \
             patch('mcpgateway.main.settings.rate_limit_admin_bypass_secret','admin-secret'):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
        
        # Create a request for an admin endpoint with the bypass header but wrong secret
        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/admin/endpoint"
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"X-Admin-Bypass": "wrong-secret"}
        
        # Configure the limiter to allow the request
        middleware.limiter.hit.return_value = True
        
        call_next = AsyncMock(return_value=MagicMock())
        call_next.return_value.headers = {}
        
        response = await middleware.dispatch(request, call_next)
        
        # Should pass through to call_next after checking rate limits
        call_next.assert_called_once_with(request)
        assert response == call_next.return_value
        
        # The limiter.hit method should be called
        assert middleware.limiter.hit.called
        
    @pytest.mark.asyncio
    async def test_non_admin_bypass_header(self, mock_settings, mock_limit,
                                        mock_async_memory_storage,
                                        mock_async_moving_window_limiter):
        """Test that non-admin endpoints with the bypass header are still rate limited"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Create a request for a non-admin endpoint with the bypass header
        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/api/endpoint"  # Not an admin endpoint
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"X-Admin-Bypass": "admin-secret"}
        
        # Configure the limiter to allow the request
        middleware.limiter.hit.return_value = True
        
        call_next = AsyncMock(return_value=MagicMock())
        call_next.return_value.headers = {}
        
        response = await middleware.dispatch(request, call_next)
        
        # Should pass through to call_next after checking rate limits
        call_next.assert_called_once_with(request)
        assert response == call_next.return_value
        
        # The limiter.hit method should be called
        assert middleware.limiter.hit.called
        
    @pytest.mark.asyncio
    async def test_empty_bypass_secret(self, mock_settings, mock_limit,
                                    mock_async_memory_storage,
                                    mock_async_moving_window_limiter):
        """Test that admin endpoints are rate limited when bypass secret is empty"""
        app = MagicMock()
        
        # Set up with empty bypass secret
        with patch('mcpgateway.main.settings.rate_limit_admin_bypass_header', 'X-Admin-Bypass'), \
             patch('mcpgateway.main.settings.rate_limit_admin_bypass_secret',''):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Create a request for an admin endpoint with the bypass header
            request = MagicMock(spec=Request)
            request.url = MagicMock()
            request.url.path = "/admin/endpoint"
            request.client = MagicMock()
            request.client.host = "127.0.0.1"
            request.headers = {"X-Admin-Bypass": "any-value"}
            
            # Configure the limiter to allow the request
            middleware.limiter.hit.return_value = True
            
            call_next = AsyncMock(return_value=MagicMock())
            call_next.return_value.headers = {}
            
            response = await middleware.dispatch(request, call_next)
            
            # Should pass through to call_next after checking rate limits
            call_next.assert_called_once_with(request)
            assert response == call_next.return_value
            
            # The limiter.hit method should be called
            assert middleware.limiter.hit.called

    @pytest.mark.asyncio
    async def test_get_client_identifier_no_auth(self, mock_settings, mock_request, 
                                               mock_async_memory_storage, 
                                               mock_async_moving_window_limiter, mock_parse_many):
        """Test _get_client_identifier without authorization"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        identifier = middleware._get_client_identifier(mock_request)
        
        assert identifier == "127.0.0.1"

        
    @pytest.mark.asyncio
    async def test_get_client_identifier_with_auth_case_insensitive(self, mock_settings,
                                                                  mock_async_memory_storage,
                                                                  mock_async_moving_window_limiter, mock_parse_many):
        """Test _get_client_identifier with authorization (case-insensitive)"""
        app = MagicMock()
        metric_service = MagicMock()
        middleware = RateLimiterMiddleware(app,metric_service)
        
        # Create a request with Authorization header in different case
        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/api/endpoint"
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"AUTHORIZATION": "Bearer token123"}  # uppercase header
        
        identifier = middleware._get_client_identifier(request)
        
        assert identifier.startswith("127.0.0.1:")
        assert len(identifier) > len("127.0.0.1:")
        
    @pytest.mark.asyncio
    async def test_get_client_identifier_with_client_id_header(self, mock_settings, mock_request,
                                                            mock_async_memory_storage,
                                                            mock_async_moving_window_limiter, mock_parse_many):
        """Test _get_client_identifier with CLIENT_ID_HEADER"""
        app = MagicMock()
        
        # Set a custom CLIENT_ID_HEADER
        with patch('mcpgateway.main.settings.rate_limit_client_identification_header', 'X-Client-ID'):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with the client ID header
            mock_request.headers = {"X-Client-ID": "test-client-123"}
            
            identifier = middleware._get_client_identifier(mock_request)
            
            # Should use the client ID header value directly
            assert identifier == "test-client-123"
            
    @pytest.mark.asyncio
    async def test_get_client_identifier_with_client_id_header_case_insensitive(self, mock_settings, mock_request,
                                                                             mock_async_memory_storage,
                                                                             mock_async_moving_window_limiter, mock_parse_many):
        """Test _get_client_identifier with CLIENT_ID_HEADER (case-insensitive)"""
        app = MagicMock()
        
        # Set a custom CLIENT_ID_HEADER
        with patch('mcpgateway.main.settings.rate_limit_client_identification_header', 'X-Client-ID'):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with the client ID header (different case)
            mock_request.headers = {"x-client-id": "test-client-123"}
            
            identifier = middleware._get_client_identifier(mock_request)
            
            # Should use the client ID header value directly (case-insensitive)
            assert identifier == "test-client-123"
            
    @pytest.mark.asyncio
    async def test_get_client_identifier_with_jwt_claim(self, mock_settings, mock_auth_request,
                                                     mock_async_memory_storage,
                                                     mock_async_moving_window_limiter, mock_parse_many):
        """Test _get_client_identifier with JWT claim"""
        app = MagicMock()
        
        # Create a valid JWT token with a 'sub' claim
        # This is a test JWT with payload {"sub": "user123", "name": "Test User"}
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyMTIzIiwibmFtZSI6IlRlc3QgVXNlciJ9.vx0h-hdCYHFc-r8guQIbCmfqvN5YwGLPp_8nFwQMNrM"
        
        # Configure middleware to use JWT claim
        with patch('mcpgateway.main.settings.rate_limit_client_identification_header', ''), \
             patch('mcpgateway.main.settings.rate_limit_client_jwt_claims', 'sub'):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
                
            # Configure the request with the JWT token
            mock_auth_request.headers = {"authorization": f"Bearer {jwt_token}"}
            
            identifier = middleware._get_client_identifier(mock_auth_request)
            
            # Should extract the 'sub' claim from the JWT token
            assert identifier == "user123"
            
    @pytest.mark.asyncio
    async def test_get_client_identifier_with_invalid_jwt(self, mock_settings, mock_auth_request,
                                                       mock_async_memory_storage,
                                                       mock_async_moving_window_limiter, mock_parse_many):
        """Test _get_client_identifier with invalid JWT token"""
        app = MagicMock()
        
        # Configure middleware to use JWT claim
        with patch('mcpgateway.main.settings.rate_limit_client_identification_header', ''), \
             patch('mcpgateway.main.settings.rate_limit_client_jwt_claims', 'sub'):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)            
            # Configure the request with an invalid JWT token
            mock_auth_request.headers = {"authorization": "Bearer invalid-token"}
            
            # Should fall back to the original implementation
            identifier = middleware._get_client_identifier(mock_auth_request)
            
            # Should start with the IP address
            assert identifier.startswith("127.0.0.1:")
            
    @pytest.mark.asyncio
    async def test_get_client_identifier_fallback_priority(self, mock_settings, mock_auth_request,
                                                        mock_async_memory_storage,
                                                        mock_async_moving_window_limiter, mock_parse_many):
        """Test _get_client_identifier fallback priority"""
        app = MagicMock()
        
        # Create a valid JWT token with a 'sub' claim
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyMTIzIiwibmFtZSI6IlRlc3QgVXNlciJ9.vx0h-hdCYHFc-r8guQIbCmfqvN5YwGLPp_8nFwQMNrM"
        
        # Configure middleware to use both CLIENT_ID_HEADER and JWT claim
        with patch('mcpgateway.main.settings.rate_limit_client_identification_header', 'X-Client-ID'), \
             patch('mcpgateway.main.settings.rate_limit_client_jwt_claims', 'sub'):
            metric_service = MagicMock()
            middleware = RateLimiterMiddleware(app,metric_service)
            
            # Configure the request with both headers
            mock_auth_request.headers = {
                "X-Client-ID": "header-client-id",
                "authorization": f"Bearer {jwt_token}"
            }
            
            identifier = middleware._get_client_identifier(mock_auth_request)
            
            # Should prioritize CLIENT_ID_HEADER over JWT claim
            assert identifier == "header-client-id"
