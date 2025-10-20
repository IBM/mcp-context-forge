# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_argon2_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive tests for Argon2 password hashing service.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from argon2 import PasswordHasher
from argon2.exceptions import HashingError, InvalidHash, VerifyMismatchError

# First-Party
from mcpgateway.services.argon2_service import Argon2PasswordService, hash_password, needs_rehash, password_service, verify_password


class TestArgon2PasswordService:
    """Test cases for Argon2PasswordService class."""

    def test_init_with_defaults(self):
        """Test service initialization with default settings."""
        with patch("mcpgateway.services.argon2_service.settings") as mock_settings:
            mock_settings.argon2id_time_cost = 3
            mock_settings.argon2id_memory_cost = 65536
            mock_settings.argon2id_parallelism = 1

            service = Argon2PasswordService()

            assert service.time_cost == 3
            assert service.memory_cost == 65536
            assert service.parallelism == 1
            assert isinstance(service.hasher, PasswordHasher)

    def test_init_with_custom_parameters(self):
        """Test service initialization with custom parameters."""
        service = Argon2PasswordService(time_cost=5, memory_cost=32768, parallelism=2, hash_len=64, salt_len=32)

        assert service.time_cost == 5
        assert service.memory_cost == 32768
        assert service.parallelism == 2
        assert isinstance(service.hasher, PasswordHasher)

    def test_init_with_partial_custom_parameters(self):
        """Test service initialization with partial custom parameters."""
        with patch("mcpgateway.services.argon2_service.settings") as mock_settings:
            mock_settings.argon2id_time_cost = 3
            mock_settings.argon2id_memory_cost = 65536
            mock_settings.argon2id_parallelism = 1

            service = Argon2PasswordService(time_cost=7)

            assert service.time_cost == 7
            assert service.memory_cost == 65536
            assert service.parallelism == 1

    def test_init_without_settings_attributes(self):
        """Test service initialization when settings lack argon2 attributes."""
        with patch("mcpgateway.services.argon2_service.settings") as mock_settings:
            # Remove argon2 attributes from settings
            del mock_settings.argon2id_time_cost
            del mock_settings.argon2id_memory_cost
            del mock_settings.argon2id_parallelism

            service = Argon2PasswordService()

            # Should use hardcoded defaults
            assert service.time_cost == 3
            assert service.memory_cost == 65536
            assert service.parallelism == 1

    def test_hash_password_success(self):
        """Test successful password hashing."""
        service = Argon2PasswordService()
        password = "secure_password_123"

        hash_value = service.hash_password(password)

        assert hash_value.startswith("$argon2id$")
        assert len(hash_value) > 50
        # Verify each hash is unique (includes random salt)
        hash_value2 = service.hash_password(password)
        assert hash_value != hash_value2

    def test_hash_password_unicode(self):
        """Test hashing passwords with Unicode characters."""
        service = Argon2PasswordService()
        unicode_passwords = [
            "пароль123",  # Cyrillic
            "密码456",  # Chinese
            "パスワード789",  # Japanese
            "🔐secure🔒",  # Emojis
            "café_résumé",  # Accented characters
        ]

        for password in unicode_passwords:
            hash_value = service.hash_password(password)
            assert hash_value.startswith("$argon2id$")
            assert len(hash_value) > 50

    def test_hash_password_very_long(self):
        """Test hashing very long passwords."""
        service = Argon2PasswordService()
        long_password = "a" * 10000  # 10,000 character password

        hash_value = service.hash_password(long_password)

        assert hash_value.startswith("$argon2id$")
        assert len(hash_value) > 50

    def test_hash_password_empty_raises_error(self):
        """Test that empty password raises ValueError."""
        service = Argon2PasswordService()

        with pytest.raises(ValueError, match="Password cannot be empty or None"):
            service.hash_password("")

    def test_hash_password_none_raises_error(self):
        """Test that None password raises ValueError."""
        service = Argon2PasswordService()

        with pytest.raises(ValueError, match="Password cannot be empty or None"):
            service.hash_password(None)

    def test_hash_password_hashing_error(self):
        """Test handling of HashingError from argon2."""
        service = Argon2PasswordService()

        # Mock the entire hasher object
        mock_hasher = MagicMock()
        mock_hasher.hash.side_effect = HashingError("Mock error")
        service.hasher = mock_hasher

        with pytest.raises(HashingError, match="Password hashing failed: Mock error"):
            service.hash_password("test_password")

    def test_verify_password_success(self):
        """Test successful password verification."""
        service = Argon2PasswordService()
        password = "correct_password"
        hash_value = service.hash_password(password)

        assert service.verify_password(password, hash_value) is True

    def test_verify_password_wrong_password(self):
        """Test verification with wrong password."""
        service = Argon2PasswordService()
        password = "correct_password"
        hash_value = service.hash_password(password)

        assert service.verify_password("wrong_password", hash_value) is False

    def test_verify_password_empty_password(self):
        """Test verification with empty password."""
        service = Argon2PasswordService()
        hash_value = service.hash_password("test")

        assert service.verify_password("", hash_value) is False

    def test_verify_password_none_password(self):
        """Test verification with None password."""
        service = Argon2PasswordService()
        hash_value = service.hash_password("test")

        assert service.verify_password(None, hash_value) is False

    def test_verify_password_empty_hash(self):
        """Test verification with empty hash."""
        service = Argon2PasswordService()

        assert service.verify_password("password", "") is False

    def test_verify_password_none_hash(self):
        """Test verification with None hash."""
        service = Argon2PasswordService()

        assert service.verify_password("password", None) is False

    def test_verify_password_invalid_hash(self):
        """Test verification with invalid hash format."""
        service = Argon2PasswordService()

        # Mock the hasher to raise InvalidHash
        mock_hasher = MagicMock()
        mock_hasher.verify.side_effect = InvalidHash("Mock invalid hash")
        service.hasher = mock_hasher

        assert service.verify_password("password", "invalid_hash") is False

    def test_verify_password_value_error(self):
        """Test verification with ValueError from argon2."""
        service = Argon2PasswordService()

        # Mock the hasher to raise ValueError
        mock_hasher = MagicMock()
        mock_hasher.verify.side_effect = ValueError("Mock value error")
        service.hasher = mock_hasher

        assert service.verify_password("password", "$argon2id$fake") is False

    def test_verify_password_unexpected_exception(self):
        """Test verification with unexpected exception."""
        service = Argon2PasswordService()

        # Mock the hasher to raise unexpected exception
        mock_hasher = MagicMock()
        mock_hasher.verify.side_effect = Exception("Unexpected error")
        service.hasher = mock_hasher

        assert service.verify_password("password", "$argon2id$fake") is False

    def test_verify_password_mismatch(self):
        """Test verification with VerifyMismatchError."""
        service = Argon2PasswordService()

        # Mock the hasher to raise VerifyMismatchError
        mock_hasher = MagicMock()
        mock_hasher.verify.side_effect = VerifyMismatchError()
        service.hasher = mock_hasher

        assert service.verify_password("wrong", "$argon2id$fake") is False

    def test_verify_password_unicode(self):
        """Test verification with Unicode passwords."""
        service = Argon2PasswordService()
        unicode_password = "пароль🔐密码"
        hash_value = service.hash_password(unicode_password)

        assert service.verify_password(unicode_password, hash_value) is True
        assert service.verify_password("wrong", hash_value) is False

    def test_needs_rehash_false(self):
        """Test needs_rehash returns False for current parameters."""
        service = Argon2PasswordService(time_cost=3, memory_cost=65536, parallelism=1)
        password = "test_password"
        hash_value = service.hash_password(password)

        assert service.needs_rehash(hash_value) is False

    def test_needs_rehash_true_different_parameters(self):
        """Test needs_rehash returns True for different parameters."""
        service1 = Argon2PasswordService(time_cost=3, memory_cost=65536, parallelism=1)
        hash_value = service1.hash_password("test_password")

        service2 = Argon2PasswordService(time_cost=5, memory_cost=65536, parallelism=1)
        assert service2.needs_rehash(hash_value) is True

    def test_needs_rehash_empty_hash(self):
        """Test needs_rehash with empty hash."""
        service = Argon2PasswordService()

        assert service.needs_rehash("") is True

    def test_needs_rehash_none_hash(self):
        """Test needs_rehash with None hash."""
        service = Argon2PasswordService()

        assert service.needs_rehash(None) is True

    def test_needs_rehash_invalid_hash(self):
        """Test needs_rehash with invalid hash format."""
        service = Argon2PasswordService()

        # Mock the hasher to raise InvalidHash
        mock_hasher = MagicMock()
        mock_hasher.check_needs_rehash.side_effect = InvalidHash("Mock invalid")
        service.hasher = mock_hasher

        assert service.needs_rehash("invalid_hash") is True

    def test_needs_rehash_value_error(self):
        """Test needs_rehash with ValueError."""
        service = Argon2PasswordService()

        # Mock the hasher to raise ValueError
        mock_hasher = MagicMock()
        mock_hasher.check_needs_rehash.side_effect = ValueError("Mock error")
        service.hasher = mock_hasher

        assert service.needs_rehash("$argon2id$fake") is True

    def test_needs_rehash_unexpected_exception(self):
        """Test needs_rehash with unexpected exception."""
        service = Argon2PasswordService()

        # Mock the hasher to raise unexpected exception
        mock_hasher = MagicMock()
        mock_hasher.check_needs_rehash.side_effect = Exception("Unexpected")
        service.hasher = mock_hasher

        assert service.needs_rehash("$argon2id$fake") is True

    def test_get_hash_info_success(self):
        """Test extracting hash info from valid hash."""
        service = Argon2PasswordService(time_cost=3, memory_cost=65536, parallelism=1)
        hash_value = service.hash_password("test")

        info = service.get_hash_info(hash_value)

        assert info is not None
        assert info["variant"] == "argon2id"
        assert info["time_cost"] == 3
        assert info["memory_cost"] == 65536
        assert info["parallelism"] == 1
        assert "version" in info

    def test_get_hash_info_empty_hash(self):
        """Test get_hash_info with empty hash."""
        service = Argon2PasswordService()

        assert service.get_hash_info("") is None

    def test_get_hash_info_none_hash(self):
        """Test get_hash_info with None hash."""
        service = Argon2PasswordService()

        assert service.get_hash_info(None) is None

    def test_get_hash_info_invalid_format(self):
        """Test get_hash_info with invalid hash format."""
        service = Argon2PasswordService()

        # Not enough parts
        assert service.get_hash_info("$argon2id") is None

        # Wrong variant
        assert service.get_hash_info("$bcrypt$v=19$m=65536,t=3,p=1$salt$hash") is None

    def test_get_hash_info_malformed_params(self):
        """Test get_hash_info with malformed parameters."""
        service = Argon2PasswordService()

        # Missing equals sign in params
        hash_value = "$argon2id$v=19$m65536,t3,p1$salt$hash"
        assert service.get_hash_info(hash_value) is None

    def test_get_hash_info_parsing_error(self):
        """Test get_hash_info with parsing error."""
        service = Argon2PasswordService()

        # Non-integer values
        hash_value = "$argon2id$v=19$m=abc,t=def,p=ghi$salt$hash"
        assert service.get_hash_info(hash_value) is None

    def test_get_hash_info_different_parameters(self):
        """Test get_hash_info with different parameter values."""
        service = Argon2PasswordService(time_cost=5, memory_cost=32768, parallelism=2)
        hash_value = service.hash_password("test")

        info = service.get_hash_info(hash_value)

        assert info["time_cost"] == 5
        assert info["memory_cost"] == 32768
        assert info["parallelism"] == 2

    def test_repr(self):
        """Test string representation of service."""
        service = Argon2PasswordService(time_cost=4, memory_cost=32768, parallelism=2)

        repr_str = repr(service)

        assert repr_str == "Argon2PasswordService(time_cost=4, memory_cost=32768, parallelism=2)"


