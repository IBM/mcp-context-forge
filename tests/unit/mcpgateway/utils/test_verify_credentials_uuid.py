# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_verify_credentials_uuid.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for UUID resolution in verify_credentials.
"""

import pytest
from unittest.mock import patch, MagicMock
from tests.helpers.auth import make_test_jwt
from mcpgateway.utils.verify_credentials import verify_credentials
from mcpgateway.db import EmailUser


class TestVerifyCredentialsUuidCoverage:
    """Tests targeting missing coverage lines in verify_credentials.py."""

    @pytest.mark.asyncio
    async def test_uuid_resolution_in_user_status_check_lines_520_525(self):
        """Cover lines 520-525: UUID resolution in user status check."""
        uuid_sub = "550e8400-e29b-41d4-a716-446655440000"

        token = make_test_jwt(email=uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user@example.com"
        mock_user.is_active = True
        mock_user.is_admin = False

        # Patch at the source module where functions are defined
        with patch("mcpgateway.auth._get_user_by_email_sync", side_effect=[None, mock_user]):
            with patch("mcpgateway.auth._get_email_by_id_sync", return_value="user@example.com"):
                with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                    result = await verify_credentials(token)

        assert result is not None
        assert result.get("sub") == uuid_sub

    @pytest.mark.asyncio
    async def test_uuid_resolution_returns_none_lines_520_525(self):
        """Cover lines 520-525: UUID resolution returns None."""
        uuid_sub = "550e8400-e29b-41d4-a716-446655440000"

        token = make_test_jwt(email=uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        # Both lookups return None
        with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
            with patch("mcpgateway.auth._get_email_by_id_sync", return_value=None):
                with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                    result = await verify_credentials(token)

        # Should return payload even without user in DB (when require_user_in_db=False)
        assert result is not None

    @pytest.mark.asyncio
    async def test_uuid_resolution_valueerror_lines_526_527(self):
        """Cover lines 526-527: ValueError exception when username is not a valid UUID."""
        # Use a non-UUID username (regular email) with token_use=session
        non_uuid_sub = "user@example.com"

        token = make_test_jwt(email=non_uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        # First lookup returns None, triggering UUID resolution attempt
        # uuid.UUID(non_uuid_sub) will raise ValueError, hitting lines 526-527
        with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
            with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                result = await verify_credentials(token)

        # Should return payload even without user in DB (when require_user_in_db=False)
        assert result is not None
        assert result.get("sub") == non_uuid_sub

    @pytest.mark.asyncio
    async def test_uuid_resolution_in_require_admin_auth_lines_1409_1414(self):
        """Cover lines 1409-1414: UUID resolution in require_admin_auth."""
        from fastapi import Request, HTTPException
        from mcpgateway.utils.verify_credentials import require_admin_auth
        from mcpgateway.db import EmailUser
        from unittest.mock import AsyncMock

        uuid_sub = "550e8400-e29b-41d4-a716-446655440000"
        token = make_test_jwt(email=uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "admin@example.com"
        mock_user.is_active = True
        mock_user.is_admin = True
        mock_user.id = uuid_sub

        mock_request = MagicMock(spec=Request)
        mock_request.headers.get.return_value = "application/json"

        mock_db_session = MagicMock()
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_user

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with patch("mcpgateway.utils.verify_credentials.settings.email_auth_enabled", True):
            with patch("mcpgateway.db.get_db", return_value=iter([mock_db_session])):
                with patch("mcpgateway.utils.verify_credentials.verify_jwt_token_cached", return_value={"sub": uuid_sub, "token_use": "session"}):
                    with patch("mcpgateway.utils.verify_credentials._enforce_revocation_and_active_user", return_value=None):
                        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_auth_service):
                            result = await require_admin_auth(request=mock_request, jwt_token=token)

        assert result == "admin@example.com"

    @pytest.mark.asyncio
    async def test_uuid_resolution_no_user_in_require_admin_auth_lines_1409_1414(self):
        """Cover lines 1409-1414: UUID resolution returns None in require_admin_auth."""
        from fastapi import Request, HTTPException
        from mcpgateway.utils.verify_credentials import require_admin_auth
        from unittest.mock import AsyncMock

        uuid_sub = "550e8400-e29b-41d4-a716-446655440000"
        token = make_test_jwt(email=uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        mock_request = MagicMock(spec=Request)
        mock_request.headers.get.return_value = "application/json"

        mock_db_session = MagicMock()
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with patch("mcpgateway.utils.verify_credentials.settings.email_auth_enabled", True):
            with patch("mcpgateway.db.get_db", return_value=iter([mock_db_session])):
                with patch("mcpgateway.utils.verify_credentials.verify_jwt_token_cached", return_value={"sub": uuid_sub, "token_use": "session"}):
                    with patch("mcpgateway.utils.verify_credentials._enforce_revocation_and_active_user", return_value=None):
                        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_auth_service):
                            with pytest.raises(HTTPException) as exc_info:
                                await require_admin_auth(request=mock_request, jwt_token=token)

        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_enforce_revocation_uuid_resolution_success(monkeypatch):
    """Lines 521-525: UUID resolution succeeds and finds user."""
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)

    uuid_sub = "550e8400-e29b-41d4-a716-446655440000"

    # Mock user with is_active=True
    active_user = MagicMock()
    active_user.is_active = True

    # First call returns None (triggers UUID resolution), second call returns user
    call_count = [0]

    def mock_get_user(email):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # First call with UUID
        return active_user  # Second call with resolved email

    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", mock_get_user)
    monkeypatch.setattr("mcpgateway.auth._get_email_by_id_sync", lambda _uuid: "user@example.com")
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": uuid_sub, "jti": "test-jti", "token_use": "session"}

    # Should resolve UUID and return None (success)
    result = await vc._enforce_revocation_and_active_user(payload)
    assert result is None
    assert call_count[0] == 2  # Verify UUID resolution was attempted


@pytest.mark.asyncio
async def test_enforce_revocation_uuid_resolution_no_email_found(monkeypatch):
    """Lines 521-525: UUID resolution returns None for email."""
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)

    uuid_sub = "550e8400-e29b-41d4-a716-446655440000"

    # Mock _get_user_by_email_sync to always return None
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: None)
    # Mock _get_email_by_id_sync to return None (UUID not found)
    monkeypatch.setattr("mcpgateway.auth._get_email_by_id_sync", lambda _uuid: None)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": uuid_sub, "jti": "test-jti", "token_use": "session"}

    # Should attempt UUID resolution but find no email
    result = await vc._enforce_revocation_and_active_user(payload)
    assert result is None


@pytest.mark.asyncio
async def test_enforce_revocation_uuid_resolution_valueerror(monkeypatch):
    """Lines 526-527: ValueError when username is not a valid UUID."""
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)

    # Use non-UUID string
    non_uuid = "not-a-uuid@example.com"

    # Mock _get_user_by_email_sync to return None (triggers UUID resolution attempt)
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: None)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": non_uuid, "jti": "test-jti", "token_use": "session"}

    # Should catch ValueError and continue (line 527)
    result = await vc._enforce_revocation_and_active_user(payload)
    assert result is None


@pytest.mark.asyncio
async def test_enforce_revocation_user_none_require_db_false_returns_none(monkeypatch):
    """Line 531-534: user is None, require_user_in_db=False, should return without raising."""
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)

    # Mock _get_user_by_email_sync to return None
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: None)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": "ghost@example.com", "jti": "test-jti"}

    # Should return None without raising (line 534)
    result = await vc._enforce_revocation_and_active_user(payload)
    assert result is None


@pytest.mark.asyncio
async def test_enforce_revocation_user_none_require_db_true_non_admin_raises(monkeypatch):
    """Line 522-523: user is None, require_user_in_db=True, non-admin user should raise 401."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import HTTPException, status

    monkeypatch.setattr(vc.settings, "require_user_in_db", True, raising=False)
    monkeypatch.setattr(vc.settings, "platform_admin_email", "admin@example.com", raising=False)

    # Mock _get_user_by_email_sync to return None
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: None)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": "regular-user@example.com", "jti": "test-jti"}

    # Should raise 401 (lines 522-523)
    with pytest.raises(HTTPException) as exc:
        await vc._enforce_revocation_and_active_user(payload)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "User not found in database" in exc.value.detail


