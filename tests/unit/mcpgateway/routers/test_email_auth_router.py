# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_email_auth_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for Email Auth router.
This module tests email authentication endpoints including login with password change required.
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
import pytest

# First-Party
from mcpgateway.db import EmailUser
from mcpgateway.schemas import AdminCreateUserRequest, AdminUserUpdateRequest, ChangePasswordRequest, ForgotPasswordRequest, PublicRegistrationRequest, ResetPasswordRequest, SuccessResponse
from mcpgateway.services.email_auth_service import AuthenticationError, EmailValidationError, PasswordValidationError, UserExistsError


class TestEmailAuthLoginPasswordChangeRequired:
    """Test cases for login endpoint when password change is required."""

    @pytest.fixture
    def mock_user_needs_password_change(self):
        """Create mock user that needs password change."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.password_hash = "hashed_password"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = True
        user.failed_login_attempts = 0
        user.account_locked_until = None
        user.is_account_locked = MagicMock(return_value=False)
        user.reset_failed_attempts = MagicMock()
        return user

    @pytest.fixture
    def mock_user_normal(self):
        """Create mock user that does not need password change."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.password_hash = "hashed_password"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = False
        user.failed_login_attempts = 0
        user.account_locked_until = None
        user.auth_provider = "local"
        user.is_account_locked = MagicMock(return_value=False)
        user.reset_failed_attempts = MagicMock()
        user.get_teams = MagicMock(return_value=[])
        user.team_memberships = []
        return user

    @pytest.mark.asyncio
    async def test_login_returns_403_when_password_change_required(self, mock_user_needs_password_change):
        """Test that login returns 403 with X-Password-Change-Required header when password change is required."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        # Create mock request
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"User-Agent": "TestAgent/1.0"}

        # Create mock db session
        mock_db = MagicMock()

        # Create login request
        login_request = EmailLoginRequest(email="test@example.com", password="password123")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            mock_service = MockAuthService.return_value
            mock_service.authenticate_user = AsyncMock(return_value=mock_user_needs_password_change)

            # Call the login function - user.password_change_required is True
            response = await login(login_request, mock_request, mock_db)

            # Verify response
            assert response.status_code == status.HTTP_403_FORBIDDEN
            assert response.headers.get("X-Password-Change-Required") == "true"

            # Verify response body
            # Third-Party
            import orjson

            body = orjson.loads(response.body)
            assert "detail" in body
            assert "password change required" in body["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_returns_403_when_using_default_password(self, mock_user_normal):
        """Test that login returns 403 when user is using default password."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        # Create mock request
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"User-Agent": "TestAgent/1.0"}

        # Create mock db session
        mock_db = MagicMock()

        # Create login request
        login_request = EmailLoginRequest(email="test@example.com", password="password123")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            mock_service = MockAuthService.return_value
            mock_service.authenticate_user = AsyncMock(return_value=mock_user_normal)

            # Patch where Argon2PasswordService is imported (inside the function)
            with patch("mcpgateway.services.argon2_service.Argon2PasswordService") as MockPasswordService:
                mock_password_service = MockPasswordService.return_value
                # User IS using default password
                mock_password_service.verify_password.return_value = True
                mock_password_service.verify_password_async = AsyncMock(return_value=True)

                with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
                    mock_settings.default_user_password.get_secret_value.return_value = "default_password"

                    # Call the login function
                    response = await login(login_request, mock_request, mock_db)

                    # Verify response
                    assert response.status_code == status.HTTP_403_FORBIDDEN
                    assert response.headers.get("X-Password-Change-Required") == "true"

    @pytest.mark.asyncio
    async def test_login_success_when_no_password_change_required(self, mock_user_normal):
        """Test that login succeeds when password change is not required."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import AuthenticationResponse, EmailLoginRequest

        # Create mock request
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"User-Agent": "TestAgent/1.0"}

        # Create mock db session
        mock_db = MagicMock()

        # Create login request
        login_request = EmailLoginRequest(email="test@example.com", password="password123")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            mock_service = MockAuthService.return_value
            mock_service.authenticate_user = AsyncMock(return_value=mock_user_normal)

            # Patch where Argon2PasswordService is imported (inside the function)
            with patch("mcpgateway.services.argon2_service.Argon2PasswordService") as MockPasswordService:
                mock_password_service = MockPasswordService.return_value
                # User is NOT using default password
                mock_password_service.verify_password.return_value = False
                mock_password_service.verify_password_async = AsyncMock(return_value=False)

                with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
                    mock_settings.default_user_password.get_secret_value.return_value = "default_password"
                    mock_settings.token_expiry = 60
                    mock_settings.jwt_issuer = "test-issuer"
                    mock_settings.jwt_audience = "test-audience"

                    with patch("mcpgateway.routers.email_auth.create_access_token") as mock_create_token:
                        mock_create_token.return_value = ("test_token_123", 3600)

                        # Call the login function
                        response = await login(login_request, mock_request, mock_db)

                        # Verify response is AuthenticationResponse (not ORJSONResponse)
                        assert isinstance(response, AuthenticationResponse)
                        assert response.access_token == "test_token_123"
                        assert response.token_type == "bearer"


class TestCreateAccessTokenTeamsFormat:
    """Test cases for create_access_token teams claim format consistency.

    Ensures login tokens emit teams as List[str] (team IDs only) to match /tokens behavior.
    See issue #1486 for background on the UUID/int casting bug this prevents.
    """

    @pytest.fixture
    def mock_user_with_teams(self):
        """Create mock user with team memberships."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_admin = False
        user.auth_provider = "local"

        # Create mock teams
        team1 = MagicMock()
        team1.id = "550e8400-e29b-41d4-a716-446655440001"
        team1.name = "Engineering"
        team1.slug = "engineering"
        team1.is_personal = False

        team2 = MagicMock()
        team2.id = "550e8400-e29b-41d4-a716-446655440002"
        team2.name = "Personal Team"
        team2.slug = "personal-team"
        team2.is_personal = True

        user.get_teams = MagicMock(return_value=[team1, team2])

        # Mock team memberships for role lookup
        membership1 = MagicMock()
        membership1.team_id = team1.id
        membership1.role = "member"

        membership2 = MagicMock()
        membership2.team_id = team2.id
        membership2.role = "owner"

        user.team_memberships = [membership1, membership2]
        return user

    @pytest.mark.asyncio
    async def test_create_access_token_is_session_token(self, mock_user_with_teams):
        """Test that create_access_token creates lightweight session tokens.

        Session tokens should have token_use='session' and NOT embed teams.
        Teams are resolved server-side at request time from DB/cache.
        This is a fix for issue #2757 where large team lists caused cookies to exceed 4KB.
        """
        # First-Party
        from mcpgateway.routers.email_auth import create_access_token

        with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
            mock_settings.token_expiry = 60
            mock_settings.jwt_issuer = "test-issuer"
            mock_settings.jwt_audience = "test-audience"

            with patch("mcpgateway.routers.email_auth.create_jwt_token") as mock_jwt:
                # Capture the payload passed to create_jwt_token
                captured_payload = None

                async def capture_payload(payload, expires_in_minutes=None):
                    nonlocal captured_payload
                    captured_payload = payload
                    return "mock_token"

                mock_jwt.side_effect = capture_payload

                # Call create_access_token
                token, expires_in = await create_access_token(mock_user_with_teams)

                # Session token: no teams/namespaces embedded, has token_use
                assert "teams" not in captured_payload, "session tokens should not embed teams"
                assert "namespaces" not in captured_payload, "session tokens should not embed namespaces"
                assert captured_payload.get("token_use") == "session", "session tokens must have token_use='session'"
                assert "user" in captured_payload, "session tokens must have user info"
                assert "scopes" in captured_payload, "session tokens must have scopes"

    @pytest.mark.asyncio
    async def test_create_access_token_admin_is_session_token(self):
        """Test that admin session tokens also use token_use='session' and omit teams."""
        # First-Party
        from mcpgateway.routers.email_auth import create_access_token

        # Create admin user
        admin_user = MagicMock(spec=EmailUser)
        admin_user.email = "admin@example.com"
        admin_user.full_name = "Admin User"
        admin_user.is_admin = True
        admin_user.auth_provider = "local"
        admin_user.get_teams = MagicMock(return_value=[])
        admin_user.team_memberships = []

        with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
            mock_settings.token_expiry = 60
            mock_settings.jwt_issuer = "test-issuer"
            mock_settings.jwt_audience = "test-audience"

            with patch("mcpgateway.routers.email_auth.create_jwt_token") as mock_jwt:
                captured_payload = None

                async def capture_payload(payload, expires_in_minutes=None):
                    nonlocal captured_payload
                    captured_payload = payload
                    return "mock_token"

                mock_jwt.side_effect = capture_payload

                await create_access_token(admin_user)

                # Admin session tokens: same as regular — no teams, has token_use
                assert "teams" not in captured_payload, "admin session tokens should omit teams key"
                assert captured_payload.get("token_use") == "session", "admin session tokens must have token_use='session'"