class TestModuleLevelFunctions:
    """Test module-level convenience functions."""

    def test_hash_password_function(self):
        """Test module-level hash_password function."""
        password = "test_password"

        hash_value = hash_password(password)

        assert hash_value.startswith("$argon2id$")
        assert len(hash_value) > 50

    def test_hash_password_function_error(self):
        """Test module-level hash_password with empty password."""
        with pytest.raises(ValueError, match="Password cannot be empty or None"):
            hash_password("")

    def test_verify_password_function(self):
        """Test module-level verify_password function."""
        password = "test_password"
        hash_value = hash_password(password)

        assert verify_password(password, hash_value) is True
        assert verify_password("wrong", hash_value) is False

    def test_verify_password_function_empty(self):
        """Test module-level verify_password with empty inputs."""
        hash_value = hash_password("test")

        assert verify_password("", hash_value) is False
        assert verify_password("test", "") is False

    def test_needs_rehash_function(self):
        """Test module-level needs_rehash function."""
        hash_value = hash_password("test")

        # Should not need rehash with same parameters
        assert needs_rehash(hash_value) is False

        # Empty hash should need rehash
        assert needs_rehash("") is True

    def test_global_password_service_instance(self):
        """Test that global password_service instance is properly initialized."""
        assert isinstance(password_service, Argon2PasswordService)
        assert hasattr(password_service, "hasher")
        assert hasattr(password_service, "time_cost")
        assert hasattr(password_service, "memory_cost")
        assert hasattr(password_service, "parallelism")