@pytest.mark.asyncio
async def test_enforce_revocation_user_none_require_db_true_platform_admin_returns(monkeypatch):
    """Line 522-524: user is None, require_user_in_db=True, but platform_admin should return."""
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "require_user_in_db", True, raising=False)
    monkeypatch.setattr(vc.settings, "platform_admin_email", "admin@example.com", raising=False)

    # Mock _get_user_by_email_sync to return None
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: None)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": "admin@example.com", "jti": "test-jti"}

    # Should return None without raising (line 524, condition fails so we skip the raise)
    result = await vc._enforce_revocation_and_active_user(payload)
    assert result is None


@pytest.mark.asyncio
async def test_enforce_revocation_inactive_user_raises(monkeypatch):
    """Line 526-527: user exists but is_active=False should raise 401."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import HTTPException, status

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)

    # Mock user with is_active=False
    inactive_user = MagicMock()
    inactive_user.is_active = False

    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: inactive_user)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": "inactive@example.com", "jti": "test-jti"}

    # Should raise 401 (lines 526-527)
    with pytest.raises(HTTPException) as exc:
        await vc._enforce_revocation_and_active_user(payload)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Account disabled" in exc.value.detail


@pytest.mark.asyncio
async def test_enforce_revocation_active_user_returns_none(monkeypatch):
    """User exists and is_active=True should return None (success path)."""
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)

    # Mock user with is_active=True
    active_user = MagicMock()
    active_user.is_active = True

    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: active_user)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": "active@example.com", "jti": "test-jti"}

    # Should return None without raising
    result = await vc._enforce_revocation_and_active_user(payload)
    assert result is None


@pytest.mark.asyncio
async def test_enforce_revocation_no_username_returns_early(monkeypatch):
    """Line 513-514: payload without username should return early."""
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)

    payload = {"jti": "test-jti"}  # No sub, email, or username

    # Should return None without calling _get_user_by_email_sync
    result = await vc._enforce_revocation_and_active_user(payload)
    assert result is None


@pytest.mark.asyncio
async def test_get_auth_header_value_with_lowercase_header():
    """Lines 119-128: get_auth_header_value with lowercase header."""
    from mcpgateway.utils import verify_credentials as vc

    # Mock headers with lowercase key
    headers = {"authorization": "Bearer token123"}
    result = vc.get_auth_header_value(headers)
    assert result == "Bearer token123"


@pytest.mark.asyncio
async def test_get_auth_header_value_with_mixed_case_header():
    """Lines 119-128: get_auth_header_value with mixed case header."""
    from mcpgateway.utils import verify_credentials as vc

    # Mock headers with mixed case key (fallback path)
    headers = {"Authorization": "Bearer token456"}
    result = vc.get_auth_header_value(headers)
    assert result == "Bearer token456"


@pytest.mark.asyncio
async def test_get_auth_header_value_none_headers():
    """Lines 119-128: get_auth_header_value with None headers."""
    from mcpgateway.utils import verify_credentials as vc

    result = vc.get_auth_header_value(None)
    assert result is None


@pytest.mark.asyncio
async def test_get_auth_bearer_token_from_request_success():
    """Lines 145-154: get_auth_bearer_token_from_request success path."""
    from mcpgateway.utils import verify_credentials as vc

    # Mock request with headers
    request = MagicMock()
    request.headers = {"authorization": "Bearer mytoken"}

    result = vc.get_auth_bearer_token_from_request(request)
    assert result == "mytoken"


@pytest.mark.asyncio
async def test_get_auth_bearer_token_from_request_no_bearer():
    """Lines 145-154: get_auth_bearer_token_from_request with non-Bearer scheme."""
    from mcpgateway.utils import verify_credentials as vc

    request = MagicMock()
    request.headers = {"authorization": "Basic dXNlcjpwYXNz"}

    result = vc.get_auth_bearer_token_from_request(request)
    assert result is None


@pytest.mark.asyncio
async def test_get_auth_bearer_token_from_request_none_request():
    """Lines 145-154: get_auth_bearer_token_from_request with None request."""
    from mcpgateway.utils import verify_credentials as vc

    result = vc.get_auth_bearer_token_from_request(None)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_auth_header_name_default():
    """Lines 96-101: _resolve_auth_header_name returns default."""
    from mcpgateway.utils import verify_credentials as vc

    # Mock settings with auth_header_name
    mock_settings = MagicMock()
    mock_settings.auth_header_name = "X-Custom-Auth"

    result = vc._resolve_auth_header_name(mock_settings)
    assert result == "X-Custom-Auth"


@pytest.mark.asyncio
async def test_resolve_auth_header_name_non_string():
    """Lines 96-101: _resolve_auth_header_name with non-string value."""
    from mcpgateway.utils import verify_credentials as vc

    mock_settings = MagicMock()
    mock_settings.auth_header_name = 123  # Non-string

    result = vc._resolve_auth_header_name(mock_settings)
    assert result == "Authorization"  # Falls back to default


@pytest.mark.asyncio
async def test_resolve_auth_header_name_empty_string():
    """Lines 96-101: _resolve_auth_header_name with empty string."""
    from mcpgateway.utils import verify_credentials as vc

    mock_settings = MagicMock()
    mock_settings.auth_header_name = "   "  # Whitespace only

    result = vc._resolve_auth_header_name(mock_settings)
    assert result == "Authorization"  # Falls back to default


@pytest.mark.asyncio
async def test_configurable_http_bearer_call_success():
    """Lines 190-209: ConfigurableHTTPBearer.__call__ success path."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request

    bearer = vc.ConfigurableHTTPBearer()

    # Mock request with valid Bearer token
    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer valid_token"}

    result = await bearer(request)
    assert result is not None
    assert result.scheme == "Bearer"
    assert result.credentials == "valid_token"


