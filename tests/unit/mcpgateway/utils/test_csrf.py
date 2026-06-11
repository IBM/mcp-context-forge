import pytest
from fastapi import Request, Response
from unittest.mock import MagicMock, patch
import secrets

from mcpgateway.utils.csrf import (
    generate_csrf_token,
    set_csrf_cookie,
    get_csrf_token_from_cookie,
    get_csrf_token_from_header,
    validate_csrf_token,
    require_csrf,
    clear_csrf_cookie,
    CSRF_TOKEN_LENGTH,
)
from mcpgateway.config import settings
from mcpgateway.utils.auth_errors import raise_auth_error

# Create a mock HTTPException to test raise_auth_error behavior
from fastapi import HTTPException

class MockAuthError(Exception):
    def __init__(self, code, message, status_code):
        self.code = code
        self.message = message
        self.status_code = status_code

@pytest.fixture
def mock_raise_auth_error(monkeypatch):
    def _mock_raise(code, message, status_code):
        raise MockAuthError(code, message, status_code)
    monkeypatch.setattr("mcpgateway.utils.csrf.raise_auth_error", _mock_raise)

def test_generate_csrf_token():
    token = generate_csrf_token()
    assert isinstance(token, str)
    assert len(token) == CSRF_TOKEN_LENGTH

def test_set_csrf_cookie():
    response = MagicMock(spec=Response)
    token = "test_token_of_correct_length_1234567890123"
    
    with patch("mcpgateway.utils.csrf.settings") as mock_settings:
        mock_settings.environment = "production"
        mock_settings.token_expiry = 60
        
        set_csrf_cookie(response, token)
        
        response.set_cookie.assert_called_once_with(
            key="csrf_token",
            value=token,
            httponly=False,
            secure=True,
            samesite="strict",
            path="/",
            max_age=3600
        )

def test_get_csrf_token_from_cookie():
    request = MagicMock(spec=Request)
    request.cookies = {"csrf_token": "test_token"}
    assert get_csrf_token_from_cookie(request) == "test_token"
    
    request.cookies = {}
    assert get_csrf_token_from_cookie(request) is None

def test_get_csrf_token_from_header():
    request = MagicMock(spec=Request)
    request.headers = {"X-CSRF-Token": "test_token"}
    assert get_csrf_token_from_header(request) == "test_token"
    
    request.headers = {}
    assert get_csrf_token_from_header(request) is None

def test_validate_csrf_token_success():
    request = MagicMock(spec=Request)
    token = generate_csrf_token()
    request.cookies = {"csrf_token": token}
    request.headers = {"X-CSRF-Token": token}
    
    # Should not raise exception
    validate_csrf_token(request)

def test_validate_csrf_token_missing_cookie(mock_raise_auth_error):
    request = MagicMock(spec=Request)
    request.cookies = {}
    request.headers = {"X-CSRF-Token": "test_token"}
    
    with pytest.raises(MockAuthError) as exc_info:
        validate_csrf_token(request)
    assert exc_info.value.code == "csrf_missing_cookie"

def test_validate_csrf_token_missing_header(mock_raise_auth_error):
    request = MagicMock(spec=Request)
    token = generate_csrf_token()
    request.cookies = {"csrf_token": token}
    request.headers = {}
    
    with pytest.raises(MockAuthError) as exc_info:
        validate_csrf_token(request)
    assert exc_info.value.code == "csrf_missing_header"

def test_validate_csrf_token_invalid_cookie_format(mock_raise_auth_error):
    request = MagicMock(spec=Request)
    token = generate_csrf_token()
    request.cookies = {"csrf_token": "short_token"}
    request.headers = {"X-CSRF-Token": token}
    
    with pytest.raises(MockAuthError) as exc_info:
        validate_csrf_token(request)
    assert exc_info.value.code == "csrf_invalid_format"

def test_validate_csrf_token_invalid_header_format(mock_raise_auth_error):
    request = MagicMock(spec=Request)
    token = generate_csrf_token()
    request.cookies = {"csrf_token": token}
    request.headers = {"X-CSRF-Token": "short_token"}
    
    with pytest.raises(MockAuthError) as exc_info:
        validate_csrf_token(request)
    assert exc_info.value.code == "csrf_invalid_format"

def test_validate_csrf_token_mismatch(mock_raise_auth_error):
    request = MagicMock(spec=Request)
    token1 = generate_csrf_token()
    token2 = generate_csrf_token()
    
    # Ensure they are different
    while token1 == token2:
        token2 = generate_csrf_token()
        
    request.cookies = {"csrf_token": token1}
    request.headers = {"X-CSRF-Token": token2}
    
    with pytest.raises(MockAuthError) as exc_info:
        validate_csrf_token(request)
    assert exc_info.value.code == "csrf_mismatch"

def test_require_csrf():
    request = MagicMock(spec=Request)
    token = generate_csrf_token()
    request.cookies = {"csrf_token": token}
    request.headers = {"X-CSRF-Token": token}
    
    # Should not raise
    require_csrf(request)

def test_clear_csrf_cookie():
    response = MagicMock(spec=Response)
    
    with patch("mcpgateway.utils.csrf.settings") as mock_settings:
        mock_settings.csrf_cookie_secure = True
        mock_settings.csrf_cookie_samesite = "strict"
        
        clear_csrf_cookie(response)
        
        response.set_cookie.assert_called_once_with(
            key="csrf_token",
            value="",
            httponly=False,
            secure=True,
            samesite="strict",
            max_age=0,
            path="/"
        )

def test_clear_csrf_cookie_with_cfg():
    response = MagicMock(spec=Response)
    mock_cfg = MagicMock()
    mock_cfg.csrf_cookie_secure = False
    mock_cfg.csrf_cookie_samesite = "lax"
    
    clear_csrf_cookie(response, cfg=mock_cfg)
    
    response.set_cookie.assert_called_once_with(
        key="csrf_token",
        value="",
        httponly=False,
        secure=False,
        samesite="lax",
        max_age=0,
        path="/"
    )
