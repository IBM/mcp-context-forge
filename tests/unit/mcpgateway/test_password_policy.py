# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_password_policy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for password policy enforcement.

This module tests the comprehensive password policy implementation
addressing pentesting report findings.
"""

# Standard
from unittest.mock import Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.password_policy_service import (
    PasswordPolicyError,
    PasswordPolicyService,
)


class TestPasswordPolicyService:
    """Test suite for PasswordPolicyService."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return Mock()

    @pytest.fixture
    def policy_service(self, mock_db):
        """Create a PasswordPolicyService instance."""
        return PasswordPolicyService(mock_db)

    # User Password Validation Tests

    def test_validate_user_password_success(self, policy_service):
        """Test that valid passwords pass validation."""
        # 12+ chars, 3 complexity types, no sequential patterns
        assert policy_service.validate_user_password("SecureP@ssw0rd!", "user@example.com")
        assert policy_service.validate_user_password("MyP@ssw0rd!2024", "admin@example.com")
        assert policy_service.validate_user_password("Tr0ng!Password", "test@example.com")

    def test_validate_user_password_too_short(self, policy_service):
        """Test that passwords under 12 characters are rejected."""
        with pytest.raises(PasswordPolicyError, match="at least 12 characters"):
            policy_service.validate_user_password("Short1!", "user@example.com")

    def test_validate_user_password_insufficient_complexity(self, policy_service):
        """Test that passwords without 3 complexity types are rejected."""
        # Only lowercase and numbers (2 types)
        with pytest.raises(PasswordPolicyError, match="at least 3 of the following"):
            policy_service.validate_user_password("alllowercase123", "user@example.com")

        # Only uppercase and lowercase (2 types)
        with pytest.raises(PasswordPolicyError, match="at least 3 of the following"):
            policy_service.validate_user_password("OnlyLettersHere", "user@example.com")

    def test_validate_user_password_common_passwords(self, policy_service):
        """Test that common passwords from pentesting report are rejected."""
        # Test that common passwords are rejected (case-insensitive)
        # "password01@!" is 12 chars, has all 4 complexity types, no sequential patterns
        with pytest.raises(PasswordPolicyError, match="too common"):
            policy_service.validate_user_password("Password01@!", "user@example.com")

        # Test another common password (admin@pass! is 12 chars)
        with pytest.raises(PasswordPolicyError, match="too common"):
            policy_service.validate_user_password("Admin@Pass!x", "admin@example.com")

    def test_validate_user_password_username_based(self, policy_service):
        """Test that passwords based on username are rejected."""
        with pytest.raises(PasswordPolicyError, match="not be based on your username"):
            policy_service.validate_user_password("john123!Pass", "john@example.com")

        with pytest.raises(PasswordPolicyError, match="not be based on your username"):
            policy_service.validate_user_password("Admin!Pass123", "admin@example.com")

    def test_validate_user_password_sequential_chars(self, policy_service):
        """Test that passwords with sequential characters are rejected."""
        with pytest.raises(PasswordPolicyError, match="sequential characters"):
            policy_service.validate_user_password("Pass123word!", "user@example.com")

        with pytest.raises(PasswordPolicyError, match="sequential characters"):
            policy_service.validate_user_password("Abcd!Password1", "user@example.com")

    def test_validate_privileged_password_length(self, policy_service):
        """Test that privileged accounts require 22+ characters."""
        # 22 characters - should pass
        assert policy_service.validate_user_password("PrivilegedP@ssw0rd2024", "admin@example.com", is_privileged=True)

        # 21 characters - should fail
        with pytest.raises(PasswordPolicyError, match="at least 22 characters"):
            policy_service.validate_user_password("PrivilegedP@ssw0rd24", "admin@example.com", is_privileged=True)

    # Service Account Password Tests

    def test_validate_service_account_password_success(self, policy_service):
        """Test that valid service account passwords pass."""
        # 20+ characters with high entropy
        assert policy_service.validate_service_account_password("aB3$xY9#mN2@pQ7!wR5%")
        assert policy_service.validate_service_account_password("Srv!Acc0unt#P@ssw0rd2024")

    def test_validate_service_account_password_too_short(self, policy_service):
        """Test that service account passwords under 20 characters are rejected."""
        with pytest.raises(PasswordPolicyError, match="at least 20 characters"):
            policy_service.validate_service_account_password("ShortP@ss123")

    def test_validate_service_account_password_low_entropy(self, policy_service):
        """Test that service account passwords with low entropy are rejected."""
        # Repeated patterns
        with pytest.raises(PasswordPolicyError, match="low entropy"):
            policy_service.validate_service_account_password("aaaaaaaaaaaaaaaaaaa1")

    # Password History Tests

    @pytest.mark.asyncio
    async def test_check_password_history_no_history(self, policy_service, mock_db):
        """Test password history check with no previous passwords."""
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        # Should pass - no history
        assert await policy_service.check_password_history("user@example.com", "NewP@ssw0rd123")

    @pytest.mark.asyncio
    async def test_check_password_history_reuse_detected(self, policy_service, mock_db):
        """Test that password reuse is detected."""
        # Mock password history with matching hash
        mock_history = Mock()
        mock_history.password_hash = "$argon2id$v=19$m=65536,t=3,p=1$test"
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_history]

        # Mock password service to return True for match
        with patch.object(policy_service.password_service, "verify_password_async", return_value=True):
            with pytest.raises(PasswordPolicyError, match="used recently"):
                await policy_service.check_password_history("user@example.com", "OldP@ssw0rd!2024", 5)

    # Password Generation Tests

    def test_generate_secure_password_length(self, policy_service):
        """Test that generated passwords meet length requirements."""
        password = policy_service.generate_secure_password(20)
        assert len(password) >= 20

    def test_generate_secure_password_service_account(self, policy_service):
        """Test that service account passwords use UUID format."""
        password = policy_service.generate_secure_password(for_service_account=True)
        assert len(password) == 36  # UUID format
        assert password.count("-") == 4  # UUID has 4 hyphens

    def test_generate_secure_password_uniqueness(self, policy_service):
        """Test that generated passwords are unique."""
        passwords = [policy_service.generate_secure_password(20) for _ in range(10)]
        assert len(set(passwords)) == 10  # All unique

    # Password Strength Scoring Tests

    def test_get_password_strength_score_strong(self, policy_service):
        """Test password strength scoring for strong passwords."""
        result = policy_service.get_password_strength_score("VeryStr0ng!P@ssw0rd2024")
        assert result["score"] >= 80
        assert result["strength"] == "strong"
        assert len(result["feedback"]) == 0

    def test_get_password_strength_score_weak(self, policy_service):
        """Test password strength scoring for weak passwords."""
        result = policy_service.get_password_strength_score("weak")
        assert result["score"] < 60
        assert result["strength"] == "weak"
        assert len(result["feedback"]) > 0

    def test_get_password_strength_score_common(self, policy_service):
        """Test that common passwords get low scores."""
        result = policy_service.get_password_strength_score("password")
        assert result["score"] <= 40  # Common passwords get penalized but still have some base score
        assert any("common" in fb.lower() for fb in result["feedback"])

    # Helper Method Tests

    def test_has_sequential_chars_numbers(self, policy_service):
        """Test sequential number detection."""
        assert policy_service._has_sequential_chars("abc123def")
        assert policy_service._has_sequential_chars("test456word")
        assert not policy_service._has_sequential_chars("test135word")

    def test_has_sequential_chars_letters(self, policy_service):
        """Test sequential letter detection."""
        assert policy_service._has_sequential_chars("abcdefgh")
        assert policy_service._has_sequential_chars("xyztest")
        assert not policy_service._has_sequential_chars("acetest")

    def test_has_sufficient_entropy(self, policy_service):
        """Test entropy checking."""
        # High entropy
        assert policy_service._has_sufficient_entropy("aB3$xY9#mN2@pQ7!")

        # Low entropy (repeated patterns)
        assert not policy_service._has_sufficient_entropy("aaaaaaaaaa")
        assert not policy_service._has_sufficient_entropy("ababababab")