@pytest.mark.asyncio
async def test_configurable_http_bearer_call_no_auth_header():
    """Lines 190-209: ConfigurableHTTPBearer.__call__ with missing auth header."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request, HTTPException

    bearer = vc.ConfigurableHTTPBearer(auto_error=True)

    # Mock request without authorization header
    request = MagicMock(spec=Request)
    request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await bearer(request)

    assert exc_info.value.status_code == 403
    assert "Not authenticated" in exc_info.value.detail


@pytest.mark.asyncio
async def test_configurable_http_bearer_call_invalid_scheme():
    """Lines 190-209: ConfigurableHTTPBearer.__call__ with non-Bearer scheme."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request, HTTPException

    bearer = vc.ConfigurableHTTPBearer(auto_error=True)

    # Mock request with Basic auth instead of Bearer
    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Basic dXNlcjpwYXNz"}

    with pytest.raises(HTTPException) as exc_info:
        await bearer(request)

    assert exc_info.value.status_code == 403
    assert "Invalid authentication credentials" in exc_info.value.detail


@pytest.mark.asyncio
async def test_configurable_http_bearer_call_no_auto_error():
    """Lines 190-209: ConfigurableHTTPBearer.__call__ with auto_error=False."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request

    bearer = vc.ConfigurableHTTPBearer(auto_error=False)

    # Mock request without authorization header
    request = MagicMock(spec=Request)
    request.headers = {}

    result = await bearer(request)
    assert result is None


@pytest.mark.asyncio
async def test_authenticate_proxy_user_active_user(monkeypatch):
    """Lines 588, 610-623: _authenticate_proxy_user with active user."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request
    from unittest.mock import AsyncMock, patch

    monkeypatch.setattr(vc.settings, "require_user_in_db", True, raising=False)

    # Mock active user
    active_user = MagicMock()
    active_user.is_active = True
    active_user.is_admin = False
    active_user.email = "proxy@example.com"

    # Mock _resolve_teams_from_db to return team list
    async def mock_resolve_teams(email, user_info):
        return ["team1", "team2"]

    # Patch at the source module where the function is defined
    monkeypatch.setattr("mcpgateway.auth._resolve_teams_from_db", mock_resolve_teams)

    # Mock the DB and auth service
    mock_db = MagicMock()
    mock_auth_service = MagicMock()
    mock_auth_service.get_user_by_email = AsyncMock(return_value=active_user)

    request = MagicMock(spec=Request)
    request.state = MagicMock()

    # Patch where get_db and EmailAuthService are imported inside _authenticate_proxy_user
    with patch("mcpgateway.db.get_db", return_value=iter([mock_db])):
        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_auth_service):
            result = await vc._authenticate_proxy_user(request, "proxy@example.com")

    assert result is not None
    assert result["sub"] == "proxy@example.com"
    assert result["source"] == "proxy"
    assert result["is_admin"] is False
    assert result["teams"] == ["team1", "team2"]
    assert result["token_use"] == "session"


