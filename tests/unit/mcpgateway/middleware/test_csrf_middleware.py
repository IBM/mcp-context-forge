# -*- coding: utf-8 -*-
"""Location: ./tests/test_csrf_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for CSRF middleware.

Tests cover request validation, token checking, exempt paths, and referer validation.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.middleware.csrf_middleware import CSRFMiddleware


@pytest.mark.asyncio
async def test_get_request_passes_without_token():
    """Test that GET requests pass without CSRF token."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/api/data"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_head_request_passes_without_token():
    """Test that HEAD requests pass without CSRF token."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "HEAD"
    request.url.path = "/api/data"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_post_without_token_returns_403():
    """Test that POST without CSRF token returns 403 with CSRF_TOKEN_MISSING."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert response.body == b'{"detail":"CSRF token missing","code":"CSRF_TOKEN_MISSING"}'
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_with_invalid_token_returns_403():
    """Test that POST with invalid CSRF token returns 403 with CSRF_TOKEN_INVALID."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {"X-CSRF-Token": "invalid_token"}
    request.state = MagicMock()
    request.state.user = MagicMock(email="user@example.com")
    request.cookies = {"session_id": "session123"}

    mock_csrf_service = MagicMock()
    mock_csrf_service.validate_csrf_token.return_value = False

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings, \
         patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=mock_csrf_service):
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_check_referer = False

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert response.body == b'{"detail":"CSRF token invalid","code":"CSRF_TOKEN_INVALID"}'
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_with_valid_token_succeeds():
    """Test that POST with valid CSRF token succeeds."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {"X-CSRF-Token": "valid_token"}
    request.state = MagicMock()
    request.state.user = MagicMock(email="user@example.com")
    request.cookies = {"session_id": "session123"}

    mock_csrf_service = MagicMock()
    mock_csrf_service.validate_csrf_token.return_value = True

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings, \
         patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=mock_csrf_service):
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_check_referer = False

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_exempt_path_passes_without_token():
    """Test that requests to exempt paths pass without CSRF token."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/auth/login"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = ["/auth/login", "/auth/register"]

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_bearer_token_request_passes_without_csrf():
    """Test that requests with Authorization: Bearer header pass without CSRF token."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {"authorization": "Bearer abc123token"}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_csrf_disabled_allows_all_requests():
    """Test that CSRF_ENABLED=False allows all requests through."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = False

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_referer_matches_trusted_origin_passes():
    """Test that request with matching referer passes."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {
        "X-CSRF-Token": "valid_token",
        "referer": "https://example.com/page"
    }
    request.state = MagicMock()
    request.state.user = MagicMock(email="user@example.com")
    request.cookies = {"session_id": "session123"}

    mock_csrf_service = MagicMock()
    mock_csrf_service.validate_csrf_token.return_value = True

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings, \
         patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=mock_csrf_service):
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_check_referer = True
        mock_settings.app_domain = "https://example.com"
        mock_settings.csrf_trusted_origins = set()

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_referer_wrong_domain_returns_403():
    """Test that request with wrong referer domain returns 403."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {
        "X-CSRF-Token": "valid_token",
        "referer": "https://evil.com/page"
    }
    request.state = MagicMock()
    request.state.user = MagicMock(email="user@example.com")
    request.cookies = {"session_id": "session123"}

    mock_csrf_service = MagicMock()
    mock_csrf_service.validate_csrf_token.return_value = True

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings, \
         patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=mock_csrf_service):
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_check_referer = True
        mock_settings.app_domain = "https://example.com"
        mock_settings.csrf_trusted_origins = set()

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert response.body == b'{"detail":"CSRF token invalid","code":"CSRF_TOKEN_INVALID"}'
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_referer_absent_passes():
    """Test that request without referer header passes (do NOT block on absence)."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {"X-CSRF-Token": "valid_token"}
    request.state = MagicMock()
    request.state.user = MagicMock(email="user@example.com")
    request.cookies = {"session_id": "session123"}

    mock_csrf_service = MagicMock()
    mock_csrf_service.validate_csrf_token.return_value = True

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings, \
         patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=mock_csrf_service):
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_check_referer = True
        mock_settings.app_domain = "https://example.com"
        mock_settings.csrf_trusted_origins = set()

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_no_user_context_returns_403():
    """Test that request without user context returns 403."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {"X-CSRF-Token": "some_token"}
    request.state = MagicMock()
    request.state.user = None  # No user context
    request.cookies = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert response.body == b'{"detail":"CSRF token invalid","code":"CSRF_TOKEN_INVALID"}'
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_put_request_requires_csrf_token():
    """Test that PUT requests require CSRF token."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "PUT"
    request.url.path = "/api/data/123"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert response.body == b'{"detail":"CSRF token missing","code":"CSRF_TOKEN_MISSING"}'


@pytest.mark.asyncio
async def test_delete_request_requires_csrf_token():
    """Test that DELETE requests require CSRF token."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "DELETE"
    request.url.path = "/api/data/123"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert response.body == b'{"detail":"CSRF token missing","code":"CSRF_TOKEN_MISSING"}'


@pytest.mark.asyncio
async def test_patch_request_requires_csrf_token():
    """Test that PATCH requests require CSRF token."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "PATCH"
    request.url.path = "/api/data/123"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert response.body == b'{"detail":"CSRF token missing","code":"CSRF_TOKEN_MISSING"}'


@pytest.mark.asyncio
async def test_options_request_passes_without_token():
    """Test that OPTIONS requests pass without CSRF token."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "OPTIONS"
    request.url.path = "/api/data"
    request.headers = {}

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings:
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_session_id_from_header():
    """Test that session_id can be extracted from X-Session-ID header."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {
        "X-CSRF-Token": "valid_token",
        "X-Session-ID": "header_session_123"
    }
    request.state = MagicMock()
    request.state.user = MagicMock(email="user@example.com")
    request.cookies = {}

    mock_csrf_service = MagicMock()
    mock_csrf_service.validate_csrf_token.return_value = True

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings, \
         patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=mock_csrf_service):
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_check_referer = False

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    # Verify session_id from header was used
    mock_csrf_service.validate_csrf_token.assert_called_once_with(
        "valid_token", "user@example.com", "header_session_123"
    )


@pytest.mark.asyncio
async def test_origin_header_used_when_referer_absent():
    """Test that Origin header is used when Referer is absent."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {
        "X-CSRF-Token": "valid_token",
        "origin": "https://example.com"
    }
    request.state = MagicMock()
    request.state.user = MagicMock(email="user@example.com")
    request.cookies = {"session_id": "session123"}

    mock_csrf_service = MagicMock()
    mock_csrf_service.validate_csrf_token.return_value = True

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings, \
         patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=mock_csrf_service):
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_check_referer = True
        mock_settings.app_domain = "https://example.com"
        mock_settings.csrf_trusted_origins = set()

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_trusted_origins_accepted():
    """Test that requests from trusted origins are accepted."""
    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/data"
    request.headers = {
        "X-CSRF-Token": "valid_token",
        "referer": "https://trusted.com/page"
    }
    request.state = MagicMock()
    request.state.user = MagicMock(email="user@example.com")
    request.cookies = {"session_id": "session123"}

    mock_csrf_service = MagicMock()
    mock_csrf_service.validate_csrf_token.return_value = True

    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings, \
         patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=mock_csrf_service):
        mock_settings.csrf_enabled = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_check_referer = True
        mock_settings.app_domain = "https://example.com"
        mock_settings.csrf_trusted_origins = {"https://trusted.com"}

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)
