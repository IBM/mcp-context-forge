# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/jwt_config_helper.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

JWT Configuration Helper Utilities with caching.
This module provides JWT configuration validation and key retrieval functions.
Configuration is validated once and cached for performance.
Key files are cached with mtime tracking to avoid repeated disk I/O.
"""

# Standard
from functools import lru_cache
from pathlib import Path
from typing import Tuple

# First-Party
from mcpgateway.config import settings

# Cache for key file contents with mtime
# Key: (path, mtime), Value: key content
_key_file_cache: dict[Tuple[str, float], str] = {}


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


def _read_key_file_cached(path: Path) -> str:
    """Read key file with mtime-based caching.

    Args:
        path: Path to key file

    Returns:
        str: Key file contents

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If file cannot be read
    """
    try:
        path_str = str(path)
        mtime = path.stat().st_mtime

        # Check cache
        cache_key = (path_str, mtime)
        if cache_key in _key_file_cache:
            return _key_file_cache[cache_key]

        # Read file
        with open(path, "r") as f:
            content = f.read()

        # Clear old entries for this path and cache new content
        _key_file_cache.clear()
        _key_file_cache[cache_key] = content

        return content
    except Exception as e:
        raise IOError(f"Failed to read key file {path}: {e}") from e


@lru_cache(maxsize=1)
def _get_validated_config() -> str:
    """Validate and cache JWT configuration at first call.

    Returns:
        The validated algorithm string.

    Raises:
        JWTConfigurationError: If configuration is invalid
    """
    algorithm = settings.jwt_algorithm

    if algorithm.startswith("HS"):
        secret_key = settings.jwt_secret_key.get_secret_value() if hasattr(settings.jwt_secret_key, "get_secret_value") else settings.jwt_secret_key
        if not secret_key:
            raise JWTConfigurationError(f"JWT algorithm {algorithm} requires jwt_secret_key to be set")
    else:
        _validate_asymmetric_keys(algorithm)

    return algorithm


def validate_jwt_algo_and_keys() -> None:
    """Validate JWT algorithm and key configuration.

    This function is cached after first successful call. Subsequent calls
    are no-ops. Use clear_jwt_caches() to reset if configuration changes.

    Raises:
        JWTConfigurationError: If configuration is invalid
        FileNotFoundError: If key files don't exist
    """
    _get_validated_config()


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


@lru_cache(maxsize=1)
def get_jwt_private_key_or_secret() -> str:
    """Get signing key based on configured algorithm (cached).

    Returns secret key for HMAC algorithms or private key content for asymmetric algorithms.
    For file-based keys, content is cached with mtime tracking to avoid repeated disk I/O.

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
    return _read_key_file_cached(path)


@lru_cache(maxsize=1)
def get_jwt_public_key_or_secret() -> str:
    """Get verification key based on configured algorithm (cached).

    Returns secret key for HMAC algorithms or public key content for asymmetric algorithms.
    For file-based keys, content is cached with mtime tracking to avoid repeated disk I/O.

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
    return _read_key_file_cached(path)


def clear_jwt_caches() -> None:
    """Clear all JWT-related caches.

    Call this function:
    - In test fixtures to ensure test isolation
    - After config reload (if runtime config changes are supported)
    - After key rotation (if keys are rotated at runtime)

    Note: In production, JWT config/key changes require application restart.
    """
    _get_validated_config.cache_clear()
    get_jwt_public_key_or_secret.cache_clear()
    get_jwt_private_key_or_secret.cache_clear()
    _key_file_cache.clear()