@pytest.mark.asyncio
async def test_authenticate_proxy_user_inactive_user_raises(monkeypatch):
    """Lines 588-591: _authenticate_proxy_user with inactive user raises 401."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request, HTTPException
    from unittest.mock import AsyncMock, patch

    monkeypatch.setattr(vc.settings, "require_user_in_db", True, raising=False)

    # Mock inactive user
    inactive_user = MagicMock()
    inactive_user.is_active = False
    inactive_user.email = "inactive@example.com"

    # Mock the DB and auth service
    mock_db = MagicMock()
    mock_auth_service = MagicMock()
    mock_auth_service.get_user_by_email = AsyncMock(return_value=inactive_user)

    request = MagicMock(spec=Request)
    request.state = MagicMock()

    # Patch where get_db and EmailAuthService are imported inside _authenticate_proxy_user
    with patch("mcpgateway.db.get_db", return_value=iter([mock_db])):
        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_auth_service):
            with pytest.raises(HTTPException) as exc_info:
                await vc._authenticate_proxy_user(request, "inactive@example.com")

    assert exc_info.value.status_code == 401
    assert "Account disabled" in exc_info.value.detail


@pytest.mark.asyncio
async def test_authenticate_proxy_user_platform_admin_bootstrap(monkeypatch):
    """Lines 610-623: _authenticate_proxy_user platform admin bootstrap."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)
    monkeypatch.setattr(vc.settings, "platform_admin_email", "admin@example.com", raising=False)

    # Mock user not found in DB
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: None)

    request = MagicMock(spec=Request)
    result = await vc._authenticate_proxy_user(request, "admin@example.com")

    assert result is not None
    assert result["sub"] == "admin@example.com"
    assert result["is_admin"] is True
    assert result["teams"] is None  # Admin bypass


