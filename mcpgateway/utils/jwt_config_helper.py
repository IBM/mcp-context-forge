# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/jwt_config_helper.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

JWT Configuration Helper Utilities.
This module provides JWT configuration validation and key retrieval functions.
"""

# Standard
from pathlib import Path

# First-Party
from mcpgateway.config import settings


class JWTConfigurationError(Exception):
    """Raised when JWT configuration is invalid or incomplete.

    Examples:
        >>> # Create a configuration error
        >>> error = JWTConfigurationError("Missing secret key")
        >>> str(error)
        'Missing secret key'
        >>> isinstance(error, Exception)
        True
    """


def validate_jwt_algo_and_keys() -> None:
    """Validate JWT algorithm and key configuration.

    Checks that the JWT configuration is valid:
    - For HMAC algorithms: jwt_secret_key must be set
    - For asymmetric algorithms: key files must exist and be readable

    Raises:
        JWTConfigurationError: If configuration is invalid
        FileNotFoundError: If key files don't exist
    """
    algorithm = settings.jwt_algorithm

    # HMAC algorithms (symmetric)
    if algorithm.startswith("HS"):
        # Handle SecretStr type from Pydantic v2
        secret_key = settings.jwt_secret_key.get_secret_value() if hasattr(settings.jwt_secret_key, "get_secret_value") else settings.jwt_secret_key
        if not secret_key:
            raise JWTConfigurationError(f"JWT algorithm {algorithm} requires jwt_secret_key to be set")
    # All other algorithms are asymmetric
    else:
        _validate_asymmetric_keys(algorithm)


def _validate_asymmetric_keys(algorithm: str) -> None:
    """Validate asymmetric key configuration.

    Args:
        algorithm: JWT algorithm being used

    Raises:
        JWTConfigurationError: If key paths are not configured
        FileNotFoundError: If key files don't exist
    """
    if not settings.jwt_public_key_path or not settings.jwt_private_key_path:
        raise JWTConfigurationError(f"JWT algorithm {algorithm} requires both jwt_public_key_path and jwt_private_key_path to be set")

    # Resolve paths
    public_key_path = Path(settings.jwt_public_key_path)
    private_key_path = Path(settings.jwt_private_key_path)

    if not public_key_path.is_absolute():
        public_key_path = Path.cwd() / public_key_path
    if not private_key_path.is_absolute():
        private_key_path = Path.cwd() / private_key_path

    if not public_key_path.is_file():
        raise JWTConfigurationError(f"JWT public key path is invalid: {public_key_path}")

    if not private_key_path.is_file():
        raise JWTConfigurationError(f"JWT private key path is invalid: {private_key_path}")


def get_jwt_private_key_or_secret() -> str:
    """Get signing key based on configured algorithm.

    Returns secret key for HMAC algorithms or private key content for asymmetric algorithms.

    Returns:
        str: The signing key as string

    Examples:
        >>> # Function returns a string key
        >>> result = get_jwt_private_key_or_secret()
        >>> isinstance(result, str)
        True
    """
    algorithm = settings.jwt_algorithm.upper()

    if algorithm.startswith("HS"):
        # Handle SecretStr type from Pydantic v2
        return settings.jwt_secret_key.get_secret_value() if hasattr(settings.jwt_secret_key, "get_secret_value") else settings.jwt_secret_key

    path = Path(settings.jwt_private_key_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    with open(path, "r") as f:
        return f.read()


def get_jwt_public_key_or_secret() -> str:
    """Get verification key based on configured algorithm.

    Returns secret key for HMAC algorithms or public key content for asymmetric algorithms.

    Returns:
        str: The verification key as string

    Examples:
        >>> # Function returns a string key
        >>> result = get_jwt_public_key_or_secret()
        >>> isinstance(result, str)
        True
    """
    algorithm = settings.jwt_algorithm.upper()

    if algorithm.startswith("HS"):
        # Handle SecretStr type from Pydantic v2
        return settings.jwt_secret_key.get_secret_value() if hasattr(settings.jwt_secret_key, "get_secret_value") else settings.jwt_secret_key

    path = Path(settings.jwt_public_key_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    with open(path, "r") as f:
        return f.read()