@pytest.mark.asyncio
async def test_register_disabled():
    # First-Party
    from mcpgateway.routers import email_auth

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"User-Agent": "TestAgent/1.0"}

    registration = PublicRegistrationRequest(email="new@example.com", password="password1234", full_name="New User")

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.public_registration_enabled = False

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.register(registration, request, MagicMock())

        assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_register_success():
    # First-Party
    from mcpgateway.routers import email_auth
    from mcpgateway.schemas import AuthenticationResponse

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"User-Agent": "TestAgent/1.0"}

    registration = PublicRegistrationRequest(email="new@example.com", password="password1234", full_name="New User")

    user = MagicMock(spec=EmailUser)
    user.email = "new@example.com"
    user.full_name = "New User"
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "local"
    user.created_at = datetime.now(tz=timezone.utc)
    user.last_login = None
    user.password_change_required = False
    user.is_email_verified = MagicMock(return_value=True)

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.public_registration_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            MockAuthService.return_value.create_user = AsyncMock(return_value=user)
            with patch("mcpgateway.routers.email_auth.create_access_token", AsyncMock(return_value=("token", 60))):
                response = await email_auth.register(registration, request, MagicMock())

    assert isinstance(response, AuthenticationResponse)
    assert response.access_token == "token"


@pytest.mark.asyncio
async def test_register_validation_error():
    # First-Party
    from mcpgateway.routers import email_auth

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"User-Agent": "TestAgent/1.0"}

    registration = PublicRegistrationRequest(email="bad@example.com", password="password1234", full_name="Bad User")

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.public_registration_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            MockAuthService.return_value.create_user = AsyncMock(side_effect=EmailValidationError("bad"))

            with pytest.raises(email_auth.HTTPException) as excinfo:
                await email_auth.register(registration, request, MagicMock())

    assert excinfo.value.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_register_user_exists_error():
    # First-Party
    from mcpgateway.routers import email_auth

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"User-Agent": "TestAgent/1.0"}

    registration = PublicRegistrationRequest(email="exists@example.com", password="password1234", full_name="User")

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.public_registration_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            MockAuthService.return_value.create_user = AsyncMock(side_effect=UserExistsError("exists"))

            with pytest.raises(email_auth.HTTPException) as excinfo:
                await email_auth.register(registration, request, MagicMock())

    assert excinfo.value.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_change_password_success():
    # First-Party
    from mcpgateway.routers import email_auth

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"User-Agent": "TestAgent/1.0"}

    password_request = ChangePasswordRequest(old_password="oldpassword", new_password="newpassword")
    current_user = MagicMock()
    current_user.email = "user@example.com"

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        MockAuthService.return_value.change_password = AsyncMock(return_value=True)
        response = await email_auth.change_password(password_request, request, current_user=current_user, db=MagicMock())

    assert isinstance(response, SuccessResponse)
    assert response.success is True


@pytest.mark.asyncio
async def test_change_password_auth_error():
    # First-Party
    from mcpgateway.routers import email_auth

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"User-Agent": "TestAgent/1.0"}

    password_request = ChangePasswordRequest(old_password="oldpassword", new_password="newpassword")
    current_user = MagicMock()
    current_user.email = "user@example.com"

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        MockAuthService.return_value.change_password = AsyncMock(side_effect=AuthenticationError("bad"))

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.change_password(password_request, request, current_user=current_user, db=MagicMock())

    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_admin_list_users_with_and_without_pagination():
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    user = MagicMock(spec=EmailUser)
    user.email = "user@example.com"
    user.full_name = "User"
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "local"
    user.created_at = datetime.now(timezone.utc)
    user.last_login = None
    user.password_change_required = False
    user.is_email_verified = MagicMock(return_value=True)

    result = SimpleNamespace(data=[user], next_cursor="next")

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        MockAuthService.return_value.list_users = AsyncMock(return_value=result)
        response = await email_auth.list_users(include_pagination=True, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)
        assert response.users[0].email == "user@example.com"

        response_list = await email_auth.list_users(include_pagination=False, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)
        assert isinstance(response_list, list)
        assert response_list[0].email == "user@example.com"