@pytest.mark.asyncio
async def test_verify_credentials_proxy_auth_path(monkeypatch):
    """Lines 733-755: require_auth with proxy auth enabled."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request
    from unittest.mock import AsyncMock, patch

    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "proxy_user_header", "X-Forwarded-User", raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)

    # Mock is_proxy_auth_trust_active to return True
    monkeypatch.setattr(vc, "is_proxy_auth_trust_active", lambda: True)

    # Mock active user
    active_user = MagicMock()
    active_user.is_active = True
    active_user.is_admin = False
    active_user.email = "proxy@example.com"

    async def mock_resolve_teams(email, user_info):
        return ["team1"]

    # Patch at the source module
    monkeypatch.setattr("mcpgateway.auth._resolve_teams_from_db", mock_resolve_teams)

    # Mock the DB and auth service
    mock_db = MagicMock()
    mock_auth_service = MagicMock()
    mock_auth_service.get_user_by_email = AsyncMock(return_value=active_user)

    # Mock request with proxy header (case-insensitive headers)
    request = MagicMock(spec=Request)
    mock_headers = MagicMock()
    mock_headers.get.return_value = "proxy@example.com"
    request.headers = mock_headers
    request.cookies = {}
    request.state = MagicMock()

    # Patch where get_db and EmailAuthService are imported inside _authenticate_proxy_user
    with patch("mcpgateway.db.get_db", return_value=iter([mock_db])):
        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_auth_service):
            result = await vc.require_auth(request=request, credentials=None, jwt_token=None)

    assert result is not None
    assert result["sub"] == "proxy@example.com"
    assert result["source"] == "proxy"


@pytest.mark.asyncio
async def test_verify_credentials_proxy_auth_no_header_raises(monkeypatch):
    """Lines 733-755: require_auth with proxy auth but no header raises."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request, HTTPException

    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "proxy_user_header", "X-Forwarded-User", raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)

    # Mock is_proxy_auth_trust_active to return True
    monkeypatch.setattr(vc, "is_proxy_auth_trust_active", lambda: True)

    # Mock request without proxy header
    request = MagicMock(spec=Request)
    request.headers = {}
    request.cookies = {}

    with pytest.raises(HTTPException) as exc_info:
        await vc.require_auth(request=request, credentials=None, jwt_token=None)

    assert exc_info.value.status_code == 401
    assert "Proxy authentication header required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_auth_bearer_token_empty_after_strip():
    """Line 149: get_auth_bearer_token_from_request with empty token after strip."""
    from mcpgateway.utils import verify_credentials as vc

    request = MagicMock()
    request.headers = {"authorization": "Bearer   "}  # Only whitespace after Bearer

    result = vc.get_auth_bearer_token_from_request(request)
    assert result is None


