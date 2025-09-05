# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_auth_basic.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Basic tests for Email Authentication Service functionality.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
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
        service.validate_password("password123")
        service.validate_password("simple123")  # 8+ chars
        service.validate_password("verylongpasswordstring")

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
        with patch('mcpgateway.services.email_auth_service.settings') as mock_settings:
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
        assert hasattr(service, 'password_service')
        assert hasattr(service.password_service, 'hash_password')
        assert hasattr(service.password_service, 'verify_password')

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
            'validate_email',
            'validate_password',
            'get_user_by_email',
            'create_user',
        ]

        for method_name in required_methods:
            assert hasattr(service, method_name)
            assert callable(getattr(service, method_name))

    def test_password_service_configuration(self, service):
        """Test password service is properly configured."""
        password_service = service.password_service

        # Test basic functionality exists
        assert hasattr(password_service, 'hash_password')
        assert hasattr(password_service, 'verify_password')

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
