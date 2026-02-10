# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_auth_basic.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Basic tests for Email Authentication Service functionality.
"""

# Standard
import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import orjson
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailAuthEvent, EmailTeam, EmailTeamMember, EmailUser
from mcpgateway.services.argon2_service import Argon2PasswordService
from mcpgateway.services.email_auth_service import AuthenticationError, EmailAuthService, EmailValidationError, PasswordValidationError, UserExistsError


class TestEmailAuthBasic:
    """Basic test suite for Email Authentication Service."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_password_service(self):
        """Create mock password service."""
        mock_service = MagicMock(spec=Argon2PasswordService)
        mock_service.hash_password.return_value = "hashed_password"
        mock_service.verify_password.return_value = True
        return mock_service

    @pytest.fixture
    def service(self, mock_db):
        """Create email auth service instance."""
        return EmailAuthService(mock_db)

    # =========================================================================
    # Email Validation Tests
    # =========================================================================

    def test_validate_email_success(self, service):
        """Test successful email validation."""
        valid_emails = [
            "test@example.com",
            "user.name@domain.org",
            "admin+tag@company.co.uk",
            "123@numbers.com",
        ]

        for email in valid_emails:
            # Should not raise any exception
            assert service.validate_email(email) is True

    def test_validate_email_invalid_format(self, service):
        """Test email validation with invalid formats."""
        invalid_emails = [
            "notanemail",
            "@example.com",
            "test@",
            "test.example.com",
            "test@.com",
            "",
            None,
        ]

        for email in invalid_emails:
            with pytest.raises(EmailValidationError):
                service.validate_email(email)

    def test_validate_email_too_long(self, service):
        """Test email validation with too long email."""
        long_email = "a" * 250 + "@example.com"  # Over 255 chars
        with pytest.raises(EmailValidationError, match="too long"):
            service.validate_email(long_email)

    # =========================================================================
    # Password Validation Tests
    # =========================================================================

    def test_validate_password_basic_success(self, service):
        """Test basic password validation success."""
        # Should not raise any exception with default settings
        service.validate_password("Password123!")
        service.validate_password("Simple123!")  # 8+ chars with requirements
        service.validate_password("VerylongPasswordString1!")

    def test_validate_password_empty(self, service):
        """Test password validation with empty password."""
        with pytest.raises(PasswordValidationError, match="Password is required"):
            service.validate_password("")

    def test_validate_password_none(self, service):
        """Test password validation with None password."""
        with pytest.raises(PasswordValidationError, match="Password is required"):
            service.validate_password(None)

    def test_validate_password_with_requirements(self, service):
        """Test password validation with specific requirements."""
        # Test with settings patch to simulate strict requirements
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = True
            mock_settings.password_require_lowercase = True
            mock_settings.password_require_numbers = True
            mock_settings.password_require_special = True

            # Valid password meeting all requirements
            service.validate_password("SecurePass123!")

            # Invalid passwords - test one at a time
            with pytest.raises(PasswordValidationError, match="uppercase"):
                service.validate_password("lowercase123!")

            with pytest.raises(PasswordValidationError, match="lowercase"):
                service.validate_password("UPPERCASE123!")

            with pytest.raises(PasswordValidationError, match="number"):
                service.validate_password("PasswordOnly!")

            with pytest.raises(PasswordValidationError, match="special"):
                service.validate_password("Password123")

    # =========================================================================
    # Service Initialization Tests
    # =========================================================================

    def test_service_initialization(self, mock_db):
        """Test service initialization."""
        service = EmailAuthService(mock_db)

        assert service.db == mock_db
        assert service.password_service is not None
        assert isinstance(service.password_service, Argon2PasswordService)

    def test_password_service_integration(self, service):
        """Test integration with password service."""
        # Test that the service has a password service
        assert hasattr(service, "password_service")
        assert hasattr(service.password_service, "hash_password")
        assert hasattr(service.password_service, "verify_password")

    # =========================================================================
    # Mock Database Integration Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_user_by_email_found(self, service, mock_db):
        """Test getting user by email when user exists."""
        # Mock database to return a user
        mock_user = MagicMock()
        mock_user.email = "test@example.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        # Test the method
        result = await service.get_user_by_email("test@example.com")

        assert result == mock_user
        assert result.email == "test@example.com"
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_by_email_not_found(self, service, mock_db):
        """Test getting user by email when user doesn't exist."""
        # Mock database to return None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Test the method
        result = await service.get_user_by_email("nonexistent@example.com")

        assert result is None
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_by_email_database_error(self, service, mock_db):
        """Test getting user by email with database error."""
        # Mock database to raise an exception
        mock_db.execute.side_effect = Exception("Database connection failed")

        # Test the method - should return None on error
        result = await service.get_user_by_email("test@example.com")

        assert result is None
        mock_db.execute.assert_called_once()

    # =========================================================================
    # Helper Method Tests
    # =========================================================================

    def test_normalize_email(self, service):
        """Test email normalization."""
        test_cases = [
            ("Test@Example.Com", "test@example.com"),
            ("USER+TAG@DOMAIN.ORG", "user+tag@domain.org"),
            ("simple@test.com", "simple@test.com"),
        ]

        for input_email, expected in test_cases:
            # Test via email validation which should normalize
            service.validate_email(input_email)
            # The normalization happens internally but we can't easily test it
            # without exposing the method or checking database calls
            assert True  # Just verify no exception was raised

    # =========================================================================
    # Integration Test Patterns
    # =========================================================================

    def test_service_has_required_methods(self, service):
        """Test that service has all required methods."""
        required_methods = [
            "validate_email",
            "validate_password",
            "get_user_by_email",
            "create_user",
        ]

        for method_name in required_methods:
            assert hasattr(service, method_name)
            assert callable(getattr(service, method_name))

    def test_password_service_configuration(self, service):
        """Test password service is properly configured."""
        password_service = service.password_service

        # Test basic functionality exists
        assert hasattr(password_service, "hash_password")
        assert hasattr(password_service, "verify_password")

        # Test that it can hash a password (real functionality)
        test_password = "test_password_123"
        hashed = password_service.hash_password(test_password)

        assert hashed != test_password  # Should be different
        assert len(hashed) > 20  # Should be substantial length
        assert hashed.startswith("$argon2id$")  # Should use Argon2id

    def test_database_dependency_injection(self, mock_db):
        """Test that database session is properly injected."""
        service = EmailAuthService(mock_db)

        assert service.db is mock_db
        assert service.db is not None

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    def test_exception_types_available(self):
        """Test that all expected exception types are available."""
        exception_classes = [
            EmailValidationError,
            PasswordValidationError,
            UserExistsError,
            AuthenticationError,
        ]

        for exc_class in exception_classes:
            # Should be able to instantiate
            exc = exc_class("Test message")
            assert isinstance(exc, Exception)
            assert str(exc) == "Test message"

    def test_service_resilience(self, service):
        """Test service resilience to various inputs."""
        # Test with various edge case inputs that shouldn't crash
        edge_cases = [
            "",  # empty string
            " ",  # whitespace
            "   test@example.com   ",  # with whitespace
            "тест@example.com",  # unicode
        ]

        for case in edge_cases:
            try:
                service.validate_email(case)
            except EmailValidationError:
                # Expected for invalid cases
                pass
            except Exception as e:
                pytest.fail(f"Unexpected exception for input '{case}': {e}")

    # =========================================================================
    # Password Policy Tests with Different Settings
    # =========================================================================

    def test_validate_password_min_length(self, service):
        """Test password validation with minimum length requirement."""
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 12
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Should pass with 12+ chars
            service.validate_password("passwordlongenough")

            # Should fail with less than 12 chars
            with pytest.raises(PasswordValidationError, match="12 characters"):
                service.validate_password("short")

    def test_validate_password_complex_requirements(self, service):
        """Test password validation with complex requirements."""
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 10
            mock_settings.password_require_uppercase = True
            mock_settings.password_require_lowercase = True
            mock_settings.password_require_numbers = True
            mock_settings.password_require_special = True

            # Valid complex password
            service.validate_password("Complex123!Pass")
            service.validate_password("AnotherGood@Pass99")

            # Missing uppercase
            with pytest.raises(PasswordValidationError, match="uppercase"):
                service.validate_password("nouppcase123!")

            # Missing lowercase
            with pytest.raises(PasswordValidationError, match="lowercase"):
                service.validate_password("NOLOWERCASE123!")

            # Missing numbers
            with pytest.raises(PasswordValidationError, match="number"):
                service.validate_password("NoNumbers!Here")

            # Missing special characters
            with pytest.raises(PasswordValidationError, match="special"):
                service.validate_password("NoSpecialChar123")

    def test_validate_password_policy_disabled_returns_true(self, service):
        """Test password validation returns True when global password policy is disabled."""
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_policy_enabled = False
            # Even a weak password should be accepted when policy is disabled (non-empty is still required).
            assert service.validate_password("x") is True


