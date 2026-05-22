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

    def test_has_sequential_chars_ascending_numbers(self, policy_service):
        """Test ascending sequential number patterns."""
        # Exactly 3 sequential digits (should trigger)
        assert policy_service._has_sequential_chars("Pass123word")
        assert policy_service._has_sequential_chars("Test456!pwd")
        assert policy_service._has_sequential_chars("789SecurePass")

        # More than 3 sequential digits (should trigger)
        assert policy_service._has_sequential_chars("Pass1234word")
        assert policy_service._has_sequential_chars("Test56789!pwd")

        # Edge case: sequences at boundaries
        assert policy_service._has_sequential_chars("123password")  # Start
        assert policy_service._has_sequential_chars("password789")  # End

    def test_has_sequential_chars_descending_numbers(self, policy_service):
        """Test descending sequential number patterns."""
        # Descending sequences (should trigger)
        assert policy_service._has_sequential_chars("Pass321word")
        assert policy_service._has_sequential_chars("Test654!pwd")
        assert policy_service._has_sequential_chars("987SecurePass")

        # Longer descending sequences
        assert policy_service._has_sequential_chars("Pass4321word")
        assert policy_service._has_sequential_chars("98765Test")

    def test_has_sequential_chars_ascending_letters(self, policy_service):
        """Test ascending sequential letter patterns (case-insensitive)."""
        # Lowercase sequences
        assert policy_service._has_sequential_chars("Passabc123")
        assert policy_service._has_sequential_chars("Test!defgh")
        assert policy_service._has_sequential_chars("xyzPassword1")

        # Uppercase sequences (should be detected - method uses .lower())
        assert policy_service._has_sequential_chars("PassABC123")
        assert policy_service._has_sequential_chars("Test!DEFGH")
        assert policy_service._has_sequential_chars("XYZPassword1")

        # Mixed case sequences (should be detected)
        assert policy_service._has_sequential_chars("PassAbC123")
        assert policy_service._has_sequential_chars("Test!DeFg")

    def test_has_sequential_chars_descending_letters(self, policy_service):
        """Test descending sequential letter patterns."""
        # Lowercase descending
        assert policy_service._has_sequential_chars("Passcba123")
        assert policy_service._has_sequential_chars("Test!fed")
        assert policy_service._has_sequential_chars("zyxPassword1")

        # Uppercase descending
        assert policy_service._has_sequential_chars("PassCBA123")
        assert policy_service._has_sequential_chars("Test!FED")
        assert policy_service._has_sequential_chars("ZYXPassword1")

    def test_has_sequential_chars_non_sequential_patterns(self, policy_service):
        """Test that non-sequential patterns are NOT flagged."""
        # Non-sequential numbers (safe)
        assert not policy_service._has_sequential_chars("Pass135word")
        assert not policy_service._has_sequential_chars("Test246!pwd")
        assert not policy_service._has_sequential_chars("1357Password")
        assert not policy_service._has_sequential_chars("Pass102word")

        # Non-sequential letters (safe)
        assert not policy_service._has_sequential_chars("Passacf159")  # Fixed: removed 123
        assert not policy_service._has_sequential_chars("Test!adf")
        assert not policy_service._has_sequential_chars("xazPassword1")

        # Alternating patterns (safe)
        assert not policy_service._has_sequential_chars("Pass1a2b3c")
        assert not policy_service._has_sequential_chars("A1B2C3Pass")

    def test_has_sequential_chars_edge_cases(self, policy_service):
        """Test edge cases for sequential character detection."""
        # Short passwords (less than 3 chars total)
        assert not policy_service._has_sequential_chars("12")
        assert not policy_service._has_sequential_chars("ab")
        assert not policy_service._has_sequential_chars("A1")

        # Exactly 3 characters
        assert policy_service._has_sequential_chars("123")
        assert policy_service._has_sequential_chars("abc")
        assert policy_service._has_sequential_chars("ABC")
        assert policy_service._has_sequential_chars("321")
        assert policy_service._has_sequential_chars("zyx")

        # Special characters mixed in (should not interfere with detection)
        assert policy_service._has_sequential_chars("Pass!123#word")
        assert policy_service._has_sequential_chars("Test@abc$pwd")

        # Multiple non-overlapping sequences (should trigger on any one)
        assert policy_service._has_sequential_chars("123test789")
        assert policy_service._has_sequential_chars("abcTESTxyz")

    def test_has_sequential_chars_boundary_sequences(self, policy_service):
        """Test sequences at alphabet/digit boundaries."""
        # Wrapping sequences (should NOT trigger - no wraparound)
        assert not policy_service._has_sequential_chars("Pass890word")  # 8,9,0 not sequential
        assert not policy_service._has_sequential_chars("Testxacword")  # x,a,c not sequential (no wraparound)

        # Near-boundary valid sequences
        assert policy_service._has_sequential_chars("Pass789word")  # 7,8,9 sequential
        assert policy_service._has_sequential_chars("Testwxyzword")  # w,x,y,z sequential (contains xyz)

    def test_has_sufficient_entropy(self, policy_service):
        """Test entropy checking."""
        # High entropy
        assert policy_service._has_sufficient_entropy("aB3$xY9#mN2@pQ7!")

        # Low entropy (repeated patterns)
        assert not policy_service._has_sufficient_entropy("aaaaaaaaaa")
        assert not policy_service._has_sufficient_entropy("ababababab")

    # Password Requirements Tests

    def test_get_password_requirements(self, policy_service):
        """Test password requirements retrieval."""
        requirements = policy_service.get_password_requirements()
        assert requirements["min_length"] == 12
        assert requirements["complexity_required"] == 3
        assert requirements["complexity_total"] == 4
        assert len(requirements["complexity_types"]) == 4
        assert len(requirements["restrictions"]) == 3

    def test_get_password_requirements_privileged(self, policy_service):
        """Test password requirements for privileged accounts."""
        requirements = policy_service.get_password_requirements(is_privileged=True)
        assert requirements["min_length"] == 22

    def test_get_password_requirements_type_validation(self, policy_service):
        """Test that get_password_requirements validates input types."""
        # Should raise TypeError for non-boolean input
        with pytest.raises(TypeError, match="is_privileged must be bool"):
            policy_service.get_password_requirements(is_privileged="true")

        # Note: Python's int (1, 0) are valid bool values, so this won't raise TypeError
        # The lru_cache will accept 1 as a valid argument, but 1 == True in Python
        # So we skip this specific test since it's a language behavior, not a bug

    def test_get_password_requirements_config_wiring_user(self, policy_service):
        """Test that get_password_requirements reflects custom user min_length from settings."""
        from mcpgateway.config import settings

        # Clear the LRU cache to ensure fresh settings are read
        policy_service.get_password_requirements.cache_clear()

        # Temporarily override settings
        original_value = getattr(settings, "password_min_length_user", 12)
        try:
            settings.password_min_length_user = 16

            requirements = policy_service.get_password_requirements(is_privileged=False)
            assert requirements["min_length"] == 16, "Should reflect custom password_min_length_user from settings"
            assert "16 characters" in requirements["min_length_description"]
        finally:
            settings.password_min_length_user = original_value
            # Clear cache again to avoid affecting other tests
            policy_service.get_password_requirements.cache_clear()

    def test_get_password_requirements_config_wiring_privileged(self, policy_service):
        """Test that get_password_requirements reflects custom privileged min_length from settings."""
        from mcpgateway.config import settings

        # Clear the LRU cache to ensure fresh settings are read
        policy_service.get_password_requirements.cache_clear()

        # Temporarily override settings
        original_value = getattr(settings, "password_min_length_privileged", 22)
        try:
            settings.password_min_length_privileged = 25

            requirements = policy_service.get_password_requirements(is_privileged=True)
            assert requirements["min_length"] == 25, "Should reflect custom password_min_length_privileged from settings"
            assert "25 characters" in requirements["min_length_description"]
        finally:
            settings.password_min_length_privileged = original_value
            # Clear cache again to avoid affecting other tests
            policy_service.get_password_requirements.cache_clear()

    def test_password_requirements_match_validation_logic(self, policy_service):
        """Ensure requirements descriptions match actual validation logic."""
        requirements = policy_service.get_password_requirements()

        # Test that a password meeting requirements actually validates
        # Meets 3-of-4 complexity (uppercase, lowercase, numbers), 12+ chars
        # Note: Avoid sequential chars (123, abc) and username matches
        password_valid = "SecureP4ss2w0rd"
        assert policy_service.validate_user_password(password_valid, email="user@example.com")

        # Test that a password missing complexity fails
        # Only 2 types (lowercase, numbers) - should fail 3-of-4 requirement
        password_weak = "weakp4ssw0rd"
        with pytest.raises(PasswordPolicyError, match="at least 3 of the following"):
            policy_service.validate_user_password(password_weak, email="user@example.com")

        # Test that password below minimum length fails
        short_password = "Abc!1x"  # Only 6 chars
        with pytest.raises(PasswordPolicyError, match="12 characters"):
            policy_service.validate_user_password(short_password, email="user@example.com")

        # Test each complexity type is correctly validated
        # Lowercase + uppercase + special (no numbers)
        assert policy_service.validate_user_password("SecurePassword!", email="user@example.com")

        # Lowercase + numbers + special (no uppercase)
        assert policy_service.validate_user_password("securep4ss!w0rd", email="person@example.com")

        # Uppercase + numbers + special (no lowercase)
        assert policy_service.validate_user_password("SECUREP4SS!W0RD", email="admin@example.com")

    def test_min_length_consistency_user_account(self, policy_service):
        """Test that get_password_requirements and validate_user_password agree on minimum length for user accounts."""
        from mcpgateway.config import settings

        # Get requirements for regular user
        requirements = policy_service.get_password_requirements(is_privileged=False)
        min_length = requirements["min_length"]

        # Verify this matches what validate_user_password enforces
        expected_min = getattr(settings, "password_min_length_user", 12)
        assert min_length == expected_min, "Requirements min_length should match settings.password_min_length_user"

        # Create a password that's exactly min_length-1 (should fail)
        # Use valid complexity: uppercase + lowercase + digit + special (4 types, no sequential)
        password_too_short = "A" + "b" * (min_length - 4) + "1!"
        assert len(password_too_short) == min_length - 1
        with pytest.raises(PasswordPolicyError, match=f"{min_length} characters"):
            policy_service.validate_user_password(password_too_short, email="user@example.com")

        # Create a password that's exactly min_length (should pass)
        password_exact = "A" + "b" * (min_length - 3) + "1!"
        assert len(password_exact) == min_length
        assert policy_service.validate_user_password(password_exact, email="user@example.com")

    def test_min_length_consistency_privileged_account(self, policy_service):
        """Test that get_password_requirements and validate_user_password agree on minimum length for privileged accounts."""
        from mcpgateway.config import settings

        # Get requirements for privileged user
        requirements = policy_service.get_password_requirements(is_privileged=True)
        min_length = requirements["min_length"]

        # Verify this matches what validate_user_password enforces
        expected_min = getattr(settings, "password_min_length_privileged", 22)
        assert min_length == expected_min, "Requirements min_length should match settings.password_min_length_privileged"

        # Create a password that's exactly min_length-1 (should fail)
        password_too_short = "A" + "b" * (min_length - 4) + "1!"
        assert len(password_too_short) == min_length - 1
        with pytest.raises(PasswordPolicyError, match=f"{min_length} characters"):
            policy_service.validate_user_password(password_too_short, email="admin@example.com", is_privileged=True)

        # Create a password that's exactly min_length (should pass)
        password_exact = "A" + "b" * (min_length - 3) + "1!"
        assert len(password_exact) == min_length
        assert policy_service.validate_user_password(password_exact, email="admin@example.com", is_privileged=True)


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

    def test_password_error_message_truncation(self):
        """Test that long error messages are truncated for URL safety."""
        from mcpgateway.config import settings

        # Simulate very long error message (like multiple concatenated validation failures)
        long_error = "Password must contain at least 3 of the following: lowercase letters, uppercase letters, numbers, special characters. " * 10
        max_length = settings.password_error_message_max_length

        # Apply safeguard logic from admin.py
        error_msg = long_error
        if len(error_msg) > max_length:
            error_msg = error_msg[: max_length - 3] + "..."

        # Verify truncation
        assert len(error_msg) == max_length, f"Expected {max_length} chars, got {len(error_msg)}"
        assert error_msg.endswith("..."), "Truncated message should end with '...'"
        assert len(long_error) > max_length, "Test setup: original message must be longer than max_length"

    def test_password_error_message_no_truncation_when_short(self):
        """Test that short error messages are not truncated."""
        from mcpgateway.config import settings

        short_error = "Password is too short"
        max_length = settings.password_error_message_max_length

        # Apply safeguard logic from admin.py
        error_msg = short_error
        if len(error_msg) > max_length:
            error_msg = error_msg[: max_length - 3] + "..."

        # Verify no truncation
        assert error_msg == short_error, "Short messages should not be modified"
        assert not error_msg.endswith("..."), "Short messages should not have '...' suffix"
        assert len(short_error) < max_length, "Test setup: short message must be under max_length"

    def test_password_error_message_custom_max_length(self):
        """Test truncation with different max_length values."""
        # Test with custom max length of 100
        custom_max_length = 100
        long_error = "A" * 200

        # Apply safeguard logic
        error_msg = long_error
        if len(error_msg) > custom_max_length:
            error_msg = error_msg[: custom_max_length - 3] + "..."

        # Verify custom truncation
        assert len(error_msg) == custom_max_length
        assert error_msg.endswith("...")
        assert error_msg == ("A" * 97) + "...", "Should be 97 A's followed by '...'"

    def test_password_error_message_url_encoding_short_message(self):
        """Test URL encoding of short error messages (no truncation)."""
        import urllib.parse

        from mcpgateway.config import settings

        short_error = "Password must contain special characters"
        max_length = settings.password_error_message_max_length

        # Apply safeguard logic (as in admin.py)
        error_msg = short_error
        if len(error_msg) > max_length:
            error_msg = error_msg[: max_length - 3] + "..."
        error_msg_encoded = urllib.parse.quote(error_msg)

        # Verify no truncation and proper encoding
        assert error_msg == short_error, "Short message should not be truncated"
        assert "special%20characters" in error_msg_encoded, "Spaces should be URL-encoded"
        assert urllib.parse.unquote(error_msg_encoded) == short_error, "Decoded message should match original"

    def test_password_error_message_url_encoding_long_message(self):
        """Test URL encoding of long error messages (with truncation)."""
        import urllib.parse

        from mcpgateway.config import settings

        long_error = "Password validation failed: " + ("A" * 500)
        max_length = settings.password_error_message_max_length

        # Apply safeguard logic (as in admin.py)
        error_msg = long_error
        if len(error_msg) > max_length:
            error_msg = error_msg[: max_length - 3] + "..."
        error_msg_encoded = urllib.parse.quote(error_msg)

        # Verify truncation and encoding
        assert len(error_msg) == max_length, "Message should be truncated to max_length"
        assert error_msg.endswith("..."), "Truncated message should end with '...'"
        assert urllib.parse.unquote(error_msg_encoded) == error_msg, "Decoded message should match truncated version"
        assert len(error_msg_encoded) > 0, "Encoded message should not be empty"

    def test_password_error_message_url_encoding_special_chars(self):
        """Test URL encoding handles special characters correctly."""
        import urllib.parse

        error_with_special = "Password cannot contain <script>alert('xss')</script> or & = ?"
        from mcpgateway.config import settings

        max_length = settings.password_error_message_max_length

        # Apply safeguard logic (as in admin.py)
        error_msg = error_with_special
        if len(error_msg) > max_length:
            error_msg = error_msg[: max_length - 3] + "..."
        error_msg_encoded = urllib.parse.quote(error_msg)

        # Verify special characters are properly encoded
        assert "<script>" not in error_msg_encoded, "HTML tags should be URL-encoded"
        assert urllib.parse.unquote(error_msg_encoded) == error_msg, "Decoded message should match original"
        assert "&" not in error_msg_encoded or "%26" in error_msg_encoded, "Ampersands should be encoded"
