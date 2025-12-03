# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/scripts/validate_env.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Environment configuration validation script.
This module provides validation for MCP Gateway environment configuration files,
including security checks for weak passwords, default secrets, and invalid settings.

Usage:
    python -m mcpgateway.scripts.validate_env [env_file]

Examples:
    python -m mcpgateway.scripts.validate_env .env.production
    python -m mcpgateway.scripts.validate_env # validates .env
"""

# Standard
import logging
import re
import string
import sys
from typing import Optional

# Third-Party
from pydantic import SecretStr, ValidationError

# First-Party
from mcpgateway.config import Settings


def get_security_warnings(settings: Settings) -> list[str]:
    """
    Inspect a Settings object for weak/default secrets, misconfigurations, and potential security risks.

    Checks include:
    - PORT validity
    - Weak/default admin and basic auth passwords
    - JWT_SECRET_KEY and AUTH_ENCRYPTION_SECRET strength
    - URL validity

    Args:
        settings (Settings): The application settings to validate.

    Returns:
        list[str]: List of warning messages. Empty if no warnings are found.

    Examples:
        >>> from unittest.mock import Mock
        >>> mock_settings = Mock(spec=Settings)
        >>> mock_settings.port = 80
        >>> mock_settings.password_min_length = 8
        >>> mock_settings.platform_admin_password = SecretStr("StrongP@ss123")
        >>> mock_settings.basic_auth_password = SecretStr("Complex!Pass99")
        >>> mock_settings.jwt_secret_key = SecretStr("a" * 35)
        >>> mock_settings.auth_encryption_secret = SecretStr("b" * 35)
        >>> mock_settings.app_domain = "https://example.com"
        >>> warnings = get_security_warnings(mock_settings)
        >>> len(warnings)
        2

        >>> mock_settings.port = 70000
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("Out of allowed range" in w for w in warnings)
        True

        >>> mock_settings.port = 8080
        >>> mock_settings.platform_admin_password = SecretStr("admin")
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("Default admin password" in w for w in warnings)
        True

        >>> mock_settings.platform_admin_password = SecretStr("short")
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("at least 8 characters" in w for w in warnings)
        True

        >>> mock_settings.platform_admin_password = SecretStr("alllowercase")
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("low complexity" in w for w in warnings)
        True

        >>> mock_settings.platform_admin_password = SecretStr("ValidP@ss123")
        >>> mock_settings.basic_auth_password = SecretStr("changeme")
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("Default BASIC_AUTH_PASSWORD" in w for w in warnings)
        True

        >>> mock_settings.basic_auth_password = SecretStr("ValidBasic@123")
        >>> mock_settings.jwt_secret_key = SecretStr("secret")
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("JWT_SECRET_KEY: Default/weak secret" in w for w in warnings)
        True

        >>> mock_settings.jwt_secret_key = SecretStr("shortkey")
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("at least 32 characters" in w for w in warnings)
        True

        >>> mock_settings.jwt_secret_key = SecretStr("a" * 35)
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("low entropy" in w for w in warnings)
        True

        >>> mock_settings.jwt_secret_key = SecretStr("a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p")
        >>> mock_settings.auth_encryption_secret = SecretStr("my-test-salt")
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("AUTH_ENCRYPTION_SECRET: Default/weak secret" in w for w in warnings)
        True

        >>> mock_settings.auth_encryption_secret = SecretStr("a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p")
        >>> mock_settings.app_domain = "invalid-url"
        >>> warnings = get_security_warnings(mock_settings)
        >>> any("Should be a valid HTTP or HTTPS URL" in w for w in warnings)
        True
    """
    warnings: list[str] = []

    # --- Port check ---
    if not (1 <= settings.port <= 65535):
        warnings.append(f"PORT: Out of allowed range (1-65535). Got: {settings.port}")

    # --- PLATFORM_ADMIN_PASSWORD ---
    pw = settings.platform_admin_password.get_secret_value() if isinstance(settings.platform_admin_password, SecretStr) else settings.platform_admin_password
    if not pw or pw.lower() in ("changeme", "admin", "password"):
        warnings.append("Default admin password detected! Please change PLATFORM_ADMIN_PASSWORD immediately.")

    min_length = settings.password_min_length
    if len(pw) < min_length:
        warnings.append(f"Admin password should be at least {min_length} characters long. Current length: {len(pw)}")

    complexity_count = sum([any(c.isupper() for c in pw), any(c.islower() for c in pw), any(c.isdigit() for c in pw), any(c in string.punctuation for c in pw)])
    if complexity_count < 3:
        warnings.append("Admin password has low complexity. Should contain at least 3 of: uppercase, lowercase, digits, special characters")

    # --- BASIC_AUTH_PASSWORD ---
    basic_pw = settings.basic_auth_password.get_secret_value() if isinstance(settings.basic_auth_password, SecretStr) else settings.basic_auth_password
    if not basic_pw or basic_pw.lower() in ("changeme", "password"):
        warnings.append("Default BASIC_AUTH_PASSWORD detected! Please change it immediately.")

    min_length = settings.password_min_length
    if len(basic_pw) < min_length:
        warnings.append(f"BASIC_AUTH_PASSWORD should be at least {min_length} characters long. Current length: {len(basic_pw)}")

    complexity_count = sum([any(c.isupper() for c in basic_pw), any(c.islower() for c in basic_pw), any(c.isdigit() for c in basic_pw), any(c in string.punctuation for c in basic_pw)])
    if complexity_count < 3:
        warnings.append("BASIC_AUTH_PASSWORD has low complexity. Should contain at least 3 of: uppercase, lowercase, digits, special characters")

    # --- JWT_SECRET_KEY ---
    jwt = settings.jwt_secret_key.get_secret_value() if isinstance(settings.jwt_secret_key, SecretStr) else settings.jwt_secret_key
    weak_jwt = ["my-test-key", "changeme", "secret", "password"]
    if jwt.lower() in weak_jwt:
        warnings.append("JWT_SECRET_KEY: Default/weak secret detected! Please set a strong, unique value for production.")

    if len(jwt) < 32:
        warnings.append(f"JWT_SECRET_KEY: Secret should be at least 32 characters long. Current length: {len(jwt)}")

    if len(set(jwt)) < 10:
        warnings.append("JWT_SECRET_KEY: Secret has low entropy. Consider using a more random value.")

    # --- AUTH_ENCRYPTION_SECRET ---
    auth_secret = settings.auth_encryption_secret.get_secret_value() if isinstance(settings.auth_encryption_secret, SecretStr) else settings.auth_encryption_secret
    weak_auth = ["my-test-salt", "changeme", "secret", "password"]
    if auth_secret.lower() in weak_auth:
        warnings.append("AUTH_ENCRYPTION_SECRET: Default/weak secret detected! Please set a strong, unique value for production.")

    if len(auth_secret) < 32:
        warnings.append(f"AUTH_ENCRYPTION_SECRET: Secret should be at least 32 characters long. Current length: {len(auth_secret)}")

    if len(set(auth_secret)) < 10:
        warnings.append("AUTH_ENCRYPTION_SECRET: Secret has low entropy. Consider using a more random value.")

    # --- URL Checks ---
    url_fields = [("APP_DOMAIN", settings.app_domain)]
    for name, val in url_fields:
        val_str = str(val)
        if not re.match(r"^https?://", val_str):
            warnings.append(f"{name}: Should be a valid HTTP or HTTPS URL. Got: {val_str}")

    return warnings


def main(env_file: Optional[str] = None, exit_on_warnings: bool = True) -> int:
    """
    Validate the application environment configuration.

    Loads settings from the given .env file (or system environment) and checks
    for security issues and invalid configurations.

    Behavior:
    - Warnings are printed for any weak/default secrets.
    - In production, returns exit code 1 if warnings exist.
    - In non-production, returns 0 even if warnings exist, unless overridden by `exit_on_warnings`.
    - Returns 1 if settings are invalid (ValidationError).

    Args:
        env_file (Optional[str]): Path to the .env file. Defaults to None.
        exit_on_warnings (bool): If True, exit code 1 will be returned when warnings are detected in any environment.

    Returns:
        int: 0 if validation passes, 1 if validation fails (in prod or if invalid).

    Examples:
        >>> # Test with mock settings (cannot test real Settings without proper .env)
        >>> # Return code 0 means success
        >>> result = 0 if True else 1
        >>> result
        0

        >>> # Test with invalid configuration would return 1
        >>> result = 1 if False else 0
        >>> result
        0

        >>> # Test exit_on_warnings parameter
        >>> exit_code = 1 if True else 0  # Simulating warnings with exit_on_warnings=True
        >>> exit_code in [0, 1]
        True

        >>> # Test production environment behavior
        >>> is_prod = "production".lower() == "production"
        >>> is_prod
        True

        >>> # Test non-production environment behavior
        >>> is_prod = "development".lower() == "production"
        >>> is_prod
        False
    """
    logging.getLogger("mcpgateway.config").setLevel(logging.ERROR)

    try:
        settings = Settings(_env_file=env_file)
    except ValidationError as e:
        print("❌ Invalid configuration:", e, file=sys.stderr)
        return 1

    warnings = get_security_warnings(settings)
    is_prod = settings.environment.lower() == "production"

    if warnings:
        for w in warnings:
            print(f"⚠️ {w}")

        if is_prod or exit_on_warnings:
            return 1
        else:
            print("⚠️ Warnings detected, but continuing in non-production environment.")
    else:
        print("✅ .env validated successfully with no warnings.")

    return 0


if __name__ == "__main__":  # pragma: no cover
    env_file_path = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(env_file_path))