@pytest.mark.asyncio
async def test_admin_list_users_error():
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        MockAuthService.return_value.list_users = AsyncMock(side_effect=Exception("boom"))
        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.list_users(include_pagination=True, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

    assert excinfo.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_admin_list_all_auth_events():
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    event = SimpleNamespace(id=1, timestamp=datetime.now(timezone.utc), user_email="user@example.com", event_type="login", success=True, ip_address="1.2.3.4", failure_reason=None)

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        MockAuthService.return_value.get_auth_events = AsyncMock(return_value=[event])
        result = await email_auth.list_all_auth_events(current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

    assert result[0].event_type == "login"


@pytest.mark.asyncio
async def test_admin_create_user_default_password_enforcement():
    # First-Party
    from mcpgateway.routers import email_auth

    user_request = AdminCreateUserRequest(email="new@example.com", password="defaultpass", full_name="New User", is_admin=False)
    mock_db = MagicMock()
    user = MagicMock(spec=EmailUser)
    user.email = "new@example.com"
    user.full_name = "New User"
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "local"
    user.created_at = datetime.now(timezone.utc)
    user.last_login = None
    user.password_change_required = False
    user.is_email_verified = MagicMock(return_value=False)

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_change_enforcement_enabled = True
        mock_settings.require_password_change_for_default_password = True
        mock_settings.default_user_password.get_secret_value.return_value = "defaultpass"

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            MockAuthService.return_value.create_user = AsyncMock(return_value=user)
            response = await email_auth.create_user(user_request, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

    assert response.password_change_required is True
    mock_db.commit.assert_called()


@pytest.mark.asyncio
async def test_admin_get_update_delete_user():
    # First-Party
    from mcpgateway.routers import email_auth

    user = MagicMock(spec=EmailUser)
    user.email = "user@example.com"
    user.full_name = "Updated"
    user.is_admin = True
    user.is_active = True
    user.auth_provider = "local"
    user.created_at = datetime.now(timezone.utc)
    user.last_login = None
    user.password_change_required = False
    user.password_hash = "hashed"
    user.is_email_verified = MagicMock(return_value=True)

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        auth_service.get_user_by_email = AsyncMock(return_value=user)
        auth_service.update_user = AsyncMock(return_value=user)
        auth_service.is_last_active_admin = AsyncMock(return_value=False)
        auth_service.delete_user = AsyncMock(return_value=None)

        update_request = AdminUserUpdateRequest(password="newPassword123!", full_name="Updated", is_admin=True)

        response = await email_auth.get_user("user@example.com", current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)
        assert response.email == "user@example.com"

        response = await email_auth.update_user("user@example.com", update_request, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)
        assert response.full_name == "Updated"
        # Verify update_user was called with correct params
        auth_service.update_user.assert_called_once_with(
            email="user@example.com",
            full_name="Updated",
            is_admin=True,
            is_active=None,
            password_change_required=None,
            password="newPassword123!",
            admin_origin_source="api",
            disable_admin_protection=None
        )

        delete_response = await email_auth.delete_user("user@example.com", current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)
        assert delete_response.success is True


@pytest.mark.asyncio
async def test_admin_update_user_without_full_name_and_is_admin():
    """Test empty update (no fields) delegates to service correctly."""
    # First-Party
    from mcpgateway.routers import email_auth

    user = MagicMock(spec=EmailUser)
    user.email = "user@example.com"
    user.full_name = "Old Name"
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "local"
    user.created_at = datetime.now(timezone.utc)
    user.last_login = None
    user.password_change_required = False
    user.password_hash = None
    user.is_email_verified = MagicMock(return_value=True)

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        auth_service.update_user = AsyncMock(return_value=user)

        update_request = AdminUserUpdateRequest()

        response = await email_auth.update_user(
            "user@example.com",
            update_request,
            current_user_ctx={"db": mock_db, "email": "admin@example.com"},
            db=mock_db,
        )

        assert response.full_name == "Old Name"
        # Verify service was called with all None values
        auth_service.update_user.assert_called_once_with(
            email="user@example.com",
            full_name=None,
            is_admin=None,
            is_active=None,
            password_change_required=None,
            password=None,
            admin_origin_source="api",
            disable_admin_protection=None
        )


@pytest.mark.asyncio
async def test_admin_update_user_invalid_password():
    """Test updating with invalid password raises PasswordValidationError."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        # Service raises PasswordValidationError when password is too weak
        auth_service.update_user = AsyncMock(side_effect=PasswordValidationError("Password too weak"))

        update_request = AdminUserUpdateRequest(password="thisisweak1234", is_admin=False)

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.update_user(
                "user@example.com",
                update_request,
                current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                db=mock_db,
            )

        assert excinfo.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Password too weak" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_admin_update_user_not_found():
    """Test updating non-existent user returns 404."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        # Service raises ValueError with "not found" for missing users
        auth_service.update_user = AsyncMock(side_effect=ValueError("User nonexistent@example.com not found"))

        update_request = AdminUserUpdateRequest(full_name="New Name", is_admin=False)

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.update_user(
                "nonexistent@example.com",
                update_request,
                current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                db=mock_db,
            )

        assert excinfo.value.status_code == status.HTTP_404_NOT_FOUND
        assert "User not found" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_admin_delete_user_self_block():
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        MockAuthService.return_value.is_last_active_admin = AsyncMock(return_value=False)
        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.delete_user("admin@example.com", current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

    assert excinfo.value.status_code == status.HTTP_400_BAD_REQUEST


def test_emailuser_response_serialization_with_api_token():
    """Test EmailUserResponse serialization with API token user (regression test for #2700).

    This test verifies that EmailUser objects created for API token authentication
    include all required fields (auth_provider, password_change_required) and can
    be successfully serialized to EmailUserResponse without validation errors.

    Previously, creating EmailUser objects without these fields would cause 422
    validation errors when GET /auth/email/me tried to serialize the response.
    """
    # First-Party
    from mcpgateway.schemas import EmailUserResponse

    # Create a user that simulates API token authentication
    mock_user = EmailUser(
        email="apitoken@example.com",
        password_hash="hash",
        full_name="API Token User",
        is_admin=False,
        is_active=True,
        auth_provider="api_token",
        password_change_required=False,
        email_verified_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # Verify serialization works without errors (this would raise ValidationError if fields missing)
    response = EmailUserResponse.from_email_user(mock_user)

    # Verify all required fields are present and correct
    assert response.email == "apitoken@example.com"
    assert response.full_name == "API Token User"
    assert response.is_admin is False
    assert response.is_active is True
    assert response.auth_provider == "api_token"
    assert response.password_change_required is False
    assert response.email_verified is True


@pytest.mark.asyncio
async def test_admin_update_last_admin_demote_blocked():
    """Test that demoting the last active admin returns 400."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        auth_service.update_user = AsyncMock(side_effect=ValueError("Cannot demote or deactivate the last remaining active admin user"))

        update_request = AdminUserUpdateRequest(is_admin=False)

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.update_user(
                "admin@example.com",
                update_request,
                current_user_ctx={"db": mock_db, "email": "other-admin@example.com"},
                db=mock_db,
            )

        assert excinfo.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "last remaining active admin" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_admin_update_last_admin_deactivate_blocked():
    """Test that deactivating the last active admin returns 400."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        auth_service.update_user = AsyncMock(side_effect=ValueError("Cannot demote or deactivate the last remaining active admin user"))

        update_request = AdminUserUpdateRequest(is_active=False)

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.update_user(
                "admin@example.com",
                update_request,
                current_user_ctx={"db": mock_db, "email": "other-admin@example.com"},
                db=mock_db,
            )

        assert excinfo.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "last remaining active admin" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_admin_update_protect_all_admins_blocked():
    """Test that demoting any admin is blocked when protect_all_admins is enabled."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        auth_service.update_user = AsyncMock(side_effect=ValueError("Admin protection is enabled — cannot demote or deactivate any admin user"))

        update_request = AdminUserUpdateRequest(is_admin=False)

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.update_user(
                "admin@example.com",
                update_request,
                current_user_ctx={"db": mock_db, "email": "other-admin@example.com"},
                db=mock_db,
            )

        assert excinfo.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Admin protection is enabled" in str(excinfo.value.detail)


# ============================================================================
# Coverage improvement tests
# ============================================================================


class TestGetDb:
    """Tests for get_db generator covering exception/cleanup branches."""

    def test_get_db_normal_flow(self):
        """Normal flow: yield → commit → close."""
        # First-Party
        from mcpgateway.routers.email_auth import get_db

        mock_session = MagicMock()
        with patch("mcpgateway.routers.email_auth.SessionLocal", return_value=mock_session):
            gen = get_db()
            db = next(gen)
            assert db is mock_session
            try:
                next(gen)
            except StopIteration:
                pass
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_db_body_exception_rollback(self):
        """Body raises → rollback → re-raise → close."""
        # First-Party
        from mcpgateway.routers.email_auth import get_db

        mock_session = MagicMock()
        with patch("mcpgateway.routers.email_auth.SessionLocal", return_value=mock_session):
            gen = get_db()
            next(gen)
            with pytest.raises(RuntimeError, match="body error"):
                gen.throw(RuntimeError("body error"))
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_db_rollback_fails_invalidate(self):
        """Rollback fails → invalidate → re-raise."""
        # First-Party
        from mcpgateway.routers.email_auth import get_db

        mock_session = MagicMock()
        mock_session.rollback.side_effect = RuntimeError("rollback error")
        with patch("mcpgateway.routers.email_auth.SessionLocal", return_value=mock_session):
            gen = get_db()
            next(gen)
            with pytest.raises(RuntimeError, match="body error"):
                gen.throw(RuntimeError("body error"))
            mock_session.invalidate.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_db_rollback_and_invalidate_both_fail(self):
        """Rollback fails, invalidate fails → pass (best effort) → re-raise."""
        # First-Party
        from mcpgateway.routers.email_auth import get_db

        mock_session = MagicMock()
        mock_session.rollback.side_effect = RuntimeError("rollback error")
        mock_session.invalidate.side_effect = RuntimeError("invalidate error")
        with patch("mcpgateway.routers.email_auth.SessionLocal", return_value=mock_session):
            gen = get_db()
            next(gen)
            with pytest.raises(RuntimeError, match="body error"):
                gen.throw(RuntimeError("body error"))
            mock_session.close.assert_called_once()


class TestGetClientIpBranches:
    """Tests for get_client_ip helper covering X-Forwarded-For and X-Real-IP."""

    def test_x_forwarded_for(self):
        # First-Party
        from mcpgateway.routers.email_auth import get_client_ip

        request = MagicMock()
        request.headers = {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}
        assert get_client_ip(request) == "10.0.0.1"

    def test_x_real_ip(self):
        # First-Party
        from mcpgateway.routers.email_auth import get_client_ip

        request = MagicMock()
        # MagicMock headers with .get that returns None for X-Forwarded-For, value for X-Real-IP
        headers_mock = MagicMock()
        headers_mock.get = lambda key, default=None: {"X-Real-IP": "192.168.1.1"}.get(key, default)
        request.headers = headers_mock
        assert get_client_ip(request) == "192.168.1.1"


class TestCreateAccessTokenEdgeCases:
    """Tests for create_access_token error handling branches."""

    @pytest.mark.asyncio
    async def test_get_teams_raises_exception(self):
        """get_teams raises → teams = [] (lines 144-145)."""
        # First-Party
        from mcpgateway.routers.email_auth import create_access_token

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test"
        user.is_admin = False
        user.auth_provider = "local"
        user.get_teams = MagicMock(side_effect=RuntimeError("db error"))
        user.team_memberships = []

        with patch("mcpgateway.routers.email_auth.settings") as mock_settings, patch("mcpgateway.routers.email_auth.create_jwt_token", AsyncMock(return_value="tok")):
            mock_settings.token_expiry = 60
            mock_settings.jwt_issuer = "iss"
            mock_settings.jwt_audience = "aud"

            token, exp = await create_access_token(user)
            assert token == "tok"

    @pytest.mark.asyncio
    async def test_safe_teams_first_fallback(self):
        """Team attribute access fails → first fallback (lines 160-163)."""
        # First-Party
        from mcpgateway.routers.email_auth import create_access_token

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test"
        user.is_admin = False
        user.auth_provider = "local"
        # Team object that causes the main try to fail (role lookup fails)
        bad_team = MagicMock()
        bad_team.id = "team1"
        bad_team.name = "Team 1"
        bad_team.slug = "team-1"
        bad_team.is_personal = False
        user.get_teams = MagicMock(return_value=[bad_team])
        # Empty team_memberships so the role generator raises StopIteration inside next()
        # Actually next() has a default, so it won't raise. Let me make the whole comprehension fail.
        # The role = str(next((...), "member")) won't fail easily. Let me make team_memberships
        # raise when iterated.
        user.team_memberships = MagicMock()
        user.team_memberships.__iter__ = MagicMock(side_effect=TypeError("not iterable"))

        captured = {}

        async def capture(payload, **kw):
            captured["payload"] = payload
            return "tok"

        with patch("mcpgateway.routers.email_auth.settings") as mock_settings, patch("mcpgateway.routers.email_auth.create_jwt_token", side_effect=capture):
            mock_settings.token_expiry = 60
            mock_settings.jwt_issuer = "iss"
            mock_settings.jwt_audience = "aud"

            token, _ = await create_access_token(user)
            assert token == "tok"
            # Should have fallen back: name=str(team), slug=str(team)
            teams_in_payload = captured["payload"].get("teams", [])
            assert isinstance(teams_in_payload, list)

    @pytest.mark.asyncio
    async def test_safe_teams_second_fallback(self):
        """Both first and second fallback - str(team) raises (lines 164-165)."""
        # First-Party
        from mcpgateway.routers.email_auth import create_access_token

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test"
        user.is_admin = False
        user.auth_provider = "local"
        # Team that fails str() in first fallback
        bad_team = MagicMock()
        bad_team.__str__ = MagicMock(side_effect=RuntimeError("no str"))
        bad_team.id = property(lambda self: (_ for _ in ()).throw(RuntimeError("no id")))
        # Make getattr fail on the team for main try block
        user.get_teams = MagicMock(return_value=[bad_team])
        user.team_memberships = MagicMock()
        user.team_memberships.__iter__ = MagicMock(side_effect=TypeError("fail"))

        captured = {}

        async def capture(payload, **kw):
            captured["payload"] = payload
            return "tok"

        with patch("mcpgateway.routers.email_auth.settings") as mock_settings, patch("mcpgateway.routers.email_auth.create_jwt_token", side_effect=capture):
            mock_settings.token_expiry = 60
            mock_settings.jwt_issuer = "iss"
            mock_settings.jwt_audience = "aud"

            token, _ = await create_access_token(user)
            assert token == "tok"


@pytest.mark.asyncio
async def test_create_legacy_access_token():
    """Test create_legacy_access_token (lines 210-230)."""
    # First-Party
    from mcpgateway.routers.email_auth import create_legacy_access_token

    user = MagicMock(spec=EmailUser)
    user.email = "user@example.com"
    user.full_name = "User"
    user.is_admin = False
    user.auth_provider = "local"

    captured = {}

    async def capture(payload, **kw):
        captured["payload"] = payload
        return "legacy_tok"

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings, patch("mcpgateway.routers.email_auth.create_jwt_token", side_effect=capture):
        mock_settings.token_expiry = 30
        mock_settings.jwt_issuer = "iss"
        mock_settings.jwt_audience = "aud"

        token, expires_in = await create_legacy_access_token(user)

    assert token == "legacy_tok"
    assert expires_in == 1800  # 30 minutes * 60
    assert captured["payload"]["sub"] == "user@example.com"
    assert captured["payload"]["email"] == "user@example.com"
    assert captured["payload"]["iss"] == "iss"
    assert "teams" not in captured["payload"]


class TestLoginEdgeCases:
    """Tests for login edge cases and error branches."""

    @pytest.mark.asyncio
    async def test_login_user_none(self):
        """authenticate_user returns None → 401 (line 269)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.authenticate_user = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc:
                await login(login_req, request, MagicMock())

            assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_password_age_expired(self):
        """Password age exceeds max → needs_password_change (lines 284-291)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.is_admin = False
        user.password_change_required = False
        user.password_changed_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        user.auth_provider = "local"

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc, patch("mcpgateway.routers.email_auth.settings") as mock_settings:
            MockSvc.return_value.authenticate_user = AsyncMock(return_value=user)
            mock_settings.password_change_enforcement_enabled = True
            mock_settings.password_max_age_days = 90
            mock_settings.detect_default_password_on_login = False

            response = await login(login_req, request, MagicMock())

        assert response.status_code == 403
        assert response.headers.get("X-Password-Change-Required") == "true"

    @pytest.mark.asyncio
    async def test_login_password_age_exception(self):
        """Password age check raises exception → debug log (lines 290-291)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = False
        # Naive datetime → subtraction with aware utc_now() raises TypeError
        user.password_changed_at = datetime(2020, 1, 1)
        user.auth_provider = "local"
        user.created_at = datetime.now(timezone.utc)
        user.last_login = None
        user.is_email_verified = MagicMock(return_value=True)
        user.get_teams = MagicMock(return_value=[])
        user.team_memberships = []

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with (
            patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc,
            patch("mcpgateway.routers.email_auth.settings") as mock_settings,
            patch("mcpgateway.routers.email_auth.create_access_token", AsyncMock(return_value=("tok", 60))),
        ):
            MockSvc.return_value.authenticate_user = AsyncMock(return_value=user)
            mock_settings.password_change_enforcement_enabled = True
            mock_settings.password_max_age_days = 90
            mock_settings.detect_default_password_on_login = False
            mock_settings.token_expiry = 60

            response = await login(login_req, request, MagicMock())

        assert response.access_token == "tok"

    @pytest.mark.asyncio
    async def test_login_password_age_not_expired(self):
        """Password age < max_age → no change required (branch 287→294)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import AuthenticationResponse, EmailLoginRequest

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = False
        # Recently changed password
        user.password_changed_at = datetime.now(timezone.utc)
        user.auth_provider = "local"
        user.created_at = datetime.now(timezone.utc)
        user.last_login = None
        user.is_email_verified = MagicMock(return_value=True)
        user.get_teams = MagicMock(return_value=[])
        user.team_memberships = []

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with (
            patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc,
            patch("mcpgateway.routers.email_auth.settings") as mock_settings,
            patch("mcpgateway.routers.email_auth.create_access_token", AsyncMock(return_value=("tok", 60))),
        ):
            MockSvc.return_value.authenticate_user = AsyncMock(return_value=user)
            mock_settings.password_change_enforcement_enabled = True
            mock_settings.password_max_age_days = 90
            mock_settings.detect_default_password_on_login = False

            response = await login(login_req, request, MagicMock())

        assert isinstance(response, AuthenticationResponse)
        assert response.access_token == "tok"

    @pytest.mark.asyncio
    async def test_login_enforcement_disabled(self):
        """password_change_enforcement_enabled is False (branch 274->312)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import AuthenticationResponse, EmailLoginRequest

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = True  # would trigger if enforcement enabled
        user.auth_provider = "local"
        user.created_at = datetime.now(timezone.utc)
        user.last_login = None
        user.is_email_verified = MagicMock(return_value=True)
        user.get_teams = MagicMock(return_value=[])
        user.team_memberships = []

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with (
            patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc,
            patch("mcpgateway.routers.email_auth.settings") as mock_settings,
            patch("mcpgateway.routers.email_auth.create_access_token", AsyncMock(return_value=("tok", 60))),
        ):
            MockSvc.return_value.authenticate_user = AsyncMock(return_value=user)
            mock_settings.password_change_enforcement_enabled = False

            response = await login(login_req, request, MagicMock())

        assert isinstance(response, AuthenticationResponse)
        assert response.access_token == "tok"

    @pytest.mark.asyncio
    async def test_login_default_password_enforcement_disabled(self):
        """Using default password but require_password_change_for_default_password=False (line 309-310)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import AuthenticationResponse, EmailLoginRequest

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = False
        user.password_changed_at = None
        user.auth_provider = "local"
        user.created_at = datetime.now(timezone.utc)
        user.last_login = None
        user.is_email_verified = MagicMock(return_value=True)
        user.get_teams = MagicMock(return_value=[])
        user.team_memberships = []

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with (
            patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc,
            patch("mcpgateway.routers.email_auth.settings") as mock_settings,
            patch("mcpgateway.services.argon2_service.Argon2PasswordService") as MockPwdSvc,
            patch("mcpgateway.routers.email_auth.create_access_token", AsyncMock(return_value=("tok", 60))),
        ):
            MockSvc.return_value.authenticate_user = AsyncMock(return_value=user)
            mock_settings.password_change_enforcement_enabled = True
            mock_settings.password_max_age_days = 90
            mock_settings.detect_default_password_on_login = True
            mock_settings.require_password_change_for_default_password = False
            mock_settings.default_user_password.get_secret_value.return_value = "default"
            MockPwdSvc.return_value.verify_password_async = AsyncMock(return_value=True)

            response = await login(login_req, request, MagicMock())

        assert isinstance(response, AuthenticationResponse)

    @pytest.mark.asyncio
    async def test_login_default_password_commit_failure(self):
        """db.commit() fails when setting password_change_required (lines 307-308)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.is_admin = False
        user.password_change_required = False
        user.password_changed_at = None
        user.auth_provider = "local"

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        mock_db = MagicMock()
        mock_db.commit.side_effect = RuntimeError("commit fail")

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with (
            patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc,
            patch("mcpgateway.routers.email_auth.settings") as mock_settings,
            patch("mcpgateway.services.argon2_service.Argon2PasswordService") as MockPwdSvc,
        ):
            MockSvc.return_value.authenticate_user = AsyncMock(return_value=user)
            mock_settings.password_change_enforcement_enabled = True
            mock_settings.password_max_age_days = 90
            mock_settings.detect_default_password_on_login = True
            mock_settings.require_password_change_for_default_password = True
            mock_settings.default_user_password.get_secret_value.return_value = "default"
            MockPwdSvc.return_value.verify_password_async = AsyncMock(return_value=True)

            # Still returns 403 since needs_password_change=True even with commit failure
            response = await login(login_req, request, mock_db)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_login_detect_default_password_disabled(self):
        """detect_default_password_on_login is False (branch 294->312)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import AuthenticationResponse, EmailLoginRequest

        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = False
        user.password_changed_at = None
        user.auth_provider = "local"
        user.created_at = datetime.now(timezone.utc)
        user.last_login = None
        user.is_email_verified = MagicMock(return_value=True)
        user.get_teams = MagicMock(return_value=[])
        user.team_memberships = []

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with (
            patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc,
            patch("mcpgateway.routers.email_auth.settings") as mock_settings,
            patch("mcpgateway.routers.email_auth.create_access_token", AsyncMock(return_value=("tok", 60))),
        ):
            MockSvc.return_value.authenticate_user = AsyncMock(return_value=user)
            mock_settings.password_change_enforcement_enabled = True
            mock_settings.password_max_age_days = 90
            mock_settings.detect_default_password_on_login = False

            response = await login(login_req, request, MagicMock())

        assert isinstance(response, AuthenticationResponse)

    @pytest.mark.asyncio
    async def test_login_generic_exception(self):
        """Non-HTTP exception → 500 (lines 330-332)."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        login_req = EmailLoginRequest(email="test@example.com", password="pass")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.authenticate_user = AsyncMock(side_effect=RuntimeError("db down"))

            with pytest.raises(HTTPException) as exc:
                await login(login_req, request, MagicMock())

            assert exc.value.status_code == 500


class TestRegisterEdgeCases:
    """Tests for register() error branches."""

    @pytest.mark.asyncio
    async def test_register_password_validation_error(self):
        """PasswordValidationError → 400 (line 399)."""
        # First-Party
        from mcpgateway.routers import email_auth

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        reg = PublicRegistrationRequest(email="new@example.com", password="weakpass1234", full_name="User")

        with patch("mcpgateway.routers.email_auth.settings") as mock_settings, patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            mock_settings.public_registration_enabled = True
            MockSvc.return_value.create_user = AsyncMock(side_effect=PasswordValidationError("too weak"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.register(reg, request, MagicMock())

            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_register_generic_exception(self):
        """Generic exception → 500 (lines 402-404)."""
        # First-Party
        from mcpgateway.routers import email_auth

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        reg = PublicRegistrationRequest(email="new@example.com", password="password1234", full_name="User")

        with patch("mcpgateway.routers.email_auth.settings") as mock_settings, patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            mock_settings.public_registration_enabled = True
            MockSvc.return_value.create_user = AsyncMock(side_effect=RuntimeError("db down"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.register(reg, request, MagicMock())

            assert exc.value.status_code == 500


class TestChangePasswordEdgeCases:
    """Tests for change_password() error branches."""

    @pytest.mark.asyncio
    async def test_change_password_returns_false(self):
        """change_password returns False → 500 (line 443)."""
        # First-Party
        from mcpgateway.routers import email_auth

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        pwd_req = ChangePasswordRequest(old_password="oldpassword", new_password="newpassword")
        current_user = MagicMock()
        current_user.email = "user@example.com"

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.change_password = AsyncMock(return_value=False)

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.change_password(pwd_req, request, current_user=current_user, db=MagicMock())

            assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_change_password_validation_error(self):
        """PasswordValidationError → 400 (lines 447-448)."""
        # First-Party
        from mcpgateway.routers import email_auth

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        pwd_req = ChangePasswordRequest(old_password="oldpassword", new_password="newpassword")
        current_user = MagicMock()
        current_user.email = "user@example.com"

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.change_password = AsyncMock(side_effect=PasswordValidationError("too weak"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.change_password(pwd_req, request, current_user=current_user, db=MagicMock())

            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_change_password_generic_exception(self):
        """Generic exception → 500 (lines 449-451)."""
        # First-Party
        from mcpgateway.routers import email_auth

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {"User-Agent": "Test"}

        pwd_req = ChangePasswordRequest(old_password="oldpassword", new_password="newpassword")
        current_user = MagicMock()
        current_user.email = "user@example.com"

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.change_password = AsyncMock(side_effect=RuntimeError("db down"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.change_password(pwd_req, request, current_user=current_user, db=MagicMock())

            assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_get_current_user_profile():
    """Test get_current_user_profile (line 471)."""
    # First-Party
    from mcpgateway.routers.email_auth import get_current_user_profile
    from mcpgateway.schemas import EmailUserResponse

    user = MagicMock(spec=EmailUser)
    user.email = "user@example.com"
    user.full_name = "User"
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "local"
    user.created_at = datetime.now(timezone.utc)
    user.last_login = None
    user.password_change_required = False
    user.is_email_verified = MagicMock(return_value=True)

    result = await get_current_user_profile(current_user=user)
    assert isinstance(result, EmailUserResponse)
    assert result.email == "user@example.com"


class TestGetAuthEvents:
    """Tests for get_auth_events endpoint."""

    @pytest.mark.asyncio
    async def test_get_auth_events_success(self):
        """Successful retrieval (lines 494-499)."""
        # First-Party
        from mcpgateway.routers.email_auth import get_auth_events

        mock_db = MagicMock()
        current_user = MagicMock()
        current_user.email = "user@example.com"

        event = SimpleNamespace(id=1, timestamp=datetime.now(timezone.utc), user_email="user@example.com", event_type="login", success=True, ip_address="1.2.3.4", failure_reason=None)

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.get_auth_events = AsyncMock(return_value=[event])

            result = await get_auth_events(limit=50, offset=0, current_user=current_user, db=mock_db)

        assert len(result) == 1
        assert result[0].event_type == "login"

    @pytest.mark.asyncio
    async def test_get_auth_events_error(self):
        """Exception → 500 (lines 501-503)."""
        # First-Party
        from mcpgateway.routers.email_auth import get_auth_events

        mock_db = MagicMock()
        current_user = MagicMock()
        current_user.email = "user@example.com"

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.get_auth_events = AsyncMock(side_effect=RuntimeError("db down"))

            with pytest.raises(HTTPException) as exc:
                await get_auth_events(limit=50, offset=0, current_user=current_user, db=mock_db)

            assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_list_all_auth_events_error():
    """list_all_auth_events generic exception → 500 (lines 588-590)."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
        MockSvc.return_value.get_auth_events = AsyncMock(side_effect=RuntimeError("db down"))

        with pytest.raises(email_auth.HTTPException) as exc:
            await email_auth.list_all_auth_events(current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

        assert exc.value.status_code == 500


class TestAdminCreateUserEdgeCases:
    """Tests for admin create_user error branches."""

    @pytest.mark.asyncio
    async def test_create_user_no_default_password_enforcement(self):
        """Password != default, so enforcement block is skipped (branch 634->642 False)."""
        # First-Party
        from mcpgateway.routers import email_auth

        user_request = AdminCreateUserRequest(email="new@example.com", password="unique_pass", full_name="User", is_admin=False)
        mock_db = MagicMock()

        user = MagicMock(spec=EmailUser)
        user.email = "new@example.com"
        user.full_name = "User"
        user.is_admin = False
        user.is_active = True
        user.auth_provider = "local"
        user.created_at = datetime.now(timezone.utc)
        user.last_login = None
        user.password_change_required = False
        user.is_email_verified = MagicMock(return_value=False)

        with patch("mcpgateway.routers.email_auth.settings") as mock_settings, patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            mock_settings.password_change_enforcement_enabled = True
            mock_settings.require_password_change_for_default_password = True
            mock_settings.default_user_password.get_secret_value.return_value = "defaultpass"
            MockSvc.return_value.create_user = AsyncMock(return_value=user)

            response = await email_auth.create_user(user_request, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

        assert response.email == "new@example.com"
        assert response.password_change_required is False

    @pytest.mark.asyncio
    async def test_create_user_email_validation_error(self):
        """EmailValidationError → 400 (line 648-649)."""
        # First-Party
        from mcpgateway.routers import email_auth

        user_request = AdminCreateUserRequest(email="bad@example.com", password="pass12345678", full_name="User", is_admin=False)
        mock_db = MagicMock()

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.create_user = AsyncMock(side_effect=EmailValidationError("invalid email"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.create_user(user_request, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_user_password_validation_error(self):
        """PasswordValidationError → 400 (lines 650-651)."""
        # First-Party
        from mcpgateway.routers import email_auth

        user_request = AdminCreateUserRequest(email="new@example.com", password="weakpass1234", full_name="User", is_admin=False)
        mock_db = MagicMock()

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.create_user = AsyncMock(side_effect=PasswordValidationError("too weak"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.create_user(user_request, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_user_user_exists_error(self):
        """UserExistsError → 409 (lines 652-653)."""
        # First-Party
        from mcpgateway.routers import email_auth

        user_request = AdminCreateUserRequest(email="exists@example.com", password="pass1234", full_name="User", is_admin=False)
        mock_db = MagicMock()

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.create_user = AsyncMock(side_effect=UserExistsError("exists"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.create_user(user_request, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

            assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_create_user_generic_exception(self):
        """Generic exception → 500 (lines 654-656)."""
        # First-Party
        from mcpgateway.routers import email_auth

        user_request = AdminCreateUserRequest(email="new@example.com", password="pass1234", full_name="User", is_admin=False)
        mock_db = MagicMock()

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.create_user = AsyncMock(side_effect=RuntimeError("db down"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.create_user(user_request, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)

            assert exc.value.status_code == 500


class TestAdminGetUserEdgeCases:
    """Tests for admin get_user error branches."""

    @pytest.mark.asyncio
    async def test_get_user_not_found(self):
        """User not found → 404 (line 680)."""
        # First-Party
        from mcpgateway.routers import email_auth

        mock_db = MagicMock()

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.get_user_by_email = AsyncMock(return_value=None)

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.get_user(
                    "missing@example.com",
                    current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                    db=mock_db,
                )

            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_user_generic_exception(self):
        """Generic exception → 500 (lines 686-688)."""
        # First-Party
        from mcpgateway.routers import email_auth

        mock_db = MagicMock()

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.get_user_by_email = AsyncMock(side_effect=RuntimeError("db down"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.get_user(
                    "user@example.com",
                    current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                    db=mock_db,
                )

            assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_admin_update_user_generic_exception():
    """update_user generic exception → 500 (lines 733-735)."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
        MockSvc.return_value.update_user = AsyncMock(side_effect=RuntimeError("db down"))

        update_request = AdminUserUpdateRequest(full_name="New Name")

        with pytest.raises(email_auth.HTTPException) as exc:
            await email_auth.update_user(
                "user@example.com",
                update_request,
                current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                db=mock_db,
            )

        assert exc.value.status_code == 500


class TestAdminDeleteUserEdgeCases:
    """Tests for admin delete_user error branches."""

    @pytest.mark.asyncio
    async def test_delete_user_last_admin(self):
        """is_last_active_admin returns True → 400 (line 763)."""
        # First-Party
        from mcpgateway.routers import email_auth

        mock_db = MagicMock()

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.is_last_active_admin = AsyncMock(return_value=True)

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.delete_user(
                    "lastadmin@example.com",
                    current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                    db=mock_db,
                )

            assert exc.value.status_code == 400
            assert "last remaining admin" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_delete_user_generic_exception(self):
        """Generic exception → 500 (lines 776-778)."""
        # First-Party
        from mcpgateway.routers import email_auth

        mock_db = MagicMock()

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.is_last_active_admin = AsyncMock(return_value=False)
            MockSvc.return_value.delete_user = AsyncMock(side_effect=RuntimeError("db down"))

            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.delete_user(
                    "user@example.com",
                    current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                    db=mock_db,
                )

            assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_forgot_password_success_response():
    """Forgot-password returns generic success message."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.request_password_reset = AsyncMock(return_value=SimpleNamespace(rate_limited=False, email_sent=True))
            response = await email_auth.forgot_password(ForgotPasswordRequest(email="user@example.com"), mock_request, db=mock_db)

    assert response.success is True
    assert "registered" in response.message.lower()


@pytest.mark.asyncio
async def test_forgot_password_rate_limited_response():
    """Forgot-password returns 429 when rate limit is hit."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.request_password_reset = AsyncMock(return_value=SimpleNamespace(rate_limited=True, email_sent=False))
            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.forgot_password(ForgotPasswordRequest(email="user@example.com"), mock_request, db=mock_db)

    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_validate_password_reset_token_success():
    """Reset-token validation returns valid=True for valid token."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    reset_token = SimpleNamespace(expires_at=datetime.now(timezone.utc))

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.validate_password_reset_token = AsyncMock(return_value=reset_token)
            response = await email_auth.validate_password_reset_token("token123", mock_request, db=mock_db)

    assert response.valid is True
    assert response.expires_at == reset_token.expires_at


@pytest.mark.asyncio
async def test_complete_password_reset_success():
    """Reset-password completion endpoint returns success."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
            MockSvc.return_value.reset_password_with_token = AsyncMock(return_value=True)
            response = await email_auth.complete_password_reset(
                "token123",
                ResetPasswordRequest(new_password="NewPassword123!", confirm_password="NewPassword123!"),
                mock_request,
                db=mock_db,
            )

    assert response.success is True
    assert "successful" in response.message.lower()


@pytest.mark.asyncio
async def test_admin_unlock_user_success():
    """Admin unlock endpoint returns success response."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockSvc:
        MockSvc.return_value.unlock_user_account = AsyncMock(return_value=MagicMock())
        response = await email_auth.unlock_user("user@example.com", current_user_ctx={"email": "admin@example.com"}, db=mock_db)

    assert response.success is True
    assert "unlocked" in response.message.lower()


@pytest.mark.asyncio
async def test_forgot_password_disabled_returns_403():
    """Forgot-password returns 403 when feature is disabled."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = False
        with pytest.raises(email_auth.HTTPException) as exc:
            await email_auth.forgot_password(ForgotPasswordRequest(email="user@example.com"), mock_request, db=mock_db)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_validate_password_reset_token_disabled_returns_403():
    """Validate-reset-token returns 403 when feature is disabled."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = False
        with pytest.raises(email_auth.HTTPException) as exc:
            await email_auth.validate_password_reset_token("token123", mock_request, db=mock_db)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_validate_password_reset_token_expired_maps_to_410():
    """Expired reset token maps to HTTP 410."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as mock_svc:
            mock_svc.return_value.validate_password_reset_token = AsyncMock(side_effect=AuthenticationError("This reset link has expired"))
            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.validate_password_reset_token("token123", mock_request, db=mock_db)

    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_validate_password_reset_token_invalid_maps_to_400():
    """Invalid reset token maps to HTTP 400."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as mock_svc:
            mock_svc.return_value.validate_password_reset_token = AsyncMock(side_effect=AuthenticationError("invalid token"))
            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.validate_password_reset_token("token123", mock_request, db=mock_db)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_complete_password_reset_disabled_returns_403():
    """Complete reset returns 403 when feature is disabled."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = False
        with pytest.raises(email_auth.HTTPException) as exc:
            await email_auth.complete_password_reset(
                "token123",
                ResetPasswordRequest(new_password="NewPassword123!", confirm_password="NewPassword123!"),
                mock_request,
                db=mock_db,
            )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_complete_password_reset_expired_maps_to_410():
    """Expired reset token on completion maps to HTTP 410."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as mock_svc:
            mock_svc.return_value.reset_password_with_token = AsyncMock(side_effect=AuthenticationError("expired link"))
            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.complete_password_reset(
                    "token123",
                    ResetPasswordRequest(new_password="NewPassword123!", confirm_password="NewPassword123!"),
                    mock_request,
                    db=mock_db,
                )

    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_complete_password_reset_invalid_maps_to_400():
    """Invalid reset token on completion maps to HTTP 400."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as mock_svc:
            mock_svc.return_value.reset_password_with_token = AsyncMock(side_effect=AuthenticationError("invalid token"))
            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.complete_password_reset(
                    "token123",
                    ResetPasswordRequest(new_password="NewPassword123!", confirm_password="NewPassword123!"),
                    mock_request,
                    db=mock_db,
                )

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_complete_password_reset_password_validation_maps_to_400():
    """Password validation errors map to HTTP 400."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"User-Agent": "TestAgent/1.0"}

    with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
        mock_settings.password_reset_enabled = True
        with patch("mcpgateway.routers.email_auth.EmailAuthService") as mock_svc:
            mock_svc.return_value.reset_password_with_token = AsyncMock(side_effect=PasswordValidationError("weak password"))
            with pytest.raises(email_auth.HTTPException) as exc:
                await email_auth.complete_password_reset(
                    "token123",
                    ResetPasswordRequest(new_password="NewPassword123!", confirm_password="NewPassword123!"),
                    mock_request,
                    db=mock_db,
                )

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_unlock_user_value_error_maps_to_404():
    """Admin unlock endpoint maps ValueError to HTTP 404."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    with patch("mcpgateway.routers.email_auth.EmailAuthService") as mock_svc:
        mock_svc.return_value.unlock_user_account = AsyncMock(side_effect=ValueError("not found"))
        with pytest.raises(email_auth.HTTPException) as exc:
            await email_auth.unlock_user("user@example.com", current_user_ctx={"email": "admin@example.com"}, db=mock_db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_unlock_user_generic_error_maps_to_500():
    """Admin unlock endpoint maps unexpected errors to HTTP 500."""
    # First-Party
    from mcpgateway.routers import email_auth

    mock_db = MagicMock()
    with patch("mcpgateway.routers.email_auth.EmailAuthService") as mock_svc:
        mock_svc.return_value.unlock_user_account = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(email_auth.HTTPException) as exc:
            await email_auth.unlock_user("user@example.com", current_user_ctx={"email": "admin@example.com"}, db=mock_db)

    assert exc.value.status_code == 500


def test_reset_password_request_validation_error_on_mismatch():
    """ResetPasswordRequest rejects mismatched password confirmation."""
    with pytest.raises(Exception, match="Passwords do not match"):
        ResetPasswordRequest(new_password="NewPassword123!", confirm_password="Different123!")


def test_emailuser_response_from_email_user_handles_non_int_failed_attempts():
    """EmailUserResponse.from_email_user handles non-int failed attempts safely."""
    # First-Party
    from mcpgateway.schemas import EmailUserResponse

    mock_user = MagicMock(spec=EmailUser)
    mock_user.email = "user@example.com"
    mock_user.full_name = "User"
    mock_user.is_admin = False
    mock_user.is_active = True
    mock_user.auth_provider = "local"
    mock_user.created_at = datetime.now(timezone.utc)
    mock_user.last_login = None
    mock_user.is_email_verified = MagicMock(return_value=False)
    mock_user.password_change_required = False
    mock_user.failed_login_attempts = object()
    mock_user.locked_until = "not-a-datetime"

    response = EmailUserResponse.from_email_user(mock_user)
    assert response.failed_login_attempts == 0
    assert response.locked_until is None