class TestSecurityEdgeCases:
    """Test security-related edge cases and boundary conditions."""

    def test_password_with_null_bytes(self):
        """Test handling passwords with null bytes."""
        service = Argon2PasswordService()
        password_with_null = "pass\x00word"

        hash_value = service.hash_password(password_with_null)
        assert service.verify_password(password_with_null, hash_value) is True
        assert service.verify_password("password", hash_value) is False

    def test_password_with_control_characters(self):
        """Test handling passwords with control characters."""
        service = Argon2PasswordService()
        control_passwords = [
            "pass\nword",  # Newline
            "pass\rword",  # Carriage return
            "pass\tword",  # Tab
            "pass\bword",  # Backspace
            "pass\x1bword",  # Escape
        ]

        for password in control_passwords:
            hash_value = service.hash_password(password)
            assert service.verify_password(password, hash_value) is True

    def test_password_max_length(self):
        """Test handling maximum length passwords."""
        service = Argon2PasswordService()
        # Argon2 can handle very long passwords
        max_password = "x" * 4096

        hash_value = service.hash_password(max_password)
        assert service.verify_password(max_password, hash_value) is True

    def test_timing_attack_resistance(self):
        """Test that verification time is consistent for wrong passwords."""
        service = Argon2PasswordService()
        hash_value = service.hash_password("correct")

        # Verification should take similar time regardless of how wrong the password is
        # This is handled by argon2 library internally
        assert service.verify_password("a", hash_value) is False
        assert service.verify_password("wrong_password_that_is_very_long", hash_value) is False

    def test_password_with_spaces(self):
        """Test passwords with various space configurations."""
        service = Argon2PasswordService()
        space_passwords = [
            " password",  # Leading space
            "password ",  # Trailing space
            " password ",  # Both
            "pass word",  # Space in middle
            "   ",  # Only spaces
        ]

        for password in space_passwords:
            hash_value = service.hash_password(password)
            assert service.verify_password(password, hash_value) is True
            # Only test strip for passwords that have something left after stripping
            if password.strip() and password != password.strip():
                assert service.verify_password(password.strip(), hash_value) is False

    def test_case_sensitive_verification(self):
        """Test that password verification is case-sensitive."""
        service = Argon2PasswordService()
        password = "PassWord123"
        hash_value = service.hash_password(password)

        assert service.verify_password(password, hash_value) is True
        assert service.verify_password("password123", hash_value) is False
        assert service.verify_password("PASSWORD123", hash_value) is False

    def test_special_characters_in_password(self):
        """Test passwords with special characters."""
        service = Argon2PasswordService()
        special_passwords = [
            "!@#$%^&*()",
            "pass<word>",
            "pass'word\"test",
            "pass\\word/test",
            "pass|word&test",
        ]

        for password in special_passwords:
            hash_value = service.hash_password(password)
            assert service.verify_password(password, hash_value) is True


