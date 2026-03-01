# -*- coding: utf-8 -*-
"""Test CSRF middleware fixes for review recommendations.

Tests for the 5 issues identified in the review:
1. Form field parsing for classic HTML form submits
2. Double-submit cookie validation
3. csrf_cookie_httponly setting honored
4. Strict Referer/Origin check (fail closed)
5. Token rotation on login
"""

# Standard
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.csrf_middleware import CSRFMiddleware
from mcpgateway.services.csrf_service import generate_csrf_token, set_csrf_cookie


@pytest.fixture
def mock_settings():
    """Mock settings for CSRF tests."""
    with patch("mcpgateway.middleware.csrf_middleware.settings") as mock:
        mock.csrf_enabled = True
        mock.auth_required = True
        mock.csrf_token_name = "X-CSRF-Token"
        mock.csrf_cookie_name = "csrf_token"
        mock.csrf_check_referer = True
        mock.csrf_trusted_origins = []
        mock.app_domain = "http://localhost:4444"
        mock.csrf_exempt_paths = ["/health"]
        mock.csrf_secret_key = "test-secret-key"
        mock.csrf_token_expiry = 3600
        mock.csrf_cookie_httponly = False
        mock.csrf_cookie_secure = True
        mock.csrf_cookie_samesite = "Strict"
        yield mock


@pytest.fixture
def csrf_middleware(mock_settings):
    """Create CSRF middleware instance."""
    app = Mock()
    return CSRFMiddleware(app)


@pytest.mark.asyncio
async def test_form_field_parsing_urlencoded(csrf_middleware, mock_settings):
    """Test Issue #1: Parse CSRF token from application/x-www-form-urlencoded form field."""
    user_id = "test@example.com"
    session_id = "test-session-123"
    csrf_token = generate_csrf_token(user_id, session_id, mock_settings.csrf_secret_key, mock_settings.csrf_token_expiry)

    # Create mock request with form data (no header)
    mock_request = Mock(spec=Request)
    mock_request.method = "POST"
    mock_request.url.path = "/api/test"
    mock_request.headers.get = Mock(side_effect=lambda key, default=None: {
        "content-type": "application/x-www-form-urlencoded",
        "authorization": "Bearer token",
    }.get(key.lower(), default))
    mock_request.cookies.get = Mock(return_value=csrf_token)
    mock_request.body = AsyncMock(return_value=f"csrf_token={csrf_token}&other_field=value".encode())
    mock_request.state.user = Mock(email=user_id)
    mock_request.state.jti = session_id

    # Mock call_next
    call_next = AsyncMock(return_value=Mock(status_code=200))

    # Execute middleware
    response = await csrf_middleware.dispatch(mock_request, call_next)

    # Should succeed (not return 403)
    assert response.status_code == 200
    call_next.assert_called_once()


@pytest.mark.asyncio
async def test_form_field_parsing_multipart(csrf_middleware, mock_settings):
    """Test Issue #1: Parse CSRF token from multipart/form-data form field."""
    user_id = "test@example.com"
    session_id = "test-session-123"
    csrf_token = generate_csrf_token(user_id, session_id, mock_settings.csrf_secret_key, mock_settings.csrf_token_expiry)

    # Create mock request with multipart form data
    mock_request = Mock(spec=Request)
    mock_request.method = "POST"
    mock_request.url.path = "/api/test"
    mock_request.headers.get = Mock(side_effect=lambda key, default=None: {
        "content-type": "multipart/form-data; boundary=----WebKitFormBoundary",
        "authorization": "Bearer token",
    }.get(key.lower(), default))
    mock_request.cookies.get = Mock(return_value=csrf_token)
    
    # Mock form() to return csrf_token
    async def mock_form():
        return {"csrf_token": csrf_token}
    
    mock_request.form = mock_form
    mock_request.state.user = Mock(email=user_id)
    mock_request.state.jti = session_id

    # Mock call_next
    call_next = AsyncMock(return_value=Mock(status_code=200))

    # Execute middleware
    response = await csrf_middleware.dispatch(mock_request, call_next)

    # Should succeed (not return 403)
    assert response.status_code == 200
    call_next.assert_called_once()


