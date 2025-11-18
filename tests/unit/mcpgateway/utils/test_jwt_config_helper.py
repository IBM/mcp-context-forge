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