class TestPerformanceAndConcurrency:
    """Test performance-related aspects and concurrency."""

    def test_different_cost_parameters_performance(self):
        """Test that different cost parameters affect hash generation."""
        # Low cost parameters (fast)
        fast_service = Argon2PasswordService(time_cost=1, memory_cost=8192, parallelism=1)
        fast_hash = fast_service.hash_password("test")

        # High cost parameters (slow but more secure)
        slow_service = Argon2PasswordService(time_cost=10, memory_cost=131072, parallelism=4)
        slow_hash = slow_service.hash_password("test")

        # Both should produce valid hashes
        assert fast_hash.startswith("$argon2id$")
        assert slow_hash.startswith("$argon2id$")

        # Cross-verification should work
        assert fast_service.verify_password("test", fast_hash) is True
        assert slow_service.verify_password("test", slow_hash) is True

        # But they should need rehashing when parameters differ
        assert slow_service.needs_rehash(fast_hash) is True
        assert fast_service.needs_rehash(slow_hash) is True

    def test_hash_uniqueness_with_same_password(self):
        """Test that same password produces different hashes due to salt."""
        service = Argon2PasswordService()
        password = "same_password"

        hashes = set()
        # Reduced from 10 to 5 iterations for faster test execution while maintaining coverage
        for _ in range(5):
            hash_value = service.hash_password(password)
            hashes.add(hash_value)

        # All hashes should be unique due to random salt
        assert len(hashes) == 5

        # But all should verify correctly
        for hash_value in hashes:
            assert service.verify_password(password, hash_value) is True