@pytest.mark.asyncio
async def test_double_submit_cookie_validation(csrf_middleware, mock_settings):
    """Test Issue #2: Validate both cookie and header/form tokens match."""
    user_id = "test@example.com"
    session_id = "test-session-123"
    csrf_token = generate_csrf_token(user_id, session_id, mock_settings.csrf_secret_key, mock_settings.csrf_token_expiry)
    wrong_token = "wrong-token-value"

    # Create mock request with mismatched tokens
    mock_request = Mock(spec=Request)
    mock_request.method = "POST"
    mock_request.url = Mock(path="/api/test")
    mock_request.headers = {"x-csrf-token": wrong_token, "referer": "http://localhost:4444/page"}
    mock_request.cookies = {"csrf_token": csrf_token}
    mock_request.state = Mock(user=Mock(email=user_id), jti=session_id)

    # Mock call_next
    call_next = AsyncMock(return_value=Mock(status_code=200))

    # Execute middleware with mocked get_csrf_service
    with patch("mcpgateway.middleware.csrf_middleware.get_csrf_service") as mock_csrf_service:
        mock_csrf_service.return_value.validate_csrf_token.return_value = True
        response = await csrf_middleware.dispatch(mock_request, call_next)

    # Should fail with 403 (tokens don't match)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 403
    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_double_submit_cookie_missing(csrf_middleware, mock_settings):
    """Test Issue #2: Reject when cookie is missing."""
    user_id = "test@example.com"
    session_id = "test-session-123"
    csrf_token = generate_csrf_token(user_id, session_id, mock_settings.csrf_secret_key, mock_settings.csrf_token_expiry)

    # Create mock request with header but no cookie
    mock_request = Mock(spec=Request)
    mock_request.method = "POST"
    mock_request.url = Mock(path="/api/test")
    mock_request.headers = {"x-csrf-token": csrf_token, "referer": "http://localhost:4444/page"}
    mock_request.cookies = {}  # No cookie
    mock_request.state = Mock(user=Mock(email=user_id), jti=session_id)

    # Mock call_next
    call_next = AsyncMock(return_value=Mock(status_code=200))

    # Execute middleware
    response = await csrf_middleware.dispatch(mock_request, call_next)

    # Should fail with 403 (cookie missing)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 403
    call_next.assert_not_called()


def test_csrf_cookie_httponly_setting_honored():
    """Test Issue #3: csrf_cookie_httponly setting is honored."""
    # Test with httponly=True
    with patch("mcpgateway.services.csrf_service.app_settings") as mock_settings:
        mock_settings.csrf_cookie_httponly = True
        mock_settings.csrf_cookie_secure = True
        mock_settings.csrf_cookie_samesite = "Strict"
        mock_settings.csrf_token_expiry = 3600
        mock_settings.csrf_cookie_name = "csrf_token"

        mock_response = Mock()
        set_csrf_cookie(mock_response, "test-token", mock_settings)

        # Verify httponly=True was passed
        mock_response.set_cookie.assert_called_once()
        call_kwargs = mock_response.set_cookie.call_args[1]
        assert call_kwargs["httponly"] is True

    # Test with httponly=False
    with patch("mcpgateway.services.csrf_service.app_settings") as mock_settings:
        mock_settings.csrf_cookie_httponly = False
        mock_settings.csrf_cookie_secure = True
        mock_settings.csrf_cookie_samesite = "Strict"
        mock_settings.csrf_token_expiry = 3600
        mock_settings.csrf_cookie_name = "csrf_token"

        mock_response = Mock()
        set_csrf_cookie(mock_response, "test-token", mock_settings)

        # Verify httponly=False was passed
        mock_response.set_cookie.assert_called_once()
        call_kwargs = mock_response.set_cookie.call_args[1]
        assert call_kwargs["httponly"] is False