@pytest.mark.asyncio
async def test_configurable_http_bearer_invalid_scheme_no_auto_error():
    """Line 207: ConfigurableHTTPBearer with invalid scheme and auto_error=False."""
    from mcpgateway.utils import verify_credentials as vc
    from fastapi import Request

    bearer = vc.ConfigurableHTTPBearer(auto_error=False)

    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Basic credentials"}

    result = await bearer(request)
    assert result is None


@pytest.mark.asyncio
async def test_enforce_revocation_user_lookup_exception_returns(monkeypatch):
    """Line 517-519: Exception during user lookup should log warning and return."""
    from mcpgateway.utils import verify_credentials as vc

    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)

    # Mock _get_user_by_email_sync to raise exception
    def raise_exception(_email):
        raise RuntimeError("Database connection failed")

    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", raise_exception)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)

    payload = {"sub": "user@example.com", "jti": "test-jti"}

    # Should return None without raising (exception is caught and logged)
    result = await vc._enforce_revocation_and_active_user(payload)
    assert result is None


@pytest.mark.asyncio
async def test_build_metadata_urls():
    """Lines 1536-1550: _build_metadata_urls function."""
    from mcpgateway.utils import verify_credentials as vc

    # Test with issuer without path
    urls = vc._build_metadata_urls("https://auth.example.com")
    assert len(urls) == 2
    assert "https://auth.example.com/.well-known/oauth-authorization-server" in urls
    assert "https://auth.example.com/.well-known/openid-configuration" in urls

    # Test with issuer with path
    urls = vc._build_metadata_urls("https://auth.example.com/tenant1")
    assert len(urls) == 2
    assert "https://auth.example.com/.well-known/oauth-authorization-server/tenant1" in urls
    assert "https://auth.example.com/tenant1/.well-known/openid-configuration" in urls