class TestPasswordPolicyIntegration:
    """Integration tests for password policy with EmailAuthService."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return Mock()

    def test_weak_passwords_rejected_in_auth_service(self, mock_db):
        """Test that weak passwords from pentesting report are rejected."""
        from mcpgateway.services.email_auth_service import EmailAuthService, PasswordValidationError

        service = EmailAuthService(mock_db)

        # Common password should be rejected
        with pytest.raises(PasswordValidationError):
            service.validate_password("Password01@!", "user@example.com")

        # Admin-based common password should be rejected
        with pytest.raises(PasswordValidationError):
            service.validate_password("Administrator!", "admin@example.com")

    def test_minimum_length_enforced(self, mock_db):
        """Test that 12-character minimum is enforced."""
        from mcpgateway.services.email_auth_service import EmailAuthService, PasswordValidationError

        service = EmailAuthService(mock_db)

        # 11 characters - should fail (S-h-o-r-t-!-P-a-s-9-x = 11 chars)
        with pytest.raises(PasswordValidationError, match="12 characters"):
            service.validate_password("Short!Pas9x", "user@example.com")

        # 12 characters - should pass
        service.validate_password("Valid1!Pass2", "user@example.com")


# Pentesting Report Compliance Tests
class TestPentestingReportCompliance:
    """Tests specifically addressing pentesting report findings."""

    @pytest.fixture
    def policy_service(self):
        """Create a PasswordPolicyService instance."""
        return PasswordPolicyService(Mock())

    def test_pentesting_weak_passwords_blocked(self, policy_service):
        """Verify that specific passwords from pentesting report are blocked."""
        weak_passwords = ["Password01@", "Admin@123"]

        for password in weak_passwords:
            with pytest.raises(PasswordPolicyError):
                policy_service.validate_user_password(password, "user@example.com")

    def test_twelve_character_minimum_enforced(self, policy_service):
        """Verify 12-character minimum as recommended."""
        # 11 characters
        with pytest.raises(PasswordPolicyError, match="12 characters"):
            policy_service.validate_user_password("Short1!Pass", "user@example.com")

        # 12 characters
        assert policy_service.validate_user_password("Valid1!Pass2", "user@example.com")

    def test_complexity_requirements_enforced(self, policy_service):
        """Verify complexity requirements (3 of 4 types)."""
        # Valid: lowercase, uppercase, numbers (no sequential patterns)
        assert policy_service.validate_user_password("ValidP@ssw0rd", "user@example.com")

        # Valid: lowercase, uppercase, special
        assert policy_service.validate_user_password("ValidP@ss!Word", "user@example.com")

        # Invalid: only 2 types
        with pytest.raises(PasswordPolicyError, match="at least 3"):
            policy_service.validate_user_password("onlylowercase", "user@example.com")

    def test_service_account_requirements(self, policy_service):
        """Verify service account password requirements (20+ chars, high entropy)."""
        # Valid service account password
        assert policy_service.validate_service_account_password("Srv!Acc0unt#P@ssw0rd2024")

        # Too short
        with pytest.raises(PasswordPolicyError, match="20 characters"):
            policy_service.validate_service_account_password("Short!Pass123")

        # Low entropy
        with pytest.raises(PasswordPolicyError, match="entropy"):
            policy_service.validate_service_account_password("aaaaaaaaaaaaaaaaaaaa")

    def test_argon2_hashing_in_use(self):
        """Verify that Argon2id hashing is being used."""
        from mcpgateway.services.argon2_service import Argon2PasswordService

        service = Argon2PasswordService()
        hashed = service.hash_password("TestPassword123!")

        # Verify Argon2id format
        assert hashed.startswith("$argon2id$")
        assert service.verify_password("TestPassword123!", hashed)