@pytest.mark.asyncio
async def test_referer_check_fail_closed_missing_header(csrf_middleware, mock_settings):
    """Test Issue #4: Reject when Referer/Origin header is missing (fail closed)."""
    user_id = "test@example.com"
    session_id = "test-session-123"
    csrf_token = generate_csrf_token(user_id, session_id, mock_settings.csrf_secret_key, mock_settings.csrf_token_expiry)

    # Create mock request without Referer/Origin header
    mock_request = Mock(spec=Request)
    mock_request.method = "POST"
    mock_request.url = Mock(path="/api/test")
    mock_request.headers = {"x-csrf-token": csrf_token}  # No referer
    mock_request.cookies = {"csrf_token": csrf_token}
    mock_request.state = Mock(user=Mock(email=user_id), jti=session_id)

    # Mock call_next
    call_next = AsyncMock(return_value=Mock(status_code=200))

    # Execute middleware with mocked get_csrf_service
    with patch("mcpgateway.middleware.csrf_middleware.get_csrf_service") as mock_csrf_service:
        mock_csrf_service.return_value.validate_csrf_token.return_value = True
        response = await csrf_middleware.dispatch(mock_request, call_next)

    # Should fail with 403 (header missing, fail closed)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 403
    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_referer_check_fail_closed_invalid_origin(csrf_middleware, mock_settings):
    """Test Issue #4: Reject when Referer/Origin is not in allowed list."""
    user_id = "test@example.com"
    session_id = "test-session-123"
    csrf_token = generate_csrf_token(user_id, session_id, mock_settings.csrf_secret_key, mock_settings.csrf_token_expiry)

    # Create mock request with invalid origin
    mock_request = Mock(spec=Request)
    mock_request.method = "POST"
    mock_request.url = Mock(path="/api/test")
    mock_request.headers = {"x-csrf-token": csrf_token, "referer": "http://evil.com/attack"}
    mock_request.cookies = {"csrf_token": csrf_token}
    mock_request.state = Mock(user=Mock(email=user_id), jti=session_id)

    # Mock call_next
    call_next = AsyncMock(return_value=Mock(status_code=200))

    # Execute middleware with mocked get_csrf_service
    with patch("mcpgateway.middleware.csrf_middleware.get_csrf_service") as mock_csrf_service:
        mock_csrf_service.return_value.validate_csrf_token.return_value = True
        response = await csrf_middleware.dispatch(mock_request, call_next)

    # Should fail with 403 (origin not allowed)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 403
    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_token_rotation_on_login():
    """Test Issue #5: CSRF token is rotated on login."""
    from mcpgateway.routers.auth import login
    from mcpgateway.routers.auth import LoginRequest

    # Mock dependencies
    mock_db = Mock()
    mock_request = Mock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers.get = Mock(return_value="test-agent")

    login_request = LoginRequest(email="test@example.com", password="password123")

    with patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service_class, \
         patch("mcpgateway.routers.auth.create_access_token") as mock_create_token, \
         patch("mcpgateway.routers.auth.settings") as mock_settings, \
         patch("mcpgateway.routers.auth.jwt") as mock_jwt, \
         patch("mcpgateway.routers.auth.generate_csrf_token") as mock_gen_csrf, \
         patch("mcpgateway.routers.auth.set_csrf_cookie") as mock_set_cookie:

        # Setup mocks
        mock_settings.csrf_rotate_on_login = True
        mock_settings.csrf_secret_key = "test-secret"
        mock_settings.csrf_token_expiry = 3600
        mock_settings.sso_enabled = False

        mock_user = Mock()
        mock_user.email = "test@example.com"
        mock_user.is_admin = False

        mock_auth_service = Mock()
        mock_auth_service.authenticate_user = AsyncMock(return_value=mock_user)
        mock_auth_service_class.return_value = mock_auth_service

        mock_create_token.return_value = ("test-jwt-token", 3600)
        mock_jwt.decode.return_value = {"jti": "test-jti-123"}
        mock_gen_csrf.return_value = "test-csrf-token"

        # Execute login
        response = await login(login_request, mock_request, mock_db)

        # Verify CSRF token was generated and set
        mock_gen_csrf.assert_called_once_with(
            user_id="test@example.com",
            session_id="test-jti-123",
            secret="test-secret",
            expiry=3600
        )
        mock_set_cookie.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
