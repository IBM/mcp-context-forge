# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_email_auth_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for Email Auth router.
This module tests email authentication endpoints including login with password change required.
"""

# Standard
import base64
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import status
import pytest

# First-Party
from mcpgateway.db import EmailUser
from mcpgateway.schemas import ChangePasswordRequest, AdminUserUpdateRequest, EmailRegistrationRequest, SuccessResponse
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
    async def test_create_access_token_teams_are_list_of_strings(self, mock_user_with_teams):
        """Test that create_access_token emits teams as List[str] of IDs, not List[dict].

        This is a regression test for issue #1486 where login tokens used int() casting
        on UUID team IDs and returned full team dicts instead of just IDs.
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

                # Verify teams claim is List[str], not List[dict]
                assert "teams" in captured_payload, "teams claim missing from payload"
                teams = captured_payload["teams"]

                assert isinstance(teams, list), "teams should be a list"
                assert len(teams) == 2, "should have 2 teams"

                # Each team entry should be a string (team ID), not a dict
                for team_id in teams:
                    assert isinstance(team_id, str), f"team entry should be string, got {type(team_id)}"
                    assert "-" in team_id, "team ID should be a UUID string"

                # Verify the actual team IDs are present
                assert "550e8400-e29b-41d4-a716-446655440001" in teams
                assert "550e8400-e29b-41d4-a716-446655440002" in teams

    @pytest.mark.asyncio
    async def test_create_access_token_admin_omits_teams(self):
        """Test that admin users do not have teams claim in token (unrestricted access)."""
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

                # Admin tokens should NOT have teams key (for unrestricted access)
                assert "teams" not in captured_payload, "admin tokens should omit teams key"


@pytest.mark.asyncio
async def test_register_disabled():
    # First-Party
    from mcpgateway.routers import email_auth

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"User-Agent": "TestAgent/1.0"}

    registration = EmailRegistrationRequest(email="new@example.com", password="password", full_name="New User")

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

    registration = EmailRegistrationRequest(email="new@example.com", password="password", full_name="New User")

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

    registration = EmailRegistrationRequest(email="bad@example.com", password="password", full_name="Bad User")

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

    registration = EmailRegistrationRequest(email="exists@example.com", password="password", full_name="User")

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

    user_request = EmailRegistrationRequest(email="new@example.com", password="defaultpass", full_name="New User", is_admin=False)
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
    user.full_name = "User"
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "local"
    user.created_at = datetime.now(timezone.utc)
    user.last_login = None
    user.password_change_required = True
    user.is_email_verified = MagicMock(return_value=True)

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        auth_service.get_user_by_email = AsyncMock(return_value=user)
        auth_service.validate_password = MagicMock()
        auth_service.is_last_active_admin = AsyncMock(return_value=False)
        auth_service.delete_user = AsyncMock(return_value=None)

        with patch("mcpgateway.services.argon2_service.Argon2PasswordService") as MockPasswordService:
            MockPasswordService.return_value.hash_password_async = AsyncMock(return_value="hashed")
            update_request = AdminUserUpdateRequest(email="user@example.com", password="newPassword123!", full_name="Updated", is_admin=True)

            response = await email_auth.get_user("user@example.com", current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)
            assert response.email == "user@example.com"

            response = await email_auth.update_user("user@example.com", update_request, current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)
            assert response.full_name == "Updated"
            # Verify password was hashed
            assert user.password_hash == "hashed"
            # Verify password was validated
            auth_service.validate_password.assert_called_once_with("newPassword123!")
            # Verify password_change_required was cleared
            assert user.password_change_required is False
            # Verify password_changed_at was set
            assert hasattr(user, 'password_changed_at')

            delete_response = await email_auth.delete_user("user@example.com", current_user_ctx={"db": mock_db, "email": "admin@example.com"}, db=mock_db)
            assert delete_response.success is True


@pytest.mark.asyncio
async def test_admin_update_user_without_full_name_and_is_admin():
    """Test updating only full_name field."""
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
        auth_service.get_user_by_email = AsyncMock(return_value=user)
        auth_service.is_last_active_admin = AsyncMock(return_value=False)

        update_request = AdminUserUpdateRequest()

        response = await email_auth.update_user(
            "user@example.com",
            update_request,
            current_user_ctx={"db": mock_db, "email": "admin@example.com"},
            db=mock_db
        )

        assert response.full_name == "Old Name"
        assert user.full_name == "Old Name"
        assert user.is_admin == False
        # Password should not be touched
        assert not hasattr(user, 'password_hash') or user.password_hash is None


@pytest.mark.asyncio
async def test_admin_update_user_invalid_password():
    """Test updating with invalid password raises PasswordValidationError."""
    # First-Party
    from mcpgateway.routers import email_auth

    user = MagicMock(spec=EmailUser)
    user.email = "user@example.com"
    user.full_name = "User Name"
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "local"
    user.created_at = datetime.now(timezone.utc)
    user.is_email_verified = MagicMock(return_value=True)

    mock_db = MagicMock()

    with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
        auth_service = MockAuthService.return_value
        auth_service.get_user_by_email = AsyncMock(return_value=user)
        # Simulate password validation failure
        auth_service.validate_password = MagicMock(side_effect=PasswordValidationError("Password too weak"))

        update_request = AdminUserUpdateRequest(password="thisisweak", is_admin=False)

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.update_user(
                "user@example.com",
                update_request,
                current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                db=mock_db
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
        auth_service.get_user_by_email = AsyncMock(return_value=None)

        update_request = AdminUserUpdateRequest(full_name="New Name", is_admin=False)

        with pytest.raises(email_auth.HTTPException) as excinfo:
            await email_auth.update_user(
                "nonexistent@example.com",
                update_request,
                current_user_ctx={"db": mock_db, "email": "admin@example.com"},
                db=mock_db
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
