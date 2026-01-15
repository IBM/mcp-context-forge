# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_jwt_config_helper.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit Tests for jwt config helper .
"""
import io
import pytest
from unittest.mock import patch
from pathlib import Path
from typing import Any

from mcpgateway.utils.jwt_config_helper import (
    JWTConfigurationError,
    validate_jwt_algo_and_keys,
    get_jwt_private_key_or_secret,
    get_jwt_public_key_or_secret,
)

@pytest.fixture
def mock_settings():
    class MockSettings:
        jwt_algorithm = "HS256"
        jwt_secret_key = "supersecret"
        jwt_public_key_path = "public.pem"
        jwt_private_key_path = "private.pem"
    return MockSettings()

def test_validate_hmac_algorithm_valid_secret(mock_settings: Any):
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        validate_jwt_algo_and_keys()  # should not raise

def test_validate_hmac_algorithm_missing_secret(mock_settings: Any):
    mock_settings.jwt_secret_key = ""
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        with pytest.raises(JWTConfigurationError):
            validate_jwt_algo_and_keys()

def test_validate_asymmetric_missing_paths(mock_settings: Any):
    mock_settings.jwt_algorithm = "RS256"
    mock_settings.jwt_public_key_path = None
    mock_settings.jwt_private_key_path = None
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        with pytest.raises(JWTConfigurationError):
            validate_jwt_algo_and_keys()

def test_validate_asymmetric_invalid_public_key(mock_settings: Any):
    mock_settings.jwt_algorithm = "RS256"
    mock_settings.jwt_public_key_path = "nonexistent_pub.pem"
    mock_settings.jwt_private_key_path = "nonexistent_priv.pem"
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        with patch.object(Path, "is_absolute", return_value=True):
            with patch.object(Path, "is_file", return_value=False):
                with pytest.raises(JWTConfigurationError):
                    validate_jwt_algo_and_keys()

def test_validate_asymmetric_invalid_private_key(mock_settings: Any):
    mock_settings.jwt_algorithm = "RS256"
    mock_settings.jwt_public_key_path = "public.pem"
    mock_settings.jwt_private_key_path = "private.pem"
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        with patch.object(Path, "is_absolute", return_value=True):
            with patch.object(Path, "is_file", side_effect=[True, False]):
                with pytest.raises(JWTConfigurationError):
                    validate_jwt_algo_and_keys()

def test_validate_asymmetric_valid_keys(mock_settings: Any):
    mock_settings.jwt_algorithm = "RS256"
    mock_settings.jwt_public_key_path = "public.pem"
    mock_settings.jwt_private_key_path = "private.pem"
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        with patch.object(Path, "is_absolute", return_value=True):
            with patch.object(Path, "is_file", return_value=True):
                validate_jwt_algo_and_keys()  # should not raise

def test_get_private_key_or_secret_hmac(mock_settings: Any):
    mock_settings.jwt_algorithm = "HS512"
    mock_settings.jwt_secret_key = "hmacsecret"
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        result = get_jwt_private_key_or_secret()
        assert result == "hmacsecret"

def test_get_private_key_or_secret_asymmetric(mock_settings: Any):
    mock_settings.jwt_algorithm = "RS256"
    mock_settings.jwt_private_key_path = "private.pem"
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        with patch.object(Path, "is_absolute", return_value=True):
            # Mock stat() to return fake mtime for caching
            mock_stat = type('obj', (object,), {'st_mtime': 123456.0})
            with patch.object(Path, "stat", return_value=mock_stat):
                with patch("builtins.open", return_value=io.StringIO("PRIVATE_KEY_CONTENT")):
                    result = get_jwt_private_key_or_secret()
                    assert result == "PRIVATE_KEY_CONTENT"

def test_get_public_key_or_secret_hmac(mock_settings: Any):
    mock_settings.jwt_algorithm = "HS256"
    mock_settings.jwt_secret_key = "sharedsecret"
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        result = get_jwt_public_key_or_secret()
        assert result == "sharedsecret"

def test_get_public_key_or_secret_asymmetric(mock_settings: Any):
    mock_settings.jwt_algorithm = "RS256"
    mock_settings.jwt_public_key_path = "public.pem"
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        with patch.object(Path, "is_absolute", return_value=True):
            # Mock stat() to return fake mtime for caching
            mock_stat = type('obj', (object,), {'st_mtime': 123456.0})
            with patch.object(Path, "stat", return_value=mock_stat):
                with patch("builtins.open", return_value=io.StringIO("PUBLIC_KEY_CONTENT")):
                    result = get_jwt_public_key_or_secret()
                    assert result == "PUBLIC_KEY_CONTENT"

def test_secretstr_handling_hmac(mock_settings: Any):
    class SecretStr:
        def get_secret_value(self):
            return "secret_from_pydantic"
    mock_settings.jwt_algorithm = "HS256"
    mock_settings.jwt_secret_key = SecretStr()
    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        result = get_jwt_private_key_or_secret()
        assert result == "secret_from_pydantic"


# ---------------------------------------------------------------------------
# Cache behavior tests
# ---------------------------------------------------------------------------

def test_validate_jwt_algo_and_keys_is_cached(mock_settings: Any):
    """Verify that validation is only performed once."""
    from mcpgateway.utils.jwt_config_helper import clear_jwt_caches
    clear_jwt_caches()

    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        # First call should validate
        validate_jwt_algo_and_keys()

        # Change settings to invalid - should NOT raise because cached
        mock_settings.jwt_secret_key = ""

        # This should still succeed (cached)
        validate_jwt_algo_and_keys()


def test_clear_jwt_caches_resets_validation(mock_settings: Any):
    """Verify that clear_jwt_caches() forces revalidation."""
    from mcpgateway.utils.jwt_config_helper import clear_jwt_caches

    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        validate_jwt_algo_and_keys()

        # Clear cache
        clear_jwt_caches()

        # Change to invalid
        mock_settings.jwt_secret_key = ""

        # Now it should raise
        with pytest.raises(JWTConfigurationError):
            validate_jwt_algo_and_keys()


def test_get_jwt_public_key_or_secret_is_cached(mock_settings: Any):
    """Verify that key retrieval is cached."""
    from mcpgateway.utils.jwt_config_helper import clear_jwt_caches
    clear_jwt_caches()

    mock_settings.jwt_algorithm = "HS256"
    mock_settings.jwt_secret_key = "original_secret"

    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        result1 = get_jwt_public_key_or_secret()
        assert result1 == "original_secret"

        # Change secret - should return cached value
        mock_settings.jwt_secret_key = "new_secret"
        result2 = get_jwt_public_key_or_secret()
        assert result2 == "original_secret"  # Still cached


def test_get_jwt_private_key_or_secret_is_cached(mock_settings: Any):
    """Verify that private key retrieval is cached."""
    from mcpgateway.utils.jwt_config_helper import clear_jwt_caches
    clear_jwt_caches()

    mock_settings.jwt_algorithm = "HS256"
    mock_settings.jwt_secret_key = "original_private_secret"

    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        result1 = get_jwt_private_key_or_secret()
        assert result1 == "original_private_secret"


def test_clear_jwt_caches():
    """Verify that clearing caches works correctly."""
    from mcpgateway.utils.jwt_config_helper import clear_jwt_caches

    class MockSettings:
        jwt_algorithm = "HS256"
        jwt_secret_key = "test_secret"

    with patch("mcpgateway.utils.jwt_config_helper.settings", MockSettings()):
        # Warm up cache
        get_jwt_public_key_or_secret()
        get_jwt_private_key_or_secret()

        # Clear caches
        clear_jwt_caches()

        # Should still work after clearing
        result = get_jwt_public_key_or_secret()
        assert result == "test_secret"


def test_key_file_caching_with_mtime(mock_settings: Any):
    """Verify that key files are cached based on mtime."""
    from mcpgateway.utils.jwt_config_helper import clear_jwt_caches
    clear_jwt_caches()

    mock_settings.jwt_algorithm = "RS256"
    mock_settings.jwt_public_key_path = "public.pem"

    with patch("mcpgateway.utils.jwt_config_helper.settings", mock_settings):
        with patch.object(Path, "is_absolute", return_value=True):
            mock_stat = type('obj', (object,), {'st_mtime': 123456.0})
            with patch.object(Path, "stat", return_value=mock_stat):
                # First call - reads from file
                with patch("builtins.open", return_value=io.StringIO("KEY_CONTENT_1")) as mock_open:
                    result1 = get_jwt_public_key_or_secret()
                    assert result1 == "KEY_CONTENT_1"
                    assert mock_open.call_count == 1

                # Second call - should use cache (no file read)
                with patch("builtins.open", return_value=io.StringIO("KEY_CONTENT_2")) as mock_open:
                    result2 = get_jwt_public_key_or_secret()
                    assert result2 == "KEY_CONTENT_1"  # Still cached
                    assert mock_open.call_count == 0  # No file read