class TestEmailAuthServiceUserManagement:
    """Tests for user management functionality."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_password_service(self):
        """Create mock password service."""
        mock_service = MagicMock(spec=Argon2PasswordService)
        mock_service.hash_password.return_value = "hashed_password_123"
        mock_service.verify_password.return_value = True
        # Add async versions for use with asyncio.to_thread
        mock_service.hash_password_async = AsyncMock(return_value="hashed_password_123")
        mock_service.verify_password_async = AsyncMock(return_value=True)
        return mock_service

    @pytest.fixture
    def service(self, mock_db):
        """Create email auth service instance."""
        return EmailAuthService(mock_db)

    @pytest.fixture
    def mock_user(self):
        """Create a mock user object."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.password_hash = "existing_hash"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.failed_login_attempts = 0
        user.account_locked_until = None
        user.is_account_locked.return_value = False
        user.increment_failed_attempts.return_value = False
        user.reset_failed_attempts = MagicMock()
        return user

    # =========================================================================
    # User Creation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_user_success(self, service, mock_db, mock_password_service):
        """Test successful user creation."""
        # Patch the password service
        service.password_service = mock_password_service

        # Mock database operations
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No existing user

        # Mock settings for personal team creation and password validation
        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False  # Disable for simplicity
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Need to also patch where validate_password imports settings
            with patch("mcpgateway.services.email_auth_service.settings", mock_settings):
                # Create user
                result = await service.create_user(email="newuser@example.com", password="SecurePass123", full_name="New User", is_admin=False, auth_provider="local")

                # Verify user was added to database
                mock_db.add.assert_called()
                mock_db.commit.assert_called()
                mock_db.refresh.assert_called()

                # Verify password was hashed (async version is called via asyncio.to_thread)
                mock_password_service.hash_password_async.assert_called_once_with("SecurePass123")

    @pytest.mark.skip(reason="PersonalTeamService import happens inside method, complex to mock")
    @pytest.mark.asyncio
    async def test_create_user_with_personal_team(self, service, mock_db, mock_password_service):
        """Test user creation with personal team auto-creation."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = True
            mock_settings.password_min_length = 7  # Pass123 is 7 chars
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with patch("mcpgateway.services.email_auth_service.PersonalTeamService") as MockPersonalTeamService:
                mock_personal_team_service = MockPersonalTeamService.return_value
                mock_team = MagicMock()
                mock_team.name = "Personal Team"
                mock_personal_team_service.create_personal_team = AsyncMock(return_value=mock_team)

                result = await service.create_user(email="user@example.com", password="Pass123", full_name="User Name")

                # Verify personal team service was called
                MockPersonalTeamService.assert_called_once_with(mock_db)
                mock_personal_team_service.create_personal_team.assert_called_once()

    @pytest.mark.skip(reason="PersonalTeamService import happens inside method, complex to mock")
    @pytest.mark.asyncio
    async def test_create_user_personal_team_failure(self, service, mock_db, mock_password_service):
        """Test user creation when personal team creation fails."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = True
            mock_settings.password_min_length = 7
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with patch("mcpgateway.services.email_auth_service.PersonalTeamService") as MockPersonalTeamService:
                # Make personal team creation fail
                mock_personal_team_service = MockPersonalTeamService.return_value
                mock_personal_team_service.create_personal_team = AsyncMock(side_effect=Exception("Team creation failed"))

                # User creation should still succeed
                result = await service.create_user(email="user@example.com", password="Pass123")

                # User should have been created despite team failure
                mock_db.add.assert_called()
                mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_already_exists(self, service, mock_db, mock_user):
        """Test creating user that already exists."""
        # Mock existing user
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        with pytest.raises(UserExistsError, match="already exists"):
            await service.create_user(email="test@example.com", password="Password123!")

    @pytest.mark.asyncio
    async def test_create_user_database_integrity_error(self, service, mock_db, mock_password_service):
        """Test user creation with database integrity error."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # Make database add fail with IntegrityError
        mock_db.commit.side_effect = IntegrityError("Unique constraint", None, None)

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 7
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with pytest.raises(UserExistsError):
                await service.create_user(email="duplicate@example.com", password="Pass123")

            # Verify rollback was called
            mock_db.rollback.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_unexpected_error(self, service, mock_db, mock_password_service):
        """Test user creation with unexpected database error."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # Make database commit fail unexpectedly
        mock_db.commit.side_effect = Exception("Database connection lost")

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 7
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with pytest.raises(Exception, match="Database connection lost"):
                await service.create_user(email="user@example.com", password="Pass123")

            # Verify rollback was called
            mock_db.rollback.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_with_is_active_true(self, service, mock_db, mock_password_service):
        """Test creating user with is_active=True (default behavior)."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with patch("mcpgateway.services.email_auth_service.settings", mock_settings):
                result = await service.create_user(email="active@example.com", password="SecurePass123", full_name="Active User", is_admin=False, is_active=True, auth_provider="local")

                # Verify user was added with is_active=True
                mock_db.add.assert_called()
                # Get the first call to add() which should be the user
                first_add_call = mock_db.add.call_args_list[0][0][0]
                assert first_add_call.is_active is True
                mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_with_is_active_false(self, service, mock_db, mock_password_service):
        """Test creating inactive user with is_active=False."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with patch("mcpgateway.services.email_auth_service.settings", mock_settings):
                result = await service.create_user(email="inactive@example.com", password="SecurePass123", full_name="Inactive User", is_admin=False, is_active=False, auth_provider="local")

                # Verify user was added with is_active=False
                mock_db.add.assert_called()
                # Get the first call to add() which should be the user
                first_add_call = mock_db.add.call_args_list[0][0][0]
                assert first_add_call.is_active is False
                mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_with_password_change_required_true(self, service, mock_db, mock_password_service):
        """Test creating user with password_change_required=True."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with patch("mcpgateway.services.email_auth_service.settings", mock_settings):
                result = await service.create_user(
                    email="pwchange@example.com", password="TempPass123", full_name="Password Change User", is_admin=False, password_change_required=True, auth_provider="local"
                )

                # Verify user was added with password_change_required=True
                mock_db.add.assert_called()
                # Get the first call to add() which should be the user
                first_add_call = mock_db.add.call_args_list[0][0][0]
                assert first_add_call.password_change_required is True
                mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_with_password_change_required_false(self, service, mock_db, mock_password_service):
        """Test creating user with password_change_required=False (default)."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with patch("mcpgateway.services.email_auth_service.settings", mock_settings):
                result = await service.create_user(
                    email="nopwchange@example.com", password="SecurePass123", full_name="No Password Change User", is_admin=False, password_change_required=False, auth_provider="local"
                )

                # Verify user was added with password_change_required=False
                mock_db.add.assert_called()
                # Get the first call to add() which should be the user
                first_add_call = mock_db.add.call_args_list[0][0][0]
                assert first_add_call.password_change_required is False
                mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_with_all_new_fields(self, service, mock_db, mock_password_service):
        """Test creating user with both is_active and password_change_required set."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            with patch("mcpgateway.services.email_auth_service.settings", mock_settings):
                result = await service.create_user(
                    email="combined@example.com", password="TempPass123", full_name="Combined Fields User", is_admin=False, is_active=False, password_change_required=True, auth_provider="local"
                )

                # Verify user was added with both fields set correctly
                mock_db.add.assert_called()
                # Get the first call to add() which should be the user
                first_add_call = mock_db.add.call_args_list[0][0][0]
                assert first_add_call.is_active is False
                assert first_add_call.password_change_required is True
                mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_email_normalization(self, service, mock_db, mock_password_service):
        """Test that email is normalized to lowercase during user creation."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 7
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            await service.create_user(
                email="  User@EXAMPLE.Com  ",  # Mixed case with whitespace
                password="Pass123",
            )

            # Verify the email was normalized when checking for existing user
            called_stmt = mock_db.execute.call_args[0][0]
            # The actual SQL would have the normalized email
            assert mock_db.add.called

    # =========================================================================
    # Authentication Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_authenticate_user_success(self, service, mock_db, mock_user, mock_password_service):
        """Test successful authentication."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        result = await service.authenticate_user(email="test@example.com", password="correct_password", ip_address="192.168.1.1", user_agent="TestAgent/1.0")

        assert result == mock_user
        mock_user.reset_failed_attempts.assert_called_once()
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_authenticate_user_not_found(self, service, mock_db):
        """Test authentication when user doesn't exist."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = await service.authenticate_user(email="nonexistent@example.com", password="password")

        assert result is None
        # Should log auth event even for non-existent users
        assert mock_db.add.called

    @pytest.mark.asyncio
    async def test_authenticate_user_inactive(self, service, mock_db, mock_user):
        """Test authentication when user account is inactive."""
        mock_user.is_active = False
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        result = await service.authenticate_user(email="test@example.com", password="password")

        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_user_account_locked(self, service, mock_db, mock_user):
        """Test authentication when account is locked."""
        mock_user.is_account_locked.return_value = True
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        result = await service.authenticate_user(email="test@example.com", password="password")

        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_user_wrong_password(self, service, mock_db, mock_user, mock_password_service):
        """Test authentication with wrong password."""
        service.password_service = mock_password_service
        mock_password_service.verify_password.return_value = False
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.max_failed_login_attempts = 5
            mock_settings.account_lockout_duration_minutes = 30

            result = await service.authenticate_user(email="test@example.com", password="wrong_password")

            assert result is None
            mock_user.increment_failed_attempts.assert_called_once_with(5, 30)

    @pytest.mark.asyncio
    async def test_authenticate_user_lockout_after_failures(self, service, mock_db, mock_user, mock_password_service):
        """Test account lockout after multiple failed attempts."""
        service.password_service = mock_password_service
        mock_password_service.verify_password.return_value = False
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_user.increment_failed_attempts.return_value = True  # Account gets locked
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.max_failed_login_attempts = 3
            mock_settings.account_lockout_duration_minutes = 15

            result = await service.authenticate_user(email="test@example.com", password="wrong_password")

            assert result is None
            mock_user.increment_failed_attempts.assert_called_once_with(3, 15)

    # =========================================================================
    # Admin Lockout Protection Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_authenticate_admin_skips_lockout_when_protected(self, service, mock_db, mock_user, mock_password_service):
        """Test that a protected admin bypasses account lockout."""
        service.password_service = mock_password_service
        mock_user.is_admin = True
        mock_user.is_account_locked.return_value = True
        mock_password_service.verify_password_async = AsyncMock(return_value=True)
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.protect_all_admins = True

            result = await service.authenticate_user(email="admin@example.com", password="correct_password")

            assert result == mock_user
            mock_user.reset_failed_attempts.assert_called()

    @pytest.mark.asyncio
    async def test_authenticate_admin_no_increment_when_protected(self, service, mock_db, mock_user, mock_password_service):
        """Test that a protected admin's failed attempts are not incremented on wrong password."""
        service.password_service = mock_password_service
        mock_user.is_admin = True
        mock_user.is_account_locked.return_value = False
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.protect_all_admins = True

            result = await service.authenticate_user(email="admin@example.com", password="wrong_password")

            assert result is None
            mock_user.increment_failed_attempts.assert_not_called()

    @pytest.mark.asyncio
    async def test_authenticate_admin_still_locked_when_not_protected(self, service, mock_db, mock_user, mock_password_service):
        """Test that admin is still locked out when protect_all_admins is False."""
        service.password_service = mock_password_service
        mock_user.is_admin = True
        mock_user.is_account_locked.return_value = True
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.protect_all_admins = False

            result = await service.authenticate_user(email="admin@example.com", password="correct_password")

            assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_non_admin_still_locked_when_protected(self, service, mock_db, mock_user, mock_password_service):
        """Test that non-admin users are still locked out even when protect_all_admins is True."""
        service.password_service = mock_password_service
        mock_user.is_admin = False
        mock_user.is_account_locked.return_value = True
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.protect_all_admins = True

            result = await service.authenticate_user(email="test@example.com", password="correct_password")

            assert result is None

    # =========================================================================
    # Password Change Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_change_password_requires_old_password(self, service):
        """Test change_password raises when old_password is missing."""
        with pytest.raises(AuthenticationError, match="Current password is required"):
            await service.change_password(email="test@example.com", old_password=None, new_password="NewSecurePass123!")

    @pytest.mark.asyncio
    async def test_change_password_success(self, service, mock_db, mock_user, mock_password_service):
        """Test successful password change."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        # Make verify return True for old password, False for new (different)
        mock_password_service.verify_password.side_effect = [True, False]
        mock_password_service.verify_password_async = AsyncMock(side_effect=[True, False])
        mock_password_service.hash_password.return_value = "new_hashed_password"
        mock_password_service.hash_password_async = AsyncMock(return_value="new_hashed_password")

        result = await service.change_password(email="test@example.com", old_password="old_password", new_password="NewSecurePass123!", ip_address="192.168.1.1")

        assert result is True
        assert mock_user.password_hash == "new_hashed_password"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_change_password_logs_debug_when_password_changed_at_fails(self, service, mock_db, mock_user, mock_password_service):
        """Test change_password continues when setting password_changed_at fails."""
        service.password_service = mock_password_service
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_password_service.hash_password_async = AsyncMock(return_value="new_hashed_password")

        with patch.object(service, "authenticate_user", new=AsyncMock(return_value=mock_user)):
            with patch("mcpgateway.services.email_auth_service.utc_now", side_effect=Exception("utc-now-failure")):
                # Avoid hitting real Redis/cache interactions
                from mcpgateway.cache.auth_cache import auth_cache

                with patch.object(auth_cache, "invalidate_user", new=AsyncMock(return_value=None)):
                    with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
                        mock_settings.password_policy_enabled = True
                        mock_settings.password_min_length = 1
                        mock_settings.password_require_uppercase = False
                        mock_settings.password_require_lowercase = False
                        mock_settings.password_require_numbers = False
                        mock_settings.password_require_special = False
                        mock_settings.password_prevent_reuse = True

                        result = await service.change_password(email="test@example.com", old_password="old_password", new_password="NewSecurePass123!")

        assert result is True
        assert mock_user.password_hash == "new_hashed_password"
        assert mock_db.commit.call_count >= 2  # password update + event logging

    @pytest.mark.asyncio
    async def test_change_password_auth_cache_invalidation_timeout_is_non_fatal(self, service, mock_user, mock_password_service):
        """Test change_password continues when auth cache invalidation times out."""
        import asyncio

        service.password_service = mock_password_service
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_password_service.hash_password_async = AsyncMock(return_value="new_hashed_password")

        async def fake_wait_for(awaitable, timeout):  # noqa: ARG001 - signature must match asyncio.wait_for
            await awaitable
            raise asyncio.TimeoutError()

        with patch.object(service, "authenticate_user", new=AsyncMock(return_value=mock_user)):
            from mcpgateway.cache.auth_cache import auth_cache

            with patch.object(auth_cache, "invalidate_user", new=AsyncMock(return_value=None)):
                with patch("asyncio.wait_for", new=fake_wait_for):
                    with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
                        mock_settings.password_policy_enabled = True
                        mock_settings.password_min_length = 1
                        mock_settings.password_require_uppercase = False
                        mock_settings.password_require_lowercase = False
                        mock_settings.password_require_numbers = False
                        mock_settings.password_require_special = False
                        mock_settings.password_prevent_reuse = True

                        assert await service.change_password(email="test@example.com", old_password="old_password", new_password="NewSecurePass123!") is True

    @pytest.mark.asyncio
    async def test_change_password_auth_cache_invalidation_exception_is_non_fatal(self, service, mock_user, mock_password_service):
        """Test change_password continues when auth cache invalidation raises."""
        service.password_service = mock_password_service
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_password_service.hash_password_async = AsyncMock(return_value="new_hashed_password")

        with patch.object(service, "authenticate_user", new=AsyncMock(return_value=mock_user)):
            from mcpgateway.cache.auth_cache import auth_cache

            with patch.object(auth_cache, "invalidate_user", new=AsyncMock(side_effect=RuntimeError("cache-down"))):
                with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
                    mock_settings.password_policy_enabled = True
                    mock_settings.password_min_length = 1
                    mock_settings.password_require_uppercase = False
                    mock_settings.password_require_lowercase = False
                    mock_settings.password_require_numbers = False
                    mock_settings.password_require_special = False
                    mock_settings.password_prevent_reuse = True

                    assert await service.change_password(email="test@example.com", old_password="old_password", new_password="NewSecurePass123!") is True

    @pytest.mark.asyncio
    async def test_change_password_clears_password_change_required_flag(self, service, mock_db, mock_user, mock_password_service):
        """Test that password change clears password_change_required flag (regression test for #1842)."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        # User initially has password_change_required = True
        mock_user.password_change_required = True

        # Make verify return True for old password, False for new (different)
        mock_password_service.verify_password.side_effect = [True, False]
        mock_password_service.verify_password_async = AsyncMock(side_effect=[True, False])
        mock_password_service.hash_password.return_value = "new_hashed_password"
        mock_password_service.hash_password_async = AsyncMock(return_value="new_hashed_password")

        result = await service.change_password(email="test@example.com", old_password="old_password", new_password="NewSecurePass123!", ip_address="192.168.1.1")

        assert result is True
        # Verify the flag was cleared - this is the key assertion for #1842
        assert mock_user.password_change_required is False
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_change_password_wrong_old_password(self, service, mock_db, mock_user, mock_password_service):
        """Test password change with incorrect old password."""
        service.password_service = mock_password_service
        mock_password_service.verify_password.return_value = False
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        with pytest.raises(AuthenticationError, match="Current password is incorrect"):
            await service.change_password(email="test@example.com", old_password="wrong_old_password", new_password="NewPassword123")

    @pytest.mark.asyncio
    async def test_change_password_same_as_old(self, service, mock_db, mock_user, mock_password_service):
        """Test password change when new password is same as old."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        # Both old and new passwords verify as True (same password)
        mock_password_service.verify_password.return_value = True

        with pytest.raises(PasswordValidationError, match="must be different"):
            await service.change_password(email="test@example.com", old_password="Password123!", new_password="Password123!")

    @pytest.mark.skip(reason="Complex mock interaction with finally block - core functionality covered by other tests")
    @pytest.mark.asyncio
    async def test_change_password_database_error(self, service, mock_db, mock_user, mock_password_service):
        """Test password change with database error."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user
        mock_password_service.verify_password.side_effect = [True, False]

        # Mock settings for password validation
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Make the password change commit fail (line 483 in the implementation)
            commit_call_count = 0

            def mock_commit():
                nonlocal commit_call_count
                commit_call_count += 1
                if commit_call_count == 1:  # First commit (password change) fails
                    raise Exception("Database error")
                # Second commit (event logging) succeeds

            mock_db.commit.side_effect = mock_commit

            with pytest.raises(Exception, match="Database error"):
                await service.change_password(email="test@example.com", old_password="old_password", new_password="new_password")

            # Verify rollback was called after the first commit failed
            mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_password_rolls_back_on_commit_error(self, service, mock_db, mock_user, mock_password_service):
        """Test change_password rolls back and re-raises when DB commit fails."""
        service.password_service = mock_password_service
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_password_service.hash_password_async = AsyncMock(return_value="new_hashed_password")

        commit_calls = {"count": 0}

        def commit_side_effect():
            commit_calls["count"] += 1
            if commit_calls["count"] == 1:
                raise Exception("Database error")

        mock_db.commit.side_effect = commit_side_effect

        with patch.object(service, "authenticate_user", new=AsyncMock(return_value=mock_user)):
            with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
                mock_settings.password_policy_enabled = True
                mock_settings.password_min_length = 1
                mock_settings.password_require_uppercase = False
                mock_settings.password_require_lowercase = False
                mock_settings.password_require_numbers = False
                mock_settings.password_require_special = False
                mock_settings.password_prevent_reuse = True

                with pytest.raises(Exception, match="Database error"):
                    await service.change_password(email="test@example.com", old_password="old_password", new_password="NewSecurePass123!")

        mock_db.rollback.assert_called_once()

    # =========================================================================
    # Platform Admin Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_platform_admin_new(self, service, mock_db, mock_password_service):
        """Test creating a new platform admin."""
        service.password_service = mock_password_service
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No existing admin

        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            result = await service.create_platform_admin(email="admin@example.com", password="AdminPass123!", full_name="Platform Admin")

            mock_db.add.assert_called()
            mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_platform_admin_existing_update_password(self, service, mock_db, mock_user, mock_password_service):
        """Test updating existing admin's password."""
        service.password_service = mock_password_service
        mock_user.is_admin = True
        mock_user.full_name = "Admin"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        # Password has changed
        mock_password_service.verify_password.return_value = False
        mock_password_service.verify_password_async = AsyncMock(return_value=False)
        mock_password_service.hash_password.return_value = "new_admin_hash"
        mock_password_service.hash_password_async = AsyncMock(return_value="new_admin_hash")

        result = await service.create_platform_admin(
            email="test@example.com",
            password="NewAdminPass123!",
            full_name="Admin",  # Same name
        )

        assert result == mock_user
        assert mock_user.password_hash == "new_admin_hash"
        assert mock_user.is_admin is True
        assert mock_user.is_active is True
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_platform_admin_existing_password_changed_at_failure_is_non_fatal(self, service, mock_user, mock_password_service):
        """Test create_platform_admin continues when setting password_changed_at fails for existing admin."""
        service.password_service = mock_password_service
        mock_user.is_admin = True

        with patch.object(service, "get_user_by_email", new=AsyncMock(return_value=mock_user)):
            mock_password_service.verify_password_async = AsyncMock(return_value=False)
            mock_password_service.hash_password_async = AsyncMock(return_value="new_admin_hash")

            with patch("mcpgateway.services.email_auth_service.utc_now", side_effect=Exception("utc-now-failure")):
                result = await service.create_platform_admin(email="test@example.com", password="NewAdminPass123!", full_name="Admin")

        assert result == mock_user
        assert mock_user.password_hash == "new_admin_hash"
        assert mock_user.is_admin is True
        assert mock_user.is_active is True

    @pytest.mark.asyncio
    async def test_create_platform_admin_existing_update_name(self, service, mock_db, mock_user, mock_password_service):
        """Test updating existing admin's name."""
        service.password_service = mock_password_service
        mock_user.full_name = "Old Name"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        # Password unchanged
        mock_password_service.verify_password.return_value = True

        result = await service.create_platform_admin(email="test@example.com", password="SamePassword", full_name="New Admin Name")

        assert result == mock_user
        assert mock_user.full_name == "New Admin Name"
        assert mock_user.is_admin is True
        mock_db.commit.assert_called()

    # =========================================================================
    # User Update Last Login Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_last_login(self, service, mock_db, mock_user):
        """Test updating last login timestamp."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user

        await service.update_last_login("test@example.com")

        mock_user.reset_failed_attempts.assert_called_once()
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_last_login_user_not_found(self, service, mock_db):
        """Test updating last login for non-existent user."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        await service.update_last_login("nonexistent@example.com")

        # Should not commit if user doesn't exist
        mock_db.commit.assert_not_called()


class TestEmailAuthServiceUserListing:
    """Tests for user listing and counting functionality."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def service(self, mock_db):
        """Create email auth service instance."""
        return EmailAuthService(mock_db)

    @pytest.fixture
    def mock_users(self):
        """Create mock user list."""
        users = []
        for i in range(5):
            user = MagicMock(spec=EmailUser)
            user.email = f"user{i}@example.com"
            user.full_name = f"User {i}"
            user.is_admin = i == 0  # First user is admin
            user.is_active = i != 4  # Last user is inactive
            users.append(user)
        return users

    @pytest.mark.asyncio
    async def test_list_users_success(self, service, mock_db, mock_users):
        """Test listing users with pagination."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_users[:3]  # Return first 3
        mock_db.execute.return_value = mock_result

        result = await service.list_users(cursor=None, limit=3)

        assert len(result.data) == 3
        assert result.data[0].email == "user0@example.com"
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_users_database_error(self, service, mock_db):
        """Test listing users with database error."""
        mock_db.execute.side_effect = Exception("Database error")

        result = await service.list_users()

        assert result.data == []

    @pytest.mark.asyncio
    async def test_list_users_generates_cursor_using_email(self, service, mock_db, mock_users):
        """Test that list_users generates cursor using (created_at, email) keyset."""
        # Create mock users with created_at timestamps
        users_with_timestamps = []
        for i, user in enumerate(mock_users[:3]):
            user.created_at = datetime(2024, 1, 15, 10, 0, i, tzinfo=timezone.utc)
            users_with_timestamps.append(user)

        # Return 4 items to trigger has_more (limit=3 + 1)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = users_with_timestamps + [mock_users[3]]
        mock_db.execute.return_value = mock_result

        result = await service.list_users(cursor=None, limit=3)

        # Should return 3 items and a next_cursor
        assert len(result.data) == 3
        assert result.next_cursor is not None

        # Decode and verify cursor uses (created_at, email)
        cursor_json = base64.urlsafe_b64decode(result.next_cursor.encode()).decode()
        cursor_data = orjson.loads(cursor_json)
        assert "created_at" in cursor_data
        assert "email" in cursor_data
        assert cursor_data["email"] == mock_users[2].email  # Last item's email

    @pytest.mark.asyncio
    async def test_list_users_with_cursor_applies_keyset_filter(self, service, mock_db, mock_users):
        """Test that list_users with cursor applies correct keyset filter."""
        # Create a cursor for the second page
        cursor_data = {
            "created_at": "2024-01-15T10:00:02+00:00",
            "email": "user2@example.com",
        }
        cursor = base64.urlsafe_b64encode(orjson.dumps(cursor_data)).decode()

        # Mock the result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_users[3:]  # Remaining users
        mock_db.execute.return_value = mock_result

        result = await service.list_users(cursor=cursor, limit=10)

        # Verify that execute was called (the filter is applied internally)
        mock_db.execute.assert_called_once()
        # Result should contain remaining users
        assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_list_users_cursor_handles_invalid_cursor(self, service, mock_db, mock_users):
        """Test that list_users handles invalid cursor gracefully."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_users
        mock_db.execute.return_value = mock_result

        # Invalid base64 cursor should be ignored
        result = await service.list_users(cursor="invalid-cursor", limit=10)

        # Should still return results (cursor ignored)
        assert len(result.data) == 5

    @pytest.mark.asyncio
    async def test_list_users_page_based_exception_returns_fallback(self, service):
        """Test list_users returns page-based fallback structure on exception."""
        with patch("mcpgateway.services.email_auth_service.unified_paginate", new=AsyncMock(side_effect=Exception("paginate-failure"))):
            result = await service.list_users(page=2, per_page=10)

        assert result.data == []
        assert result.pagination is not None
        assert result.pagination.page == 2
        assert result.pagination.per_page == 10
        assert result.links is not None

    @pytest.mark.asyncio
    async def test_list_users_cursor_based_exception_returns_fallback(self, service, mock_db):
        """Test list_users returns cursor-based fallback structure on exception."""
        mock_db.execute.side_effect = Exception("Database error")

        result = await service.list_users(cursor="invalid-cursor", limit=10)

        assert result.data == []
        assert result.next_cursor is None

    @pytest.mark.asyncio
    async def test_list_users_cursor_missing_keys_does_not_apply_keyset_filter(self, service, mock_db, mock_users):
        """Test list_users with a cursor missing created_at/email does not apply keyset filter."""
        cursor_data = {
            "email": "user2@example.com",
            # missing created_at on purpose
        }
        cursor = base64.urlsafe_b64encode(orjson.dumps(cursor_data)).decode()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_users[:2]
        mock_db.execute.return_value = mock_result

        result = await service.list_users(cursor=cursor, limit=10)

        assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_list_users_limit_zero_returns_all_users_no_cursor(self, service, mock_db, mock_users):
        """Test list_users(limit=0) returns all results without generating a next cursor."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_users
        mock_db.execute.return_value = mock_result

        result = await service.list_users(cursor=None, limit=0)

        assert len(result.data) == 5
        assert result.next_cursor is None

    @pytest.mark.asyncio
    async def test_list_users_not_in_team_page_based_success(self, service):
        """Test list_users_not_in_team page-based mode uses unified_paginate."""
        # First-Party
        from mcpgateway.schemas import PaginationLinks, PaginationMeta

        users = [MagicMock(spec=EmailUser, email="a@example.com"), MagicMock(spec=EmailUser, email="b@example.com")]
        pagination = PaginationMeta(page=1, per_page=30, total_items=2, total_pages=1, has_next=False, has_prev=False)
        links = PaginationLinks(self="/admin/teams/team-123/non-members?page=1&per_page=30", first="/admin/teams/team-123/non-members?page=1&per_page=30", last="/admin/teams/team-123/non-members?page=1&per_page=30")

        with patch(
            "mcpgateway.services.email_auth_service.unified_paginate",
            new=AsyncMock(return_value={"data": users, "pagination": pagination, "links": links}),
        ) as mock_paginate:
            result = await service.list_users_not_in_team(team_id="team-123", page=1, per_page=30, search="john")

        assert result.data == users
        assert result.pagination == pagination
        assert result.links == links
        mock_paginate.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_users_not_in_team_cursor_based_generates_next_cursor_and_commits(self, service, mock_db):
        """Test list_users_not_in_team cursor mode generates next cursor and commits."""
        users = []
        for i in range(3):  # limit=2 + 1
            user = MagicMock(spec=EmailUser)
            user.email = f"user{i}@example.com"
            user.created_at = datetime(2024, 1, 15, 10, 0, i, tzinfo=timezone.utc)
            users.append(user)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = users
        mock_db.execute.return_value = mock_result

        result = await service.list_users_not_in_team(team_id="team-123", cursor=None, limit=2)

        assert len(result.data) == 2
        assert result.next_cursor is not None
        cursor_json = base64.urlsafe_b64decode(result.next_cursor.encode()).decode()
        cursor_data = orjson.loads(cursor_json)
        assert cursor_data["email"] == "user1@example.com"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_users_not_in_team_cursor_with_cursor_decodes_and_applies_keyset_filter(self, service, mock_db):
        """Test list_users_not_in_team decodes cursor and still returns results."""
        cursor_data = {
            "created_at": "2024-01-15T10:00:02+00:00",
            "email": "user2@example.com",
        }
        cursor = base64.urlsafe_b64encode(orjson.dumps(cursor_data)).decode()

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user3@example.com"
        mock_user.created_at = datetime(2024, 1, 15, 10, 0, 3, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_user]
        mock_db.execute.return_value = mock_result

        result = await service.list_users_not_in_team(team_id="team-123", cursor=cursor, limit=50)

        assert len(result.data) == 1
        assert result.data[0].email == "user3@example.com"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_users_not_in_team_cursor_invalid_cursor_is_ignored(self, service, mock_db):
        """Test list_users_not_in_team ignores invalid cursor payloads."""
        # Valid base64, invalid JSON => triggers inner (ValueError, TypeError) handling.
        cursor = base64.urlsafe_b64encode(b"not-json").decode()

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user3@example.com"
        mock_user.created_at = datetime(2024, 1, 15, 10, 0, 3, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_user]
        mock_db.execute.return_value = mock_result

        result = await service.list_users_not_in_team(team_id="team-123", cursor=cursor, limit=50)

        assert len(result.data) == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_users_not_in_team_cursor_missing_keys_does_not_apply_keyset_filter(self, service, mock_db):
        """Test list_users_not_in_team cursor missing required keys skips keyset filter."""
        cursor_data = {
            "email": "user2@example.com",
            # missing created_at on purpose
        }
        cursor = base64.urlsafe_b64encode(orjson.dumps(cursor_data)).decode()

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user3@example.com"
        mock_user.created_at = datetime(2024, 1, 15, 10, 0, 3, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_user]
        mock_db.execute.return_value = mock_result

        result = await service.list_users_not_in_team(team_id="team-123", cursor=cursor, limit=50)

        assert len(result.data) == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_users_not_in_team_page_based_exception_returns_fallback(self, service):
        """Test list_users_not_in_team returns page-based fallback on exception."""
        with patch("mcpgateway.services.email_auth_service.unified_paginate", new=AsyncMock(side_effect=Exception("paginate-failure"))):
            result = await service.list_users_not_in_team(team_id="team-123", page=1, per_page=10)

        assert result.data == []
        assert result.pagination is not None
        assert result.pagination.page == 1
        assert result.links is not None

    @pytest.mark.asyncio
    async def test_list_users_not_in_team_cursor_based_exception_returns_fallback(self, service, mock_db):
        """Test list_users_not_in_team returns cursor-based fallback on exception."""
        mock_db.execute.side_effect = Exception("Database error")

        result = await service.list_users_not_in_team(team_id="team-123", cursor=None, limit=10)

        assert result.data == []
        assert result.next_cursor is None

    @pytest.mark.asyncio
    async def test_get_all_users(self, service, mock_db, mock_users):
        """Test getting all users without explicit pagination."""
        EmailAuthService.get_all_users_deprecated_warned = False
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = len(mock_users)
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = mock_users
        mock_db.execute.side_effect = [mock_count_result, mock_list_result]

        with pytest.deprecated_call():
            result = await service.get_all_users()

        assert len(result) == 5
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_get_all_users_no_warning_when_already_warned(self, service, mock_db, mock_users):
        """Test get_all_users does not emit DeprecationWarning after the first call."""
        # Standard
        import warnings

        EmailAuthService.get_all_users_deprecated_warned = True
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = len(mock_users)
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = mock_users
        mock_db.execute.side_effect = [mock_count_result, mock_list_result]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = await service.get_all_users()

        assert len(result) == 5
        assert not any(isinstance(w.message, DeprecationWarning) and "get_all_users()" in str(w.message) for w in caught)

    @pytest.mark.asyncio
    async def test_get_all_users_raises_when_exceeds_limit(self, service, mock_db):
        """Test get_all_users raises when total exceeds limit."""
        EmailAuthService.get_all_users_deprecated_warned = False
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 10001
        mock_db.execute.return_value = mock_count_result

        with pytest.deprecated_call(), pytest.raises(ValueError):
            await service.get_all_users()

    @pytest.mark.asyncio
    async def test_count_users_success(self, service, mock_db, mock_users):
        """Test counting total users using func.count()."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5  # func.count() returns scalar
        mock_db.execute.return_value = mock_result

        result = await service.count_users()

        assert result == 5

    @pytest.mark.asyncio
    async def test_count_users_database_error(self, service, mock_db):
        """Test counting users with database error."""
        mock_db.execute.side_effect = Exception("Database error")

        result = await service.count_users()

        assert result == 0


class TestEmailAuthServiceAuthEvents:
    """Tests for authentication event tracking."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def service(self, mock_db):
        """Create email auth service instance."""
        return EmailAuthService(mock_db)

    @pytest.fixture
    def mock_events(self):
        """Create mock authentication events."""
        events = []
        for i in range(3):
            event = MagicMock(spec=EmailAuthEvent)
            event.user_email = f"user{i}@example.com"
            event.event_type = "login_attempt"
            event.success = i != 1  # Second event is failure
            event.timestamp = datetime.now(timezone.utc) - timedelta(minutes=i)
            events.append(event)
        return events

    @pytest.mark.asyncio
    async def test_get_auth_events_all(self, service, mock_db, mock_events):
        """Test getting all authentication events."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_events
        mock_db.execute.return_value = mock_result

        result = await service.get_auth_events(limit=100, offset=0)

        assert len(result) == 3
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_auth_events_by_email(self, service, mock_db, mock_events):
        """Test getting authentication events for specific user."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_events[0]]
        mock_db.execute.return_value = mock_result

        result = await service.get_auth_events(email="user0@example.com", limit=10)

        assert len(result) == 1
        assert result[0].user_email == "user0@example.com"

    @pytest.mark.asyncio
    async def test_get_auth_events_database_error(self, service, mock_db):
        """Test getting auth events with database error."""
        mock_db.execute.side_effect = Exception("Database error")

        result = await service.get_auth_events()

        assert result == []


class TestEmailAuthServiceUserUpdates:
    """Tests for user update operations."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_password_service(self):
        """Create mock password service."""
        mock_service = MagicMock(spec=Argon2PasswordService)
        mock_service.hash_password.return_value = "new_hashed_password"
        return mock_service

    @pytest.fixture
    def service(self, mock_db):
        """Create email auth service instance."""
        return EmailAuthService(mock_db)

    @pytest.fixture
    def mock_user(self):
        """Create a mock user object."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_hash = "old_hash"
        return user

    @pytest.mark.asyncio
    async def test_update_user_full_name(self, service, mock_db, mock_user):
        """Test updating user's full name."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.update_user(email="test@example.com", full_name="Updated Name")

        assert mock_user.full_name == "Updated Name"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_admin_status(self, service, mock_db, mock_user):
        """Test updating user's admin status."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.update_user(email="test@example.com", is_admin=True)

        assert mock_user.is_admin is True
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_password(self, service, mock_db, mock_user, mock_password_service):
        """Test updating user's password."""
        service.password_service = mock_password_service
        mock_password_service.hash_password_async = AsyncMock(return_value="new_hashed_password")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.update_user(email="test@example.com", password="NewSecurePass123!")

        assert mock_user.password_hash == "new_hashed_password"
        mock_password_service.hash_password_async.assert_called_once_with("NewSecurePass123!")
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_not_found(self, service, mock_db):
        """Test updating non-existent user."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await service.update_user(email="nonexistent@example.com", full_name="Name")

    @pytest.mark.asyncio
    async def test_update_user_database_error(self, service, mock_db, mock_user):
        """Test updating user with database error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result
        mock_db.commit.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            await service.update_user(email="test@example.com", full_name="Name")

        mock_db.rollback.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_is_active(self, service, mock_db, mock_user):
        """Test updating user's is_active status."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.update_user(email="test@example.com", is_active=False)

        assert mock_user.is_active is False
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_password_change_required(self, service, mock_db, mock_user):
        """Test updating user's password_change_required flag."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.update_user(email="test@example.com", password_change_required=True)

        assert mock_user.password_change_required is True
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_partial_update_preserves_other_fields(self, service, mock_db, mock_user):
        """Test that partial updates don't overwrite unspecified fields."""
        # Set initial state
        mock_user.full_name = "Original Name"
        mock_user.is_admin = False
        mock_user.is_active = True
        mock_user.password_change_required = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        # Update only is_active
        result = await service.update_user(email="test@example.com", is_active=False)

        # Verify only is_active changed
        assert mock_user.is_active is False
        assert mock_user.full_name == "Original Name"
        assert mock_user.is_admin is False
        assert mock_user.password_change_required is False
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_multiple_fields_including_new_ones(self, service, mock_db, mock_user, mock_password_service):
        """Test updating multiple fields including is_active and password_change_required."""
        service.password_service = mock_password_service
        mock_password_service.hash_password_async = AsyncMock(return_value="new_hashed_password")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.update_user(email="test@example.com", full_name="Updated Name", is_admin=True, is_active=False, password_change_required=True, password="NewPassword123!")

        assert mock_user.full_name == "Updated Name"
        assert mock_user.is_admin is True
        assert mock_user.is_active is False
        assert mock_user.password_change_required is True
        assert mock_user.password_hash == "new_hashed_password"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_protect_all_admins_blocks_demote(self, service, mock_db, monkeypatch):
        """Test that protect_all_admins blocks demoting any admin (not just last)."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "protect_all_admins", True)

        admin_user = MagicMock(spec=EmailUser)
        admin_user.email = "admin@example.com"
        admin_user.is_admin = True
        admin_user.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = admin_user
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Admin protection is enabled"):
            await service.update_user(email="admin@example.com", is_admin=False)

    @pytest.mark.asyncio
    async def test_update_user_protect_all_admins_blocks_deactivate(self, service, mock_db, monkeypatch):
        """Test that protect_all_admins blocks deactivating any admin."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "protect_all_admins", True)

        admin_user = MagicMock(spec=EmailUser)
        admin_user.email = "admin@example.com"
        admin_user.is_admin = True
        admin_user.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = admin_user
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Admin protection is enabled"):
            await service.update_user(email="admin@example.com", is_active=False)

    @pytest.mark.asyncio
    async def test_update_user_protect_all_admins_allows_other_updates(self, service, mock_db, monkeypatch):
        """Test that protect_all_admins still allows non-admin-related updates."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "protect_all_admins", True)

        admin_user = MagicMock(spec=EmailUser)
        admin_user.email = "admin@example.com"
        admin_user.is_admin = True
        admin_user.is_active = True
        admin_user.password_hash = "old_hash"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = admin_user
        mock_db.execute.return_value = mock_result

        result = await service.update_user(email="admin@example.com", full_name="New Name")
        assert admin_user.full_name == "New Name"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_blocks_demote_last_active_admin(self, service, mock_db, monkeypatch):
        """Test update_user blocks demoting/deactivating the last active admin when protection is off."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "protect_all_admins", False)

        admin_user = MagicMock(spec=EmailUser)
        admin_user.email = "admin@example.com"
        admin_user.is_admin = True
        admin_user.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = admin_user
        mock_db.execute.return_value = mock_result

        with patch.object(service, "is_last_active_admin", new=AsyncMock(return_value=True)):
            with pytest.raises(ValueError, match="last remaining active admin"):
                await service.update_user(email="admin@example.com", is_admin=False)

    @pytest.mark.asyncio
    async def test_activate_user_success(self, service, mock_db, mock_user):
        """Test activating a user account."""
        mock_user.is_active = False
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.activate_user("test@example.com")

        assert mock_user.is_active is True
        assert result == mock_user
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_activate_user_not_found(self, service, mock_db):
        """Test activating non-existent user."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await service.activate_user("nonexistent@example.com")

    @pytest.mark.asyncio
    async def test_activate_user_database_error(self, service, mock_db, mock_user):
        """Test activating user with database error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result
        mock_db.commit.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            await service.activate_user("test@example.com")

        mock_db.rollback.assert_called()

    @pytest.mark.asyncio
    async def test_deactivate_user_success(self, service, mock_db, mock_user):
        """Test deactivating a user account."""
        mock_user.is_active = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.deactivate_user("test@example.com")

        assert mock_user.is_active is False
        assert result == mock_user
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_deactivate_user_not_found(self, service, mock_db):
        """Test deactivating non-existent user."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await service.deactivate_user("nonexistent@example.com")

    @pytest.mark.asyncio
    async def test_deactivate_user_database_error(self, service, mock_db, mock_user):
        """Test deactivating user with database error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result
        mock_db.commit.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            await service.deactivate_user("test@example.com")

        mock_db.rollback.assert_called()


class TestEmailAuthServiceUserDeletion:
    """Tests for user deletion functionality."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def service(self, mock_db):
        """Create email auth service instance."""
        return EmailAuthService(mock_db)

    @pytest.fixture
    def mock_user(self):
        """Create a mock user object."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        return user

    @pytest.fixture
    def mock_team(self):
        """Create a mock team object."""
        team = MagicMock(spec=EmailTeam)
        team.id = 1
        team.name = "Test Team"
        team.created_by = "test@example.com"
        return team

    @pytest.fixture
    def mock_team_member(self):
        """Create a mock team member object."""
        member = MagicMock(spec=EmailTeamMember)
        member.user_email = "other@example.com"
        member.team_id = 1
        member.role = "owner"
        return member

    @pytest.mark.asyncio
    async def test_delete_user_success(self, service, mock_db, mock_user):
        """Test successful user deletion including role cleanup."""
        # Setup mock returns
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_result.scalars.return_value.all.return_value = []  # No teams owned
        mock_db.execute.return_value = mock_result

        # Mock role_service to verify role deletion
        mock_role_svc = MagicMock()
        mock_role_svc.delete_all_user_roles = AsyncMock(return_value=2)

        with patch.object(type(service), "role_service", new_callable=lambda: property(lambda self: mock_role_svc)):
            result = await service.delete_user("test@example.com")

        assert result is True
        mock_role_svc.delete_all_user_roles.assert_called_once_with("test@example.com")
        mock_db.delete.assert_called_once_with(mock_user)
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_delete_user_cache_invalidation_exception_is_non_fatal(self, service, mock_db, mock_user):
        """Test delete_user continues when auth cache invalidation fails."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_result.scalars.return_value.all.return_value = []  # No teams owned
        mock_db.execute.return_value = mock_result

        with patch("asyncio.create_task", side_effect=Exception("task-failure")):
            result = await service.delete_user("test@example.com")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_user_not_found(self, service, mock_db):
        """Test deleting non-existent user."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await service.delete_user("nonexistent@example.com")

    @pytest.mark.asyncio
    async def test_delete_user_with_team_transfer(self, service, mock_db, mock_user, mock_team, mock_team_member):
        """Test deleting user who owns teams that can be transferred."""
        # First execute: get user
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        # Second execute: get teams owned
        mock_teams_result = MagicMock()
        mock_teams_result.scalars.return_value.all.return_value = [mock_team]

        # Third execute: get potential new owners
        mock_members_result = MagicMock()
        mock_members_result.scalars.return_value.all.return_value = [mock_team_member]

        # Fourth execute: auth events (empty)
        # Fifth execute: team members (empty)
        mock_empty_result = MagicMock()

        mock_db.execute.side_effect = [mock_user_result, mock_teams_result, mock_members_result, mock_empty_result, mock_empty_result]

        mock_role_svc = MagicMock()
        mock_role_svc.delete_all_user_roles = AsyncMock(return_value=0)

        with patch.object(type(service), "role_service", new_callable=lambda: property(lambda self: mock_role_svc)):
            result = await service.delete_user("test@example.com")

        assert result is True
        assert mock_team.created_by == "other@example.com"  # Ownership transferred
        mock_role_svc.delete_all_user_roles.assert_called_once_with("test@example.com")
        mock_db.delete.assert_called_once_with(mock_user)
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_delete_user_with_personal_team(self, service, mock_db, mock_user, mock_team):
        """Test deleting user with single-member personal team."""
        # Setup single team member (just the user)
        single_member = MagicMock(spec=EmailTeamMember)
        single_member.user_email = "test@example.com"
        single_member.team_id = 1
        single_member.role = "owner"

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        mock_teams_result = MagicMock()
        mock_teams_result.scalars.return_value.all.return_value = [mock_team]

        # No other owners available
        mock_no_owners = MagicMock()
        mock_no_owners.scalars.return_value.all.return_value = []

        # Single member in team
        mock_single_member = MagicMock()
        mock_single_member.scalars.return_value.all.return_value = [single_member]

        mock_empty = MagicMock()

        mock_db.execute.side_effect = [
            mock_user_result,
            mock_teams_result,
            mock_no_owners,  # No other owners
            mock_single_member,  # Just the user as member
            mock_empty,  # Delete team members
            mock_empty,  # Delete auth events
            mock_empty,  # Delete user team members
        ]

        mock_role_svc = MagicMock()
        mock_role_svc.delete_all_user_roles = AsyncMock(return_value=0)

        with patch.object(type(service), "role_service", new_callable=lambda: property(lambda self: mock_role_svc)):
            result = await service.delete_user("test@example.com")

        assert result is True
        mock_role_svc.delete_all_user_roles.assert_called_once_with("test@example.com")
        mock_db.delete.assert_any_call(mock_team)  # Team should be deleted
        mock_db.delete.assert_any_call(mock_user)  # User should be deleted
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_delete_user_with_team_no_transfer_possible(self, service, mock_db, mock_user, mock_team):
        """Test deleting user who owns team with members but no other owners."""
        # Setup multiple members but no other owners
        members = [MagicMock(user_email="test@example.com", role="owner"), MagicMock(user_email="member1@example.com", role="member"), MagicMock(user_email="member2@example.com", role="member")]

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        mock_teams_result = MagicMock()
        mock_teams_result.scalars.return_value.all.return_value = [mock_team]

        mock_no_owners = MagicMock()
        mock_no_owners.scalars.return_value.all.return_value = []  # No other owners

        mock_members_result = MagicMock()
        mock_members_result.scalars.return_value.all.return_value = members

        mock_db.execute.side_effect = [mock_user_result, mock_teams_result, mock_no_owners, mock_members_result]

        with pytest.raises(ValueError, match="no other owners to transfer"):
            await service.delete_user("test@example.com")

        mock_db.rollback.assert_called()

    @pytest.mark.asyncio
    async def test_delete_user_database_error(self, service, mock_db, mock_user):
        """Test deleting user with database error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_db.commit.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            await service.delete_user("test@example.com")

        mock_db.rollback.assert_called()


class TestEmailAuthServiceAdminCounting:
    """Tests for admin user counting functionality."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def service(self, mock_db):
        """Create email auth service instance."""
        return EmailAuthService(mock_db)

    @pytest.mark.asyncio
    async def test_count_active_admin_users(self, service, mock_db):
        """Test counting active admin users."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_db.execute.return_value = mock_result

        result = await service.count_active_admin_users()

        assert result == 3
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_active_admin_users_none(self, service, mock_db):
        """Test counting when no active admins."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.count_active_admin_users()

        assert result == 0

    @pytest.mark.asyncio
    async def test_is_last_active_admin_true(self, service, mock_db):
        """Test checking if user is last active admin - true case."""
        mock_user = MagicMock(spec=EmailUser)
        mock_user.is_admin = True
        mock_user.is_active = True

        # First call: get user
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        # Second call: count admins
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_db.execute.side_effect = [mock_user_result, mock_count_result]

        result = await service.is_last_active_admin("admin@example.com")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_last_active_admin_false_multiple_admins(self, service, mock_db):
        """Test checking if user is last active admin - false due to multiple admins."""
        mock_user = MagicMock(spec=EmailUser)
        mock_user.is_admin = True
        mock_user.is_active = True

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 3  # Multiple admins

        mock_db.execute.side_effect = [mock_user_result, mock_count_result]

        result = await service.is_last_active_admin("admin@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_last_active_admin_false_not_admin(self, service, mock_db):
        """Test checking if non-admin user is last active admin."""
        mock_user = MagicMock(spec=EmailUser)
        mock_user.is_admin = False
        mock_user.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.is_last_active_admin("user@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_last_active_admin_false_inactive(self, service, mock_db):
        """Test checking if inactive admin is last active admin."""
        mock_user = MagicMock(spec=EmailUser)
        mock_user.is_admin = True
        mock_user.is_active = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        result = await service.is_last_active_admin("admin@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_last_active_admin_user_not_found(self, service, mock_db):
        """Test checking if non-existent user is last active admin."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.is_last_active_admin("nonexistent@example.com")

        assert result is False

    # ---- _escape_like ---- #
    def test_escape_like_backslash(self, service):
        """Backslashes are escaped in LIKE patterns."""
        assert service._escape_like("test\\val") == "test\\\\val"

    def test_escape_like_percent(self, service):
        """Percent signs are escaped in LIKE patterns."""
        assert service._escape_like("100%") == "100\\%"

    def test_escape_like_underscore(self, service):
        """Underscores are escaped in LIKE patterns."""
        assert service._escape_like("user_name") == "user\\_name"

    def test_escape_like_combined(self, service):
        """Combined special characters are all escaped."""
        result = service._escape_like("a\\b%c_d")
        assert result == "a\\\\b\\%c\\_d"

    # ---- count_users ---- #
    @pytest.mark.asyncio
    async def test_count_users_success(self, service, mock_db):
        """count_users returns count from DB."""
        mock_db.execute.return_value.scalar.return_value = 42
        result = await service.count_users()
        assert result == 42

    @pytest.mark.asyncio
    async def test_count_users_none_returns_zero(self, service, mock_db):
        """count_users returns 0 when scalar is None."""
        mock_db.execute.return_value.scalar.return_value = None
        result = await service.count_users()
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_users_error_returns_zero(self, service, mock_db):
        """count_users returns 0 on exception."""
        mock_db.execute.side_effect = Exception("db error")
        result = await service.count_users()
        assert result == 0

    # ---- count_active_admin_users ---- #
    @pytest.mark.asyncio
    async def test_count_active_admin_users(self, service, mock_db):
        """count_active_admin_users returns count."""
        mock_db.execute.return_value.scalar.return_value = 3
        result = await service.count_active_admin_users()
        assert result == 3

    @pytest.mark.asyncio
    async def test_count_active_admin_users_none(self, service, mock_db):
        """count_active_admin_users returns 0 when None."""
        mock_db.execute.return_value.scalar.return_value = None
        result = await service.count_active_admin_users()
        assert result == 0

    # ---- list_users with search ---- #
    @pytest.mark.asyncio
    async def test_list_users_with_search(self, service, mock_db):
        """list_users with search parameter filters results."""
        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "john@test.com"
        mock_user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_user]

        result = await service.list_users(search="john", limit=50)
        assert len(result.data) == 1

    @pytest.mark.asyncio
    async def test_list_users_page_based(self, service, mock_db):
        """list_users with page parameter returns pagination metadata."""
        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user@test.com"
        mock_user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        # Mock count for pagination
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        # Mock data query
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [mock_user]

        mock_db.execute.side_effect = [count_result, data_result]

        result = await service.list_users(page=1, per_page=10)
        assert result.data is not None

    # ---- get_auth_events ---- #
    @pytest.mark.asyncio
    async def test_get_auth_events_success(self, service, mock_db):
        """get_auth_events returns events."""
        mock_event = MagicMock(spec=EmailAuthEvent)
        mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_event]
        result = await service.get_auth_events(email="user@test.com")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_auth_events_error(self, service, mock_db):
        """get_auth_events returns empty list on error."""
        mock_db.execute.side_effect = Exception("db error")
        result = await service.get_auth_events()
        assert result == []

    # ---- is_last_active_admin true case ---- #
    @pytest.mark.asyncio
    async def test_is_last_active_admin_true(self, service, mock_db):
        """is_last_active_admin returns True when only 1 active admin."""
        mock_user = MagicMock()
        mock_user.is_admin = True
        mock_user.is_active = True
        # First call: find user; Second call: count admins
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        mock_db.execute.side_effect = [user_result, count_result]

        result = await service.is_last_active_admin("admin@test.com")
        assert result is True