@pytest.mark.asyncio
async def test_discover_oidc_metadata_success(monkeypatch):
    """Lines 1574-1645: _discover_oidc_metadata success path."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock

    # Mock HTTP client
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"issuer": "https://auth.example.com", "jwks_uri": "https://auth.example.com/jwks", "authorization_endpoint": "https://auth.example.com/authorize"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    async def mock_get_http_client():
        return mock_client

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

    # Clear cache
    vc._oauth_oidc_metadata_cache.clear()

    result = await vc._discover_oidc_metadata("https://auth.example.com")

    assert result is not None
    assert result["issuer"] == "https://auth.example.com"
    assert result["jwks_uri"] == "https://auth.example.com/jwks"


@pytest.mark.asyncio
async def test_discover_oidc_metadata_http_error(monkeypatch):
    """Lines 1574-1645: _discover_oidc_metadata with HTTP error."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock

    # Mock HTTP client with 404 response
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    async def mock_get_http_client():
        return mock_client

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

    # Clear cache
    vc._oauth_oidc_metadata_cache.clear()

    result = await vc._discover_oidc_metadata("https://auth.example.com")

    assert result is None


@pytest.mark.asyncio
async def test_discover_oidc_metadata_network_error(monkeypatch):
    """Lines 1574-1645: _discover_oidc_metadata with network error."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock

    # Mock HTTP client that raises exception
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

    async def mock_get_http_client():
        return mock_client

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

    # Clear cache
    vc._oauth_oidc_metadata_cache.clear()

    result = await vc._discover_oidc_metadata("https://auth.example.com")

    assert result is None


@pytest.mark.asyncio
async def test_verify_oauth_access_token_no_issuer(monkeypatch):
    """Lines 1673-1770: verify_oauth_access_token with token missing issuer."""
    from mcpgateway.utils import verify_credentials as vc
    import jwt

    # Create token without issuer
    token = jwt.encode({"sub": "user@example.com"}, "secret", algorithm="HS256")

    result = await vc.verify_oauth_access_token(token, ["https://auth.example.com"])

    assert result is None


@pytest.mark.asyncio
async def test_verify_oauth_access_token_issuer_not_in_allowlist(monkeypatch):
    """Lines 1673-1770: verify_oauth_access_token with issuer not in allowlist."""
    from mcpgateway.utils import verify_credentials as vc
    import jwt

    # Create token with issuer not in allowlist
    token = jwt.encode({"sub": "user@example.com", "iss": "https://untrusted.example.com"}, "secret", algorithm="HS256")

    result = await vc.verify_oauth_access_token(token, ["https://auth.example.com"])

    assert result is None


@pytest.mark.asyncio
async def test_verify_oauth_access_token_success(monkeypatch):
    """Lines 1690-1770: verify_oauth_access_token success path."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock
    import jwt

    # Create a valid token
    token_payload = {"sub": "user@example.com", "iss": "https://auth.example.com", "aud": "my-api", "exp": 9999999999}
    token = jwt.encode(token_payload, "secret", algorithm="HS256")

    # Mock metadata discovery
    mock_metadata = {"issuer": "https://auth.example.com", "jwks_uri": "https://auth.example.com/jwks"}

    # Mock JWKS client
    mock_signing_key = MagicMock()
    mock_signing_key.key = "secret"

    mock_jwks_client = MagicMock()
    mock_jwks_client.get_signing_key_from_jwt = MagicMock(return_value=mock_signing_key)

    monkeypatch.setattr(vc, "_discover_oidc_metadata", AsyncMock(return_value=mock_metadata))
    monkeypatch.setattr("jwt.PyJWKClient", lambda uri: mock_jwks_client)

    # Mock jwt.decode to return verified payload
    def mock_jwt_decode(token, **kwargs):
        return token_payload

    monkeypatch.setattr("asyncio.to_thread", AsyncMock(side_effect=lambda fn, *args, **kwargs: mock_jwt_decode(args[0]) if fn == jwt.decode else mock_signing_key))

    result = await vc.verify_oauth_access_token(token, ["https://auth.example.com"], expected_audience="my-api")

    assert result is not None
    assert result["sub"] == "user@example.com"