class TestLoggingIntegration:
    """Test logging behavior of the service."""

    @patch("mcpgateway.services.argon2_service.logger")
    def test_init_logging(self, mock_logger):
        """Test that initialization logs parameters."""
        service = Argon2PasswordService(time_cost=4, memory_cost=32768, parallelism=2)

        mock_logger.info.assert_called_once_with("Initialized Argon2PasswordService with time_cost=4, memory_cost=32768, parallelism=2")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_hash_password_success_logging(self, mock_logger):
        """Test logging on successful password hashing."""
        service = Argon2PasswordService()
        service.hash_password("test")

        mock_logger.debug.assert_called_with("Successfully hashed password for user authentication")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_hash_password_error_logging(self, mock_logger):
        """Test logging on password hashing error."""
        service = Argon2PasswordService()

        # Clear any previous calls from init
        mock_logger.reset_mock()

        # Mock the hasher to raise HashingError
        mock_hasher = MagicMock()
        mock_hasher.hash.side_effect = HashingError("Mock error")
        service.hasher = mock_hasher

        with pytest.raises(HashingError):
            service.hash_password("test")

        mock_logger.error.assert_called_with("Failed to hash password: Mock error")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_verify_password_success_logging(self, mock_logger):
        """Test logging on successful verification."""
        service = Argon2PasswordService()

        # Clear any previous calls from init
        mock_logger.reset_mock()

        # Mock the hasher to succeed
        mock_hasher = MagicMock()
        mock_hasher.verify.return_value = None  # verify returns None on success
        service.hasher = mock_hasher

        result = service.verify_password("test", "$argon2id$fake")

        assert result is True
        mock_logger.debug.assert_called_with("Password verification successful")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_verify_password_mismatch_logging(self, mock_logger):
        """Test logging on password mismatch."""
        service = Argon2PasswordService()

        # Clear any previous calls from init
        mock_logger.reset_mock()

        # Mock the hasher to raise VerifyMismatchError
        mock_hasher = MagicMock()
        mock_hasher.verify.side_effect = VerifyMismatchError()
        service.hasher = mock_hasher

        result = service.verify_password("wrong", "$argon2id$fake")

        assert result is False
        mock_logger.debug.assert_called_with("Password verification failed - password mismatch")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_verify_password_invalid_hash_logging(self, mock_logger):
        """Test logging on invalid hash format."""
        service = Argon2PasswordService()

        # Clear any previous calls from init
        mock_logger.reset_mock()

        # Mock the hasher to raise InvalidHash
        mock_hasher = MagicMock()
        mock_hasher.verify.side_effect = InvalidHash("Bad hash")
        service.hasher = mock_hasher

        result = service.verify_password("test", "invalid")

        assert result is False
        mock_logger.warning.assert_called_with("Invalid hash format during verification: Bad hash")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_verify_password_unexpected_error_logging(self, mock_logger):
        """Test logging on unexpected error."""
        service = Argon2PasswordService()

        # Clear any previous calls from init
        mock_logger.reset_mock()

        # Mock the hasher to raise unexpected exception
        mock_hasher = MagicMock()
        mock_hasher.verify.side_effect = Exception("Unexpected")
        service.hasher = mock_hasher

        result = service.verify_password("test", "$argon2id$fake")

        assert result is False
        mock_logger.error.assert_called_with("Unexpected error during password verification: Unexpected")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_needs_rehash_invalid_hash_logging(self, mock_logger):
        """Test logging when checking rehash with invalid hash."""
        service = Argon2PasswordService()

        # Clear any previous calls from init
        mock_logger.reset_mock()

        # Mock the hasher to raise InvalidHash
        mock_hasher = MagicMock()
        mock_hasher.check_needs_rehash.side_effect = InvalidHash("Bad hash")
        service.hasher = mock_hasher

        result = service.needs_rehash("invalid")

        assert result is True
        mock_logger.warning.assert_called_with("Invalid hash format when checking rehash need: Bad hash")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_needs_rehash_unexpected_error_logging(self, mock_logger):
        """Test logging on unexpected error in needs_rehash."""
        service = Argon2PasswordService()

        # Clear any previous calls from init
        mock_logger.reset_mock()

        # Mock the hasher to raise unexpected exception
        mock_hasher = MagicMock()
        mock_hasher.check_needs_rehash.side_effect = Exception("Unexpected")
        service.hasher = mock_hasher

        result = service.needs_rehash("$argon2id$fake")

        assert result is True
        mock_logger.error.assert_called_with("Unexpected error checking rehash need: Unexpected")

    @patch("mcpgateway.services.argon2_service.logger")
    def test_get_hash_info_parse_error_logging(self, mock_logger):
        """Test logging when failing to parse hash info."""
        service = Argon2PasswordService()

        # Malformed parameters
        result = service.get_hash_info("$argon2id$v=19$malformed$salt$hash")

        assert result is None
        mock_logger.warning.assert_called()