@pytest.mark.asyncio
async def test_verify_oauth_access_token_no_metadata(monkeypatch):
    """Lines 1690-1770: verify_oauth_access_token when metadata discovery fails."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock
    import jwt

    token = jwt.encode({"sub": "user@example.com", "iss": "https://auth.example.com"}, "secret", algorithm="HS256")

    # Mock metadata discovery to return None
    monkeypatch.setattr(vc, "_discover_oidc_metadata", AsyncMock(return_value=None))

    result = await vc.verify_oauth_access_token(token, ["https://auth.example.com"])

    assert result is None


@pytest.mark.asyncio
async def test_verify_oauth_access_token_no_jwks_uri(monkeypatch):
    """Lines 1690-1770: verify_oauth_access_token when metadata has no jwks_uri."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock
    import jwt

    token = jwt.encode({"sub": "user@example.com", "iss": "https://auth.example.com"}, "secret", algorithm="HS256")

    # Mock metadata without jwks_uri
    mock_metadata = {"issuer": "https://auth.example.com"}
    monkeypatch.setattr(vc, "_discover_oidc_metadata", AsyncMock(return_value=mock_metadata))

    result = await vc.verify_oauth_access_token(token, ["https://auth.example.com"])

    assert result is None


@pytest.mark.asyncio
async def test_verify_oauth_access_token_jwks_uri_origin_mismatch(monkeypatch):
    """Lines 1690-1770: verify_oauth_access_token with jwks_uri origin mismatch (SSRF defense)."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock
    import jwt

    token = jwt.encode({"sub": "user@example.com", "iss": "https://auth.example.com"}, "secret", algorithm="HS256")

    # Mock metadata with mismatched jwks_uri origin
    mock_metadata = {"issuer": "https://auth.example.com", "jwks_uri": "https://attacker.com/jwks"}  # Different origin!
    monkeypatch.setattr(vc, "_discover_oidc_metadata", AsyncMock(return_value=mock_metadata))

    result = await vc.verify_oauth_access_token(token, ["https://auth.example.com"])

    assert result is None


@pytest.mark.asyncio
async def test_verify_oauth_access_token_id_token_rejection(monkeypatch):
    """Lines 1690-1770: verify_oauth_access_token rejects OIDC ID tokens."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock
    import jwt

    # Create token with ID token markers (nonce)
    token = jwt.encode({"sub": "user@example.com", "iss": "https://auth.example.com", "nonce": "abc123"}, "secret", algorithm="HS256")  # ID token marker

    mock_metadata = {"issuer": "https://auth.example.com", "jwks_uri": "https://auth.example.com/jwks"}
    monkeypatch.setattr(vc, "_discover_oidc_metadata", AsyncMock(return_value=mock_metadata))

    result = await vc.verify_oauth_access_token(token, ["https://auth.example.com"])

    assert result is None


@pytest.mark.asyncio
async def test_verify_oauth_access_token_jwt_error(monkeypatch):
    """Lines 1690-1770: verify_oauth_access_token with JWT verification error."""
    from mcpgateway.utils import verify_credentials as vc
    from unittest.mock import AsyncMock
    import jwt

    token = jwt.encode({"sub": "user@example.com", "iss": "https://auth.example.com"}, "secret", algorithm="HS256")

    mock_metadata = {"issuer": "https://auth.example.com", "jwks_uri": "https://auth.example.com/jwks"}

    # Mock JWKS client that raises error
    mock_jwks_client = MagicMock()
    mock_jwks_client.get_signing_key_from_jwt = MagicMock(side_effect=jwt.PyJWTError("Invalid signature"))

    monkeypatch.setattr(vc, "_discover_oidc_metadata", AsyncMock(return_value=mock_metadata))
    monkeypatch.setattr("jwt.PyJWKClient", lambda uri: mock_jwks_client)

    result = await vc.verify_oauth_access_token(token, ["https://auth.example.com"])

    assert result is None
